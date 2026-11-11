# 第 10 章 测试替身：Dummy、Stub、Spy、Mock、Fake

## 本章目标

读完本章你能：

- 说清楚「为什么测试需要替身」而不是处处连真库；
- 区分测试替身（Test Double）的五大类——Dummy、Stub、Spy、Mock、Fake；
- 看懂 codegen-server 的 `MonitorControllerTest` 里 `@Mock` 到底替了谁、为什么替；
- 在真实项目里根据场景选对替身类型。

## 为什么需要测试替身

设想你给 `MonitorController` 写一个单元测试，它依赖四个协作者：`MonitorStore`（内存指标缓冲）、`MonitorWindow`（滑动窗口）、`MonitorProperties`（采样配置）、`PermissionService`（权限判定）。如果直接 `new MonitorController()` 然后跑，会发生三件痛苦的事：

1. **无法隔离**：任意一个依赖出 bug，控制器测试跟着红，你分不清是谁的问题。
2. **无法提速**：真依赖里可能连数据库、读文件、发网络请求，单测从毫秒级变成秒级。
3. **不可控边界**：你想测「缺权限应返回 403」，但真实权限服务永远返回「有权限」，这个分支永远覆盖不到。

测试替身就是把这些「真实、缓慢、不可控」的依赖换成「可控、快速、听话」的替代品，让你只验证**被测对象本身的逻辑**。这正是 codegen-server 在 `src/test/java/com/codegen/controller/MonitorControllerTest.java` 开头就写下的动机——它用 Mockito 的 `@Mock` 把四个依赖全部替掉：

```java
// 来源：src/test/java/com/codegen/controller/MonitorControllerTest.java
@ExtendWith(MockitoExtension.class)
class MonitorControllerTest {
    @Mock MonitorStore store;              // 替掉指标缓冲
    @Mock MonitorWindow window;            // 替掉滑动窗口
    @Mock MonitorProperties props;         // 替掉采样配置
    @Mock PermissionService permissionService; // 替掉权限判定
    @InjectMocks MonitorController controller;  // 把上面的替身注入控制器
}
```

本章不展开 Mockito 注解（第 11 章细讲），你只需先建立观念：**`@Mock` 生成的四个对象就是测试替身**，它们长得像真依赖、方法签名一模一样，但行为完全由你编排。下面把替身的五大类逐一拆开。

⚠️ **踩坑提示**：替身不是「越少真越好」。如果一个依赖本身就是纯函数、无副作用、毫秒返回（比如 `MonitorWindow.clampMinutes`），你完全可以不用替身直接 `new`。过度 mock 会让测试只验证「你写的 stub 是否和 stub 一致」，而非真实行为。

## 五大类：一张对照表

| 类型 | 中文 | 它做什么 | 典型用途 |
|------|------|----------|----------|
| Dummy | 占位哑元 | 只用来填充参数，从不真正被调用 | 满足方法签名但无意义的对象 |
| Stub | 桩 | 返回你预设的 canned 数据 | 让依赖「吐」出特定结果 |
| Spy | 间谍 | 部分真实运行，同时**记录**被怎么调用 | 既要真逻辑又要观察调用 |
| Mock | 模拟 | 不实现真逻辑，专注**验证行为**是否被调用 | 断言「某个方法以某参数被调了 N 次」 |
| Fake | 假实现 | 一个**轻量但可用**的真实实现（如内存库） | 替代重型依赖（真数据库）跑通整条链路 |

## Dummy：占位哑元

Dummy 是最「懒」的替身——它存在的唯一理由是让代码能编译/能传参。例如有个方法签名要求传一个 `AuditLog`，但你要测的逻辑根本不碰它。

```java
// 以下为通用示例（非 codegen-server 代码）
class AuditLogDummy implements AuditLog {
    @Override public void record(String event) { /* 什么都不做 */ }
}

@Test
void createsOrderIgnoringLog() {
    OrderService svc = new OrderService(new AuditLogDummy()); // 仅为满足构造器
    Order o = svc.create("SKU-1", 2);
    assertEquals("SKU-1", o.getSku());
}
```

## Stub：返回预设数据

Stub 的重点是「喂数据」。`MonitorControllerTest` 里大量使用 Stub 思想——用 `when(...).thenReturn(...)` 让 `store`、`window` 返回特定快照，从而把控制器逼到某个分支。下面用通用示例展示 Stub 的本质：

```java
// 以下为通用示例（非 codegen-server 代码）
interface ExchangeRate { double rate(String from, String to); }

class FixedRateStub implements ExchangeRate { // 永远返回 7.2，可控
    @Override public double rate(String from, String to) { return 7.2; }
}

@Test
void priceInCnyUsesStubbedRate() {
    PriceCalculator calc = new PriceCalculator(new FixedRateStub());
    assertEquals(72.0, calc.toCny(10.0)); // 10 美元 × 7.2
}
```

## Spy：部分真实 + 记录

Spy 与 Mock 最大的区别是：Spy 背后有**真实对象**，只有你显式 stub 的方法才被替换，其余方法照常运行；同时它能记录「方法被调了几次、传了什么参」。

```java
// 以下为通用示例（非 codegen-server 代码）
class ListSpy extends ArrayList<String> {
    int addCalls = 0;
    @Override public boolean add(String e) { addCalls++; return super.add(e); } // 真逻辑 + 记录
}

@Test
void spyRecordsRealBehavior() {
    ListSpy spy = new ListSpy();
    spy.add("a"); spy.add("b");
    assertEquals(2, spy.size());     // 真实逻辑仍在
    assertEquals(2, spy.addCalls);   // 同时记录到了调用次数
}
```

## Mock：专注行为验证

Mock 不实现任何真逻辑，`when` 之外的方法默认返回空/null。它的杀手锏是 `verify`——「你到底有没有按预期调用依赖」。这正是 codegen-server 验证「minutes 越界被钳到 30」的核心：

```java
// 来源：src/test/java/com/codegen/controller/MonitorControllerTest.java（节选）
@Test
void seriesClampsMinutesTo30() throws Exception {
    when(window.of(anyInt())).thenReturn(Collections.emptyList());
    when(window.intervalSeconds()).thenReturn(5.0);
    when(window.warmup(anyList(), anyInt())).thenReturn(true);
    mvc.perform(get("/monitor/series").param("metric", "jvm.heap").param("minutes", "999"))
            .andExpect(status().isOk());
    verify(window).of(30);          // 断言控制器只向窗口要了 30 分钟
    verify(window, never()).of(999); // 断言它绝没有真的传 999 进去
}
```

这里 `window` 就是 Mock：`of(30)` 必须被调用一次，`of(999)` 永远不出现——控制器内部的 `clampMinutes` 钳制逻辑被严格证明。

## Fake：轻量可用实现

Fake 是「能用的假货」，最经典的就是用内存 Map 实现 `Repository`，替代真数据库。它跑得快、行为正确，只是不持久化。

```java
// 以下为通用示例（非 codegen-server 代码）
class InMemoryUserRepo implements UserRepository { // 轻量但可用的假实现
    private final Map<Long, User> db = new HashMap<>();
    @Override public void save(User u) { db.put(u.getId(), u); }
    @Override public User find(Long id) { return db.get(id); }
}

@Test
void fakeRepoPersistsInMemory() {
    UserRepository repo = new InMemoryUserRepo();
    repo.save(new User(1L, "alice"));
    assertEquals("alice", repo.find(1L).getName());
}
```

codegen-server 的契约测试（第 14 章）用 `@TempDir` 沙箱 + 真 MySQL 做端到端，但如果你只想测某个 service 而不想连库，写一个 `InMemoryXxxMapper` 当 Fake 是绝佳选择。

## 选型速记：一句话决定用哪个

面对一个依赖，按下面顺序问自己：

1. 这个依赖在用例里**根本不会被调用**，只是用来满足构造器/方法签名？→ **Dummy**。
2. 你需要它**吐出特定数据**让被测对象进入某个分支？→ **Stub**（`when().thenReturn()`）。
3. 你想**保留它的真实逻辑**，同时**观察**它被怎么调用？→ **Spy**（`Mockito.spy()`）。
4. 你只关心**某个方法是否被以某参数调用了**（行为契约）？→ **Mock**（`when` + `verify`）。
5. 你想要一个**真正能跑通、但很轻量**的替代（比如不连真库）？→ **Fake**（手写内存实现）。

codegen-server 的 `MonitorControllerTest` 几乎只用到 Mock：因为控制器的逻辑是「编排四个依赖 + 钳制参数 + 鉴权」，没有需要保留真实实现的环节，所以四个依赖全 `@Mock`，再用 `verify` 锁行为。而它的契约测试（第 14 章）反过来大量用真实 Bean + 真 MySQL，因为那一层要验证的是「真实链路不破坏」。

## 本章小结

- 替身解决三件事：**隔离被测对象、提速、把不可控边界变可控**。
- 五大类按需取用：只占位用 Dummy；喂数据用 Stub；想保留真逻辑又观察调用用 Spy；只验证行为用 Mock；想要可用替代实现用 Fake。
- codegen-server 的 `MonitorControllerTest` 用 `@Mock` 把四个协作者全部替换，再用 `verify` 锁住「越界入参被钳制」这类行为契约，是 Mock 用法的标准范例。

⚠️ **踩坑提示**：别把 Mock 当 Stub 用错方向。Stub 回答「返回什么」，Mock 回答「调了没有」。如果你只 `when().thenReturn()` 从不 `verify`，那其实在用 Mock 当 Stub——没问题；但反之如果你只 `verify` 不 `when`，未 stub 的方法返回 null/空，容易触发 NPE。先想清楚你要验证的是「输出」还是「交互」。
