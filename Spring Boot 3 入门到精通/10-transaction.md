# 第 10 章 声明式事务：@Transactional 的原理与陷阱

本章目标：理解 Spring `@Transactional` 的底层机制（AOP 代理），掌握传播行为、隔离级别与回滚规则，并通过 codegen-server 的真实代码看清两类典型场景——「哪些地方必须包事务」与「哪些地方故意不包事务」，避免纸上谈兵。

## 10.1 原理：事务是基于 AOP 代理的

`@Transactional` 不是数据库魔法，而是 Spring AOP 在方法调用前后自动织入 `begin / commit / rollback`。关键点：**它通过代理对象生效**。当你注入 `GenTableService` 并调用其方法时，调用先经过 Spring 生成的代理，代理负责开启事务、调用目标方法、根据成败提交或回滚。

因此一个根本约束是：**只有「通过代理调用」的外部方法才走事务切面，类内部自调用不走代理，事务注解会失效**（见 10.5）。

## 10.2 必须用事务的真实案例

codegen-server 中「结构漂移同步」(`syncColumns`) 是多步数据库写操作：先批量插入新列、再按条件删除被移除的列。这几步必须原子——要么全成、要么全不成，否则表配置与数据库结构对不上。源码 `com.codegen.service.impl.GenTableServiceImpl`：

```java
// 来源：com.codegen.service.impl.GenTableServiceImpl（节选）
@Override
@Transactional                       // 整个方法在一个事务里
public GenColumnSyncVO syncColumns(Long id, boolean removeMissing) {
    GenTable table = getById(id);
    if (table == null) {
        throw new BusinessException(404, "表配置不存在");
    }
    // ... 读取库里列、读取配置列，做差异 ...

    // 1) 库里有、配置没有 → 批量新增
    List<GenTableColumn> toInsert = new ArrayList<>();
    for (...) { /* 攒待插入实体 */ }
    if (!toInsert.isEmpty()) {
        columnService.saveBatch(toInsert);     // 第①步写库
    }

    // 2) 配置里有、库里没有 → removeMissing=true 才删除
    List<Long> toRemove = new ArrayList<>();
    for (...) { /* 收集待删 id */ }
    if (!toRemove.isEmpty()) {
        columnService.removeByIds(toRemove);   // 第②步写库
    }
    return vo;
}
```

如果第①步成功、第②步抛异常（比如某个 id 关联外键冲突），`@Transactional` 会把第①步的 `saveBatch` 一并回滚，保证配置表始终一致。这正是「多步写操作必须事务包裹」的标准范式。

codegen-server 中大量写库方法都标了 `@Transactional`（`GenTableServiceImpl` 有 10 处，`DictServiceImpl`、`SysUserServiceImpl` 等也都用），且多数写成 `@Transactional(rollbackFor = Exception.class)`——这是**强烈推荐**的写法（见 10.4）。

## 10.3 传播行为与隔离级别

### 10.3.1 传播行为（propagation）

当一个事务方法调用另一个事务方法时，两者如何「共存」由传播行为决定。最常用两个：

- `REQUIRED`（默认）：如果已有事务就加入，没有就新建。绝大多数业务方法用它。
- `REQUIRES_NEW`：挂起当前事务，新建一个独立事务。内部事务的提交/回滚不影响外部。适用于「记账/写日志」这类「即使主流程失败也必须落库」的场景。

> 通用示例：下单主流程里记审计日志，日志失败不应导致订单回滚。

```java
// 通用示例
@Transactional
public void placeOrder(OrderDTO dto) {
    orderMapper.insert(...);
    auditLogService.record(dto);   // 该方法标 @Transactional(REQUIRES_NEW)
}

@Transactional(propagation = Propagation.REQUIRES_NEW)
public void record(AuditDTO dto) { auditMapper.insert(dto); }
```

其它还有 `NESTED`（嵌套，依赖 JDBC 保存点）、`SUPPORTS`、`NOT_SUPPORTED`、`NEVER`、`MANDATORY`，按「是否要求/支持已有事务」选择，实践中 90% 用 `REQUIRED`，少数用 `REQUIRES_NEW`。

### 10.3.2 隔离级别（isolation）

对应数据库隔离级别，解决脏读/不可重复读/幻读：

- `READ_UNCOMMITTED`：读未提交，可能脏读。
- `READ_COMMITTED`：读已提交（Oracle 默认）。
- `REPEATABLE_READ`：可重复读（MySQL InnoDB 默认）。
- `SERIALIZABLE`：串行化，最安全但性能最差。

Spring 默认 `ISOLATION_DEFAULT`，即沿用数据库配置。除非遇到明确的并发数据问题，一般不要手动改隔离级别——改了可能和数据库实际能力不符。

## 10.4 回滚规则：默认只回滚 RuntimeException

Spring 的默认策略：**只有未检查异常（RuntimeException 及其子类）和 Error 才触发回滚；受检异常（Exception 但不继承 RuntimeException）不回滚。**

codegen-server 大量使用 `@Transactional(rollbackFor = Exception.class)`，正是为纠正这个默认行为——让所有 `Exception`（包括受检异常）都触发回滚，避免「业务抛了受检异常、数据却已提交一半」的诡异状态。对比两种写法：

```java
// 默认：只有 RuntimeException 回滚，抛出 IOException 不会回滚——危险
@Transactional
public void importFile() throws IOException { ... }

// 显式：所有 Exception 都回滚——更稳妥
@Transactional(rollbackFor = Exception.class)
public void importFile() throws IOException { ... }
```

⚠️ 踩坑提示：如果你在事务方法里 `throw new Exception("...")`（受检）却只写了 `@Transactional`，Spring **不会回滚**，数据会被提交。生产代码一律建议显式写 `rollbackFor = Exception.class`，把意图说清楚。

## 10.5 常见失效场景

### 10.5.1 自调用（类内部方法互调）

```java
// 通用示例：事务失效
@Service
public class OrderService {
    public void outer() {
        inner();          // 直接调用，绕过了代理，@Transactional 不生效！
    }
    @Transactional
    public void inner() { ... }
}
```

`outer()` 内部 `this.inner()` 是对象自身调用，不经过 Spring 代理，事务切面不会织入。解决：把 `inner` 抽到另一个 `@Service`，或通过注入自身的代理（`@Autowired OrderService self`）调用。

### 10.5.2 异常被 catch 吞掉

```java
// 通用示例：事务失效——异常没抛出去，代理无从感知
@Transactional
public void transfer() {
    try {
        deduct();
        add();
    } catch (Exception e) {
        log.error("失败", e);   // 只记日志，没 rethrow → 不会回滚
    }
}
```

### 10.5.3 非 public 方法

`@Transactional` 默认只对 `public` 方法生效（基于 CGLIB/接口代理的限制）。写在 `private`/`protected`/`package` 方法上要么不生效，要么不同代理方式表现不一，不要依赖。

### 10.5.4 多线程

事务绑定在数据库连接上，而连接绑定在当前线程（ThreadLocal）。新开线程执行 DB 操作拿的是另一条连接、另一个事务，父事务无法覆盖它。

## 10.6 真实工程权衡：故意「不」包事务的地方

不是所有写操作都该包事务。codegen-server 的「写盘」(`writeToDisk`，`com.codegen.service.impl.GenCodeServiceImpl`) 就是一个**刻意不包事务**的真实案例——源码里整段方法**没有任何 `@Transactional`**。为什么？

```java
// 来源：com.codegen.service.impl.GenCodeServiceImpl（节选，方法无 @Transactional）
@Override
public List<GenWriteVO> writeToDisk(GenWriteDTO dto, String batchNo) {
    // ... 逐表、逐文件写磁盘（Files.writeString）+ 写台账（genOutputMapper.insert）...
    // 多张表、几十个文件，每个文件独立处理，单文件失败只记 ERROR 不中断其余
    for (GenTable table : loadTablesInOrder(ids)) {
        results.addAll(writeTable(table, ...));   // 文件落盘 + 台账
    }
    deliverSqlForProjects(idsByProject, batchNo);  // SQL 交付失败只记录不抛出
    return results;
}
```

它不包事务的设计理由有三层：

1. **写盘是「文件 IO + 数据库」的混合操作**，数据库事务保护不了「已写出的磁盘文件」。即使 DB 回滚，磁盘上的 `.java`/`.vue` 已经落地，做不到「整批原子」。强行包事务反而制造「DB 回滚了但文件没回滚」的不一致。
2. **需要「逐步可观测」**。写盘按表、按文件逐个进行，单个文件失败应当只标记该文件 `ERROR` 并继续，而不是让整个批次滚掉——用户能拿到「哪些文件成功了、哪些失败了」的明细，方便重试。
3. **台账失败不应阻断写盘**。源码注释明确：「文件已经落盘，因为台账失败去回滚它反而更糟」。所以 `recordOutput` 里 `catch` 只 `log.warn + 计数`，把 `ledgerErrors` 放进响应体/响应头暴露给调用方，而非抛出异常。

它甚至用 `ThreadLocal` 做请求级计数（因为 Service 是单例，计数不能跨请求串），进一步说明「这类非事务场景要靠自己管理状态」。这正是真实工程的权衡：**事务边界 = 真正能原子回滚的边界**，磁盘写、跨系统调用、批量可中断操作都不适合塞进一个 `@Transactional`。

⚠️ 踩坑提示：不要「无脑给所有写方法加 `@Transactional`」。如果方法里混合了「本地磁盘写 / 远程 HTTP 调用 / 消息发送」，事务只能回滚其中数据库那一段，其余副作用无法撤销，反而让你误以为「已经安全回滚」。先想清楚「这个方法的原子边界到底是什么」，再决定事务范围。

## 本章小结

- `@Transactional` 底层是 AOP 代理，只有经代理的外部调用才生效。
- 多步 DB 写操作必须包事务（如 codegen-server 的 `syncColumns`）；强烈建议写 `rollbackFor = Exception.class`，因为默认只对 `RuntimeException` 回滚。
- 传播行为 `REQUIRED`（默认）/`REQUIRES_NEW`（独立事务）最常用；隔离级别默认沿用数据库，一般不改。
- 四大失效场景：自调用、异常被 catch、非 public 方法、多线程。
- 真实工程会**故意不包事务**：涉及磁盘写盘、远程调用、需逐步可观测的批量操作（如 codegen-server 的 `writeToDisk`）不适合塞进单一事务，应让各环节可独立观测与重试。
