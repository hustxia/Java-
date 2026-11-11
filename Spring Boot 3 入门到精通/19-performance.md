# 第 19 章 性能调优：先度量，再动手

## 本章目标

读完本章你将掌握：

- 如何用 JVM 参数与 GC 选择为 Spring Boot 3（Java 21）打好底座；
- HikariCP 连接池的关键参数与默认值背后的取舍；
- Web 容器线程池与 Spring 调度线程池（`spring.task.scheduling`）的调优要点；
- 慢 SQL 的识别与治理套路；
- **最重要的一条：用第 16 章搭建的 monitor 指标先定位瓶颈，再谈优化**——codegen-server 已经把这套度量埋到了写盘主流程里，本章就带你用它发现"慢写盘"。

> 性能优化最大的谎言是"我猜它慢"。真实工程里，永远先有数据、后有结论。

---

## 19.1 性能优化的第一条军规：先度量，再动手

codegen-server 在 V6.10 落地了一整套可观测性（详见第 16 章），其中业务埋点被收敛在 `MonitorMetrics` 里，并且**全部包在 try/catch 中**——度量本身绝不能拖垮业务主流程：

```java
// 来源：com/codegen/monitor/MonitorMetrics.java
public void stop(Timer.Sample sample, String name, String... tags) {
    try {
        Timer.Builder builder = Timer.builder(name);
        for (int i = 0; i + 1 < tags.length; i += 2) {
            builder.tag(tags[i], tags[i + 1]);   // tags 按 key,value 成对传入
        }
        sample.stop(builder.register(registry));  // 打点失败也不影响业务
    } catch (Exception e) {
        log.debug("指标埋点失败（已忽略）：{} - {}", name, e.getMessage());
    }
}
```

写盘（最容易被人追问"怎么这么慢"的环节）在入口就开了计时，在 `finally` 里收尾：

```java
// 来源：com/codegen/service/impl/GenCodeServiceImpl.java  writeToDisk(...)
Timer.Sample sample = monitorMetrics.start();   // 进入写盘即计时
boolean success = false;
try {
    // ... 渲染、备份、逐文件写盘 ...
    success = true;
    return results;
} finally {
    // 从结果集统计各状态文件数（WRITTEN/MERGED/SKIPPED/ERROR），不额外扫磁盘
    Map<String, Integer> statusCounts = new HashMap<>();
    for (GenWriteVO r : results) {
        if (r.getStatus() != null) {
            statusCounts.merge(r.getStatus(), 1, Integer::sum);
        }
    }
    monitorMetrics.finishWrite(sample, success, statusCounts);  // 一次 timer + 按状态计数
}
```

`finishWrite` 正是"先度量"的落点：它既记录了 `gen.write` 这个 Timer（带 `result=success/fail` tag），也按文件状态记了 `gen.write.files` 计数器：

```java
// 来源：com/codegen/monitor/MonitorMetrics.java
public void finishWrite(Timer.Sample sample, boolean success, Map<String, Integer> fileStatusCounts) {
    try {
        fileStatusCounts.forEach((status, count) ->
                count("gen.write.files", count, "status", status));   // 分状态计数
    } catch (Exception e) { log.debug("写盘文件数埋点失败（已忽略）：{}", e.getMessage()); }
    stop(sample, "gen.write", "result", success ? "success" : "fail");
}
```

这些数据最终被 `MonitorSampler` 按 5s 区间差分、落进 `MonitorStore` 的环形缓冲，再由 `MonitorController` 暴露给前端。也就是说：**你不需要临时加日志、不需要复现问题，打开监控页就能看到写盘耗时、各状态文件分布、慢接口排行**。这就是"先度量"的工程化形态。

---

## 19.2 JVM 参数与 GC 选择

### 19.2.1 默认值已经很强

Spring Boot 3 搭配 Java 21，默认就站在了一个不错的起点上：

- 默认 GC 是 **G1**（JDK 9+ 起），吞吐与停顿的平衡已经很好，绝大多数单体服务不需要换；
- 堆大小默认是物理内存的 **1/4**（`-XX:MaxRAMPercentage=25.0`），容器里也按 cgroup 限制走，不会撑爆；
- 元空间默认不受限（随用随涨，但会受 `-XX:MaxMetaspaceSize` 约束）。

对 codegen-server 这种"平时闲、生成时忙一阵"的单体，G1 足矣，**不要盲目上 ZGC/Shenandoah**——它们为超低延迟设计，代价是更高的内存与 CPU 占用，业务体感未必更好。

### 19.2.2 一个可复用的启动参数模板

```bash
# 生产启动示例（此为通用示例，非 codegen 专属）
java -Xms2g -Xmx2g \
     -XX:MaxMetaspaceSize=256m \
     -XX:+UseG1GC \
     -XX:MaxGCPauseMillis=200 \
     -XX:+HeapDumpOnOutOfMemoryError \
     -XX:HeapDumpPath=/var/log/codegen/heapdump.hprof \
     -jar codegen-server.jar
```

关键点：

- **`-Xms` 与 `-Xmx` 设成相同值**：避免运行时动态扩缩堆带来的抖动，也让运维对"用了多少"心里有数；
- **`MaxGCPauseMillis` 是目标而非承诺**：G1 会尽量贴近，但不会牺牲吞吐硬卡；
- **OOM 必须留堆转储**：没有 hprof，事后排查基本靠猜。codegen-server 写盘涉及大量 `Files.writeString` 与 `ByteArrayOutputStream`，内存异常时 dump 是唯一的真相来源。

> ⚠️ 踩坑提示：容器里只给 512M 内存却用默认 `MaxRAMPercentage=25%`，JVM 最多只用 128M，业务稍一并发就频繁 GC。要么调大容器内存，要么显式 `-Xmx`。在 K8s 里，**务必同时配 `resources.limits` 与 JVM 的 `-Xmx`**，让两者一致。

---

## 19.3 数据库连接池 HikariCP

Spring Boot 3 默认就是 **HikariCP**，零配置即可用。codegen-server 在 `application.yml` 里没有覆盖任何连接池参数，因此完全走默认：

```yaml
# 来源：src/main/resources/application.yml（节选）
spring:
  datasource:
    url: jdbc:mysql://localhost:3306/gen_platform?...
    username: ${DB_USERNAME:root}      # 生产必须环境变量覆盖
    password: ${DB_PASSWORD:root}
    driver-class-name: com.mysql.cj.jdbc.Driver
```

HikariCP 最重要、最容易被误配的几个参数如下（**此为通用示例**，演示需要时在 `spring.datasource.hikari.*` 下配置）：

```yaml
# 此为通用示例：codegen 当前未显式配置，故走 Hikari 默认
spring:
  datasource:
    hikari:
      maximum-pool-size: 10          # 默认 10；公式 ≈ CPU核数*2 + 磁盘数，DB 密集可略增
      minimum-idle: 10               # 默认与 maximum-pool-size 相等（池子不收缩）
      connection-timeout: 30000      # 拿连接最多等 30s，超时抛异常
      idle-timeout: 600000          # 空闲连接 10min 后回收（仅当 minimum-idle < maximum 时生效）
      max-lifetime: 1800000         # 连接最长存活 30min，小于 DB/中间件空闲断开时间，防"断开的连接"
      pool-name: codegen-pool
```

**为什么 `max-lifetime` 是必看项**：MySQL 服务端 `wait_timeout` 默认 8 小时，云数据库 RDS 常设为几分钟。如果池子里的连接比服务端空闲阈值活得久，就会拿到"已断开的连接"，表现成偶发的 `com.mysql.cj.jdbc.exceptions.CommunicationsException: The last packet successfully received from the server was ...`。经验值是把 `max-lifetime` 设得**比服务端超时短 30s~1min**。

codegen-server 目前连接池够用（生成后台操作以短事务为主），若上线后监控发现 `http.server.requests` 出现周期性尖刺、且伴随 `HikariPool-1 - Connection is not available`，就该调大 `maximum-pool-size` 并核对 `max-lifetime`。

---

## 19.4 Web 与调度线程池

### 19.4.1 Web（Tomcat）线程池

Spring Boot 内嵌 Tomcat 默认 **最大 200 个工作线程、等待队列无限**。对 codegen-server 这种内部平台足够。若要做背压（防止突发打爆后端），可在 `application.yml` 配置：

```yaml
# 此为通用示例
server:
  tomcat:
    threads:
      max: 200            # 最大工作线程
      min-spare: 10       # 常驻空闲线程，避免冷启动瞬时建线程
    accept-count: 100     # 队列满后还能排多少连接
    max-connections: 10000
```

### 19.4.2 调度线程池（Spring Scheduling）

codegen-server 在 V6.10 第一次引入调度（`MonitorSampler` 定时采样），并在 yml 里显式给了大小——因为**默认是单线程**：

```yaml
# 来源：src/main/resources/application.yml
spring:
  task:
    scheduling:
      pool:
        size: 2            # 默认单线程；将来再加定时任务会互相阻塞，故预留 2
```

配套的开关就在 `MonitorConfig` 上，单独一个类、不污染主启动类：

```java
// 来源：com/codegen/config/MonitorConfig.java
@Configuration
@EnableScheduling
public class MonitorConfig {
}
```

> ⚠️ 踩坑提示：Spring `@Scheduled` 默认**所有任务共享一个单线程调度器**。一旦某个任务卡住（比如采样时查了慢查询），后续所有定时任务都会排队。codegen-server 主动把 `size` 提到 2，正是对这一点的防御。如果你将来加 `@Async` 异步任务，**默认 `SimpleAsyncTaskExecutor` 是无界创建线程**，必须用 `@Bean` 自定义一个带上限的 `ThreadPoolTaskExecutor`，否则高并发下线程数爆炸。

---

## 19.5 慢 SQL 治理

慢 SQL 是后端性能的头号杀手。codegen-server 里能"写出慢 SQL"的地方不少，举两个真实代码中的隐患与应对：

### 19.5.1 N+1 与逐表查询

`GenCodeServiceImpl` 在批量生成时有个很讲究的细节——**不逐表查库**：

```java
// 来源：com/codegen/service/impl/GenCodeServiceImpl.java  loadTablesInOrder(...)
// 逐个 selectById 会把「勾 30 张表」放大成 30 次数据库往返；
// 用 selectBatchIds 一次取回，再按入参顺序重组（下游文件/台账/回滚都依赖这个顺序）
Map<Long, GenTable> byId = new HashMap<>();
for (GenTable table : genTableMapper.selectBatchIds(ids)) {
    byId.put(table.getId(), table);
}
```

同样，`projectOf` 用请求内 `Map` 缓存挡住"批量生成几十张表→几十次重复查询系统配置"：

```java
// 来源：同上  projectOf(...)
if (projectCache.containsKey(projectId)) {  // 不用 computeIfAbsent：selectById 返回 null 时也要缓存
    return projectCache.get(projectId);
}
SysProject project = projectMapper.selectById(projectId);
projectCache.put(projectId, project);
```

### 19.5.2 用 monitor 的慢接口排行定位

第 16 章的 `MonitorController` 已经把 HTTP 指标做成了"慢接口排行"，按平均耗时倒序返回：

```java
// 来源：com/codegen/controller/MonitorController.java  http(...)
List<MonitorHttpVO.SlowUri> slow = new ArrayList<>();
stats.getByUri().forEach((key, delta) -> {
    if (delta[0] <= 0) return;
    // ... 拆分 method/uri，组装 SlowUri ...
    item.setAvgMs(r2(delta[1] / delta[0]));   // 平均耗时
    item.setMaxMs(r2(delta[2]));               // 区间最大耗时
});
slow.sort(Comparator.comparingDouble(MonitorHttpVO.SlowUri::getAvgMs).reversed());
vo.setTopSlow(...);   // 前端直接拿到 Top N 慢接口
```

同时 P95/P99 来自直方图的区间差分（`MonitorSampler.collectHttp` 里 `takeSnapshot().histogramCounts()`），比单纯看平均更能暴露长尾。

**慢 SQL 治理套路**：先看监控页 Top 慢接口 → 定位到具体 URI → 进对应 Service 看这条链路打了几条 SQL → 用 `selectBatchIds` / 缓存 / 分页合并掉循环查询 → 再回监控验证曲线是否下来。这正是一节开头说的"先度量，再优化"。

---

## 19.6 实战：用指标抓出一次"慢写盘"

把前面几节串起来，假设运维反馈"点一次生成要好几秒"。排查路径如下：

1. 打开 `GET /monitor/business`，看 `gen.write` 的 `success` 次数与平均耗时 `avgMs`——这是 19.1 埋的 `gen.write` Timer 的聚合；
2. 看 `gen.write.files` 的 `WRITTEN/MERGED/SKIPPED/ERROR` 分布，判断是文件多还是单文件慢；
3. 打开 `GET /monitor/http` 的 `topSlow`，确认 `/gen/write` 是否进了慢接口榜、P95 多少；
4. 若确认写盘慢，回到 `GenCodeServiceImpl.writeTable`：逐文件 `Files.writeString` + 覆盖前备份 `Files.copy` + 文件级台账 `recordOutput`（每条 INSERT）。文件数一多，磁盘 IO 与逐条 INSERT 就是瓶颈——这时再考虑"批量落台账"或"异步备份"，而不是一上来就改 JVM。

注意 `recordOutput` 即使失败也只 `log.warn` + 计数，不阻断写盘——因为文件已经落盘，回滚它更糟：

```java
// 来源：com/codegen/service/impl/GenCodeServiceImpl.java  recordOutput(...)
} catch (Exception e) {
    LEDGER_ERRORS.set(LEDGER_ERRORS.get() + 1);   // 用 ThreadLocal 隔离，单例 Service 不串请求
    log.warn("写盘台账记录失败（文件已落盘，不影响写盘结果）：batch={} ...", ...);
}
```

这就是"度量—定位—决策"的闭环：**指标告诉你哪慢，代码告诉你为什么慢，优化才有方向**。

---

## 本章小结

- 性能优化第一条军规是**先度量、后优化**，codegen-server 的 `MonitorMetrics`/`MonitorSampler`/`MonitorController` 已把写盘耗时、慢接口排名、P95/P99 做成现成数据；
- JVM 用 G1 + 固定堆（`-Xms=-Xmx`）+ OOM 堆转储，容器里务必让 `-Xmx` 与 limit 一致；
- HikariCP 默认够用，重点关注 `maximum-pool-size` 与 `max-lifetime`（防断开连接）；
- Web 线程池默认 200，调度线程池默认单线程——codegen-server 已把 `spring.task.scheduling.pool.size` 提到 2 防御单线程阻塞；
- 慢 SQL 治理靠"监控定位 → 合并循环查询（`selectBatchIds`/缓存）→ 回监控验证"，根除 N+1。

⚠️ **踩坑提示（本章）**：不要为"可能慢"提前加缓存、加线程池、换 GC。codegen-server 里 `projectOf` 的缓存、`scheduling.pool.size=2`、都是"先发现瓶颈再补"的结果，不是预防性过度设计。**没有度量支撑的优化，多半是给未来埋坑。**
