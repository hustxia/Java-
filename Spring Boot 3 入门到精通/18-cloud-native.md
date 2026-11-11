# 第 18 章 云原生：容器化、健康检查与配置外部化

## 本章目标

Spring Boot 3 应用天生适合云原生。本章讲四件事：

- 用**多阶段 Dockerfile** 把「连上 MySQL 就能跑」的单体打成精简镜像；
- 把 Actuator **health** 接入 **Kubernetes 探针**（liveness / readiness）；
- **GraalVM Native Image** 的注意事项（反射/资源注册、Runner 初始化、Boot 3 的 AOT 支持）；
- 配置**外部化**在云上的落地实践（来源 codegen `application.yml` 的全量 `${ENV:default}`）。

本章真实片段来自 codegen-server 的配置与 `pom.xml`，Dockerfile 与 K8s 清单为**通用示例**。

## 18.1 容器化：多阶段 Dockerfile

Spring Boot 3 默认产出可执行的「胖 jar」（由 `spring-boot-maven-plugin` 的 `repackage` 目标打包，来源 `pom.xml`）。多阶段构建把「编译环境」与「运行环境」分开，最终镜像只含 JRE 与 jar，体积小、攻击面小（**通用示例**）：

```dockerfile
# 此为通用示例：Spring Boot 3 多阶段构建
# ---- 阶段一：用完整的 JDK 编译打包 ----
FROM maven:3.9-eclipse-temurin-21 AS build
WORKDIR /app
COPY pom.xml .
RUN mvn -B -q dependency:go-offline          # 先拉依赖，利用层缓存
COPY src ./src
RUN mvn -B -q package -DskipTests           # 产出 target/codegen-server.jar

# ---- 阶段二：极简运行镜像 ----
FROM eclipse-temurin:21-jre
WORKDIR /app
# 用不可变用户跑，降低容器逃逸风险
RUN groupadd -r spring && useradd -r -g spring spring
COPY --from=build /app/target/codegen-server.jar app.jar
USER spring
EXPOSE 8120
# 用数组形式传参，支持优雅接收 SIGTERM
ENTRYPOINT ["java", "-jar", "/app/app.jar"]
```

构建与运行：

```bash
# 此为通用示例
docker build -t codegen-server:1.0.0 .
docker run -p 8120:8120 \
  -e DB_PASSWORD='<强口令>' -e JWT_SECRET='<32位+随机串>' \
  codegen-server:1.0.0
```

为什么 codegen 这种单体特别适合容器化：它**没有额外的 sidecar、没有必需的中间件集群**，唯一硬依赖是 MySQL。把 `DB_*`、`JWT_SECRET` 用环境变量注入，镜像本身不含任何凭据，一份镜像可在开发、测试、生产复用。这正是「十二要素应用」的配置外部化原则。

> ⚠️ 踩坑提示：不要把 `application-local.yml`（含本机路径、口令）打进镜像；用 `docker run -e` 或 K8s Secret 注入。另外 `EXPOSE` 只是文档声明，真正端口由 `server.port` 决定，二者要一致（codegen 是 8120）。

## 18.2 健康检查接入 K8s 探针

Kubernetes 用三类探针管理容器生命周期，全部可指向 Actuator 的 `/actuator/health`：

- **liveness**（存活）：失败 → 重启容器。指向 health 即可。
- **readiness**（就绪）：失败 → 摘流量但不重启。可配 `management.endpoint.health.group.readiness` 只包含 DB 等依赖。
- **startup**（启动）：给慢启动应用更长的初始宽限。

codegen 的健康配置（来源 `src/main/resources/application.yml`）：`health.show-details=never` 只暴露 `{"status":"UP"}`，安全且不吐数据库地址。K8s 清单示意（**通用示例**）：

```yaml
# 此为通用示例：Deployment 探针配置
apiVersion: apps/v1
kind: Deployment
spec:
  template:
    spec:
      containers:
        - name: codegen-server
          ports:
            - containerPort: 8120
          readinessProbe:                  # 就绪探针：连不上 MySQL 时摘流量
            httpGet:
              path: /actuator/health/readiness
              port: 8120
            initialDelaySeconds: 20
            periodSeconds: 10
          livenessProbe:                   # 存活探针：进程假死则重启
            httpGet:
              path: /actuator/health/liveness
              port: 8120
            initialDelaySeconds: 30
            periodSeconds: 15
```

若只需基础存活，直接用 `/actuator/health` 即可。注意：readiness/liveness 分组需要额外配置 `management.endpoint.health.group.*.include`，否则该子路径不存在会 404。

⚠️ 踩坑提示：liveness 探针超时或阈值太严，会在应用 GC 停顿或启动慢时**被反复重启**，形成「启动 → 被杀 → 重启」死循环。给 `initialDelaySeconds` 和 `failureThreshold` 留足余量。readiness 与 liveness 要用不同阈值——就绪失败只需摘流量，不该触发重启。

## 18.3 GraalVM Native Image 注意事项

把 Spring Boot 3 应用编译成 GraalVM native image，启动可达毫秒级、内存大幅下降，但代价是**封闭世界假设**：所有运行时才出现的东西（反射、资源、动态代理、Runner 初始化）都要提前声明。

Boot 3 提供 **AOT（Ahead-Of-Time）** 处理：编译期生成运行时所需的反射/资源/代理清单，配合 `spring-boot-maven-plugin` 的 `process-aot` 目标。关键点：

1. **反射需注册**：FreeMarker 模板、Jackson 反序列化的 DTO、MyBatis 实体等大量依赖运行期反射。未注册会在 native 下抛出 `ClassNotFoundException` 或静默为空。Boot 3 的 AOT 能自动处理大部分 Spring 托管 Bean，但第三方库（如 codegen 用的 `jsqlparser`、ip2region 自定义二进制解析）可能仍需 `@RegisterReflectionForBinding` 或 `reflect-config.json`。
2. **资源要显式包含**：`classpath:/ip/ip2region.db` 这类非 `.class` 资源，native image 默认不打包，需要用 `native-image.properties` 的 `--initialize-at-build-time` / 资源包含规则，或在 `src/main/resources/META-INF/native-image` 下放配置。
3. **Runner / @PostConstruct 初始化**：`@EnableScheduling` 的 `MonitorConfig` 这类在运行期才生效的调度，native 下仍可用，但要确认初始化不在「构建期」偷偷执行（构建期没有真实环境）。
4. **构建产物与 profile**：native 构建通常走独立 profile（如 `-Pnative`），`spring-boot-maven-plugin` 配合 GraalVM `native-maven-plugin` 完成。

对 codegen 这种**重度依赖模板引擎、MyBatis-Plus、自定义二进制库**的单体，上 native image 的反射/资源清单工作量不小。务实建议：**先用容器化拿到「部署标准化」收益，native image 作为后续优化项**，待核心依赖都验证过 native 兼容再推进。

> ⚠️ 踩坑提示：native image 不是「加个插件就能跑」。凡是用 `Class.forName`、反射实例化、读 classpath 资源、`Proxy` 动态代理的地方，在 native 下都可能失灵。上线前务必在 native 构建产物上跑一轮集成测试，而不是只在 JVM 模式验证过就以为等价。

## 18.4 配置外部化在云上的实践

云上部署的第一铁律：**镜像不含环境相关配置**。codegen 的 `application.yml` 几乎每个敏感/环境相关项都用了 `${ENV:default}` 外置点（来源 `src/main/resources/application.yml`）：

```yaml
# 来源：src/main/resources/application.yml
spring:
  datasource:
    username: ${DB_USERNAME:root}           # 默认值只为「克隆下来直接能跑」
    password: ${DB_PASSWORD:root}           # 生产必须用环境变量覆盖
jwt:
  secret: ${JWT_SECRET:codegen-platform-jwt-secret-key-2026-very-long}  # 拿到它就能伪造任意 token
  expire-hours: ${JWT_EXPIRE_HOURS:24}
gen:
  output:
    backend-root: ${GEN_OUTPUT_BACKEND_ROOT:../codegen-demo-target}
doc:
  upload-dir: ${DOC_UPLOAD_DIR:./uploads/doc}
  max-size-mb: ${DOC_MAX_SIZE_MB:30}
  allowed-exts: ${DOC_ALLOWED_EXTS:pdf,doc,docx,xls,xlsx,ppt,pptx}
monitor:
  sample:
    interval-ms: ${MONITOR_SAMPLE_INTERVAL_MS:5000}
    buffer-size: ${MONITOR_SAMPLE_BUFFER_SIZE:360}
```

外加 `spring.profiles.include: local`——把本机专属配置（AI 的 base-url/api-key、生成自检 classpath）放到不入库的 `application-local.yml`，文件缺失时静默跳过，不影响他人直接跑起来。

云上的最佳实践层次：

1. **非敏感默认内置**：如 `server.port`、采样周期，给合理默认值方便本地。
2. **敏感项走环境变量/Secret**：`DB_PASSWORD`、`JWT_SECRET` 绝不能出现在镜像或代码仓库。K8s 用 `Secret` + `envFrom` 注入。
3. **本机专属走可选 profile**：`application-local.yml` 不入库，开发态自动叠加。
4. **配置中心按需引入**：当实例数多到手动改环境变量不可控时，再接 Spring Cloud Config / Nacos，但 codegen 单体目前用 `${ENV}` + profile 已足够。

⚠️ 踩坑提示：仓库里的 `JWT_SECRET` / `DB_PASSWORD` 默认值等于「没有口令」。codegen 启动时会打 WARN 提醒覆盖。任何把默认凭据推到生产镜像的行为都是安全事故——务必在 CI 里加一道「镜像内不得出现已知默认口令」的检查。

## 本章小结

云原生对 Spring Boot 3 单体而言，门槛比想象中低。**多阶段 Dockerfile** 即可把「连 MySQL 就能跑」的 codegen 打成精简、不含凭据的标准镜像；**Actuator health** 天然适配 K8s 三类探针，只需注意 readiness/liveness 阈值与 `show-details=never`；**GraalVM Native Image** 收益诱人但反射/资源注册清单工作量不可忽视，建议先容器化、再择机 native；**配置外部化**靠全量的 `${ENV:default}` + 可选 `local` profile 落地，敏感项一律进 Secret。云化不是重写应用，而是把「环境差异」从代码里剥离出去。

## ⚠️ 本章核心踩坑

1. 镜像**绝不含凭据**：`JWT_SECRET`/`DB_PASSWORD` 默认值只是本地便利，生产必须用 Secret 覆盖，并在 CI 拦截默认口令入镜像。
2. K8s 探针阈值要松：liveness 过严会在 GC/启动慢时引发重启死循环；readiness 失败应摘流量而非重启。
3. Native Image 是「封闭世界」：反射、classpath 资源、动态代理都得提前声明，上线前必须在 native 产物上跑实测。
4. `application-local.yml` 务必加进 `.gitignore`——它不入库才叫「可选 profile」，误提交即泄露本机路径与密钥。

## 本章云化落地清单

把 codegen-server 推上云，按优先级做这五步即可：

1. 加多阶段 Dockerfile，确认 `spring-boot-maven-plugin` 的 `repackage` 已产出可执行 jar（已在 `pom.xml` 配置）。
2. 把 `DB_PASSWORD` / `JWT_SECRET` 等所有 `${ENV:default}` 的敏感项用 K8s Secret 注入，删掉任何硬编码。
3. 配 readiness/liveness 探针指向 `/actuator/health`，`show-details` 保持 `never`。
4. 把本机路径（`GEN_OUTPUT_BACKEND_ROOT`、`DOC_UPLOAD_DIR`）挂成 PVC 或环境变量，避免写进镜像层。
5. （可选后续）评估 GraalVM native image，重点验证 FreeMarker、MyBatis-Plus、ip2region 三处的反射/资源注册。
