# 第 13 章 Web 层测试：用 MockMvc 秒级验证控制器

## 本章目标

- 弄清 `MockMvcBuilders.standaloneSetup` 与 `webAppContextSetup` 的本质区别；
- 用真实 `MonitorControllerTest` 看懂：不发真实 HTTP、不拉 Spring，也能测控制器；
- 掌握请求构造（get/post、param、contentType）与断言（status、content、jsonPath）；
- 理解「为什么越界入参钳到 30、非法 metric 回 400、缺权限回 403」能被硬断言锁死。

## 两种装配方式：standalone vs webAppContextSetup

测 Spring MVC 控制器有两套武器，差别巨大：

| 方式 | 加载什么 | 速度 | 吃 @ExceptionHandler？ | 适合 |
|------|----------|------|------------------------|------|
| `standaloneSetup(controller)` | **只**实例化你给的控制器 + 基础 MVC | 毫秒级 | ✅ 直接生效 | 纯控制器逻辑/边界断言 |
| `webAppContextSetup(ctx)` | 整个 Spring Web 上下文 | 秒~十秒级 | ✅（需 `@SpringBootTest`） | 验证装配、拦截器、过滤器 |

`webAppContextSetup` 必须配合 `@SpringBootTest` 拿到 `WebApplicationContext`，启动重。而 `standaloneSetup` **不碰 Spring 容器**，你自己把控制器 `new` 出来塞进去——这正是 codegen-server 的选择。

```java
// 来源：MonitorControllerTest.java:52
mvc = MockMvcBuilders.standaloneSetup(controller).build();
```

`controller` 是 `@InjectMocks` 出来的实例（四个依赖已换成 mock），standalone 把它的 `@ExceptionHandler` 直接纳入处理链。于是控制器里那段 `handleBusiness`（`MonitorController.java:301-310`）能在测试里真实生效——非法 `metric` 抛 `BusinessException`，被它翻译成 400。

⚠️ **踩坑提示**：standalone 模式**不会**加载全局 `@ControllerAdvice`、拦截器、`@ExceptionHandler` 之外的异常处理。codegen-server 把监控接口的异常处理直接写在控制器内部的 `@ExceptionHandler` 上，所以 standalone 能覆盖；如果你的异常处理在独立 `GlobalExceptionHandler` 类里，standalone 测就吃不到，得改用 `webAppContextSetup` 或手动 `.setControllerAdvice(...)`。

## 为什么它不拉 Spring 也能测控制器

`MonitorController` 的逻辑是「编排四个依赖 + 钳制参数 + 鉴权 + 组装 VO」。这些都不依赖 Spring 的代理、事务、AOP——它只是个普通的 `@RestController` 类。把依赖换成 mock 后，standalone MockMvc 直接反射调用方法、模拟 `HttpServletRequest`，完全绕开容器。

好处在 `MonitorControllerTest` 的注释里说得很直白：

```
// 来源：MonitorControllerTest.java:34-35
// 用 standalone MockMvc 直接吃控制器的 @ExceptionHandler，不拉 Spring 上下文，
// 因此本测试秒级返回，可纳入 mvn test 常规门禁。
```

这意味着它能被 `mvn test` 作为**零成本门禁**——不像契约测试需要连库、重建 schema。

## 构造请求：get / post / param / contentType

MockMvc 的请求构造非常贴近真实 HTTP：

```java
// 来源：MonitorControllerTest.java:64-65（节选）
mvc.perform(get("/monitor/series").param("metric", "evil"))  // GET + 查询参数
        .andExpect(status().is(400));
```

- `get(...)` / `post(...)`：HTTP 方法；
- `.param("k","v")`：表单/查询参数（对应 `@RequestParam`）；
- `.contentType(MediaType.APPLICATION_JSON)` + `.content(json)`：发 JSON 体（契约测试里大量使用，如 `GenPipelineContractTest` 的 `post("/gen/write")`）。

## 硬断言一：非法 metric → 400

`/monitor/series` 的 `metric` 经 `SeriesMetric.of(metric)` 解析，非法值抛 `BusinessException`（无对应枚举）。控制器 `@ExceptionHandler` 把非鉴权类异常映射成 400：

```java
// 来源：MonitorControllerTest.java:62-72
@Test
void invalidMetricReturns400() throws Exception {
    mvc.perform(get("/monitor/series").param("metric", "evil"))
            .andExpect(status().is(400));
}
@Test
void missingMetricReturns400() throws Exception {
    mvc.perform(get("/monitor/series"))   // 连 metric 都不传
            .andExpect(status().is(400));
}
```

对照 `MonitorController.series()`（`MonitorController.java:99-103`）：`SeriesMetric.of(metric)` 对 `null` 或非法串都会抛异常，因此两个用例都命中 400。这正是 AC-5 的第一条硬断言。

## 硬断言二：缺权限 → 403

`require()`（`MonitorController.java:287-295`）先判超管，再判 `monitor:view` 权限。测试在 `setUp` 默认把 `isSuperAdmin` 设为 true，但在本用例里**覆盖**成 false 且权限集为空：

```java
// 来源：MonitorControllerTest.java:74-79
@Test
void deniedWithoutViewPermissionReturns403() throws Exception {
    when(permissionService.isSuperAdmin(UID)).thenReturn(false);
    when(permissionService.permissionsOf(UID)).thenReturn(Collections.emptySet());
    mvc.perform(get("/monitor/overview")).andExpect(status().is(403));
}
```

`require()` 抛 `BusinessException(ResultCode.FORBIDDEN)`，被 `@ExceptionHandler` 翻译成 403（`MonitorController.java:304`）。这条断言锁住了「监控接口不能裸奔给任意登录用户」。

## 硬断言三：minutes 越界钳到 30

这是行为验证的精华。`/monitor/series?minutes=999` 应当被 `MonitorWindow.clampMinutes` 钳到合法上限 30，控制器再拿 30 去查窗口：

```java
// 来源：MonitorControllerTest.java:90-99
@Test
void seriesClampsMinutesTo30() throws Exception {
    when(window.of(anyInt())).thenReturn(Collections.emptyList());
    when(window.intervalSeconds()).thenReturn(5.0);
    when(window.warmup(anyList(), anyInt())).thenReturn(true);
    mvc.perform(get("/monitor/series").param("metric", "jvm.heap").param("minutes", "999"))
            .andExpect(status().isOk());
    verify(window).of(30);          // 必须只查了 30 分钟窗口
    verify(window, never()).of(999); // 越界值绝不能泄漏给窗口
}
```

这里把「返回值断言」和「行为断言」结合：既确认 200，又用 `verify` 证明越界值被钳制、没污染下游。

## 更多断言：status / content / jsonPath

除 `status()` 外，常用断言还有：

- `content().string(...)` / `content().json(...)`：校验响应体；
- `jsonPath("$.code").value(200)`：按 JSON 路径抽取字段（契约测试大量使用）；
- `view().name("x")`：测返回视图名。

契约测试里 `GenPipelineContractTest.callJson` 就靠读响应体做 JSON 断言：

```java
// 来源：GenPipelineContractTest.java:793-799（节选）
private JsonNode callJson(MockHttpServletRequestBuilder builder) throws Exception {
    MvcResult result = mockMvc.perform(builder).andReturn();
    String body = result.getResponse().getContentAsString(UTF_8);
    return json.readTree(body);   // 再对 JsonNode 做 assertEquals/jsonPath 式断言
}
```

通用示例（jsonPath）：

```java
// 以下为通用示例（非 codegen-server 代码）
mvc.perform(get("/api/order/1"))
   .andExpect(status().isOk())
   .andExpect(jsonPath("$.data.sku").value("SKU-1"))
   .andExpect(jsonPath("$.data.qty").value(2));
```

## 真实对照：契约测试走的是 webAppContextSetup 路线

与 `MonitorControllerTest` 相反，codegen-server 的 `GenPipelineContractTest` 用 `@SpringBootTest` + `@AutoConfigureMockMvc` 拿 MockMvc——这背后正是 `webAppContextSetup`：它要**真实装配整个 Web 上下文**，因为要验证「写盘后台账行数 == 磁盘文件数」这种跨越 Controller→Service→Mapper→磁盘的端到端事实。

```java
// 来源：GenPipelineContractTest.java:62-69
@SpringBootTest
@AutoConfigureMockMvc(addFilters = false)
@ActiveProfiles("test")
class GenPipelineContractTest {
    @Autowired private MockMvc mockMvc;   // 由 Spring 容器装配，含全部过滤器/拦截器（addFilters=false 关掉安全链）
}
```

注意 `addFilters = false`：它关掉 Spring Security 过滤器链，让测试能直接打接口而不必先过登录鉴权——因为契约测试关心的是「业务链路对不对」，不是「鉴权过不过」。这正是 standalone 与 webAppContextSetup 两种路线在 codegen-server 里的现实分工：**轻量边界断言用 standalone，重链路事实用 webAppContextSetup**。

## 本章小结

- `standaloneSetup(controller)` 不启 Spring、毫秒级、直接吃控制器内 `@ExceptionHandler`，是纯控制器逻辑测试的首选；`webAppContextSetup` 需 `@SpringBootTest`，适合验装配/拦截器。
- 请求用 `get/post` + `param`/`content` 构造；断言用 `status()`、`content()`、`jsonPath()`。
- `MonitorControllerTest` 用 standalone + mock 把三条 AC-5 硬断言（400 / 403 / 钳到 30）全部锁死，且能塞进 `mvn test` 常规门禁。

⚠️ **踩坑提示**：standalone 模式**不吃**独立的 `@ControllerAdvice` 全局异常处理。若你的异常统一在 `GlobalExceptionHandler`（独立类）里，standalone 测会漏掉它，导致 400/403 断言失败或拿到 500。解法：要么把该控制器的异常处理内联成 `@ExceptionHandler`（codegen-server 的做法），要么改用 `webAppContextSetup` + `@SpringBootTest`，要么 `.setControllerAdvice(handler)` 手动挂上。
