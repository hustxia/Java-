# Vue 从入门到精通

> 一本**主线讲 Vue 3（Composition API / `<script setup>` / Pinia / Vue Router 4 / Vite）**，并**以真实企业级后台 `codegen-web`（Vue 2.7.16 + Element UI + Vuex + Vue Router 3 + ECharts 5 + axios）为贯穿案例**的实战书。每章末以"真实项目对照"展示生产代码，末章专讲 **Vue 2.7 → 3 迁移**。既学到当下最现代的 Vue，又看得懂你手上的真实项目。

## 版本取向（必读）

- **主线语法 = Vue 3**：`<script setup>`、Composition API、`ref/reactive`、Pinia、Router 4、Vite。这是"精通"当下的标准。
- **真实案例 = Vue 2.7 的 `codegen-web`**：它是你正在维护的企业后台（Options API + Vuex + Element UI）。本书用它的真实文件（`src/views/monitor/index.vue`、`src/api/monitor.js`、`src/router/index.js`、`src/store/modules/user.js`、`src/utils/request.js`、`src/directive/permission.js` 等）做"生产级对照"，并标注 Vue 3 的等价写法。
- **末章（16）**：专门讲 2.7 → 3 的迁移清单，让你能把手上的项目平滑升级。

## 本书特色

- **现代 + 真实双轨**：Vue 3 语法为主，真实 Vue 2.7 代码为案例，对照清晰。
- **真实组件贯穿**：以 `monitor/index.vue`（848 行：指标卡 + ECharts 趋势 + 轮询 + 降级）作为"复杂页面"范本。
- **工程闭环**：路由、状态、请求层、权限指令、UI 库、构建部署全覆盖。
- **统一结构**：每章「本章目标 → 原理 + 代码 → 本章小结 → ⚠️ 踩坑提示」。

## 阅读路线

| 目标 | 推荐章节 |
|---|---|
| 零基础到能写页面 | 1 → 2 → 3 → 4 → 6 → 7 |
| 掌握组件化 | 8 → 9 → 10 |
| 工程化后台 | 12（路由）→ 13（状态）→ 14（请求）→ 15（UI 库/Element） |
| 看懂 codegen-web 真实项目 | 每章末"真实项目对照" + 16 |
| 升级到 Vue 3 | 11（Composables）→ 16（迁移） |

## 目录

1. [前端框架演进 & 为什么是 Vue](01-why-vue.md)
2. [快速开始：从 CDN 到 Vite 工程](02-quick-start.md)
3. [模板语法：插值、指令、绑定](03-template-syntax.md)
4. [响应式基础：ref / reactive（含 Vue 2 data 对比）](04-reactivity.md)
5. [计算属性与侦听器：computed / watch](05-computed-watch.md)
6. [Class 与 Style 绑定、条件与列表渲染](06-binding-render.md)
7. [事件处理与表单：v-on / v-model](07-events-forms.md)
8. [组件基础：props / emits / slot](08-component-basics.md)
9. [组件进阶：作用域插槽 / provide-inject / 异步组件](09-component-advanced.md)
10. [生命周期钩子（Vue 2 与 3 对照）](10-lifecycle.md)
11. [组合式函数 Composables（Vue 3 精华）](11-composables.md)
12. [路由：Vue Router 4（真实 router 结构对照）](12-router.md)
13. [状态管理：Pinia（对比 Vuex 真实 store）](13-state.md)
14. [网络请求与 API 层：axios（真实 request.js / api 模块）](14-http.md)
15. [UI 组件库与 Element（真实 monitor 页面剖析）](15-ui-element.md)
16. [工程化、部署与 Vue 2.7 → 3 迁移](16-engineering-migration.md)

## 真实案例索引（来自 codegen-web/src）

| 文件 | 体现的知识点 |
|---|---|
| `views/monitor/index.vue` | 复杂页面：模板/响应式/computed/生命周期/轮询/ECharts 懒加载/降级 |
| `api/monitor.js` | API 模块封装（按资源拆分、返回 res.data） |
| `utils/request.js` | axios 实例、拦截器、错误处理 |
| `router/index.js` | 路由表、懒加载、守卫 |
| `store/modules/user.js` | Vuex 用户模块（state/getters/mutations/actions） |
| `store/modules/permission.js` | 权限模块、动态路由 |
| `directive/permission.js` | 自定义指令做按钮级权限 |
| `views/login/index.vue` | 表单页、v-model、校验 |
| `views/gen/table/index.vue` | 复杂表格 + 弹窗组件 |

## 环境

- Node.js 16+（codegen-web 实测）
- 包管理：npm（Vue 3 推荐 pnpm/Vite）
- 真实项目可在 `D:/workspace/github/codegen-web` 下 `npm install && npm run dev` 运行
