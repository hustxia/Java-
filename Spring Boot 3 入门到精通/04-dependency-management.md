# 第 4 章 依赖管理：BOM 与 Starter

## 本章目标

读完本章你将掌握 Spring Boot 如何「不用写版本号也能管住成百上千个依赖版本」——即 BOM 机制；理解 `spring-boot-dependencies` 与 `dependencyManagement` 的关系；分清官方 starter 与第三方 starter 的命名约定；并学会如何自己写一个可复用的 starter。本章所有真实片段取自 codegen-server 的 `pom.xml`。

## 4.1 为什么你几乎从不用写版本号

打开 codegen-server 的 `pom.xml`，你会发现绝大多数依赖都没有 `<version>`：

```xml
<!-- 代码来自 pom.xml -->
<dependency>
    <groupId>org.springframework.boot</groupId>
    <artifactId>spring-boot-starter-web</artifactId>
    <!-- 没有 version！版本由 BOM 统一治理 -->
</dependency>
<dependency>
    <groupId>org.springframework.boot</groupId>
    <artifactId>spring-boot-starter-actuator</artifactId>
</dependency>
```

原因只有一个：它们的版本被一份「物料清单（BOM，Bill Of Materials）」集中管控了。Spring Boot 把一套互相兼容的库版本打包进 `spring-boot-dependencies`，你只要导入它，子依赖的版本就自动对齐，避免「Spring 6.1 撞上 Jackson 2.11 导致 NoSuchMethodError」这类地狱。

## 4.2 BOM 机制与 dependencyManagement

BOM 本质上是一个 `<packaging>pom</packaging>` 的特殊工程，它本身不含代码，只声明 `<dependencyManagement>` 里的一堆带版本的依赖模板。

codegen-server **没有继承** `spring-boot-starter-parent`，而是通过 `import` 作用域导入 BOM（代码来自 `pom.xml`）：

```xml
<!-- 代码来自 pom.xml -->
<properties>
    <spring-boot.version>3.2.5</spring-boot.version>
    <!-- 其余库的版本仍自行声明 -->
    <mybatis-plus.version>3.5.5</mybatis-plus.version>
</properties>

<dependencyManagement>
    <dependencies>
        <dependency>
            <groupId>org.springframework.boot</groupId>
            <artifactId>spring-boot-dependencies</artifactId>
            <version>${spring-boot.version}</version>
            <type>pom</type>
            <scope>import</scope>   <!-- 关键：import 把 BOM 里的版本表合并进来 -->
        </dependency>
    </dependencies>
</dependencyManagement>
```

### 两种方式对比

| 方式 | 写法 | 适用场景 |
| --- | --- | --- |
| 继承 parent（推荐） | `<parent>` 指向 `spring-boot-starter-parent` | 新建项目、能改 parent 时 |
| 导入 BOM | `dependencyManagement` 里 `import` `spring-boot-dependencies` | 项目已有父 POM、不便继承时 |

> 继承 parent 的好处不止 BOM：它还预设了 `java.version`、资源过滤、插件版本（如 `spring-boot-maven-plugin`）等。codegen-server 因历史原因已有自己的层级结构，故选择「导入 BOM」这条更灵活的路线——**两种都能享用版本治理，只是 parent 还多送你一些默认配置**。

⚠️ **踩坑提示**：`import` 作用域只能出现在 `<dependencyManagement>` 内，且一个 `<dependencyManagement>` 里可以 import 多个 BOM。但如果你同时 import 了多个互相冲突的 BOM（比如两个都管 Jackson 版本），**后声明的覆盖先声明的**，容易引入非预期版本，务必检查依赖树（`mvn dependency:tree`）。

## 4.3 Starter 命名约定

starter 是一类「聚合依赖 + 自动配置」的便捷包。Spring Boot 社区有一条铁律级的命名约定，用于区分官方与第三方：

| 类型 | 命名规则 | 示例 |
| --- | --- | --- |
| 官方 starter | `spring-boot-starter-*` | `spring-boot-starter-web`、`spring-boot-starter-data-jpa` |
| 第三方 starter | `*-spring-boot-starter` | `mybatis-plus-spring-boot3-starter`、`springdoc-openapi-starter-webmvc-ui` |

注意看 codegen-server 的 `pom.xml` 里两类并存：

```xml
<!-- 官方：spring-boot-starter-* -->
<dependency>
    <groupId>org.springframework.boot</groupId>
    <artifactId>spring-boot-starter-web</artifactId>
</dependency>

<!-- 第三方：*-spring-boot-starter -->
<dependency>
    <groupId>com.baomidou</groupId>
    <artifactId>mybatis-plus-spring-boot3-starter</artifactId>
    <version>${mybatis-plus.version}</version>
</dependency>

<!-- 第三方（名字里带 starter 但不完全套用后缀的特例，由社区约定俗成） -->
<dependency>
    <groupId>org.springdoc</groupId>
    <artifactId>springdoc-openapi-starter-webmvc-ui</artifactId>
    <version>${springdoc.version}</version>
</dependency>
```

> 命名约定不是语法强制，而是**可读性约定**：看到 `spring-boot-starter-` 开头就知道是官方维护、版本跟着 Spring Boot 走；看到 `*-spring-boot-starter` 结尾就知道是第三方封装。SpringDoc 这类虽不严格后缀，但 `starter` 关键字仍在名字中，便于辨认。

## 4.4 自己写一个 Starter（autoconfigure + starter 两模块）

当你想把一个通用能力（如「统一调用某内部 SDK」）封装成「引入即用」，标准做法是拆成两个 Maven 模块：

```
my-sdk-spring-boot-starter/          ← 空壳 starter（仅聚合依赖）
└── pom.xml
my-sdk-spring-boot-autoconfigure/    ← 真正的自动配置实现
├── pom.xml
└── src/main/java/.../MySdkAutoConfiguration.java
└── src/main/resources/META-INF/spring/org.springframework.boot.autoconfigure.AutoConfiguration.imports
```

**模块一：autoconfigure（承载逻辑）**

```java
// 通用示例
package com.example.sdk.autoconfigure;

@AutoConfiguration
@ConditionalOnClass(MySdkClient.class)
@EnableConfigurationProperties(MySdkProperties.class)
public class MySdkAutoConfiguration {

    @Bean
    @ConditionalOnMissingBean
    public MySdkClient mySdkClient(MySdkProperties props) {
        return new MySdkClient(props.getEndpoint(), props.getToken());
    }
}
```

```java
// 通用示例：类型安全的配置绑定
@ConfigurationProperties(prefix = "my-sdk")
public class MySdkProperties {
    private String endpoint = "https://default.example.com";
    private String token;
    // getter / setter 省略
}
```

在 `autoconfigure` 模块的 `resources` 下登记清单：

```text
# META-INF/spring/org.springframework.boot.autoconfigure.AutoConfiguration.imports
com.example.sdk.autoconfigure.MySdkAutoConfiguration
```

**模块二：starter（仅依赖聚合，无 Java 代码）**

```xml
<!-- 通用示例：starter 模块 pom.xml -->
<artifactId>my-sdk-spring-boot-starter</artifactId>
<dependencies>
    <dependency>
        <groupId>com.example.sdk</groupId>
        <artifactId>my-sdk-spring-boot-autoconfigure</artifactId>
        <version>1.0.0</version>
    </dependency>
    <!-- 顺带把 SDK 本身也带进来 -->
    <dependency>
        <groupId>com.example.sdk</groupId>
        <artifactId>my-sdk-core</artifactId>
        <version>1.0.0</version>
    </dependency>
</dependencies>
```

使用者只需引入 `my-sdk-spring-boot-starter`，自动配置就会被 Boot 扫描到并生效，还能用 `my-sdk.endpoint` 配置——这正是 codegen-server 引入 `mybatis-plus-spring-boot3-starter` 时「零配置就能用 MyBatis-Plus」的底层原理。

## 4.5 本章小结

- Spring Boot 通过 BOM（`spring-boot-dependencies`）集中管理依赖版本，因此业务依赖通常**无需写版本号**。
- 导入 BOM 有两种方式：继承 `spring-boot-starter-parent`（顺带送插件与默认配置）或在 `dependencyManagement` 中 `import` BOM（更灵活，codegen-server 采用此方式）。
- 命名约定：官方 starter 用 `spring-boot-starter-*`，第三方用 `*-spring-boot-starter`，便于一眼区分维护方。
- 自定义 starter 推荐「autoconfigure（实现 + imports 清单）+ starter（空壳聚合依赖）」两模块结构，让能力「引入即用、可配置、可覆盖」。

⚠️ **踩坑提示**：第三方 starter 的版本号**不在** Spring Boot BOM 管辖范围内（如 codegen-server 的 `mybatis-plus.version` 需自行声明）。升级 Spring Boot 大版本后，第三方 starter 可能尚未适配（例如 MyBatis-Plus 必须选 `-spring-boot3-starter` 才能跑在 Boot 3 / Jakarta 命名空间下），照搬旧版会直接报 `javax.servlet` 找不到——务必核对第三方 starter 对 Boot 3 的兼容性。
