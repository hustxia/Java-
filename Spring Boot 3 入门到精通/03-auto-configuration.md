# 第 3 章 Spring Boot 自动配置原理

## 本章目标

读完本章你将理解：`@SpringBootApplication` 究竟做了什么，`DataSource`、`WebMvc`、`Jackson` 这些 Bean 为什么「不用写就自动有了」，自动配置背后的条件装配机制，以及如何按需排除或自定义自动配置。本章所有真实片段均取自贯穿案例 codegen-server。

## 3.1 入口注解：@SpringBootApplication 是三个注解的合体

绝大多数 Spring Boot 应用的启动类都长这样（代码来自 `src/main/java/com/codegen/CodegenApplication.java`）：

```java
package com.codegen;

import org.mybatis.spring.annotation.MapperScan;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

@SpringBootApplication          // 一个注解，背后是三个
@MapperScan("com.codegen.mapper")
public class CodegenApplication {

    public static void main(String[] args) {
        SpringApplication.run(CodegenApplication.class, args);
    }
}
```

`@SpringBootApplication` 是一个组合注解，等价于同时写了下面三个：

```java
@SpringBootConfiguration          // = 一个 @Configuration，声明这是配置源
@EnableAutoConfiguration          // 开启自动配置（本章核心）
@ComponentScan(                   // 按启动类所在包递归扫描 @Component 等
    excludeFilters = { ... })     // （Spring Boot 内部预设了一些排除规则）
public class CodegenApplication {}
```

- **@SpringBootConfiguration**：本质就是 `@Configuration`，让启动类本身成为 Bean 定义的来源（你可以在里面写 `@Bean`）。
- **@ComponentScan**：默认扫描「启动类所在包及其子包」。`com.codegen` 下的 `@Controller`、`@Service`、`@Component`（如 `MonitorProperties` 上的 `@Component`）都是被它扫进容器的。
- **@EnableAutoConfiguration**：真正让 Spring Boot「开箱即用」的开关，下面两节重点拆解。

⚠️ **踩坑提示**：如果你的 Controller / Service 写在启动类所在包**之外**，组件扫描扫不到，启动不报错但接口 404。codegen-server 的 `@MapperScan("com.codegen.mapper")` 也是同理——MyBatis 的 Mapper 不走 `@ComponentScan`，必须显式指定扫描路径。

## 3.2 自动配置到底配置了什么

自动配置解决的问题是：**根据「类路径上有哪些依赖」自动决定装配哪些 Bean**，而不是让你手动 `new` 一堆基础设施。

以 codegen-server 为例：`pom.xml` 里引入了 `spring-boot-starter-web`、`mybatis-plus-spring-boot3-starter`、`mysql-connector-j`，但你翻遍源码也找不到一个显式声明 `DataSource` 的 `@Bean`。可应用启动后却能连上 MySQL、用 MyBatis-Plus 操作数据库——这正是自动配置的功劳：

```java
// 你没写，但 Spring Boot 替你装配了：
// DataSourceAutoConfiguration        -> 按 classpath 上的驱动自动建 DataSource
// DataSourceTransactionManager       -> 事务管理器
// MybatisPlusAutoConfiguration       -> SqlSessionFactory / Mapper 注入
// WebMvcAutoConfiguration            -> DispatcherServlet、消息转换器等
```

自动配置类本身也是普通的 `@Configuration`，只不过它们被放在一个「候选清单」里，是否生效由**条件注解**决定（见 3.4）。

## 3.3 自动配置的加载机制：从 spring.factories 到 imports 文件

Spring Boot 怎么知道要加载哪些自动配置类？答案是一份「清单文件」。

在 Spring Boot 2.7 之前，清单写在 `META-INF/spring.factories`：

```properties
# 旧写法（已废弃，仅作了解）
org.springframework.boot.autoconfigure.EnableAutoConfiguration=\
org.springframework.boot.autoconfigure.jdbc.DataSourceAutoConfiguration,\
org.springframework.boot.autoconfigure.web.servlet.WebMvcAutoConfiguration
```

从 Spring Boot 2.7 起（codegen-server 用的 3.2.5 已全面采用），清单迁移到：

```
META-INF/spring/org.springframework.boot.autoconfigure.AutoConfiguration.imports
```

文件里每行一个自动配置类的全限定名，例如 Spring Boot 自带的该文件包含数百行：

```text
org.springframework.boot.autoconfigure.jdbc.DataSourceAutoConfiguration
org.springframework.boot.autoconfigure.web.servlet.WebMvcAutoConfiguration
org.springframework.boot.autoconfigure.jackson.JacksonAutoConfiguration
...
```

`@EnableAutoConfiguration` 在启动时读取这份清单，把候选的自动配置类全部纳入容器，再交给条件注解逐一审视「该不该真的生效」。

> 第三方 starter（如 MyBatis-Plus、SpringDoc）同样会在自己的 jar 里带一份 `AutoConfiguration.imports`，因此只要你引入了该依赖，它的自动配置就会被纳入候选。

## 3.4 条件装配：自动配置的「守门员」

自动配置类几乎都带着 `@ConditionalOnXxx` 注解，只有条件满足时才注册 Bean。常用几个：

```java
@AutoConfiguration
@ConditionalOnClass(DataSource.class)            // 类路径存在 DataSource 才生效
@ConditionalOnMissingBean(DataSource.class)      // 用户没自己定义 DataSource 才生效
@EnableConfigurationProperties(DataSourceProperties.class)
public class DataSourceAutoConfiguration {
    // 只有「有驱动 + 用户没自定义」时才帮你建一个 DataSource Bean
}
```

| 条件注解 | 含义 |
| --- | --- |
| `@ConditionalOnClass` | 类路径存在指定类时生效 |
| `@ConditionalOnMissingBean` | 容器中尚未有该类型 Bean 时生效（用户优先） |
| `@ConditionalOnProperty` | 配置项满足特定值（如 `enabled=true`）时生效 |
| `@ConditionalOnWebApplication` | 当前是 Web 应用时生效 |
| `@ConditionalOnResource` | 指定资源存在时生效 |

理解这一点很关键：**自动配置永远是「兜底」**。一旦你自己写了同类型的 `@Bean`，`@ConditionalOnMissingBean` 就会让自动配置退场，你的定义胜出。codegen-server 没有自定义 `DataSource`，所以自动配置建立的那份被采用。

## 3.5 排除与自定义自动配置

### 3.5.1 用 exclude 关闭不需要的自动配置

有时某个自动配置你不想要（比如引入了 web 但又不想自动注册某些东西），可以排除：

```java
// 代码来自 src/main/java/com/codegen/CodegenApplication.java 的改造示例（通用示例）
@SpringBootApplication(
    exclude = {
        org.springframework.boot.autoconfigure.security.servlet.SecurityAutoConfiguration.class
    })
@MapperScan("com.codegen.mapper")
public class CodegenApplication {
    public static void main(String[] args) {
        SpringApplication.run(CodegenApplication.class, args);
    }
}
```

> 说明：codegen-server 实际并未排除任何自动配置（它仅依赖 `spring-security-crypto`，未引入完整 Security，无需排除）。上面是「通用示例」，演示 `exclude` 的用法，请勿照抄到该项目以免误关配置。

也可以在配置文件中排除（更解耦）：

```yaml
spring:
  autoconfigure:
    exclude:
      - org.springframework.boot.autoconfigure.security.servlet.SecurityAutoConfiguration
```

### 3.5.2 自定义自动配置：写你自己的 starter 候选

当你想把自己封装的能力也做成「引入即用」，就新建一个自动配置类并登记到 `imports` 文件：

```java
// 通用示例：自定义一个自动配置
@AutoConfiguration
@ConditionalOnClass(MyClient.class)
@EnableConfigurationProperties(MyClientProperties.class)
public class MyClientAutoConfiguration {

    @Bean
    @ConditionalOnMissingBean
    public MyClient myClient(MyClientProperties props) {
        return new MyClient(props.getEndpoint());
    }
}
```

然后在 `src/main/resources/META-INF/spring/org.springframework.boot.autoconfigure.AutoConfiguration.imports` 中登记：

```text
com.example.autoconfig.MyClientAutoConfiguration
```

## 3.6 本章小结

- `@SpringBootApplication` = `@SpringBootConfiguration` + `@EnableAutoConfiguration` + `@ComponentScan`，是三合一的便捷注解。
- 自动配置让基础设施 Bean 按「类路径依赖」自动装配，codegen-server 未写 `DataSource` 却连库正是它的功劳。
- 自动配置清单从旧的 `spring.factories` 迁移到了 `META-INF/spring/org.springframework.boot.autoconfigure.AutoConfiguration.imports`。
- 条件注解（`@ConditionalOnClass`、`@ConditionalOnMissingBean`、`@ConditionalOnProperty` 等）决定每个自动配置是否生效，且用户自定义的 Bean 永远优先。
- 用 `@SpringBootApplication(exclude=...)` 或 `spring.autoconfigure.exclude` 可关闭不需要的自动配置。

⚠️ **踩坑提示**：`@ConditionalOnMissingBean` 的判定依据是「容器中是否已有该类型 Bean」。**配置类的加载顺序会影响结果**——不要假设自动配置一定晚于你的 `@Bean` 加载。如果你发现自定义 Bean 没生效，先确认它是否真的在自动配置类之前被注册，必要时用 `@AutoConfigureBefore` / `@AutoConfigureAfter` 显式声明顺序。
