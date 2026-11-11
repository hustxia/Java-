# 第 14 章 测试策略与收尾：金字塔、覆盖率、CI 门禁与契约测试

## 本章目标

读完本章你能把前 13 章串成一套**工程级测试策略**：

- 用测试金字塔决定「单元测试多、集成测试中、端到端少」；
- 建立命名与目录约定，让测试可维护；
- 用 JaCoCo 设覆盖率阈值，且 `failOnViolation` 拦住劣质合并；
- 把 `mvn test` 零失败作为 CI 合并门禁；
- 用契约测试（Provider/Consumer）锁住接口输入输出稳定；
- 收齐全书踩坑，形成一张速查表。

## 测试金字塔：别把集成测试写成主力

经典测试金字塔（Mike Cohn）告诉我们资源分配应为：

```
        / 端到端 (E2E) \        ← 少：慢、脆、贵（如 UI 自动化）
       /  集成测试 (Integration) \   ← 中：@SpringBootTest 契约测试
      /___________________________\
     /                             \
    /      单元测试 (Unit)           \  ← 多：毫秒级、多、稳（Mockito + standalone）
   /_________________________________\
```

- **单元层（多）**：codegen-server 的 `MonitorControllerTest`（standalone MockMvc）、`GenScaffoldPathSafetyTest`（纯函数）都属此层，毫秒返回、不连库。
- **集成层（中）**：`GenPipelineContractTest` / `AiRecommendApplyContractTest` 用 `@SpringBootTest` + 真 MySQL 验证跨层事实，慢但保真，数量应克制。
- **端到端层（少）**：真正打浏览器/全链路，codegen-server 暂未涉及。

⚠️ **踩坑提示**：最常见的反模式是「冰激凌筒」——全是 `@SpringBootTest` 重集成测试。它们一跑几分钟、互相抢库、还动不动红。先把逻辑抽到纯函数（如 `MonitorWindow.clampMinutes`、`GenScaffoldServiceImpl.safeModule`），用便宜的单元测试覆盖，重测试只守「必须真实链路才验证得了」的不变式。

## 命名与目录约定

codegen-server 的 `src/test/java/com/codegen/...` 严格镜像 `src/main` 的包结构，且按**被测对象 + Test** 命名（如 `MonitorController` → `MonitorControllerTest`、`GenScaffoldServiceImpl` → `GenScaffoldPathSafetyTest`）。方法名用「行为_预期」自然语言，配合 `@DisplayName` 给人看：

```java
// 来源：MonitorControllerTest.java:62 与 GenScaffoldPathSafetyTest.java:24
@Test void invalidMetricReturns400() { ... }            // 行为+预期，一眼读懂
@Test @DisplayName("模块名拒绝 ../、绝对路径、分隔符与空值") void moduleMustBeSingleSegment() { ... }
```

推荐约定：测试类 `XxxTest` 放同包；用例方法 `should_当X_期望Y` 或纯英文 `whenXThenY`；夹具方法统一放 `@BeforeEach` 或私有 `fixture()`。

## 覆盖率：JaCoCo 阈值门禁

JaCoCo 在 `mvn test` 时插桩统计行/分支覆盖。codegen-server 的 `pom.xml` 目前**未**引入 JaCoCo 插件，但加上下面这段即可启用并检查报告：

```xml
<!-- 以下为通用示例（非 codegen-server 现有 pom）：在 <build><plugins> 内追加 -->
<plugin>
    <groupId>org.jacoco</groupId>
    <artifactId>jacoco-maven-plugin</artifactId>
    <version>0.8.12</version>
    <executions>
        <execution>
            <goals><goal>prepare-agent</goal></goals>     <!-- 插桩 -->
        </execution>
        <execution>
            <id>report</id>
            <phase>test</phase>
            <goals><goal>report</goal></goals>            <!-- 生成 target/site/jacoco -->
        </execution>
        <execution>
            <id>check</id>
            <phase>verify</phase>
            <goals><goal>check</goal></goals>
            <configuration>
                <rules>
                    <rule>
                        <element>BUNDLE</element>
                        <limits>
                            <!-- 行覆盖低于 70% 直接失败 -->
                            <limit><counter>LINE</counter><value>COVEREDRATIO</value><minimum>0.70</minimum></limit>
                        </limits>
                    </rule>
                </rules>
            </configuration>
        </execution>
    </executions>
</plugin>
```

命令：`mvn jacoco:report` 看报告；`mvn verify` 时 `check` 规则生效，`failOnViolation`（默认 true）会让覆盖率不达标直接构建失败。

⚠️ **踩坑提示**：别把覆盖率门槛定太高（如 90%）当政治任务——团队会去「刷覆盖」写无意义的断言，反而稀释了真正有价值的测试。70% 行覆盖 + 关键路径 100% 是更务实的起点。覆盖率衡量「跑了哪些代码」，不衡量「断言对不对」。

## CI 门禁：mvn test 零失败才能合并

codegen-server 的 `pom.xml` 用 `failIfNoTests=true`（`pom.xml:163`）确保「没跑任何用例也不能算 SUCCESS」，从根上杜绝 surefire 版本错配导致的静默绿。CI 流水线只需一条：

```bash
# 以下为通用示例（CI 脚本）
mvn -B clean test      # -B 批处理模式；任一用例失败即非零退出，阻断合并
```

结合 JaCoCo 的 `verify` 阶段，合并门禁 = `mvn test` 零失败 + 覆盖率达标。codegen-server 的契约测试还有**数据源护栏**（`guardAgainstDevDatabase`），确保 CI 不会把测试数据写进开发库。

## 契约测试：Provider/Consumer 锁住接口稳定

契约测试回答一个问题：「**上下游的接口约定，谁改坏了谁负责**」。角色：

- **Consumer（消费者）**：调用方，声明「我需要这个请求/响应形状」；
- **Provider（提供者）**：服务端，保证「我按契约返回」。

codegen-server 没有引入 Pact 等契约框架，而是用**「针对真实链路的不变式测试」**充当契约——它钉死「输入 → 输出」这组承诺，任何破坏都会让用例红。

### 范例一：GenPipelineContractTest 锁住写盘链路

`GenPipelineContractTest`（`GenPipelineContractTest.java`）把四条不变式钉在 HTTP 接口层，用 `@TempDir` 做写盘沙箱：

1. **台账完整**：写盘后台账行数 == 磁盘文件数，且每行 `md5` == 文件 `md5`（`ledgerMatchesDisk`）；
2. **备份可信**：覆盖时 `prev_md5` == 备份文件 md5（回滚凭据，`backupAndPrevMd5Trustworthy`）；
3. **回滚可逆 + 可再回滚**：回滚后文件回到覆盖前，对 RBK 批次再回滚可回到回滚前（`rollbackRestoresAndCanRollbackAgain`）；
4. **漂移检测**：手改文件被识别为 `DRIFTED`，「只写未漂移」策略跳过它（`driftDetectedAndSkipped`）。

它还验证 V4.4 一主多子级联删除三档（`cascadeDeleteCleansEveryChildAndGrand` 等）——「主子表实现类必须含孙层 import 与删除，否则生成代码编译不过」这类**跨模板与生成产物的契约**，正是单元测试守不住、只有端到端契约测试能锁的。

### 范例二：AiRecommendApplyContractTest 锁住 AI 建议应用

`AiRecommendApplyContractTest`（`AiRecommendApplyContractTest.java`）锁的是 V7.0 两条不变式：

- **AC-3 预览只读**：`preview` 不得对 `gen_table` / `gen_table_column` 产生任何 UPDATE（用 `snapshot()` 前后比对，`previewIsReadOnly`）；
- **AC-4 勾选才写库**：选中的字段按建议写库、未选中的保持现值；主子建议按 `masterTableName` 解析成 `master_table_id`（`applyWritesOnlySelected`）。

这两条就是典型的 Consumer 期望：「我点应用之前，你别偷偷改库；我勾了才改，没勾不动」。一旦有人把预览改成顺手写库，或把未勾选项也覆盖，测试立刻变红。

### 安全边界：单元测试守护安全

`GenScaffoldPathSafetyTest`（`GenScaffoldPathSafetyTest.java`）是「单元测试守护安全」的范例：一键建工程时 `backendModule`/`rootPackage` 来自请求，`Path.resolve` 遇 `../` 或绝对路径会逃出输出根。它只测纯函数 `safeModule` / `safeTarget`，断言 `../../tmp/pwn`、`/etc/passwd` 等一律被拒，合法相对路径仍落在根内。不连库、不写盘，毫秒级，却挡住了「约 45 个基座文件被写到任意目录」的路径穿越风险。

⚠️ **踩坑提示**：契约测试会**真实写库/写盘**，必须配环境护栏。codegen-server 用 `@ActiveProfiles("test")` + `application-test.yml` 的 `_test` 库名，再在 `setUp` 里 `guardAgainstDevDatabase()` 断言数据源含 `gen_platform_test`。没有这层护栏，一次本地误操作就可能清掉开发台账。

## 全书踩坑速查表

| 章节 | 踩坑 | 正确做法 |
|------|------|----------|
| 10 | 过度 mock，测试只验证 stub 本身 | 纯函数/无副作用依赖直接 `new`，不必替 |
| 10 | 把 Mock 当 Stub 用反了方向 | Stub 答「返回什么」，Mock 答「调了没」 |
| 11 | `@InjectMocks` 有构造器时字段注入失效 | 优先写带参构造器 + `final` 字段，注入路径唯一 |
| 11 | `when` 里匹配器与字面量混用编译失败 | 整列统一用匹配器，字面量显式 `eq(...)` |
| 11 | `verify` 顺序错导致假阴性 | 验证发生在桩切换后的调用快照上，必要时拆用例 |
| 11 | `@BeforeEach` 通用桩触发 UnnecessaryStubbing | 通用桩加 `lenient()`，单测桩保持严格 |
| 12 | 无父 POM 时 surefire 静默不跑用例 | 钉 surefire 版本 + `failIfNoTests=true` |
| 12 | 多个 `@MockBean` 反复重建上下文拖慢 | Web 层能用 standalone 就别上 `@WebMvcTest` |
| 13 | standalone 吃不到独立 `@ControllerAdvice` | 异常内联 `@ExceptionHandler` 或改 webAppContextSetup |
| 13 | 冰激凌筒：全用 `@SpringBootTest` | 逻辑抽纯函数，单元测试为主力 |
| 14 | 覆盖率定太高逼出刷覆盖 | 70% 行覆盖 + 关键路径 100% 更务实 |
| 14 | 契约测试连错库冲掉开发数据 | `@ActiveProfiles("test")` + 数据源护栏 |

## 落地清单：从零搭起测试防线

把本章策略变成可执行的动作：

1. **先抽纯函数**：新增功能时先把校验/换算（如 `clampMinutes`、`safeModule`）写成无副作用方法，配单元测试，成本最低。
2. **Web 层用 standalone**：控制器边界断言走 `MockMvcBuilders.standaloneSetup` + `@Mock`，进 `mvn test` 常规门禁。
3. **重链路用契约**：跨层事实（写盘/回滚/AI 应用）用 `@SpringBootTest` + `@ActiveProfiles("test")` + 数据源护栏，数量克制。
4. **覆盖率设闸**：引入 JaCoCo，`check` 阶段 70% 行覆盖 + 关键路径 100%，`failOnViolation` 拦合并。
5. **CI 一条命令**：`mvn -B clean test`，零失败才放行；契约测试连 `_test` 库，绝不碰开发数据。

## 本章小结

- 遵循测试金字塔：**单元测试多、集成中、E2E 少**；把逻辑抽成纯函数，便宜地覆盖。
- 命名 `XxxTest` 同包镜像，用例用「行为_预期」+ `@DisplayName`。
- JaCoCo `prepare-agent` + `report` + `check`（`failOnViolation`）把覆盖率变成门禁；CI 用 `mvn test` 零失败阻断合并。
- 契约测试（Provider/Consumer）锁住「输入→输出」承诺：codegen-server 用 `GenPipelineContractTest` 守写盘/回滚不变式、`AiRecommendApplyContractTest` 守 AI 建议应用契约、`GenScaffoldPathSafetyTest` 用单元测试守路径穿越安全。
- 本书到此收尾：从 JUnit 5 基础、生命周期、断言，到替身、Mockito、Spring Boot 测试、Web 层测试，再到工程策略——一套可落地的 Java 测试方法论已成型。
