# 第 11 章 轻量级鉴权：Spring Security 6 与 JWT

## 本章目标

读完本章你将能够：

- 说清 Spring Security 6 相对旧版的核心变化，以及为什么 codegen-server 选择「只引 crypto、不引完整 Security」。
- 用 `OncePerRequestFilter` 自己写一个鉴权过滤器，完成白名单放行、Bearer 解析与 SSE 长连接兜底。
- 用 jjwt 0.12.5 的 `Jwts.builder()/parser()` 新 API 签发与校验 token，并理解它与旧版 API 的区别。
- 用 `ThreadLocal` 实现线程级的 `UserContext`，在业务代码里无侵入地拿到当前登录用户。
- 意识到「出厂默认密钥」是生产环境的致命风险，并用环境变量覆盖它。

---

## 11.1 Spring Security 6 变化概览

Spring Boot 3 绑定的是 Spring Security 6（准确说是 6.2.x）。如果你是从 Spring Boot 2 / Security 5 升级过来，下面几点是最大的体感差异：

1. **`WebSecurityConfigurerAdapter` 被废弃移除**。不再需要继承它来配过滤器链，改为直接声明一个 `SecurityFilterChain` 类型的 `@Bean`。
2. **配置风格从 `antMatchers` 转向 `requestMatchers`**，`authorizeHttpRequests` 取代 `authorizeRequests`。
3. **默认开启 CSRF 防护的端点范围收窄**，并且默认使用「无状态」语义更适合前后端分离。
4. **`PasswordEncoder` 必须显式提供**，否则启动报错——这正是本章 `SecurityBeanConfig` 存在的意义。
5. **Lambda DSL 成为主流**，配置项以 `http -> { }` 形式书写，可读性更好。

完整 Security 的配置大致是声明一个 `SecurityFilterChain` Bean，在 `authorizeHttpRequests(...)` 里用 `requestMatchers(...).permitAll()` / `.authenticated()` 描述放行规则，并设置 `sessionCreationPolicy(STATELESS)` 表达「JWT 无状态」语义（**此为通用示例**，codegen-server 未使用完整 Security，下文会讲它为何选择自建方案）。

## 11.2 为什么只引 crypto，不引完整 Security

打开 codegen-server 的 `pom.xml`，你会看到鉴权相关只有三样东西：

```xml
<!-- 仅用 BCrypt，不启用完整 Spring Security -->
<dependency>
    <groupId>org.springframework.security</groupId>
    <artifactId>spring-security-crypto</artifactId>
</dependency>
<dependency>
    <groupId>io.jsonwebtoken</groupId>
    <artifactId>jjwt-api</artifactId>
    <version>${jjwt.version}</version>      <!-- 0.12.5 -->
</dependency>
<dependency>
    <groupId>io.jsonwebtoken</groupId>
    <artifactId>jjwt-impl</artifactId>
    <version>${jjwt.version}</version>
    <scope>runtime</scope>
</dependency>
```

（`pom.xml` 第 89–110 行）

注意这里只引了 **`spring-security-crypto`**，而**没有**引 `spring-boot-starter-security`。`spring-security-crypto` 只是 Spring Security 里关于「加密」的一个**独立模块**，它不带来任何过滤器、不接管请求、不自动配 `SecurityFilterChain`——它只提供 `BCryptPasswordEncoder`、`PasswordEncoder` 等加密工具类。

**为什么这么选？** 项目是一个单体服务，前面没有网关兜底，鉴权逻辑非常直白：除登录/健康等少数接口外，所有请求必须带合法 Bearer token。与其引入一整套 Security 的 `AuthenticationManager`、`UserDetailsService`、CSRF、session 体系，不如自己写一个 `Filter` 直接拿到 `HttpServletRequest` 处理，反而更贴合需求、依赖更轻、心智负担更小。

而 `BCryptPasswordEncoder` 仍然值得用——它是经过时间检验的「加盐哈希」实现，存库只存哈希、不存明文。配置如下（`SecurityBeanConfig.java` 全文）：

```java
@Configuration
public class SecurityBeanConfig {

    @Bean
    public BCryptPasswordEncoder passwordEncoder() {
        return new BCryptPasswordEncoder();
    }
}
```

---

## 11.3 AuthContextFilter：自建鉴权过滤器

codegen-server 的鉴权核心是 `AuthContextFilter`，它继承 `OncePerRequestFilter`——这是 Spring 提供的一个基类，保证「一次请求只过一次该过滤器」，避免转发(forward)场景下重复执行。

### 11.3.1 在过滤器链中的位置

```java
@Component
@Order(Ordered.HIGHEST_PRECEDENCE + 10)
public class AuthContextFilter extends OncePerRequestFilter {
```

（`AuthContextFilter.java` 第 36–38 行）

`@Order(Ordered.HIGHEST_PRECEDENCE + 10)` 让这个过滤器尽量靠前执行。**关键点**：因为项目没引完整 Security，Spring 不会注入那条庞大的 `SecurityFilterChain`，所以本过滤器在 Tomcat 的 `FilterChain` 里几乎是「第一个业务相关」的过滤器。它先于所有 `@Controller` 执行，因此能在进入 controller 之前决定「放行还是 401」。

### 11.3.2 白名单放行

```java
private static final List<String> WHITE_LIST = List.of(
        "/auth/login",          // 拿 token 前必须能访问
        "/actuator/health",     // 探活；匹配逻辑是 equals || startsWith(prefix + "/")
        "/v3/api-docs",         // 接口文档
        "/swagger-ui",
        "/swagger-resources",
        "/error"                // Spring 内部错误页
);
```

（`AuthContextFilter.java` 第 43–52 行）

白名单只放行「拿 token 之前必须能访问」的接口。其余业务接口一律要求 Bearer token，否则直接 401。匹配逻辑是 `equals || startsWith(prefix + "/")`，所以 `/actuator/health/liveness` 也会自动放行。

### 11.3.3 Bearer 解析与 SSE 兜底

```java
String authorization = request.getHeader("Authorization");
// V5.0：SSE（EventSource）无法自定义请求头，允许 access_token 查询参数兜底。
if (!StringUtils.hasText(authorization) || !authorization.startsWith(BEARER_PREFIX)) {
    String queryToken = request.getParameter("access_token");
    if (StringUtils.hasText(queryToken)) {
        authorization = BEARER_PREFIX + queryToken;   // 仅 header 缺失时生效
    }
}
boolean hasToken = StringUtils.hasText(authorization) && authorization.startsWith(BEARER_PREFIX);
```

（`AuthContextFilter.java` 第 75–82 行）

这里有个真实场景的坑：**SSE（Server-Sent Events）的 `EventSource` API 不允许自定义请求头**。前端用 `EventSource` 订阅服务端推送（比如代码生成进度）时，没法带 `Authorization` 头，所以这里允许用 `?access_token=xxx` 查询参数兜底。优先级仍然是 Authorization 头优先，仅当 header 缺失才读参数。

另外，CORS 预检 `OPTIONS` 请求不带 Authorization，必须直接放行，否则浏览器跨域调用会全部失败（见第 67–71 行）。

### 11.3.4 解析成功则填充上下文

```java
if (hasToken) {
    String token = authorization.substring(BEARER_PREFIX.length());
    Long userId;
    String username;
    try {
        userId = jwtUtil.userIdOf(token);
        username = jwtUtil.usernameOf(token);
    } catch (Exception e) {
        writeUnauthorized(response, "登录状态已失效，请重新登录");  // 过期/篡改/密钥变更
        return;
    }
    UserContext.setUserId(userId);
    UserContext.setUsername(username);
    loadAuthority(userId);              // 角色/权限范围从库里查（不写进 token）
    try {
        filterChain.doFilter(request, response);
    } finally {
        UserContext.clear();            // 关键：请求结束清掉 ThreadLocal，防止串号
    }
    return;
}
```

（`AuthContextFilter.java` 第 84–106 行）

注意 `finally { UserContext.clear(); }`：**请求处理完毕一定要清理 ThreadLocal**。因为 Tomcat 用线程池复用线程，不清的话下一个请求可能读到上一个用户的身份，造成严重的「串号」安全漏洞。

---

## 11.4 UserContext：线程级用户上下文

`UserContext` 是一组 `ThreadLocal`，由过滤器写入、业务代码只读。

```java
public class UserContext {
    private static final ThreadLocal<Long> USER_ID_HOLDER = new ThreadLocal<>();
    private static final ThreadLocal<String> USERNAME_HOLDER = new ThreadLocal<>();
    private static final ThreadLocal<List<String>> ROLES_HOLDER = new ThreadLocal<>();
    private static final ThreadLocal<String> DATA_SCOPE_HOLDER = new ThreadLocal<>();
    private static final ThreadLocal<Long> DEPT_ID_HOLDER = new ThreadLocal<>();

    public static void setUserId(Long userId) { USER_ID_HOLDER.set(userId); }
    public static Long getUserId() { return USER_ID_HOLDER.get(); }
    // ... 其余 getter/setter 类似 ...
    public static void clear() {           // 请求结束时整体清理
        USER_ID_HOLDER.remove();
        USERNAME_HOLDER.remove();
        ROLES_HOLDER.remove();
        DATA_SCOPE_HOLDER.remove();
        DEPT_ID_HOLDER.remove();
    }
}
```

（`UserContext.java` 第 14–93 行）

业务代码里想拿当前用户，直接 `UserContext.getUserId()` 即可，无需在每个接口参数里传 `HttpServletRequest`。它还携带 `roles` 与 `dataScope`（数据权限范围 `all/dept/self`），供数据权限拦截器改写 SQL 时使用。`getDataScope()` 在未显式设置时按角色推导——有 `admin`/`super_admin` 即 `all`，否则 `self`（最小权限兜底）。

⚠️ **踩坑提示**：`ThreadLocal` 只在「同一线程内」有效。如果你的业务代码把任务丢进 `@Async` 线程池或 `CompletableFuture` 异步执行，子线程**读不到**父线程的 `UserContext`！需要在异步方法调用前手动 `UserContext.setXxx(...)` 传递，或者用 `TransmittableThreadLocal`（阿里开源）跨线程传递。本项目 MonitorSampler 的定时任务就在独立调度线程里跑，因此根本不依赖 UserContext，而是直接读 Micrometer 全局指标——这也是一种设计上的规避。

---

## 11.5 JwtUtil 与 jjwt 0.12 API

codegen-server 用 `JwtUtil` 封装 jjwt 0.12.5 的签发与解析。

### 11.5.1 签发 token（新 API）

```java
public String generateToken(Long userId, String username) {
    Date now = new Date();
    Date expireAt = new Date(now.getTime() + expireHours * 3600_000L);
    return Jwts.builder()
            .claim("userId", userId)
            .claim("username", username)
            .issuedAt(now)
            .expiration(expireAt)
            .signWith(secretKey())      // 0.12 用 signWith(SecretKey)
            .compact();
}
```

（`JwtUtil.java` 第 47–57 行）

### 11.5.2 解析 token（新 API）

```java
public Claims parseToken(String token) {
    return Jwts.parser()
            .verifyWith(secretKey())    // 0.12 用 verifyWith，旧版是 setSigningKey
            .build()
            .parseSignedClaims(token)
            .getPayload();
}
```

（`JwtUtil.java` 第 62–68 行）

### 11.5.3 jjwt 0.12 与旧版的 API 区别

| 能力 | jjwt 0.11 及更早 | jjwt 0.12.5（本项目） |
|------|------------------|------------------------|
| 构建器 | `Jwts.builder()` | `Jwts.builder()`（基本一致） |
| 设置签名 | `signWith(key, SignatureAlgorithm.HS256)` | `signWith(SecretKey)`（算法从 key 推断） |
| 解析器 | `Jwts.parser().setSigningKey(key).parseClaimsJws(t).getBody()` | `Jwts.parser().verifyWith(key).build().parseSignedClaims(t).getPayload()` |
| Key 构造 | `Keys.hmacShaKeyFor(...)` | 同左 |

最大变化是：**解析时必须先 `.build()` 再 `parseSignedClaims`**，且 `parseClaimsJws` 改名为 `parseSignedClaims`；`setSigningKey` 改为 `verifyWith`。如果你从老项目复制旧写法，编译就会报错。

⚠️ **踩坑提示（真实 bug）**：`JwtUtil.userIdOf` 里**不能**写 `claims.get("userId", Long.class)`。Jackson 会把小整数（比如用户 ID = 1）反序列化成 `Integer`，而传 `Long.class` 时 JJWT 会抛 `RequiredTypeException`（"Cannot convert existing claim value of type Integer to Long"），被上层兜底成「token 无效」——用户 ID 是 1 这种小数字时必现。本项目用 `instanceof Number` 再 `longValue()` 规避（见第 77–86 行）。

---

## 11.6 缺省密钥的安全风险

`application.yml` 里 JWT 这样配：

```yaml
jwt:
  secret: ${JWT_SECRET:codegen-platform-jwt-secret-key-2026-very-long}
  expire-hours: ${JWT_EXPIRE_HOURS:24}
```

（`application.yml` 第 93–95 行）

`${JWT_SECRET:默认值}` 的意思是：优先读环境变量 `JWT_SECRET`，读不到就用冒号后的默认值。这个默认值只为「克隆下来直接能跑」，但**生产环境如果没覆盖它，等于把 token 签发权公开**——拿到这串就能伪造任意用户的 token（包括 admin）。

为此 `JwtUtil` 在启动时主动告警：

```java
@PostConstruct
void warnIfSecretIsDefault() {
    if (DEV_DEFAULT_SECRET.equals(secret)) {
        log.warn("jwt.secret 正在使用仓库内置默认值，仅适用于本机开发；"
                + "部署到任何共享/公网环境前请设置环境变量 JWT_SECRET（否则 token 可被伪造）");
    }
}
```

（`JwtUtil.java` 第 36–42 行）

⚠️ **踩坑提示**：除了 secret，本章开头 `application.yml` 里的 `spring.datasource.password: ${DB_PASSWORD:root}` 也是同样的思路——**仓库里的口令等于没有口令**。任何敏感配置（数据库密码、JWT 密钥、AI 的 api-key）都应走环境变量或 `application-local.yml`（不入库），绝不以明文提交到 git。

---

## 本章小结

- Spring Security 6 废弃了 `WebSecurityConfigurerAdapter`，转向 `SecurityFilterChain` Bean 与 `requestMatchers` Lambda DSL；Boot 3 绑定的是 6.2.x。
- codegen-server 只引 `spring-security-crypto` 而不引完整 Security，用 `BCryptPasswordEncoder` 做密码哈希，鉴权逻辑自建，依赖更轻、更贴合单体需求。
- `AuthContextFilter` 继承 `OncePerRequestFilter`，用 `@Order(HIGHEST_PRECEDENCE+10)` 排在链首，完成白名单放行、Bearer 解析、SSE 查询参数兜底，并在 `finally` 中清理 `UserContext`。
- `UserContext` 用 `ThreadLocal` 保存当前用户身份与数据权限，业务只读；但 `ThreadLocal` 不跨异步线程。
- jjwt 0.12 用 `Jwts.builder().signWith(key)` 签发、`Jwts.parser().verifyWith(key).build().parseSignedClaims(t)` 解析；注意小整数 claim 的类型陷阱。
- 所有敏感配置用 `${ENV:默认}` 占位，默认值仅用于本机开发，生产必须用环境变量覆盖，否则存在 token 伪造与口令泄露风险。
