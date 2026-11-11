# 第 1 章 自动化测试与 JUnit 5 入门

## 本章目标

- 理解为什么要把测试写成可自动运行的代码；
- 认识 JUnit 5 的三大模块（Platform / Jupiter / Vintage）及其分工；
- 厘清 JUnit 5 与 JUnit 4 在注解、扩展机制上的关键区别；
- 知道在 codegen-server（Spring Boot 3.2.5 + Java 21）中如何引入依赖、如何运行测试。

---

## 1.1 为什么写自动化测试

很多团队把测试停留在「手动点点点」：本地验证完，提交，祈祷线上别炸。但三个更可靠的价值，只有**自动化测试**能稳定提供：

### 回归保护（Regression Guard）

代码库会不断变大、被人反复修改。一个看似无关的补丁，可能悄悄破坏三个月前写好的逻辑。自动化测试是「永不疲倦的守门员」——每次 `mvn test` 都会把所有用例重跑一遍。只要有一条断言失败，构建立刻变红，问题被挡在合并之前。

> 本书贯穿案例 codegen-server 是一个代码生成器平台后端。它的监控模块有一段**环形缓冲**逻辑：缓冲区满了就淘汰最旧的数据，且绝不允许扩容。这种「边界行为」正是回归测试最该盯住的地方——一旦有人把 `add` 写成「满了就扩容」，肉眼几乎看不出来，但有测试就会立刻报错。（详见第 2、3 章对 `MonitorStoreTest` 的拆解。）

### 活文档（Living Documentation）

好的测试名就是规格说明。看到 `invalidMetricReturns400`、`seriesClampsMinutesTo30` 这样的方法名，你不用读实现，就知道系统「非法 metric 返回 400」「minutes 越界被钳到 30」。测试比注释更可靠——注释会过期，测试不过编译都过不了。

### 设计反馈（Design Feedback）

测试难写，往往是代码设计有味道的信号。一个类如果依赖十几个外部组件、构造函数塞满参数，测试根本没法孤立构造。反过来，容易被测试的代码，通常职责单一、依赖清晰。写测试的过程，就是逼着你把代码拆干净的过程。

---

## 1.2 JUnit 5 三大模块

JUnit 5 不是 JUnit 4 的小版本升级，而是一次从内到外的重写，被拆成了三个独立子项目：

| 模块 |  artifactId  | 职责 |
|------|--------------|------|
| **JUnit Platform** | `junit-platform-*` | 测试运行的「底座」：定义 `TestEngine` SPI、在 IDE / Maven / Gradle 中启动测试、上报结果。 |
| **JUnit Jupiter** | `junit-jupiter-*` | 全新的编程模型与扩展模型，也就是我们日常写的 `@Test`、`@BeforeEach`、`assertXxx`。名字来自 JUnit 5 的开发代号。 |
| **JUnit Vintage** | `junit-vintage-engine` | 兼容引擎，能在 JUnit 5 平台上跑**老旧的 JUnit 4 / 3 用例**，用于渐进迁移。 |

记住一句话：**Platform 负责「跑」、Jupiter 负责「写」、Vintage 负责「兼容老的」**。本书绝大部分内容围绕 Jupiter 展开。

---

## 1.3 与 JUnit 4 的关键区别

如果你写过 JUnit 4，下面这几处改动最容易被绊倒：

1. **`@Test` 的包名变了**。JUnit 5 来自 `org.junit.jupiter.api.Test`；JUnit 4 是 `org.junit.Test`。导入错了，注解直接失效。
2. **没有 `@RunWith`，改用 `@ExtendWith`**。JUnit 4 用 `@RunWith(SpringRunner.class)` 注入运行器；JUnit 5 用「扩展（Extension）」机制，`@ExtendWith(MockitoExtension.class)` 是典型例子（codegen-server 的 `MonitorControllerTest` 就是这么用的）。
3. **断言类改名**。`org.junit.Assert` → `org.junit.jupiter.api.Assertions`。方法签名基本不变，但包要改。
4. **假设 `Assumptions`** 仍在，且行为更明确：当 `assumeTrue(...)` 不满足时，该用例被标记为「跳过（skipped）」而非失败，常用于「当前环境不满足前提就跳过」。

> 包名 `jupiter` 是 JUnit 5 的开发代号，看到它就代表「新 API」，与 `junit` 老包严格区分。

---

## 1.4 如何引入依赖

在 codegen-server 的 `pom.xml` 中，测试相关依赖只有一段（代码来自 `pom.xml` 第 111–115 行）：

```xml
<!-- 代码来自 pom.xml 第 111-115 行 -->
<dependency>
    <groupId>org.springframework.boot</groupId>
    <artifactId>spring-boot-starter-test</artifactId>
    <scope>test</scope>
</dependency>
```

你**没有**手写 `junit-jupiter`、`mockito`、`assertj`。原因很巧妙：`spring-boot-starter-test` 是一个「聚合 starter」，它通过 Spring Boot 的依赖管理，间接触发了以下 transitive 依赖：

- `junit-jupiter`（JUnit 5 的 Jupiter 引擎与 API）——本书主角；
- `mockito-core` / `mockito-junit-jupiter`（Mockito 模拟框架，配合 `@ExtendWith(MockitoExtension.class)`）；
- `assertj-core`（流式断言库，比 `Assertions` 可读性更强）；
- `junit-platform-launcher`（让 Maven Surefire 能发现并执行 JUnit 5 用例）。

也就是说，只要你引入了 `spring-boot-starter-test`，开箱即用的测试栈就齐了，无需逐个声明。

---

## 1.4.1 本书贯穿案例：codegen-server

从本章起，所有真实示例都来自一个真实项目 **codegen-server**——一个基于 Spring Boot 3.2.5 + Java 21 的代码生成器平台后端（含登录、系统管理与 V6.10 新增的平台可观测性模块）。它的测试代码全部位于 `src/test/java` 下，共 49 个真实测试类。我们会在后续章节反复引用其中两个：

- `com.codegen.monitor.MonitorStoreTest`：验证**环形缓冲**的边界行为（容量上限、淘汰最旧、空状态），纯单元测试、零 Spring 上下文，跑得极快；
- `com.codegen.controller.MonitorControllerTest`：在 HTTP 层验证监控接口的**状态码契约**（非法参数 400、越权 403、正常 200），用 standalone `MockMvc` 直接吃控制器的 `@ExceptionHandler`，同样不拉 Spring 上下文。

选择这两个类做样板，是因为它们恰好覆盖了「纯逻辑断言」与「Web 层契约」两类最典型的单元测试场景，而且都足够小、能整段贴出而不臃肿。

---

## 1.5 如何运行测试

codegen-server 提供了三种常见运行方式：

**方式一：IDE 直接跑**
在 IntelliJ IDEA / Eclipse 中，右键测试类或方法 → Run。开发时最高频，反馈最快。

**方式二：Maven 命令行**
```bash
# 跑全部测试
mvn test

# 只跑某个类的测试
mvn test -Dtest=MonitorStoreTest
```

**方式三：Maven Surefire 插件（CI 门禁）**
Surefire 是 Maven 在 `test` 阶段自动绑定的「测试执行器」。codegen-server 显式固定了它的版本（代码来自 `pom.xml` 第 155–165 行）：

```xml
<!-- 代码来自 pom.xml 第 155-165 行 -->
<plugin>
    <groupId>org.apache.maven.plugins</groupId>
    <artifactId>maven-surefire-plugin</artifactId>
    <version>3.5.4</version>
    <configuration>
        <!-- 测试数为 0 必须失败，避免「一个用例都没跑却 BUILD SUCCESS」 -->
        <failIfNoTests>true</failIfNoTests>
    </configuration>
</plugin>
```

这里有两个值得记住的点：

- **版本固定为 3.5.4**：注释说明，早期因为父 POM 未继承导致 surefire 版本错配（3.6.0 解析失败）、一个用例都没跑却显示成功。锁到 3.5.4 后配合 `surefire-junit-platform` + `junit-platform-launcher` 1.10.2 才稳定。这正是「JUnit Platform 负责跑、Jupiter 负责写」的体现——Surefire 通过 `surefire-junit-platform` 桥接到 Platform。
- **`failIfNoTests=true`**：任何被误配导致「零用例执行」的情况都会让构建失败，而非「绿了假象」。
- 依赖锁定后，本工程甚至可在**离线**（`mvn -o`）环境下完成 `mvn test`，因为它在 `pom.xml` 注释中明确写明 surefire 3.5.4 + `surefire-junit-platform` + `junit-platform-launcher` 1.10.2 均已就位本地仓库。
- 若后续升级 Spring Boot，JUnit 相关版本会随 `spring-boot-dependencies` 这个 BOM 一起联动，无需手动逐个改版本号。

---

## 1.6 测试金字塔与本书定位

提到运行测试，顺带说一个经典心智模型——**测试金字塔**：底层是大量廉价、快速的「单元测试」（本书主角），中层是「集成测试」，顶层是少量昂贵的「端到端测试」。codegen-server 的 `MonitorStoreTest` / `MonitorControllerTest` 都属于底层单元测试：不连库、不拉上下文、毫秒级返回，因此能无负担地挂进 `mvn test` 常规门禁，每次提交都跑。本书聚焦金字塔底层的 JUnit 5 写法，把「快、稳、可读」的单元测试能力打扎实。

> 经验法则：当一个单元测试慢到「不敢经常跑」，它往往已经越界成了集成测试——要么拆分依赖，要么明确挪到金字塔中上层并单独贴标签（见第 4 章 `@Tag`）。

## 本章小结

- 自动化测试提供三大价值：**回归保护、活文档、设计反馈**。
- JUnit 5 由 **Platform（跑）、Jupiter（写）、Vintage（兼容老）** 三模块构成。
- 相比 JUnit 4：注解包名改为 `org.junit.jupiter.api`，`@RunWith` → `@ExtendWith`，断言类改为 `Assertions`。
- codegen-server 仅靠 `spring-boot-starter-test` 即获得完整测试栈；运行靠 IDE / `mvn test` / Surefire 3.5.4。

## ⚠️ 踩坑提示

**别把 JUnit 4 和 JUnit 5 的注解混在同一个类里。** 新手最容易犯的错误是：导入了 `org.junit.Test`（老包）又想用 `@BeforeEach`（新包），结果 `@BeforeEach` 根本不被识别，初始化逻辑没执行，测试莫名其妙 NPE。记住——只要看到 `jupiter` 包，整个测试类就统一用 Jupiter 全家桶；若项目里还有老用例要跑，交给 `junit-vintage-engine`，而不是在新类里混用。
