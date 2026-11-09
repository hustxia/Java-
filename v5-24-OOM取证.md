---
book: true
volume: 5
chapter: 24
order: 5-24
title: OOM：加堆之前先取证
sources:
  - 02-Java进阶/01-JVM/OOM与CPU问题排查.md
  - 02-Java进阶/01-JVM/垃圾回收器.md
  - 02-Java进阶/01-JVM/JVM调优.md
status: review
words: 4671   # 汉字计数，由脚本实测
---


# 第二十四章　OOM：加堆之前先取证

> 卷五 · 上线之后

**本章要回答**：`OutOfMemoryError` 到底缺的是哪块内存？为什么 `-Xmx` 从 4G 加到 8G，第二天又 OOM 了？

**本章你能带走**
- 六类 OOM 的区分方法（**冒号后面那几个字决定一切**）
- 一个反直觉的事实：`exit code 137` 不是 Java OOM，**不会产生 dump**
- 一条原则：**加堆是最后手段，不是第一反应**

**难度构成**：本章主线【必读】；含【进阶】深挖 0 处；章末「延伸」小节放支线深挖与知识库指针。
---

## 24.1　现场：加到 16G，第三天还是 OOM

一个服务 OOM，运维加到 8G，好了三天；又 OOM，加到 16G；第三天又 OOM。

**"加内存能缓解三天"这个现象，本身就是最强的证据：你在漏，不是在不够用。**

如果是容量不足，加到 16G 之后应该稳定；如果是泄漏，加多少都是同一个结局——只是时间被拉长了。而拉长的时间会让人误以为"问题解决了"，直到下次爆发。

**加堆不是解决问题，是延后问题，并且让下次的 dump 更大、MAT 更难打开。**

**当时怎么误判的**：第一反应是"内存真的不够，加堆就行"——加到 8G 好三天、再加到 16G 又 OOM，每次"缓解"都更让人确信是容量问题，直到第三次爆发才起疑。中间走了一条死路：怀疑"是不是热部署或动态代理把 Metaspace 撑爆了"，`jcmd VM.metaspace` 拉出来类数量一直平稳，纯属无用线索，白白加了一次 `-XX:MaxMetaspaceSize`。真正扭转方向的是（本该在事前就配的）`HeapDumpOnOutOfMemoryError` 拿到的那份 dump，MAT 的 Dominator Tree 里一个静态 `HashMap` 的 Retained Heap 接近整堆。教训很硬：加堆只是延后问题、还把下次现场变大，先留证再谈加堆，否则你永远在和三天后的自己打同一场仗。

## 24.2　先看冒号后面那几个字

`OutOfMemoryError` 只是大类。真正决定排查方向的是 message：

| message | 缺哪块 | 典型原因 | 首查动作 |
|---|---|---|---|
| `Java heap space` | 堆 | 泄漏、一次加载大量数据、缓存无界 | `jmap -dump` + MAT |
| `GC overhead limit exceeded` | 堆（其实满了） | 同上，GC 空转 | 同上，**别关 `UseGCOverheadLimit`** |
| `Metaspace` | 元空间 | 动态生成类、CGLIB、热部署、ClassLoader 泄漏 | `jcmd VM.metaspace` |
| `Compressed class space` | 压缩类空间 | 类元数据超默认 1G 上限 | `-XX:CompressedClassSpaceSize` |
| `Direct buffer memory` | 直接内存 | Netty ByteBuf 未释放、`allocateDirect` 无节制 | `jcmd VM.native_memory summary` |
| `unable to create new native thread` | 线程栈 / OS | 线程数触顶、`ulimit -u`、容器 pids limit | `jcmd Thread.print` 数线程 |
| `Requested array size exceeds VM limit` | 堆 | 数组长度超 `Integer.MAX_VALUE - 2` | 查大集合 `toArray()`、大文件一次性读 |

**一个高频误判**：`Metaspace` 和 `Compressed class space` 经常被混为一谈，但它们由两个不同参数控制：

```bash
-XX:MaxMetaspaceSize=512m            # 元空间上限
-XX:CompressedClassSpaceSize=1g      # 压缩类空间上限（默认 1G）
```

只调前者，后者溢出照样报错。看到 `Compressed class space` 就去调第二个。

### 【必读】冒号后面每个词对应哪块内存、谁在申请它

24.2 那张表给的是"首查动作"，这里把每一类再往下拆一层：**是谁在向哪块内存申请、申请不到时 JVM 走哪条路抛出来**。同一个 `OutOfMemoryError`，冒号后面的词不同，`-Xmx` 加不加得上完全不同。

| message | 申请方 → 内存区 | 触发判据 | 加 `-Xmx` 有用吗 |
|---|---|---|---|
| `Java heap space` | `new` / 集合扩容 → 堆 | 分配时新生代与老年代都放不下，且 Full GC 后仍不够 | 有时（仅容量不足），泄漏时无效 |
| `GC overhead limit exceeded` | 同上 → 堆 | GC 时间占比 > 98% 且每次回收 < 2% 堆，连续多次 | ❌ 它就是堆满，关掉开关只是把报错推迟成 `Java heap space` |
| `Metaspace` | 类加载器 `defineClass` → 本地内存的类元数据 | 动态代理、CGLIB、热部署持续造类，`MetaspaceSize` 高水位反复触发 Full GC 仍涨 | ❌ 完全无关，`-XX:MaxMetaspaceSize` 才管它 |
| `Compressed class space` | 类元数据中的 Klass 部分 → 压缩类空间 | 默认 1G 上限被打满，常与 `UseCompressedClassPointers` 同时出现 | ❌ 要调 `-XX:CompressedClassSpaceSize` |
| `Direct buffer memory` | `ByteBuffer.allocateDirect` / Netty `ByteBuf` → 堆外 | `Bits.reserveMemory()` 申请不到，默认上限约等于 `-Xmx` | ❌ 反而更糟，要 `-XX:MaxDirectMemorySize` |
| `unable to create new native thread` | `pthread_create` → OS 线程栈 | 线程数触顶：`ulimit -u`、容器 pids limit、`-Xss` 过大 | ❌ 加堆只挤占本就不够的内存 |
| `Requested array size exceeds VM limit` | 数组分配 → 堆 | 请求长度 > `Integer.MAX_VALUE - 2`（2,147,483,645） | ❌ 这是长度上限，不是空间不够 |

`GC overhead limit exceeded` 值得单独说清，因为它最容易被当成"GC 出问题了"。它的判据是一个算式：`UseGCOverheadLimit` 默认开启，当**最近一段时间 GC 总耗时占比超过 98%、且每次回收释放不到堆的 2%** 时，JVM 主动抛出这个错误，好让进程别把剩下的时间也耗在无效 GC 上。**它不是一种独立的内存区，是"堆已经满了"的提前引爆。** 所以 `-XX:-UseGCOverheadLimit` 这种"关掉就好"的处理，只是把报错换成了稍后更贵的 `Java heap space`，还顺手丢掉了这条最有价值的线索。

`Direct buffer memory` 的链路最容易查错方向：

```text
ByteBuffer.allocateDirect(cap) / Netty PooledByteBufAllocator
   → java.nio.Bits.reserveMemory(size, cap)
      → 已用 + size > MaxDirectMemorySize ?
         → 先触发一次 System.gc()，等 Cleaner 回收堆外块
         → 仍不够 → 抛 OutOfMemoryError: Direct buffer memory
```

注意中间那次 `System.gc()`：如果启动时加了 `-XX:+DisableExplicitGC`（第 25 章会讲），这条兜底路径直接断掉，堆外块只能等 Cleaner 被动触发，泄漏会来得更快。**看到 `Direct buffer memory`，先别去调 `-Xmx`——堆外的账不在堆里。**

`unable to create new native thread` 也值得算一笔，因为它最常被误当成"内存不够"从而去加 `-Xmx`。线程栈是每线程一份、堆外的，能吃多少线程由三者里最小的那个决定：

```text
线程数上限 ≈ min( 内存余量 / (-Xss),  ulimit -u,  pids limit )
举例：-Xss1m、容器剩余内存 1.5G、pids limit 512、ulimit -u 1024
→ 内存能撑 1.5G/1M ≈ 1536 个，三者取最小 → 最多约 512 个线程
→ 若某次发版把线程池 core 从 200 调到 600，
   第 513 个线程创建时抛 unable to create new native thread
```

判据在 24.3 的 `05-thread.txt`：线程总数贴着 pids limit、`VM.native_memory` 里 `Thread` 的 `committed` 还在涨，就是它。**此时加堆不仅无效，还会挤占本就不够的线程栈预算**——堆和栈抢的是同一个 cgroup limit。这也是 24.4 那条 `limit = -Xmx × 1.3~1.5` 的另一半理由：多留出来的 30%，一部分就是给线程栈和直接内存预留的。第 9 章讲无界线程池会讲到同一条上限，只是视角从"任务堆积"换成了"线程数触顶"。



## 24.3　取证：重启之前必须做的五件事

```bash
# ① 抓 heap dump（最重要）
jmap -dump:format=b,file=/tmp/heap.hprof <pid>
# 或 jcmd（更稳，对大堆影响小）
jcmd <pid> GC.heap_dump /tmp/heap.hprof

# ② 类直方图（dump 太大时先用这个快速定性）
jcmd <pid> GC.class_histogram | head -30
# 看哪个类的实例数和占用最多

# ③ JVM 参数
jcmd <pid> VM.flags > /tmp/flags.txt

# ④ 直接内存（如果怀疑 netty/off-heap）
jcmd <pid> VM.native_memory summary     # 需要启动时加 -XX:NativeMemoryTracking=summary

# ⑤ GC 日志
# 启动时就该配好：-Xlog:gc*:file=/var/log/gc.log:time,uptime:filecount=5,filesize=50m
```

**这五件事做完再重启。** 重启一次，`/tmp` 之外的一切证据都会消失，而"下次复现"可能要等三天——三天后你面对的还是一样的信息空白。

### 【必读】提前配好 dump 参数

```bash
# 别等出事才想起来
-XX:+HeapDumpOnOutOfMemoryError
-XX:HeapDumpPath=/data/dump/
-Xlog:gc*:file=/data/log/gc.log:time,uptime:filecount=5,filesize=50m
```

`HeapDumpOnOutOfMemoryError` 是**唯一能保证"OOM 那一刻自动留证"** 的配置。没有它，你能拿到的只有"服务挂了"。

注意：大堆（16G+）dump 会暂停应用几十秒，且文件可能十几 G。**要预留磁盘空间**，并把 dump 目录挂到持久卷上——容器销毁后 `/tmp` 里的一切都会消失。

### 【必读】五件事按这个顺序敲，每条看输出里哪个字段

24.3 列了五件事，但没说"每条命令的输出该盯哪个字段"。凌晨三点对着一屏数字，最费时间的就是这一步。把顺序和字段一起固化进脚本：

```bash
#!/usr/bin/env bash
# OOM 现场取证：先留证，后重启；全部落到持久卷，别写 /tmp
set -euo pipefail
PID=$1
OUT=/data/incident/oom-$(date +%Y%m%d-%H%M%S)
mkdir -p "$OUT"

jcmd "$PID" VM.flags                          > "$OUT/01-flags.txt"
jcmd "$PID" GC.heap_info                      > "$OUT/02-heap.txt"
jcmd "$PID" GC.class_histogram                > "$OUT/03-histo.txt"   # 看 #instances 与 #bytes
jcmd "$PID" VM.native_memory summary scale=MB > "$OUT/04-nmt.txt"    # 需启动时开 NMT
jcmd "$PID" Thread.print -l                   > "$OUT/05-thread.txt"  # 数线程，查 pids limit
jstat -gcutil "$PID" 1000 10                  > "$OUT/06-gcutil.txt"  # 看 O 列是否贴顶
# 已配 HeapDumpOnOutOfMemoryError 就直接取现成 dump；否则才现场抓
cp /data/dump/*.hprof "$OUT/" 2>/dev/null || \
  jcmd "$PID" GC.heap_dump "$OUT/heap.hprof"
```

各文件里盯哪个字段，比命令本身重要：

| 文件 | 盯哪一列 | 什么值算命中 |
|---|---|---|
| `03-histo.txt` | `#instances`、`#bytes` | 某个业务类实例数百万、或 `[B`/`char[]` 累计占堆 70%+ |
| `04-nmt.txt` | `Internal`、`Class`、`Thread` 各行 `committed` | `Internal`（含堆外）远大于堆 → 直接内存嫌疑 |
| `05-thread.txt` | `java.lang.Thread.State` 计数、线程总数 | 线程数接近 `ulimit -u` 或 pids limit → 第 7 行那类 OOM |
| `06-gcutil.txt` | `O`（老年代%）、`FGC`、`FGCT` | `O` 长期 99%+、`FGC` 快速增长 → 堆已满 |

一次真实直方图的开头长这样，`#bytes` 一列直接把嫌疑点排在第一行：

```text
 num     #instances         #bytes  class name
----------------------------------------------
   1:       3,214,887   1,542,345,760  [B
   2:       3,208,102     102,659,264  com.demo.cache.Product
   3:           8,901      41,203,456  java.util.concurrent.ConcurrentHashMap$Node
```

`[B`（byte 数组）三千多万个、占 1.5GB，`Product` 三百多万个——**这一屏就能定性是"缓存把 byte 数组攒住了"**，比打开几个 G 的 dump 快得多。也正因如此，24.3 把直方图排在第二而不是最后：它是"便宜且先给方向"的那一步。

五件事的顺序不能颠倒，理由各自都很具体：

| 顺序 | 为什么必须在这个位置 | 颠倒的代价 |
|---|---|---|
| `VM.flags` 第一 | 后面所有命令的解释都依赖"当时实际生效的参数" | 重启后参数可能被改过，先抓才对得上 |
| 直方图在 dump 前 | 不触发 Full GC、几秒出结果，先给方向 | 一上来就 dump，几个 G 的文件打开前不知道找什么 |
| `Thread.print` 在数线程前 | 顺带把线程栈和锁信息一起留下 | 只数数量，事后无法判断线程在等什么 |
| dump 最后 | 会 STW，线上要挑摘流实例 | 高峰期全量 dump 能把服务冻结数分钟 |

一个真实反面案例：某次值班先跑了 `jmap -histo:live`（带 `:live` 会先触发一次 Full GC），8G 堆停了 6 秒，接口超时一片，dump 还没抓到就被要求"先恢复服务"，最后只剩一份被 GC 改过现场的直方图。**`:live` 版更聚焦泄漏，但它不是取证第一步**；要看存活对象分布，用不带 `:live` 的 `jcmd GC.class_histogram`，把"先触发 Full GC"留到已经摘流的实例上。



### 【必读】HeapDumpOnOutOfMemoryError 在容器里静默失败的四个原因

`HeapDumpOnOutOfMemoryError` 是唯一能在 OOM 那一刻自动留证的配置，但它有四个"配了却没 dump"的坑，全在容器里：

| 坑 | 现象 | 判据与修法 |
|---|---|---|
| 路径在 `/tmp` 或 emptyDir | Pod 重启后 dump 随容器一起消失 | `HeapDumpPath` 必须指向 PVC/持久卷；`-XX:HeapDumpPath=/data/dump/` 要带尾斜杠，指向目录而非文件 |
| 目录不存在或只读 | JVM 写 dump 失败但**只打一行日志**，不阻断 OOM | 镜像里 `mkdir -p` 并 `chmod`；上线前用 `jcmd <pid> GC.heap_dump /data/dump/probe.hprof` 预演一次 |
| 磁盘 quota 小于堆 | 写到一半失败，得到的 hprof 打不开 | 预留 ≥ 堆大小 × 1.5；`df -h /data/dump` 进启动检查 |
| 进程被 SIGKILL | 参数根本来不及执行 | 这是 exit code 137，见 24.4，属于另一类问题 |

第四行要和 `-XX:+ExitOnOutOfMemoryError` 一起看：容器内常配它让 JVM 快速失败、交给 K8s 重启，但它与"留 dump"是有顺序竞争的两件事——先写 dump 再退出才对，若 dump 目录不可写，快速失败反而让现场丢得更干净。**上线前那次 `GC.heap_dump` 预演，是唯一能提前证明"这条链路通"的动作**，别等真 OOM 才发现目录是只读的。

## 24.4　`exit code 137`：不是 Java 的错

K8s 里 Pod 突然重启，`kubectl describe` 显示：

```
Last State: Terminated
  Reason: OOMKilled
  Exit Code: 137
```

**这不是 Java 的 `OutOfMemoryError`，是内核的 OOM Killer 用 SIGKILL 杀掉了进程。**

区别很关键：

| | Java OOM | 内核 OOMKilled |
|---|---|---|
| 触发者 | JVM | Linux 内核 |
| 异常 | 有 `OutOfMemoryError` | **无任何 Java 异常** |
| dump | `HeapDumpOnOutOfMemoryError` 会生成 | **不会生成** |
| 证据 | 堆 dump、GC 日志 | `dmesg`、kubelet events、NMT |

所以"配了 `HeapDumpOnOutOfMemoryError` 却没 dump"的经典困惑，答案通常是 137。

排查 137 要看三个地方：

```bash
# ① 内核日志（宿主机或节点上）
dmesg -T | grep -i "killed process"

# ② K8s 事件
kubectl describe pod <pod> | grep -A5 "Last State"

# ③ 容器内存构成
# JVM 总占用 = 堆 + Metaspace + 直接内存 + 线程栈 + 代码缓存 + GC 结构
# 容器 limit 必须 > 这个总和（不是 > -Xmx）
```

**最常见的原因**：`-Xmx` 设成了容器 limit 的 100%。比如 limit 4G、`-Xmx4g`，那么堆能用到 4G，加上元空间、直接内存、线程栈，必然超 4G → 内核杀。

经验配置：

```
容器 limit = -Xmx × 1.3 ~ 1.5
```

或者用 `-XX:MaxRAMPercentage=70`，让 JVM 按容器 limit 自己算。

### 【必读】137 = 128 + 9：把 cgroup OOM Killer 判死

`Exit Code: 137` 不是一个需要背的错误码，它是一句算术：`137 = 128 + 9`，`9` 是 `SIGKILL` 的信号编号，**Shell 用 128+信号号 表示"被信号杀死"**。同理 `143 = 128 + 15` 是 `SIGTERM`。看到 137，第一结论就该是：**没有人调用 `System.exit()`，是内核直接把进程掐了**，所以 Java 层不会有任何异常、任何 finally、任何 dump。

把 24.4 那张判别表补成一条可执行的决策树：

```bash
# ① 内核日志：谁被杀、为什么
dmesg -T | grep -i -E 'killed process|oom-kill|memory cgroup'
# 典型行：Killed process 8842 (java) total-vm:..., anon-rss:4194304kB

# ② cgroup 账本（v2；v1 路径是 /sys/fs/cgroup/memory/）
cat /sys/fs/cgroup/memory.current     # 当前用量
cat /sys/fs/cgroup/memory.max         # 上限
cat /sys/fs/cgroup/memory.events      # oom_kill 计数，>0 即实锤

# ③ K8s 侧交叉印证
kubectl describe pod <pod> | grep -A5 'Last State'
```

判别顺序只有三问：**有没有 `OutOfMemoryError` 异常栈？有没有 `.hprof` 文件？`memory.events` 的 `oom_kill` 是否 > 0？** 三问里若前两问都"没有"、第三问"是"，就是 cgroup OOM Killer，不用再翻 JVM 参数。反过来，有异常栈、有 dump 却也显示 137，通常是"先被 kill、随后编排系统重启时又记录了一次"的叠加事件，按时间线分开读，别合成一个原因。

最常见的成因可以算得很清楚。容器 `limit = 4Gi`，却配了 `-Xmx4g`：

```text
堆 4.0G + Metaspace 0.5G + 线程栈 300×1M≈0.3G + 直接内存 0.5G + CodeCache 0.25G
= 约 5.55G  >  4Gi limit
```

堆还没满，RSS 已经越界，内核先动手。**多数人以为"堆没到 -Xmx 就不会 137"，实际是"堆只是 RSS 的一部分"**：`limit` 管的是整个 cgroup，不是 `-Xmx`。所以经验值 `limit = -Xmx × 1.3 ~ 1.5`，或者干脆用 `-XX:MaxRAMPercentage=70` 把算账交给 JVM（JDK 10 起 `UseContainerSupport` 默认开启，8u191 也回移了）。这两个写法别混用——显式 `-Xmx` 会覆盖 `MaxRAMPercentage`，混用时以 `-Xmx` 为准，容易以为自己在按比例、其实写死了。

cgroup 两代的取证路径不一样，抄错会一无所获：

| 版本 | 用量 / 上限 | OOM 计数 | 判据 |
|---|---|---|---|
| cgroup v1 | `memory.usage_in_bytes` / `memory.limit_in_bytes` | `memory.failcnt`、`memory.oom_control` | `failcnt` 持续增长 |
| cgroup v2 | `memory.current` / `memory.max` | `memory.events` 的 `oom` / `oom_kill` 行 | `oom_kill > 0` 即实锤 |

```bash
# ✅ v2 一眼判死：三个数就够
cat /sys/fs/cgroup/memory.max /sys/fs/cgroup/memory.current /sys/fs/cgroup/memory.events
```

`dmesg` 还要和节点对上：容器里往往没有权限读宿主机内核日志，得在**节点上**执行，或者看 kubelet 的 event。三处证据（内核日志、cgroup 账本、Pod Last State）齐了才写结论——只凭 `Exit Code: 137` 就断定"内存不够"，会漏掉另一种可能：**进程是被存活探针失败后以 `SIGTERM`（143）主动终止、再叠加一次重启记录的**，那是一条完全不同的链。



## 24.5　MAT：只看三个视图就够了

dump 拿到之后，MAT 打开（大堆记得调 `MemoryAnalyzer.ini` 的 `-Xmx`），按顺序看三件事：

**① Leak Suspects（一键泄漏报告）**

MAT 自动分析，直接给出"疑似泄漏点"和占比。**80% 的情况这里就有答案。**

**② Dominator Tree（支配树）**

按"持有内存"排序，看谁占得最多。注意看的是**支配关系**，不是引用关系——一个 `HashMap` 引用 100 万个对象，支配树里会显示 `HashMap` 占 100MB。

**③ Path to GC Roots（引用链）**

找到可疑对象后，右键 → `Path to GC Roots` → **排除弱引用/软引用**，看它是被谁强引用住的。

三条最常见的引用链：

```
Thread → ThreadLocalMap → Entry → value        ← ThreadLocal 泄漏
ClassLoader → 静态字段 → 集合                 ← 静态缓存无界
连接池 → Connection → Statement → ResultSet    ← 资源未关
```

**`Path to GC Roots` 是 MAT 里最有价值的功能**，因为它回答的是"为什么它还没被回收"——而这正是泄漏的定义。

### 【必读】三个视图各回答一个问题，别串着用

24.5 给了三个视图，但没说清它们各自**只回答一个问题**。混着用最常见的后果是：在 Histogram 里挑了一个实例数最多的 `String`，追了半天发现它只是常量池里的，跟泄漏无关。

| 视图 | 它回答的问题 | 该看哪一列 | 什么时候会误导 |
|---|---|---|---|
| Leak Suspects | "有没有一处明显的大块头？" | 自动报告的 `Retained Heap` 占比 | 只看单个 dominator，多个中等泄漏各占 10% 时它会说"未发现明显泄漏" |
| Dominator Tree | "如果回收掉这个对象，能释放多少？" | `Retained Heap` | `HashMap` 支配 100 万个小对象时它排第一，但根因在"谁往里 put" |
| Histogram | "哪一类对象数量/体积反常？" | `#instances`、`Shallow Heap` | 只按数量排，`String`/`byte[]` 永远第一，看不出谁持有 |

两个必须先分清的概念，MAT 里所有列都建立在它们之上：

```text
Shallow Heap  = 对象自身占用（不含它引用的对象）
Retained Heap = 该对象被回收后，能连带释放的总量
             = Shallow(自身) + Σ Retained(仅被它支配的子对象)
```

一个 `ConcurrentHashMap` 的 Shallow Heap 可能只有 64 字节，Retained Heap 却是 3.2GB——**因为支配树算的是"它活着，这 3.2GB 就下不去"**。所以 24.5 说"看支配关系不是引用关系"，指的就是 Retained Heap：引用只说明"能找到"，支配才说明"卡住了谁"。

正确的顺序应当是：**Leak Suspects 先给方向 → Dominator Tree 按 Retained Heap 排序锁定那个大块头 → 对它右键 `Path to GC Roots`，排除弱引用/软引用/虚引用，看是谁强引用着它**。第三步是唯一能回答"为什么它还没被回收"的，也是 24.5 里最有价值的一步。补一个实操坑：打开几个 G 的 dump 前先调 `MemoryAnalyzer.ini` 里的 `-Xmx`，MAT 自己也是个 Java 程序，默认配置常常比 dump 还小，一打开就先 OOM 一次。

## 24.6　三种根因与对策

| 根因 | 表现 | 对策 |
|---|---|---|
| **真泄漏** | 每次 Full GC 后老年代底部抬升，不回落 | 修代码（找引用链） |
| **容量不足** | Full GC 后能降下来，但很快又涨满 | 加堆 / 优化数据结构 / 加缓存上限 |
| **一次性大对象** | 某个时刻突然涨，之后回落 | 分批处理、流式读、避免 `SELECT *` 全量加载 |

区分"泄漏"和"不足"的方法很简单：**看 Full GC 之后的堆占用曲线**。

- 每次 Full GC 后老年代**高于上一次** → 泄漏（阶梯上升）
- 每次 Full GC 后回到同一水平 → 容量不足

```bash
jstat -gcutil <pid> 1000        # 看 O 列（老年代使用率）
# 或从 GC 日志里看 Full GC 前后的堆占用
```

**这个判断决定了你要不要加堆。** 泄漏加堆是浪费钱，还会让下次 dump 更难处理。

### 【必读】一段能稳定复现 Java heap space 的泄漏代码

看十遍支配树，不如自己造一次 OOM。下面这段用**无界静态集合 + ThreadLocal 不 remove** 两条最常见的泄漏路径，配 `-Xmx64m` 能在几秒内稳定复现，且能直接用 MAT 打开验证 24.5 的三步：

```java
// ❌ 可复现的泄漏：静态 Map 无界 + ThreadLocal 不清理
public class LeakDemo {
    static final Map<Long, byte[]> CACHE = new HashMap<>();
    static final ThreadLocal<byte[]> TL = new ThreadLocal<>();

    public static void main(String[] args) {
        for (long i = 0; ; i++) {
            CACHE.put(i, new byte[1024]);       // 每个 1KB，永不移除
            TL.set(new byte[1024]);              // 不 remove，线程池场景会一直挂着
            if (i % 10_000 == 0) System.out.println("put=" + i);
        }
    }
}
```

```bash
# ✅ 用 64m 小堆跑，配好自动 dump，几秒内必现
java -Xms64m -Xmx64m \
  -XX:+HeapDumpOnOutOfMemoryError -XX:HeapDumpPath=/data/dump/ \
  -Xlog:gc*:file=/data/dump/gc.log:time,uptime \
  -cp . LeakDemo
```

算一下时间：每次循环往静态 Map 塞 1KB，64m 堆去掉 JVM 自身开销约剩 55MB 可用，`55 × 1024 ≈ 56,000` 次就该见底。按每秒十万次的分配速度，**不到一秒就会抛 `java.lang.OutOfMemoryError: Java heap space`**，并自动写出 `heap.hprof`。拿这个 dump 打开 MAT：Leak Suspects 会把 `HashMap` 标成嫌疑，Dominator Tree 里它的 Retained Heap 接近整个堆，`Path to GC Roots` 一路指到 `LeakDemo.CACHE` 这个静态字段——正好把 24.5 的三步走一遍。

```java
// ✅ 修法：有界 + 过期，ThreadLocal 用完即清
private final Cache<Long, byte[]> cache = Caffeine.newBuilder()
        .maximumSize(10_000)
        .expireAfterWrite(Duration.ofMinutes(10))
        .build();

void handle() {
    TL.set(new byte[1024]);
    try {
        // 业务逻辑
    } finally {
        TL.remove();     // 线程池复用线程，不 remove 就是泄漏（第 9 章）
    }
}
```

这个例子的价值不在"知道 HashMap 会漏"，而在**它把 24.1 那句"'加内存能缓解三天'本身就是证据"变成了可控实验**：把 `-Xmx` 从 64m 加到 128m，OOM 只是从 5.6 万次推迟到 11 万次，曲线形状一模一样。**能靠加堆拖时间、不能靠加堆改形状的，就是泄漏。**

把例子再推一步，验证"泄漏到底归在哪块内存"。启动时加 `-XX:NativeMemoryTracking=summary`，跑完对比两次快照：

```bash
java -Xms64m -Xmx64m -XX:NativeMemoryTracking=summary \
  -XX:+HeapDumpOnOutOfMemoryError -XX:HeapDumpPath=/data/dump/ -cp . LeakDemo

# 另开终端，在 OOM 前抓基线，OOM 后抓 diff
jcmd <pid> VM.native_memory baseline
jcmd <pid> VM.native_memory summary.diff scale=MB
```

`summary.diff` 里若只有 `Java Heap` 一行在涨，就是纯堆内泄漏（本例的静态 Map）；若 `Thread` 或 `Internal` 也在涨，说明还叠了线程/堆外问题。**这一步把 24.2 那张"冒号后面对照表"从"看报错"变成"看账本"**：NMT 是唯一能同时看到堆、类、线程、CodeCache、GC 结构的视图，代价是 5%~10% 性能开销，所以只在排障期临时开、平时关掉。第 25 章调参时看分配速率，也要靠这份 diff 确认"降下来的到底是分配还是留存"。



## 24.7　自检清单

- [ ] 启动参数有 `-XX:+HeapDumpOnOutOfMemoryError` + `HeapDumpPath`
- [ ] 有 GC 日志，且滚动配置合理（filecount + filesize）
- [ ] dump 目录挂持久卷，磁盘空间足够（≥ 堆大小 × 1.5）
- [ ] 容器 limit ≥ `-Xmx` × 1.3（或用 `MaxRAMPercentage`）
- [ ] 知道 137 和 Java OOM 的区别，137 会去查 `dmesg`
- [ ] 能区分"泄漏"和"容量不足"（看 Full GC 后的基线）
- [ ] 缓存/集合都有容量上限（`Caffeine.maximumSize`、`LinkedHashMap` LRU）
- [ ] 大查询是分批/流式的，没有 `SELECT *` 全量进内存
- [ ] OOM 后先取证再重启，流程写进了值班手册

## 24.8　一句话总结

> OOM 是**结果**，不是原因。原因藏在"哪块内存"和"谁在持有它"里。
> 加堆只会让下一次的现场更大、更难查。

### 【选读】延伸

- 知识库对应原理篇：02-Java进阶/01-JVM/OOM与CPU问题排查、02-Java进阶/01-JVM/垃圾回收器、02-Java进阶/01-JVM/JVM调优
