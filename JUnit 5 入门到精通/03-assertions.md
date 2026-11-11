# 第 3 章 断言全家桶 Assertions

## 本章目标

- 熟悉 `org.junit.jupiter.api.Assertions` 下的常用断言方法；
- 理解 `assertAll` 的「分组断言不短路」与 `assertThrows` / `assertDoesNotThrow` 的异常校验；
- 用真实文件 `MonitorStoreTest.java` 的断言作为样板，再补充 `assertAll` 与 `assertThrows` 的通用示例。

---

## 3.1 什么是断言

断言（Assertion）是测试的「验收点」：你向 JUnit 声明「此处应当成立」。若成立，测试继续；若不成立，该方法**立即失败**并抛 `AssertionFailedError`。所有断言都来自 `org.junit.jupiter.api.Assertions`，通常通过静态导入使用：

```java
import static org.junit.jupiter.api.Assertions.assertEquals;
```

---

## 3.2 相等与不等

| 方法 | 用途 |
|------|------|
| `assertEquals(a, b)` | 断言 `a` 与 `b` 相等（用 `Object.equals`） |
| `assertNotEquals(a, b)` | 断言不相等 |
| `assertSame(a, b)` | 断言**同一个对象引用**（`==`） |

> `assertEquals` 比的是「值相等」，`assertSame` 比的是「内存里是不是同一个对象」。比较 `new Integer(1)` 与 `new Integer(1)` 时，`assertEquals` 通过、`assertSame` 失败。

真实用例来自 `MonitorStoreTest`（代码来自 `src/test/java/com/codegen/monitor/MonitorStoreTest.java` 第 28–33 行）：

```java
// 代码来自 src/test/java/com/codegen/monitor/MonitorStoreTest.java
assertEquals(5, store.size());                 // 缓冲区只保留 5 个
assertEquals(8, store.latest().timestamp());   // 最新快照时间戳是 8
List<MetricSnapshot> all = store.since(0);
assertEquals(5, all.size());
assertEquals(4, all.get(0).timestamp());       // 最旧的是第 4 个
assertEquals(8, all.get(4).timestamp());
```

注意它断言的是**数值字段**（`size()`、`timestamp()`），而不是整个对象——这比 `assertEquals(expected, actual)` 整对象比对更聚焦、失败信息更清晰。

---

## 3.3 真假与空值

| 方法 | 用途 |
|------|------|
| `assertTrue(cond)` / `assertFalse(cond)` | 断言布尔条件 |
| `assertNull(x)` / `assertNotNull(x)` | 断言引用为空 / 非空 |

`MonitorStoreTest` 里测「尚无样本时」的状态（代码来自 `src/test/java/com/codegen/monitor/MonitorStoreTest.java` 第 52–58 行）：

```java
// 代码来自 src/test/java/com/codegen/monitor/MonitorStoreTest.java
@Test
void latestIsNullBeforeFirstSample() {
    MonitorStore store = new MonitorStore(new MonitorProperties());
    assertEquals(null, store.latest());        // 还没有数据时 latest 为 null
    assertEquals(0, store.lastSampleAt());
    assertTrue(store.size() == 0);             // 大小为 0
}
```

> 小建议：校验「为空」优先用 `assertNull(store.latest())` 而非 `assertEquals(null, store.latest())`，语义更直白。

---

## 3.4 数组与文本行匹配

| 方法 | 用途 |
|------|------|
| `assertArrayEquals(a, b)` | 断言两个数组逐元素相等 |
| `assertLinesMatch(expected, actual)` | 断言 `List<String>` 逐行相等，支持正则与占位符 |

`assertLinesMatch` 特别适合校验多行输出（如日志、CSV）。此为通用示例：

```java
// 此为通用示例
@Test
void linesMatchWithRegex() {
    List<String> out = List.of("id=1", "id=2", "id=3");
    assertLinesMatch(
        List.of("id=\\d+", "id=\\d+", "id=\\d+"),   // 每行用正则匹配
        out);
}
```

---

## 3.5 超时：assertTimeout

有时你要确认某段逻辑「不能太慢」。JUnit 5 提供两种超时断言：

```java
// 此为通用示例
@Test
void timeoutExample() {
    // 非抢占式：等 exec 跑完再判断是否超时（会真实执行完）
    assertTimeout(Duration.ofMillis(100), () -> {
        Thread.sleep(50);
        return "ok";
    });

    // 抢占式：超过时限立刻中断并失败（不会等它跑完）
    assertTimeoutPreemptively(Duration.ofMillis(100), () -> {
        Thread.sleep(500);   // 到这里就会被强制打断
        return "never";
    });
}
```

- `assertTimeout`：**先执行完再判定**，执行时长真实发生；
- `assertTimeoutPreemptively`：**到点就掐断线程**，适合卡死风险场景，但不适用于依赖共享线程池/静态状态的代码（可能被误杀）。

---

## 3.6 分组断言：assertAll（不短路）

普通断言一旦失败就**立即退出方法**，后面的断言不再执行，你一次只能看到第一个错误。`assertAll` 会把一组断言**全部跑完**，再汇总所有失败：

```java
// 此为通用示例
@Test
void groupedAssertions() {
    MetricSnapshot s = store.latest();
    assertAll("快照完整性检查",
        () -> assertEquals(8, s.timestamp()),
        () -> assertEquals(100, s.cpu()),
        () -> assertEquals(1024, s.memory()),
        () -> assertTrue(s.latency() >= 0)
    );
}
```

如果四个里有两个失败，报告会一次性列出**全部**问题，而不是「改完一个再跑才发现下一个也错」。这能显著减少「修一个 bug 跑一次」的往返。

---

## 3.7 异常：assertThrows / assertDoesNotThrow

校验「这段代码**应当**抛异常」是测试边界的刚需：

```java
// 此为通用示例
@Test
void rejectsNegativeBufferSize() {
    MonitorProperties props = new MonitorProperties();
    props.getSample().setBufferSize(-1);    // 非法输入

    // 断言构造时抛出 IllegalArgumentException，并可进一步校验异常信息
    IllegalArgumentException ex = assertThrows(
        IllegalArgumentException.class,
        () -> new MonitorStore(props));
    assertTrue(ex.getMessage().contains("bufferSize"));
}
```

- `assertThrows(expectedType, executable)` 返回被抛出的异常对象，可继续断言其 message / cause；
- 反方向用 `assertDoesNotThrow(executable)`，确认「正常路径不该炸」。

---

## 本章小结

- `Assertions` 提供：相等/不等（`assertEquals`/`assertSame`）、真假与空值（`assertTrue`/`assertNotNull`）、数组与行匹配、超时（`assertTimeout` 系列）、分组（`assertAll`）、异常（`assertThrows`/`assertDoesNotThrow`）。
- 真实文件 `MonitorStoreTest` 用 `assertEquals` / `assertTrue` 验证了环形缓冲的「容量上限、最旧淘汰、空状态」等核心行为。
- `assertAll` 不短路，一次暴露全部失败；`assertThrows` 用来钉死异常路径。

## ⚠️ 踩坑提示

**`assertEquals` 比较浮点数别直接用 `==` 精度。** `assertEquals(0.1 + 0.2, 0.3)` 会失败，因为 IEEE 754 下 `0.1+0.2=0.30000000000000004`。`Assertions` 提供了带误差的 `assertEquals(double expected, double actual, double delta)` 重载，或者断言前用 `BigDecimal`。同理，`assertArrayEquals` 比较对象数组时依赖元素自身的 `equals`，若元素是没重写 `equals` 的 POJO，会退化成「引用比较」而莫名其妙失败——务必确认元素类型正确实现了相等语义。
