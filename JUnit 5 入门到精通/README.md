# JUnit 5 从入门到精通

> 一本以**真实生产测试代码**为贯穿案例的 JUnit 5 实战书。所有示例优先取自 `codegen-server`（Spring Boot 3.2.5 + Java 21 代码生成器平台）的 `src/test` 目录——那里有 49 个真实测试类，覆盖单元、Mock、Web 层、契约与边界安全测试。读完后你不仅能写测试，更能写出"像生产项目一样"的测试。

## 本书特色

- **真实代码贯穿**：每章优先用 `codegen-server` 的真实测试作为示例（如 `MonitorStoreTest`、`MonitorControllerTest`、各类 `*ContractTest`），未实现的特性才用标准通用示例并标注。
- **JUnit 5 全家族**：Jupiter API、断言、参数化、动态测试、测试生命周期、条件执行、Mockito、Spring Boot 测试切片、MockMvc、测试策略与度量。
- **工程视角**：不只教 API，更讲"为什么这么测"——测试金字塔、契约测试、覆盖率门禁、CI 集成。
- **统一结构**：每章「本章目标 → 原理 + 代码 → 本章小结 → ⚠️ 踩坑提示」。

## 阅读路线

| 目标 | 推荐章节 |
|---|---|
| 零基础学测试 | 1 → 2 → 3 → 4 |
| 写好断言与边界 | 3 → 5 → 8 → 9 |
| Mock 与 Web 层测试 | 10 → 11 → 12 → 13 |
| 测试策略与团队落地 | 14 |
| 直接参考真实测试代码 | 11（Mockito）、13（MockMvc）、14（契约） |

## 目录

1. [为什么写测试 & JUnit 5 总览](01-intro.md)
2. [第一个单元测试：注解与生命周期](02-first-test.md)
3. [断言全家桶：Assertions](03-assertions.md)
4. [测试的组织与命名：@DisplayName / @Nested / @Tag](04-organization.md)
5. [参数化测试：@ParameterizedTest](05-parameterized.md)
6. [动态测试：@TestFactory](06-dynamic-tests.md)
7. [测试实例与执行顺序：@TestInstance / @Order](07-lifecycle-order.md)
8. [条件执行与假设：@Disabled / Assumptions](08-conditional.md)
9. [异常与超时测试](09-exception-timeout.md)
10. [测试替身：Dummy / Stub / Mock / Fake / Spy](10-test-doubles.md)
11. [Mockito 实战：@Mock / @InjectMocks / when / verify](11-mockito.md)
12. [Spring Boot 测试：@SpringBootTest 与测试切片](12-spring-boot-test.md)
13. [Web 层测试：MockMvc 与 @WebMvcTest](13-web-mvc-test.md)
14. [测试策略与质量门禁：金字塔 / 覆盖率 / 契约 / CI](14-strategy.md)

## 真实案例索引（来自 codegen-server/src/test）

| 测试文件 | 体现的知识点 |
|---|---|
| `monitor/MonitorStoreTest.java` | 基础断言、`@Test`、环形缓冲边界 |
| `controller/MonitorControllerTest.java` | MockitoExtension、`@Mock/@InjectMocks`、MockMvc standalone、verify/never |
| `contract/GenPipelineContractTest.java` | 契约测试、流水线输入/输出稳定 |
| `contract/AiRecommendApplyContractTest.java` | AI 推荐契约、输入净化 |
| `service/impl/GenScaffoldPathSafetyTest.java` | 路径穿越安全边界测试 |
| `support/GenPathResolverTest.java` | 路径解析纯函数单测 |
| `monitor/HistogramConfigProbeTest.java` | 配置探针、直方图分位 |

## 环境

- JDK 21（示例为 Java 21，语法兼容 Java 17+）
- JUnit 5（Jupiter）通过 `spring-boot-starter-test` 引入
- 构建：`mvn test`（surefire-plugin + junit-platform）
- 真实测试可在 `codegen-server` 仓库下直接 `mvn -o test` 运行
