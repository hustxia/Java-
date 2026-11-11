# 第 15 章 UI 组件库与图表集成（Element Plus + ECharts）

## 本章目标

- 清楚 Vue 3 用 Element Plus、Vue 2 用 Element UI 的对应关系。
- 掌握常用布局 / 表单 / 表格 / 弹窗组件的使用套路。
- 学会 ECharts 按需引入（不进主包）、异步 chunk、init / setOption / dispose / resize 完整生命周期。
- 给图表加载失败做降级，避免「图表挂了整个页面白屏」。
- 通过 codegen-web 真实监控页 `src/views/monitor/index.vue`，逐节拆解「一个生产级监控页是怎么搭起来的」。

---

## 15.1 Element Plus（Vue 3） vs Element UI（Vue 2）

codegen-web 用的是 Vue 2.7 + Element UI（`src/main.js` 里 `Vue.use(ElementUI)`）。升级到 Vue 3 后，组件库要换成 **Element Plus**。两者标签名几乎一致，主要差别在：

| 维度 | Element UI（Vue 2） | Element Plus（Vue 3） |
| --- | --- | --- |
| 全量引入 | `import ElementUI from 'element-ui'` | `import ElementPlus from 'element-plus'` |
| 样式 | `element-ui/lib/theme-chalk/index.css` | `element-plus/dist/index.css` |
| 按需引入 | `babel-plugin-component` | `unplugin-vue-components` 自动导入 |
| 消息 API | `import { Message } from 'element-ui'` | `import { ElMessage } from 'element-plus'` |
| 作用域插槽 | `slot="header"` | `#header`（`v-slot`） |

也就是说，绝大多数 `<el-xxx>` 标签可以直接平移，但要改三处：样式路径、`Message/MessageBox` → `ElMessage/ElMessageBox`、具名插槽语法。

---

## 15.2 常用组件：布局 / 表单 / 表格 / 弹窗

```vue
<template>
  <!-- 布局：el-card 做卡片容器，header 用具名插槽 -->
  <el-card shadow="never">
    <template #header>系统概览</template>
    <el-table :data="rows" border v-loading="loading">
      <el-table-column prop="name" label="名称" />
      <el-table-column label="操作" width="120">
        <template #default="{ row }">
          <el-button size="small" @click="edit(row)">编辑</el-button>
        </template>
      </el-table-column>
    </el-table>
  </el-card>

  <!-- 弹窗 -->
  <el-dialog v-model="visible" title="编辑">
    <el-form :model="form">
      <el-form-item label="名称">
        <el-input v-model="form.name" />
      </el-form-item>
    </el-form>
  </el-dialog>
</template>
```

注意 Vue 3 里 `el-dialog` 用 `v-model="visible"`（替代 Vue 2 的 `:visible.sync`），`v-loading` 仍是 Element Plus 提供的指令，没变。

---

## 15.3 ECharts 集成：按需引入 + 异步 chunk

监控页有趋势图，但 ECharts 体积不小。生产实践是把 ECharts **拆成独立 chunk 异步加载**，首屏不背这个包。

```js
// 按需引入核心 + 折线图 + 必要组件，全部动态 import
let echartsLoader = null
function loadEcharts() {
  if (!echartsLoader) {
    echartsLoader = Promise.all([
      import('echarts/core'),
      import('echarts/charts'),     // 只引 LineChart，不引全量
      import('echarts/components'), // Grid/Tooltip/Legend 等
      import('echarts/renderers')   // CanvasRenderer
    ]).then(([core, charts, components, renderers]) => {
      const echarts = core.default || core
      echarts.use([
        charts.LineChart,
        components.GridComponent,
        components.TooltipComponent,
        components.LegendComponent,
        renderers.CanvasRenderer
      ])
      return echarts
    }).catch(err => { echartsLoader = null; throw err })
  }
  return echartsLoader
}
```

---

## 15.4 图表生命周期：init / setOption / resize / dispose

```js
import { onMounted, onBeforeUnmount, ref, nextTick } from 'vue'

const jvmChart = ref(null)
let chart = null

onMounted(async () => {
  const echarts = await loadEcharts()
  await nextTick()
  chart = echarts.init(jvmChart.value) // init 必须在 DOM 就绪后
  chart.setOption({ /* 配置 */ })
  window.addEventListener('resize', handleResize)
})

function handleResize() { chart?.resize() } // 容器尺寸变化要 resize

onBeforeUnmount(() => {
  window.removeEventListener('resize', handleResize)
  chart?.dispose() // 必须 dispose，否则内存泄漏
  chart = null
})
```

四个动作缺一不可：`init`（挂载）、`setOption`（渲染/更新）、`resize`（响应式）、`dispose`（卸载时销毁）。Vue 2 对应的是 `mounted / beforeDestroy` 与 `this.$refs.xxx`。

---

## 15.5 真实项目对照：codegen-web 监控页

真实文件 `src/views/monitor/index.vue`（Vue 2 + Options API）把上面所有要点都落地了。下面逐节剖析。

### 15.5.1 模板：el-alert / el-tag / el-card / el-table / el-progress / el-button

```html
<!-- 采样停滞告警（el-alert + slot="title"） -->
<el-alert v-if="stalled" type="error" :closable="false" show-icon class="stall-alert">
  <span slot="title">采样停滞：最近一次采样在 {{ lastSampleText }}…</span>
</el-alert>

<!-- 状态条：el-tag 标记采样进度，el-button 触发刷新 -->
<el-tag size="mini" type="info">已采样 {{ overview.sampledPoints }} / {{ overview.bufferSize }} 点</el-tag>
<el-button size="mini" icon="el-icon-refresh" :loading="loading" @click="fetchAll">立即刷新</el-button>

<!-- 指标卡里用 el-progress 画堆内存进度条 -->
<el-progress :percentage="heapPercent" :show-text="false" :stroke-width="5" :color="heapColor" />

<!-- 慢接口：el-card + el-table，header 用 slot="header" -->
<el-card shadow="never" class="slow-card">
  <div slot="header" class="card-head"><span>慢接口 Top 10</span></div>
  <el-table v-loading="loading" :data="http.topSlow" size="small" border>
    <el-table-column prop="uri" label="URI" min-width="300">
      <template slot-scope="{ row }"><span class="mono">{{ row.uri }}</span></template>
    </el-table-column>
    <el-table-column label="平均耗时" width="130">
      <template slot-scope="{ row }">
        <span class="num" :class="slowClass(row.avgMs)">{{ fmtMs(row.avgMs) }}</span>
      </template>
    </el-table-column>
  </el-table>
</el-card>
```

**Element Plus 等价写法**：`slot="header"` → `#header`，`slot-scope="{ row }"` → `#default="{ row }"`，`el-icon-refresh` → `el-icon` 包裹或新版图标组件，`el-progress / el-tag / el-table` 标签名不变。

### 15.5.2 脚本：按需懒加载 ECharts、mounted 里 initCharts

```js
// 真实代码：用 import() 把 echarts 拆成独立 chunk（webpackChunkName: "echarts"）
function loadEcharts() {
  if (!echartsLoader) {
    echartsLoader = Promise.all([
      import(/* webpackChunkName: "echarts" */ 'echarts/core'),
      import(/* webpackChunkName: "echarts" */ 'echarts/charts'),
      import(/* webpackChunkName: "echarts" */ 'echarts/components'),
      import(/* webpackChunkName: "echarts" */ 'echarts/renderers')
    ]).then(([core, charts, components, renderers]) => {
      const echarts = core.default || core
      echarts.use([charts.LineChart, components.GridComponent,
        components.TooltipComponent, components.LegendComponent, renderers.CanvasRenderer])
      return echarts
    }).catch(err => { echartsLoader = null; throw err })
  }
  return echartsLoader
}

// mounted：加载 ECharts → nextTick → initCharts → 首帧渲染
mounted() {
  document.addEventListener('visibilitychange', this.handleVisibility)
  window.addEventListener('resize', this.handleResize)
  loadEcharts().then(echarts => {
    this.echarts = echarts
    this.$nextTick(() => { this.initCharts(); this.renderCharts() })
  }).catch(() => { this.chartError = true }) // 加载失败降级
  this.fetchAll()
  this.startTimer()
}
```

### 15.5.3 beforeDestroy 里 dispose + visibilitychange 暂停轮询

```js
// 卸载时：清定时器、去监听、dispose 两个图表，防止内存泄漏
beforeDestroy() {
  this.stopTimer()
  document.removeEventListener('visibilitychange', this.handleVisibility)
  window.removeEventListener('resize', this.handleResize)
  Object.keys(this.charts).forEach(key => {
    if (this.charts[key]) { this.charts[key].dispose(); this.charts[key] = null }
  })
},
// 标签页切到后台就停轮询，回来再拉一次并重启——省流量、省 CPU
methods: {
  handleVisibility() {
    if (document.hidden) this.stopTimer()
    else { this.fetchAll(); this.startTimer() }
  }
}
```

### 15.5.4 加载失败降级（chartError）

```html
<!-- 图表区：chartError 时显示降级文案，指标卡与表格照常可用 -->
<div v-if="chartError" class="chart-fallback">图表组件加载失败，指标卡与表格仍可用</div>
<div v-else ref="jvmChart" class="chart" />
```

这是非常成熟的做法：**图表属于「锦上添花」的部分，绝不能因为它的加载失败拖垮整个页面**。降级文案明确告诉用户「核心数据还在」。

### 15.5.5 Vue 3 `<script setup>` 重构对照

上述 Options API 在 Vue 3 中可改写为：

```vue
<script setup>
import { ref, reactive, onMounted, onBeforeUnmount, nextTick } from 'vue'
import { getMonitorOverview, getMonitorSeries } from '@/api/monitor'

const loading = ref(false)
const chartError = ref(false)
const overview = reactive({ /* ... */ })
const jvmChart = ref(null)
let echarts = null, chart = null, timer = null

async function fetchAll() { /* await Promise.all(...) 与真实代码同构 */ }
function initCharts() { if (!echarts || !jvmChart.value) return; chart = echarts.init(jvmChart.value) }
function handleResize() { chart?.resize() }
function handleVisibility() { document.hidden ? stopTimer() : (fetchAll(), startTimer()) }

onMounted(async () => {
  window.addEventListener('resize', handleResize)
  document.addEventListener('visibilitychange', handleVisibility)
  try { echarts = await loadEcharts(); await nextTick(); initCharts() }
  catch { chartError.value = true }
  fetchAll(); startTimer()
})
onBeforeUnmount(() => {
  stopTimer()
  window.removeEventListener('resize', handleResize)
  document.removeEventListener('visibilitychange', handleVisibility)
  chart?.dispose(); chart = null
})
</script>
```

`data()` → `ref/reactive`，`computed` → `computed()`，`mounted/beforeDestroy` → `onMounted/onBeforeUnmount`，`this.xxx` 直接引用同名变量。模板里 `slot="header"` 改成 `#header`、`slot-scope` 改成 `#default`。

---

## 15.6 本章小结

- Vue 3 配 Element Plus，Vue 2 配 Element UI；标签名几乎一致，注意样式路径、消息 API、具名插槽三处差异。
- `el-card / el-table / el-progress / el-tag / el-button / el-alert` 覆盖了后台 80% 的界面需求。
- ECharts 一定要按需引入并异步 chunk，首屏不背重包；init → setOption → resize → dispose 四步闭环。
- `visibilitychange` 暂停轮询、`chartError` 降级，是生产级监控页的两道保险。

## ⚠️ 踩坑提示

1. **`echarts.init` 必须等 DOM 就绪**：真实代码用 `$nextTick` 保证容器存在。直接在 `loadEcharts().then` 里 init 而不 nextTick，会拿到 `null` 容器导致图表空白。
2. **忘记 `dispose` 会内存泄漏**：监控页 `beforeDestroy` 里把两个 chart 都 `dispose` 并置 `null`。Vue 3 里漏掉 `onBeforeUnmount` 的 dispose，组件反复进出会累积图表实例。
3. **加载失败要降级**：真实页 `chartError` 分支保证「图表挂了核心数据还在」。若没有这层兜底，CDN/分包加载失败会让用户以为整个页面坏了。
4. **`el-dialog` 的 `v-model`**：Vue 3 用 `v-model` 替代 Vue 2 的 `:visible.sync`，迁移时漏改会报 warning 且弹窗关不掉。
