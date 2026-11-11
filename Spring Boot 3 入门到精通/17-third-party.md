# 第 17 章 第三方集成：HTTP 调用、文件上传与归属地查询

## 本章目标

真实平台总要和外部打交道。本章围绕「调别人」与「收文件」两类场景展开：

- 调用外部 HTTP 的两种姿势：**RestTemplate**（同步阻塞）与 **WebClient**（响应式、非阻塞）；
- **文件上传**的 multipart 配置与校验（来源 codegen 文档中心 `DocController` / `DocProperties`）；
- **IP 归属地查询**的稳妥实现：离线库优先、在线接口兜底、结果缓存（来源 codegen `IpRegionResolver` / `Ip2RegionSearcher`）。

本章真实片段来自 codegen-server，源文件路径见文中标注；RestTemplate/WebClient 对比与部分调用骨架为**通用示例**。

## 17.1 调用外部 HTTP：RestTemplate vs WebClient

Spring 生态里发 HTTP 有两套主流方案。

**RestTemplate**——同步阻塞式，API 直观，适合调用频次不高、逻辑简单的场景（**通用示例**）：

```java
// 此为通用示例：RestTemplate 同步调用
@Service
public class RegionClient {
    private final RestTemplate rest = new RestTemplate();

    public String fetchJson(String url) {
        return rest.getForObject(url, String.class);   // 阻塞直到响应返回
    }
}
```

**WebClient**——基于 Reactor 的响应式、非阻塞客户端，适合高并发或需要流式处理、超时精细控制的场景（**通用示例**）：

```java
// 此为通用示例：WebClient 响应式调用
@Service
public class RegionClient {
    private final WebClient web = WebClient.builder()
            .baseUrl("http://ip-api.com")
            .build();

    public Mono<String> fetchJson(String ip) {
        return web.get()
                  .uri("/json/{ip}?lang=zh-CN", ip)
                  .retrieve()
                  .bodyToMono(String.class)
                  .timeout(Duration.ofMillis(3000));    // 响应式超时
    }
}
```

选型建议：单体后台里只是「偶尔调一下外部接口补数据」，RestTemplate 够用且心智负担小；若接口是请求链路的 hot path、或你要和响应式栈（WebFlux）统一，再上 WebClient。codegen 的归属地查询用的是 JDK 11+ 自带的 `java.net.http.HttpClient`（见 17.3），不引入额外依赖、同步可控，是介于二者之间的务实选择。

⚠️ 踩坑提示：RestTemplate 在 Spring 5.3 后被标记为「不推荐用于新代码」，但并未废弃。若只用同步调用，它可以继续用；新项目想统一技术栈可优先 WebClient。无论哪种，**超时一定要显式设置**——不配超时，对方卡住时你的线程会被永久占用直到系统资源耗尽。

## 17.2 文件上传：multipart 配置与两层校验

文件上传在 Spring MVC 里用 `MultipartFile` 接收。codegen 文档中心的真实接收端（来源 `src/main/java/com/codegen/controller/DocController.java`）：

```java
// 来源：src/main/java/com/codegen/controller/DocController.java（节选）
@PostMapping("/upload")
public Result<DocVO> upload(@RequestParam("file") MultipartFile file) {
    require("doc:upload");                  // 权限码校验：写操作落到 doc:upload
    return Result.ok(docService.upload(file));
}
```

multipart 有**两层大小限制**必须都配，只配 `max-file-size` 时请求体超限仍会被拒且报错难懂（来源 `src/main/resources/application.yml`）：

```yaml
# 来源：src/main/resources/application.yml
spring:
  servlet:
    multipart:
      max-file-size: 30MB        # 单个文件上限
      max-request-size: 35MB     # 整个请求上限（多文件场景必配）
```

业务侧还有一份独立的白名单与上限配置（来源 `src/main/java/com/codegen/config/DocProperties.java`）：

```java
// 来源：src/main/java/com/codegen/config/DocProperties.java（节选）
@Data
@Component
@ConfigurationProperties(prefix = "doc")
public class DocProperties {
    private String uploadDir = "./uploads/doc";
    private int maxSizeMb = 30;                               // 与 spring 两层校验独立
    private String allowedExts = "pdf,doc,docx,xls,xlsx,ppt,pptx";  // 白名单扩展名
    // ...
    public Set<String> allowedExtSet() {
        Set<String> set = new LinkedHashSet<>();
        for (String raw : allowedExts.split(",")) {
            String ext = raw.trim().toLowerCase(Locale.ROOT);  // 小写、去点、去空
            if (ext.startsWith(".")) ext = ext.substring(1);
            if (!ext.isEmpty()) set.add(ext);
        }
        return set;
    }
}
```

白名单刻意**不含 svg / html / md**——这些可含脚本或富文本，叠加免鉴权直链即成存储型 XSS（来源 `DocController` 注释与 `DocCenterBaselineTest` 断言）。`DocController` 的所有二进制端点（`preview/raw/download`）都不套 `{code,msg,data}` 信封，成功返文件流、失败返 HTTP 状态 + JSON，避免前端把错误 JSON 当文件解析。

落盘路径安全由 `DocStorage` 兜底：文件名用 UUID、目录按 `yyyyMM` 分片，且 `resolve` 拒绝 `../` 穿越（来源 `src/test/java/com/codegen/service/DocCenterBaselineTest.java` 验证 `../../etc/passwd` 被 404 拒绝）。

> ⚠️ 踩坑提示：只信前端传的 `Content-Type` 与文件名扩展名是危险的。codegen 用 `allowedExtSet()` 做服务端白名单，并禁止脚本载体扩展名；下载时还会设 `X-Content-Type-Options: nosniff` 防止浏览器把文档嗅探成 HTML 执行。文件上传三件套：**服务端大小校验 + 扩展名白名单 + 落盘路径防穿越**缺一不可。

## 17.3 IP 归属地查询：离线优先 + 在线兜底 + 缓存

操作日志要回答「这次操作从哪来」，只记 IP 看不出地域。codegen 的实现是一套很经典的「多级 fallback + 缓存」架构（来源 `src/main/java/com/codegen/common/log/IpRegionResolver.java`）。

设计取舍要点：

- **离线优先**：classpath 里的 `ip2region.db`（8.7MB，约 68 万索引）纯内存二分，微秒级、不碰网络。公网免费接口实测六次只成一次，纯在线方案会让一半日志没有省市。
- **内网不发请求**：回环与私有网段直接给「本机 / 内网」，企业内网部署零延迟。
- **在线兜底**：离线库查不到（新分配的段、只到国家粒度）才走接口，且受缓存保护。
- **结果带缓存**：同一 IP 24h 内只查一次，失败也缓存（负缓存 5min），避免接口不可达时每条日志都白等一个超时。
- **绝不抛异常**：解析失败返回 `null`，日志照常落库——省市是锦上添花，不能拖垮业务。

核心流程（来源 `IpRegionResolver.java` 节选）：

```java
// 来源：src/main/java/com/codegen/common/log/IpRegionResolver.java（节选）
public Region resolve(String ip) {
    if (ip == null || ip.isBlank()) return null;
    Region local = localRegion(key);                  // 本机/内网直接给结论，不发请求
    if (local != null) return local;
    if (!enabled) return null;

    CacheEntry hit = cache.get(key);                  // 先查缓存（24h / 5min 负缓存）
    if (hit != null && hit.expireAt() > now) return hit.region();

    Ip2RegionSearcher db = searcher();                // 离线库懒加载（首次才读 8.7MB）
    if (db != null) {
        Region region = db.search(key);               // 命中即返回，不碰网络
        if (region != null && !region.isEmpty()) {
            putCache(key, region, TTL_MS);
            return region;
        }
    }
    Region region = query(key);                        // 在线兜底
    putCache(key, region, region == null ? FAIL_TTL_MS : TTL_MS);
    return region;
}
```

在线查询用 JDK 自带 `HttpClient`，并显式设置超时与代理（来源同文件 `queryOnce` / `client`）：

```java
// 来源：src/main/java/com/codegen/common/log/IpRegionResolver.java（节选）
private Region queryOnce(String ip) throws Exception {
    String url = api.replace("{ip}", ip);             // app.ip-region.api 用 {ip} 占位，可换自建接口
    HttpResponse<byte[]> resp = client().send(
        HttpRequest.newBuilder(URI.create(url))
            .timeout(Duration.ofMillis(timeoutMs))     // 显式 3s 超时
            .header("User-Agent", "codegen-oper-log/1.0")
            .GET().build(),
        HttpResponse.BodyHandlers.ofByteArray());
    if (resp.statusCode() != 200) return null;
    // ... 解析 province/city，兼容 province/regionName/pro/city 多种键名 ...
}
```

离线库本身是纯二进制二分查找（来源 `src/main/java/com/codegen/common/log/Ip2RegionSearcher.java`）：从 superBlock 取索引区首尾指针，按 12 字节/条二分定位，再从数据区读出 `国家|区域|省份|城市|ISP` 串解析。库缺失或格式异常时 `load()` 返回 `null`，由上层回落在线接口——**降级路径永远可用**。

异步回填也很关键：归属地查询放在后台线程池，调用方（日志切面）绝不阻塞，队列满了直接丢弃（丢的是归属地，不是日志）。

> ⚠️ 踩坑提示：JDK `HttpClient` 默认读系统代理（`HTTP_PROXY`），机器上若有代理环境变量，请求会悄悄转给代理、代理不通时表现为「连不上」，排查半天是环境变量。codegen 用 `app.ip-region.proxy` 显式控制直连或指定代理。另：离线库懒加载而非启动时加载——8.7MB 放启动期会拖慢启动，第一次真正要解析归属地时才初始化，失败则永远是 null（走在线）。

## 本章小结

本章覆盖了平台「对外连接」的两类典型需求。**HTTP 调用**上，RestTemplate 简单同步、WebClient 响应式非阻塞，还有 JDK 自带 HttpClient 这种零依赖选择，核心纪律是「永远显式设超时」。**文件上传**要配齐 Spring 两层大小限制 + 业务侧扩展名白名单 + 落盘路径防穿越，codegen 文档中心还刻意屏蔽脚本载体扩展名防 XSS。**IP 归属地**则示范了一个教科书级的「离线优先 → 在线兜底 → 缓存 → 异步 → 永不抛异常」稳健模式，值得在任意「补数据」型外部调用里复用。

## ⚠️ 本章核心踩坑

1. 文件上传**两层大小**都要配：只配 `max-file-size` 时请求体超限仍会被拒；扩展名白名单**必须服务端校验**且排除 svg/html/md。
2. 外部 HTTP 调用**不设超时**是生产事故温床；对方卡住会拖垮你的线程池。
3. 离线库/外部接口**不可达是常态不是意外**——必须保证降级路径可用，且失败不能连累主流程。codegen 把归属地失败降级为 `null`、埋点失败降级为忽略，是同一思路。
4. 注意系统代理对 `HttpClient` 的隐式影响，云/容器环境尤其容易踩。
