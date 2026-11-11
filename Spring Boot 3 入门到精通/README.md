# 《Spring Boot 3 入门到精通》

> 一本以真实生产项目为贯穿案例的 Spring Boot 3 实战书。所有示例优先取自 **codegen-server**（Spring Boot 3.2.5 + Java 21 的代码生成器平台后端），尽量做到"学到的就是能上生产的写法"。

## 这本书讲什么

Spring Boot 3 不是 2.x 的小升级，而是一次底座换代：**Java 17+（推荐 21）**、**Jakarta EE 命名空间**、**Spring Framework 6**、**内置 Micrometer 可观测性**、**GraalVM 原生镜像支持**。本书从"为什么换"讲起，一路讲到部署上线，并用一个真实项目的全貌把知识点串起来。

全书 22 章，约 4700 行，分四篇：

- **基础篇（1–7）**：定位、快速开始、自动配置、依赖管理、配置外化、日志、Web 基础
- **核心篇（8–14）**：校验与 AOP、MyBatis-Plus、事务、安全与 JWT、缓存、异步定时、事件
- **进阶篇（15–18）**：测试、可观测性、第三方集成、云原生
- **实战篇（19–22）**：性能调优、部署运维、codegen-server 全貌剖析、迁移与速查附录

## 阅读路线

| 你的目标 | 推荐章节 |
|---|---|
| 从零入门到能写业务 | 1 → 2 → 3 → 5 → 7 → 8 → 9 → 10 |
| 只关心安全与鉴权 | 11（结合 2、7） |
| 想学平台级可观测性 | 16（结合 13、19、21） |
| 准备上线部署 | 5 → 18 → 20 |
| 做代码生成/脚手架类系统 | 9 → 10 → 21 |
| 把旧 2.x 项目升级到 3.x | 1 → 22（附录迁移清单） |

## 目录

### 基础篇
1. [为什么是 Spring Boot 3](01-why-spring-boot-3.md) —— Java 21、Jakarta、Spring 6、可观测性，以及与 2.x 的差异
2. [快速开始](02-quick-start.md) —— pom / 启动类 / application.yml 三件套，十分钟跑起 codegen-server
3. [自动配置原理](03-auto-configuration.md) —— @SpringBootApplication、条件注解、AutoConfiguration.imports
4. [依赖管理与 Starter](04-dependency-management.md) —— BOM、dependencyManagement、自定义 starter
5. [配置文件与外部化](05-configuration.md) —— @ConfigurationProperties、profiles、配置优先级、占位符
6. [日志](06-logging.md) —— SLF4J + Logback、滚动切割、MDC 透传 traceId
7. [Web 开发基础](07-web-basics.md) —— 参数绑定、统一返回 Result、全局异常处理

### 核心篇
8. [数据校验与 AOP](08-validation-aop.md) —— JSR-380 校验、自定义注解、切面与审计字段自动填充
9. [数据持久化 MyBatis-Plus](09-mybatis-plus.md) —— 分页、逻辑删除、自动填充、BaseMapper
10. [事务管理](10-transaction.md) —— @Transactional 原理、传播行为、失效场景与工程权衡
11. [Spring Security 6 + JWT](11-security-jwt.md) —— 轻量鉴权方案、AuthContextFilter、UserContext、jjwt 0.12
12. [缓存](12-caching.md) —— Spring Cache 抽象、Caffeine / Redis、进程内缓冲类比
13. [异步与定时任务](13-async-scheduling.md) —— @Async 线程池、@Scheduled、MonitorSampler 实战
14. [事件机制](14-events.md) —— ApplicationEvent、@EventListener、@TransactionalEventListener

### 进阶篇
15. [测试](15-testing.md) —— JUnit 5、@SpringBootTest、MockMvc 切片测试、Testcontainers
16. [可观测性](16-observability.md) —— Actuator、Micrometer、monitor 包落地、Prometheus + Grafana（标杆案例）
17. [集成第三方](17-third-party.md) —— HTTP 调用、文件上传、IP 归属地离线/在线兜底
18. [云原生与 GraalVM](18-cloud-native.md) —— 多阶段 Dockerfile、K8s 探针、Native Image 注意事项

### 实战篇
19. [性能调优](19-performance.md) —— JVM、连接池、线程池、慢 SQL、用指标定位瓶颈
20. [部署与运维](20-deployment.md) —— 可执行 jar、配置外置、systemd、Nginx、多实例
21. [实战：codegen-server 全貌剖析](21-case-study.md) —— 一次 `/gen/apply` 请求的完整链路，串起全书中所有知识点
22. [附录](22-appendix.md) —— Spring Boot 2→3 迁移清单、常用注解速查、全书踩坑 FAQ

## 案例项目

本书贯穿案例 **codegen-server** 是一个独立单体后端（连上 MySQL 即可运行，端口 8120），技术栈：

- Spring Boot **3.2.5** / Java **21**
- MyBatis-Plus 3.5.5（Boot 3 专用 starter）
- Freemarker 模板引擎（代码生成渲染）
- spring-security-crypto（BCrypt）+ jjwt 0.12.5（Token）
- Actuator + Micrometer（V6.10 平台可观测性）
- Lombok、springdoc-openapi（接口文档）

书中引用的真实片段均注明来源文件，例如：

```
代码来自 src/main/java/com/codegen/config/AuthContextFilter.java
```

## 约定与提示

- 每个代码块都标注了语言，关键行有中文注释。
- 每章末尾有「本章小结」，并至少含 1 处「⚠️ 踩坑提示」。
- 标记「此为通用示例」的代码块表示 codegen-server 未实现该特性，采用标准 Spring Boot 写法演示。
- 仓库中密钥一律用 `${ENV:default}` 占位，生产靠环境变量注入——克隆即可跑，上线改配置。

> 本书所有示例均可在真实 Java 21 + Spring Boot 3.2.5 环境下编译运行。建议配合 codegen-server 源码同步阅读，效果最佳。
