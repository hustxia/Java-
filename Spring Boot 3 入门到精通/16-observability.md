# 第 16 章 可观测性：Actuator 与 Micrometer 落地

## 本章目标

「连上 MySQL 就能跑」的单体平台，未必需要 Prometheus + Grafana 全家桶。本章以 codegen-server 的真实可观测性实现为标杆案例，讲透：

- **Actuator** 端点暴露（`health` / `info` / `metrics`）与最小暴露面安全；
- **Micrometer** 三大原语 **Timer / Gauge / Counter** 如何埋点；
- 如何用一个**自定义环形缓冲 + 定时采样**，把累计指标换算成「近 30 分钟窗口」的差分序列，零外部依赖地撑起平台级监控面板；
- 业务埋点如何与 `MonitorController` 的四个 `/monitor/*` 接口、以及 `monitor:view` 权限结合；
- Prometheus + Grafana 的接入思路（通用示例）。

本章全部真实片段来自 codegen-server 的 `monitor` 包与 `config` 包，源文件路径见文中标注。

## 16.1 为什么不用全套监控栈

很多团队一谈可观测性就上 Prometheus + Pushgateway + Grafana + 自建 exporter，对「连库即跑」的内部平台是过度工程。codegen 的取舍很务实（来源 `pom.xml` 注释）：**Boot 3.2.5 自带 Micrometer 1.12，Actuator 直接依赖即用，不单独引**。只需要：

1. Actuator 暴露有限的几个端点；
2. Micrometer 持续累计 HTTP、JVM、业务指标；
3. 一个定时任务把累计值做**区间差分**写进进程内环形缓冲；
4. Controller 把缓冲收敛成前端要的 JSON。

这样一个进程内、重启归零、多实例不共享的轻量方案，对单实例管理后台已经足够有效。

## 16.2 Actuator 端点与最小暴露面

Actuator 默认暴露面很宽（env / heapdump / threaddump 都能查数据库口令、dump 内存）。codegen 在 `application.yml` 里把暴露面**枚举收窄**（来源 `src/main/resources/application.yml`）：

```yaml
# 来源：src/main/resources/application.yml
management:
  endpoints:
    web:
      exposure:
        include: health,info,metrics      # 只放这三个，env/beans/heapdump/threaddump 永不暴露
  endpoint:
    health:
      show-details: never                 # 外部只看得到 {"status":"UP"}，不吐数据库地址
  metrics:
    tags:
      application: codegen-server         # 所有指标自动带 application 标签，多实例聚合时区分
    web:
      server:
        max-uri-tags: 100
    distribution:
      percentiles-histogram:
        "[http.server.requests]": true    # 开 HTTP 请求耗时直方图，才能算 p95/p99
```

> 注意带点的 key 必须写成 `"[http.server.requests]"`（引号 + 方括号），否则 YAML 会按点拆成多层结构，配置失效。codegen 因此专门写了 `MonitorConfigTest` 做安全基线断言（来源 `src/test/java/com/codegen/config/MonitorConfigTest.java`）：

```java
// 来源：src/test/java/com/codegen/config/MonitorConfigTest.java（节选）
@Test
void exposureIsEnumeratedAndHealthHidesDetails() throws IOException {
    PropertySource<?> ps = load();
    String include = String.valueOf(ps.getProperty("management.endpoints.web.exposure.include"));
    assertTrue(include.contains("health"));
    assertTrue(include.contains("metrics"));
    assertFalse(include.contains("env"), "env 绝不能暴露，里面有数据库口令");
    assertFalse(include.contains("heapdump"));
    assertFalse(include.contains("loggers"));
    assertEquals("never", ps.getProperty("management.endpoint.health.show-details"));
}
```

⚠️ 踩坑提示：`health.show-details` 默认在敏感端点关闭时是 `never`，但一旦你用 `management.endpoint.health.show-details=always` 图方便调试，health 会把数据库连接串、磁盘路径一并吐给任意能访问 `/actuator/health` 的人。`never` 才是生产默认值。

## 16.3 Micrometer 三大原语：Timer / Gauge / Counter

Micrometer 把度量抽象成与后端（Prometheus、InfluxDB…）无关的原语，由 `MeterRegistry` 统一注册：

- **Timer**：记录「次数 + 耗时」，自动给出 count、总和、最大、直方图桶。最适合 API 耗时、业务处理耗时。
- **Gauge**：瞬时值（如 JVM 内存、线程数、队列长度），由注册时的 getter 实时采样。
- **Counter**：只增计数器，记录「发生了多少次」（如文件落盘数、错误数）。

codegen 把三者包在 `MonitorMetrics` 里，并对**每一次埋点做 try/catch 隔离**——指标坏掉绝不能连带生成主流程失败（来源 `src/main/java/com/codegen/monitor/MonitorMetrics.java`）：

```java
// 来源：src/main/java/com/codegen/monitor/MonitorMetrics.java（节选）
@Component
public class MonitorMetrics {

    private final MeterRegistry registry;

    public Timer.Sample start() {
        return Timer.start(registry);            // 计时起点：业务开始处取 sample
    }

    /** 停止计时并打上 tag；tags 按 key,value 成对传入 */
    public void stop(Timer.Sample sample, String name, String... tags) {
        try {
            Timer.Builder builder = Timer.builder(name);
            for (int i = 0; i + 1 < tags.length; i += 2) {
                builder.tag(tags[i], tags[i + 1]);   // 用 tag 区分成功/失败、不同步骤
            }
            sample.stop(builder.register(registry));
        } catch (Exception e) {
            log.debug("指标埋点失败（已忽略）：{} - {}", name, e.getMessage());  // 埋点异常不刷业务日志
        }
    }

    public void count(String name, long amount, String... tags) {
        try {
            Counter.Builder builder = Counter.builder(name);
            for (int i = 0; i + 1 < tags.length; i += 2) {
                builder.tag(tags[i], tags[i + 1]);
            }
            builder.register(registry).increment(amount);
        } catch (Exception e) {
            log.debug("指标埋点失败（已忽略）：{}", e.getMessage());
        }
    }

    /** 写盘收尾：一次 timer + 按状态（WRITTEN/MERGED/SKIPPED/ERROR）统计文件数 */
    public void finishWrite(Timer.Sample sample, boolean success, Map<String, Integer> fileStatusCounts) {
        try {
            fileStatusCounts.forEach((status, count) ->
                    count("gen.write.files", count, "status", status));  // Counter：文件状态计数
        } catch (Exception ignored) { }
        stop(sample, "gen.write", "result", success ? "success" : "fail");  // Timer：带 result tag
    }
}
```

典型埋点调用（生成主流程中）：`metrics.start()` 取计时起点，业务结束或异常时调 `finishWrite(sample, success, fileStatusCounts)` 收尾——成功/失败通过 `result` tag 区分。

## 16.4 自定义采样与环形缓冲：把累计值变成窗口差分

`http.server.requests` 的 count/totalTime 是**从启动累计**的。直接展示会让「近 30 分钟」曲线一路向上，失去窗口意义。`MonitorSampler` 用 `@Scheduled` 定时采样，把累计值做**区间差分**后写入环形缓冲（来源 `src/main/java/com/codegen/monitor/MonitorSampler.java`）：

```java
// 来源：src/main/java/com/codegen/monitor/MonitorSampler.java（节选）
@Component
public class MonitorSampler {

    private final MeterRegistry registry;
    private final MonitorStore store;
    private Map<String, double[]> prevHttpTimers = new HashMap<>();  // 上一轮快照，用于差分

    @Scheduled(fixedDelayString = "${monitor.sample.interval-ms:5000}")  // 默认 5s 一采
    public void sampleOnce() {
        try {
            store.add(collect());                  // 采一轮写缓冲
        } catch (Exception e) {
            log.warn("指标采样失败（不影响业务）：{}", e.getMessage());  // 失败只 warn，下一轮继续
        }
    }

    private HttpDelta collectHttp() {
        Map<String, double[]> current = new HashMap<>();
        for (Timer timer : registry.find(HTTP_METRIC).timers()) {
            // 以 method|uri|status 为 key，取本轮 count / 总耗时 / 最大耗时
            current.put(key, new double[]{ timer.count(), timer.totalTime(MILLIS), timer.max(MILLIS) });
        }
        HttpDelta delta = new HttpDelta();
        for (var e : current.entrySet()) {
            double[] cur = e.getValue();
            double[] prev = prevHttpTimers.get(e.getKey());
            long dc = (long) Math.max(0, cur[0] - (prev == null ? 0 : prev[0]));  // 区间差分
            delta.count += dc;                     // 本轮新增请求数
            if (status.startsWith("4")) delta.e4xx += dc;
            else if (status.startsWith("5")) delta.e5xx += dc;
        }
        prevHttpTimers = current;                  // 滚动上一轮
        return delta;
    }
}
```

环形缓冲 `MonitorStore` 用 `ArrayDeque` 实现，**满了淘汰最旧、绝不扩容**——宁可少一段历史，也不要内存随运行时长无限上涨（来源 `src/main/java/com/codegen/monitor/MonitorStore.java`）：

```java
// 来源：src/main/java/com/codegen/monitor/MonitorStore.java（节选）
@Component
public class MonitorStore {
    private final int capacity;                    // 360，来自配置
    private final ArrayDeque<MetricSnapshot> buffer;

    public MonitorStore(MonitorProperties props) {
        this.capacity = Math.max(2, props.getSample().getBufferSize());  // 360 ≈ 30 分钟 / 5s
        this.buffer = new ArrayDeque<>(this.capacity);
    }

    public synchronized void add(MetricSnapshot snapshot) {
        if (buffer.size() >= capacity) {
            buffer.pollFirst();                    // 满了淘汰最旧样本
        }
        buffer.addLast(snapshot);
    }

    // since(from) 时间升序返回窗口内样本；latest() 取最新；size()/capacity() 供概览接口
}
```

采样调度由独立配置类开启（来源 `src/main/java/com/codegen/config/MonitorConfig.java`）：

```java
// 来源：src/main/java/com/codegen/config/MonitorConfig.java
@Configuration
@EnableScheduling                                 // 平台此前无调度能力，单独放配置类不污染启动类
public class MonitorConfig {
}
```

窗口参数来自 `MonitorProperties`（来源 `src/main/java/com/codegen/config/MonitorProperties.java`）：

```java
// 来源：src/main/java/com/codegen/config/MonitorProperties.java
@Data
@Component
@ConfigurationProperties(prefix = "monitor")
public class MonitorProperties {
    private Sample sample = new Sample();
    @Data
    public static class Sample {
        private long intervalMs = 5000;           // 采样周期，决定 QPS 分母口径
        private int bufferSize = 360;             // 360 点 × 5s = 30 分钟
    }
}
```

对应 `application.yml`：

```yaml
# 来源：src/main/resources/application.yml
monitor:
  sample:
    interval-ms: ${MONITOR_SAMPLE_INTERVAL_MS:5000}
    buffer-size: ${MONITOR_SAMPLE_BUFFER_SIZE:360}
```

> ⚠️ 踩坑提示：`prevHttpTimers = current` 用**引用替换**而非 `clear()`，是因为下一轮差分必须基于本轮快照；若误用 mutable 复用，会在并发采样里算错差分。同样，JVM Gauge 的 `sumGauges` 必须遍历多个 gauge 求和——`jvm.memory.max` 在某些内存池上返回 -1（未定义），要 `v > 0` 才累加，否则把总量拉低。

## 16.5 聚合接口与权限：MonitorController 四个端点

前端不直接打 Actuator。codegen 用 `MonitorController` 把 Micrometer 原始结构收敛成页面形状，并统一加 `monitor:view` 权限（来源 `src/main/java/com/codegen/controller/MonitorController.java`）：

```java
// 来源：src/main/java/com/codegen/controller/MonitorController.java（节选）
@RestController
@RequestMapping("/monitor")
public class MonitorController {

    @Autowired MonitorStore store;
    @Autowired MonitorWindow window;

    @GetMapping("/overview")               // 实时概览：JVM / HTTP 整体
    public Result<MonitorOverviewVO> overview() { require(); /* ... */ }

    @GetMapping("/series")                 // 指标趋势序列：按 metric + minutes 取窗口点
    public Result<MonitorSeriesVO> series(@RequestParam String metric,
                                         @RequestParam Integer minutes) { require(); /* ... */ }

    @GetMapping("/http")                   // HTTP 聚合 + 慢接口排行（p95/p99/错误率）
    public Result<MonitorHttpVO> http(@RequestParam Integer minutes,
                                      @RequestParam Integer topN) { require(); /* ... */ }

    @GetMapping("/business")               // 业务指标：生成批次/成功率、流水线、文档转换
    public Result<MonitorBusinessVO> business(@RequestParam Integer minutes) { require(); /* ... */ }

    /** 权限码校验：超管直通，其余用户按角色 → 菜单 perms 判定 monitor:view */
    private void require() {
        Long userId = UserContext.getUserId();
        if (permissionService.isSuperAdmin(userId)) return;
        if (!permissionService.permissionsOf(userId).contains("monitor:view")) {
            throw new BusinessException(ResultCode.FORBIDDEN);
        }
    }
}
```

四个接口分别支撑：仪表盘实时概览、任意指标的趋势曲线、慢接口与错误率排行、业务域（代码生成 / 流水线 / 文档转换）的成功率与耗时。关键设计是**暴露给前端的永远是聚合后的视图**，原始指标树和 Actuator 端点都不直接对外开放，配合 16.2 的端口收窄，安全面最小。

测试侧用 standalone MockMvc 验证了权限与参数钳制（来源 `src/test/java/com/codegen/controller/MonitorControllerTest.java`）：非法 `metric` → 400、缺 `monitor:view` → 403、`minutes` 越界被钳到 30。

## 16.6 Prometheus + Grafana 接入思路（通用示例）

当平台需要跨实例聚合、长期留存、告警，再上 Prometheus。引入 `micrometer-registry-prometheus` 后，Actuator 会出现 `/actuator/prometheus` 端点吐出文本格式指标，被 `prometheus.yml` 的 `scrape_configs` 抓取（**通用示例**）：

```yaml
# 此为通用示例：暴露 prometheus 端点
management:
  endpoints:
    web:
      exposure:
        include: health,info,metrics,prometheus
  metrics:
    tags:
      application: ${spring.application.name}
```

Grafana 侧导入 JVM / HTTP 模板 Dashboard，用 `application` 标签区分多实例。codegen 的 `MonitorController` 方案与 Prometheus **不冲突**——进程内缓冲解决「单实例即时面板」，Prometheus 解决「跨实例留存告警」，二者可并存。

## 本章小结

本章以 codegen-server 的真实 `monitor` 包为标杆，展示了**不引入全套监控栈也能做有效平台级可观测性**的完整范式：Actuator 收窄暴露面（`health/info/metrics` + `show-details=never`）守住安全底线；Micrometer 的 Timer/Gauge/Counter 在业务里轻量埋点并全程 try/catch 隔离；`MonitorSampler` 把累计指标做区间差分，`MonitorStore` 用 360 点环形缓冲（≈30 分钟）零外部依赖地保留窗口；`MonitorController` 四个接口收敛视图并加 `monitor:view` 权限。这是对「单体连库即跑」场景克制而有效的工程范本。

## ⚠️ 本章核心踩坑

1. **累计值不能直接当窗口展示**：HTTP/JVM 指标从启动累计，必须做差分，否则曲线一路向上、聚合失真。
2. **直方图开关的 YAML 写法**：`"[http.server.requests]"` 必须带引号方括号，否则 p95/p99 恒为 0（codegen 因此写了 `HistogramConfigProbeTest` 专门验证）。
3. **暴露面宁窄勿宽**：`env/heapdump/threaddump` 一旦暴露即等同泄露口令与内存；`health.show-details` 生产必设 `never`。
4. **埋点必须隔离**：指标异常绝不允许拖垮业务主流程——所有 `registry.*` 调用都要 catch 住只打 debug。
