# 第 1 章 为什么要学 Vue

## 本章目标

读完本章，你将能够：

- 说清楚前端框架解决了什么"原生开发痛点"，以及 jQuery → Angular/React/Vue 的演进脉络。
- 理解 Vue 的"渐进式"设计哲学，以及它为什么对初学者友好。
- 区分 Vue 2.7 与 Vue 3 的关系，明白老项目也能用上部分新特性。
- 理解本书"Vue 3 主线 + codegen-web 真实案例对照"的双轨写法的用意。

---

## 1.1 框架出现之前：我们怎么写页面

如果你写过纯 HTML + CSS + JavaScript，一定遇到过这样的场景：点击一个按钮，要改十几个地方的 DOM，要自己管理数据和视图谁先谁后。

```js
// 没有框架时，数据与视图是割裂的
const count = 0
document.getElementById('btn').onclick = () => {
  count++                                   // 改数据
  document.getElementById('num').innerText = count  // 手动同步到视图
  document.getElementById('tip').innerText = count > 3 ? '够了' : '继续'
}
```

问题在哪？**数据变了，你得亲手动 DOM 去"追"数据**。页面一复杂，这种"数据 → 视图"的同步逻辑会散落得到处都是，难维护、易出 bug。

这里藏着一对重要概念，请务必分清：

- **命令式（Imperative）**：你用代码一步步"命令"计算机怎么做，例如 `element.innerText = count`。关注"过程"。
- **声明式（Declarative）**：你只"声明"视图应该长什么样（由数据决定），框架负责把它变成现实。关注"结果"。

```html
<!-- 声明式：我只说"这里显示 count"，至于怎么更新 DOM 是框架的事 -->
<div>{{ count }}</div>
```

前端框架的核心使命只有一个：**让"数据的变化"自动反映到"视图"，你只管改数据，剩下的交给框架**。这就是"响应式"思想的起点。从命令式到声明式，是人类从"手洗衣服"到"用洗衣机"的跨越——你描述目标，机器处理过程。

## 1.2 演进脉络：jQuery → Angular → React → Vue

| 阶段 | 代表 | 它解决了什么 | 遗留的问题 |
| --- | --- | --- | --- |
| 刀耕火种 | 原生 JS | —— | 手动操作 DOM，同步成本高 |
| 胶水层 | jQuery | 统一 API、链式调用、`$()` 选择器 | 仍是"命令式"手动改 DOM |
| 全家桶 | AngularJS (Google) | 双向绑定、指令、依赖注入 | 学习曲线陡、性能随规模下降 |
| 组件化 | React (Facebook) | 组件 + 虚拟 DOM + 单向数据流 | JSX 心智负担、样板代码多 |
| 渐进式 | Vue (尤雨溪) | 模板语法像写 HTML、上手快、按需采用 | 早期生态不如前两者 |

**关键认知**：框架不是互相取代，而是"在易用性、性能、约束度"上做不同取舍。Vue 选择了一条"模板友好、渐进式采用"的路线——你可以只用核心库渲染一个页面，也可以逐步引入路由、状态管理，最后搭成完整应用。

## 1.3 Vue 的设计哲学：渐进式框架

"渐进式"是 Vue 最常被提及、也最容易被误解的词。它的意思是：

- **核心小**：`vue` 包只负责视图层（声明式渲染 + 组件）。
- **按需叠加**：你需要路由就装 `vue-router`，需要全局状态就装 Pinia/Vuex，需要构建工具就上 Vite。
- **不强制**：你不必像某些框架那样，一开始就接受一整套工程约束。

```html
<!-- 渐进式的极致：只引入一个 vue 文件，就能开始用 -->
<script src="https://unpkg.com/vue@3/dist/vue.global.js"></script>
<div id="app">{{ message }}</div>
```

这种"从 CDN 一行引入，到完整工程化"的平滑过渡，正是 Vue 对初学者友好的根本原因。本书后面会带你走完这条完整路径。

## 1.4 真实项目对照：codegen-web 是什么

为了不让你学完只会写玩具 Demo，本书贯穿一个**真实的企业级后台项目 codegen-web**。它用一组"老而成熟"的技术栈：

> 真实代码来自 `package.json`：

```json
{
  "dependencies": {
    "vue": "^2.7.16",
    "vue-router": "^3.6.5",
    "vuex": "^3.6.2",
    "element-ui": "^2.15.14",
    "echarts": "^5.5.0",
    "axios": "^1.7.4"
  }
}
```

注意这一行：**`"vue": "^2.7.16"`**。它是 Vue 2 的最后一个小版本，但你别急着替它"落伍"——这正是理解 Vue 3 的最佳参照物。

## 1.5 Vue 2.7 与 Vue 3 的关系

很多人困惑："我学 Vue 3，为什么书里老提 Vue 2？"这里必须把关系讲透。

**Vue 2.7（代号 "Naruto"）做了一次关键的向后移植**：把 Vue 3 的 Composition API（`ref`、`reactive`、`computed`、`setup`）等核心能力，移植回了 Vue 2。所以一个 Vue 2.7 的老项目，**也能写 `setup()` 函数、用 `ref`**。

但请记住结论：

- **Vue 2.7 是"兼容兜底"，不是未来方向。** Vue 2 官方已于 2023 年底停止维护（EOL）。
- **Vue 3 才是主线**：更好的性能（Proxy 响应式）、更小的体积、Composition API、`<script setup>` 语法糖、对 TypeScript 的原生友好。
- **为什么本书双轨讲**：你今天进入职场，极可能接手的是 Vue 2.x（或 2.7）的老项目（比如 codegen-web），而不是从零的 Vue 3。学会"主线用 Vue 3 标准写法，同时能读懂并迁移老项目的 Options API 代码"，才是真本事。

> 一句话总结：**Vue 3 是你要写向未来的代码；Vue 2.7 是你要能读懂、能维护、能迁移的遗产。**

## 1.6 第一次并排：同一个需求，两种写法

为了让你对"双轨"有肌肉记忆，这里提前看一眼同一段"点击计数"在 Vue 3 与 Vue 2.7 下的样子。先别纠结语法细节，感受差异即可——第 2、3、4 章会逐一拆解。

**Vue 3 主线写法（`<script setup>` + `ref`）**：

```vue
<script setup>
import { ref } from 'vue'          // 从 vue 引入 ref
const count = ref(0)              // 基本类型用 ref 包裹，模板里自动解包
function add() { count.value++ }  // 脚本里改值要写 .value
</script>

<template>
  <button @click="add">点了 {{ count }} 次</button>
</template>
```

**codegen-web 用的 Vue 2.7 Options API 写法（等价行为）**：

```js
export default {
  data() {                         // 数据集中在 data() 返回的对象里
    return { count: 0 }
  },
  methods: {                       // 方法集中在 methods
    add() { this.count++ }         // 通过 this 访问，不用 .value
  }
}
```

看出门道了吗？**两者行为完全一致（点一下加一），但 Vue 3 把"状态"和"逻辑"按功能聚在一起，Vue 2 按"选项类型"（data/methods/computed）横向切分**。当组件变大时，Vue 3 的聚合方式更利于复用与维护——这正是 Composition API 的设计动机。

## 1.7 为什么这本书"双轨讲"

本书的约定如下，请先记住，后续每章都会遵守：

1. **主线代码一律用 Vue 3 标准写法**：`ref` / `reactive` / `<script setup>` / Pinia / Vue Router 4 / Vite。
2. **每章设"真实项目对照"小节**：展示 codegen-web（Vue 2.7 Options API）的真实代码，并标注 Vue 3 的等价写法。
3. **不架空**：对照代码都来自本机真实源码 `D:/workspace/github/codegen-web/src/` 下的文件，并注明来源。

这样做的好处：你既能写出现代化的 Vue 3 应用，又能在面试/工作中看懂公司里那套跑了很多年的 Vue 2 后台，并知道两者"行为一致、写法不同"的对应关系。

接下来，第 2 章我们就真正动手：先用 CDN 跑通第一个 Hello World 热热身，再用 Vite 搭起一个像样的工程；同时翻开 codegen-web 的 `src/main.js` 与 `App.vue`，看看一个真实 Vue 2 工程的入口长什么样。

---

## 本章小结

- 框架的本质是"数据变 → 视图自动变"，免去手动同步 DOM。
- 前端从 jQuery 的"手动胶水"，演进到组件化、虚拟 DOM 的现代框架；Vue 以"渐进式 + 模板友好"占据独特生态位。
- Vue 2.7 把 Composition API 向后移植，所以老项目也能用部分新特性；但 **Vue 3 才是未来，Vue 2 已停维护**。
- 本书双轨：主线学 Vue 3，对照读懂 codegen-web（Vue 2.7）真实源码，做到"会写新的、能维护旧的"。

## ⚠️ 踩坑提示

**不要把"Vue 2.7 能用 Composition API"误解为"Vue 2.7 = Vue 3"。** 二者底层响应式原理完全不同：Vue 2 用 `Object.defineProperty`（无法监听新增属性、数组索引赋值），Vue 3 用 `Proxy`。因此在 Vue 2.7 里你仍要遵守"给对象预先声明所有属性""数组用 `$set`"等老规矩，而 Vue 3 天然没有这些限制。本书第 4 章会专门对比这一差异。
