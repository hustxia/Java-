# 第 11 章 组合式函数：把逻辑抽成 useXxx

## 本章目标

- 理解「组合式函数（Composable）」是什么，以及它为什么能取代 Vue 2 的 `mixins`。
- 掌握用 `ref` / `reactive` + 生命周期钩子封装「有状态逻辑」的标准套路。
- 通过 `useFetch`、`useInterval` 两个完整示例，建立可复用的封装直觉。
- 把真实项目 codegen-web 监控页的「轮询 + ECharts + 停滞判断」重构成 `useMonitorPolling`，体会组合式函数的威力。

## 一、什么是组合式函数

组合式函数（惯例以 `use` 开头，如 `useFetch`、`useMouse`）是一个**返回响应式状态与方法的函数**，把「带状态的业务逻辑」从组件里抽出来，做到跨组件复用。它本质是「利用闭包 + 组合式 API 的封装」，不需要像 mixins 那样混入组件选项。

核心特征：
- 内部用 `ref` / `reactive` 持有状态，用 `onMounted` / `onUnmounted` 等管理副作用。
- 通过 `return` 把状态和方法交还给组件，组件在 `<script setup>` 里解构即用。
- 可接收参数、可组合（一个 composable 内部调用另一个 composable）。

## 二、对比 Vue 2 的 mixins 缺陷

Vue 2 时代复用逻辑主要靠 `mixins`，但它有三个公认痛点，Vue 3 的 composable 全部解决：

| 问题 | mixins（Vue 2） | composable（Vue 3） |
| --- | --- | --- |
| 命名冲突 | 多个 mixin 的同名字段**静默覆盖**，难排查 | 解构时自己命名，冲突一眼可见 |
| 来源不明 | 模板里 `$xxx` 不知来自哪个 mixin | 变量来自哪段 `useXxx()` 调用，清晰可追溯 |
| 耦合性 | mixin 隐式依赖组件 data 中的字段 | 显式通过参数传入，依赖可视化 |

```js
// Vue 2 mixins：来源模糊、易冲突
export const myMixin = {
  data() { return { loading: false } },        // 与组件 data 同名会被覆盖
  methods: { fetch() { /* 隐式依赖 this.xxx */ } }
}
```

```js
// Vue 3 composable：来源清晰、显式传参
export function useFetch(url) {
  const data = ref(null)
  const loading = ref(false)
  async function fetchData() { /* ... */ }
  return { data, loading, fetchData }   // 调用方自己解构命名
}
```

## 三、示例一：useFetch

一个最小可用的「数据请求」组合式函数：内部维护 `data` / `error` / `loading`，并自动在卸载时避免 setState。

```js
// composables/useFetch.js
import { ref, isRef, unref, watchEffect, onUnmounted } from 'vue'

export function useFetch(url) {
  const data = ref(null)
  const error = ref(null)
  const loading = ref(false)
  let active = true                       // 防止组件卸载后还写入响应式状态

  async function doFetch(target) {
    loading.value = true
    error.value = null
    try {
      const res = await fetch(unref(target))   // unref 兼容 ref / 普通值
      data.value = await res.json()
    } catch (e) {
      error.value = e
    } finally {
      if (active) loading.value = false
    }
  }

  // 自动追踪 url（它可能是 ref，url 变化即重新请求）
  if (isRef(url)) {
    watchEffect(() => { if (url.value) doFetch(url) })
  } else {
    doFetch(url)
  }

  onUnmounted(() => { active = false })   // 清理：标记失效，避免内存泄漏

  return { data, error, loading, refetch: () => doFetch(url) }
}
```

使用：

```vue
<script setup>
import { useFetch } from '@/composables/useFetch'
const { data, loading, error } = useFetch('/api/user')
</script>
```

## 四、示例二：useInterval

把「定时轮询」封装成可暂停 / 恢复的 composable，并**自动在卸载时清理定时器**（这正是生命周期一章强调的清理职责）。

```js
// composables/useInterval.js
import { ref, onMounted, onUnmounted } from 'vue'

export function useInterval(callback, delay = 5000) {
  const isActive = ref(false)
  let timer = null

  function start() {
    stop()                                 // 先停后起，避免重复
    timer = setInterval(callback, delay)
    isActive.value = true
  }
  function stop() {
    if (timer) { clearInterval(timer); timer = null }
    isActive.value = false
  }

  onMounted(start)                         // 挂载即开始轮询
  onUnmounted(stop)                        // 卸载自动停止，绝不泄漏

  return { isActive, start, stop }
}
```

## 五、真实项目对照：把监控页重构为 useMonitorPolling

codegen-web 的 `src/views/monitor/index.vue`（Vue 2.7）把「轮询 `+` ECharts 加载 `+` 停滞判断」全堆在组件里（见源码 `src/views/monitor/index.vue:188-492`）。这些逻辑和模板无关，非常适合抽成 composable。下面给出 Vue 3 重构版（仅展示组合式函数骨架，关键行注释）：

```js
// composables/useMonitorPolling.js
import { ref, onMounted, onBeforeUnmount, nextTick } from 'vue'
import { getMonitorOverview, getMonitorSeries, getMonitorHttp, getMonitorBusiness } from '@/api/monitor'

const POLL_MS = 5000

export function useMonitorPolling() {
  // —— 响应式状态（对应 Vue 2 的 data / computed 派生）——
  const overview = ref(emptyOverview())
  const http = ref(emptyHttp())
  const business = ref(emptyBusiness())
  const series = ref({ heap: [], threads: [], qps: [], p95: [] })
  const stalled = ref(false)                 // 采样停滞标记
  const loading = ref(false)
  const chartError = ref(false)
  const echarts = ref(null)
  const charts = ref({ jvm: null, http: null })

  let timer = null
  const fetchAll = async () => { /* 同源码 fetchAll，把 this.xxx 换成上面的 ref */ }
  const initCharts = () => { /* ... */ }
  const renderCharts = () => { /* ... */ }

  // —— 停滞判断：超过周期无新样本即告警（原 handleVisibility 同思路）——
  // —— 事件处理：可见性切换停/启轮询、窗口缩放 resize 图表 ——
  function handleVisibility() { /* document.hidden 时 stop，否则 fetch+start */ }
  function handleResize() { Object.values(charts.value).forEach(c => c && c.resize()) }

  // —— 生命周期：与源码 mounted / beforeDestroy 一一对应 ——
  onMounted(() => {
    document.addEventListener('visibilitychange', handleVisibility)
    window.addEventListener('resize', handleResize)
    loadEcharts().then(e => { echarts.value = e; nextTick(() => { initCharts(); renderCharts() }) })
      .catch(() => { chartError.value = true })
    fetchAll()
    start()
  })

  onBeforeUnmount(() => {                    // ★ 原 beforeDestroy 改名而来
    stop()
    document.removeEventListener('visibilitychange', handleVisibility)
    window.removeEventListener('resize', handleResize)
    Object.values(charts.value).forEach(c => c && c.dispose())
  })

  function start() { stop(); timer = setInterval(fetchAll, POLL_MS) }
  function stop() { if (timer) { clearInterval(timer); timer = null } }

  return { overview, http, business, series, stalled, loading, chartError }
}
```

组件中只需一行调用，模板和 Vue 2 几乎不变：

```vue
<script setup>
import { useMonitorPolling } from '@/composables/useMonitorPolling'
// 解构出来的名字即来源，没有 mixin 的「来源不明」问题
const { overview, http, business, series, stalled, loading, chartError } = useMonitorPolling()
</script>
```

> 重构收益：监控逻辑可以单独测试、可以在别的页面（如大屏）复用，组件文件从近 500 行缩到模板 + 一行 `useXxx`。这正是组合式函数对比 mixins 最直观的优势。

## 本章小结

- 组合式函数是以 `use` 开头的函数，内部持有响应式状态、管理副作用，通过 `return` 暴露给组件。
- 它解决了 mixins 的命名冲突、来源不明、隐式耦合三大缺陷。
- 经典封装公式：`ref/reactive` 存状态 + `onMounted/onUnmounted` 管生命周期 + `return` 暴露接口。
- 真实项目里「轮询 + ECharts + 停滞判断」这类与 UI 解耦的逻辑，抽成 `useMonitorPolling` 后可读性与复用性大幅提升。

## ⚠️ 踩坑提示

1. **composable 里不要直接访问 `this`**：组合式函数没有组件实例，`this` 是 `undefined`。所有状态必须用 `ref` / `reactive` 显式声明。
2. **只在该用到的组件里调用**：组合式函数依赖「调用时的当前组件实例」来绑定生命周期。务必在 `setup` / `<script setup>` 顶层调用，不要在普通函数或 `setTimeout` 回调里调用，否则 `onMounted` 等钩子绑定失败。
3. **忘记卸载清理**：composable 里起的定时器、事件监听、ECharts 实例，必须在 `onBeforeUnmount` 里清掉；否则组件销毁后定时器继续跑，控制台狂报「实例已卸载」。
