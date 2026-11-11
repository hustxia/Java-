# Java-backend 书架

本仓库收录以真实生产项目为贯穿案例撰写的技术书籍（Markdown 电子书，按书分目录）。

| 书名 | 目录 | 章数 | 贯穿案例 |
|---|---|---|---|
| 《Java 后端故障图鉴》 | [java 后端故障图鉴/](java%20后端故障图鉴/) | 37+ | 生产故障复盘实录 |
| 《Spring Boot 3 入门到精通》 | [Spring Boot 3 入门到精通/](Spring%20Boot%203%20入门到精通/) | 22 | codegen-server（Spring Boot 3.2.5 + Java 21） |
| 《JUnit 5 入门到精通》 | [JUnit 5 入门到精通/](JUnit%205%20入门到精通/) | 14 | codegen-server 的 49 个真实测试类 |
| 《Vue 从入门到精通》 | [Vue 入门到精通/](Vue%20入门到精通/) | 16 | codegen-web（Vue 2.7 + Element UI），主线讲 Vue 3 |

每本书入口为各自目录下的 `README.md`（含总目录与阅读路线）。

## 写作约定

- 每章统一结构：本章目标 → 原理 + 代码 → 本章小结 → ⚠️ 踩坑提示。
- 示例优先取自真实项目源码（标注来源文件）；项目未实现的特性用通用示例并明确标注。
- 书稿为 Markdown 源文件，可按需转换为 Word / PDF / 网页版。
