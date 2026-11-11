# 第 6 章 日志体系：SLF4J + Logback 实战

## 本章目标

读完本章你将理解 Spring Boot 的日志门面/实现分工，能用 `logback-spring.xml` 配置滚动切割与格式，掌握 MDC 透传 traceId 做链路追踪，以及按 profile 切换日志级别。本章所有真实片段取自 codegen-server 的 `logback-spring.xml` 与 `application.yml` 的 logging 段。

## 6.1 门面与实现：SLF4J + Logback

Spring Boot 默认日志栈是 **SLF4J（门面）+ Logback（实现）**。你在代码里只依赖 SLF4J 的 API，不直接碰 Logback，这样将来换实现（如 Log4j2）不用改业务代码：

```java
// 通用示例：永远用 SLF4J 门面，别 import ch.qos.logback.*
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

@RestController
public class UserController {
    private static final Logger log = LoggerFactory.getLogger(UserController.class);

    public void login(String user) {
        log.info("用户登录: {}", user);   // 用占位符 {}，避免字符串拼接开销
        log.debug("调试信息...");
    }
}
```

为什么不直接 `System.out.println`？因为日志有级别、可异步、可滚动归档、可带上下文，而 `println` 一条都没有。SLF4J 提供 `TRACE < DEBUG < INFO < WARN < ERROR` 五级，生产一般设到 `INFO`，排查时临时调到 `DEBUG`。

## 6.2 用 logback-spring.xml 接管日志配置

Spring Boot 自带一套默认日志格式，但生产需要自定义。codegen-server 在 `application.yml` 里显式指定了日志配置文件（代码来自 `application.yml`）：

```yaml
# 代码来自 src/main/resources/application.yml
logging:
  config: classpath:logback-spring.xml   # 指定自定义 Logback 配置
  level:
    com.codegen: info                     # 业务包默认 INFO 级
```

> 命名约定：**必须用 `logback-spring.xml` 而非 `logback.xml`**。前者由 Spring 接管，支持 `<springProfile>` 等特有标签；后者在 Spring 环境就绪前就被加载，拿不到 `${}` 占位符和 profile 信息。

### 6.2.1 真实配置：JSON 行格式 + 滚动切割

codegen-server 的 `logback-spring.xml` 把日志输出成**单行 JSON**，方便后续被 ELK/Loki 等采集（代码来自 `src/main/resources/logback-spring.xml`）：

```xml
<!-- 代码来自 src/main/resources/logback-spring.xml -->
<configuration>
    <springProperty scope="context" name="appName" source="spring.application.name" defaultValue="codegen-server"/>
    <!-- 端口占位直接用 server.port，别用 local.server.port（容器就绪后才写入，取不到会随机端口） -->
    <springProperty scope="context" name="appPort" source="server.port" defaultValue="0"/>

    <property name="LOG_HOME" value="logs"/>
    <property name="LOG_PATTERN"
              value='{"@timestamp":"%d{yyyy-MM-dd HH:mm:ss.SSS}","app":"${appName}","port":"${appPort}","thread":"%t","level":"%p","logger":"%c{40}","msg":"%m","throwable":"%ex"}%n'/>

    <appender name="CONSOLE" class="ch.qos.logback.core.ConsoleAppender">
        <encoder><pattern>${LOG_PATTERN}</pattern><charset>UTF-8</charset></encoder>
    </appender>

    <appender name="FILE" class="ch.qos.logback.core.rolling.RollingFileAppender">
        <file>${LOG_HOME}/${appName}.log</file>
        <rollingPolicy class="ch.qos.logback.core.rolling.SizeAndTimeBasedRollingPolicy">
            <fileNamePattern>${LOG_HOME}/${appName}-%d{yyyy-MM-dd}.%i.log</fileNamePattern>
            <maxFileSize>100MB</maxFileSize>     <!-- 单文件超 100MB 翻滚 -->
            <maxHistory>14</maxHistory>          <!-- 保留 14 天 -->
            <totalSizeCap>5GB</totalSizeCap>     <!-- 总容量上限，超出删最旧 -->
        </rollingPolicy>
        <encoder><pattern>${LOG_PATTERN}</pattern><charset>UTF-8</charset></encoder>
    </appender>

    <root level="INFO">
        <appender-ref ref="CONSOLE"/>
        <appender-ref ref="FILE"/>
    </root>
</configuration>
```

要点：
- **`<springProperty>`**：从 Spring 环境取值注入 Logback 变量，比原生 `<property>` 能拿到 `application.yml` 里的配置。`appPort` 直接取 `server.port`，避免用 `local.server.port`（容器就绪后才写入，日志初始化阶段取不到会退化成随机端口，误导排障）。
- **`SizeAndTimeBasedRollingPolicy`**：按「时间（天）+ 大小」双维度翻滚，既保证每天一个基线文件，又防止单文件无限膨胀。
- **JSON 格式**：`msg`、`level`、`throwable` 等字段独立，机器解析友好。

⚠️ **踩坑提示**：`<springProperty>` 取 `server.port` 没问题，但**不要**用 `local.server.port` 当端口占位符。后者是 Web 容器启动后才写入环境的，而日志系统在应用最早阶段就初始化了，取不到时会用默认值甚至随机端口，导致你看到日志里端口是「0」或乱码，排查「端口被占用」类问题时被严重误导。

## 6.3 MDC 透传 traceId 做链路追踪

在微服务或长调用链里，怎么把「一次请求」的所有日志串起来？答案是 **MDC（Mapped Diagnostic Context）**——一个线程级的键值容器，Logback 的 `%X{traceId}` 能把它打印进每条日志。

```java
// 通用示例：在过滤器/拦截器里注入 traceId
import org.slf4j.MDC;

@Component
public class TraceFilter implements Filter {
    @Override
    public void doFilter(ServletRequest req, ServletResponse res, FilterChain chain) {
        String traceId = UUID.randomUUID().toString();
        MDC.put("traceId", traceId);          // 放入当前线程上下文
        try {
            chain.doFilter(req, res);
        } finally {
            MDC.clear();                       // 必须清理！线程池复用会串味
        }
    }
}
```

然后在 `logback-spring.xml` 的 pattern 里加 `"traceId":"%X{traceId}"`。之后同一请求的所有日志都带同一个 `traceId`，用 `grep` 或日志平台即可拉出完整链路。

⚠️ **踩坑提示**：MDC 基于 `ThreadLocal`，**线程池/异步（`@Async`、CompletableFuture、WebClient 回调）会丢上下文**。跨线程时必须用 `MDC.getCopyOfContextMap()` 在提交任务前取出、在任务内 `MDC.setContextMap()` 还原；否则异步线程打出的日志没有 `traceId`。另外 `finally` 里务必 `MDC.clear()`，否则线程归还池子后被别的请求复用，会串到别人的 traceId。

## 6.4 按 Profile 切换日志级别

不同环境常需要不同日志级别：本地想看 `DEBUG`，生产只看 `INFO`/`WARN`。`logback-spring.xml` 的 `<springProfile>` 标签可按 profile 差异化配置（**通用示例**，codegen-server 当前文件未使用，但其 `logback-spring.xml` 命名支持此特性）：

```xml
<!-- 通用示例：本地放开 DEBUG，生产收紧 -->
<springProfile name="local">
    <logger name="com.codegen" level="DEBUG"/>
</springProfile>

<springProfile name="prod">
    <logger name="com.codegen" level="INFO"/>
    <root level="WARN"/>
</springProfile>
```

也可以不碰 XML，直接在对应 `application-{profile}.yml` 里设级别（更轻量）：

```yaml
# 通用示例：application-local.yml
logging:
  level:
    com.codegen: debug
    org.springframework.web: debug
```

注意 codegen-server 的主 `application.yml` 已用 `include: local` 叠加本地配置（见第 5 章），所以本地把级别写进 `application-local.yml` 即可覆盖 `com.codegen: info`，互不冲突。

## 6.5 生产进阶：异步日志与控制台取舍

同步写日志在高并发下会阻塞业务线程。Logback 提供 `AsyncAppender` 把日志先入队列、由独立线程落盘（**通用示例**，codegen-server 当前 `logback-spring.xml` 未使用，可按需追加）：

```xml
<!-- 通用示例：用 AsyncAppender 包裹 FILE，业务线程非阻塞 -->
<appender name="ASYNC_FILE" class="ch.qos.logback.classic.AsyncAppender">
    <queueSize>2048</queueSize>            <!-- 队列容量 -->
    <discardingThreshold>0</discardingThreshold>  <!-- 0=队列满时阻塞而非丢日志 -->
    <appender-ref ref="FILE"/>
</appender>

<root level="INFO">
    <appender-ref ref="CONSOLE"/>
    <appender-ref ref="ASYNC_FILE"/>
</root>
```

此外生产常做两个取舍：
- **关掉控制台日志**：容器化部署时 stdout 由平台采集，`CONSOLE` appender 可去掉，只留文件/平台采集，减少重复 IO。
- **ERROR 单独归档**：再配一个按 `<level>ERROR</level>` 过滤的 appender，把错误日志单独落 `error.log`，告警系统只需盯这一个文件。

⚠️ **踩坑提示**：`AsyncAppender` 的 `discardingThreshold` 默认是队列剩余容量小于 20% 时**丢弃 TRACE/DEBUG/INFO**，只保 WARN/ERROR。若你的 INFO 日志也不能丢，必须设为 `0`（如上），否则高峰期会「静默丢日志」，排障时以为没发生其实只是没记下来。

## 6.6 本章小结

- Spring Boot 默认 **SLF4J + Logback**；代码中只依赖 SLF4J 门面，用 `{}` 占位符输出，不要直接 `println`。
- 用 `logging.config=classpath:logback-spring.xml` 接管配置；文件名必须是 `logback-spring.xml`（带 `-spring`）才能用 `<springProfile>` 与 `${}` 占位符。
- 滚动切割推荐 `SizeAndTimeBasedRollingPolicy`，配合 `maxFileSize`/`maxHistory`/`totalSizeCap` 控盘；JSON 行格式利于日志平台采集。
- `<springProperty>` 可从 Spring 环境注入变量（如 `appName`、`appPort`），但端口要用 `server.port` 而非 `local.server.port`。
- MDC + `%X{traceId}` 实现链路串联，异步场景需手动透传且 `finally` 清理。
- 用 `<springProfile>` 或 `application-{profile}.yml` 的 `logging.level` 按环境切级别。

⚠️ **踩坑提示**：日志文件「写不进去/不滚动」多半是路径权限或文件名模式问题。codegen-server 把日志写到 `logs/` 相对目录——**以 fat jar 部署时，`logs/` 相对的是 jar 启动所在的工作目录，而非 jar 内部**。若用 systemd 等服务管理器启动，工作目录可能不是你预期的路径，导致 `FileNotFoundException`。部署前确认工作目录可写，或用绝对路径（如 `/var/log/codegen-server/`）。
