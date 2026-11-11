# 第 11 章 Mockito 实战：把 MonitorControllerTest 逐行讲透

## 本章目标

本章以 codegen-server 真实的 `src/test/java/com/codegen/controller/MonitorControllerTest.java` 为唯一蓝本，逐行拆解：

- `@ExtendWith(MockitoExtension.class)` 为何是 Mockito 测试的入场券；
- `@Mock` 与 `@InjectMocks` 如何协作（构造器注入 vs 字段注入）；
- `when(...).thenReturn(...)` / `thenThrow(...)` 怎么编排桩数据；
- `verify(mock).method(...)` 与 `verify(mock, never())` 如何锁行为；
- `ArgumentMatchers`（anyInt / anyList / eq）怎么用才不报错；
- `lenient()` 为何能救你于「unnecessary stubbing」报错。

## 先看全貌：这个测试在守护什么

`MonitorControllerTest` 的注释写明它要验证三条硬断言（AC-5）：

- 非法 `metric` → **400**；
- 缺权限 → **403**；
- `minutes` 越界（如 999）→ 被**钳到 30** 再交给窗口。

它用 standalone MockMvc（第 13 章细讲）直接吃控制器的 `@ExceptionHandler`，不拉 Spring 上下文，因此秒级返回。下面把它的 109 行拆成零件。

## 入场券：@ExtendWith(MockitoExtension.class)

```java
// 来源：MonitorControllerTest.java:37
@ExtendWith(MockitoExtension.class)
class MonitorControllerTest {
```

JUnit 5 的扩展机制（`Extension`）让第三方框架接入生命周期。`MockitoExtension` 干两件事：① 在**每个测试方法前**初始化所有 `@Mock`/`@InjectMocks` 字段；② 执行 Mockito 的严格桩检查（strict stubbing）。没有这行注解，`@Mock` 字段会是 `null`，一跑就 NPE。

## 声明替身：@Mock

```java
// 来源：MonitorControllerTest.java:40-43
@Mock MonitorStore store;
@Mock MonitorWindow window;
@Mock MonitorProperties props;
@Mock PermissionService permissionService;
```

每个 `@Mock` 都会由 Mockito 动态生成一个**实现了该接口的代理对象**。它现在「长得像真依赖、方法签名全在」，但默认行为是：返回类型返回 null/空集合/0，void 方法什么都不做。你接下来要用 `when` 给它「喂」行为。

## 注入被测对象：@InjectMocks

```java
// 来源：MonitorControllerTest.java:44
@InjectMocks MonitorController controller;
```

`@InjectMocks` 会 `new MonitorController()`，并把**同测试类里**的 `@Mock` 对象按类型塞进去。codegen-server 的 `MonitorController` 用字段注入（`@Autowired` 四个私有字段，见 `MonitorController.java:47-54`），Mockito 通过反射把 `store/window/props/permissionService` 填进对应字段。

⚠️ **踩坑提示**：`@InjectMocks` 默认**先尝试构造器注入，失败才回退字段注入**。如果你的类写了带参构造器，Mockito 只会用构造器，不会再去填字段——此时没被构造器覆盖的 `@Autowired` 字段会是 null。codegen-server 这里没有构造器，所以走字段注入没问题。优先推荐写**带参构造器 + `final` 字段**，让注入路径唯一、可测更稳。

## 准备与清理：setUp / tearDown

```java
// 来源：MonitorControllerTest.java:46-60
private final Long UID = 2L;
private MockMvc mvc;

@BeforeEach
void setUp() {
    UserContext.setUserId(UID);                       // 模拟当前登录用户
    mvc = MockMvcBuilders.standaloneSetup(controller).build();
    lenient().when(permissionService.isSuperAdmin(UID)).thenReturn(true); // 默认超管
    lenient().when(props.getSample()).thenReturn(new MonitorProperties().getSample());
}

@AfterEach
void tearDown() {
    UserContext.clear();                              // 清 ThreadLocal，防串味
}
```

两点值得记：

1. `UserContext` 是 ThreadLocal 式的上下文，`@AfterEach` 必须 `clear()`，否则测试之间会互相污染（下一个用例可能还以为自己是 UID=2）。
2. 这里出现了 `lenient()`，先记住它用于「放宽严格桩检查」，原理见本章末尾。

## 打桩：when(...).thenReturn(...) 与 thenThrow(...)

`when(...).thenReturn(...)` 的意思是「当某个方法以某参数被调用时，返回这个值」。最典型在 `overviewReturns200ForSuperAdmin`：

```java
// 来源：MonitorControllerTest.java:82-88
@Test
void overviewReturns200ForSuperAdmin() throws Exception {
    when(store.latest()).thenReturn(null);     // 还没采样点
    when(store.capacity()).thenReturn(360);    // 缓冲容量 360
    when(store.size()).thenReturn(0);          // 当前 0 点
    when(store.lastSampleAt()).thenReturn(0L); // 从未采样
    mvc.perform(get("/monitor/overview")).andExpect(status().isOk());
}
```

对照 `MonitorController.overview()`（`MonitorController.java:58-71`）：它读 `store.latest()` 拿到 `null` 就提前返回 `Result.ok(vo)`，于是 4 个 stub 把这段代码逼到「无数据」分支，断言 200。

`thenThrow(...)` 形态用于「依赖抛异常时控制器怎么表现」。通用示例：

```java
// 以下为通用示例（非 codegen-server 代码）
when(permissionService.permissionsOf(UID)).thenThrow(new IllegalStateException("down"));
// 随后断言控制器把异常转成 500/友好错误，而非直接崩溃
```

## 行为验证：verify 与 never

Mock 的灵魂不在「返回什么」，而在「**调没调、怎么调**」。`seriesClampsMinutesTo30` 是全书最漂亮的一处：

```java
// 来源：MonitorControllerTest.java:90-99
@Test
void seriesClampsMinutesTo30() throws Exception {
    when(window.of(anyInt())).thenReturn(Collections.emptyList());
    when(window.intervalSeconds()).thenReturn(5.0);
    when(window.warmup(anyList(), anyInt())).thenReturn(true);
    mvc.perform(get("/monitor/series").param("metric", "jvm.heap").param("minutes", "999"))
            .andExpect(status().isOk());
    verify(window).of(30);          // 控制器必须向窗口要 30 分钟
    verify(window, never()).of(999); // 绝不能把 999 原样传进去
}
```

`verify(window).of(30)` 证明：即便用户传 `minutes=999`，控制器内部的 `MonitorWindow.clampMinutes` 也把它钳成了 30。`verify(window, never()).of(999)` 反向证明越界值从未泄漏。这就是**行为契约**——比「返回空列表」更有说服力。

再看权限分支如何用 `verify` 的隐性力量（此处主要靠 `when` 切换返回）：

```java
// 来源：MonitorControllerTest.java:74-79
@Test
void deniedWithoutViewPermissionReturns403() throws Exception {
    when(permissionService.isSuperAdmin(UID)).thenReturn(false);          // 非超管
    when(permissionService.permissionsOf(UID)).thenReturn(Collections.emptySet()); // 且无菜单权限
    mvc.perform(get("/monitor/overview")).andExpect(status().is(403));
}
```

## 参数匹配器：anyInt / anyList / eq

当桩或验证里某个参数你「不关心具体值，只关心类型」时，用 `ArgumentMatchers`：

- `anyInt()`：匹配任意 `int`；
- `anyList()`：匹配任意 `List`；
- `eq(x)`：精确匹配值 `x`（默认就是精确匹配，但混用匹配器时必须显式 `eq`）。

⚠️ **踩坑提示**：**在一个方法调用的参数列表里，要么全用匹配器，要么全用字面值，不能混搭**。下面会编译报错：

```java
// 错误示例：window.of 第一个用 anyInt()，第二个却用字面量 5 —— 编译失败
// when(window.of(anyInt(), 5)).thenReturn(...);
// 正确写法：when(window.of(anyInt(), eq(5))).thenReturn(...);
```

`seriesClampsMinutesTo30` 里 `window.warmup(anyList(), anyInt())` 两个参数都用匹配器，是合规写法。

## 救火队员：lenient() 与 unnecessary stubbing

回到 `setUp`：

```java
// 来源：MonitorControllerTest.java:53-54
lenient().when(permissionService.isSuperAdmin(UID)).thenReturn(true);
lenient().when(props.getSample()).thenReturn(new MonitorProperties().getSample());
```

默认 `MockitoExtension` 开启**严格桩检查**：如果某个 `when` 定义的桩在测试里**一次都没被用到**，测试会失败，报 `UnnecessaryStubbingException`。但 `setUp` 里准备的超管桩，在 `deniedWithoutViewPermissionReturns403` 等用例里会被**重新打桩覆盖**，于是「原桩没被用」会误伤。

`lenient()` 就是告诉 Mockito：「这个桩我允许它不被使用」。经验法则：**写在 `@BeforeEach` 通用准备里的桩，多半要加 `lenient()`；写在单个 `@Test` 里的桩，保持严格以暴露无效桩**。

## 本章小结

- `MockitoExtension` 是入场券；`@Mock` 造替身，`@InjectMocks` 把替身注入被测类（优先构造器注入）。
- `when().thenReturn()/thenThrow()` 编排「返回什么」；`verify(mock).method()` 与 `verify(mock, never())` 锁定「行为是否发生」。
- 参数匹配器（`anyInt/anyList/eq`）需整列统一，不能和字面量混用。
- `@BeforeEach` 里的通用桩用 `lenient()` 包一层，避免 strict stubbing 误报 `UnnecessaryStubbingException`。

⚠️ **踩坑提示**：`verify` 默认要求「至少一次」。要精确断言次数请用 `verify(mock, times(2))`、`atMostOnce()`、`never()`。另外 `verify` 作用在**最后一次 `when` 之后**的方法调用快照上——如果你想验证「某方法在 stub 切换前被调用过」，需要把 `verify` 顺序排对，或拆成两个用例，否则会出现「明明调了却 verify 不到」的假阴性。
