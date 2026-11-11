# 第 12 章 Spring Boot 测试：从全上下文到切片测试

## 本章目标

- 掌握 `@SpringBootTest` 加载完整应用上下文的代价与适用场景；
- 理解切片测试（`@WebMvcTest` / `@DataJpaTest` / `@MybatisTest`）「只加载相关层」为何更快；
- 会用 `@MockBean` / `@SpyBean` 在 Spring 容器里替换 Bean；
- 用 `@ActiveProfiles` 切测试专用配置（以 codegen-server 的 `application-test.yml` 为例）；
- 了解 Testcontainers 如何用 `@Container` 起真实 MySQL 替换内存库。

## 先确认环境：pom.xml 里的依赖

codegen-server 的 `pom.xml` 已经把测试全家桶引入：

```xml
<!-- 来源：pom.xml:111-115 -->
<dependency>
    <groupId>org.springframework.boot</groupId>
    <artifactId>spring-boot-starter-test</artifactId>
    <scope>test</scope>
</dependency>
```

`spring-boot-starter-test` 一站式带来了 JUnit 5、Mockito、AssertJ、Hamcrest、JSONassert、Spring Test 与 `spring-test` 的 `MockMvc`。注意 `pom.xml` 里**没有父工程继承**，所以必须显式声明 surefire：

```xml
<!-- 来源：pom.xml:155-164 -->
<plugin>
    <groupId>org.apache.maven.plugins</groupId>
    <artifactId>maven-surefire-plugin</artifactId>
    <version>3.5.4</version>
    <configuration>
        <!-- 测试数为 0 必须失败，防止「用例没跑却 BUILD SUCCESS」 -->
        <failIfNoTests>true</failIfNoTests>
    </configuration>
</plugin>
```

⚠️ **踩坑提示**：无父 POM 时，surefire 默认版本可能和 JDK 21 的 class 文件不兼容，导致「一个用例都没跑却 SUCCESS」。codegen-server 把 surefire 钉到 `3.5.4` 并设 `failIfNoTests=true`，正是为了暴露这类静默失败。

## @SpringBootTest：加载完整上下文

`@SpringBootTest` 会沿 `@SpringBootApplication` 向上找配置，启动**几乎完整的 Spring 容器**（含所有 `@Component`、数据源、Web 层）。它的优点是「测的就是生产装配」，缺点是慢——每启动一个这样的测试类都要重建上下文。

codegen-server 的契约测试就用了它，因为那一层要验证真实链路（写盘、台账、回滚）：

```java
// 来源：src/test/java/com/codegen/contract/GenPipelineContractTest.java:62-64
@SpringBootTest
@AutoConfigureMockMvc(addFilters = false)   // 不加载安全过滤器链，直接打接口
@ActiveProfiles("test")                      // 切到测试专用配置（见下文）
@DisplayName("写盘链路四条不变式（HTTP 契约）")
class GenPipelineContractTest { ... }
```

`webEnvironment` 是常用调参项：

- `WebEnvironment.MOCK`（默认）：不起真实 Servlet 容器，用 MockMvc 打（最快，契约测试即此模式）；
- `RANDOM_PORT` / `DEFINED_PORT`：起真实 Tomcat，可测过滤器、CORS、真实 HTTP；
- `NONE`：只建上下文，不暴露 Web。

通用示例：

```java
// 以下为通用示例（非 codegen-server 代码）
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
class HealthIntegrationTest {
    @LocalServerPort int port;
    @Test void ping() { /* 用真实端口发 HTTP 请求 */ }
}
```

## 切片测试：只加载相关层

`@SpringBootTest` 太重时，用**切片注解**只装配某一层，启动飞快：

| 注解 | 加载范围 | 用途 |
|------|----------|------|
| `@WebMvcTest` | 仅 Web 层（Controller + MVC 基础设施） | 测控制器，不连 DB |
| `@DataJpaTest` | 仅 JPA 仓库 + 内存库 | 测 Repository 查询 |
| `@MybatisTest` | 仅 MyBatis Mapper + 内存库 | 测 Mapper SQL |
| `@JsonTest` | 仅 JSON 序列化 | 测 DTO 编组 |

```java
// 以下为通用示例（非 codegen-server 代码）
@WebMvcTest(OrderController.class)   // 只加载 OrderController 及 MVC 配置
class OrderControllerTest {
    @Autowired MockMvc mvc;
    @MockBean OrderService svc;       // 容器里的 OrderService 被替换为 mock
}
```

⚠️ **踩坑提示**：codegen-server **实际上没有使用** `@WebMvcTest` / `@DataJpaTest` / `@MybatisTest` 这类切片注解（Grep 全测试源码无匹配）。它选择用 `@SpringBootTest` + `@ActiveProfiles("test")` 配合 `@TempDir` 沙箱做契约测试。原因见下一节——它的写盘/台账链路必须真实落库才能验证「md5 与磁盘一致」这类不变式，切片测试的内存库反而没法覆盖。本书保留切片测试讲解，是因为它是 Spring 测试工具箱的标准能力，你自己的项目大概率用得上。

## 在容器里替换 Bean：@MockBean / @SpyBean

`@MockBean` 会在 Spring 容器里**注册一个 Mockito mock 替换掉同类型的真实 Bean**；`@SpyBean` 则保留真实 Bean、仅包裹一层间谍。这对「我想测 Controller，但不想让它真连权限服务」特别有用：

```java
// 以下为通用示例（非 codegen-server 代码）
@WebMvcTest(UserController.class)
class UserControllerTest {
    @Autowired MockMvc mvc;
    @MockBean PermissionService permissionService; // 容器里的真权限服务被 mock 顶替
    @Test void list() {
        when(permissionService.isSuperAdmin(1L)).thenReturn(true);
        // ... 断言
    }
}
```

`MonitorControllerTest` 之所以**不用** `@MockBean` 而用 `@Mock` + standalone MockMvc，正是因为 standalone 模式根本不启动容器——没有容器可注入，所以用纯 Mockito 字段更直接（详见第 13 章）。

## 切配置：@ActiveProfiles

`@ActiveProfiles("test")` 让测试加载 `application-test.yml`。codegen-server 的测试配置有三条硬约束（`src/test/resources/application-test.yml`）：

```yaml
# 来源：src/test/resources/application-test.yml（节选）
spring:
  datasource:
    url: jdbc:mysql://localhost:3306/gen_platform_test?createDatabaseIfNotExist=true
    username: root
    password: root
  sql:
    init:
      mode: always
      schema-locations: classpath:schema-test.sql   # 每次启动重建表
gen:
  output:
    backend-root: ${java.io.tmpdir}/gen-contract-fallback  # 兜底，真用例用 @TempDir 覆盖
```

契约测试还在 `setUp` 里加了**数据源护栏**，防连错库把开发数据冲掉：

```java
// 来源：GenPipelineContractTest.java:648-654
private void guardAgainstDevDatabase() throws Exception {
    try (Connection c = dataSource.getConnection()) {
        String url = c.getMetaData().getURL();
        assertTrue(url.contains("gen_platform_test"),
                "契约测试会写库，数据源必须是 gen_platform_test，当前是：" + url);
    }
}
```

## Testcontainers：用真实 MySQL 替换内存库

内存库（H2）跑得过轻，但 SQL 方言、事务行为与 MySQL 有差异，容易「本地绿、上线程」。Testcontainers 用 Docker 起一个**真实 MySQL**，测试完自动销毁：

```java
// 以下为通用示例（非 codegen-server 代码，需引入 testcontainers 依赖）
@Testcontainers
@SpringBootTest
class RealMySqlContractTest {
    @Container
    static MySQLContainer<?> mysql = new MySQLContainer<>("mysql:8.0")
            .withDatabaseName("gen_platform_test");

    @DynamicPropertySource
    static void props(DynamicPropertyRegistry r) {
        r.add("spring.datasource.url", mysql::getJdbcUrl);
        r.add("spring.datasource.username", mysql::getUsername);
        r.add("spring.datasource.password", mysql::getPassword);
    }
}
```

codegen-server 目前直接连本机 `gen_platform_test`（见 `application-test.yml`），没有引入 Testcontainers；如果 CI 环境没有常驻 MySQL，把上面这段接上即可实现「零本地依赖、跑真实库」。

## 本章小结

- `@SpringBootTest` 启动近完整上下文，慢但保真；`webEnvironment` 控制是否起真实容器。
- 切片测试（`@WebMvcTest`/`@DataJpaTest`/`@MybatisTest`）只装相关层，快；codegen-server 实战未用切片，而是用 `@SpringBootTest`+`@ActiveProfiles("test")` 跑真实链路。
- `@MockBean`/`@SpyBean` 在容器里替换 Bean；`@ActiveProfiles` 切测试配置，`application-test.yml` 用 `_test` 库名 + 每次重建 schema 防污染。
- Testcontainers 用 `@Container` 起真实 MySQL，解决 H2 方言漂移问题。

⚠️ **踩坑提示**：`@MockBean` 会**触发上下文缓存失效**——同一测试类里每多一个 `@MockBean`，Spring 就可能重建一份上下文，多个此类测试叠加会明显拖慢。能用纯 Mockito（`@Mock` + standalone）解决的 Web 层测试，就不要上 `@WebMvcTest`+`@MockBean`。codegen-server 的 `MonitorControllerTest` 正是这么做的。
