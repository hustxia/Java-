# 第 2 章 快速开始：从 Hello World 到工程化

## 本章目标

读完本章，你将能够：

- 用 CDN 方式在单 HTML 文件里跑通第一个 Vue 3 应用。
- 用 Vite 脚手架创建一个标准的 Vue 3 工程，并理解目录结构。
- 看懂 `npm run dev` / `npm run build` 背后的命令。
- 对照 codegen-web 的 `src/main.js` 与 `App.vue`，理解 Vue 2 工程的入口长什么样，并写出 Vue 3 等价入口。

---

## 2.1 方式一：CDN 引入，零安装跑起来

学任何框架，第一步都是"先看到它动起来"。最快的方式是 CDN——不需要 Node、不需要安装，一个 `.html` 文件双击即可。

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <title>Vue 3 Hello</title>
  <!-- 引入 Vue 3 全局构建版，会暴露全局变量 Vue -->
  <script src="https://unpkg.com/vue@3/dist/vue.global.js"></script>
</head>
<body>
  <div id="app">{{ greeting }}</div>

  <script>
    const { createApp, ref } = Vue        // 从全局 Vue 上解构 API
    createApp({                            // createApp 创建应用实例
      setup() {
        const greeting = ref('Hello Vue 3!')  // ref 包裹字符串，模板自动解包
        return { greeting }                    // 返回后模板才能用
      }
    }).mount('#app')                       // 挂载到页面上的 #app 容器
  </script>
</body>
</html>
```

要点：Vue 3 用 `createApp().mount('#app')` 启动；数据通过 `setup()` 返回给模板。注意 **CDN 方式只适合学习和演示**，真实项目要用工程化方案。

## 2.2 方式二：Vite 创建标准工程

Vite 是 Vue 官方推荐的新一代构建工具，特点是"开发时秒级启动、按需编译"。创建工程只需一行：

```bash
# 创建工程，按提示选择 Vue + JavaScript
npm create vite@latest my-vue-app

# 进入目录并安装依赖
cd my-vue-app
npm install

# 启动开发服务器（默认 http://localhost:5173）
npm run dev
```

`npm create vite@latest` 会让你选择模板（Vue / React 等）和语言（TS / JS）。本书主线用 **Vue + JavaScript**，降低初学门槛；后续章节会自然过渡到更工程化的写法。

### 2.2.1 Vite 工程的目录结构

```text
my-vue-app/
├── index.html          # 入口 HTML，含 <div id="app"></div>
├── package.json        # 依赖与脚本（dev/build/preview）
├── vite.config.js      # Vite 配置（插件、别名、端口等）
└── src/
    ├── main.js         # 应用入口：createApp(App).mount('#app')
    ├── App.vue         # 根组件
    └── components/     # 可复用的子组件
```

`index.html` 里只有一个空容器 `<div id="app"></div>`，真正的界面由 `src/main.js` 挂载的 `App.vue` 渲染出来。这种"HTML 只管壳，JS 管内容"的结构，是工程化的标准姿态。

### 2.2.2 常用脚本

```bash
npm run dev      # 启动开发服务器（热更新）
npm run build    # 打包到 dist/，用于部署生产
npm run preview  # 本地预览打包后的产物
```

---

## 2.3 真实项目对照：codegen-web 用什么脚手架

我们的真实案例 codegen-web 是一个更"老派"但依然常见的工程，它用 **vue-cli** 而非 Vite。看它的 `package.json`：

> 真实代码来自 `package.json` 的 `scripts` 与依赖：

```json
{
  "scripts": {
    "serve": "vue-cli-service serve",
    "build": "vue-cli-service build",
    "build:prod": "vue-cli-service build --mode production",
    "lint": "vue-cli-service lint"
  },
  "devDependencies": {
    "@vue/cli-service": "~5.0.8"
  }
}
```

注意两个差异：

- **命令名不同**：Vue 3 + Vite 用 `npm run dev`，codegen-web（vue-cli）用 `npm run serve`。
- **底层不同**：vue-cli 基于 Webpack（配置重、启动慢）；Vite 基于 esbuild + 原生 ESM（启动快）。两者"行为都是启动开发服务器"，但技术内核已换代。

> 经验：你进公司接手老项目时，先看 `package.json` 的 `scripts` 和 `devDependencies`，一眼就能判断它是 Vite 还是 vue-cli，避免用错命令白等半天。

## 2.4 最小的单文件组件：Vue 3 vs codegen-web

单文件组件（`.vue` 文件）是 Vue 的标志性写法。我们把"入口"这一层对照看清楚。

### 2.4.1 Vue 3 最小入口

**`src/main.js`**：

```js
import { createApp } from 'vue'   // 引入 createApp
import App from './App.vue'       // 引入根组件
import './style.css'              // 全局样式

createApp(App).mount('#app')      // 创建并挂载
```

**`src/App.vue`**（根组件，通常放顶层布局或路由出口）：

```vue
<script setup>
import HelloWorld from './components/HelloWorld.vue'
</script>

<template>
  <HelloWorld msg="欢迎来到 Vue 3" />
</template>
```

### 2.4.2 codegen-web 的真实入口

> 真实代码来自 `src/main.js`：

```js
import Vue from 'vue'
import ElementUI from 'element-ui'      // 引入 Element UI 组件库
import 'element-ui/lib/theme-chalk/index.css'
import App from './App.vue'
import router from './router'
import store from './store'

Vue.use(ElementUI, { size: 'medium' })   // 全局注册 Element UI 插件
Vue.config.productionTip = false

new Vue({                                // Vue 2 用 new Vue() 而非 createApp
  router,
  store,
  render: h => h(App)                    // render 函数渲染根组件
}).$mount('#app')                        // 挂载到 #app
```

> 真实代码来自 `src/App.vue`：

```vue
<template>
  <div id="app">
    <router-view />                       <!-- 路由出口：根据 URL 渲染不同页面 -->
  </div>
</template>

<script>
export default {
  name: 'App'                            // Vue 2 选项式：用 export default 导出对象
}
</script>
```

### 2.4.3 对照小结

| 维度 | Vue 3（Vite） | codegen-web（Vue 2.7 + vue-cli） |
| --- | --- | --- |
| 启动 | `createApp(App).mount()` | `new Vue({...}).$mount()` |
| 组件导出 | `<script setup>` 编译产物 / `export default` | `export default { ... }` 选项对象 |
| 根组件 | `App.vue` 直接放内容 | `App.vue` 仅放 `<router-view/>` |
| UI 库 | 按需引入（如 Element Plus） | `Vue.use(ElementUI)` 全局注册 |
| 插件 | 路由/状态通过 `app.use()` | 通过根实例 `router`/`store` 选项传入 |

**Vue 3 等价写法**：把 codegen-web 的入口改成 Vue 3，核心就是 `new Vue(...)` → `createApp(App)`、`Vue.use(ElementUI)` → `app.use(ElementPlus)`、`$mount` → `.mount`。骨架几乎一一对应。

---

## 本章小结

- CDN 引入适合"零安装热个身"，但真实项目要用工程化方案。
- Vite 是 Vue 3 官方推荐脚手架：`npm create vite@latest` → `npm install` → `npm run dev`；目录核心是 `index.html` + `src/main.js` + `src/App.vue`。
- codegen-web 用 vue-cli（`npm run serve`），底层 Webpack；命令名和内核都和 Vite 不同，但"启动开发服务器"的目标一致。
- 入口对照：Vue 3 用 `createApp().mount()`，Vue 2 用 `new Vue().$mount()`；App.vue 在 Vue 2 里常只放 `<router-view/>`。

## ⚠️ 踩坑提示

**别把 `npm run dev` 和 `npm run serve` 混用。** 它们由 `package.json` 的 `scripts` 决定，不是 Vue 的固定命令。在 Vite 项目里敲 `npm run serve` 会直接报错 `Missing script: "serve"`；在 vue-cli 项目里敲 `npm run dev` 同样找不到脚本。接手任何陌生前端工程，**第一件事永远是打开 `package.json` 看 `scripts` 里到底叫什么**。
