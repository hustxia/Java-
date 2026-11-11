# 第 2 章 第一个测试类与生命周期

## 本章目标

- 写出第一个 JUnit 5 测试类与 `@Test` 方法；
- 掌握四个生命周期注解 `@BeforeEach` / `@AfterEach` / `@BeforeAll` / `@AfterAll` 的执行时机与 `@BeforeAll` 必须静态的原因；
- 用 **Arrange-Act-Assert（三段式）** 组织测试代码；
- 以真实文件 `MonitorStoreTest.java` 为样板，读懂一个可运行的测试长什么样。

---

## 2.1 最小的测试类

一个 JUnit 5 测试类，本质就是一个**普通 Java 类**，里面带若干被 `@Test` 标注的方法。方法名可以随便起（甚至不用 `test` 前缀），返回 `void`，通常不带参数。

下面先给一个最小骨架（此为通用示例）：

```java
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.assertEquals;

class CalculatorTest {

    @Test
    void addTwoNumbers() {
        // 这里写测试逻辑
        assertEquals(4, 2 + 2);
    }
}
```

要点：`@Test` 来自 `org.junit.jupiter.api.Test`；断言用 `Assertions.assertEquals`。只要类在 `src/test/java` 下、方法是非私有的，JUnit 就能发现它。

---

## 2.2 真实样板：MonitorStoreTest

codegen-server 的环形缓冲测试就是很好的真实样板（代码来自 `src/test/java/com/codegen/monitor/MonitorStoreTest.java`）：

```java
// 代码来自 src/test/java/com/codegen/monitor/MonitorStoreTest.java
package com.codegen.monitor;

import com.codegen.config.MonitorProperties;
import org.junit.jupiter.api.Test;

import java.util.HashMap;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

class MonitorStoreTest {

    @Test
    void keepsOnlyCapacityAndEvictsOldest() {
        MonitorProperties props = new MonitorProperties();
        props.getSample().setBufferSize(5);            // 缓冲区容量设为 5
        MonitorStore store = new MonitorStore(props);

        for (int i = 1; i <= 8; i++) {
            store.add(snapshot(i));                    // 连续塞入 8 个快照
        }

        assertEquals(5, store.size());                 // 只保留 5 个
        assertEquals(8, store.latest().timestamp());   // 最新的是第 8 个
        List<MetricSnapshot> all = store.since(0);
        assertEquals(5, all.size());
        assertEquals(4, all.get(0).timestamp());        // 最旧的是第 4 个（1~3 已被淘汰）
        assertEquals(8, all.get(4).timestamp());
    }
    // ... 其余方法省略 ...
}
```

这个测试可读性很强：**方法名 `keepsOnlyCapacityAndEvictsOldest` 本身就是规格**——满了只保留容量大小、并淘汰最旧的。这正是第 1 章说的「活文档」。

注意末尾还有一个 `static` 工厂方法：

```java
// 代码来自 src/test/java/com/codegen/monitor/MonitorStoreTest.java
static MetricSnapshot snapshot(long ts) {
    Map<Double, Long> buckets = new HashMap<>();
    Map<String, double[]> byUri = new HashMap<>();
    Map<String, Double> business = new HashMap<>();
    return new MetricSnapshot(ts, 100, 1024, 50, 20, 0, 0, 0.1,
            100, 8, 0, 0, 0, 0, buckets, byUri, business);
}
```

它是个**测试辅助方法**，用来造测试数据，不是 `@Test`，所以不会被当作用例执行。

---

## 2.3 生命周期注解

很多时候，多个测试需要共享「准备环境 / 清理环境」的逻辑。JUnit 5 提供四个生命周期注解：

| 注解 | 执行时机 | 典型用途 |
|------|----------|----------|
| `@BeforeEach` | 每个 `@Test` **之前**各跑一次 | 构造被测对象、准备干净数据 |
| `@AfterEach` | 每个 `@Test` **之后**各跑一次 | 清理状态、关闭资源 |
| `@BeforeAll` | 整个类**所有测试之前**只跑一次 | 启动重量级资源（数据库、服务） |
| `@AfterAll` | 整个类**所有测试之后**只跑一次 | 释放重量级资源 |

真实例子：`MonitorControllerTest` 用 `@BeforeEach` / `@AfterEach` 管理用户上下文（代码来自 `src/test/java/com/codegen/controller/MonitorControllerTest.java` 第 49–60 行）：

```java
// 代码来自 src/test/java/com/codegen/controller/MonitorControllerTest.java
@BeforeEach
void setUp() {
    UserContext.setUserId(UID);                              // 每个用例前注入用户
    mvc = MockMvcBuilders.standaloneSetup(controller).build();
    lenient().when(permissionService.isSuperAdmin(UID)).thenReturn(true);
}

@AfterEach
void tearDown() {
    UserContext.clear();                                    // 每个用例后清空，避免污染下一个
}
```

这样每个测试都从「已登录的干净状态」开始，互不干扰。

### 为什么 `@BeforeAll` 必须 static？

`@BeforeAll` 标注的方法在整个测试类里**只执行一次**。而 JUnit 在运行测试时，每个 `@Test` 方法可能跑在**不同的实例**上（或者至少，`@BeforeAll` 的调用时机早于任何实例方法）。非静态方法属于「某个实例」，但此时还没有实例可依附，所以平台要求它必须是 `static`：

```java
// 此为通用示例
class DbTest {

    @BeforeAll
    static void startContainer() {        // 必须是 static，否则编译报错
        // 启动一次测试数据库容器，供全部用例复用
    }

    @Test
    void case1() { /* ... */ }
}
```

若你确实想让 `@BeforeAll` 作用于实例字段，可以改用**非静态 + `@TestInstance(PER_CLASS)`**（此为通用示例）：

```java
@TestInstance(TestInstance.Lifecycle.PER_CLASS)   // 整个类共用一个实例
class DbTest {
    @BeforeAll
    void startContainer() { /* 此时可访问实例字段 */ }
}
```

> 本书先记住铁律：**`@BeforeAll` / `@AfterAll` 默认必须 `static`**。`@BeforeEach` / `@AfterEach` 则不需要。

---

## 2.4 三段式：Arrange-Act-Assert

写测试最忌「一锅粥」。业界公认的最佳结构是 **AAA**：

1. **Arrange（准备）**：构造输入、打桩依赖、搭建前置状态；
2. **Act（执行）**：调用被测方法，拿到真实结果；
3. **Assert（断言）**：用 `assertEquals` 等校验结果符合预期。

用 `MonitorStoreTest` 的 `keepsOnlyCapacityAndEvictsOldest` 套进去看：

```java
// 此为对真实测试的三段式拆解（逻辑来自 MonitorStoreTest.java）
void keepsOnlyCapacityAndEvictsOldest() {
    // —— Arrange ——
    MonitorProperties props = new MonitorProperties();
    props.getSample().setBufferSize(5);
    MonitorStore store = new MonitorStore(props);

    // —— Act ——
    for (int i = 1; i <= 8; i++) {
        store.add(snapshot(i));
    }

    // —— Assert ——
    assertEquals(5, store.size());
    assertEquals(8, store.latest().timestamp());
}
```

把「准备 / 执行 / 断言」用空行或注释隔开，未来你或同事回看时，一眼就能分清「哪段是喂数据、哪段是测、哪段是验」。

---

## 本章小结

- 测试类就是普通 Java 类，`@Test` 方法返回 `void`、通常无参。
- 四个生命周期注解：`@BeforeEach`/`@AfterEach` 每用例一次，`@BeforeAll`/`@AfterAll` 全类一次且**必须 static**（或用 `PER_CLASS`）。
- 真实样板 `MonitorStoreTest` 展示了可读的方法名 + 静态数据工厂；`MonitorControllerTest` 展示了 `@BeforeEach`/`@AfterEach` 的环境隔离。
- 用 **Arrange-Act-Assert** 组织测试，清晰不混乱。

## ⚠️ 踩坑提示

**不要在 `@Test` 方法之间共享可变实例字段来「传递状态」。** 比如用例 A 写入 `this.result`，指望用例 B 读取它——JUnit 不保证测试执行顺序，而且多实例模式下 A、B 可能根本不是同一个对象，于是 B 读到 `null` 随机失败。每个测试都应当自给自足（self-contained）：在 `@BeforeEach` 或方法内自己准备数据，断言完就走，绝不依赖兄弟用例留下的副作用。
