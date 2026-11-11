# 第 20 章 部署上线：克隆即可跑，生产改环境变量

## 本章目标

读完本章你将掌握：

- 用 Spring Boot Maven 插件把 codegen-server 打成**可执行 fat jar**；
- 理解并落地"**仓库零密钥、环境变量覆盖一切**"的外部化配置哲学；
- 用 **systemd** 把服务托管成开机自启、崩溃自拉起的守护进程；
- 用 **Nginx** 做反向代理（HTTPS、静态资源、超时）；
- 多实例部署与**日志切割归档**的基本做法。

---

## 20.1 打包：一个能直接 `java -jar` 的 fat jar

codegen-server 的 `pom.xml` 用 `spring-boot-maven-plugin` 的 `repackage` 目标把依赖打进一个可直接运行的 jar，并且 `finalName` 固定为 `codegen-server`：

```xml
<!-- 来源：pom.xml（节选） -->
<build>
    <!-- finalName 决定产出文件名：codegen-server.jar -->
    <finalName>${project.artifactId}</finalName>
    <plugins>
        <!-- -parameters 必须保留：Spring MVC 靠参数名绑定 @RequestParam/@PathVariable，
             本 POM 无父工程继承，不显式声明会触发 "Name for argument ... not specified" 500 -->
        <plugin>
            <groupId>org.apache.maven.plugins</groupId>
            <artifactId>maven-compiler-plugin</artifactId>
            <configuration>
                <compilerArgs><arg>-parameters</arg></compilerArgs>
            </configuration>
        </plugin>
        <plugin>
            <groupId>org.springframework.boot</groupId>
            <artifactId>spring-boot-maven-plugin</artifactId>
            <version>${spring-boot.version}</version>
            <executions>
                <execution>
                    <goals><goal>repackage</goal></goals>   <!-- 关键：把依赖嵌进 jar -->
                </execution>
            </executions>
        </plugin>
    </plugins>
</build>
```

打包命令（跳过测试加快，CI 里则保留测试）：

```bash
# 此为通用示例（在项目根目录执行）
mvn -DskipTests clean package
# 产出：target/codegen-server.jar
ls -lh target/codegen-server.jar
```

运行：

```bash
java -jar target/codegen-server.jar
# 默认读 classpath 里的 application.yml，端口 8120
```

> ⚠️ 踩坑提示：fat jar 内部依赖是 `BOOT-INF/classes!/` 嵌套路径。codegen-server 的**生成自检**需要把依赖 classpath 交给 `javac` 做内存编译，如果留空取 `java.class.path`，启动进程是 fat jar 时它只是 `app.jar` 自身，`javac` 解析不到嵌套依赖 → 满屏 `cannot find symbol`（假报错）。所以 `gen.selfcheck.classpath` 必须指向目标工程的依赖目录（见 20.2）。**这就是"肥 jar 找不到资源/依赖"的典型坑。**

---

## 20.2 外部化配置：仓库零密钥

codegen-server 把"**克隆下来直接能跑**"和"**生产安全**"通过一个简单约定同时满足了：`application.yml` 里的每一个敏感/环境相关项都用 `${ENV:default}` 语法，默认值只服务于本地开发，**真上生产一律用环境变量覆盖**。

汇总所有外置点（来源：`src/main/resources/application.yml`）：

```yaml
# ---- 数据库（仓库里写的 root/root 等于没有口令）----
spring.datasource.username: ${DB_USERNAME:root}
spring.datasource.password: ${DB_PASSWORD:root}

# ---- JWT（拿到 JWT_SECRET 就能伪造任意用户 token）----
jwt.secret:        ${JWT_SECRET:-codegen-platform-jwt-secret-key-2026-very-long}
jwt.expire-hours:  ${JWT_EXPIRE_HOURS:24}

# ---- 可观测性采样窗口 ----
monitor.sample.interval-ms:   ${MONITOR_SAMPLE_INTERVAL_MS:5000}
monitor.sample.buffer-size:   ${MONITOR_SAMPLE_BUFFER_SIZE:360}

# ---- 接口文档（生产关闭 swagger）----
springdoc.api-docs.enabled:   ${SPRINGDOC_API_DOCS_ENABLED:true}
springdoc.swagger-ui.enabled: ${SPRINGDOC_UI_ENABLED:true}

# ---- 代码生成输出根目录（指向任意目标工程）----
gen.output.backend-root:   ${GEN_OUTPUT_BACKEND_ROOT:../codegen-demo-target}
gen.output.frontend-root:  ${GEN_OUTPUT_FRONTEND_ROOT:../codegen-demo-target}
gen.selfcheck.classpath:   ${GEN_SELFCHECK_CLASSPATH:}   # 肥 jar 部署必配

# ---- 文档中心（上传目录、预览引擎等）----
doc.upload-dir:               ${DOC_UPLOAD_DIR:./uploads/doc}
doc.max-size-mb:              ${DOC_MAX_SIZE_MB:30}
doc.preview.engine:           ${DOC_PREVIEW_ENGINE:auto}
doc.preview.soffice-path:     ${DOC_SOFFICE_PATH:}
# … 其余 DOC_PREVIEW_* 同理
```

此外，本机路径（如 `gen.output.*`、AI 的 `api-key`、`maven` 路径）按约定放进**不入库**的 `application-local.yml`，由 `spring.profiles.include: local` 叠加。文件不存在时静默跳过，不影响别人直接跑起来。

生产启动示例（**此为通用示例**，演示环境变量覆盖）：

```bash
# 生产：用环境变量覆盖所有密钥与路径，仓库里不出现任何真实值
export DB_USERNAME=codegen_prod
export DB_PASSWORD='********'
export JWT_SECRET='换成 32 字节以上的随机串'
export SPRINGDOC_API_DOCS_ENABLED=false
export SPRINGDOC_UI_ENABLED=false
export GEN_OUTPUT_BACKEND_ROOT=/srv/codegen/target/backend
export GEN_OUTPUT_FRONTEND_ROOT=/srv/codegen/target/web
export GEN_SELFCHECK_CLASSPATH=/srv/codegen/target/demo-lib/*

java -jar /opt/codegen/codegen-server.jar \
     --spring.profiles.active=prod
```

**设计哲学一句话**：默认值让"新人 `git clone` 后直接 `mvn package && java -jar` 就能跑起来"；环境变量让"运维把同一个 jar 丢到生产、换个 shell 环境就安全上线"。同一份制品，两种用法，互不污染。

---

## 20.3 用 systemd 托管

`nohup java -jar &` 最大的问题是进程死了没人拉、机器重启没人起。用 systemd 托管才是正路（**此为通用示例**）：

```ini
# /etc/systemd/system/codegen-server.service
[Unit]
Description=codegen-server (Spring Boot 3 code generator)
After=network.target mysql.service

[Service]
# 不要用 root 跑业务进程
User=codegen
WorkingDirectory=/opt/codegen
# 环境变量集中写在这里，仓库与 jar 都不含密钥
Environment=DB_USERNAME=codegen_prod
Environment=DB_PASSWORD=********
Environment=JWT_SECRET=换成随机串
Environment=SPRINGDOC_API_DOCS_ENABLED=false
Environment=SPRINGDOC_UI_ENABLED=false
Environment=GEN_OUTPUT_BACKEND_ROOT=/srv/codegen/target/backend
ExecStart=/usr/bin/java -jar /opt/codegen/codegen-server.jar
SuccessExitStatus=143          # SIGTERM 退出码，systemd 视为正常
Restart=on-failure             # 崩溃自动重启
RestartSec=5
# 限制资源，防失控
LimitNOFILE=65535

[Install]
WantedBy=multi-user.target
```

```bash
# 此为通用示例
sudo systemctl daemon-reload
sudo systemctl enable --now codegen-server
journalctl -u codegen-server -f     # 看实时日志
```

> ⚠️ 踩坑提示：systemd 的 `Environment` 里如果值含空格或 `$`，要用双引号并转义 `$`（写 `$$`）。把密钥明文写进 unit 文件虽然不如 Vault 优雅，但**远比把密钥提交进 Git 仓库安全**——codegen-server 的 `application.yml` 里连默认口令都标了"等于没有口令"，就是逼你走环境变量这条路。

---

## 20.4 Nginx 反向代理

服务监听 `8120`，前置 Nginx 做统一入口、TLS 终止与超时控制（**此为通用示例**）：

```nginx
# /etc/nginx/conf.d/codegen.conf
upstream codegen_backend {
    server 127.0.0.1:8120;
    # 多实例时再加一行：server 127.0.0.1:8121;
    keepalive 32;
}

server {
    listen 443 ssl;
    server_name codegen.example.com;

    ssl_certificate     /etc/nginx/ssl/codegen.crt;
    ssl_certificate_key /etc/nginx/ssl/codegen.key;

    # 上传文档可能较大，调大 body 上限（应用侧 max-file-size=30MB 也要配套）
    client_max_body_size 40m;

    location / {
        proxy_pass http://codegen_backend;
        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        # 生成/写盘可能耗时，超时放宽；默认 60s 会在大表生成时截断
        proxy_read_timeout 300s;
        proxy_connect_timeout 10s;
    }
}
```

注意 codegen-server 的 `AuthContextFilter` 校验的是 `Authorization: Bearer` 头，Nginx 透传即可，无需在 Nginx 层做鉴权。

---

## 20.5 多实例部署

codegen-server 是**有状态单体**（写盘落本地目录、监控是进程内环形缓冲、不依赖 Redis/Nacos），所以多实例不是"无脑加节点"：

- **写盘根目录要隔离或共享**：每个实例的 `GEN_OUTPUT_BACKEND_ROOT` 若指向同一台机器的不同工程，互不影响；若多实例共享同一目标工程，需保证不会同时写同一批文件（目前靠人工错峰，没有分布式锁）；
- **监控不跨实例聚合**：`MonitorStore` 是进程内、重启归零、多实例不共享（yml 注释明确写了）。要做全局看板，要么各实例独立看，要么接 Prometheus 远端（本书不展开）；
- **会话/令牌无状态**：JWT 自带信息，任意实例都能验，天然支持负载均衡——这是它**不用 Redis 也能多实例**的底气。

结论：codegen-server 适合"一主一备"或"按目标工程分实例"，不适合无状态横向无限扩。

---

## 20.6 日志切割与归档

Spring Boot 默认用 Logback，codegen-server 指定了 `logback-spring.xml`：

```yaml
# 来源：application.yml
logging:
  config: classpath:logback-spring.xml
  level:
    com.codegen: info
```

生产日志别只靠一个 `spring.log` 无限增长，两种做法：

1. **Logback 自带滚动**（推荐）：在 `logback-spring.xml` 里用 `RollingFileAppender` + `SizeAndTimeBasedRollingPolicy`，按天 + 按大小滚动并保留 N 天；
2. **systemd + logrotate**：若日志走 stdout（`journalctl`），用 `journald` 的 `SystemMaxUse` 限制，或用 `logrotate` 对文件切割。

logrotate 片段（**此为通用示例**）：

```conf
# /etc/logrotate.d/codegen
/opt/codegen/logs/*.log {
    daily
    rotate 30
    compress
    delaycompress
    missingok
    notifempty
    copytruncate    # Spring Boot 持有着文件句柄，copytruncate 最稳
}
```

> ⚠️ 踩坑提示：如果用 `copytruncate` 之外的 rename 方式切割，Java 进程仍写旧 fd，日志会"消失"。Logback 自身滚动则无此问题。**不要同时开 Logback 滚动和 logrotate**，否则两份机制打架。

---

## 本章小结

- 打包靠 `spring-boot-maven-plugin` 的 `repackage`，产物 `codegen-server.jar` 可直接 `java -jar`；
- "仓库零密钥"的核心是 `${ENV:default}`：DB_*/JWT_*/MONITOR_*/SPRINGDOC_*/GEN_*/DOC_* 全部可被环境变量覆盖，克隆即跑、生产改环境变量；
- systemd 负责"开机自启 + 崩溃自拉"，密钥写在 unit 的 `Environment` 里；
- Nginx 做 TLS 终止与超时（生成接口要放宽 `proxy_read_timeout`）；
- codegen-server 是有状态单体，多实例需隔离写盘根目录，但其 JWT 无状态设计天然支持负载均衡；
- 日志用 Logback 滚动或 logrotate，二者别同时开。

⚠️ **踩坑提示（本章）**：codegen-server 同时是"生成器"和"被生成系统的运行平台"，**它写的文件落在目标工程磁盘上**，所以部署规划里最容易漏掉的是"目标工程目录的磁盘空间与权限"。`GEN_OUTPUT_BACKEND_ROOT` 指向的目录必须让运行用户（如 `codegen`）有写权限，否则写盘会满屏 `ERROR` 而主流程不报错——这正是 19.6 说的"台账失败不阻断写盘"设计的副作用，部署时务必把目录权限先给定好。
