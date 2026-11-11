# 第 8 章 参数校验与 AOP：让边界自动守规矩

本章目标：掌握 JSR-380（Bean Validation）在 Spring Boot 3 中的用法——`@Valid`/`@Validated`、常用约束注解、分组校验与自定义注解；并理解 AOP 的核心概念，结合 codegen-server 真实使用的 MyBatis-Plus 元对象填充器，看清「审计字段自动填充」这类横切关注点如何用最少的代码落地。

## 8.1 JSR-380 校验入门

Spring Boot 3 内置 `spring-boot-starter-validation`，它实现 Jakarta Bean Validation（JSR-380），约束注解来自 `jakarta.validation.constraints` 包（注意是 `jakarta` 而非旧版的 `javax`）。常用注解：

| 注解 | 作用 |
|------|------|
| `@NotNull` | 不能为 null |
| `@NotBlank` | 字符串非 null 且去空白后非空 |
| `@NotEmpty` | 集合/数组/字符串非空 |
| `@Size(min,max)` | 长度/元素数范围 |
| `@Min/@Max` | 数值上下限 |
| `@Pattern(regexp)` | 正则匹配 |
| `@Email` | 邮箱格式 |
| `@Past/@Future` | 日期在过去/未来 |

### 8.1.1 在 DTO 上声明约束

codegen-server 的 `GenScaffoldDTO`（`com.codegen.dto.GenScaffoldDTO`）是典型的真实示例——它给每个入参字段标了 `@NotBlank`/`@Pattern` 并带中文 `message`：

```java
// 来源：com.codegen.dto.GenScaffoldDTO（节选）
@Data
@Schema(description = "一键建工程入参")
public class GenScaffoldDTO {

    @NotBlank(message = "工程名不能为空")
    private String projectName;

    @NotBlank(message = "包名不能为空")
    @Pattern(regexp = "^[A-Za-z][A-Za-z0-9_.]*$", message = "根包名必须是合法 Java 包名")
    private String rootPackage;

    @Pattern(regexp = "^[A-Za-z0-9_.-]+$", message = "模块目录名只能含字母、数字、下划线、点与横线")
    private String backendModule;
    // ... 其余字段
}
```

### 8.1.2 在 Controller 触发校验

光声明还不够，必须在 **入口** 用 `@Valid`（或 `@Validated`）触发。codegen-server 在 `GenController` 里这样用：

```java
// 来源：com.codegen.controller.GenController（节选）
@PostMapping("/scaffold")
public Result<GenScaffoldVO> scaffold(@Valid @RequestBody GenScaffoldDTO dto) {
    return Result.ok(genScaffoldService.scaffold(dto));
}

@PostMapping("/db/execute-ddl")
public Result<GenDdlExecuteVO> executeDdl(@Valid @RequestBody GenDdlExecuteDTO dto) {
    return Result.ok(genDdlService.execute(dto));
}
```

`@Valid` 作用在 `@RequestBody` 参数上，校验失败会抛出 `MethodArgumentNotValidException`——这个异常在第 7 章讲 `GlobalExceptionHandler` 时已专门映射成 `Result.fail(400, 字段:信息)`，所以前端拿到的是统一格式的错误提示，而不是一堆堆栈。

另一个真实示例 `GenDdlExecuteDTO`（`com.codegen.dto.GenDdlExecuteDTO`）只给 `ddl` 加了 `@NotBlank`，其余字段留空即可，体现「按需校验」：

```java
// 来源：com.codegen.dto.GenDdlExecuteDTO（节选）
@Data
public class GenDdlExecuteDTO {
    @NotBlank(message = "DDL 不能为空")
    private String ddl;
    private String schema;            // 可选，缺省时从 DDL 推断
    private Boolean autoImport = Boolean.TRUE;
    private Boolean allowDestructive = Boolean.FALSE;
}
```

### 8.1.3 @Valid 与 @Validated 的区别

- `@Valid`：标准 JSR 注解，支持**嵌套校验**（对象里的对象继续校验）。
- `@Validated`：Spring 扩展注解，**支持分组校验**（见 8.2），但不支持标注在字段上做嵌套级联。

实践建议：常规入参校验用 `@Valid`；需要分组（同一 DTO 在不同接口下约束不同）时用 `@Validated` 标在类或方法上。

## 8.2 分组校验

同一个 DTO 在「新增」和「修改」时约束常常不同：新增时 `id` 必须为 null，修改时 `id` 必须非空。分组校验通过「约束注解的 `groups` 属性 + `@Validated(分组.class)`」实现。

> 以下为通用示例（codegen-server 当前未显式使用分组，故按标准写法给出）。

```java
// 通用示例：分组接口
public interface AddGroup {}
public interface UpdateGroup {}

// 通用示例：DTO 上按组声明
@Data
public class UserDTO {
    @Null(groups = AddGroup.class, message = "新增时 id 必须为空")
    @NotNull(groups = UpdateGroup.class, message = "修改时 id 不能为空")
    private Long id;

    @NotBlank(groups = {AddGroup.class, UpdateGroup.class})
    private String username;
}

// 通用示例：Controller 按组触发
@PostMapping("/user")
public Result<Void> add(@Validated(AddGroup.class) @RequestBody UserDTO dto) { ... }

@PutMapping("/user")
public Result<Void> update(@Validated(UpdateGroup.class) @RequestBody UserDTO dto) { ... }
```

⚠️ 踩坑提示：分组校验下，**未指定分组的约束注解默认不参与校验**。也就是说，一旦你给某个注解加了 `groups`，它就只在对应分组生效；其余没分组的字段在该次校验中会被「放行」。要么所有约束都规划分组，要么把公共约束放进一个「默认组」并显式列入。

## 8.3 自定义校验注解

当内置注解不够用时（如「枚举值必须是约定的几个之一」「两个字段至少填一个」），可自定义约束注解。标准四步：

1. 定义注解，加 `@Constraint(validatedBy = ...)` 指向校验器；
2. 实现 `ConstraintValidator<A, T>` 写校验逻辑；
3. 在 DTO 字段上使用；
4. 校验失败信息通过第 7 章的全局异常处理器统一返回。

> 以下为通用示例（codegen-server 未自定义校验注解，故给出标准写法）。

```java
// 通用示例：自定义注解，约束字符串必须是给定枚举值之一
@Target({ElementType.FIELD})
@Retention(RetentionPolicy.RUNTIME)
@Constraint(validatedBy = EnumValueValidator.class)
public @interface EnumValue {
    String message() default "取值不合法";
    Class<?>[] groups() default {};
    Class<? extends Payload>[] payload() default {};
    String[] values();   // 允许的合法值集合
}

// 通用示例：校验器实现
public class EnumValueValidator implements ConstraintValidator<EnumValue, String> {
    private Set<String> allowed;
    @Override
    public void initialize(EnumValue ann) {
        allowed = Set.of(ann.values());
    }
    @Override
    public boolean isValid(String value, ConstraintValidatorContext ctx) {
        return value == null || allowed.contains(value);  // null 放行，由 @NotNull 管
    }
}
```

## 8.4 AOP 概念与核心注解

**AOP（Aspect-Oriented Programming，面向切面编程）** 用来把「横切关注点」——即散落在很多业务方法里、但与核心逻辑无关的通用行为（日志、鉴权、事务、审计填充）——抽出来集中管理。

Spring AOP 基于动态代理，关键术语：

- **Join Point（连接点）**：程序执行的点，如方法调用。
- **Pointcut（切点）**：用表达式筛出「要织入的地方」，如「所有 service 包下的 public 方法」。
- **Advice（通知）**：在切点处执行的逻辑，常用：
  - `@Before`：方法执行前。
  - `@After`：方法执行后（无论成败）。
  - `@AfterReturning`：正常返回后。
  - `@AfterThrowing`：抛异常后。
  - `@Around`：包裹整个方法，能控制是否执行、改写入参/返回值（最强大）。
- **Aspect（切面）**：切点 + 通知的组合，本身是一个 `@Component`。

启用 AOP 只需引入 `spring-boot-starter-aop`（codegen-server 的 `pom.xml` 第 64–67 行已引入，并注释说明它顺带支撑操作日志切面）：

```xml
<!-- 来源：pom.xml（节选） -->
<!-- 操作日志切面依赖 AOP；spring-boot-starter-web 不带 aspectjweaver -->
<dependency>
    <groupId>org.springframework.boot</groupId>
    <artifactId>spring-boot-starter-aop</artifactId>
</dependency>
```

> 以下为通用示例：一个统计方法耗时的切面，展示 `@Aspect + @Around` 的标准写法。

```java
// 通用示例：方法耗时切面
@Slf4j
@Aspect
@Component
public class CostTimeAspect {

    // 切点：com.codegen.service 包下所有方法
    @Pointcut("execution(* com.codegen.service..*(..))")
    public void serviceLayer() {}

    @Around("serviceLayer()")
    public Object around(ProceedingJoinPoint pjp) throws Throwable {
        long start = System.currentTimeMillis();
        try {
            return pjp.proceed();                 // 继续执行原方法
        } finally {
            long cost = System.currentTimeMillis() - start;
            log.info("{}.{} 耗时 {}ms",
                    pjp.getTarget().getClass().getSimpleName(),
                    pjp.getSignature().getName(), cost);
        }
    }
}
```

## 8.5 真实案例：审计字段自动填充

codegen-server 用 MyBatis-Plus 的 `MetaObjectHandler` 做审计字段自动填充——这虽不是手写 `@Aspect`，但本质是同一个思想：**把「每次插入/更新都要写 createTime/updateBy」这件事从业务代码里剥离，由框架在持久化前统一注入**。

源码 `com.codegen.common.handler.AuditMetaObjectHandler`：

```java
// 来源：com.codegen.common.handler.AuditMetaObjectHandler（节选）
@Component
public class AuditMetaObjectHandler implements MetaObjectHandler {

    @Override
    public void insertFill(MetaObject metaObject) {
        LocalDateTime now = LocalDateTime.now();
        this.strictInsertFill(metaObject, "createTime", LocalDateTime.class, now);
        this.strictInsertFill(metaObject, "updateTime", LocalDateTime.class, now);
        Long userId = UserContext.getUserId();      // 从登录上下文取当前用户
        if (userId != null) {
            this.strictInsertFill(metaObject, "createBy", Long.class, userId);
            this.strictInsertFill(metaObject, "updateBy", Long.class, userId);
        }
    }

    @Override
    public void updateFill(MetaObject metaObject) {
        this.strictUpdateFill(metaObject, "updateTime", LocalDateTime.class, LocalDateTime.now());
        Long userId = UserContext.getUserId();
        if (userId != null) {
            this.strictUpdateFill(metaObject, "updateBy", Long.class, userId);
        }
    }
}
```

要让填充生效，实体字段必须用 `@TableField(fill = ...)` 声明填充时机（见第 9 章）。codegen-server 的基类 `BaseEntity`（`com.codegen.common.entity.BaseEntity`）已统一声明：

```java
// 来源：com.codegen.common.entity.BaseEntity（节选）
@TableField(fill = FieldFill.INSERT)
private LocalDateTime createTime;

@TableField(fill = FieldFill.INSERT_UPDATE)
private LocalDateTime updateTime;

private Long createBy;     // 创建人（由填充器写入）
private Long updateBy;     // 修改人
```

这里 `UserContext`（`com.codegen.common.context.UserContext`）是一个 `ThreadLocal` 封装的登录用户上下文，由鉴权过滤器写入、业务代码只读——这也正是 AOP/拦截器与业务解耦的体现：填充器只管「从上下文取值」，至于上下文何时被写入，它并不关心。

设计要点：
1. **创建人允许为 null**：未登录场景（如系统初始化脚本）不强行写 userId，避免空指针。
2. **时间字段用 `strictInsertFill`**：MyBatis-Plus 3.5+ 推荐用 strict 系方法，能感知字段类型，避免把 String 填进 LocalDateTime 等类型错配。
3. **与 DB 默认值互补**：`BaseEntity` 注释说明数据库列本身有 `DEFAULT CURRENT_TIMESTAMP` 兜底，填充器是「显式写回实体、保证回写一致性」，两者不冲突。

⚠️ 踩坑提示：自动填充**只对 `fill` 属性匹配的操作生效**。如果你用 `updateById` 但字段只标了 `FieldFill.INSERT`，更新时该字段不会被碰；反之标了 `INSERT_UPDATE` 的字段，每次更新都会被重写。codegen-server 的 `GenTable.projectId` 还特意用 `@TableField(updateStrategy = FieldStrategy.IGNORED)` 来允许写 `null`（否则「清空系统归属」会静默失败），这是填充/更新策略的另一个易错点。

## 本章小结

- JSR-380 校验靠 `spring-boot-starter-validation`，约束注解来自 `jakarta.validation.constraints`。
- 在 DTO 字段声明约束，在 Controller 用 `@Valid`（嵌套）或 `@Validated`（分组）触发；校验失败由第 7 章的全局异常处理器统一转成 `Result.fail(400)`。
- 分组校验解决「同一 DTO 不同场景约束不同」，但注意未分组的约束默认不生效。
- 自定义校验注解按「注解 + ConstraintValidator」四步实现。
- AOP 用 `@Aspect/@Pointcut/@Before/@Around` 抽离横切逻辑；codegen-server 的 `AuditMetaObjectHandler` 是「审计字段自动填充」的真实落地，与 `UserContext` 配合实现「业务代码零侵入」地写入创建人/时间。
