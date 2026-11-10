---
book: true
volume: 3
chapter: 16
order: 3-16
title: 缓存三大问题与热 Key
sources:
  - 17-常见Bug与解决方案/05-Redis与缓存坑.md
  - 06-缓存/缓存穿透击穿雪崩.md
  - 06-缓存/Redis集群与高可用.md
status: review
words: 4969   # 汉字计数，由脚本实测
---


# 第十六章　缓存三大问题与热 Key

> 卷三 · 数据落地

**本章要回答**：为什么加了 32 个 Redis 节点，还是有一个 key 把 CPU 打满？

**本章你能带走**
- 穿透/击穿/雪崩三者的准确区别（多数人说不清）
- 一个真相：**热 key 是 cluster 的盲区，加节点救不了**
- 一条红线：`KEYS *`、`FLUSHALL`、大 key `DEL` 都是线上事故

**难度构成**：本章主线【必读】；含【进阶】深挖 1 处；章末「延伸」小节放支线深挖与知识库指针。
---

## 16.1　现场：32 个节点，一个 key 打满 CPU

促销预热时，所有请求打同一个商品：`item:hot:1001`。

Redis Cluster 32 个节点，其中**一个节点 CPU 100%**，其余 31 个几乎空闲。这个节点的所有读写全部超时，于是所有依赖它的接口一起超时。

运维的第一反应是"加节点"——但集群已经是 32 个了。

问题在于：**Redis Cluster 按 key 的 CRC16 取模分 16384 个 slot，同一个 key 永远落在同一个 slot、同一个节点上。** 加再多节点，`item:hot:1001` 还是在那一个节点上。

> **热 key 的问题不是"集群容量不够"，是"单个 key 的吞吐有物理上限"。**
> 一个 Redis 单节点大约能扛 8–10 万 QPS（简单命令），超过就是单点瓶颈，和集群规模无关。

**当时怎么误判的**：第一反应是"集群容量不够，加节点"——运维已经把 Redis Cluster 从更少扩到 32 个，加完还是那一个节点 CPU 100%，纯属白加；又怀疑"是不是某个节点硬件 / 配置不均，成了拖后腿的慢节点"，查其余 31 个节点的 CPU 几乎全空，没有普遍瓶颈。两条都排除后，才有人去算 CRC16 分 slot 的规则：同一个 key 永远落同一个 slot、同一个节点，加再多节点也救不了单 key 的吞吐上限。这一下把方向从"扩容"扭回"单 key 拆分 / 本地缓存"，后面的热 key 解法才对路。

## 16.2　穿通雪：三个概念，别混着说

| 问题 | 现象 | 根因 | 关键词 |
|---|---|---|---|
| **穿透** | 大量请求查**不存在**的数据 | 缓存和 DB 都没有，每次都打到 DB | 数据不存在 |
| **击穿** | 某个**热点 key 突然失效** | 一万个请求同时重建同一个 key | 单个 key 过期 |
| **雪崩** | **大量 key 同时失效** 或 Redis 整体不可用 | TTL 设成同一个值 / 宕机 | 面 |

一句话区分：**穿透是"查不存在的"，击穿是"一个热的没了"，雪崩是"一片同时没了"。**

### 【必读】穿透：空值缓存 + 布隆过滤器

```java
// ✅ 空值也缓存，短 TTL
User u = userMapper.selectById(id);
if (u == null) {
    redis.setex("user:" + id, 60, "NULL");    // 30~60 秒，别太长
    return null;
}
```

```java
// ✅ 布隆过滤器：先挡一层
if (!bloomFilter.mightContain(id)) {
    return null;              // 一定不存在，直接返回
}
```

布隆过滤器的两个特性必须知道：

- **只会误判"存在"，不会误判"不存在"** → 所以它能挡住不存在的请求，不会误杀真实数据
- **不支持删除** → 数据删了，布隆里还在，会短时间放行。要删除就得用 counting bloom 或定期重建

另一个坑：布隆过滤器**必须预热**。服务启动时没加载数据就上线，等于没开。

### 【必读】击穿：互斥重建 或 逻辑过期

```java
// ✅ 方案一：互斥锁重建（只有一个线程回源）
String val = redis.get(key);
if (val == null) {
    if (redis.set(lockKey, "1", "NX", "EX", 10)) {   // SET NX EX 10：原子加锁带过期（SETNX 无此签名）
        try {
            val = loadFromDb();
            redis.setex(key, ttl, val);
        } finally {
            redis.delete(lockKey);
        }
    } else {
        Thread.sleep(50);                          // 没抢到，等一会儿重试
        return get(key);
    }
}
```

```java
// ✅ 方案二：逻辑过期（不删 key，后台异步刷新）
class CacheVal {
    Object data;
    long expireAt;        // 逻辑过期时间
}
// 读到逻辑过期 → 返回旧值 + 异步刷新，用户永远不等
```

两种方案的取舍很明确：

| 方案 | 一致性 | 用户等待 | 复杂度 |
|---|---|---|---|
| 互斥重建 | 强（一定拿到新值） | **要等重建完成**（可能几百 ms） | 中 |
| 逻辑过期 | 弱（短时间返回旧值） | **零等待** | 中 |

热点商品详情页选逻辑过期，库存/价格这类选互斥重建。

### 【必读】雪崩：TTL 加抖动 + 高可用

```java
// ✅ 基础 TTL + 随机抖动，消除"同时过期"
long ttl = 3600 + ThreadLocalRandom.current().nextLong(600);   // 3600~4200 秒
```

这是最便宜、最有效的一招——**一行代码消灭"同时失效"**。

Redis 整体不可用的雪崩，靠三件事：

1. **高可用**：哨兵 / Cluster，主从自动切换
2. **多级缓存**：本地缓存（Caffeine）挡一层，Redis 挂了还有本地
3. **熔断降级**：Redis 超时直接返回兜底值，不要死等

### 【必读】穿透、击穿、雪崩的判据表

16.2 那张表给的是定义，排障时要的是**判据**——看到监控上一条曲线，第一分钟就能把它归到三类中哪一类。三者的根因都落在"回源 QPS 突增"，但突增的形状完全不同：

| 判据 | 穿透 | 击穿 | 雪崩 |
|---|---|---|---|
| 查的数据存不存在 | **不存在**（缓存和 DB 都没有） | 存在，只是缓存那一刻没了 | 存在，但一大批 key 同时没了 |
| 受影响的 key 数量 | 大量**不同的**非法 key | **恰好 1 个**热 key | 成片 / 全实例 |
| DB QPS 曲线 | 随攻击流量平稳抬高 | 单 key 过期瞬间一根尖针 | 批量过期时台阶式跃升 |
| 缓存命中率 | 掉，且 `keyspace_misses` 全是新 key | 短暂掉，随即恢复 | 大面积掉 |
| 第一分钟敲什么 | `SLOWLOG GET` + 入参分布，看是不是随机 ID | `TTL hotkey` + `OBJECT FREQ hotkey` | `INFO stats` 看 `expired_keys` 突增、`evicted_keys` |
| 最便宜的一招 | 空值缓存 + 布隆 | 互斥重建 / 逻辑过期 | TTL 抖动 |

取证顺序建议固定下来，别一上来就抓线程 dump（第 7 章"锁→事务→线程→差值"的思路在缓存同样适用）：

```bash
# ① 先看命中率与过期曲线，区分"面"还是"点"
redis-cli INFO stats | grep -E 'keyspace_hits|keyspace_misses|expired_keys|evicted_keys'
# ② 看慢命令，确认是不是 KEYS / 大集合把主线程堵了
redis-cli SLOWLOG GET 10
# ③ 看单 key 热度（需 maxmemory-policy 为 *-lfu，见本节末尾）
redis-cli OBJECT FREQ item:hot:1001
# ④ 看客户端都在等谁
redis-cli CLIENT LIST | head -20
```

> 反常识点：多数人以为"命中率掉"就等于雪崩，实际穿透和击穿也会让命中率掉，三者区别在"掉完之后能不能自己回来"。**击穿的针尖在重建完成后立刻恢复，穿透不挡就一直低，雪崩要等一批 key 全部重建完；看恢复速度比看掉多少更有判据价值。**
### 【必读】布隆过滤器误判率：m、n、k 的算式

16.2 说布隆"只会误判存在"，但没说误判率怎么定。它完全由三个量决定：

```
n = 预计装入的元素个数
m = 位数组长度（bit）
k = 哈希函数个数
p = 误判率（false positive）

m = - n · ln p / (ln 2)²        k = (m / n) · ln 2
p = ( 1 - e^(-k·n/m) ) ^ k
```

代一组具体数字：`n = 1,000,000`（100 万商品 ID）、目标 `p = 0.01`（1%）。

```
m = -1e6 × ln(0.01) / (0.6931)²
  = 1e6 × 4.6052 / 0.4805 ≈ 9,585,058 bit ≈ 1.14 MB
k = (9.585e6 / 1e6) × 0.6931 ≈ 6.64 → 取 7

反代验证：p = (1 - e^(-7×1e6/9.585e6))^7
            = (1 - e^(-0.730))^7 = 0.518^7 ≈ 0.0100
```

**业务含义：100 万 ID、1% 误判，只要 1.14 MB 内存和 7 次哈希，就换来了"不存在"的请求 99% 被挡在 DB 之前。** 若把 `p` 压到 0.001，`m` 约 1.71 MB（1.5 倍内存换 10 倍精度），`k` 约 10——注意 `k` 变大意味着每次查询的 CPU 也涨，**误判率不是越低越好，要连哈希次数一起算**。

RedisBloom 把这些计算封装了，可以直接核对：

```bash
# 需在自己的版本上验证 BF.* 是否内置；独立模块时代要先装 RedisBloom
redis-cli BF.RESERVE product:bf 0.01 1000000
redis-cli BF.ADD product:bf 1001
redis-cli BF.EXISTS product:bf 99999        # 0 = 一定不存在
redis-cli BF.INFO product:bf                 # 看 Capacity / 实际占用
```

用 Python 复算同一组数字，复制就能证伪"1.14MB"：

```python
import math
n, p = 1_000_000, 0.01
m = -n * math.log(p) / (math.log(2) ** 2)
k = (m / n) * math.log(2)
p_real = (1 - math.exp(-k * n / m)) ** k
print(f"m={m/8/1024/1024:.2f}MB  k={k:.2f}  p={p_real:.4f}")
# m=1.14MB  k=6.64  p=0.0100
```

两个坑配着公式记：一是**漏灌比误判严重**——真实 ID 没灌进过滤器会被判"一定不存在"，直接误杀真实请求，所以上线必须先全量预热；二是**元素超容量后误判率飙升**，`BF.INFO` 容量使用率超过 80% 就该规划重建（用"新 key + 双读灰度 + 切换"，别原地清空）。标准布隆不支持删除，根因是多个元素共享 bit 位，清零会误杀别人；要删就换布谷鸟过滤器或定期重建。
### 【必读】互斥重建与逻辑过期：两段代码对照

16.2 给了两个方案的伪代码，这里补上能直接抄的写法，顺带修掉一个流传很广的假 API。

**先纠一个错**：16.2 击穿代码里的 `setnx(lockKey, "1", 10)` 看着合理，其实**标准 Redis 没有这个签名**——`SETNX key value` 只有两个参数，不带过期；想要"不存在才写 + 自动过期"得用 `SET key value NX EX ttl`。混写的结果要么锁永不过期（持锁者崩了别人永远等），要么 TTL 根本没设上。这一点在 16.6 的锁坑里还会再出现。

```java
// ❌ 伪 API：SETNX 没有第三个参数；value 用固定 "1"、finally 直接 DEL
if (redis.setnx(lockKey, "1", 10)) {
    try { val = loadFromDb(); redis.setex(key, ttl, val); }
    finally { redis.delete(lockKey); }     // 可能删掉别人刚拿到的锁
}

// ✅ 互斥重建：原子加锁 + 唯一 token + double-check + Lua 比对释放
private static final String UNLOCK_LUA =
    "if redis.call('get', KEYS[1]) == ARGV[1] then "
    + "return redis.call('del', KEYS[1]) else return 0 end";

public Product queryWithMutex(long id) {
    String key = "product:" + id;
    Product v = getFromCache(key);
    if (v != null) return v;

    String lockKey = "lock:product:" + id;
    String token = UUID.randomUUID().toString();
    Boolean ok = redisTemplate.opsForValue()
            .setIfAbsent(lockKey, token, Duration.ofSeconds(3));   // SET NX EX 3
    if (Boolean.TRUE.equals(ok)) {
        try {
            Product again = getFromCache(key);          // double-check：别人可能已重建
            if (again != null) return again;
            Product p = productMapper.selectById(id);   // 全局只有一个线程回源
            setToCache(key, p, jitterTtl());
            return p;
        } finally {
            redisTemplate.execute(new DefaultRedisScript<>(UNLOCK_LUA, Long.class),
                    List.of(lockKey), token);            // 只删自己的锁
        }
    }
    for (int i = 0; i < 3; i++) {                       // 等待者只重读缓存，不查库
        sleepQuietly(50);
        Product p = getFromCache(key);
        if (p != null) return p;
    }
    return fallbackOf(id);                              // 有限次 + 兜底，绝不无限自旋
}
```

```java
// ✅ 逻辑过期：Redis 不设 TTL，value 自带 expireAt，返回旧值 + 异步刷新
record ExpiringValue<T>(T data, long expireAtMillis) {}

public Product queryLogicalExpire(long id) {
    ExpiringValue<Product> v = getExpiring(key(id));
    if (v == null) return loadWithMutex(key(id), id);      // 冷启动仍需一次互斥
    if (System.currentTimeMillis() < v.expireAtMillis()) {
        return v.data();                                     // 未过期，直接返回
    }
    refreshExecutor.submit(() -> {                           // 过期：先返回旧值
        String lock = "lock:refresh:" + key(id);
        if (Boolean.TRUE.equals(redisTemplate.opsForValue()
                .setIfAbsent(lock, "1", Duration.ofSeconds(30)))) {
            try {
                Product fresh = productMapper.selectById(id);
                setExpiring(key(id), new ExpiringValue<>(fresh,
                        System.currentTimeMillis() + 1800_000));
            } finally { redisTemplate.delete(lock); }
        }
    });
    return v.data();                                         // 用户零等待
}
```

两处细节比代码本身值钱：**等待者醒来必须读缓存，不能查库**（持锁者很可能已把值写回去；醒来还查库，锁就白加了）；**锁 TTL 按 DB 查询 P99 的 2~3 倍定**，不是拍 30 秒，太短会并发重建，太长则持锁者崩溃后其他人干等。

| 维度 | 互斥重建 | 逻辑过期 |
|---|---|---|
| 一致性 | 强（一定拿到新值） | 弱（返回短时旧值） |
| 用户等待 | 要等重建（几百 ms） | 零等待 |
| 实现要点 | token + Lua + double-check + 限次 | `expireAt` 字段 + 异步线程池 + 刷新去重 |
| 风险 | 锁等待堆积 | 刷新失败 → 长期旧值；物理不过期 → 内存膨胀 |
| 适用 | 库存、价格 | 商品详情、榜单 |

**④ TTL 抖动的随机区间算法**（顺带把 16.2 雪崩那行补全）：`ttl = base + U(0, jitter)`，`U` 取均匀分布，`jitter` 取 `base` 的 10%~20%。它消除"同时过期"的原理不是"让每个 key 不一样"，而是**把 M 个 key 的过期时刻摊到宽度 jitter 的窗口**：均匀假设下同一秒过期数 ≈ `M / jitter`。取 `base=1800s, jitter=300s, M=10万`，则 `≈ 333 个/秒`；若全写成固定 1800s，就是 `10万/秒` 的瞬时回源，差 300 倍（第 15 章 TTL 算式用的是同一套推导）。**空值缓存的 TTL 也要抖动**，否则一批非法 ID 的空值会约好一起过期，制造一次穿透尖针。

## 16.3　热 key：三个解法，按成本排

### 【必读】① 本地缓存（最有效）

```java
// Caffeine：热点数据放进程内，直接绕开 Redis
Cache<Long, Item> local = Caffeine.newBuilder()
        .maximumSize(10_000)
        .expireAfterWrite(Duration.ofSeconds(3))     // 短 TTL 保证一致性
        .build();
```

一个 8 核机器能扛几十万 QPS 的本地读。**热点 key 的流量被拦在进程内，Redis 完全不受影响。**

代价是**一致性变弱**：本地缓存 3 秒过期，意味着最坏 3 秒不一致。对商品详情、配置、字典这类数据完全够用；对库存、价格不行。

### 【必读】② key 拆分（读扩散）

把一个热 key 拆成 N 份，请求随机打散：

```java
// 写：写 N 份
for (int i = 0; i < 10; i++) redis.set("item:1001:" + i, val);

// 读：随机选一份
int idx = ThreadLocalRandom.current().nextInt(10);
String val = redis.get("item:1001:" + idx);
```

代价：写放大 10 倍、数据有短暂不一致（写 N 份不是原子的）、删除要删 N 个。**只适合"读极多、写极少"的场景**（如秒杀商品快照）。

### 【必读】③ 读写分离（治标）

从节点分担读流量。但注意：**主从复制是异步的，热 key 的写入峰值会打满主节点**，读写分离只解决读。

### 【进阶】热 key 探测：三种手段的代价

16.1 说"加节点救不了热 key"，前提是**先知道哪个 key 热**。三种手段的代价差了一个数量级，别一上来就开 `MONITOR`。

**① `redis-cli --hotkeys`（最省，但有前提）**

```bash
# 必须先把淘汰策略切到 LFU，否则拿不到热度数据
redis-cli CONFIG SET maxmemory-policy allkeys-lfu
redis-cli --hotkeys
redis-cli OBJECT FREQ item:hot:1001     # 单点确认，返回 0~255 的对数频率
```

它靠 LFU 计数器采样统计，**不阻塞主线程**，但要满足两个前提：策略是 `*-lfu`（默认 `noeviction` 或 `*-lru` 时拿不到），且实例开了 `maxmemory`。**这意味着为了探测去改生产淘汰策略本身就有风险**——切到 `allkeys-lfu` 后内存打满会开始淘汰，得先确认容量余量。

**② `MONITOR`（能看全，但可能自己制造故障）**

```bash
redis-cli MONITOR | head -100000
```

`MONITOR` 会把**每一条命令**复制一份写进客户端输出缓冲区。按 16.1 那个节点 8 万 QPS 算，一条简单命令文本约 60 字节，就是 `8万 × 60B ≈ 4.8 MB/s` 的额外输出；更糟的是它同步推送，消费稍慢就顶到 `client-output-buffer-limit`，Redis 主动断开监控连接还算好的，极端情况下缓冲区膨胀拖慢主线程。**线上开 MONITOR 等于给已经 CPU 100% 的节点再加一份日志负载**——这正是 16.5 把它列进红线、却又让人忍不住去开的原因。真要用，限定几百条、低峰、单节点。

**③ 客户端埋点（最可控，推荐做成长效机制）**

在缓存访问层按 key 计数，本地聚合后上报，把统计压力留在应用侧：

```java
// LongAdder 按 key 分桶，每 10 秒上报一次 TopN，避免每次访问都发指标
private final ConcurrentHashMap<String, LongAdder> counter = new ConcurrentHashMap<>();

public <T> T get(String key, Class<T> type) {
    counter.computeIfAbsent(key, k -> new LongAdder()).increment();
    return redisTemplate.opsForValue().get(key);   // 序列化按项目封装
}
// 定时任务：取 TopN 上报，超过 1w QPS 告警（性能篇的经验阈值）
```

代价是**只能看到自己这个应用**，多应用共用一个 Redis 时要把各实例 TopN 汇总；好处是零 Redis 侵入、能带业务维度（哪个接口、哪个用户段打热了 key），还能顺手统计本地缓存命中。

| 手段 | 是否侵入 Redis | 覆盖多应用 | 主要代价 | 适用 |
|---|---|---|---|---|
| `--hotkeys` / `OBJECT FREQ` | 中（要改淘汰策略） | 全实例 | 需 LFU + maxmemory | 临时巡检 |
| `MONITOR` | **高**（同步复制每条命令） | 全实例 | 输出缓冲区膨胀，可能压垮节点 | 低峰、短时、单节点 |
| 客户端埋点 | 零 | 单应用，需汇总 | 要写聚合与上报代码 | **长效机制，推荐** |

> 反常识点：多数人以为"用 Redis 自带命令查热 key 最准也最安全"，实际 `--hotkeys` 要先改淘汰策略、`MONITOR` 会放大故障；**最安全的探测恰恰不在 Redis 里，而在你自己的客户端。**

## 16.4　大 key：比热 key 更常见的杀手

判定标准（经验值）：

| 类型 | 大 key 阈值 |
|---|---|
| String | > 10 KB（有人说几百 KB，但 10KB 的 key 几万个就是几百 MB） |
| Hash / List / Set / ZSet | 元素数 > 5000，或总大小 > 1 MB |

大 key 的三个危害：

1. **网络阻塞**：一次 `GET` 拉 1MB，千兆网卡跑满
2. **删除阻塞**：`DEL` 大 key 是**同步**操作，删一个百万元素的 Hash 会卡住 Redis 几百毫秒
3. **集群倾斜**：一个大 key 可以把一个节点的内存打满

```bash
# 定位
redis-cli --bigkeys                    # 采样扫描，找最大的 key
redis-cli MEMORY USAGE key_name        # 精确看单个 key 大小

# 删除（必须用 UNLINK，异步释放）
redis-cli UNLINK big_key
```

`UNLINK` 把"释放内存"这一步放到后台线程，主线程只做"从字典里摘掉"，不会阻塞。**线上删大 key 只能用 `UNLINK`，用 `DEL` 就是一次事故。**

### 【必读】大 key 的渐进式删除与拆分

16.4 给了 `UNLINK`，这里补两件它没说的事：**UNLINK 之后内存不会立刻降**，以及**老版本 / 集合类大 key 怎么拆**。

```bash
# ✅ 4.0+：异步释放，主线程只从字典摘掉 key
redis-cli UNLINK big_hash_key
# 确认后台真的在回收，别把"内存没降"当成 UNLINK 失效
redis-cli INFO stats | grep lazyfreed_objects

# ✅ 让过期 / 淘汰 / DEL 也走异步释放
redis-cli CONFIG SET lazyfree-lazy-expire yes
redis-cli CONFIG SET lazyfree-lazy-eviction yes
# 各 lazyfree 开关的默认值需在自己的版本上验证

# ✅ 无 UNLINK 的老版本：HSCAN 分批 HDEL，每次只删 500 个 field
redis-cli HSCAN big_hash_key 0 COUNT 500
# 循环取 field 后逐批 HDEL，最后再 DEL 空壳
```

`UNLINK` 把释放交给后台线程（`lazyfree`），所以对**百万元素的 Hash**，`DEL` 是主线程同步 `O(N)` 释放、卡几百毫秒，`UNLINK` 是主线程 `O(1)` 摘 key、后台慢慢还内存。**`UNLINK` 后 `used_memory` 不立刻下降是正常的**，看 `lazyfreed_objects` 增长即可——16.4 那句"必须用 UNLINK"没错，但别拿"内存马上下了"当验收标准。

拆分比删除更根本。**大 Hash 按业务键分桶**：`user:profile:{id}` 装不下，就按 `id % 64` 拆成 64 个小 Hash；**大 List/ZSet 按时间分片**：`feed:global` 按月拆成 `feed:2026-11`。拆完单 key 元素数落到 5000 以内，`HGETALL` / `ZRANGE 0 -1` 这类 O(N) 命令自然不再堵主线程。写侧加一道阈值告警（value > 10KB 或集合 > 5000 元素直接拒绝），比事后 `--bigkeys` 巡检便宜得多。

一条取证顺序，照着敲就能判断"卡顿是不是大 key 释放造成的"：

```bash
redis-cli SLOWLOG GET 10                          # DEL / HGETALL 是否上榜（单位微秒）
redis-cli --bigkeys                               # 采样找各类型最大 key，SCAN 安全
redis-cli MEMORY USAGE big_hash_key SAMPLES 0     # 精确看字节数
redis-cli INFO memory | grep mem_fragmentation_ratio
```

`mem_fragmentation_ratio > 1.5` 才值得处理，`> 2` 考虑 `activedefrag yes` 或低峰滚动重启；`< 1` 说明部分内存被换出到 swap，是更严重的信号，别当成"内存省了"。**版本区间**：`UNLINK` / `lazyfree` 自 Redis 4.0 起，`--memkeys`、字段级 TTL（`HEXPIRE`）是 7.4+，`CLUSTER SLOT-STATS` 是 8.4+；具体命令是否可用，在自己的实例上用 `COMMAND INFO UNLINK` 核一下再写进运维脚本。

## 16.5　线上禁用命令

这几条不是"优化建议"，是红线：

| 命令 | 危害 | 替代 |
|---|---|---|
| `KEYS *` | 遍历全部 key，**阻塞主线程**，百万 key 卡几秒 | `SCAN` 渐进遍历 |
| `FLUSHALL` / `FLUSHDB` | 清库，不可逆 | 无（禁用） |
| `HGETALL` 大 hash | 一次拉几百 MB | `HSCAN` 分批 |
| `DEL` 大 key | 同步释放，阻塞 | `UNLINK` |
| `SMEMBERS` 大 set | 同上 | `SSCAN` |
| `MONITOR` | 生产开它等于给 Redis 加了个同步日志 | 用 slowlog |

配置层面也加一道保险：

```ini
rename-command KEYS ""
rename-command FLUSHALL ""
rename-command FLUSHDB ""
```

## 16.6　Redisson 分布式锁的三个坑

缓存章节里带一句锁，因为库存扣减常常用：

**① 误删别人的锁**

```java
// ❌ 自己用 SETNX + DEL 实现：value 是固定的 "1"、finally 直接删
//    A 超时释放后 B 拿到锁，A 的 DEL 删掉的其实是 B 的锁
redisTemplate.opsForValue().setIfAbsent(lockKey, "1", Duration.ofSeconds(30));
try { doDeduct(skuId); }
finally { redisTemplate.delete(lockKey); }
```

自己用 `SETNX` + `DEL` 实现就会踩上面那个坑；Redisson 的 `unlock()` 内部用 Lua 脚本校验 value，**不会误删别人的锁**，但锁已过期时调用会抛 `IllegalMonitorStateException`（详见本节末尾的小节）。

**② watchdog 只在没指定 leaseTime 时生效**

```java
// ✅ 不指定 leaseTime → watchdog 每 10 秒续期，业务没完锁不会过期
lock.lock();
// ❌ 指定了 30 秒 → 30 秒后强制释放，业务还在跑就丢锁了
lock.lock(30, TimeUnit.SECONDS);
```

**③ 主从切换丢锁**

Redis 主节点写入锁 → 还没同步到从节点 → 主节点挂了 → 从节点升主 → 锁没了。**RedLock 试图解决，但有学术界争议**（时钟跳变、GC 停顿可以破）。

结论：**强一致场景不要只靠 Redis 锁。** 用数据库唯一约束、状态机（`UPDATE ... WHERE status = 'INIT'`）兜底，Redis 锁只作为"减少冲突"的优化。

### 【必读】Redisson 两个坑的代码：看门狗与误解锁

16.6 给了两处最容易被 CR 放过的写法，这里补成可对照的代码。

**坑一：看门狗续期只在"不显式指定 leaseTime"时生效。**

```java
RLock lock = redissonClient.getLock("stock:" + skuId);

// ❌ 显式传 leaseTime：watchdog 关闭，30 秒后强制释放
//    业务若跑 40 秒，后 10 秒没有锁，第二个线程进了临界区
lock.lock(30, TimeUnit.SECONDS);
try { doDeduct(skuId); } finally { lock.unlock(); }

// ✅ 不指定 leaseTime：默认 30s 租约，后台每 10s（leaseTime/3）续期，
//    业务没跑完锁不过期；进程崩溃后最多 30s 自动释放
lock.lock();
try { doDeduct(skuId); } finally {
    if (lock.isHeldByCurrentThread()) { lock.unlock(); }
}
```

看门狗不是"永久锁"：它是 `RedissonLock` 里的定时刷新任务，靠 `EXPIRE` 把租约往回拨；**一旦显式给了 `leaseTime`，这个定时任务根本不会注册**（16.6 ② 的结论对，但没写清"注册"这个机制）。所以"业务耗时可能超过 30 秒"和"显式设一个更大的 leaseTime"不是一回事——后者关闭了续期，把长尾 GC、下游抖动全暴露成丢锁。**只在能给出业务耗时硬上界时才显式指定。**

**坑二：解锁"不是自己的锁"。**

16.6 ① 把 `lock.unlock()` 标成 ❌、注释写"没校验 value"，但同一节又说"用 Redisson 的 API 是安全的"——这两句其实不矛盾：前者指手写 Redis 锁容易漏校验，后者指用 Redisson 时校验由框架保证。真实情况分两层：

```java
// ❌ 自己手写 SETNX + DEL：A 超时释放后 B 拿到锁，A 的 DEL 删掉 B 的锁
redisTemplate.opsForValue().setIfAbsent(lockKey, "1", Duration.ofSeconds(30));
try { doDeduct(skuId); }
finally { redisTemplate.delete(lockKey); }        // 删的很可能不是自己的锁

// ✅ 手写也要 value 带唯一标识 + Lua 原子"比对再删"
String token = UUID.randomUUID().toString();
if (Boolean.TRUE.equals(redisTemplate.opsForValue()
        .setIfAbsent(lockKey, token, Duration.ofSeconds(30)))) {
    try { doDeduct(skuId); }
    finally {
        redisTemplate.execute(UNLOCK_SCRIPT, List.of(lockKey), token);  // GET 相等才 DEL
    }
}

// ✅ Redisson 的 unlock() 内部已用 Lua 校验 value，不会误删别人的锁；
//    但锁已过期/被别人持有时调用会抛 IllegalMonitorStateException
RLock lock = redissonClient.getLock(lockKey);
try { doDeduct(skuId); }
finally {
    if (lock.isHeldByCurrentThread()) {   // 先判断，避免对不属于自己的锁调用 unlock
        lock.unlock();
    }
}
```

**所以"Redisson 安全"要加半句：安全是指"不会误删别人的锁"，不是"任何时刻 unlock() 都能安静返回"。** 少了 `isHeldByCurrentThread()` 这道判断，在锁超时、看门狗没续上的场景下，`unlock()` 抛出的 `IllegalMonitorStateException` 会盖掉真正的业务异常，日志里只剩一个莫名其妙的锁错误（第 6 章"catch 住的是异常不是状态"是同一类陷阱）。

最后重申 16.6 ③：主从异步复制下，锁写入主节点尚未同步就切换会丢锁；RedLock 有学术界争议（时钟跳变、长 GC pause 都能破坏其安全性）。**强互斥（库存、幂等、资金）不要只靠 Redis 锁**，用数据库唯一约束或状态机 `UPDATE ... WHERE status = 'INIT'` 兜底（第 14 章行锁、第 18 章最终一致），Redis 锁只用来"减少冲突"。

## 16.7　自检清单

- [ ] 热点 key 有本地缓存（Caffeine）或 key 拆分方案
- [ ] 所有 TTL 带随机抖动，没有"整点同时过期"
- [ ] 不存在的查询有空值缓存或布隆过滤器
- [ ] 热点重建有互斥（互斥锁或逻辑过期），不是全部回源
- [ ] 没有大 key（`--bigkeys` 扫过），删除用 `UNLINK`
- [ ] `KEYS` / `FLUSHALL` 已在配置文件重命名禁用
- [ ] Redis 有高可用（哨兵/Cluster），有熔断降级兜底
- [ ] Redisson 锁：不指定 leaseTime（用 watchdog），关键路径有 DB 兜底
- [ ] 有 slowlog 监控（`slowlog-log-slower-than`）

## 16.8　一句话总结

> 缓存的容量问题都能靠加机器解决，**只有"单个 key 的吞吐"不能**。
> 热 key 是唯一一个"钱解决不了"的缓存问题。

### 【选读】延伸

- 知识库对应原理篇：17-常见Bug与解决方案/05-Redis与缓存坑、06-缓存/缓存穿透击穿雪崩、06-缓存/Redis集群与高可用
