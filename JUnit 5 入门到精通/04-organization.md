# 第 4 章 组织与标注你的测试

## 本章目标

- 用 `@DisplayName` 给测试起「人话」名字（支持空格、emoji）；
- 用 `@Nested` 把相关测试聚成嵌套类、共享 `@BeforeEach`；
- 用 `@Tag` 给测试分组，配合 `mvn test -Dgroups=` 过滤执行；
- 掌握测试类 / 方法的命名约定（方法名用 snake_case 描述行为）。

---

## 4.1 @DisplayName：让报告说人话

默认报告里显示的是方法名（如 `invalidMetricReturns400`）。`@DisplayName` 允许你覆盖成任意字符串——空格、中文、emoji 都行：

```java
// 此为通用示例
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

@DisplayName("购物车结算功能")
class CartCheckoutTest {

    @Test
    @DisplayName("🛒 空购物车结算应报错")
    void emptyCartThrows() { /* ... */ }
}
```

生成的报告会显示「🛒 空购物车结算应报错」而非 `emptyCartThrows`，对产品/测试同学更友好。不过代码里的方法名仍建议保持英文 snake_case，便于命令行检索。

---

## 4.2 @Nested：嵌套测试类

当一类被测对象有多种「前置场景」时（例如「已登录 / 未登录」「管理员 / 普通用户」），用嵌套类能把这些状态分组，且**内层类可共享外层实例的 `@BeforeEach`**。

> codegen-server 的 `MonitorControllerTest` 目前用扁平的多个 `@Test` 方法（如 `deniedWithoutViewPermissionReturns403`、`overviewReturns200ForSuperAdmin`）来表达权限分支（代码来自 `src/test/java/com/codegen/controller/MonitorControllerTest.java`）。它**没有使用** `@Nested`。下面给出一个**通用嵌套示例**演示该特性的写法：

```java
// 此为通用示例（codegen-server 未使用 @Nested，此处演示写法）
import org.junit.jupiter.api.*;

@DisplayName("监控接口权限")
class MonitorAccessTest {

    @BeforeEach
    void setUp() {
        // 外层准备：构造 controller、mock 依赖
    }

    @Nested
    @DisplayName("超级管理员")
    class SuperAdmin {
        @BeforeEach
        void asAdmin() {
            // 内层额外准备：把当前用户设为超级管理员
        }

        @Test
        void overviewReturns200() { /* 期望 200 */ }

        @Test
        void businessReturns200() { /* 期望 200 */ }
    }

    @Nested
    @DisplayName("普通用户（无查看权限）")
    class NoPermission {
        @BeforeEach
        void asGuest() {
            // 内层准备：把当前用户设为无权限
        }

        @Test
        void overviewReturns403() { /* 期望 403 */ }
    }
}
```

要点：

- `@Nested` 类**默认不能是静态的**（它和外层共享同一个测试实例，才能继承外层的 `@BeforeEach`）；
- 执行顺序：外层 `@BeforeEach` → 内层 `@BeforeEach` → 内层 `@Test` → 内层 `@AfterEach` → 外层 `@AfterEach`；
- 嵌套层级可多层，IDE 报告会按树形展示，一眼看清「哪组场景、哪条用例」。

---

## 4.3 @Tag：分组过滤

`@Tag` 给测试打标签，运行时刻按需筛选用例。真实项目常按「快 / 慢」「单元 / 集成」「smoke / full」分组：

```java
// 此为通用示例
import org.junit.jupiter.api.Tag;
import org.junit.jupiter.api.Test;

class SampleTest {

    @Test
    @Tag("fast")          // 标记为快速单元测试
    void pureLogic() { /* 不依赖外部资源 */ }

    @Test
    @Tag("integration")   // 标记为集成测试（可能连数据库）
    void withDatabase() { /* 较慢 */ }
}
```

命令行过滤执行：

```bash
# 只跑 fast 标签
mvn test -Dgroups=fast

# 排除 integration
mvn test -DexcludedGroups=integration
```

> 标签名是自由字符串，但按约定**用小写、无空格**（如 `fast`、`slow`、`smoke`）。在 Surefire 里，`-Dgroups` 最终交给 JUnit Platform 的 `TagFilter` 处理。codegen-server 的 `pom.xml` 当前未配置默认分组，需要时照上面写法即可。

---

## 4.4 命名约定：方法名即文档

JUnit 5 的方法名**没有任何强制格式**——可以是中文、空格（配合 `@DisplayName`）、甚至 emoji。但团队内部强烈建议遵循一套约定，让 `mvn test -Dtest=...` 和 grep 都能用：

1. **类名**：`被测类 + Test`。如 `MonitorStore` → `MonitorStoreTest`；`MonitorController` → `MonitorControllerTest`。codegen-server 严格遵循此约定。
2. **方法名用 snake_case 描述「行为 + 预期」**，而非 `test1`、`testAdd`。看 codegen-server 的真实方法名（来自 `MonitorStoreTest.java` 与 `MonitorControllerTest.java`）：

   - `keepsOnlyCapacityAndEvictsOldest`（满了只保留容量、淘汰最旧）
   - `sinceReturnsAscendingWindow`（since 返回升序窗口）
   - `latestIsNullBeforeFirstSample`（首样本前 latest 为 null）
   - `invalidMetricReturns400`（非法 metric → 400）
   - `deniedWithoutViewPermissionReturns403`（无权限 → 403）
   - `seriesClampsMinutesTo30`（minutes 越界被钳到 30）

   这些名字都采用了 **`when_Then` / `subjectVerbExpected`** 的句式：前半段描述输入或前置，后半段描述预期结果。新人读测试名就能还原规格，无需翻开实现。

3. **避免使用 `test` 前缀**：JUnit 5 不靠前缀识别用例，`testXxx` 是 JUnit 4 的残留习惯；用描述性名字更清晰。

---

## 本章小结

- `@DisplayName` 让报告更可读，支持空格/中文/emoji；代码内方法名仍建议英文 snake_case。
- `@Nested` 把「前置场景」分组，内层共享外层 `@BeforeEach`（此为通用示例，codegen-server 当前未使用）。
- `@Tag` 打标签 + `mvn test -Dgroups=` 按需过滤执行。
- 命名约定：类用 `XxxTest`；方法用「行为 + 预期」的 snake_case，以 codegen-server 的真实方法名为范本。

## ⚠️ 踩坑提示

**`@Nested` 类不要声明成 `static`。** 嵌套测试类必须能访问外层实例（从而继承外层生命周期与方法级别的字段/注入），因此默认要求**非静态**。一旦你习惯性地给类加 `static`，JUnit 会直接报错「@Nested class must not be static」。此外，若外层用了 `@TestInstance(PER_CLASS)`，内层仍是非静态嵌套——两者是正交的两个概念，别混淆。另一个常见坑：`@Tag` 的值若包含空格（如 `"fast test"`），Maven 的 `-Dgroups` 无法正确解析，请坚持小写无空格的标签命名。
