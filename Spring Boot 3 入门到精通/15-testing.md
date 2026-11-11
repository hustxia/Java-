# 第 15 章 单元测试与集成测试

## 本章目标

读完本章你将掌握：

- 在 Spring Boot 3 项目中用 **JUnit 5** 编写单元测试，理解它与 JUnit 4 的关键差异；
- 用 **@SpringBootTest** 拉起完整（或随机端口）Spring 上下文做集成测试；
- 用 **@WebMvcTest + MockMvc** 做「只加载 Web 层」的切片测试，又快又隔离；
- 了解 **@DataJpaTest** 与 **Testcontainers**，应对持久层与真实中间件的测试；
- 用 **@ActiveProfiles** 与专用 `application-test.yml` 让测试配置与线上解耦。

本章所有「真实片段」均取自本书贯穿案例 codegen-server（`D:/workspace/xyh-devbranch/codegen-server`），源文件见文中标注。

## 15.1 测试依赖与构建门槛

Spring Boot 3 以 `spring-boot-starter-test` 一站式带来 JUnit 5（`junit-jupiter`）、Mockito、AssertJ、Hamcrest、`spring-test` 等。codegen-server 的依赖声明如下（来源 `pom.xml`）：

```xml
<!-- 来源：pom.xml -->
<dependency>
    <groupId>org.springframework.boot</groupId>
    <artifactId>spring-boot-starter-test</artifactId>
    <scope>test</scope>
</dependency>
```

构建配置上有两个容易被忽视的「门禁」开关（来源 `pom.xml` 的 `maven-surefire-plugin`）：

```xml
<!-- 来源：pom.xml，maven-surefire-plugin 配置 -->
<plugin>
    <groupId>org.apache.maven.plugins</groupId>
    <artifactId>maven-surefire-plugin</artifactId>
    <version>3.5.4</version>
    <configuration>
        <!-- 测试数为 0 必须失败，避免「版本错配导致一个用例都没跑却 BUILD SUCCESS」 -->
        <failIfNoTests>true</failIfNoTests>
    </configuration>
</plugin>
```

`failIfNoTests=true` 是本工程在踩过「surefire 版本错配导致用例全被静默跳过、却仍 BUILD SUCCESS」的坑后立的规矩：**没有任何用例跑起来，CI 必须红**。这一点对单体工程尤为关键——你以为测试通过了，其实根本没执行。

> ⚠️ 踩坑提示：`spring-boot-starter-test` 只管「引入依赖」，不保证 surefire 版本与 JDK 21 兼容。若本地用 JDK 21 却跑出「no tests executed / 0 tests」，优先把 surefire 钉到 3.x 较新版本（codegen 钉 `3.5.4`），并确认 `junit-platform-launcher` 在依赖里，否则 IDE/命令行都可能「假装跑过」。

## 15.2 JUnit 5 基础：纯函数与边界测试

并非所有测试都需要 Spring 上下文。对纯逻辑（路径安全、模板渲染、算法）直接写 JUnit 5 用例，秒级返回、零启动成本。codegen-server 的脚手架路径越界防线就是典型（来源 `src/test/java/com/codegen/service/impl/GenScaffoldPathSafetyTest.java`）：

```java
// 来源：src/test/java/com/codegen/service/impl/GenScaffoldPathSafetyTest.java（节选）
@DisplayName("脚手架写盘路径越界防线")
class GenScaffoldPathSafetyTest {

    @Test
    @DisplayName("模块名拒绝 ../、绝对路径、分隔符与空值")
    void moduleMustBeSingleSegment() {
        // 各种注入式非法输入
        for (String bad : new String[]{"../../tmp/pwn", "..", ".", "",
                "a/b", "a\\b", "C:/Windows/Temp/pwn", "server;rm"}) {
            assertThrows(BusinessException.class,
                    () -> GenScaffoldServiceImpl.safeModule(bad),
                    "应拒绝的模块名：" + bad);   // 断言「一定会抛异常」
        }
        assertEquals("demo-server", GenScaffoldServiceImpl.safeModule(" demo-server "));
    }
}
```

JUnit 5 与 JUnit 4 的核心差异：`@Test` 来自 `org.junit.jupiter.api`，不再要求方法 `public`、无 `throws Exception` 限制；断言来自 `org.junit.jupiter.api.Assertions`（`assertThrows` / `assertEquals` / `assertTrue` 等）；生命周期注解是 `@BeforeEach` / `@AfterEach` / `@BeforeAll`（静态）而非 `@Before` / `@After`。

## 15.3 @SpringBootTest：集成测试

当被测逻辑依赖 Spring 装配（注入 `MeterRegistry`、读配置、跑真实 HTTP），用 `@SpringBootTest` 拉起上下文。codegen 排查 Prometheus 直方图是否生效时写了这样一个探针（来源 `src/test/java/com/codegen/monitor/HistogramConfigProbeTest.java`）：

```java
// 来源：src/test/java/com/codegen/monitor/HistogramConfigProbeTest.java（节选）
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
class HistogramConfigProbeTest {

    @LocalServerPort                       // 注入随机端口，避免与 8120 冲突
    private int port;

    @Autowired(required = false)           // 非必须，缺失不报错
    private MeterRegistry registry;

    @Test
    void httpServerRequestsHasHistogramBuckets() {
        // 真正打一次 actuator/health，让 http.server.requests 产生样本
        new RestTemplate().getForEntity(
                "http://localhost:" + port + "/actuator/health", String.class);
        var timers = registry.find("http.server.requests").timers();
        assertFalse(timers.isEmpty());
        assertTrue(bucketBounds > 0, "http.server.requests 直方图桶为空，percentiles-histogram 未生效");
    }
}
```

`webEnvironment` 三种常用取值：

- `MOCK`（默认）：不启真实 Web 服务器，走 Mock Servlet 容器，配合 `MockMvc` 用；
- `RANDOM_PORT`：启动真实 Tomcat 并监听随机端口，`@LocalServerPort` 取端口，适合端到端；
- `DEFINED_PORT`：用 `server.port` 指定的固定端口。

⚠️ 集成测试会加载整个应用上下文，**慢且重**。生产项目里它应只占测试金字塔的尖顶，绝大多数覆盖由切片测试和纯单元测试承担。

## 15.4 @WebMvcTest + MockMvc：Web 层切片测试

`@WebMvcTest` 只加载 Web 相关 Bean（Controller、Filter、Converter），**不加载 Service/Repository**，需要什么协作者用 `@MockBean` 注入。下面的写法是「通用示例」（codegen 的 `MonitorControllerTest` 用 `MockMvcBuilders.standaloneSetup` 而非 `@WebMvcTest`，二者等价，后者更接近框架原生切片）：

```java
// 此为通用示例：@WebMvcTest 切片测试骨架
@WebMvcTest(MonitorController.class)          // 只装配 Web 层，不拉全上下文
class MonitorControllerSliceTest {

    @Autowired MockMvc mvc;                   // 由 @AutoConfigureMockMvc 提供
    @MockBean MonitorStore store;             // 协作者全部打桩
    @MockBean PermissionService permissionService;

    @Test
    void overviewReturns403WhenNoPermission() throws Exception {
        when(permissionService.isSuperAdmin(anyLong())).thenReturn(false);
        when(permissionService.permissionsOf(anyLong())).thenReturn(Set.of());
        mvc.perform(get("/monitor/overview"))
           .andExpect(status().isForbidden());   // 期望 403
    }
}
```

codegen 真实采用 standalone MockMvc（来源 `src/test/java/com/codegen/controller/MonitorControllerTest.java`），优点是不依赖任何 Spring 装配、直接吃控制器的 `@ExceptionHandler`：

```java
// 来源：src/test/java/com/codegen/controller/MonitorControllerTest.java（节选）
@ExtendWith(MockitoExtension.class)              // JUnit 5 + Mockito 扩展
class MonitorControllerTest {
    @Mock MonitorStore store;
    @InjectMocks MonitorController controller;   // 把 mock 注入被测对象
    private MockMvc mvc;

    @BeforeEach void setUp() {
        mvc = MockMvcBuilders.standaloneSetup(controller).build();
    }

    @Test
    void invalidMetricReturns400() throws Exception {
        mvc.perform(get("/monitor/series").param("metric", "evil"))
           .andExpect(status().is(400));          // 非法 metric → 400
    }

    @Test
    void deniedWithoutViewPermissionReturns403() throws Exception {
        when(permissionService.isSuperAdmin(UID)).thenReturn(false);
        when(permissionService.permissionsOf(UID)).thenReturn(Collections.emptySet());
        mvc.perform(get("/monitor/overview")).andExpect(status().isForbidden());
    }
}
```

## 15.5 @DataJpaTest 与 Testcontainers

`@DataJpaTest` 只加载 JPA 相关 Bean，自动配置嵌入式或测试库，事务默认回滚，适合仓储层。以下为**通用示例**：

```java
// 此为通用示例：@DataJpaTest 切片测试仓储层
@DataJpaTest
@TestPropertySource(properties = "spring.jpa.hibernate.ddl-auto=create-drop")
class SysDocRepositoryTest {
    @Autowired SysDocMapper mapper;            // MyBatis-Plus 不归 JPA 管，此处示意 Repository 接口

    @Test
    void insertAndFind() {
        // 断言插入后可查回；方法结束自动回滚，不留脏数据
    }
}
```

当被测逻辑依赖**真实** MySQL / Redis 等中间件时，用 Testcontainers 起一个临时容器，既保真又不被环境绑架（**通用示例**）：

```java
// 此为通用示例：Testcontainers 起真实 MySQL
@Testcontainers
@SpringBootTest
class OrderRepositoryContainerTest {

    @Container
    static MySQLContainer<?> mysql = new MySQLContainer<>("mysql:8.0")
            .withDatabaseName("gen_platform_test");

    @DynamicPropertySource          // 把容器随机端口注入 Spring 环境
    static void props(DynamicPropertyRegistry r) {
        r.add("spring.datasource.url", mysql::getJdbcUrl);
        r.add("spring.datasource.username", mysql::getUsername);
        r.add("spring.datasource.password", mysql::getPassword);
    }
}
```

## 15.6 测试配置与 @ActiveProfiles

测试绝不能直接连开发库——codegen 的契约测试会 `DROP/CREATE` 表，连到 `gen_platform` 就是删开发库。因此用专用 profile 隔离（来源 `src/test/resources/application-test.yml`）：

```yaml
# 来源：src/test/resources/application-test.yml
spring:
  datasource:
    # 库名必须带 _test —— 契约测试会重建表，连到 gen_platform 就是删开发库
    url: jdbc:mysql://localhost:3306/gen_platform_test?createDatabaseIfNotExist=true&...
    username: root
    password: root
  sql:
    init:
      mode: always
      schema-locations: classpath:schema-test.sql   # 每次启动重建 schema
gen:
  output:
    backend-root: ${java.io.tmpdir}/gen-contract-fallback   # 兜底写盘路径
    selfcheck:
      compile-enabled: false                        # 测试环境不做 javac 编译自检
```

激活方式：在测试类加 `@ActiveProfiles("test")`，或在 `application.yml` 里 `spring.profiles.include` 叠加。codegen 主配置还用 `spring.profiles.include: local` 叠加不入库的本地配置，文件缺失时静默跳过——这个「可选 profile」技巧同样适用于测试。

> ⚠️ 踩坑提示：把数据库口令、JWT 密钥写死在 `application-test.yml` 并入库，是常见安全事故。测试库口令也该走环境变量 `${DB_PASSWORD:root}`，至少生产部署不会误用测试凭证。

## 本章小结

本章梳理了 Spring Boot 3 的测试武器库：**纯单元测试**（JUnit 5，零上下文，秒级）是基底；**切片测试**（@WebMvcTest、@DataJpaTest）按层加载、又快又准；**@SpringBootTest** 承载真正的集成验证，但应克制使用；**Testcontainers** 让你在 CI 里跑真中间件；**@ActiveProfiles** 把测试配置与线上彻底隔离。codegen-server 的 `failIfNoTests=true` 门禁提醒我们：能跑、且真的跑了，测试才算数。

## 本章实战要点

1. 优先写不依赖 Spring 的纯单元测试，把「路径越界、模板渲染」这类纯逻辑锁死在毫秒级用例里。
2. Web 层接口契约用 MockMvc 验证「状态码」与「权限码」，codegen 的 /monitor/* 接口正是这么防回归的。
3. 集成测试务必配独立 `_test` 库与 `schema-test.sql` 重建，杜绝误删开发数据。
