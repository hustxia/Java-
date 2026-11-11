# 第 9 章 异常断言与超时控制

## 本章目标

- 用 `assertThrows` 验证「应当抛异常」的路径，并进一步断言异常信息；
- 用 `assertDoesNotThrow` 验证「不应抛异常」的契约；
- 区分 `assertTimeout`（不中断）与 `assertTimeoutPreemptively`（强杀线程）；
- 理解超时断言在集成/网络测试中的正确用法；
- 参考 codegen-server 中四处真实的异常断言写法。

异常路径往往比正常路径更藏 bug。一段「输入非法就该报错」的逻辑，如果没测，上线后可能要么吞异常、要么把堆栈甩给用户。JUnit 5 的 `Assertions` 把「抛异常」也变成了一等公民。

## 9.1 `assertThrows`：验证异常被抛出

`assertThrows(期望异常类, 被测lambda)` 返回捕获到的异常对象，可继续断言其消息或字段：

```java
import static org.junit.jupiter.api.Assertions.assertThrows;

@Test
void 未知指标应抛异常() {
    // 传入非法指标名，期望抛 BusinessException
    BusinessException ex = assertThrows(BusinessException.class,
            () -> SeriesMetric.of("evil"));
    assertTrue(ex.getMessage().contains("unknown"));   // 顺带校验异常信息
}
```

codegen-server 的 `SeriesMetricTest.java:27-32` 就是把「非法指标」作为独立等价类，连测三个边界值（`"evil"`、`null`、`" "`）：

```java
@Test
void rejectsUnknownOrMissingMetric() {
    assertThrows(BusinessException.class, () -> SeriesMetric.of("evil"));
    assertThrows(BusinessException.class, () -> SeriesMetric.of(null));
    assertThrows(BusinessException.class, () -> SeriesMetric.of(" "));
}
```

另一个真实例子来自路径安全防线 `GenScaffoldPathSafetyTest.java:24-34`。它把一批「应被拒绝的非法模块名」用循环遍历，每条都断言抛 `BusinessException`，并附上「应拒绝的模块名：xxx」作为失败信息——这正是第 5 章提到的边界值集合：

```java
@Test
@DisplayName("模块名拒绝 ../、绝对路径、分隔符与空值")
void moduleMustBeSingleSegment() {
    for (String bad : new String[]{"../../tmp/pwn", "..", ".", "", "   ",
            "a/b", "a\\b", "C:/Windows/Temp/pwn", "server;rm"}) {
        assertThrows(BusinessException.class,
                () -> GenScaffoldServiceImpl.safeModule(bad), "应拒绝的模块名：" + bad);
    }
    assertEquals("demo-server", GenScaffoldServiceImpl.safeModule(" demo-server "));
}
```

## 9.2 `assertDoesNotThrow`：验证契约「不崩」

有时你要保证「即便输入奇怪，代码也不应抛异常（而是优雅降级）」。`assertDoesNotThrow` 正是为此：

```java
import static org.junit.jupiter.api.Assertions.assertDoesNotThrow;

@Test
void 脱敏后仍是合法JSON() {
    String masked = LogAspect.maskSensitive(
            "{\"username\":\"admin\",\"password\":\"root123\"}");
    // 脱敏不能破坏 JSON 结构，否则下游解析会崩
    assertDoesNotThrow(() -> new ObjectMapper().readTree(masked),
            "脱敏破坏了 JSON：" + masked);
}
```

这是 codegen-server 的真实用例 `LogAspectMaskTest.java:56-62`：脱敏逻辑如果多删/少删了引号，就会产出非法 JSON，`assertDoesNotThrow` 把这条「结构性契约」钉死。

## 9.3 异常路径在 Web 层：返回码而非异常

注意「异常」不一定以 Java 异常形式冒泡到测试。在 Web 层，框架常把异常转成 HTTP 状态码。codegen-server 的 `MonitorControllerTest.java:62-72` 验证「非法 metric 必须返回 400」，用的是 MockMvc 的状态断言，而非 `assertThrows`：

```java
@Test
void invalidMetricReturns400() throws Exception {
    mvc.perform(get("/monitor/series").param("metric", "evil"))
            .andExpect(status().is(400));   // 异常被 @ExceptionHandler 转成 400
}

@Test
void missingMetricReturns400() throws Exception {
    mvc.perform(get("/monitor/series"))
            .andExpect(status().is(400));    // 缺参也走 400 路径
}
```

> 💡 经验：测「异常路径」前先看清异常在哪一层被处理。若在 Controller 被全局 `@ExceptionHandler` 接住并转成状态码，就该断言状态码；若异常直接抛出到调用方，才用 `assertThrows`。两者都是「异常契约」，只是断言形态不同。

## 9.4 超时断言：`assertTimeout` vs `assertTimeoutPreemptively`

超时断言用于「这个方法不应该跑太久」。JUnit 5 提供两种语义截然不同的 API：

```java
import org.junit.jupiter.api.Assertions;
import java.time.Duration;

@Test
void 软超时_不中断() {
    // assertTimeout：在调用线程执行，超时只标记失败，不杀线程
    Assertions.assertTimeout(Duration.ofMillis(100), () -> {
        slowTask();          // 即便跑了 5 秒，它也会跑完才报错
    });
}

@Test
void 硬超时_强杀线程() {
    // assertTimeoutPreemptively：另起线程执行，真超时就中断该线程
    Assertions.assertTimeoutPreemptively(Duration.ofMillis(100), () -> {
        slowTask();          // 到 100ms 会被强制停止
    });
}
```

关键差异：

- `assertTimeout`：被测代码在**当前线程**跑，超时后测试标记为失败，但代码其实**已经跑完**（甚至可能留下副作用）。适合「只想知道慢不慢、不关心是否真停得下来」的场景。
- `assertTimeoutPreemptively`：被测代码在**另一个线程**跑，超时后通过中断强制停止。适合「真要卡住死循环/挂死连接」的场景。代价是不能用 `ThreadLocal` 相关逻辑（换了线程），且中断可能被忽略。

> ⚠️ **踩坑提示**：`assertTimeoutPreemptively` 依赖线程中断。若被测代码吞掉了 `InterruptedException` 或不响应中断（比如阻塞在不可中断的 I/O），它**仍然停不下来**，超时强杀形同虚设。此时应改在被测代码内部加超时（如 `HttpClient` 的 `connectTimeout`），而不是指望测试层强杀。

## 9.5 超时在集成/网络测试中的用法（此为通用示例）

超时最该用在「会触及外部资源」的测试上：数据库、HTTP 接口、消息队列。这些地方一旦挂死，整个测试套件会被拖垮。下面是一份通用示例：

```java
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.Assertions;
import java.time.Duration;

class IntegrationTimeoutTest {   // 此为通用示例，未引用 codegen-server 真实代码

    @Test
    void 远程接口必须在2秒内返回() {
        Assertions.assertTimeoutPreemptively(Duration.ofSeconds(2), () -> {
            String resp = callRemoteApi();     // 可能网络拥塞/服务挂死
            Assertions.assertNotNull(resp);
        });
    }

    @Test
    void 数据库查询不应超时() {
        Assertions.assertTimeout(Duration.ofMillis(500), () -> {
            queryFromDb();                     // 软超时即可，便于定位慢 SQL
        });
    }
}
```

实践建议：单元测试（纯逻辑）**不要**加超时——它们本就该是毫秒级，加超时反而掩盖了设计问题；超时留给真正的集成/网络测试，作为「防挂死护栏」。

## 本章小结

- `assertThrows(异常类, lambda)` 验证「应抛异常」，返回值可继续断言消息；codegen 的 `SeriesMetricTest`、`GenScaffoldPathSafetyTest` 都用它守非法输入；
- `assertDoesNotThrow(lambda)` 守「不应崩」的契约，如 `LogAspectMaskTest` 的脱敏结构校验；
- Web 层异常常被转成 HTTP 状态码，应断言状态码（如 `MonitorControllerTest` 的 400），而非 `assertThrows`；
- `assertTimeout` 不中断线程只标记失败；`assertTimeoutPreemptively` 另起线程强杀，真超时；
- 超时断言优先用于集成/网络测试，纯单元测试不必加。

⚠️ **踩坑提示**：`assertThrows` 只验证「抛了异常」，**不验证抛的是不是你想要的那个分支**。若方法在「校验参数」和「真正执行」两处都可能抛同类型异常，光写 `assertThrows(BusinessException.class, ...)` 会通过，但其实炸在了后面。务必再用 `ex.getMessage()` 或异常字段区分分支，像 9.1 的 `rejectsUnknownOrMissingMetric` 那样，把 `null`/`" "`/`"evil"` 分开成独立用例，才能确认每一条非法路径都被正确拦截。
