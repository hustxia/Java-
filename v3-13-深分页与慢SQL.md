---
book: true
volume: 3
chapter: 13
order: 3-13
title: 深分页与慢 SQL：从 8 秒到 200 毫秒
sources:
  - 17-常见Bug与解决方案/04-MySQL与ORM坑.md
  - 05-数据库/01-MySQL/SQL优化.md
  - 05-数据库/01-MySQL/执行计划.md
status: review
words: 4577   # 汉字计数，由脚本实测
---


# 第十三章　深分页与慢 SQL：从 8 秒到 200 毫秒

> 卷三 · 数据落地

**本章要回答**：`LIMIT 1000000, 10` 只返回 10 条，为什么这么慢？

**本章你能带走**
- 深分页的真实成本：**不是"少了 100 万行"，是"扫描 100 万 + 回表 100 万"**
- 三种改法：延迟关联、游标翻页、覆盖索引，各自的适用边界
- 一条判断：**优化器不用索引，常常是因为它算过账，觉得不值得**

**难度构成**：本章主线【必读】；含【进阶】深挖 2 处；章末「延伸」小节放支线深挖与知识库指针。
---

## 13.1　现场：导出功能拖垮了主库

一个后台导出页面，默认每页 10 条。运营往下翻到第 8000 页，浏览器转圈 8 秒，然后主库 CPU 冲到 90%，**其他接口跟着一起慢**。

SQL 很简单：

```sql
SELECT * FROM order_info ORDER BY id LIMIT 80000, 10;
```

`id` 是主键，`ORDER BY id` 走主键索引，看起来没毛病。但 `LIMIT 80000, 10` 的真实执行过程是：

```
① 沿主键索引顺序扫描
② 每扫到一行，回表取整行数据
③ 计数，前 80000 行全部丢弃
④ 只返回第 80001~80010 行
```

**扫描 8 万行、回表 8 万次，只为返回 10 行。** 成本随页码线性增长——第 1 页 1ms，第 8000 页 8 秒。

更糟的是它占着连接，而且 `SELECT *` 让回表的每一行都要读完整行（可能带 TEXT 字段）。

**当时怎么误判的**：第一反应是"深分页慢，那就加索引 / 加机器"——`id` 本就是主键索引、加了两台从库后主库 CPU 照样冲到 90%，都不对症；又怀疑"`SELECT *` 把 TEXT 字段拉太多拖慢了回表"，于是只 `SELECT id` 试了一遍，单条快了，但翻到第 8000 页依旧 8 秒。两条都排除后，才有人把 `LIMIT 80000, 10` 的执行过程一层层拆开：扫 8 万行、回表 8 万次、丢掉前 8 万行，瓶颈在"回表次数"而不是"扫描行数"。这一下把方向从"扩容"扭回"减少回表"，后面的延迟关联才对路。

## 13.2　三种改法

### 【必读】① 延迟关联（Deferred Join）

思路：**先在索引上拿到主键，再回表拿数据。** 让"丢弃 8 万行"这件事不产生回表。

```sql
-- ❌ 回表 8 万次
SELECT * FROM order_info ORDER BY id LIMIT 80000, 10;

-- ✅ 子查询只走索引（覆盖索引，不回表），外层按 id 精确回表 10 次
SELECT o.* FROM order_info o
INNER JOIN (
    SELECT id FROM order_info ORDER BY id LIMIT 80000, 10
) t ON o.id = t.id;
```

关键在子查询里只有 `id` 一列——**`id` 就在索引上，不需要回表**。所以子查询是"纯索引扫描 8 万行"，外层只回表 10 次。

收益：从"8 万次回表"降到"10 次回表"。这是性价比最高的一种改法，因为它**不需要改前端、不需要改接口协议**。

### 【必读】② 游标翻页（Keyset Pagination）

思路：**不要"第 N 页"，要"比上一页最后一条更靠后的 10 条"。**

```sql
-- ❌ 偏移量翻页
SELECT * FROM order_info ORDER BY id LIMIT 80000, 10;

-- ✅ 游标翻页：把上一页最后一条的 id 带过来
SELECT * FROM order_info WHERE id > 80000 ORDER BY id LIMIT 10;
```

这条 SQL 的 `type` 是 `range`，扫描 10 行，**耗时恒定**，不管翻到第几页。

代价非常明确，必须先说清楚：

| 代价 | 说明 |
|---|---|
| 不能跳页 | 用户不能"直接去第 500 页"，只能上一页/下一页 |
| 排序字段必须唯一且有序 | 用 `create_time` 排序要加 `id` 作为第二排序键，否则会漏/重 |
| 前端要改 | 传 `lastId` 而不是 `pageNo` |

```sql
-- 复合游标：按 create_time 排序时，要用 (create_time, id) 做游标
SELECT * FROM order_info
WHERE (create_time, id) > ('2026-11-08 10:00:00', 80000)
ORDER BY create_time, id
LIMIT 10;
```

**只要业务允许（列表页、消息流、日志查询基本都是这种场景），游标翻页是最优解。** 它把"越翻越慢"直接变成"永远一样快"。

### 【必读】③ 覆盖索引：让查询根本不需要回表

如果返回的字段都在索引里，MySQL 直接从索引返回：

```sql
-- 联合索引 (status, create_time, id)
SELECT id, status, create_time FROM order_info
WHERE status = 1 ORDER BY create_time DESC LIMIT 10;
-- Extra: Using index  ← 全程不回表
```

适用条件很苛刻：**返回的列必须全部在索引里**。做列表页（只返回摘要字段）时很有效，做详情页时没用。

### 【必读】把 100 万偏移量算成一笔账

13.1 现场里"第 1 页 1ms、第 8000 页 8 秒"不是两个孤立的数字，把它们相除就能验出成本模型：

```
8s / 1ms = 8000 = 页码数  →  耗时 ∝ 页码
```

`LIMIT offset, N` 的执行成本是线性的：

```
扫描索引项数 = offset + N
回表次数（SELECT *）= offset + N
丢弃行数    = offset
返回行数    = N
有效产出比  = N / (offset + N)
```

代入 offset = 1,000,000、N = 10：

```
扫描并回表 1,000,010 次，丢弃 1,000,000 行，返回 10 行
有效产出比 = 10 / 1,000,010 ≈ 0.001%
```

也就是说 **99.999% 的工作没有任何产出**。现场那个 8 秒，买到的就是 10 行数据。

再把回表换成 IO 账（第十二章算过：一次二级索引点查约 3 次 IO，回表再约 3 次，且回表是随机 IO）。取单次随机读 0.1ms（SSD）到 10ms（HDD）的常见量级：

```
1,000,010 × 0.1ms = 100 秒（SSD，且假设全不命中缓存）
1,000,010 × 10ms  = 约 2.8 小时（HDD）
```

这两个数字要在自己的硬件上实测，Buffer Pool 命中会把它们压下来，但**量级关系不变**：深分页的瓶颈从来不是"扫描 100 万行索引"，是"100 万次随机回表"。顺序扫索引 100 万项可能只要几十毫秒，随机回表 100 万次是另一个数量级。这也解释了为什么 `SELECT id`（覆盖索引）能救命——它把第二项整个删掉了。

反常识点：多数人以为 `LIMIT 1000000, 10` 慢在"数据库翻了 100 万行"，于是想靠加机器、加缓存解决。实际慢在"每一行都回表读了整行又扔掉"，**这是 SQL 写法制造的无用功，加机器只是把无用功复制 N 份**。13.5 把"加机器"排在最后一步，就是这个道理。

### 【必读】延迟关联前后：把耗时算式写出来

13.2 给了 SQL，这里把收益算成可核对的式子。改法的核心是让"丢弃 100 万行"这件事**不产生回表**：

```sql
-- ❌ 每扫一行就回表一次
SELECT * FROM order_info ORDER BY id LIMIT 1000000, 10;

-- ✅ 子查询只取 id（覆盖索引，不回表），外层按 10 个 id 精确回表
SELECT o.* FROM order_info o
INNER JOIN (
    SELECT id FROM order_info ORDER BY id LIMIT 1000000, 10
) t ON o.id = t.id;
```

设单次回表成本 `R`（随机 IO），单次索引项顺序扫描成本 `S`，经验上 `R` 比 `S` 大一到两个数量级。两种写法的成本：

```
改前 = (offset + N) × R                       ≈ 1,000,010 × R
改后 = (offset + N) × S + N × R              ≈ 1,000,010 × S + 10 × R
收益 ≈ 1 - S/R                               → 接近 100%
```

代一组便于心算的数：`R = 0.1ms`、`S = 0.001ms`：

```
改前 ≈ 100 秒
改后 ≈ 1.0 秒 + 0.001 秒 ≈ 1 秒
```

约两个数量级。**具体倍数取决于行宽、Buffer Pool 命中率与是否有 TEXT 列，需在自己的数据上实测**；标题里"8 秒到 200 毫秒"是 40 倍，属于这一类改法的常见区间，不是承诺值。

一个必须现场核对的前提：子查询的 `EXPLAIN` 里 `Extra` 要出现 `Using index`。如果子查询写成了 `SELECT id, status`，而 `(id, status)` 不在同一棵索引上，就会退化成"边翻边回表"，延迟关联白改。取证命令就一条：

```sql
EXPLAIN SELECT id FROM order_info ORDER BY id LIMIT 1000000, 10;
-- key=PRIMARY, Extra=Using index  ✅ 才成立
```

还有一处容易被忽略：延迟关联**仍然要顺序翻过 100 万个索引项**，它只是把回表从 100 万次降到 10 次。所以它是"必须跳页"场景下的最优解，不是"任意页都快"——真正恒定耗时的是游标翻页（13.2 ②）。两者的差别是 O(offset) 与 O(1)，别混。

### 【进阶】覆盖索引为什么能免回表：一次点查的两次 B+ 树

延迟关联之所以成立，全靠"覆盖索引"这一个机制。把它画开：

```
聚簇索引（PRIMARY）：叶子 = 整行数据
二级索引 idx_x(x)  ：叶子 = (x 的值, 对应主键 id)

SELECT * FROM t WHERE x = ? 的执行链路：
  ① 走 idx_x 的 B+ 树，定位到叶子，拿到 (x, id=100)      ← 第 1 次 B+ 树
  ② 拿 id=100 再走 PRIMARY 的 B+ 树，取出整行           ← 第 2 次 B+ 树（回表）
  ③ 返回整行

SELECT id FROM t WHERE x = ? 的执行链路：
  ① 走 idx_x 的 B+ 树，叶子上就已经有 id                ← 只有第 1 次
  ② 直接返回，Extra: Using index，回表 0 次
```

关键在二级索引叶子**本来就带着主键值**：`id` 是索引的一部分，不需要去聚簇索引取。所以"覆盖"的判据很死——`SELECT` 的列、以及 `WHERE` / `ORDER BY` 用到的列，必须全部落在同一棵索引里，多一列都不行。

| 写法（索引 `(status, create_time, id)`） | 回表次数 | `Extra` | 判据 |
|---|---|---|---|
| `SELECT id, status, create_time` | 0 | `Using index` | 全在索引内，覆盖 |
| `SELECT id, status, amount` | 命中行数次 | `Using where` | `amount` 不在索引，逐行回表 |
| `SELECT *` | 命中行数次 | 通常无 `Using index` | 破坏覆盖 |

这就把 13.2 ③ 那句"适用条件很苛刻"说清楚了：**多取一列就前功尽弃**，所以覆盖索引只适合列表页、下拉框、摘要接口这类字段固定的查询，详情页永远用不上。

一个反常识点：多数人以为 `SELECT *` 的代价只是"多传了几个字段"。更贵的是它悄悄把"索引扫描"变成了"大量随机回表"——第十二章的 `Extra` 对照表里，`Using index` 消失、`Using where` 出现，就是这件事的现场证据。表里有 `TEXT` / `JSON` 时更严重，每次回表都可能触发额外的离页读取。**改 `SELECT *` 往往是列表接口性价比最高的一次改动，一行代码、零索引变更。**

## 13.3　什么时候该用哪种

| 场景 | 推荐 | 原因 |
|---|---|---|
| 后台管理列表，允许改协议 | 游标翻页 | 恒定耗时，一劳永逸 |
| 前端已定死 `pageNo`，不能改 | 延迟关联 | 只改 SQL，不动接口 |
| 只返回少数字段 | 覆盖索引 | 彻底不回表 |
| 需要总数 `COUNT(*)` | 单独处理（见下） | 深分页的 COUNT 往往比数据本身更慢 |

**`COUNT(*)` 是深分页的隐藏杀手。** 分页组件要显示"共 128 万条"，这个数字每次翻页都算一遍：

```sql
SELECT COUNT(*) FROM order_info WHERE status = 1;   -- 走索引但也要扫全部匹配行
```

三种处理：

1. **缓存总数**：按条件缓存 5 分钟，翻页时不重算
2. **不显示精确总数**：显示"约 128 万条"，或只显示"是否有下一页"
3. **维护计数表**：写入时维护，牺牲实时性换性能

**第 2 种最常被忽略，但它是最有效的。** 用户真的需要知道"精确 1,284,731 条"吗？

### 【必读】游标翻页的三个边界：跳页、删除、乱序

13.2 ② 列了三条代价，这里把最容易被低估的两条展开——尤其是"删除"，它比"不能跳页"隐蔽得多。

**边界一：不能跳页。** `WHERE id > lastId` 只认"上一页最后一条"，前端拿不到"第 500 页"的起点。Google 式"最多翻 100 页"或直接改成筛选条件，本质都是回避这个限制，不是解决它。

**边界二：偏移量翻页本身会漏行 / 重行。** 这条常被算到游标头上，其实正好相反。翻页之间若有写入，偏移量会整体漂移：

```
t0：SELECT ... LIMIT 10, 10   → 拿到第 11~20 行，lastId=20
t1：另一事务插入了 id=5 的新行（或删除了 id=3）
t2：SELECT ... LIMIT 20, 10   → 原第 21 行现在排到第 22 位，第 20 行被重复看到
```

游标翻页用 `id > 20` 定位，插入/删除都不影响结果——**它比偏移量翻页更健壮**，这也是 Feed 流、消息流天然该用它的原因。

**边界三：游标键选错，删除与更新会静默漏数据。** 真正的坑在这里。如果游标取的不是不可变主键，而是会变的排序列（排行榜分数、`update_time`、状态），那么上一页最后那一行被删除或改了分数之后，下一页的起点就对不上了：

```sql
-- ❌ 游标取了可变列，且排序键不唯一：漏行 / 重行
SELECT * FROM t WHERE score > 90 ORDER BY score LIMIT 10;

-- ✅ 复合游标：完整元组比较，第二排序键用唯一且不可变的 id
SELECT * FROM t
WHERE (create_time, id) > ('2026-11-08 10:00:00', 80000)
ORDER BY create_time, id
LIMIT 10;
```

注意元组比较必须写全 `(create_time, id) > (?, ?)`，只写 `create_time > ?` 时，同一秒内的多行会被整批跳过。这就是为什么 13.2 ② 要求"排序字段唯一且有序"——不是洁癖，是漏行与否的分界。

把"删除致漏"亲手跑一遍，比记结论可靠：

```sql
-- 复现：游标取了可变排序列，删除后漏行
-- 会话 A：第一页最后一条 score=90、id=7
SELECT * FROM t_rank ORDER BY score DESC, id DESC LIMIT 10;   -- 记下 last=(90, 7)
-- 会话 B：删掉 id=7 这一行，或把它的 score 改成 95
DELETE FROM t_rank WHERE id = 7;
-- 会话 A：第二页
SELECT * FROM t_rank WHERE score < 90 ORDER BY score DESC, id DESC LIMIT 10;
-- ❌ 只用 score 做游标，score 恰好等于 90 的其他行被整批跳过
-- ✅ 用完整元组 (score, id) < (90, 7) 才不会漏
```

判据只有一条：**游标值必须来自上一页那一行的"不可变列"**。删除之所以危险，不是因为 MySQL 记不住位置，而是你交给它的锚点本身可能已经不存在、或已经变了。用自增主键做锚点时，删除一行只是让那个 id 消失，后续 `id > lastId` 依然连续，不受影响——这也是"主键游标"比"业务字段游标"更稳的根本原因。

一句话收口：**游标翻页的性能是免费的，正确性要自己挣**。游标键必须满足唯一、有序、不可变三条，自增主键是唯一几乎不用想的选项；一旦用了业务字段，就得接受它在删除与更新下的边界。分库分表之后（第十七章）跨分片排序还得把分片键拼进游标，是同一问题的放大版；而排序能不能走索引，回到第十二章的最左前缀。

## 13.4　其他几类慢 SQL

### 【必读】隐式转换与索引失效

见上一章。这里只补一个排查动作：**慢查询日志里 `Rows_examined` 远大于 `Rows_sent`，就是"扫了很多只返回一点"**，典型是索引没走对。

```sql
-- 慢查询日志里看这三个数
-- Query_time: 8.02  Rows_examined: 80010  Rows_sent: 10
```

`Rows_examined / Rows_sent = 8001` —— 这个比值超过 100 就该查索引了。

### 【必读】N+1 查询

ORM 的经典病：

```java
// ❌ 1 次查订单 + N 次查用户
List<Order> orders = orderMapper.selectByStatus(1);      // 1 次
for (Order o : orders) {
    o.setUser(userMapper.selectById(o.getUserId()));     // N 次
}
```

100 条订单 = 101 次 SQL。每次 2ms，总共 202ms——**单看每条都很快，加起来就是慢**。

```java
// ✅ 批量查再内存拼装
List<Long> userIds = orders.stream().map(Order::getUserId).distinct().toList();
Map<Long, User> userMap = userMapper.selectByIds(userIds).stream()
        .collect(Collectors.toMap(User::getId, u -> u));
orders.forEach(o -> o.setUser(userMap.get(o.getUserId())));
```

MyBatis-Plus 的 `@TableField(exist = false)` 关联字段、JPA 的 `@ManyToOne(fetch = LAZY)` 都是 N+1 的高发地。**开启 SQL 日志，数一下一次请求打了几条 SQL**，是最快的发现方式。

### 【必读】批量写：伪批量

```java
// ❌ 循环 insert：1000 次网络往返
for (Order o : list) orderMapper.insert(o);

// ⚠️ saveBatch 但不加参数：仍是逐条 insert
// jdbc url 必须加 rewriteBatchedStatements=true，否则 MySQL 驱动不会真正合并
```

MyBatis-Plus 的 `saveBatch` 底层是 JDBC batch，但 **MySQL 驱动默认不重写 SQL**，所以每次都发一条完整 INSERT。加上参数才真正合并成 `INSERT INTO ... VALUES (...),(...),(...)`：

```
jdbc:mysql://host/db?rewriteBatchedStatements=true
```

这一行参数能把 1000 条插入从 3 秒降到 80ms。**它是最容易被忽略的一个"性能开关"**。

### 【必读】N+1 与伪批量：两段能直接跑的复现

13.4 给了改法，这里给"怎么证明它真的发生了"——这两类问题都不会报错，只能靠数 SQL 条数抓。

**N+1 的可运行取证。** 不靠肉眼数日志，把条数变成断言：

```java
// ❌ 1 次查订单 + N 次查用户；100 条订单 = 101 次 SQL
List<Order> orders = orderMapper.selectByStatus(1);
for (Order o : orders) {
    o.setUser(userMapper.selectById(o.getUserId()));
}

// ✅ 批量查 + 内存拼装：2 次 SQL
List<Long> ids = orders.stream().map(Order::getUserId).distinct().toList();
Map<Long, User> map = userMapper.selectByIds(ids).stream()
        .collect(Collectors.toMap(User::getId, u -> u));
orders.forEach(o -> o.setUser(map.get(o.getUserId())));
```

```java
// 可运行验证：用 p6spy / Druid 统计一次请求内的 SQL 条数
@Test
void noNPlusOne() {
    SqlCounter.reset();                 // 自定义拦截器累计 execute 次数
    List<Order> orders = orderService.listWithUser(1);
    assertThat(SqlCounter.count()).isLessThanOrEqualTo(2);   // ❌ 原实现会是 101
}
```

算式比感觉可靠：单次 SQL 2ms、单次网络 RTT 0.5ms，100 条订单：

```
N+1   = 101 × (2ms + 0.5ms) ≈ 253ms
批量  = 2   × (2ms + 0.5ms) ≈ 5ms
```

**单看每一条都很快，加起来就是慢**——这类问题在测试库（订单只有 3 条）里永远不会暴露，必须造满一页数据再跑。

**伪批量的可运行取证。** `saveBatch` 不等于批量，别只看 URL，去数服务端到底收到几条 `INSERT`：

```bash
# 打开 general log，执行批量插入后数语句条数
mysql -e "SET GLOBAL general_log = ON;"
grep -c "INSERT INTO" /var/lib/mysql/*.log        # ❌ 未开 rewrite：1000 条
                                                  # ✅ 开了 rewrite：2 条（每批 500）
```

```ini
# JDBC URL：唯一真正让驱动合并多值 INSERT 的开关
jdbc:mysql://host:3306/db?rewriteBatchedStatements=true
```

反常识点：多数人以为调了 `saveBatch`、URL 里加了参数就万事大吉。**改了配置不等于生效**——驱动版本、是否启用服务端预编译、批内 SQL 模板是否完全一致，都会让重写失效；上面那条 `grep -c` 才是验收标准。另外合并后的单条 SQL 别超过 `max_allowed_packet`，按 500~1000 行一批是稳妥起点。

这两条和 13.1 的现场是同一类病：**慢在往返次数，不在单条耗时**。深分页放大的是回表次数，N+1 放大的是网络往返次数，伪批量放大的是事务提交次数——三者都是"把一个 O(1) 的动作写成了 O(N)"。

## 13.5　优化顺序：不要一上来就加索引

正确的顺序，成本从低到高：

```
1. 看 SQL 本身：有没有 SELECT *、有没有 N+1、有没有循环查库
2. 看索引：EXPLAIN，type 和 rows
3. 改 SQL：延迟关联、游标翻页、去掉函数
4. 加/调索引（注意写放大）
5. 改数据模型：冗余字段、读写分离、分表
6. 上缓存 / 异构（ES）
```

大多数"慢 SQL"在第 1、3 步就解决了。**直接跳到第 4 步加索引，往往加了也用不上**（因为问题是写法，不是索引）。

### 【进阶】优化顺序四步：为什么加机器总是最后一步

13.5 给了六步清单，把它压成四个决策点更好记，也更容易在 CR 里执行：

| 步骤 | 动作 | 取证命令 / 判据 | 跳过它的代价 |
|---|---|---|---|
| ① 看执行计划 | 先定位到具体哪条 SQL | 慢日志按 `Rows_examined/Rows_sent` 排序；`EXPLAIN` 看 `type/key/rows/Extra` | 凭感觉改 SQL，改错地方 |
| ② 改写 SQL | 去掉 `SELECT *`、拆 N+1、延迟关联、游标翻页 | 改前改后 `rows` 与耗时留痕对比 | 加了索引也用不上 |
| ③ 调索引 | 补复合索引、覆盖索引、刷统计信息 | `ANALYZE TABLE`；8.0 可建直方图 | 单表索引超 8 个，写放大 |
| ④ 加机器 / 分表 | 读写分离、缓存、ES、分库分表 | 只在 ①②③ 都做完仍不达标时 | 把无用功复制 N 份 |

顺序反了会怎样，用现场的数字算一遍。那条 8 秒的深分页 SQL 占着 1 个数据库连接跑 8 秒：

```
单实例：QPS=1、耗时 8s → 并发占用连接 ≈ 1 × 8 = 8 个
Hikari maximumPoolSize 默认 10 → 两个这样的请求就把池占满
加 10 台应用 → 10 × 10 = 100 个连接同时压向同一主库
→ 主库连接池先崩，其他接口一起慢（现场正是这样）
```

按 Little's law `L = λ × W`，加机器提高的是到达率 `λ`，不改服务时间 `W`。**只要 `W` 里的 8 秒还是 8 秒，扩容只是让队列更长、让主库更早打满。** 这和第 4 章连接池耗尽、第 7 章"加线程等于给排队队伍扩容"是同一条公式的三个现场。

取证顺序也按这四步走，两分钟内不要跳步：

```sql
-- ① 定位：慢日志三件套 Query_time / Rows_examined / Rows_sent
--    比值 > 100 就查索引
EXPLAIN SELECT ...;                        -- 看 type、key、rows、Extra
-- ② ③ 之间的分水岭：统计信息是否过期
ANALYZE TABLE order_info;                  -- 刷新后再 EXPLAIN 对比
-- 8.0.18+ 想看真实耗时（会真实执行，生产别对 UPDATE/DELETE 跑）
EXPLAIN ANALYZE SELECT ...;
```

版本上有三个会漂移的点：`EXPLAIN ANALYZE` 需 8.0.18+；8.0 起已移除查询缓存，别再按 `query_cache_size` 做规划；直方图（`UPDATE HISTOGRAM`）也是 8.0 才有的。分库分表之后（第十七章），深分页要改成"每片各取 TopN 再归并"，是步骤 ④ 里的另一套题；缓存（第十五、十六章）同理，属于最后一步，不是开场白。

一句话：**先把"每个请求做了多少无用功"降下来，再谈用多少台机器去扛。** 九成慢查询死在步骤 ②③，架构级手段是最后的大招。

## 13.6　自检清单

- [ ] 列表接口没有超过 100 页的偏移量翻页（或有游标翻页方案）
- [ ] 深分页的 `COUNT(*)` 有缓存或不精确返回
- [ ] 没有 `SELECT *`（尤其表里有 TEXT/JSON 时）
- [ ] 没有循环里查库（N+1），已批量查询
- [ ] 批量插入的 JDBC URL 带 `rewriteBatchedStatements=true`
- [ ] 慢查询日志有 `Rows_examined / Rows_sent` 比值监控（> 100 告警）
- [ ] 关键 SQL 的 `EXPLAIN` 有版本化管理
- [ ] 优化先改 SQL，再考虑加索引

## 13.7　一句话总结

> 深分页的慢，不是"数据库不行"，是**你在让它做了 8 万次没有产出的工作**。
> 优化 SQL 的本质，是让数据库只做"有产出"的那部分工作。

### 【选读】延伸

- 知识库对应原理篇：17-常见Bug与解决方案/04-MySQL与ORM坑、05-数据库/01-MySQL/SQL优化、05-数据库/01-MySQL/执行计划
