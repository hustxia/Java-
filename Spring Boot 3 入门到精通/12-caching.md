# 第 12 章 Spring Cache 抽象与缓存落地

## 本章目标

读完本章你将能够：

- 理解 Spring Cache 抽象层的设计思想，以及 `@Cacheable` / `@CachePut` / `@CacheEvict` 三件套的用法与差异。
- 在 Caffeine（本地）与 Redis（分布式）两种 `CacheManager` 之间做出选型，并写出对应的自动配置。
- 把 codegen-server 的 monitor 内存环形缓冲当作「应用内缓存」的活教材，理解进程内缓冲也是一种缓存。
- 针对「代码生成」这种读多写少、可容忍短暂不一致的场景，设计合理的缓存策略。

---

## 12.1 什么是 Spring Cache 抽象

Spring 从 3.1 起提供了一套**缓存抽象（Cache Abstraction）**。注意它只是抽象——Spring 自己不存数据，而是定义了一套统一的注解和接口（`Cache` / `CacheManager`），把「怎么存、存在哪」交由具体实现（Caffeine、Redis、Ehcache、ConcurrentMap…）去完成。

这带来两个好处：

1. **业务无侵入**：加缓存只是加一个注解，不用在业务代码里手写 `if (cache.get(k) != null) ... else { compute; cache.put(k, v); }`。
2. **实现可替换**：开发用 `ConcurrentMapCache`，上线切 `RedisCacheManager`，业务代码一行不用改。

启用缓存只需在配置类上标注 `@EnableCaching`：

```java
@Configuration
@EnableCaching
public class CacheConfig {
}
```

⚠️ **踩坑提示**：`@EnableCaching` 是缓存生效的前提。如果注解加了却没生效，十有八九是忘了开这个开关，或者配置类没被 Spring 扫描到（包路径不对）。另外，缓存注解基于 AOP 代理，**同类内部方法互相调用（self-invocation）不会触发缓存**——`@Cacheable` 方法被同一个类里的另一个方法直接调用时，注解等于没写。

---

## 12.2 三个核心注解

### 12.2.1 @Cacheable：查缓存，没有就执行并回填

```java
@Cacheable(cacheNames = "user", key = "#id", unless = "#result == null")
public UserDO getUserById(Long id) {
    return userMapper.selectById(id);   // 第一次查库，之后命中缓存直接返回
}
```

- `cacheNames`：缓存分组名。
- `key`：SpEL 表达式，决定缓存键。`#id` 表示取方法入参 `id`。
- `unless`：满足条件则不缓存（这里结果 null 不缓存，避免缓存穿透）。

### 12.2.2 @CachePut：一定执行方法，并把返回值写入缓存

```java
@CachePut(cacheNames = "user", key = "#user.id")
public UserDO updateUser(UserDO user) {
    userMapper.updateById(user);
    return user;                         // 返回值写入缓存，保证缓存与库一致
}
```

`@CachePut` 与 `@Cacheable` 的关键区别：**它每次都会执行方法体**（用于「写」场景），然后把结果塞进缓存。`@Cacheable` 命中时则不执行方法体。

### 12.2.3 @CacheEvict：删除缓存

```java
@CacheEvict(cacheNames = "user", key = "#id")
public void deleteUser(Long id) {
    userMapper.deleteById(id);
}
```

`allEntries = true` 可一次性清空整个 `cacheNames`（如「全量刷新字典缓存」）；`beforeInvocation = true` 可让删除发生在方法执行前（方法可能抛异常时仍清缓存）。

---

## 12.3 CacheManager 选型：Caffeine 本地 vs Redis 分布式

### 12.3.1 Caffeine（进程内）

Caffeine 是 Guava Cache 的现代继任者，性能极高，基于「Window TinyLfu」淘汰算法。适合**单机、数据量不大、可容忍重启丢失**的场景。

```java
@Configuration
@EnableCaching
public class CacheConfig {

    @Bean
    public CacheManager cacheManager() {
        CaffeineCacheManager manager = new CaffeineCacheManager();
        manager.setCaffeine(Caffeine.newBuilder()
                .expireAfterWrite(Duration.ofMinutes(10))   // 写后 10 分钟过期
                .maximumSize(10_000));                      // 最多 1 万条，超出按 LRU 淘汰
        return manager;
    }
}
```

（`**此为通用示例**`，codegen-server 未使用 Spring Cache）

### 12.3.2 Redis（分布式）

多实例部署时，本地缓存各自为政会导致「数据不一致」——A 实例更新了，B 实例还是旧值。Redis 作为集中式缓存可解决：

```java
@Bean
public CacheManager cacheManager(RedisConnectionFactory factory) {
    RedisCacheConfiguration cfg = RedisCacheConfiguration.defaultCacheConfig()
            .entryTtl(Duration.ofMinutes(10))             // 统一过期时间
            .serializeKeysWith(RedisSerializationContext
                    .SerializationPair.fromSerializer(new StringRedisSerializer()))
            .serializeValuesWith(RedisSerializationContext
                    .SerializationPair.fromSerializer(new GenericJackson2JsonRedisSerializer()));
    return RedisCacheManager.builder(factory).cacheDefaults(cfg).build();
}
```

（`**此为通用示例**`，codegen-server 未使用 Spring Cache）

**选型口诀**：单实例 + 读多写少 + 能容忍重启丢 → Caffeine；多实例 + 需要共享 + 不能容忍丢 → Redis。二者也可组合：本地 Caffeine 做一级（挡绝大部分读），Redis 做二级（跨实例一致），但两级缓存会带来「一致性更复杂」的代价，中小项目慎用。

---

## 12.4 进程内缓冲也是缓存：从 monitor 环形缓冲说起

codegen-server 没有显式使用 `@Cacheable`，但它有一个绝佳的「应用内缓存」范例——**monitor 包的内存环形缓冲**。

`MonitorStore` 用 `ArrayDeque` 实现了一个固定容量的环形缓冲，存最近 N 个 `MetricSnapshot`（指标快照）：

```java
@Component
public class MonitorStore {

    private final int capacity;
    private final ArrayDeque<MetricSnapshot> buffer;
    private final AtomicLong lastSampleAt = new AtomicLong(0);

    public MonitorStore(MonitorProperties props) {
        this.capacity = Math.max(2, props.getSample().getBufferSize());  // 默认 360
        this.buffer = new ArrayDeque<>(this.capacity);
    }

    public synchronized void add(MetricSnapshot snapshot) {
        if (buffer.size() >= capacity) {
            buffer.pollFirst();          // 满了淘汰最旧样本，不扩容
        }
        buffer.addLast(snapshot);
        lastSampleAt.set(snapshot.timestamp());
    }

    public synchronized MetricSnapshot latest() {
        return buffer.peekLast();        // O(1) 取最新
    }
}
```

（`MonitorStore.java` 第 17–39 行）

它和 Spring Cache 在本质上是同一类东西：**用一块内存空间暂存「算起来贵、但允许略旧」的数据，加速读取**。区别只在于：

- Spring Cache 是「键 → 值」的通用映射，有 TTL、有淘汰策略、有统一抽象；
- MonitorStore 是「时间序列」专用结构，按时间窗口滚动，满了丢最旧——这叫**环形缓冲（ring buffer）**，是最古老也最高效的缓存形态之一。

配置上，缓冲大小与采样周期来自 `MonitorProperties` + `application.yml`：

```yaml
monitor:
  sample:
    interval-ms: ${MONITOR_SAMPLE_INTERVAL_MS:5000}    # 5 秒一采
    buffer-size: ${MONITOR_SAMPLE_BUFFER_SIZE:360}      # 360 点 = 30 分钟
```

（`application.yml` 第 81–84 行，注释：采样窗口 5s×360=30 分钟，仅进程内，重启归零，多实例不共享）

> 这个「仅进程内、重启归零、多实例不共享」的注释，恰恰说明了**本地内存缓存的边界**：它快，但脆弱、不共享。换到需要跨实例一致或持久化的场景，就得上 Redis。

⚠️ **踩坑提示**：MonitorStore 的 `add/latest/since` 全部 `synchronized`，因为**写发生在调度线程、读来自 HTTP 线程**（`MonitorSampler` 的定时任务写，`/actuator/metrics` 或监控接口读）。不加同步会出现 `ArrayDeque` 并发修改导致的数据错乱甚至 `ConcurrentModificationException`。多线程读写共享缓冲时，要么用锁，要么用 `ConcurrentLinkedDeque` 等并发容器，要么像这里明确「单写多读 + synchronized」。

---

## 12.5 在代码生成场景如何落地缓存

代码生成这类平台，「读多写少、可容忍短暂不一致」的特征非常明显，很适合加缓存。举几个落地点（**以下为通用示例**，演示思路，非 codegen-server 现有代码）：

1. **代码模板 / 字典缓存**：表元数据、字段类型映射、数据库方言等几乎不变的数据，用 `@Cacheable` 缓存，TTL 设 10~30 分钟足够。
2. **生成结果预览缓存**：同一张表、同一份配置重复点「预览」时，命中缓存直接返回上次产物，省去重复渲染。
3. **用户/角色信息**：第 11 章提到 `AuthContextFilter` 每次请求都查库加载权限。可以把「用户 → 角色/数据权限范围」缓存 5 分钟，既减轻数据库压力，又比「写进 token」更灵活（改权限不必等 token 过期）。

但要注意缓存与「正确性」的边界：

- 生成产物是**用户实时诉求**，不该被长 TTL 缓存误导——缓存的应是「模板/元数据」而非「本次生成结果」。
- 涉及「写后立刻读一致性」的路径（如刚保存的表结构马上用于生成），要么用 `@CacheEvict` 写后清缓存，要么干脆不缓存。

---

## 本章小结

- Spring Cache 是「抽象 + 可插拔实现」的设计，启用靠 `@EnableCaching`，业务加缓存只靠注解。
- `@Cacheable` 命中则不执行方法；`@CachePut` 每次执行并把结果写回；`@CacheEvict` 删除缓存。三者配合覆盖「读/写/删」全生命周期。
- 本地用 Caffeine（快、单实例、重启丢），分布式用 Redis（共享、一致、需序列化）。选型看「是否多实例 + 能否容忍重启丢」。
- codegen-server 的 `MonitorStore` 环形缓冲是「进程内缓存」的生动范例：用固定内存滚动保存时间序列，满了丢最旧、不扩容，且必须处理跨线程读写同步。
- 在代码生成场景落地缓存，优先缓存「模板/元数据/字典」等读多写少的数据，避免缓存「本次实时生成结果」；写后一致性用 `@CacheEvict` 兜底。
