# 第 13 章 异步与定时任务：@Async 与 @Scheduled

## 本章目标

读完本章你将能够：

- 用 `@EnableAsync` + `@Async` 把耗时操作异步化，并自定义线程池替代默认的 `SimpleAsyncTaskExecutor`。
- 用 `@EnableScheduling` + `@Scheduled` 配置定时任务，搞清 `cron` / `fixedRate` / `fixedDelay` 三者的区别。
- 看懂 codegen-server 的调度线程池配置，以及 `MonitorSampler` 如何用 `@Scheduled` 做指标定时采样。
- 理解异步任务与第 11 章 `UserContext`（ThreadLocal）之间的「跨线程失效」陷阱。

---

## 13.1 @Async：让方法异步执行

`@Async` 标注的方法会在独立线程中执行，调用方不阻塞等待。典型场景：记录操作日志、发送通知、触发代码生成等「主流程不必等它」的操作。

```java
@Service
public class NotifyService {

    @Async
    public void sendCodeGenDone(Long userId, String tableName) {
        // 耗时通知逻辑，主流程不等它
    }
}
```

启用只需：

```java
@Configuration
@EnableAsync
public class AsyncConfig {
}
```

### 13.1.1 为什么必须自定义线程池

⚠️ **踩坑提示（极其重要）**：`@Async` 默认使用 `SimpleAsyncTaskExecutor`。这个执行器**每次提交任务都 new 一个线程**，不做任何复用、不限制上限。高并发下线程数会失控暴涨，直到耗尽系统资源、触发 OOM 或拖垮整个 JVM。生产环境**必须**自定义线程池。

自定义方式——提供一个 `TaskExecutor` 或 `Executor` 类型的 `@Bean`，Spring 会自动把它用作 `@Async` 的默认执行器：

```java
@Configuration
@EnableAsync
public class AsyncConfig {

    @Bean("taskExecutor")
    public Executor taskExecutor() {
        ThreadPoolTaskExecutor executor = new ThreadPoolTaskExecutor();
        executor.setCorePoolSize(8);            // 核心线程数
        executor.setMaxPoolSize(32);            // 最大线程数
        executor.setQueueCapacity(200);         // 队列容量
        executor.setThreadNamePrefix("async-"); // 线程名前缀，便于排查
        executor.setRejectedExecutionHandler(new ThreadPoolExecutor.CallerRunsPolicy());
        executor.initialize();
        return executor;
    }
}
```

（`**此为通用示例**`，演示标准写法；codegen-server 的 `@Async` 若有则会复用此 Bean）

要点：

- `CallerRunsPolicy` 表示队列满时由调用方线程自己执行，避免直接丢任务；也可选 `AbortPolicy`（抛异常）或 `DiscardOldestPolicy`。
- 通过 `@Async("taskExecutor")` 可指定用哪个执行器；不指定则用上面这个默认 Bean。

---

## 13.2 @Scheduled：定时任务

`@Scheduled` 用于周期性执行，三兄弟：

| 属性 | 含义 | 示例 |
|------|------|------|
| `fixedRate` | 固定频率：上次**开始**到下次**开始**的间隔 | `@Scheduled(fixedRate = 5000)` 每 5 秒一次（不管上次跑多久） |
| `fixedDelay` | 固定间隔：上次**结束**到下次**开始**的间隔 | `@Scheduled(fixedDelay = 5000)` 跑完歇 5 秒再跑 |
| `cron` | 类 Unix cron 表达式，最灵活 | `@Scheduled(cron = "0 0 2 * * ?")` 每天凌晨 2 点 |

⚠️ **踩坑提示（真实 bug）**：`fixedRate` 和 `fixedDelay` 别混用。若某个任务单次执行可能超过间隔（比如采样偶尔卡 6 秒），用 `fixedRate=5000` 会导致任务「背靠背」堆积、线程被占满；而 `fixedDelay` 保证「跑完才歇」，天然错峰。codegen-server 的采样器就刻意用了 `fixedDelay`（见 13.4）。

启用定时任务：

```java
@Configuration
@EnableScheduling
public class SchedulingConfig {
}
```

### 13.2.1 配置线程池大小

Spring Boot 的 `spring.task.scheduling` 可配调度线程池大小。codegen-server 在 `application.yml` 里写明：

```yaml
# V6.10 平台首次引入调度（MonitorSampler）。默认单线程，将来再加定时任务会互相阻塞
task:
  scheduling:
    pool:
      size: 2
```

（`application.yml` 第 26–30 行）

**为什么配 size: 2？** 调度线程池默认是**单线程**的。如果只有一个 `@Scheduled` 方法还好；一旦再加第二个定时任务，它们会**互相阻塞**——前一个没跑完，后一个只能排队。预留 2 个线程，是为后续扩展留余地。codegen-server 把 `@EnableScheduling` 单独放在 `MonitorConfig` 里，不污染主启动类：

```java
@Configuration
@EnableScheduling
public class MonitorConfig {
}
```

（`MonitorConfig.java` 全文）

---

## 13.3 codegen-server 的定时采样实战

`MonitorSampler` 是 codegen-server 里唯一使用 `@Scheduled` 的类，承担了「指标定时采样」的职责。

### 13.3.1 采样入口

```java
@Component
public class MonitorSampler {

    @Scheduled(fixedDelayString = "${monitor.sample.interval-ms:5000}")
    public void sampleOnce() {
        try {
            store.add(collect());           // 采一轮，写入环形缓冲
        } catch (Exception e) {
            // 单轮失败不能让定时任务停摆：下一轮 fixedDelay 继续执行
            log.warn("指标采样失败（不影响业务）：{}", e.getMessage());
        }
    }
    // ...
}
```

（`MonitorSampler.java` 第 27–58 行）

几个真实设计点，值得借鉴：

1. **用 `fixedDelayString` 而非 `fixedRate`**：字符串形式可从配置读（默认 5000ms），且用 `fixedDelay` 保证「跑完歇一会」，避免采样任务堆叠。
2. **`collect()` 抛异常只 warn 不抛出**：注释里写得很清楚——`fixedDelay` 任务若抛异常，并不会「补采」，面板只会静默停更。所以这里把异常吞掉并打 warn，保证采样线程永不死。
3. **采样失败不影响业务**：指标是「可观测性」，绝不能因为 metrics 坏了而让代码生成主流程失败。

### 13.3.2 为什么存「区间差分」而不是累计值

```java
/**
 * 定时采样：把 Micrometer 的累计值换算成**区间差分**后放进环形缓冲。
 *
 * <p>为什么不直接存累计值：`http.server.requests` 的 count/totalTime 是从启动累计的，
 * 直接展示会让「近 30 分钟」的曲线一路向上，窗口聚合也失去意义。
 */
```

（`MonitorSampler.java` 第 18–26 行 注释）

Micrometer 的 `count`/`totalTime` 是从进程启动就一直累加的。如果直接把累计值存进环形缓冲，那么「近 30 分钟曲线」会一路向上爬，完全失真。所以 `MonitorSampler` 在 `collect()` 里做**区间差分**——用「本轮累计 − 上一轮累计」得到本窗口内的增量，再存快照（见第 39–43 行保存 `prevHttpTimers/prevBuckets/prevBusiness` 上一轮值）。这正是把「累计计数器」转成「速率/增量」的标准做法。

采样配置来自 `MonitorProperties`（绑定 `monitor` 前缀），缓冲窗口 = 5s × 360 = 30 分钟，重启归零、多实例不共享（见第 12 章 12.4 节）。

---

## 13.4 异步任务与 UserContext 的协作边界

把第 11 章（鉴权）、第 12 章（缓存）和本章串起来，有一个必须警惕的边界问题：

**`@Async` 方法的执行线程是线程池里的另一条线程，它读不到主线程 `UserContext` 里的 `ThreadLocal` 数据。**

```java
@Async
public void auditAfterGenerate(Long tableId) {
    // 这里 UserContext.getUserId() 很可能返回 null！
    // 因为本方法跑在 async- 线程池，不是处理 HTTP 请求的 Tomcat 线程
}
```

（`**此为通用示例 + 风险说明**`，codegen-server 若用 @Async 需手动传递上下文）

应对方式：

1. **调用前手动传递**：在同步方法里先把 `UserContext.getUserId()` 取出来，作为参数传给异步方法。
2. **用 `TransmittableThreadLocal`**（阿里 TTL）替代 `ThreadLocal`，在线程池提交任务时自动把父线程上下文复制到子线程。
3. **异步方法不依赖 UserContext**：像 `MonitorSampler` 这样完全不碰用户上下文，只读全局指标——这是最干净的设计。

> 这也是 codegen-server 把「权限加载」放在 `AuthContextFilter`（同步 HTTP 线程内）而不是异步任务里的根本原因：鉴权上下文天然绑定单次请求线程。

---

## 本章小结

- `@EnableAsync` + `@Async` 让方法异步执行；但默认 `SimpleAsyncTaskExecutor` 每任务 new 线程，**生产必须自定义 `ThreadPoolTaskExecutor`** 并限制核心/最大线程数与队列。
- `@Scheduled` 三兄弟：`fixedRate`（开始到开始）、`fixedDelay`（结束到开始）、`cron`（表达式）。周期任务单次可能超间隔时优先 `fixedDelay`，避免堆积。
- 调度线程池默认单线程，多个定时任务会互相阻塞；codegen-server 在 `application.yml` 用 `spring.task.scheduling.pool.size: 2` 预留并发度。
- `MonitorSampler` 用 `@Scheduled(fixedDelayString=...)` 周期性采样，异常只 warn 不抛出（防任务停摆），并把 Micrometer 累计值转成区间差分后存入 `MonitorStore` 环形缓冲——是「可观测性解耦业务」的好范例。
- `@Async` 的线程池线程**读不到**主线程 `UserContext` 的 ThreadLocal，需手动传参或用 TTL 跨线程传递；最佳实践是让异步/定时任务不依赖请求级上下文。
