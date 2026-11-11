# 第 8 章 条件执行：让测试学会「看情况」

## 本章目标

- 掌握 `@Disabled`（含原因）临时关闭测试；
- 了解基于环境的条件注解：`@EnabledOnOs`、`@EnabledOnJre`、`@EnabledIfEnvironmentVariable`、`@DisabledIf`；
- 理解 `Assumptions.assumeTrue` / `assumingThat` 与「禁用」的本质区别：**假设不满足则跳过，而非失败**；
- 知道 codegen-server 未使用条件注解，但理解其适用场景。

并不是所有测试在任何环境都该跑。某些用例只在 Linux 上成立、某些只在 JDK 21 上有意义、某些依赖一台外部数据库。JUnit 5 提供了两类机制：一类是**硬性开关**（条件注解 / `@Disabled`），不满足就「跳过」；另一类是**运行时假设**（`Assumptions`），在测试方法内部判断「若前提不成立就跳过剩余逻辑」。

> 说明：经检索，codegen-server 的 `src/test/java` 下**没有**使用 `@Disabled` 或 `Assumptions`，其全部测试都设计为「任何环境都能跑的纯逻辑测试」。因此本章以标准通用示例讲解，便于你在需要时引入。

## 8.1 `@Disabled`：最朴素的开关

`@Disabled` 让整个类或单个方法不参与执行，引擎会报告「跳过」而非「失败」。务必写明原因，否则日后没人知道为什么关：

```java
import org.junit.jupiter.api.Disabled;
import org.junit.jupiter.api.Test;

@Disabled("Windows 上路径分隔符行为不同，待修复后开启")   // 标在类上：整类跳过
class WindowsOnlyFeatureTest { }

class SomeTest {
    @Test
    @Disabled("已知缺陷 #123，修复后移除本注解")            // 标在方法上：单方法跳过
    void 尚未修复的用例() {}
}
```

⚠️ **踩坑提示**：`@Disabled` 是一次「技术债」。团队里 `@Disabled` 越积越多，等于测试套件在悄悄缩水。建议：加 `@Disabled` 时同步建一个跟踪 issue，并在 CI 里用 `junit-platform.properties` 的 `junit.jupiter.conditions.deactivate` 或定期审计，防止「永久禁用」。

## 8.2 基于环境的条件注解

JUnit 5 内置了一批「看环境决定跑不跑」的注解，全部来自 `org.junit.jupiter.api.condition`：

```java
import org.junit.jupiter.api.condition.*;

@EnabledOnOs(OS.LINUX)                      // 仅 Linux 执行
@Test
void 只跑在Linux() {}

@EnabledOnOs({OS.MAC, OS.LINUX})            // 多平台
@Test
void 非Windows() {}

@EnabledOnJre(JRE.JAVA_21)                  // 仅 JDK 21
@Test
void 需要Java21特性() {}

@EnabledIfEnvironmentVariable(named = "CI", matches = "true")  // 环境变量 CI=true 才跑
@Test
void 仅CI环境() {}

@DisabledIf("System.getenv('SKIP_SLOW') != null")  // 脚本式条件，返回 true 则禁用
@Test
void 慢速用例() {}
```

- `@EnabledOnOs` / `@DisabledOnOs`：按操作系统；
- `@EnabledOnJre` / `@DisabledOnJre`：按 Java 版本；
- `@EnabledIfEnvironmentVariable` / `@DisabledIfEnvironmentVariable`：按环境变量名+正则；
- `@DisabledIf` / `@EnabledIf`：接收 SpEL 表达式或静态方法引用，做任意判断。

> 💡 这类注解适合「集成/平台相关」用例：比如 codegen 若要在 Windows 上验证某个路径归一化，可用 `@EnabledOnOs(OS.WINDOWS)` 单独圈定，避免跨平台 CI 误红。

## 8.3 `Assumptions`：假设不满足就跳过

条件注解在「类/方法层面」决定跑不跑；而 `Assumptions` 在「方法内部」判断——它更灵活，能基于被测运行时的任意状态。

```java
import org.junit.jupiter.api.Assumptions;
import org.junit.jupiter.api.Test;

@Test
void 仅当外部数据库可达时才验证() {
    // 假设：测试库连得上。连不上 → 本条跳过（不是失败）
    Assumptions.assumeTrue(isDatabaseUp(), "测试库不可用，跳过");
    assertTrue(queryWorks());   // 只有假设成立才会执行到这里
}
```

`assumingThat(condition, executable)` 则更细粒度：**条件成立才执行那段逻辑，不成立时方法其余部分照常跑，且不标记跳过**：

```java
@Test
void 分平台校验() {
    Assumptions.assumingThat(
        System.getProperty("os.name").contains("Linux"),
        () -> assertTrue(linuxOnlyCheck()));   // 仅 Linux 跑这段
    // 不管上面成不成立，下面都会执行
    assertTrue(commonCheck());
}
```

## 8.4 假设 vs 禁用：一个关键区别

这是本章最重要的一点：

| 机制 | 不满足时的结果 | 适用层级 | 典型意图 |
|---|---|---|---|
| `@Disabled` / 条件注解 | 跳过（整条不执行） | 类/方法 | 环境不支持、暂时坏掉 |
| `Assumptions.assumeTrue` | 跳过（方法提前结束） | 方法内部 | 前置条件缺失，测了也没意义 |
| `assertTrue`（断言） | **失败** | 方法内部 | 这是被测代码「应该保证」的事 |

核心区别：**假设（Assumption）是「测试的前提」，不满足说明「环境不具备条件」，应跳过；断言（Assertion）是「被测代码的契约」，不满足说明「代码有 bug」，应失败。** 把该用 `assumeTrue` 的地方写成 `assertTrue`，会把「环境没就绪」误报成「代码缺陷」，反过来亦然。

## 8.5 可运行示例：平台相关校验（此为通用示例）

```java
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledOnOs;
import org.junit.jupiter.api.condition.OS;
import org.junit.jupiter.api.Assumptions;

import static org.junit.jupiter.api.Assertions.assertTrue;

class PlatformAwareTest {   // 此为通用示例

    @EnabledOnOs(OS.LINUX)
    @Test
    void linux特有路径校验() {
        assertTrue("/opt/app".startsWith("/"));
    }

    @Test
    void 仅在配置了测试库时验证连接() {
        String url = System.getenv("TEST_DB_URL");
        Assumptions.assumeTrue(url != null, "未配置 TEST_DB_URL，跳过");
        assertTrue(url.startsWith("jdbc:"));
    }
}
```

## 8.6 在 CI 中审计被跳过的测试

条件注解和 `Assumptions` 会让用例「静默跳过」，长期积累等于测试覆盖在缩水。建议在 CI 里加一道检查：统计被跳过（skipped）的用例数，超过阈值就告警。Maven Surefire 的报告里本就区分 `tests` / `skipped` / `failures`，配合流水线脚本即可监控趋势。代码里也可借助 `@Tag("integration")` 给「可能跳过的重型用例」打标签，单独统计，避免它们稀释核心单元测试的覆盖率指标。这样既能保留「按需跳过」的灵活性，又不至于让跳过数悄悄失控。

## 本章小结

- `@Disabled("原因")` 是临时开关，记得标注原因并限期清理；
- 环境类条件注解：`@EnabledOnOs`、`@EnabledOnJre`、`@EnabledIfEnvironmentVariable`、`@DisabledIf` 等，在类/方法层面决定跑不跑；
- `Assumptions.assumeTrue` 在方法内判断前提，不满足则**跳过**；`assumingThat` 做局部条件执行；
- 关键区分：**假设不满足 → 跳过（环境无关），断言不满足 → 失败（代码有错）**。

⚠️ **踩坑提示**：`@Disabled` 会让测试「静默消失」。如果一段逻辑已经稳定，请尽快移除 `@Disabled`；长期保留等于让这块代码处于「无人看守」状态。另外，`Assumptions` 跳过的是**整个方法或那段 lambda**，不是「断言失败」——若你其实是想验证「代码必须如何」，请用 `assertTrue`，别错用 `assumeTrue` 把真正的 bug 也「跳过」了。
