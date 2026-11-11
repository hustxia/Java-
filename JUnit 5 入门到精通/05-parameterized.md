# 第 5 章 参数化测试：一套逻辑，多组输入

## 本章目标

- 理解 `@ParameterizedTest` 的工作原理与生命周期；
- 掌握 `@ValueSource`、`@NullSource`、`@EmptySource`、`@CsvSource`、`@CsvFileSource`、`@MethodSource`、`@EnumSource` 七种常用数据源；
- 用「边界值 + 等价类」的思路设计参数，体会参数化相比复制粘贴 `@Test` 的省力之处；
- 看懂 codegen-server 中两条真实的参数化用例。

参数化测试是 JUnit 5 使用频率最高的进阶特性之一。它的核心思想很简单：**同一个测试方法，用不同的参数跑多遍，每一组参数都会生成一个独立的测试结果。** 当你需要验证「一批输入 → 各自对应输出」时，它比写十几个长得很像的 `@Test` 方法优雅得多，也更不容易漏改。

## 5.1 骨架：`@ParameterizedTest` 与数据源

把普通的 `@Test` 换成 `@ParameterizedTest`，并至少配一个数据源注解，方法参数就是每组数据：

```java
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import static org.junit.jupiter.api.Assertions.assertTrue;

// 方法参数直接接收每组数据
@ParameterizedTest
@ValueSource(strings = {"mkt", "shop", "wms"})
void 系统编码合法(String code) {
    assertTrue(code != null && !code.isBlank());
}
```

> 注意：`@ParameterizedTest` 不能与 `@Test` 同时标注同一个方法，否则会报错「被测方法上同时出现了 @Test 与参数化注解」。

参数化测试的数据源必须在编译期通过注解声明，或运行期通过 `@MethodSource` 的方法提供。`@ValueSource` 支持的类型有：`shorts`、`bytes`、`ints`、`longs`、`floats`、`doubles`、`chars`、`booleans`、`strings`、`classes`。

## 5.2 `@NullSource` 与 `@EmptySource`：空值也要测

`null` 和空串是很多 `NullPointerException` 的温床，JUnit 提供了专门的注解把它们纳入一组：

```java
import org.junit.jupiter.params.provider.NullSource;
import org.junit.jupiter.params.provider.EmptySource;

// 三组合一：null、""、以及下面的正常值
@ParameterizedTest
@NullSource
@EmptySource
@ValueSource(strings = {"mkt", "shop"})
void 空值与正常值都被覆盖(String code) {
    // 即使是 null，方法也不应抛 NPE
    assertNotNullOrSafe(code);
}
```

`@EmptySource` 只会产生一个空串；如果你的方法还接收 `Collection`，可以用 `@EmptySource` 配合单独处理，或改用 `@MethodSource` 自行构造空集合。

## 5.3 `@CsvSource`：多列参数

当方法需要多个入参与一个期望值时，`@CsvSource` 用逗号分隔每一列，每一行就是一组用例：

```java
@ParameterizedTest(name = "系统编码=[{0}] 表名={1} → 权限前缀 {2}")
@CsvSource({
        "mkt,       sys_flow_task, mkt_sys_flow_task",   // 常规
        "MKT,       sys_flow_task, mkt_sys_flow_task",   // 大写：过去会漏 toLowerCase
        "'  mkt  ', sys_flow_task, mkt_sys_flow_task",   // 前后空白
        "'',        sys_flow_task, sys_flow_task"        // 未绑定系统：不加前缀
})
@DisplayName("权限前缀归一化")
void permsPrefix(String projectCode, String tableName, String expected) {
    assertEquals(expected, GenNaming.permsPrefix(projectCode, tableName));
}
```

> ⚠️ **踩坑提示**：`@CsvSource` 里的值是 `String`，空列默认解析为 `null`。如果你想传入「空字符串」而不是 `null`，必须像上例一样用单引号包裹：`' '` 或 `''`。codegen-server 的 `GenNamingConsistencyTest.java:35-48` 正是用 `'  mkt  '` 这种写法，把「带空白的输入」作为独立等价类来验证大小写归一化逻辑。

下面这条是 codegen-server 中更「硬核」的真实用例——路径回落链的四级优先级（`GenPathResolverTest.java:138-159`）。它用 `@CsvSource` 把四种来源组合一次性钉死，并配合一个 `blankToNull` 工具把空列转成 `null`：

```java
@ParameterizedTest(name = "表级={0} 系统={1} 模块={2} → {3}")
@CsvSource({
        // 表级有值：其余都不看
        "tbl-server/src/main/java/com/tbl, mkt-server/src/main/java/com/mkt, '', tbl-server/src/main/java/com/tbl",
        // 表级空、系统有值：系统生效（以前会退到全局，文件写错仓库）
        "'', mkt-server/src/main/java/com/mkt, '', mkt-server/src/main/java/com/mkt",
        // 表级/系统空、模块有值：模块生效
        "'', '', demo, module-server/src/main/java/com/module",
        // 全空：全局兜底
        "'', '', '', global-server/src/main/java/com/global"
})
@DisplayName("四级回落")
void chain(String tablePath, String projectPath, String module, String expected) {
    GenTable t = table();
    t.setBackendPath(blankToNull(tablePath));            // 空列 → null，触发下一级回落
    if (module != null && !module.isBlank()) {
        t.setTargetModule(module);
    }
    SysProject p = project();
    p.setBackendPath(projectPath);
    assertEquals(expected, GenPathResolver.backendBase(t, p, globalOutput()));
}
```

`@CsvSource` 还支持 `delimiter = '|'`、引号字符 `quoteCharacter` 等配置，遇到字段本身含逗号时用 `quoteCharacter = '\''` 包裹即可。

## 5.4 `@CsvFileSource`：数据外置到 CSV 文件

当用例很多、或希望非工程师也能维护测试数据时，把数据放进 `src/test/resources` 下的 CSV 文件：

```java
@ParameterizedTest
@CsvFileSource(resources = "/cases/path-fallback.csv", numLinesToSkip = 1)
void fromCsvFile(String tablePath, String projectPath, String expected) {
    // CSV 第一行是表头，用 numLinesToSkip = 1 跳过
    assertEquals(expected, GenPathResolver.backendBase(tablePath, projectPath));
}
```

`resources` 指向 classpath 资源，`numLinesToSkip` 跳过表头；默认分隔符仍是逗号，可用 `delimiterString` 调整。

## 5.5 `@MethodSource`：返回 `Stream<Arguments>`

当参数需要动态构造、或每组的类型不统一时，用 `@MethodSource` 指向一个返回 `Stream<Arguments>` 的静态（或 PER_CLASS 下非静态）方法：

```java
import org.junit.jupiter.params.provider.Arguments;
import java.util.stream.Stream;

@ParameterizedTest
@MethodSource("fallbackCases")
void fromMethod(String a, String b, String expected) {
    assertEquals(expected, combine(a, b));
}

// 方法名默认与方法同名；也可显式写 @MethodSource("fallbackCases")
static Stream<Arguments> fallbackCases() {
    return Stream.of(
        Arguments.of("x", "y", "xy"),
        Arguments.of(null, "y", "y"),   // 用 Arguments 显式表达 null
        Arguments.of("", "y", "y")
    );
}
```

`@MethodSource` 是唯一能优雅表达「含 null 的多参数组」的源（因为 `@CsvSource` 的 null 需要靠空列推断）。这是它相比 CSV 系列注解的独特价值。

## 5.6 `@EnumSource`：枚举遍历

验证「对某个枚举的每个取值都应成立」时，`@EnumSource` 直接枚举：

```java
import org.junit.jupiter.params.provider.EnumSource;

enum ModuleMode { mono, multi, micro }

@ParameterizedTest
@EnumSource(ModuleMode.class)
void 每种模式都能解析(ModuleMode mode) {
    assertTrue(GenPathResolver.isMultiLike(mode.name()) || mode == ModuleMode.mono);
}
```

还可用 `names = {"multi", "micro"}` 只选部分取值，或用 `mode = EXCLUDE` 排除某些值。

## 5.7 用「边界值 + 等价类」设计参数

参数化的威力不在于「多」，而在于「全」。经典黑盒设计法：

- **等价类划分**：把输入域分成若干「行为应一致」的区间，每类取一个代表值；
- **边界值分析**：重点取区间的边界（0、1、-1、null、空串、超大值）。

codegen-server 的 `GenScaffoldPathSafetyTest.java:27-31` 就是一个反面教材式的边界集合——它没用参数化，而是手写 `for` 循环遍历一批「应被拒绝的非法模块名」：

```java
for (String bad : new String[]{"../../tmp/pwn", "..", ".", "", "   ",
        "a/b", "a\\b", "C:/Windows/Temp/pwn", "server;rm"}) {
    assertThrows(BusinessException.class,
            () -> GenScaffoldServiceImpl.safeModule(bad), "应拒绝的模块名：" + bad);
}
```

> 💡 若改用 `@ValueSource(strings = {...})` + `@ParameterizedTest`，每组非法输入都会是独立的测试条目，哪一组漏判在报告里一目了然，而不是只看到「循环里挂了」。这正是「边界值 + 等价类」配参数化最省力的地方。

## 本章小结

- `@ParameterizedTest` + 数据源 = 一组方法、多组结果；
- `@ValueSource` 最轻量；`@NullSource`/`@EmptySource` 专治空值；`@CsvSource` 处理多列；`@CsvFileSource` 外置数据；`@MethodSource` 灵活但需返回 `Stream<Arguments>`；`@EnumSource` 遍历枚举；
- `@CsvSource` 中空列解析为 `null`，要传空串必须用单引号包裹，codegen 的 `GenNamingConsistencyTest` 与 `GenPathResolverTest` 都依赖这一技巧；
- 参数设计用「边界值 + 等价类」，让覆盖既省事又严密。

⚠️ **踩坑提示**：参数化方法的参数类型要和数据源能转换的类型匹配；`@CsvSource` 的列会先转成 `String` 再按参数类型转换，遇到无法转换（如把 `"abc"` 转 `int`）会直接抛转换异常，让整组用例失败——这通常是「数据写错了」而不是「被测代码错了」，定位时先看报错行号和列。
