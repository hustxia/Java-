# 第 10 章 Vue 生命周期

## 本章目标

- 理解组件从「创建」到「卸载」的完整生命周期，掌握 8 个常用钩子。
- 记住 Vue 2 的 `beforeDestroy` / `destroyed` 在 Vue 3 已更名为 `beforeUnmount` / `unmounted`。
- 清楚父子组件钩子的执行顺序，以及在服务端渲染（SSR）中使用钩子的边界。
- 通过真实项目 codegen-web 的监控页，看懂「资源清理」这一生命周期最典型的用法。

## 一、Vue 3 的 8 个生命周期钩子

Vue 3 组件实例在创建后会经历一系列「关键时刻」，框架在每段时间点调用对应的**生命周期钩子**。在 `<script setup>` 中，我们用 `onXxx` 这个组合式 API 来注册钩子；在 Options API（Vue 2 风格）中则直接写同名方法。

| 阶段 | Options API | Composition API（`onXxx`） | 触发时机 |
| --- | --- | --- | --- |
| 创建 | `beforeCreate` / `created` | 直接在 `setup()` 里写 | 实例初始化、响应式数据就绪 |
| 挂载 | `beforeMount` | `onBeforeMount` | 渲染前，DOM 尚未生成 |
| 挂载 | `mounted` | `onMounted` | 模板已渲染进 DOM，可访问 `$refs` |
| 更新 | `beforeUpdate` | `onBeforeUpdate` | 数据变化、虚拟 DOM 打补丁前 |
| 更新 | `updated` | `onUpdated` | 重新渲染完成，DOM 已更新 |
| 卸载 | `beforeUnmount` | `onBeforeUnmount` | 组件即将卸载，仍可访问实例 |
| 卸载 | `unmounted` | `onUnmounted` | 组件已卸载，子组件与事件监听均销毁 |
| 缓存 | `activated` / `deactivated` | `onActivated` / `onDeactivated` | 被 `<keep-alive>` 包裹时进出缓存 |

```vue
<script setup>
import { onMounted, onUpdated, onUnmounted, ref } from 'vue'

const count = ref(0)

onMounted(() => {
  // 模板已渲染，可操作 DOM、启动定时器、发起首屏请求
  console.log('组件挂载完成')
})

onUpdated(() => {
  // 注意：这里读取的 DOM 是最新渲染结果
  console.log('count 变成了', count.value)
})

onUnmounted(() => {
  // 清理副作用：定时器、事件监听、第三方实例
  console.log('组件被卸载')
})
</script>
```

`beforeCreate` 与 `created` 在组合式里**没有对应的 `onXxx`**，因为 `setup()` 本身就在这两个阶段之间执行，所有初始化逻辑直接写在 `setup()` 顶层即可。

## 二、重点对比：destroyed 改名为 unmounted

这是从 Vue 2 升级到 Vue 3 最容易踩的坑之一。Vue 2 中组件销毁阶段的钩子是 `beforeDestroy` 和 `destroyed`；**Vue 3 把它们更名为 `beforeUnmount` 和 `unmounted`**，语义更贴近「卸载」而非「销毁」。

```js
// Vue 2（Options API）—— 旧写法
export default {
  beforeDestroy() { /* 卸载前清理 */ },
  destroyed() { /* 已卸载 */ }
}
```

```js
// Vue 3（Composition API）—— 新写法
import { onBeforeUnmount, onUnmounted } from 'vue'
onBeforeUnmount(() => { /* 卸载前清理 */ })
onUnmounted(() => { /* 已卸载 */ })
```

⚠️ 如果你用 Vue 3 但写了 `beforeDestroy`，Vue 会给出警告并且钩子**不会执行**——这是迁移时最隐蔽的 bug 来源。同理 `destroyed` 也不会触发。

## 三、父子组件钩子顺序

理解钩子顺序对排查「子组件拿不到父组件数据」「定时器没清干净」很有帮助。

**初次挂载时**：父 `beforeMount` → 子 `beforeMount` → 子 `mounted` → 父 `mounted`。
也就是说，**子组件的 `mounted` 先于父组件的 `mounted` 执行**。如果父组件在 `mounted` 里才给子组件传数据，子组件第一次渲染用的是初始值，可依赖 `watch` 或 `props` 默认响应。

**卸载时**：父 `beforeUnmount` → 子 `beforeUnmount` → 子 `unmounted` → 父 `unmounted`。
子组件一定先于父组件被卸载，所以「父组件在 `onUnmounted` 里清理共享资源」是安全的。

## 四、SSR 中的生命周期注意

服务端渲染（如 Nuxt / Vue SSR）只在 Node 端运行**创建阶段**（`setup`、`beforeCreate`、`created`），**永远不会执行 `mounted`、`beforeUnmount` 等依赖浏览器 DOM 的钩子**，因为服务端没有 `window` / `document`。

- 访问浏览器的逻辑（定时器、`addEventListener`、`echarts.init`）必须放在 `onMounted` 里，它只在客户端执行。
- 若要做服务端数据预取，Vue 3 提供了 `onServerPrefetch`；Vue 2 用的是 `serverPrefetch`。
- 不要在 `setup` 顶层直接 `window.xxx`，否则 SSR 会抛 `window is not defined`。

## 五、真实项目对照：监控页的资源清理

下面这段来自 codegen-web 的 `src/views/monitor/index.vue`（Vue 2.7），是生命周期「资源清理」的教科书范例。组件在 `mounted` 里启动轮询、加载 ECharts、注册全局事件；在 `beforeDestroy` 里**逐一反向清理**，避免内存泄漏与崩溃。

先看 `mounted()`（源码 `src/views/monitor/index.vue:307-323`）：

```js
mounted() {
  // ① 注册全局事件监听：标签页可见性 + 窗口缩放
  document.addEventListener('visibilitychange', this.handleVisibility)
  window.addEventListener('resize', this.handleResize)
  // ② 按需异步加载 ECharts（独立 chunk，失败仅降级图表区）
  loadEcharts()
    .then(echarts => {
      this.echarts = echarts
      this.$nextTick(() => {        // ③ 等 DOM 就绪再初始化图表
        this.initCharts()
        this.renderCharts()
      })
    })
    .catch(() => { this.chartError = true })
  // ④ 立即拉一次数据
  this.fetchAll()
  // ⑤ 启动 5 秒轮询定时器
  this.startTimer()
}
```

再看 `beforeDestroy()`（源码 `src/views/monitor/index.vue:324-334`），它和 `mounted` 严格对称：

```js
beforeDestroy() {
  // ① 停掉轮询，否则组件销毁后定时器仍在回调已销毁实例 -> 报错
  this.stopTimer()
  // ② 移除在 mounted 注册的事件监听（不移除会泄漏、且回调访问空实例）
  document.removeEventListener('visibilitychange', this.handleVisibility)
  window.removeEventListener('resize', this.handleResize)
  // ③ dispose 掉 ECharts 实例，释放 canvas / 内存
  Object.keys(this.charts).forEach(key => {
    if (this.charts[key]) {
      this.charts[key].dispose()   // 关键：否则图表实例常驻内存
      this.charts[key] = null
    }
  })
}
```

> 对照要点：在 Vue 2 这里用的是 `beforeDestroy`；迁移到 Vue 3 后**必须改名为 `onBeforeUnmount`**，否则这三步清理全都不会执行，定时器会继续跑、Echarts 实例无法释放。

对应的 Vue 3 `<script setup>` 等价写法（用 `onMounted` / `onBeforeUnmount`）：

```vue
<script setup>
import { onMounted, onBeforeUnmount, ref, nextTick } from 'vue'

const echarts = ref(null)
const chartError = ref(false)
const charts = ref({ jvm: null, http: null })
let timer = null

function startTimer() { /* 同 Vue 2 的 startTimer，用闭包变量 */ }
function stopTimer() { if (timer) { clearInterval(timer); timer = null } }
function handleVisibility() { /* ... */ }
function handleResize() { /* ... */ }
async function loadEchartsAndInit() {
  try { echarts.value = await loadEcharts() ; await nextTick(); initCharts() }
  catch { chartError.value = true }
}

onMounted(() => {
  document.addEventListener('visibilitychange', handleVisibility)
  window.addEventListener('resize', handleResize)
  loadEchartsAndInit()
  fetchAll()
  startTimer()
})

onBeforeUnmount(() => {        // ★ Vue 2 的 beforeDestroy 在这里
  stopTimer()
  document.removeEventListener('visibilitychange', handleVisibility)
  window.removeEventListener('resize', handleResize)
  Object.values(charts.value).forEach(c => c && c.dispose())
})
</script>
```

## 本章小结

- Vue 3 用 `onXxx` 组合式 API 注册生命周期钩子，替代 Options API 的同名方法。
- **最关键的迁移点**：`beforeDestroy` → `onBeforeUnmount`、`destroyed` → `onUnmounted`。
- 挂载顺序「父 beforeMount → 子 mounted → 父 mounted」；卸载顺序相反，子先父后。
- SSR 只跑创建阶段，所有浏览器相关逻辑（DOM、定时器、Echarts）必须放进 `onMounted`。
- 生命周期的核心职责之一是**清理副作用**：定时器、事件监听、第三方实例（如 ECharts）务必在 `onBeforeUnmount` 里对称销毁。

## ⚠️ 踩坑提示

1. **钩子改名忘记同步**：Vue 3 中写 `beforeDestroy` 不会报错（只是警告），但钩子体永不执行，定时器、Echarts 实例持续泄漏，页面切走再切回会越跑越卡甚至崩溃。
2. **在 `setup` 顶层访问 DOM / `window`**：`setup` 在 SSR 也会执行，直接 `window.addEventListener` 会导致服务端渲染失败。务必把这些放进 `onMounted`。
3. **`onUnmounted` 里才清定时器**：太晚了——`onUnmounted` 执行时子组件已被卸载，若定时器在 `onUnmounted` 前触发回调访问已销毁实例同样报错。清理动作优先放在 `onBeforeUnmount`。
