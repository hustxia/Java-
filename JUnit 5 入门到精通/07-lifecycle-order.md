# 第 7 章 测试实例生命周期与执行顺序

## 本章目标

- 理解 `@TestInstance` 的 `PER_METHOD`（默认）与 `PER_CLASS` 两种生命周期；
- 弄懂为什么 `PER_CLASS` 下 `@BeforeAll` 可以不是 `static`；
- 掌握用 `@Order` + `@TestMethodOrder` 显式控制方法顺序；
- 建立「测试彼此独立、不应依赖顺序」的基本原则。

JUnit 5 运行测试时，要决定两件事：**一个测试类创建几个实例**（生命周期），以及**这些实例里的测试方法按什么顺序跑**（方法排序）。这两件事都可以通过注解精确控制，但控制得越多，越要警惕「隐式依赖」。

## 7.1 `@TestInstance`：实例创建策略

默认情况下（不写 `@TestInstance`），JUnit 5 使用 `Lifecycle.PER_METHOD`：**每个测试方法都 new 一个测试类实例**。所以 `@BeforeAll`、`@AfterAll` 必须标在 `static` 方法上——因为它们在「所有实例」之前/之后运行，没有哪个实例能承载它们。

```java
import org.junit.jupiter.api.*;

@TestInstance(TestInstance.Lifecycle.PER_METHOD)   // 默认，可省略
class DefaultLifecycleTest {
    @BeforeAll
    static void 全局准备() { /* 必须是 static */ }

    @Test
    void a() {}

    @Test
    void b() {}
}
```

改成 `PER_CLASS` 后，整个测试类**只创建一个实例**，于是 `@BeforeAll`/`@AfterAll` 可以标在非 `static` 方法上：

```java
@TestInstance(TestInstance.Lifecycle.PER_CLASS)
class SharedInstanceTest {
    private Database db;   // 实例字段，生命周期内共享

    @BeforeAll
    void 连接数据库() {        // 注意：不再是 static
        db = Database.connect();
    }

    @Test
    void 写入() { db.insert("x"); }

    @Test
    void 读取() { assertTrue(db.exists("x")); }

    @AfterAll
    void 关闭数据库() { db.close(); }
}
```

> 💡 `PER_CLASS` 的常见动机：省去把所有字段/辅助方法都写成 `static` 的麻烦，或需要在多个测试方法间**有意**共享一个昂贵的资源（如数据库连接）。但共享也意味着方法间可能互相影响——见 7.4 的踩坑。

## 7.2 方法排序：`@TestMethodOrder` + `@Order`

JUnit 5 默认按「方法名哈希」的确定性顺序执行，但**这个顺序不可依赖**。要显式排序，先标 `@TestMethodOrder`，再给方法标 `@Order`：

```java
import org.junit.jupiter.api.MethodOrderer;

@TestMethodOrder(MethodOrderer.OrderAnnotation.class)   // 按 @Order 数值升序
class OrderedTest {
    @Order(1)
    @Test
    void 先建表() {}

    @Order(2)
    @Test
    void 再插数据() {}

    @Order(3)
    @Test
    void 最后校验() {}
}
```

`MethodOrderer` 提供三种常用实现：

- `OrderAnnotation.class`：按 `@Order(int)` 的数值从小到大；
- `DisplayName.class`：按 `@DisplayName` 字母序；
- `Random.class`：每次运行随机顺序（用于「揪出依赖顺序的脆弱测试」）。

无注解时默认是 `MethodOrderer.MethodName`，按方法名排序，仅用于稳定复现，仍不建议作为业务依赖。

## 7.3 `@Order` 的语义细节

- `@Order` 的取值越小越先执行，默认值为 `Integer.MAX_VALUE / 2`，未标注的方法排在标了的方法之后、且彼此之间仍按默认序；
- `@Order` 只在同一类（或同一 `@Nested`）内有效，不同类之间由测试引擎统一调度，互不影响；
- `@Nested` 内部类可以有自己的 `@TestMethodOrder`，与外部类独立。

```java
@TestMethodOrder(MethodOrderer.Random.class)   // 随机序，专门用来验证独立性
class RandomOrderTest {
    @Test
    void 用例一() {}
    @Test
    void 用例二() {}
}
```

> 小技巧：CI 里偶尔用 `Random` 跑一遍，若某些用例在随机序下变红，基本可以确定它们偷偷依赖了执行顺序或共享状态——这是发现「脆弱测试」的利器。

## 7.4 真实代码中的「天然顺序」需求

有些集成测试确实步骤性强（准备→执行→清理），比如 codegen-server 的 `GenScaffoldPathSafetyTest.java:24-49` 测的是「非法输入一律拒绝、合法输入落在根内」，虽然方法之间没有顺序依赖，但逻辑上是同一防线的不同侧面。这类测试即便加了 `@Order` 也不该互相依赖——每个方法都能独立通过。

codegen-server 的真实测试均以 `@Test`（默认 `PER_METHOD`）书写，未使用 `PER_CLASS` 或 `@Order`，因为它们都做到了「方法零耦合」。这正是我们倡导的写法。

## 7.5 小结：何时该用、何时不该用

- 用 `PER_CLASS`：需要共享非 `static` 资源、或 `@BeforeAll` 依赖实例状态；
- 用 `@Order`：仅在确有强先后步骤（如端到端流程）时使用，并清楚标注原因；
- 默认推荐：`PER_METHOD` + 方法独立，最安全、最易并行。

## 7.6 并行执行与顺序的冲突

JUnit 5 默认串行跑同一类的测试方法，但你可以用 `@Execution(ExecutionMode.CONCURRENT)` 开启并行（或全局在 `junit-platform.properties` 配 `junit.jupiter.execution.parallel.mode.default = concurrent`）。这里有个铁律：**并行一旦开启，任何隐式顺序依赖都会立即暴露为偶发失败。**

```java
import org.junit.jupiter.api.parallel.Execution;
import org.junit.jupiter.api.parallel.ExecutionMode;

@Execution(ExecutionMode.CONCURRENT)   // 本类方法可能并行
class ParallelTest {
    private int counter = 0;           // 危险：并行下多个方法同时改它
    @Test void a() { counter++; }
    @Test void b() { counter++; }
}
```

并行下 `counter` 的读写会互相穿插，结果不可预测。这正是 7.4 强调「方法独立」的根本原因：独立的方法天然可并行，可并行就能在多核机器上大幅缩短测试总时长。反过来，依赖顺序或共享可变字段的测试，永远无法安全地并行。

## 7.7 一份综合示例（此为通用示例）

把 `PER_CLASS` 与 `@Order` 组合，模拟「需要先起一个共享服务、再按步骤验证」的端到端场景：

```java
@TestInstance(TestInstance.Lifecycle.PER_CLASS)          // 共享一个实例
@TestMethodOrder(MethodOrderer.OrderAnnotation.class)    // 按 @Order 排序
class PipelineE2ETest {   // 此为通用示例，未引用 codegen-server 真实代码
    private Server srv;

    @BeforeAll
    void 启动服务() { srv = Server.start(); }            // 非 static，因 PER_CLASS

    @Order(1) @Test void 服务可连通() { assertTrue(srv.ping()); }
    @Order(2) @Test void 接收请求()   { assertTrue(srv.accept("job-1")); }
    @Order(3) @Test void 结果正确()   { assertEquals("ok", srv.result("job-1")); }

    @AfterAll
    void 停止服务() { srv.stop(); }
}
```

注意：这里用 `@Order` 是因为步骤**本质上**有先后（先连通才能收请求）。但三个 `@Test` 仍各自断言一件事，没有「靠上一个方法写入状态供下一个读取」——状态来自共享的 `srv`，而非方法间的隐式传递，因此即便将来拆成独立实例也不会崩。

## 本章小结

- `@TestInstance(PER_METHOD)` 是默认，每方法一实例，`@BeforeAll` 必须 `static`；
- `@TestInstance(PER_CLASS)` 全类一实例，`@BeforeAll`/`@AfterAll` 可非 `static`，适合共享昂贵资源；
- `@TestMethodOrder(OrderAnnotation.class)` + `@Order(n)` 显式控制方法顺序；另有 `DisplayName`、`Random` 两种排序器；
- 方法间应保持独立，`@Order` 是「最后的手段」而非「默认习惯」；
- 并行执行（`@Execution(CONCURRENT)`）会立刻暴露顺序/共享依赖，独立的方法才可安全并行。

⚠️ **踩坑提示（重点）**：**测试应彼此独立，不要依赖执行顺序。** 一旦某个测试方法假定「另一个方法先跑过」，你就会收获一颗定时炸弹——并行执行或 `Random` 排序下它会随机失败。如果确实需要「先建后查」，优先用 `@BeforeEach` 在该方法内自建数据，而不是指望别的 `@Test` 替你铺垫。共享实例字段（`PER_CLASS`）同样会引入跨方法污染：方法 A 写入、方法 B 读取，单独跑 B 就会挂。能用 `@BeforeEach` 重建状态，就别用实例字段「借」状态。
