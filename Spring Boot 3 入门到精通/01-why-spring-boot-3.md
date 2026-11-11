# 第 1 章 为什么是 Spring Boot 3

> 本章目标：搞清楚 Spring Boot 3 到底"新"在哪里，它和 2.x 的本质区别是什么，以及为什么 2024 年以后新项目都应该直接上 3.x。读完后你会对全书的"贯穿案例"——一个真实的 Spring Boot 3.2.5 代码生成器平台（codegen-server）——有一个整体印象。

## 1.1 Spring Boot 解决了什么

在谈"3"之前，先记住 Spring Boot 存在的理由：**让 Spring 应用的搭建从"配置地狱"变成"开箱即用"**。

十年前写一个能跑的 Spring Web 项目，你需要：
- 手动引入十几个 Jar 包并小心翼翼对齐版本；
- 写一大坨 `web.xml` 和 Spring 的 `applicationContext.xml`；
- 自己配 `DispatcherServlet`、数据源、事务管理器……

Spring Boot 用三件事把这套流程压缩到分钟级：

1. **起步依赖（Starter）**：`spring-boot-starter-web` 一个依赖，Web 开发要的全部东西一次性拉齐。
2. **自动配置（Auto-configuration）**：只要 classpath 上有相关 Jar，Boot 就自动帮你把 Bean 配好。
3. **嵌入式容器 + 可执行 Jar**：一个 `java -jar` 就能跑，不再依赖外部 Tomcat。

第 2 章你会亲手跑起来一个。先理解"3"的增量价值。

## 1.2 Spring Boot 3 的四大底座升级

Spring Boot 3.0 于 2022 年底发布，3.2.x 是当前最稳的生产线版本（本书案例用的就是 **3.2.5**）。它不是 2.x 的小修小补，而是一次"底座换代"。

### 1.2.1 Java 17 起步，推荐 Java 21

Spring Boot 3 **最低要求 Java 17**，彻底告别 Java 8。本书案例的代码生成器后端直接用 **Java 21**（`pom.xml` 里 `<java.version>21</java.version>`）。

为什么这很重要？Java 17/21 带来了：
- **Record 类**：写 DTO、配置类更简洁；
- **密封类（sealed）**：精确控制继承关系；
- **文本块（Text Blocks）**：多行字符串终于不用拼 `+`；
- **虚拟线程（Virtual Threads，Java 21）**：高并发 I/O 场景吞吐量数量级提升。

```xml
<!-- codegen-server/pom.xml -->
<properties>
    <java.version>21</java.version>
    <maven.compiler.source>21</maven.compiler.source>
    <maven.compiler.target>21</maven.compiler.target>
</properties>
```

### 1.2.2 Jakarta EE 9+：最大的" breaking change"

这是从 2.x 升级时最容易踩的坑。Java EE 捐给 Eclipse 基金会后包名从 `javax.*` 改成了 `jakarta.*`。

| 2.x（Java EE） | 3.x（Jakarta EE） |
|---|---|
| `javax.servlet.*` | `jakarta.servlet.*` |
| `javax.persistence.*` | `jakarta.persistence.*` |
| `javax.annotation.*` | `jakarta.annotation.*` |

只要你的代码或第三方库还 `import javax.servlet.http.HttpServletRequest`，在 3.x 下**编译都过不了**，必须改成 `jakarta`。这是升级项目时工作量最集中的地方。

### 1.2.3 Spring Framework 6 基座

Boot 3 基于 Spring Framework 6。核心收益包括：
- AOT（Ahead-Of-Time）编译基础，为 GraalVM 原生镜像铺路；
- `ProblemDetail`（RFC 7807）统一错误格式；
- 全面拥抱 `jakarta` 命名空间。

### 1.2.4 可观测性一等公民

Boot 3 把 **Micrometer** 深度集成进框架。过去要单独接 Prometheus，现在 `http.server.requests`、JVM、线程池等指标开箱即用。本书第 16 章会用一个真实落地的 `monitor` 包带你手写一套平台级埋点。

## 1.3 和 Spring Boot 2.x 的差异速查

| 维度 | 2.x | 3.x |
|---|---|---|
| 最低 Java | 8 | 17（推荐 21） |
| 命名空间 | `javax.*` | `jakarta.*` |
| 基线 Spring | 5.x | 6.x |
| 原生支持 | 实验性 | AOT + GraalVM 正式支持 |
| 安全框架 | Spring Security 5 | Spring Security 6（配置 API 大改） |
| 可观测性 | 需手动接 | Micrometer 内置 |

> ⚠️ **踩坑提示**：不要指望"只改个版本号就能升级"。Security 6 把 `WebSecurityConfigurerAdapter` 标记为移除，配置要改成 `SecurityFilterChain` Bean；大量配置属性也改了名（如 `spring.redis` → `spring.data.redis`）。第 22 章附录有一份迁移清单。

## 1.4 本书的贯穿案例：codegen-server

为了让所有知识点都"长在真实代码上"，本书用一个我维护的生产级项目 **codegen-server** 作为贯穿案例。它是什么？

- 一个**代码生成器平台后端**：你给它一张数据库表，它能生成 Entity、Mapper、Service、Controller，甚至整个可运行的前后端工程；
- 技术栈：**Spring Boot 3.2.5 + Java 21 + MyBatis-Plus 3.5.5 + Freemarker + JWT + Actuator**；
- 形态：**独立单体应用**（不依赖 Nacos/网关/Redis，连上 MySQL 就能跑），端口 8120。

它麻雀虽小五脏俱全，几乎覆盖了本书全部主题：

```java
// 代码来自 src/main/java/com/codegen/CodegenApplication.java
package com.codegen;

import org.mybatis.spring.annotation.MapperScan;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

@SpringBootApplication
@MapperScan("com.codegen.mapper")
public class CodegenApplication {
    public static void main(String[] args) {
        SpringApplication.run(CodegenApplication.class, args);
    }
}
```

就这么几行，一个完整的后端就启动了。后面你会看到它内部如何用自动配置、Starter、类型安全配置、AOP、事务、JWT、异步调度、可观测性把能力一点点撑起来。

## 1.5 本书怎么读

- **零基础到能写业务**：按顺序读第 1～10 章；
- **只关心安全/部署**：跳读第 11、16、20 章；
- **想学可观测性实战**：重点第 16 章 + 第 21 章剖析；
- 每章都有"⚠️ 踩坑提示"和"本章小结"，建议配合 codegen-server 源码一起看。

## 本章小结

- Spring Boot 3 = Java 17+（推荐 21）+ Jakarta EE + Spring 6 + 原生/AOT + 内置可观测性。
- 最大的升级成本是 `javax` → `jakarta` 的包名迁移和 Security 6 配置改写。
- 本书所有示例优先取自真实项目 codegen-server，确保你学到的是生产级写法。

> ⚠️ **踩坑提示**：如果你本地还是 Java 8 环境，跑本书示例会直接报 `UnsupportedClassVersionError`。请先安装 JDK 17 或 21，并用 `java -version` 确认。
