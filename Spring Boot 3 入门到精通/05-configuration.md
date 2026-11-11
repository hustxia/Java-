# 第 5 章 配置体系：application.yml 与类型安全绑定

## 本章目标

读完本章你将掌握 Spring Boot 的配置加载体系：YAML 文件结构、`@Value` 与 `@ConfigurationProperties` 两种取值方式的取舍、多环境 profile 叠加、以及配置项的优先级链。本章所有真实片段取自 codegen-server 的 `application.yml` 与 `MonitorProperties.java`，并借此讲透「配置外置」这一生产必修课。

## 5.1 application.yml 的基本结构

Spring Boot 默认读取 `src/main/resources/application.yml`（或 `.properties`）。YAML 用缩进表达层级，比 properties 更易读。codegen-server 的 `application.yml` 顶层就是几个逻辑分组（代码来自 `application.yml`）：

```yaml
# 代码来自 src/main/resources/application.yml
server:
  port: 8120            # Web 端口

spring:
  application:
    name: codegen-server
  datasource:
    url: jdbc:mysql://localhost:3306/gen_platform?...
    username: ${DB_USERNAME:root}   # 占位符 + 默认值（见 5.3）
    password: ${DB_PASSWORD:root}
```

YAML 的层级最终会拍平成 `server.port`、`spring.datasource.username` 这样的「点分隔键」。**带点的 key 在 YAML 里天然成层级，无需转义**——这和日志配置里的情况不同（见 5.2 反例）。

## 5.2 @Value 与 @ConfigurationProperties

取值有两种主流方式。

### 5.2.1 @Value：简单直接，但易散落

```java
// 通用示例
@Component
public class SomeService {

    @Value("${jwt.expire-hours:24}")     // 支持默认值
    private int jwtExpireHours;

    @Value("${monitor.sample.interval-ms}")
    private long intervalMs;             // 类型需自己保证可转换
}
```

`@Value` 适合零散读取一两个值，但缺点明显：键名硬编码在多处、不支持分组校验、类型转换出错要运行时才爆。

### 5.2.2 @ConfigurationProperties：类型安全、整体绑定

codegen-server 的 `MonitorProperties` 是教科书式范例（代码来自 `src/main/java/com/codegen/config/MonitorProperties.java`）：

```java
// 代码来自 src/main/java/com/codegen/config/MonitorProperties.java
package com.codegen.config;

import lombok.Data;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.stereotype.Component;

@Data
@Component
@ConfigurationProperties(prefix = "monitor")   // 绑定配置里 monitor 开头的全部键
public class MonitorProperties {

    private Sample sample = new Sample();

    @Data
    public static class Sample {
        private long intervalMs = 5000;   // 对应 monitor.sample.interval-ms
        private int bufferSize = 360;     // 对应 monitor.sample.buffer-size
    }
}
```

配合 `application.yml` 中的：

```yaml
# 代码来自 src/main/resources/application.yml
monitor:
  sample:
    interval-ms: ${MONITOR_SAMPLE_INTERVAL_MS:5000}
    buffer-size: ${MONITOR_SAMPLE_BUFFER_SIZE:360}
```

Spring Boot 会把 `monitor.sample.interval-ms` 自动注入到 `sample.intervalMs`（**横杠命名自动转驼峰**），并附带默认值。相比 `@Value`：

| 维度 | @Value | @ConfigurationProperties |
| --- | --- | --- |
| 类型安全 | 弱（运行时转换） | 强（启动时绑定校验） |
| 分组管理 | 散落各处 | 集中到一个类 |
| 默认值 | 写在注解里 | 写在字段初始化里 |
| 元数据提示 | 无 | 配合 `spring-configuration-metadata` 有 IDE 补全 |

### 5.2.3 如何启用绑定

`MonitorProperties` 用了 `@Component`，所以被组件扫描直接注册为 Bean，绑定即生效。若你的配置类**不在组件扫描范围内**，可用以下任一方式启用（通用示例）：

```java
// 方式一：在任意 @Configuration 类上挂 @EnableConfigurationProperties
@Configuration
@EnableConfigurationProperties(MonitorProperties.class)
public class AppConfig {}

// 方式二：在启动类上用 @ConfigurationPropertiesScan 批量扫描
@SpringBootApplication
@ConfigurationPropertiesScan("com.codegen.config")
public class CodegenApplication {}
```

⚠️ **踩坑提示**：`@ConfigurationProperties` 绑定的字段必须有 **getter/setter**（Lombok 的 `@Data` 已提供）。如果忘了 getter/setter，启动不会报错，但字段永远是 `null`/默认值，排查极费时间。`MonitorProperties` 正是靠 `@Data` 省去了这些样板代码。

## 5.3 占位符 ${} 与默认值 ${ENV:default}

配置的精髓是「外置」——同一份代码在不同环境用不同参数。YAML 占位符 `${ENV:default}` 是核心语法：`${变量名:默认值}`。

codegen-server 大量使用该写法把敏感/环境相关项外置（代码来自 `application.yml`）：

```yaml
# 代码来自 src/main/resources/application.yml
spring:
  datasource:
    username: ${DB_USERNAME:root}     # 有环境变量 DB_USERNAME 用它，否则用 root
    password: ${DB_PASSWORD:root}

jwt:
  secret: ${JWT_SECRET:codegen-platform-jwt-secret-key-2026-very-long}
  expire-hours: ${JWT_EXPIRE_HOURS:24}
```

**生产铁律**：像 `JWT_SECRET`、`DB_PASSWORD` 这类绝不能写死进仓库。codegen-server 在注释里明确写道「仓库里的口令等于没有口令」「默认值只为克隆下来直接能跑」。正确做法是用环境变量或本地 `application-local.yml` 覆盖（见 5.4）。

占位符还能嵌套引用别的配置项：

```yaml
# 通用示例
app:
  name: codegen-server
  greeting: ${app.name} 启动完成   # 引用同文件的 app.name
```

## 5.4 多环境 Profiles 与叠加（include）

Spring Boot 用 profile 区分环境：`application-{profile}.yml` 会被自动加载。codegen-server 的 `application.yml` 用 `include` 叠加本地配置（代码来自 `application.yml`）：

```yaml
# 代码来自 src/main/resources/application.yml
spring:
  profiles:
    # 默认叠加 local 配置（application-local.yml，不入库）。
    # 文件不存在时静默跳过，不影响其他人直接跑起来。
    include: local
```

`include: local` 的含义是：无论激活哪个 profile，**始终额外加载** `application-local.yml`。库里提供了模板 `application-local.yml.example`（代码来自 `application-local.yml.example`）：

```yaml
# 代码来自 src/main/resources/application-local.yml.example
gen:
  output:
    backend-root: /path/to/your-target-project
    frontend-root: /path/to/your-target-project
  selfcheck:
    classpath: /path/to/your-target-project/demo-lib/*
```

本地把该文件复制为 `application-local.yml`（已在 `.gitignore` 排除），即可把本机路径、密钥覆盖掉默认值，且**绝不进版本库**。

激活 profile 的几种方式：

```bash
# 命令行参数（优先级最高，见 5.5）
java -jar codegen-server.jar --spring.profiles.active=local

# 或系统属性
java -Dspring.profiles.active=local -jar codegen-server.jar
```

## 5.5 配置优先级：命令行 > 环境变量 > 配置文件 > 默认值

当同一个键在多处出现，Spring Boot 按固定顺序取「后者覆盖前者」的高优先级来源。由高到低大致为：

1. 命令行参数（`--server.port=9000`）
2. `SPRING_APPLICATION_JSON` 中的属性
3. Servlet 上下文 / 环境变量（`SERVER_PORT=9000`，支持大写+下划线转点）
4. `application-{profile}.yml` / `application.yml`
5. 默认属性（`SpringApplication.setDefaultProperties`）

codegen-server 正是利用这条链：**默认值写在 yml 里 → 环境变量（如 `JWT_SECRET`）覆盖 → 命令行可再覆盖**，实现「一份代码、处处可配」。

⚠️ **踩坑提示**：环境变量名要转换成「大写 + 下划线 + 点变下划线」。例如 `monitor.sample.interval-ms` 对应环境变量 `MONITOR_SAMPLE_INTERVAL_MS`（codegen-server 用的就是这套命名）。写成 `monitor.sample.interval-ms` 作为环境变量名在大多操作系统上**不合法**，务必用下划线形式。

另一个易错点：**带点的 key 在某些 YAML 场景会被拆层**。codegen-server 在 `management.metrics.distribution` 段特意注释（代码来自 `application.yml`）：

```yaml
management:
  metrics:
    distribution:
      percentiles-histogram:
        # 带点的 key 必须写 "[http.server.requests]"，否则 yml 会按点拆层级
        "[http.server.requests]": true
```

不加方括号，`http.server.requests` 会被错误地拆成三层嵌套，配置失效。

## 5.6 本章小结

- `application.yml` 用缩进表达层级，最终拍平为点分隔键；YAML 比 properties 更适合管理嵌套配置。
- 取值优先用 `@ConfigurationProperties`（类型安全、集中管理、可校验），零散值才用 `@Value`；`MonitorProperties` 是标准范例。
- 启用绑定可用 `@Component`、`@EnableConfigurationProperties` 或 `@ConfigurationPropertiesScan`。
- `${ENV:default}` 占位符 + 默认值实现「配置外置」，敏感项务必靠环境变量/本地 yml 覆盖，不入库。
- `include: local` 可让本地配置常驻叠加；profile 加载遵循固定优先级链：命令行 > 环境变量 > 配置文件 > 默认值。

⚠️ **踩坑提示**：不要把「能跑的默认值」当成「安全的默认值」。`application.yml` 里 `${JWT_SECRET:...}` 的默认串一旦被提交到公开仓库，任何人都能拿它伪造 token。团队规范应要求：所有含密钥/口令的配置项默认值仅用于本地 demo，CI 与生产的真正取值**必须通过环境变量注入**，并在启动时校验缺失即失败。
