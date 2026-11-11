# 第 22 章 附录：迁移、速查与排错字典

> 这是收尾章，定位是"字典"——当你忘了某个注解怎么写、迁移时某属性改名叫啥、线上又报那个老错误时，翻这一章就够了。

## 本章目标

- 掌握 **Spring Boot 2 → 3** 的关键迁移点（包名、Java 基线、Security 6、属性重命名）；
- 一张**常用注解速查表**，扫一眼就知道该用哪个；
- 一份**FAQ / 排错清单**，把全书各章的"踩坑提示"汇总成可检索的表格。

---

## 22.1 Spring Boot 2 → 3 迁移要点

### 22.1.1 `javax` → `jakarta` 包名（破坏性最大）

Spring Boot 3 基于 Jakarta EE 9+，所有 `javax.*` 变成 `jakarta.*`。codegen-server 里就能看到迁移后的写法：

```java
// 来源：com/codegen/controller/GenController.java
import jakarta.servlet.http.HttpServletResponse;   // 注意是 jakarta，不是 javax
import jakarta.validation.Valid;
// 来源：com/codegen/config/AuthContextFilter.java
import jakarta.servlet.FilterChain;
import jakarta.servlet.http.HttpServletRequest;
```

**迁移动作**：全局把 `javax.servlet` → `jakarta.servlet`、`javax.validation` → `jakarta.validation`、`javax.persistence` → `jakarta.persistence`（MyBatis-Plus 3.5.5 for Boot3 已适配）。IDE 的"Replace in Files" + 编译报错是主要手段；第三方库必须选**明确支持 Jakarta** 的版本（如 codegen 用的 `mybatis-plus-spring-boot3-starter`，而不是老 starter）。

### 22.1.2 Java 17+ 基线（codegen 直接上 21）

Spring Boot 3 **最低 Java 17**，codegen-server 一步到位用 Java 21（`pom.xml` 里 `java.version=21`）。收益：虚拟线程预览、record、更优的 G1/ZGC。迁移时：

- 把编译与运行 JDK 都升到 17+；
- 老代码里依赖的 `javax.xml.bind` 等被移除的模块需另引依赖；
- 利用新语法（record 做 DTO、switch 表达式）精简代码——codegen 的 `MetricSnapshot` 就是 `record`。

### 22.1.3 Spring Security 6 配置改法

Security 6 最大的变化是**弃用 `WebSecurityConfigurerAdapter`**，改用**组件式 `SecurityFilterChain` Bean**。codegen-server 没用完整 Security（只用 BCrypt，鉴权自写 Filter），但通用迁移写法如下（**此为通用示例**）：

```java
// 此为通用示例：Security 6 组件式配置
@Configuration
@EnableWebSecurity
public class SecurityConfig {
    @Bean
    public SecurityFilterChain filterChain(HttpSecurity http) throws Exception {
        http
            .csrf(AbstractHttpConfigurer::disable)   // 前后端分离常关 CSRF
            .authorizeHttpRequests(auth -> auth
                .requestMatchers("/auth/login", "/actuator/health").permitAll()
                .anyRequest().authenticated())
            .sessionManagement(s -> s.sessionCreationPolicy(SessionCreationPolicy.STATELESS));
        return http.build();
    }
}
```

要点：`authorizeRequests` → `authorizeHttpRequests`；`antMatchers` → `requestMatchers`；配置从"继承 Adapter 重写方法"变成"声明 `SecurityFilterChain` Bean"。

### 22.1.4 配置属性重命名清单（高频）

| Spring Boot 2 | Spring Boot 3 | 说明 |
|---------------|---------------|------|
| `spring.redis.*` 旧键 | `spring.data.redis.*` | 统一收进 `spring.data` |
| `server.max-http-header-size` | `server.max-http-request-header-size` | 改名 |
| `spring.datasource.*` (Hikari 旧) | 不变，但 `spring.datasource.hikari.*` 正式化 | 见第 19 章 |
| `management.endpoints.web.exposure.include` | 同，但默认暴露更少 | 需显式开 `health,info,metrics`（codegen 正是这么配的） |
| `spring.config.use-legacy-processing` | 移除 | 老配置加载机制彻底下线 |

> 最稳妥的迁移工具是 Spring 官方的 **`spring-boot-properties-migrator`** 依赖：编译期提示哪些属性被改名/移除。

---

## 22.2 常用注解速查表

| 注解 | 一句话说明 |
|------|-----------|
| `@SpringBootApplication` | 启动类总注解，等价于 `@Configuration+@EnableAutoConfiguration+@ComponentScan` |
| `@RestController` | `@Controller+@ResponseBody`，直接返回 JSON（codegen 的 `GenController`/`MonitorController` 都用它） |
| `@Controller` | 返回视图名（模板渲染），不全是 JSON |
| `@RequestMapping` | 类/方法级映射 URL；`@GetMapping`/`@PostMapping` 是其派生 |
| `@PathVariable` | 取 URL 路径变量，如 `/table/{id}` 的 `id` |
| `@RequestParam` | 取查询参数；**参数名绑定依赖编译期 `-parameters`**（见 FAQ） |
| `@RequestBody` | 把请求体 JSON 反序列化成对象；`@Valid` 触发校验 |
| `@Configuration` | 声明配置类，里面 `@Bean` 方法向容器注册组件 |
| `@Bean` | 方法级，返回对象注册为 Spring Bean（如 `MybatisPlusInterceptor`） |
| `@ConfigurationProperties` | 把 yml 前缀绑定成强类型对象（codegen 的 `MonitorProperties`/`GenOutputProperties`） |
| `@Component`/`@Service`/`@Repository` | 通用/业务/持久层组件扫描标记 |
| `@MapperScan` | 指定 MyBatis Mapper 接口扫描包（codegen 在启动类上） |
| `@Transactional` | 声明式事务；注意自调用、非 public、异常被吞会导致失效（见 FAQ） |
| `@Cacheable` / `@CacheEvict` | 方法结果缓存 / 清除缓存（需先开缓存注解驱动） |
| `@Async` | 异步执行；**默认无界线程池，必须自定义 `ThreadPoolTaskExecutor`**（见 FAQ） |
| `@Scheduled` | 定时任务；**默认单线程调度器**（codegen 用 `spring.task.scheduling.pool.size=2` 防御） |
| `@EnableScheduling` | 开启调度（codegen 的 `MonitorConfig` 上） |
| `@EventListener` | 监听 ApplicationEvent，解耦模块间通知 |
| `@Order` | 控制同类型组件（如 Filter、切面）的执行顺序（codegen 鉴权 Filter 用 `HIGHEST_PRECEDENCE+10`） |
| `@Tag` / `@Operation` | springdoc 注解，给接口文档分组与描述 |

---

## 22.3 FAQ 与排错清单（全书踩坑汇总）

| # | 现象 | 根因 | 解决 / 出处 |
|---|------|------|------------|
| 1 | 接口报 `Name for argument of type [X] not specified`，HTTP 500 | 编译没保留参数名，MVC 无法绑定 `@RequestParam`/`@PathVariable` | `pom.xml` 的 `maven-compiler-plugin` 加 `<arg>-parameters</arg>`（第 19 章） |
| 2 | 打成 fat jar 后，生成自检满屏 `cannot find symbol` | `java.class.path` 只有 `app.jar` 自身，javac 解析不到嵌套依赖 | 配 `gen.selfcheck.classpath` 指向目标工程依赖目录（第 20 章） |
| 3 | 启动报循环依赖 `BeanCurrentlyInCreationException` | Boot 2.6+ 默认禁止构造器循环依赖 | 改用 `@Lazy`、setter 注入，或重构拆依赖（通用） |
| 4 | `@Transactional` 方法里抛异常却没回滚 / 根本没开事务 | 自调用（同类方法调）、方法非 public、异常被 catch 吞掉、用了不支持事务的数据源 | 跨类调用、public、抛未捕获 `RuntimeException`；codegen 写盘刻意不用单事务而用台账（第 21 章） |
| 5 | 分页查询 `total` 恒为 0 | 漏注册 `PaginationInnerInterceptor` | `MybatisPlusConfig` 里 `addInnerInterceptor(new PaginationInnerInterceptor(DbType.MYSQL))`（第 13/21 章） |
| 6 | 偶发 `CommunicationsException: last packet ...` | 连接比 MySQL `wait_timeout` 活得久，拿到断开连接 | 调小 Hikari `max-lifetime` 小于服务端超时（第 19 章） |
| 7 | 定时任务互相卡住 / 一个慢任务拖垮全部 | `@Scheduled` 默认单线程调度器 | `spring.task.scheduling.pool.size` 提到 2+（codegen 已配）（第 19 章） |
| 8 | `@Async` 高并发下线程数爆炸 | 默认 `SimpleAsyncTaskExecutor` 无界建线程 | 自定义 `ThreadPoolTaskExecutor` 设上限（第 19 章） |
| 9 | 改了用户角色/权限，要等登录过期才生效 | JWT 里塞了角色，token 不过期就不刷新 | codegen 决策：角色权限**实时查库**，不写进 token（第 15/21 章） |
| 10 | 写盘接口返回成功，但数据库没有台账记录 | `recordOutput` 失败被吞（只 `log.warn`） | 看响应头 `X-Gen-Ledger-Errors`；台账失败不阻断写盘是刻意设计（第 19/21 章） |
| 11 | 日志"消失"、磁盘不增长却仍在写 | logrotate 用 rename 切割，Java 持旧 fd | 用 Logback 自带滚动，或 logrotate 加 `copytruncate`（第 20 章） |
| 12 | 生产 `git clone` 后直接跑，连的是别人/默认的库与密钥 | 敏感信息写死在 yml | 全部 `${ENV:default}` 外部化，密钥走环境变量（第 20 章） |
| 13 | `springdoc` 接口文档在生产仍暴露 | 没关 `enabled` | 设 `SPRINGDOC_API_DOCS_ENABLED=false` / `SPRINGDOC_UI_ENABLED=false`（第 20 章） |
| 14 | 生成大表时 Nginx 返回 504 | 默认 `proxy_read_timeout=60s` 太短 | 放宽到 300s（第 20 章） |
| 15 | 新增全局 Filter 后未登录也能访问接口 | 没加 `@Order`，排在鉴权 Filter 之前 | 鉴权 Filter 用最高优先级 `@Order(Ordered.HIGHEST_PRECEDENCE+10)`（第 21 章） |
| 16 | 多实例下监控数据对不上 / 重启后曲线清空 | `MonitorStore` 是进程内环形缓冲，不跨实例、不持久化 | 单实例看即可；要全局接 Prometheus（第 19 章） |
| 17 | 容器里频繁 Full GC / OOM | `-Xmx` 没和容器 limit 对齐，或默认只用了 1/4 内存 | 显式 `-Xmx`，与 limit 一致，开 OOM 堆转储（第 19 章） |

---

## 22.4 Spring Boot 3 其它破坏性变更与版本对照

除了 22.1 的三大项，迁移时还常撞到这些"隐性变化"：

| 变更点 | Boot 2 | Boot 3 | 备注 |
|--------|--------|--------|------|
| 自动配置注册 | `META-INF/spring.factories` | `META-INF/spring/org.springframework.boot.autoconfigure.AutoConfiguration.imports` | 写 starter 才需关心 |
| HTTP 客户端 | `RestTemplate` 默认可用 | 仍可用，但官方推荐 `RestClient` / `WebClient` | 新项目优先响应式/声明式 |
| `@ConstructorBinding` | 放在类上即可 | 必须放在构造器上，且类需 `@ConfigurationProperties` | 配置绑定写法收紧 |
| 属性绑定校验 | 宽松 | 类型不匹配直接启动失败 | 迁移后留意 yml 类型 |
| Apache HttpClient | 有自动配置 | 移除相关自动配置 | 改用 `RestClient` 或自管客户端 |
| 最低 Java 版本 | 8/11 | **17** | 连带很多库的最低版本水涨船高 |

**版本与依赖对照（来自 codegen-server 的真实 `pom.xml`，可作为迁移时的"基线参照"）：**

```xml
<!-- 来源：pom.xml（节选，已是 Spring Boot 3 形态） -->
<properties>
    <java.version>21</java.version>                       <!-- 远高于 17 基线 -->
    <spring-boot.version>3.2.5</spring-boot.version>
    <mybatis-plus.version>3.5.5</mybatis-plus.version>    <!-- 注意用 spring-boot3-starter -->
    <springdoc.version>2.3.0</springdoc.version>          <!-- Swagger UI 2.x 适配 Boot 3 -->
    <jjwt.version>0.12.5</jjwt.version>
    <lombok.version>1.18.30</lombok.version>
</properties>
```

迁移 checklist（落地顺序）：

1. 升 JDK 到 17+（codegen 用 21），确认本地/CI 工具链一致；
2. 升 `spring-boot.version` 到 3.x，执行 `mvn dependency:tree` 排查不兼容的旧库；
3. 全局 `javax` → `jakarta`，替换不支持 Jakarta 的第三方依赖（如 MyBatis-Plus 换 `spring-boot3-starter`）；
4. 若用 Spring Security，重写为 `SecurityFilterChain` Bean；
5. 跑官方 `spring-boot-properties-migrator`，按提示改属性名；
6. 全量编译 + 单元测试 + 启动冒烟，重点验证 JPA/MyBatis 映射、Servlet Filter、校验。

---

## 22.5 名词速查（本书高频术语）

| 术语 | 含义（一句话） |
|------|--------------|
| 自动配置 `auto-configuration` | Spring Boot 按 classpath 自动装配 Bean，无需手写大量 XML/Java 配置 |
| 起步依赖 `starter` | 一组预选好的依赖集合，如 `spring-boot-starter-web` |
| 外部化配置 `externalized config` | 把环境相关值（密码、路径）放到环境变量/配置文件，jar 不变 |
| 胖 jar `fat jar` | 把依赖一起打进的可执行 jar（codegen 产出 `codegen-server.jar`） |
| 统一返回 | 用 `Result<T>` 包裹所有接口响应，前端按统一结构解析 |
| AOP 审计 | 用切面在方法前后记录操作日志，与业务代码解耦 |
| 数据权限 | 按登录用户的范围（all/dept/self）改写 SQL，看不到不该看的数据 |
| 逻辑删除 | 用 `deleted` 字段标记删除而非物理删（codegen 用 `logic-delete-field`） |
| 连接池 `HikariCP` | 复用数据库连接，避免每次新建连接的开销 |
| 可观测性 `observability` | metrics / logs / traces 三位一体，能回答"为什么慢/为什么错" |
| 区间差分 | 本轮累计值减上轮，得到"近 N 分钟"口径，避免曲线只涨不跌 |
| 准事务 | 用业务台账 + 回滚替代跨资源的数据库事务（codegen 写盘方案） |
| 幂等 `idempotent` | 同一操作重复执行结果一致，流水线重跑安全的前提 |
| 降级 `degrade` | 增强功能失败时退化为基础行为，不拖垮主线 |

> 这本"字典"章节的任务是：**当你卡住时，先翻这里**。迁移查 22.1、注解查 22.2、报错查 22.3、术语查 22.5——把书当工具，而不是当故事。

---

## 本章小结

- 迁移三座大山：`javax→jakarta`（全局替换 + 换 Jakarta 版依赖）、**Java 17+ 基线**（codegen 直接 21）、**Security 6 组件式 `SecurityFilterChain`**；属性重命名用官方 migrator 辅助；
- 注解速查表覆盖启动、Web、配置、事务、缓存、异步、调度、事件、排序等高频注解，扫一眼即可定位该用哪个；
- FAQ 把全书踩坑凝成 17 条可检索清单：参数名 500、肥 jar 资源、循环依赖、事务失效、分页 total 为 0、连接断开、线程池默认值、JWT 权限延迟、台账静默、日志切割、密钥外置、文档暴露、网关超时、Filter 顺序、监控不共享、容器 GC——**把这本书当字典翻，比死记硬背更有效**。

⚠️ **收尾提示**：没有哪一条踩坑是"别人的故事"。codegen-server 的每一个 `@Order`、`-parameters`、`pool.size=2`、`${ENV:default}`、台账失败不阻断，背后都是一次线上事故或演示翻车。**写代码时多想一步"它会怎么坏"，比坏了再查快十倍。**
