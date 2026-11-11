# 第 2 章 快速开始：十分钟跑起一个 Spring Boot 3 服务

> 本章目标：从零认识一个 Spring Boot 3 项目的骨架，亲手理解 `pom.xml`、启动类、配置文件三者如何协作，并认识本书案例 codegen-server 的工程结构。读完你能独立 clone 它、改配置、启动、调通第一个接口。

## 2.1 一个最小项目的三件套

Spring Boot 3 项目最核心的三个文件：

```
my-app/
├── pom.xml                  # 1. 依赖与构建（Maven）
├── src/main/java/com/demo/
│   └── DemoApplication.java # 2. 启动类
└── src/main/resources/
    └── application.yml      # 3. 配置
```

下面以 codegen-server 的真实片段逐一看。

## 2.2 pom.xml：不是普通父工程

codegen-server 因历史原因**没有继承 `spring-boot-starter-parent`**，而是用 `dependencyManagement` 显式导入 BOM（这种方式更灵活，适合作为子模块被别的父工程管理）：

```xml
<!-- 代码来自 codegen-server/pom.xml -->
<properties>
    <java.version>21</java.version>
    <spring-boot.version>3.2.5</spring-boot.version>
    <mybatis-plus.version>3.5.5</mybatis-plus.version>
    <jjwt.version>0.12.5</jjwt.version>
</properties>

<!-- 关键：用 BOM 锁定 Spring Boot 全家桶版本 -->
<dependencyManagement>
    <dependencies>
        <dependency>
            <groupId>org.springframework.boot</groupId>
            <artifactId>spring-boot-dependencies</artifactId>
            <version>${spring-boot.version}</version>
            <type>pom</type>
            <scope>import</scope>
        </dependency>
    </dependencies>
</dependencyManagement>

<dependencies>
    <!-- Web 开发一站式起步依赖 -->
    <dependency>
        <groupId>org.springframework.boot</groupId>
        <artifactId>spring-boot-starter-web</artifactId>
    </dependency>
    <!-- 可观测性：Actuator + Micrometer（Boot 3.2.5 自带 micrometer，无需单独引） -->
    <dependency>
        <groupId>org.springframework.boot</groupId>
        <artifactId>spring-boot-starter-actuator</artifactId>
    </dependency>
    <!-- 参数校验 JSR-380 -->
    <dependency>
        <groupId>org.springframework.boot</groupId>
        <artifactId>spring-boot-starter-validation</artifactId>
    </dependency>
</dependencies>
```

要点：
- **Starter 命名约定**：`spring-boot-starter-*` 是官方起步依赖；`*-spring-boot-starter` 是第三方（如 `mybatis-plus-spring-boot3-starter`）。
- **BOM 帮你管版本**：引入 `spring-boot-starter-web` 时你不写版本号，版本由 BOM 统一决定，避免冲突。

### 两个非写不可的构建细节

codegen-server 的 `pom.xml` 里有两段注释极多的插件配置，这是踩过坑才留下的：

```xml
<!-- 必须保留 -parameters：Spring MVC 靠参数名绑定 @RequestParam/@PathVariable。
     没有它，运行时会报 "Name for argument ... not specified" 的 500 错误 -->
<plugin>
    <groupId>org.apache.maven.plugins</groupId>
    <artifactId>maven-compiler-plugin</artifactId>
    <configuration>
        <compilerArgs><arg>-parameters</arg></compilerArgs>
    </configuration>
</plugin>
```

> ⚠️ **踩坑提示**：如果你的工程**不是**通过 `spring-boot-starter-parent` 继承的（像本书案例这样用 BOM 导入），`maven-compiler-plugin` 不会自动带 `-parameters`，必须如上显式声明，否则带参接口会莫名其妙 500。

## 2.3 启动类：四行代码背后的魔法

```java
// 代码来自 src/main/java/com/codegen/CodegenApplication.java
@SpringBootApplication
@MapperScan("com.codegen.mapper")
public class CodegenApplication {
    public static void main(String[] args) {
        SpringApplication.run(CodegenApplication.class, args);
    }
}
```

`@SpringBootApplication` 是一个**组合注解**，它等价于同时声明了：
- `@SpringBootConfiguration`：标记这是配置源；
- `@EnableAutoConfiguration`：开启自动配置（Boot 3 的精华）；
- `@ComponentScan`：扫描当前包及子包下的 `@Component/@Service/@Controller` 等。

`@MapperScan` 是 MyBatis 的注解，告诉框架去 `com.codegen.mapper` 找接口。

`SpringApplication.run(...)` 干的事：启动内嵌 Tomcat（默认 8080，案例改成 8120）、完成自动配置、刷新 Spring 容器、触发 `CommandLineRunner`、应用就绪。

## 2.4 application.yml：一切可配置

案例监听 8120 端口，连本机 MySQL：

```yaml
# 代码来自 codegen-server/src/main/resources/application.yml
server:
  port: 8120

spring:
  application:
    name: codegen-server
  datasource:
    url: jdbc:mysql://localhost:3306/gen_platform?useUnicode=true&characterEncoding=UTF-8&useSSL=false&serverTimezone=Asia/Shanghai
    username: ${DB_USERNAME:root}      # 环境变量优先，缺省 root
    password: ${DB_PASSWORD:root}
```

`${DB_USERNAME:root}` 是**占位符 + 默认值**：部署到生产时只需 `export DB_USERNAME=realuser`，不用改文件。这是 Spring Boot「配置外置」思想的缩影（第 5 章详解）。

## 2.5 跑起来：三条命令

```bash
# 1. 克隆/进入项目（本书案例）
cd codegen-server

# 2. 用 Maven 启动（跳过测试快速验证）
./mvnw spring-boot:run
# 或用已安装 maven：
mvn spring-boot:run -DskipTests

# 3. 看到 Started CodegenApplication 即成功，访问：
curl http://localhost:8120/actuator/health
# 返回 {"status":"UP"}
```

如果端口被占用，改 `server.port` 或 `SERVER_PORT` 环境变量即可。

## 2.6 工程结构一览（codegen-server）

```
src/main/java/com/codegen/
├── CodegenApplication.java        # 启动类
├── config/                        # 安全过滤器、MyBatis、可观测性、类型安全配置
├── controller/                    # REST 接口（GenController, MonitorController…）
├── service/                       # 业务逻辑（含代码生成流水线）
├── mapper/                        # MyBatis Mapper 接口
├── entity/                        # 数据库实体
├── monitor/                       # V6.10 平台可观测性七件套
└── common/                        # 统一返回、异常、数据权限、用户上下文
```

这个结构会贯穿全书——第 7 章讲 `controller` + 统一返回，第 9 章讲 `mapper`/`entity`，第 11 章讲 `config` 里的鉴权，第 16 章讲 `monitor` 包。

## 2.7 开发提效：devtools 与热部署

开发阶段加上：

```xml
<dependency>
    <groupId>org.springframework.boot</groupId>
    <artifactId>spring-boot-devtools</artifactId>
    <scope>runtime</scope>
    <optional>true</optional>
</dependency>
```

改代码后 IDE 触发重新编译，devtools 自动重启（比冷启动快，因为它只重建应用上下文）。案例工程未引入，但新项目强烈建议加上。

## 本章小结

- Spring Boot 3 项目 = `pom.xml`（依赖/BOM）+ 启动类（`@SpringBootApplication`）+ `application.yml`（配置）。
- 不用继承 parent 时，记得显式加 `-parameters` 编译器参数。
- `${ENV:default}` 占位符是配置外置的第一步，生产靠环境变量注入密钥。
- 本书案例 codegen-server 已可本地启动，后续章节都围绕它的真实代码展开。

> ⚠️ **踩坑提示**：用 `mvn spring-boot:run` 和打 `jar` 后 `java -jar` 的类加载方式不同。若代码里用到了"扫描 classpath 下某个文件"（如案例的可观测性离线库），在 IDE 里能跑、打成肥 jar 后可能找不到——第 21 章会专门讲这种"肥 jar 陷阱"。
