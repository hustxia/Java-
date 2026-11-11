# 第 7 章 Web 基础：构建统一的 REST 接口层

本章目标：掌握 Spring MVC 在 Spring Boot 3 中的核心用法——`@RestController`、各类请求映射注解、三种参数绑定方式，并基于 codegen-server 的真实代码，理解生产项目如何通过「统一返回体 + 全局异常处理」让前后端契约保持一致。

## 7.1 @RestController 与请求映射

Spring Boot 3 使用 Jakarta EE 9+ 命名空间（`jakarta.servlet`、`jakarta.validation`），这是从 Spring Boot 2（`javax.*`）升级时最容易踩的坑之一。控制器只需 `@RestController` 一个注解，它等价于 `@Controller + @ResponseBody`，意味着每个方法的返回值直接序列化为 HTTP 响应体（默认 JSON），而不是去解析视图名。

类级别用 `@RequestMapping("/gen")` 统一定义路径前缀，方法级别再用具体动词注解拆细。Spring MVC 提供了语义化的快捷注解：

| 注解 | HTTP 方法 | 典型场景 |
|------|-----------|----------|
| `@GetMapping` | GET | 查询、详情、导出 |
| `@PostMapping` | POST | 新增、复杂查询体、导入 |
| `@PutMapping` | PUT | 整体修改 |
| `@DeleteMapping` | DELETE | 删除 |
| `@PatchMapping` | PATCH | 局部更新 |

下面是 codegen-server 的真实控制器片段（`src/main/java/com/codegen/controller/GenController.java`），它把上述注解组合得相当标准：

```java
// 来源：com.codegen.controller.GenController（节选）
@RestController
@RequestMapping("/gen")
public class GenController {

    // GET + 路径变量：表配置详情
    @GetMapping("/table/{id}")
    public Result<GenTableVO> detail(@PathVariable("id") Long id) {
        return Result.ok(genTableService.detail(id));
    }

    // POST + 请求体：保存表配置（导入）
    @PostMapping("/table")
    public Result<Long> save(@RequestBody GenTableSaveDTO dto) {
        return Result.ok(genTableService.saveConfig(dto));
    }

    // PUT + 请求体：整体修改
    @PutMapping("/table")
    public Result<Void> update(@RequestBody GenTableSaveDTO dto) {
        genTableService.updateConfig(dto);
        return Result.ok();
    }

    // DELETE + 路径变量：删除
    @DeleteMapping("/table/{id}")
    public Result<Void> delete(@PathVariable("id") Long id) {
        genTableService.deleteConfig(id);
        return Result.ok();
    }
}
```

注意 `@PathVariable("id")` 显式写明了变量名。在 Spring Boot 3 中，方法参数名是通过编译期 `-parameters` 选项保留的——codegen-server 的 `pom.xml` 里有这样一段（第 124–131 行）：

```xml
<plugin>
    <groupId>org.apache.maven.plugins</groupId>
    <artifactId>maven-compiler-plugin</artifactId>
    <configuration>
        <!-- Spring MVC 靠参数名绑定 @RequestParam/@PathVariable；
             不显式声明会导致运行时 "Name for argument of type [X] not specified" 500 错误 -->
        <compilerArgs>
            <arg>-parameters</arg>
        </compilerArgs>
    </configuration>
</plugin>
```

⚠️ 踩坑提示：如果你的工程没有父 POM 继承 `spring-boot-starter-parent`，编译器默认**不会**保留参数名。此时要么在注解里显式写 `@PathVariable("id")`（像上面那样），要么加 `-parameters`。否则启动正常、一调接口就 500，且错误信息非常隐蔽。

## 7.2 三种参数绑定方式

### 7.2.1 @RequestParam——查询参数 / 表单字段

用于绑定 URL 查询串（`?name=xxx`）或表单字段。常用属性：

- `required`：默认 `true`，缺失即报错；可设 `false` 变成可选。
- `defaultValue`：提供默认值（设了默认值后 `required` 自动失效）。

```java
// 来源：GenController.java
@GetMapping("/api-catalog")
public Result<List<ApiCatalogItemVO>> apiCatalog(
        @RequestParam(required = false) Long tableId,       // 可选
        @RequestParam(required = false) String keyword) {
    return Result.ok(apiCatalogService.catalog(tableId, keyword));
}

@GetMapping("/output/batches")
public Result<List<GenOutputBatchVO>> outputBatches(
        @RequestParam(value = "limit", defaultValue = "20") int limit) {  // 带默认值
    return Result.ok(genOutputService.batchSummary(limit));
}
```

### 7.2.2 @PathVariable——路径变量

RESTful 风格把资源标识放进路径，如 `/table/{id}`。它比查询参数更具语义，也更适合作为资源的唯一寻址。codegen-server 大量使用这种写法（详情、删除、按 id 同步列等）。

```java
// 来源：GenController.java
@PostMapping("/table/{id}/sync-columns")
public Result<GenColumnSyncVO> syncColumns(@PathVariable("id") Long id,
                                           @RequestParam(value = "removeMissing", defaultValue = "false")
                                           boolean removeMissing) {
    return Result.ok(genTableService.syncColumns(id, removeMissing));
}
```

### 7.2.3 @RequestBody——请求体（JSON）

复杂入参（嵌套对象、数组）必须用 `@RequestBody` 接收，由 HttpMessageConverter 把 JSON 反序列化成 Java 对象。配合 Lombok 的 `@Data` 可以省去大量 getter/setter 样板代码。

```java
// 来源：GenController.java
@PostMapping("/table/page")
public Result<IPage<GenTableVO>> page(@RequestBody GenTablePageDTO dto) {
    return Result.ok(genTableService.pageList(dto));
}
```

三者组合时顺序无所谓，Spring 按类型与注解各自解析：路径变量归 `@PathVariable`，查询串归 `@RequestParam`，请求体归 `@RequestBody`。

## 7.3 统一返回体设计

如果每个接口都自由返回 `Map`、裸对象或字符串，前端无法用统一逻辑判断「成功还是失败」。生产项目几乎都会封装一个 `Result<T>`。codegen-server 的 `Result`（`com.codegen.common.result.Result`）是标准范本：

```java
// 来源：com.codegen.common.result.Result
@Data
public class Result<T> implements Serializable {
    private int code;        // 业务状态码：成功 200，参数错误 400……
    private String msg;      // 提示信息
    private T data;          // 业务数据，泛型

    public static <T> Result<T> ok(T data) {              // 成功且带数据
        return new Result<>(ResultCode.SUCCESS.getCode(),
                           ResultCode.SUCCESS.getMsg(), data);
    }
    public static <T> Result<T> ok() {                    // 成功无数据（如删除）
        return new Result<>(ResultCode.SUCCESS.getCode(),
                           ResultCode.SUCCESS.getMsg(), null);
    }
    public static <T> Result<T> fail(int code, String msg) { // 失败
        return new Result<>(code, msg, null);
    }
}
```

状态码与文案集中在枚举 `ResultCode`（`com.codegen.common.result.ResultCode`）里，避免散落字符串：

```java
// 来源：com.codegen.common.result.ResultCode
public enum ResultCode {
    SUCCESS(200, "success"),
    FAIL(500, "服务异常"),
    PARAM_ERROR(400, "参数错误"),
    UNAUTHORIZED(401, "未授权"),
    FORBIDDEN(403, "无权限"),
    NOT_FOUND(404, "资源不存在");
}
```

设计要点：
1. **泛型 `data`**：成功时携带任意业务对象（如 `Result<GenTableVO>`、`Result<List<...>>`），失败时 `data` 为 `null`，结构不塌缩。
2. **静态工厂方法**：`Result.ok(data)` / `Result.fail(...)` 让 Controller 的返回语句极简，无需 new。
3. **HTTP 状态码 ≠ 业务 code**：即使业务失败（`code=400`），HTTP 状态仍返回 200（响应体能正常解析）。需要区分时再引入 `ResponseEntity`（见 7.5）。

## 7.4 全局异常处理

异常不应散落在各 Controller 里 try-catch。Spring 3 用 `@RestControllerAdvice` + `@ExceptionHandler` 做全局兜底：`@RestControllerAdvice` 同时具备「切面织入所有 `@RestController`」和「返回 JSON」两层含义（等于 `@ControllerAdvice + @ResponseBody`）。

codegen-server 的 `GlobalExceptionHandler`（`com.codegen.common.exception.GlobalExceptionHandler`）是教科书级的范例。它至少做了三件重要的事：

**第一，把业务异常转成统一返回体。** 自定义 `BusinessException` 携带 `code` 与 `message`，处理器把它翻译成 `Result.fail`：

```java
// 来源：com.codegen.common.exception.GlobalExceptionHandler（节选）
@Slf4j
@RestControllerAdvice
public class GlobalExceptionHandler {

    // 业务异常：直接取出 code 和 message 透传给前端
    @ExceptionHandler(BusinessException.class)
    public Result<Void> handleBusinessException(BusinessException ex) {
        log.warn("业务异常: code={}, msg={}", ex.getCode(), ex.getMessage());
        return Result.fail(ex.getCode(), ex.getMessage());
    }
}
```

`BusinessException` 本身很简单（`com.codegen.common.exception.BusinessException`），继承 `RuntimeException` 所以无需在方法签名声明 throws：

```java
// 来源：com.codegen.common.exception.BusinessException
@Getter
public class BusinessException extends RuntimeException {
    private final int code;
    public BusinessException(ResultCode resultCode) {
        super(resultCode.getMsg());
        this.code = resultCode.getCode();
    }
    public BusinessException(int code, String message) {
        super(message);
        this.code = code;
    }
}
```

Controller 里只需 `throw new BusinessException(400, "请先勾选要生成的表")` 即可，无需关心如何拼返回体。

**第二，参数校验异常单独映射。** 校验失败（`MethodArgumentNotValidException` 等）本质也是「参数错误」，应当返回 `PARAM_ERROR(400)` 而不是被最后的 `Exception` 分支包成 `500 服务异常`。codegen-server 专门写了清晰注释说明为什么必须单独处理（见下方代码片段）：

```java
// 来源：GlobalExceptionHandler.java
@ExceptionHandler(MethodArgumentNotValidException.class)
public Result<Void> handleValidException(MethodArgumentNotValidException ex) {
    String msg = ex.getBindingResult().getFieldErrors().stream()
            .findFirst()
            .map(e -> e.getField() + ":" + e.getDefaultMessage())   // 字段名:错误信息
            .orElse(ResultCode.PARAM_ERROR.getMsg());
    log.warn("参数校验失败: {}", msg);
    return Result.fail(ResultCode.PARAM_ERROR.getCode(), msg);
}
```

它甚至把 `BindException`（表单绑定）、`ConstraintViolationException`（方法参数级校验）、`MissingServletRequestParameterException`（缺参）、`MethodArgumentTypeMismatchException`（类型不匹配）等都单独映射——这些「调用方用错」的异常若落到 `Exception` 兜底，会污染日志且掩盖真正的服务端 bug。

**第三，保留一个总兜底。** 任何未被前面捕获的异常统一记 error 日志并返回 `FAIL(500)`：

```java
// 来源：GlobalExceptionHandler.java
@ExceptionHandler(Exception.class)
public Result<Void> handleException(Exception ex) {
    log.error("系统异常", ex);            // 真正的系统异常才打完整堆栈
    return Result.fail(ResultCode.FAIL);
}
```

⚠️ 踩坑提示：参数类异常（缺参、类型错、校验不过）**必须**单独 `@ExceptionHandler` 映射。否则它们会一路滑到最后 `Exception.class` 分支，表现为「前端传错参数 → HTTP 200 + code:500 服务异常」，日志里刷出一整页堆栈，排查时根本分不清是调用方用错还是服务端 bug。codegen-server 在类注释里明确点出了这个坑（audit B-02）。

## 7.5 需要返回真实 HTTP 状态码时

有些场景响应体形状仍是 `Result`，但 HTTP 状态码要准确（如 404）。这时用 `ResponseEntity<Result<T>>` 包装：

```java
// 来源：GlobalExceptionHandler.java（节选）
@ExceptionHandler(NoResourceFoundException.class)
public ResponseEntity<Result<Void>> handleNoResource(NoResourceFoundException ex) {
    log.debug("资源不存在: {}", ex.getMessage());
    return ResponseEntity.status(HttpStatus.NOT_FOUND)        // 真实 404
            .body(Result.fail(ResultCode.NOT_FOUND));         // 但响应体仍是统一的 Result
}
```

codegen-server 还有一处「不走 Result、直接返回字节流」的例子：`/gen/download` 下载 ZIP。它是文件下载，必须用 `ResponseEntity<byte[]>` 设置 `Content-Type` 与 `Content-Disposition`，不能用 JSON 包裹。这说明「统一返回体」是规范而非铁律，文件流、SSE、重定向等场景要灵活绕过。

```java
// 来源：GenController.java（节选）
@PostMapping("/download")
public ResponseEntity<byte[]> download(@RequestBody GenDownloadDTO dto) {
    GenCodeService.GenZipResult result = genCodeService.generateZip(dto);
    HttpHeaders headers = new HttpHeaders();
    headers.setContentType(MediaType.APPLICATION_OCTET_STREAM);
    headers.set(HttpHeaders.CONTENT_DISPOSITION, "attachment; filename=gen_code.zip");
    return new ResponseEntity<>(result.bytes(), headers, HttpStatus.OK);
}
```

## 本章小结

- Spring Boot 3 基于 Jakarta 命名空间，`@RestController` 让返回值直接序列化为 JSON。
- `@GetMapping/@PostMapping/@PutMapping/@DeleteMapping` 是 `@RequestMapping` 的语义化快捷方式；`@PathVariable`、`@RequestParam`、`@RequestBody` 分别绑定路径变量、查询参数、请求体。
- 真实工程必须用「统一返回体 `Result<T>` + 状态码枚举 `ResultCode`」约束前后端契约。
- `@RestControllerAdvice + @ExceptionHandler` 实现全局异常兜底，业务异常 `BusinessException` 应转成统一返回；参数类异常务必单独映射，避免被包成 500。
- 文件下载等特例用 `ResponseEntity<byte[]>`，不必强套 JSON 返回体。
