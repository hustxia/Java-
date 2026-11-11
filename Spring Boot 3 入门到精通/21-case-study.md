# 第 21 章 案例全貌：codegen-server 是怎么把前面各章串起来的

> 这是本书的"收口章"。前面 20 章你零散地学了自动配置、Web、统一返回、AOP、MyBatis、事务、安全、可观测性、性能、部署……这一章把它们**全部收拢到一次真实的"生成代码"请求里**。读完你会有那种"原来前面学的都在这里用上了"的顿悟。

## 本章目标

- 看清 codegen-server 的**整体架构与技术栈决策**；
- 走马核心模块：`config / monitor / security / service / controller / dao / common`；
- 理解"一句话建系统"的 **PipelineExecutor 12 步**流水线；
- **串起一次 `/gen/apply` 请求的完整链路**，把前面各章知识点对号入座。

---

## 21.1 它是什么：一个独立的单体

启动类极简，没有 Nacos、没有网关、没有 Redis——连上 MySQL 就能跑：

```java
// 来源：com/codegen/CodegenApplication.java
@SpringBootApplication
@MapperScan("com.codegen.mapper")   // 让 MyBatis-Plus 扫描 Mapper 接口，省去逐个 @Mapper
public class CodegenApplication {
    public static void main(String[] args) {
        SpringApplication.run(CodegenApplication.class, args);
    }
}
```

这种"轻依赖、零中间件"的选型，决定了它**容易部署**（见第 20 章），也决定了它**有状态**（写盘落本地、监控在进程内，见第 19 章）。技术决策从来不是孤立的，一个选择会顺着链路影响后面所有章节。

### 技术栈决策一览（来源：pom.xml）

| 能力 | 选型 | 决策理由（从代码反推） |
|------|------|----------------------|
| 基础框架 | Spring Boot **3.2.5** + Java **21** | 本书主线；虚拟线程、record、新 GC 全用上 |
| 持久层 | MyBatis-Plus **3.5.5**（`mybatis-plus-spring-boot3-starter`） | 代码生成本就操作元数据，MP 的 `selectBatchIds`/`LambdaQueryWrapper` 省大量样板 |
| 接口文档 | springdoc-openapi **2.3.0** | Spring Boot 3 配 springdoc，Swagger UI 可一键关闭 |
| 鉴权 | **spring-security-crypto（仅 BCrypt）**，不引入完整 Spring Security | 单体前面没网关，鉴权自己用 Filter 做，只借 BCrypt 哈希口令 |
| Token | jjwt **0.12.5** | 自签 JWT，角色/权限不塞进 token（改权限要等过期才生效，见 21.5） |
| 模板 | spring-boot-starter-freemarker | 代码模板用 FTL 渲染 |
| 可观测 | Actuator + Micrometer（Boot 3.2.5 自带） | 第 16 章落地，不单独引 micrometer |
| 工具 | lombok / jsqlparser / mysql-connector-j | Lombok 省 getter；jsqlparser 给数据权限拦截器改写 SQL |

> ⚠️ 注意一个反直觉点：**codegen-server 没有启用完整 Spring Security**。它只用 `spring-security-crypto` 的 BCrypt。鉴权逻辑放在一个普通的 `OncePerRequestFilter` 里（21.5 详述）。这是"够用就别引入重依赖"的典型取舍。

---

## 21.2 核心模块地图

```
com.codegen
├── CodegenApplication          # 启动类（@SpringBootApplication + @MapperScan）
├── controller/                 # Web 层：GenController + MonitorController 等
├── service / service.impl/     # 业务层：GenCodeServiceImpl / GenApplyServiceImpl / PipelineExecutor ...
├── mapper/                     # DAO 层（MyBatis-Plus Mapper 接口）
├── entity/ vo/ dto/            # 领域模型 / 返回视图 / 入参
├── config/                     # 配置与装配：MybatisPlusConfig / AuthContextFilter /
│                               #   MonitorConfig / GenOutputProperties / MonitorProperties ...
├── monitor/                    # 可观测性：MonitorMetrics / MonitorSampler / MonitorStore /
│                               #   MonitorController / MetricSnapshot ...
├── common/                     # 横切：Result<T> 统一返回 / BusinessException /
│                               #   UserContext / 数据权限拦截器 DataScopeInterceptor / 审计切面
└── util/ support/              # 模板引擎、路径解析、合并工具、流水线组装
```

几个"看不见但贯穿全局"的 `common` 组件，正是前面章节的主角：

- **`Result<T>` + `BusinessException`**：统一返回与全局异常处理（第 7 章）；
- **`UserContext`**：登录上下文（ThreadLocal），由 `AuthContextFilter` 填充、finally 清理；
- **`DataScopeInterceptor`**：数据权限 SQL 改写（第 12 章 AOP/拦截器）；
- **操作日志切面**：依赖 `spring-boot-starter-aop`（pom 里特意引了 `aspectjweaver`）。

---

## 21.3 "一句话建系统"流水线：PipelineExecutor 12 步

比"生成几张表"更宏大的是 V5.0 的"一句话建系统"：给一个 DDL，自动建库建表、生成前后端、打包、部署、探活。这条流水线由 `PipelineExecutor` 串行执行，**每一步一行落库、状态变更即推 SSE**，任何一步失败即停：

```java
// 来源：com/codegen/service/impl/PipelineExecutor.java
public static final String[] STEP_KEYS = {
    "model",          // 1. 建模（AI 或手动，这里只补语义）
    "db",             // 2. 建库建表 + 导入表配置台账
    "ai_recommend",   // 3. AI 推荐三层页面配置（增强步骤，失败降级不阻断）
    "seed",           // 4. 生成示例数据
    "scaffold",       // 5. 脚手架：生成前后端骨架 + 种子 SQL
    "gen",            // 6. 代码生成（自检→备份→写盘→菜单→路由）
    "package_backend",// 7. mvn package 后端
    "deploy_backend", // 8. java -jar 启动后端（显式 --server.port）
    "package_frontend",// 9. npm install 前端
    "package_mobile", // 10. 移动端出包（H5 + 小程序，可跳过）
    "deploy_frontend",// 11. npm run serve 前端 dev server
    "health"          // 12. 双端端口就绪 + 前端 HTTP 可访问
};
```

每一步都带计时埋点，失败/降级都会写进 `pipeline.step` 指标：

```java
// 来源：同文件 execute(...)
Timer.Sample stepSample = monitorMetrics.start();
try {
    String message = switch (step.getStepKey()) { ... };  // 分发到 stepXxx
    mark(step, "success", message, null);
    monitorMetrics.stop(stepSample, "pipeline.step", "step", step.getStepKey(), "state", "success");
} catch (AiRecommendDegradedException e) {
    // AI 是增强步骤，失败只标记本步，流水线照走
    monitorMetrics.stop(stepSample, "pipeline.step", "step", ..., "state", "degraded");
} catch (Exception e) {
    monitorMetrics.stop(stepSample, "pipeline.step", "step", ..., "state", "failed");
    // ... 标记 failed，return 停线
}
```

注意第 6 步 `gen` 直接复用前面章节讲过的 `GenApplyServiceImpl.apply`——也就是"一键生成"子流水线（自检→备份→写盘→编译→注册菜单→重建路由）。**大流水线套小流水线，模块边界清晰**。

---

## 21.4 串起来：一次 `/gen/apply` 请求的完整链路

现在把前面 20 章的 knowledge 全部对号入座。前端点"一键生成"，请求打到 `POST /gen/apply`，看它怎么一路穿过各层：

### 链路总览（文字版时序）

```
浏览器
  │  POST /gen/apply  (Authorization: Bearer <jwt>)
  ▼
[1] 自动配置层   Spring 容器已就绪：Tomcat、HikariCP、Jackson、MP、Actuator
  │
  ▼
[2] Web 过滤链   AuthContextFilter（@Order 最高优先级）
  │   ① OPTIONS 预检直接放行  ② 取 token → jwtUtil 解析 userId/username
  │   ③ loadAuthority：查 sys_role/sys_user_role 填角色与数据权限
  │   ④ UserContext.setXxx()  → filterChain.doFilter  → finally UserContext.clear()
  ▼
[3] DispatcherServlet  →  HandlerMapping 命中 GenController.apply(...)
  │   入参 @Valid @RequestBody GenApplyDTO（参数名绑定靠 pom 的 -parameters，第 19 章提过）
  ▼
[4] 统一返回/异常   GenController 返回 Result<GenApplyVO>；任何 BusinessException 被全局异常
  │                 处理器包成 Result.fail(...)，不会裸抛 500
  ▼
[5] AOP / 拦截器   ① 操作日志切面（spring-boot-starter-aop）记录本次操作
  │               ② MybatisPlusInterceptor：DataScopeInterceptor 先缩数据范围，
  │                  PaginationInnerInterceptor 再分页（顺序不能反，见 MybatisPlusConfig）
  ▼
[6] Service 层     GenApplyServiceImpl.apply(ids)
  │   ├─ 自检  selfCheckService.check(ids)  —— 不通过直接 return，一个文件都不写
  │   ├─ 写盘  genCodeService.writeToDisk(dto, batchNo)
  │   │        ├─ monitorMetrics.start()            【可观测性：开始计时】
  │   │        ├─ clearProjectCache() 防读旧配置
  │   │        ├─ loadTablesInOrder：selectBatchIds 一次取表（防 N+1，第 19 章）
  │   │        ├─ writeTable：逐文件 Files.writeString + 覆盖前备份 + 块合并
  │   │        ├─ recordOutput：每条文件 INSERT gen_output 台账（失败只 warn 不阻断）
  │   │        └─ finally: monitorMetrics.finishWrite(sample, success, statusCounts)
  │   │                                          【可观测性：gen.write timer + 分状态计数】
  │   ├─ 编译  mvn compile（可选，后台工程根目录，日志重定向防管道死锁）
  │   ├─ 注册菜单 genMenuService.register(...)
  │   └─ 重建路由 genMenuService.syncRoute(false)
  ▼
[7] DAO / MyBatis-Plus   GenTableMapper / GenOutputMapper 走 MP 自动实现；
  │                  JdbcTemplate 直接执行部分 SQL（如 last_gen_time 更新）
  ▼
[8] 事务边界   写盘是"文件系统 + 数据库"的跨资源操作，无法用一个 DB 事务包住；
  │           所以 codegen 不用大事务，而是用 gen_output 台账 + 回滚接口实现"准事务"：
  │           每一份写动作都留痕，事后可精确还原/删除（见 GenApplyServiceImpl.rollbackPlan）
  ▼
[9] 可观测性收口   MonitorSampler 每 5s 把 Micrometer 累计值做区间差分，
  │             落进 MonitorStore 环形缓冲；前端 /monitor/business 直接看 gen.write 成功率与耗时
  ▼
[10] 安全收口   全程基于 UserContext 里的 userId/角色/数据权限；
  │           JWT 只带身份，角色权限实时查库——改权限立即生效，不要等 token 过期
  ▼
返回 Result<GenApplyVO>（含各阶段 PASS/FAILED、写盘数、台账错误数、备份目录）
```

### 把"前面学的"逐项点名

| 前面章节 | 在这一次请求里的落点（真实代码） |
|----------|------------------------------|
| 自动配置（第 2~3 章） | `@SpringBootApplication` + 各 starter 自动装配 Tomcat/HikariCP/Jackson/MP/Actuator |
| Web（第 5 章） | `DispatcherServlet` → `GenController`，`@RestController`/`@PostMapping`/`@Valid` |
| 统一返回（第 7 章） | `Result<T>` 包裹；`BusinessException`→全局异常→`Result.fail` |
| AOP/拦截器（第 12 章） | 操作日志切面 + `MybatisPlusInterceptor`（数据权限 + 分页） |
| MyBatis-Plus（第 13 章） | `GenTableMapper.selectBatchIds` 批量取表；`LambdaQueryWrapper` 查列 |
| 事务（第 14 章） | 跨资源写盘不用单 DB 事务，改用 gen_output 台账 + 回滚实现准事务 |
| 安全（第 15 章） | `AuthContextFilter` 鉴权 + `UserContext` + BCrypt；角色权限实时查库 |
| 可观测性（第 16 章） | `MonitorMetrics.start/finishWrite` 包住写盘；`MonitorSampler`/`MonitorController` 暴露 |
| 性能（第 19 章） | `selectBatchIds` 防 N+1；`scheduling.pool.size=2`；写盘计时定位瓶颈 |
| 部署（第 20 章） | 有状态单体、`${ENV:default}` 外部化、systemd/Nginx、写盘落本地目录 |

> 这就是你读到的"顿悟"时刻：**没有哪一章是孤岛**。自动配置把零件装好，Web 把请求接进来，安全先验身，AOP 补审计与数据权限，MyBatis 落地 SQL，事务/台账保证"写坏能回"，可观测性全程记点，最后统一返回包成 `Result` 出去——一次请求，二十章知识，全用上了。

---

## 21.5 设计取舍里的"为什么"

### 为什么角色权限不写进 JWT？

`AuthContextFilter.loadAuthority` 每次请求都查 `sys_role` / `sys_user_role` 拿角色和数据权限范围：

```java
// 来源：com/codegen/config/AuthContextFilter.java
// 角色/部门/权限范围从库里查：写进 token 会因改权限要等 token 过期才生效
loadAuthority(userId);
```

代价是每次请求多一两条 SQL；收益是**改权限立即生效**。对于内部平台，"正确性"优先级高于"省两次查询"，而且这两次查询本来就在连接池里、开销极小。

### 为什么写盘不用一个数据库事务包住？

写盘同时动"本地文件系统"和"gen_output 表"，二者无法纳入同一个 ACID 事务。codegen 的答案是：

- 文件写哪、写了什么、写前 MD5（`prevMd5`）、备份路径，全部**逐文件记进 gen_output**；
- 失败时文件已落盘也不回滚（回滚它更糟），但把"台账失败条数"通过 `X-Gen-Ledger-Errors` 响应头暴露给前端；
- 需要撤销时走 `rollbackPlan`：按台账精确还原/删除，甚至回滚动作本身也入台账，保证"回滚可再回滚"。

这是一个"**用业务台账替代分布式事务**"的务实范本。

### 为什么监控是进程内、不接 Prometheus？

`MonitorStore` 注释写得很直白：纯内存环形缓冲，重启归零、多实例不共享。`MetricSnapshot` 存的是区间差分而非累计值，避免"30 分钟曲线一路向上"。对单实例内部平台够用；要全局看板再接远端注册（第 19 章已说明多实例限制）。

---

## 本章小结

- codegen-server 是一个**零中间件、有状态的单体**：`@SpringBootApplication` + `@MapperScan` 即起，连 MySQL 即可跑；
- 技术栈决策环环相扣：轻依赖 → 易部署（第 20 章）；有状态 → 写盘落本地、监控在进程内（第 19 章）；
- 核心模块 `controller/service/dao/config/monitor/common` 各司其职，`common` 里藏着贯穿全局的统一返回、上下文、数据权限、审计；
- "一句话建系统"由 `PipelineExecutor` 的 **12 步串行流水线**完成，每步落库 + 推 SSE + 埋点，AI 推荐是"失败降级不阻断"的增强步骤；
- 一次 `/gen/apply` 把自动配置、Web、统一返回、AOP 审计、MyBatis、事务/台账、可观测性、安全**全部串起**——前面 20 章不是孤岛，而是这一条链上的零件。

⚠️ **踩坑提示（本章）**：codegen-server 的"轻依赖"是把双刃剑——它没有用 Spring Security 的过滤器链，而是自己写 `AuthContextFilter`。**任何新增的全局 Filter 都要显式声明 `@Order`**，否则可能排在鉴权之前导致未登录就能访问；同时白名单（`/actuator/health`、`/v3/api-docs` 等）一旦写漏，要么该放行的被拦、要么该拦的被放。鉴权是系统的"门"，门的清单永远值得反复核对。

---

## 21.6 给想深入的你：还能从 codegen 学什么

本书讲的是"主线"，codegen-server 里还有不少值得临摹的工程细节，作为你继续探索的路标：

- **幂等设计**：流水线任意一步失败都可整线重跑（所有落盘动作幂等），`GenApplyServiceImpl` 的回滚甚至"回滚可再回滚"——这是把"重跑即恢复"做成一等公民；
- **降级不阻断**：AI 推荐/AI 种子失败只标记 `degraded`，绝不让增强功能拖垮主线（见 `AiRecommendDegradedException`）；
- **文档即真相**：`MetricSnapshot` 用 `record` + 不可变快照，区间差分而不是累计值，前端拿到的是同一口径的曲线与聚合；
- **跨资源一致性**：用业务台账替代分布式事务，是中小团队最务实的"准事务"范本；
- **诚实的边界**：代码生成不是"写个模板就完事"，自检（内存编译）、漂移检测、块合并（保留用户手写代码）才是它能在生产里用的原因；
- **配置分层**：`application.yml` 给默认值、`application-local.yml` 放本机路径、环境变量覆盖密钥——三层互不污染，新人克隆即跑、运维改环境即上线。

把这些和前面 20 章对照着读，你会发现：**Spring Boot 的威力不在某个注解，而在它把"配置、Web、数据、安全、观测"拧成一条默认就能跑、按需可替换的流水线**——这正是 codegen-server 这整个案例存在的意义。

顺着这条线读下去，你会从"会用 Spring Boot"走到"懂得为什么这么设计"——这也是本书希望留给你的最后一课。
