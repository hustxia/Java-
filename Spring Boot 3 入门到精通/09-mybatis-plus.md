# 第 9 章 MyBatis-Plus：少写 SQL 的持久层方案

本章目标：掌握在 Spring Boot 3 中集成 MyBatis-Plus（使用专用于 Boot 3 的 starter），理解分页插件、逻辑删除、自动填充、代码生成器与 `BaseMapper` 的基础 CRUD，并结合 codegen-server 的真实配置与实体注解讲透生产用法。

## 9.1 集成：使用 spring-boot3 starter

MyBatis-Plus 针对 Spring Boot 3 提供了独立的 starter `mybatis-plus-spring-boot3-starter`（注意**不是**普通的 `mybatis-plus-boot-starter`，后者面向 Boot 2，混用会在 Boot 3 下报 `javax` 相关 NoClassDefFound）。codegen-server 的 `pom.xml`（第 58–61 行）这样引入：

```xml
<!-- 来源：pom.xml（节选） -->
<dependency>
    <groupId>com.baomidou</groupId>
    <artifactId>mybatis-plus-spring-boot3-starter</artifactId>
    <version>${mybatis-plus.version}</version>   <!-- 3.5.5 -->
</dependency>
```

⚠️ 踩坑提示：Spring Boot 3 + MyBatis-Plus 必须用 `mybatis-plus-spring-boot3-starter`。用错 starter 会在启动时因 `javax.persistence`/`javax.servlet` 找不到而失败。MyBatis-Plus 从 3.5.4 起才正式支持 Boot 3 的 Jakarta 命名空间。

## 9.2 配置：分页、逻辑删除、驼峰映射

codegen-server 的 `application.yml` 里 `mybatis-plus` 段（第 32–42 行）配置了三件关键事：

```yaml
# 来源：application.yml（节选）
mybatis-plus:
  mapper-locations: classpath*:/mapper/**/*.xml
  type-aliases-package: com.codegen.entity
  configuration:
    map-underscore-to-camel-case: true   # 下划线列名自动转驼峰属性
  global-config:
    db-config:
      id-type: auto                      # 主键自增
      logic-delete-field: deleted        # 逻辑删除字段名
      logic-delete-value: 1              # 已删除标记
      logic-not-delete-value: 0          # 未删除标记
```

- `map-underscore-to-camel-case: true`：数据库 `create_time` 自动映射到实体 `createTime`，无需每个字段写 `@TableField("create_time")`。
- `logic-delete-field`：全局指定逻辑删除字段。执行 `deleteById` 时实际变成 `UPDATE ... SET deleted=1`，查询自动加 `deleted=0` 条件——业务代码零感知。

### 9.2.1 分页插件必须注册

MyBatis-Plus 的分页靠拦截器实现。codegen-server 的 `MybatisPlusConfig`（`com.codegen.config.MybatisPlusConfig`）注册了拦截器链：

```java
// 来源：com.codegen.config.MybatisPlusConfig
@Configuration
public class MybatisPlusConfig {

    @Bean
    public MybatisPlusInterceptor mybatisPlusInterceptor() {
        MybatisPlusInterceptor interceptor = new MybatisPlusInterceptor();
        // ① 数据权限拦截器：按登录用户范围改写 SQL
        interceptor.addInnerInterceptor(new DataScopeInterceptor());
        // ② 分页拦截器：缺了它 Page 查询不执行 count，total 恒为 0
        interceptor.addInnerInterceptor(new PaginationInnerInterceptor(DbType.MYSQL));
        return interceptor;
    }
}
```

⚠️ 踩坑提示：分页拦截器**不注册就分页**是经典静默故障——`page.getTotal()` 永远为 0、列表却正常返回，前端分页条直接「崩」成第一页。顺序上数据权限拦截器要在分页之前（先缩小可见数据再分页，否则不该看的行会算进总数）。codegen-server 在类注释里明确写了这个顺序要求。

## 9.3 实体注解：@TableName / @TableField / @TableLogic

实体类通过注解与表结构绑定。codegen-server 的 `GenTable`（`com.codegen.entity.GenTable`）与基类 `BaseEntity` 给出了完整范式。

类级别 `@TableName("gen_table")` 指定表名；主键用 `@TableId(type = IdType.ASSIGN_ID)`（雪花算法，18–19 位 Long，配合 `@JsonSerialize(ToStringSerializer.class)` 避免前端 JS 精度丢失）：

```java
// 来源：com.codegen.entity.BaseEntity（节选）
@Data
public abstract class BaseEntity implements Serializable {

    @TableId(type = IdType.ASSIGN_ID)               // 雪花 ID，非自增
    @JsonSerialize(using = ToStringSerializer.class) // 字符串下发，防 JS 精度丢失
    private Long id;

    @TableField(fill = FieldFill.INSERT)            // 见 8.5 自动填充
    private LocalDateTime createTime;

    @TableField(fill = FieldFill.INSERT_UPDATE)
    private LocalDateTime updateTime;

    @TableLogic                                   // 逻辑删除字段
    private Integer deleted;
}
```

`GenTable` 继承 `BaseEntity` 并标注表名，同时展示了一处「更新策略」实战（第 241 行）：

```java
// 来源：com.codegen.entity.GenTable（节选）
@Data
@EqualsAndHashCode(callSuper = true)
@TableName("gen_table")
public class GenTable extends BaseEntity {

    private String tableName;
    private String className;
    // ... 大量生成开关 genEntity/genMapper/...

    /**
     * 所属系统。更新策略显式设为 IGNORED：MP 默认 NOT_NULL，
     * null 字段不进 UPDATE，用户在弹窗里清空系统想「解绑」时会静默失败。
     */
    @TableField(updateStrategy = FieldStrategy.IGNORED)
    private Long projectId;
}
```

⚠️ 踩坑提示：MyBatis-Plus 的字段更新策略默认是 `NOT_NULL`（值为 null 的字段不拼进 UPDATE）。想「主动置空」某字段（如解绑系统、清空备注）必须设 `FieldStrategy.IGNORED` 或用 `updateStrategy`，否则前台清空操作会静默无效。codegen-server 这个字段注释就是踩过坑后的经验。

## 9.4 BaseMapper：基础 CRUD 零 SQL

任何 Mapper 继承 `BaseMapper<T>` 即可获得 `insert`/`deleteById`/`updateById`/`selectById`/`selectList` 等方法，无需写 XML。codegen-server 大量使用，例如 `GenCodeServiceImpl` 中：

```java
// 来源：com.codegen.service.impl.GenCodeServiceImpl（节选）
@Autowired
private GenOutputMapper genOutputMapper;   // 继承 BaseMapper<GenOutput>

// 写台账：一行 insert 搞定
GenOutput row = new GenOutput();
row.setBatchNo(batchNo);
row.setTableName(table.getTableName());
// ... 设字段
genOutputMapper.insert(row);               // 无需写 SQL

// 批量按 id 取表，一次往返
Map<Long, GenTable> byId = new HashMap<>();
for (GenTable table : genTableMapper.selectBatchIds(ids)) {
    byId.put(table.getId(), table);
}
```

### 9.4.1 分页查询

配合 `Page<T>` 与分页拦截器，分页是几行代码的事。codegen-server 的 `GenController` 暴露的分页接口返回 `IPage<GenTableVO>`：

```java
// 来源：GenController.java（节选）
@PostMapping("/table/page")
public Result<IPage<GenTableVO>> page(@RequestBody GenTablePageDTO dto) {
    return Result.ok(genTableService.pageList(dto));   // 内部构造 Page 并查询
}
```

分页在 Service 内的典型写法（通用示例，展示 Page 用法）：

```java
// 通用示例：分页 + 条件构造器
public IPage<GenTable> pageList(int current, int size, String keyword) {
    Page<GenTable> page = new Page<>(current, size);   // 第几页，每页几条
    LambdaQueryWrapper<GenTable> w = new LambdaQueryWrapper<>();
    if (keyword != null) {
        w.like(GenTable::getTableName, keyword);
    }
    return genTableMapper.selectPage(page, w);         // total/records 自动填充
}
```

`LambdaQueryWrapper` 用方法引用写条件（`GenTable::getTableName`），编译期检查字段名，比硬编码字符串更安全。codegen-server 中 `renderTables` 方法就用它一次 `IN (ids)` 查出所有列，避免逐表查库的 N+1。

## 9.5 代码生成器

MyBatis-Plus 自带 `AutoGenerator`，可依据数据库表反向生成 Entity/Mapper/Service/Controller 模板代码——这正是 codegen-server 这类「代码生成器平台」的底层能力来源之一。典型用法（通用示例）：

```java
// 通用示例：AutoGenerator 配置骨架
AutoGenerator generator = new AutoGenerator();
generator.setDataSource(new DataSourceConfig.Builder(url, username, password).build());
generator.setGlobal(new GlobalConfig.Builder()
        .outputDir("./src/main/java").author("codegen").build());
generator.setStrategy(new StrategyConfig.Builder()
        .addInclude("gen_table")           // 指定表
        .entityBuilder().enableLombok()    // 实体启用 Lombok
        .build());
generator.execute();
```

> 说明：codegen-server 本身是一个**应用层**的代码生成器（用 Freemarker 模板渲染任意目标工程代码），其内部表配置仍走 `BaseMapper` 管理，并不直接依赖 `AutoGenerator` 运行期生成自身代码。此处给出标准写法供读者了解 MP 自带的逆向生成能力。

## 9.6 自动填充与逻辑删除的协作

本章与前一章是连贯的：`BaseEntity` 里 `createTime/updateTime` 的 `@TableField(fill=...)` 由第 8 章的 `AuditMetaObjectHandler` 在插入/更新时自动注入；`deleted` 的 `@TableLogic` 由本章的分页/查询拦截器自动拼接条件。两者都属于「把通用持久化逻辑从业务方法里抽掉」，让读者体会 ORM 框架的价值——**业务代码只关心领域模型，脏活交给框架**。

⚠️ 踩坑提示：逻辑删除与自动填充都依赖字段注解正确。若 `@TableLogic` 字段类型不是数值/布尔，或全局 `logic-delete-field` 与实体字段名不一致，删除会变成**物理删除**（真删库），风险极高。上线前务必用一条测试数据验证 `deleteById` 实际执行的是 UPDATE 还是 DELETE。

## 本章小结

- Spring Boot 3 必须用 `mybatis-plus-spring-boot3-starter`，版本 ≥ 3.5.4。
- `application.yml` 里配置驼峰映射、逻辑删除字段、id 策略；分页拦截器（`PaginationInnerInterceptor`）必须注册，否则分页 total 恒为 0。
- 实体用 `@TableName`/`@TableId`/`@TableField(fill)`/`@TableLogic` 绑定表结构；`FieldStrategy.IGNORED` 解决「主动置空」静默失败。
- `BaseMapper<T>` 提供零 SQL 的 CRUD，`Page<T>` + `LambdaQueryWrapper` 实现类型安全的分页与条件查询。
- 自动填充（第 8 章）与逻辑删除（本章）共同体现「持久化通用逻辑框架化」的思想。
