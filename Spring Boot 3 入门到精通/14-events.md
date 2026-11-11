# 第 14 章 应用事件：用语义化事件解耦

## 本章目标

读完本章你将能够：

- 理解 Spring 的 `ApplicationEvent` / `ApplicationListener` / `@EventListener` 机制，以及它如何帮你在「代码生成完成」这类场景下解耦主流程与通知/审计。
- 用 `@Async` 让事件监听异步执行，避免监听器拖慢主流程。
- 用 `@TransactionalEventListener` 把事件绑定到事务的特定阶段（提交后/回滚后），解决「事务还没提交监听就拿不到数据」的坑。
- 厘清事件机制与第 8 章 AOP、第 13 章异步之间的协作边界。

---

## 14.1 为什么需要事件机制

设想一个典型场景：用户触发「代码生成完成」后，系统要**同时**做几件事——写一条操作审计日志、给相关成员发通知、更新生成统计。如果把这些逻辑全堆在 `generate()` 方法里，它会变成：

```java
public void generate(GenRequest req) {
    doGenerate(req);          // 主流程
    auditLogService.save(...); // 审计
    notifyService.send(...);   // 通知
    statsService.incr(...);    // 统计
}
```

问题：`generate()` 被迫依赖三个下游服务，任何一处慢或报错都会影响主流程；而且「生成完成后要做的事」会随着需求不断增加，方法越来越臃肿。

**事件机制的解法**：`generate()` 只负责「生成 + 发布一个 `CodeGenCompletedEvent`」，至于「谁关心这个事件、关心了要干嘛」，由监听器各自订阅。主流程与下游彻底解耦。

> 说明：codegen-server 当前**未显式使用** Spring 事件机制（已检索确认无 `ApplicationEvent`/`@EventListener`/`publishEvent`）。本章用标准通用示例讲解这一能力，并说明在 codegen 这类平台如何落地。

---

## 14.2 事件三要素：事件、发布、监听

### 14.2.1 定义事件（Payload）

事件就是一个普通对象，通常继承 `ApplicationEvent` 或（Spring 4.2+）直接是任意类：

```java
/** 代码生成完成事件 */
public class CodeGenCompletedEvent {

    private final Long userId;
    private final String tableName;
    private final long fileCount;
    private final boolean success;

    public CodeGenCompletedEvent(Long userId, String tableName, long fileCount, boolean success) {
        this.userId = userId;
        this.tableName = tableName;
        this.fileCount = fileCount;
        this.success = success;
    }
    // getter 省略
}
```

### 14.2.2 发布事件

在业务代码里注入 `ApplicationEventPublisher` 并 `publishEvent`：

```java
@Service
public class GenService {

    @Autowired
    private ApplicationEventPublisher publisher;

    public void generate(GenRequest req) {
        boolean ok = doGenerate(req);
        // 主流程只管发布事件，不关心谁监听
        publisher.publishEvent(
            new CodeGenCompletedEvent(req.getUserId(), req.getTableName(), req.getFileCount(), ok));
    }
}
```

（`**此为通用示例**`，演示 publishEvent 用法）

### 14.2.3 监听事件

最简洁的方式是 `@EventListener`：

```java
@Component
public class CodeGenEventListener {

    @EventListener
    public void onCompleted(CodeGenCompletedEvent event) {
        // 写审计日志
        auditLogService.save(event.getUserId(), "GEN", event.getTableName(), event.isSuccess());
    }

    @EventListener
    public void onNotify(CodeGenCompletedEvent event) {
        if (event.isSuccess()) {
            notifyService.send(event.getUserId(), "代码已生成：" + event.getTableName());
        }
    }
}
```

（`**此为通用示例**`，演示 @EventListener 用法）

`@EventListener` 的方法参数类型就是「想监听的事件类型」，Spring 按类型匹配分发。一个事件可以被**任意多个**监听器消费，这正是解耦的精髓。

---

## 14.3 异步监听：@Async + @EventListener

如果监听器里的通知、审计比较耗时，会拖慢 `generate()` 的返回。把监听器变成异步即可：

```java
@EventListener
@Async            // 与第 13 章 @Async 同机制，跑在自定义线程池
public void onNotify(CodeGenCompletedEvent event) {
    notifyService.send(event.getUserId(), "代码已生成：" + event.getTableName());
}
```

（`**此为通用示例**`，注意 @Async 需 @EnableAsync，且依赖第 13 章自定义的线程池）

⚠️ **踩坑提示**：`@Async` 监听方法**不能抛出受检异常到主流程**——它本就在另一条线程跑，主流程早返回了。异步监听里的异常只能在监听器内部 try/catch 处理或落到异步异常处理器，否则会被 `SimpleAsyncUncaughtExceptionHandler` 吞掉只打日志。另外，异步监听破坏了「顺序保证」：多个 `@Async` 监听器之间不再有确定的先后执行顺序，需要顺序时不要加 `@Async`。

---

## 14.4 事务绑定事件：@TransactionalEventListener

这是事件机制里最容易踩、也最有价值的一节。

**问题场景**：假设监听器的职责是「生成成功后，去数据库查刚落库的生成记录，再发通知」。如果直接用 `@EventListener`，而 `publishEvent` 发生在事务**提交之前**，那么监听器执行时，那条生成记录还没提交——监听器查不到它，发通知逻辑就错了。

`@TransactionalEventListener` 解决了这个问题：它让监听器**绑定到事务的某个阶段**才执行。

```java
@Component
public class AfterCommitListener {

    @TransactionalEventListener(phase = TransactionPhase.AFTER_COMMIT)
    public void onAfterCommit(CodeGenCompletedEvent event) {
        // 此刻事务已提交，库里已能查到生成记录
        GenRecord record = genRecordMapper.selectByTable(event.getTableName());
        notifyService.send(event.getUserId(), "已生成 " + record.getFileCount() + " 个文件");
    }

    @TransactionalEventListener(phase = TransactionPhase.AFTER_ROLLBACK)
    public void onAfterRollback(CodeGenCompletedEvent event) {
        // 主事务回滚了，做补偿/告警
        log.warn("代码生成事务回滚：{}", event.getTableName());
    }
}
```

（`**此为通用示例**`，演示 AFTER_COMMIT / AFTER_ROLLBACK 阶段）

`TransactionPhase` 的几个阶段：

- `AFTER_COMMIT`（默认）：事务成功提交后触发——最常用，保证监听器看到的是「已持久化」的数据。
- `AFTER_ROLLBACK`：事务回滚后触发，用于补偿。
- `AFTER_COMPLETION`：无论提交还是回滚都触发。
- `BEFORE_COMMIT`：事务提交前触发。

⚠️ **踩坑提示**：`@TransactionalEventListener` 的监听器，**只有当前存在事务且到达对应阶段时才会被调用**。如果 `publishEvent` 时根本没有开启事务（比如一个 `@Transactional(propagation=NOT_SUPPORTED)` 的方法里发事件），`AFTER_COMMIT` 监听器**根本不会执行**——事件就像「丢失」了一样。若希望「无事务时也照常触发」，加 `fallbackExecution = true`。

---

## 14.5 事件 vs AOP vs 异步：协作边界

把本书前面几章串起来，三者都能做「横切」，但职责不同，别用混：

| 机制 | 解决什么 | 典型场景 |
|------|----------|----------|
| **AOP（第 8 章）** | 把「横切逻辑」织入**指定方法的执行点**（前/后/异常），关注「方法拦截」 | 操作日志切面、数据权限改写 SQL、统一耗时统计 |
| **事件（本章）** | 把「发生了某事」广播出去，关注「状态变化的通知与解耦」 | 生成完成后触发通知/审计/统计 |
| **异步（第 13 章）** | 把「耗时操作」挪到别的线程，关注「不阻塞主流程」 | 发邮件、调第三方、重计算 |

它们可以叠加使用，例如：**AOP 切面**捕获「生成方法成功返回」→ 在切面里 `publishEvent` 一个事件 → 事件被 **`@Async` 监听器**异步消费去发通知。分工是：

- AOP 负责「在正确的执行点无侵入地埋点」；
- 事件负责「把这件事广播给多个互不相识的订阅者」；
- 异步负责「让订阅者的耗时动作不拖慢主流程」。

> 结合第 8 章的审计：如果审计逻辑强依赖「方法执行结果且必须同步落库」，用 AOP 更直接；如果「生成完成」后要联动多个下游（通知、统计、缓存失效），用事件更解耦。codegen-server 当前审计走 AOP 切面（见第 8 章），若未来要扩展「生成完成联动」，事件机制就是最顺手的补充。

---

## 本章小结

- Spring 事件三要素：定义事件对象 → `ApplicationEventPublisher.publishEvent(...)` 发布 → `@EventListener` 按类型监听。一个事件可被多个监听器订阅，主流程与下游解耦。
- `@EventListener` + `@Async` 让监听异步执行（需 `@EnableAsync` 与自定义线程池），但会失去执行顺序保证，异常也需在监听器内自行处理。
- `@TransactionalEventListener(phase=...)` 把监听绑定到事务阶段，`AFTER_COMMIT` 能保证监听器看到已提交的数据，避免「事件先于提交、查不到刚落库记录」的坑；无事务时默认不触发，需 `fallbackExecution=true`。
- 事件、AOP、异步三者分工明确：AOP 负责方法执行点的横切织入，事件负责状态变化的广播解耦，异步负责不阻塞主流程。它们可组合（AOP 埋点 → 发事件 → 异步监听），是构建可扩展平台的重要积木。
- codegen-server 当前未显式使用事件机制；在「代码生成完成联动通知/审计/统计/缓存失效」这类需求上，事件是比把逻辑硬塞进主流程更优雅的落地方式。
