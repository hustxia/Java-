# 第 6 章 动态测试：运行时才决定用例数量

## 本章目标

- 理解 `@TestFactory` 与 `DynamicTest` 的机制；
- 区分 `DynamicTest` 与 `DynamicContainer` 的用途；
- 看清动态测试与参数化测试（第 5 章）的本质差异；
- 用「扫描模板目录生成用例」的类比，写出可运行的动态测试示例。

前面讲的所有测试，用例数量在**编译期、甚至写代码时**就已经固定：你写了多少个 `@Test`、多少组 `@ParameterizedTest` 数据，运行前就确定。但有些场景，用例要等到**运行期**才知道——比如「磁盘上有多少份模板文件，就生成多少条用例」「配置里列了 N 个数据源，就校验 N 个连通性」。这类需求，交给动态测试最自然。

## 6.1 `@TestFactory` 与 `DynamicTest`

动态测试不是用 `@Test` 标方法，而是用 `@TestFactory` 标一个**返回测试集合**的方法。集合里的每个元素是 `DynamicTest.dynamicTest(displayName, executable)`：

```java
import org.junit.jupiter.api.DynamicTest;
import org.junit.jupiter.api.TestFactory;
import java.util.List;

@TestFactory
List<DynamicTest> 校验所有模板文件() {
    // 运行期才知道有多少个模板文件
    List<Path> templates = scanTemplateDir();   // 扫描模板目录
    return templates.stream()
        .map(p -> DynamicTest.dynamicTest(
                "模板 " + p.getFileName(),       // ① 用例展示名
                () -> assertTrue(isValid(p),     // ② 真正执行的断言
                        "非法模板：" + p)))
        .toList();
}
```

`dynamicTest` 的两个参数：第一个是展示名（会显示在测试报告里），第二个是 `Executable`（一个无参 lambda）。注意：**lambda 里的断言要引用「当时」的数据**——如果直接捕获循环变量，可能出现所有用例都用了最后一个值（变量遮蔽问题），用 `.map(p -> ...)` 的局部变量 `p` 即可避免。

## 6.2 `DynamicContainer`：给动态用例分组

当动态用例很多，可以用 `DynamicContainer.dynamicContainer(name, children)` 把它们组织成树状结构，报告更清晰：

```java
import org.junit.jupiter.api.DynamicContainer;
import org.junit.jupiter.api.DynamicNode;

@TestFactory
List<DynamicNode> 按模块组织动态用例() {
    return List.of(
        DynamicContainer.dynamicContainer("后端模板", backendTemplates().stream()
            .map(p -> DynamicTest.dynamicTest(p.getFileName().toString(),
                    () -> assertTrue(isValid(p))))
            .toList()),
        DynamicContainer.dynamicContainer("前端模板", frontendTemplates().stream()
            .map(p -> DynamicTest.dynamicTest(p.getFileName().toString(),
                    () -> assertTrue(isValid(p))))
            .toList())
    );
}
```

`DynamicContainer` 的第二个参数是 `Collection<? extends DynamicNode>`，而 `DynamicNode` 既可来自 `DynamicTest` 也可来自嵌套的 `DynamicContainer`，因此能任意嵌套。

## 6.3 动态测试 vs 参数化测试

这是初学者最容易混淆的一对。核心区别在「用例数量何时确定」：

| 维度 | `@ParameterizedTest` | `@TestFactory` 动态测试 |
|---|---|---|
| 用例数量确定时机 | 编译期（数据源固定） | 运行期（代码动态算出） |
| 数据来源 | 注解声明的源 | 任意 Java 代码（读文件、查库、反射） |
| 典型场景 | 多组「输入→输出」已知 | 「有多少个 X 就测多少个 X」 |
| 报告粒度 | 每组一个结果，名字可模板化 | 每个 `DynamicTest` 一个结果 |

简单判断：**数据在写代码时就能列出来 → 参数化；数据要跑起来才知道有多少 → 动态测试。**

> 关于「扫描模板目录生成用例」的类比：codegen-server 的 `GenScaffoldPathSafetyTest.java:27-31` 其实用 `for` 循环遍历一批非法模块名做断言，算是「穷人版动态测试」——它能跑多组，但报告里只算一个 `@Test`。若改用 `@TestFactory`，每一条非法输入都会独立出现在报告里，定位哪个漏判更直观。这正是动态测试与循环断言的区别。

## 6.4 可运行示例：模板目录校验器（此为通用示例）

下面是一份完整、可编译运行的动态测试示例，模拟「codegen 扫描模板目录，对每个 `.tpl` 文件生成一个校验用例」：

```java
import org.junit.jupiter.api.DynamicTest;
import org.junit.jupiter.api.TestFactory;
import org.junit.jupiter.api.function.Executable;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.stream.Stream;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

class TemplateScanTest {   // 此为通用示例，未引用 codegen-server 真实代码

    @TestFactory
    Stream<DynamicTest> 每个模板都以_tpl结尾且不空() throws Exception {
        Path dir = Path.of("src/test/resources/templates");   // 模板目录
        if (!Files.exists(dir)) {
            return Stream.of();   // 目录不存在：返回空，相当于「无用例」
        }
        return Files.list(dir)
                .filter(p -> p.toString().endsWith(".tpl"))
                .map(p -> {
                    String name = p.getFileName().toString();
                    Executable exec = () -> {
                        String content = Files.readString(p);
                        assertTrue(content.length() > 0, name + " 不应是空模板");
                        assertFalse(name.contains(" "), name + " 模板名不能含空格");
                    };
                    return DynamicTest.dynamicTest("校验模板 " + name, exec);
                });
    }
}
```

这个例子演示了动态测试最经典的形态：**目录里有几个 `.tpl` 文件，就生成几条用例**，文件增删后无需改测试代码。换成 codegen 的场景，只需把断言换成 `校验模板能被 Freemarker 解析` 之类即可。

## 6.5 命名、调试与报告可读性

动态测试的展示名直接决定报告可读性。如果两个用例名字撞车（都叫 `dynamicTest`），报告里会分不清谁红了。建议名字里带上「区分度足够」的上下文：

```java
// 不好的命名：所有用例都叫 "校验模板"，报告里无法区分
DynamicTest.dynamicTest("校验模板", () -> assertTrue(isValid(p)));

// 好的命名：把文件名塞进展示名
DynamicTest.dynamicTest("模板[" + name + "] 大小与命名合法", () -> { ... });
```

在 IDE（IntelliJ / Eclipse）里，动态测试会以「可展开树」形式出现：先看到 `@TestFactory` 方法这一层，展开后才是每条 `DynamicTest`。配合 6.2 的 `DynamicContainer`，可把「目录 → 文件」两层结构完整映射到报告树，调试时一眼定位到具体文件。

## 6.6 动态测试能配合参数化吗？

不能直接在 `@TestFactory` 方法上叠 `@ParameterizedTest`（二者都是「测试工厂」语义，会冲突）。但若你想「先动态扫出 N 个文件，再对每个文件做 M 组参数校验」，正确做法是：**在 `DynamicTest` 的 lambda 内部调用一个 `@ParameterizedTest` 方法是不可能的**（参数化方法不能直接被调用）。替代方案是抽一个普通私有方法 `check(Path, Case) `，在 lambda 里循环调用它——把「动态」负责发现、「参数」负责多组数据，用代码而非注解组合。

## 6.7 何时不该用动态测试

动态测试不是万能钥匙。如果用例数量在写代码时就能确定（常见「多组输入输出」），**优先用第 5 章的参数化测试**——它的报告更规整、数据源声明更清晰、IDE 支持更好。动态测试真正的用武之地只有一类：**用例数量或内容依赖运行期才能拿到的信息**（文件清单、配置条目、数据库行数）。拿它去替代本可参数化的场景，反而增加复杂度和调试成本。换句话说：能列清单用参数化，列不出清单才用动态。

## 本章小结

- 动态测试用 `@TestFactory` 返回 `DynamicTest` / `DynamicContainer` 集合，用例数量在运行期决定；
- `DynamicTest.dynamicTest(name, exec)` 构造单条用例，`DynamicContainer` 用来分组；
- 与参数化测试的关键差异：**参数化数据源编译期固定，动态测试运行期计算**；
- 动态测试非常适合「按文件/按配置条目生成用例」，是循环断言的升级替代品；
- 展示名要带足上下文，配合 `DynamicContainer` 能把「目录→文件」结构映射成报告树。

⚠️ **踩坑提示**：`@TestFactory` 方法上**不能再标 `@Test`**，否则报错；且 `@TestFactory` 方法本身不能是 `private`。另外，动态测试里的 `BeforeEach`/`AfterEach` **不会**为每条 `DynamicTest` 单独执行（它们只作用于 `@TestFactory` 这一层），需要每条用例独立的准备/清理逻辑时，要写进 lambda 内部，而不是依赖生命周期回调。最后，lambda 捕获外部变量时请用 `.map(p -> ...)` 的局部绑定，避免循环变量共享导致「所有用例都用了最后一个值」。
