# 第 9 章 组件进阶

## 本章目标

- 掌握具名插槽与作用域插槽（`v-slot` 简写 `#`），理解"子传父模板片段"的能力。
- 掌握 `provide` / `inject` 跨层级传值，避免逐层透传 props。
- 掌握 Vue 3 的 `defineAsyncComponent` 异步组件，对照 Vue 2 的 `() => import()`。
- 对照 codegen-web 弹窗组件（`GenDiffDialog`、`GenCheckDialog`）与 `monitor` 的 `slot-scope` 写法。

---

## 9.1 具名插槽与作用域插槽

**具名插槽**：一个组件有多个插槽位置时，用 `name` 区分，父组件用 `v-slot:name`（简写 `#name`）填充。

```vue
<!-- 子组件：两个具名插槽 + 默认插槽 -->
<template>
  <div class="dialog">
    <header><slot name="title">默认标题</slot></header>
    <main><slot /></main>
    <footer><slot name="footer" /></footer>
  </div>
</template>

<!-- 父组件 -->
<MyDialog>
  <template #title>差异预览</template>
  <p>主体内容</p>
  <template #footer><el-button>关闭</el-button></template>
</MyDialog>
```

**作用域插槽**：子组件把数据"反向"传给插槽内容，父组件用 `#name="slotProps"` 接收。常用于列表/表格类组件把行数据交给使用者自定义渲染。

```vue
<!-- 子组件：把 row 暴露给插槽 -->
<slot name="cell" :row="item" :index="i">{{ item.name }}</slot>

<!-- 父组件：拿到 row 自定义渲染 -->
<template #cell="{ row }">
  <span :class="{ bad: row.error }">{{ row.name }}</span>
</template>
```

### 真实项目对照：monitor 的 slot-scope（Vue 2 写法）

`SystemMonitor` 在 `el-table` 列里大量用 Vue 2 的 `slot-scope` 拿到行数据自定义渲染。来源：`src/views/monitor/index.vue:96-112`。

```html
<!-- Vue 2 作用域插槽写法（真实代码） -->
<el-table-column prop="uri" label="URI" min-width="300">
  <template slot-scope="{ row }">
    <span class="mono">{{ row.uri }}</span>
  </template>
</el-table-column>

<el-table-column label="平均耗时" width="130">
  <template slot-scope="{ row }">
    <span class="num" :class="slowClass(row.avgMs)">{{ fmtMs(row.avgMs) }}</span>
  </template>
</el-table-column>
```

**Vue 3 等价写法**（用 `v-slot` / `#`）：

```html
<el-table-column label="URI" min-width="300">
  <template #default="{ row }">
    <span class="mono">{{ row.uri }}</span>
  </template>
</el-table-column>
```

迁移要点：Vue 2 的 `slot="xxx"` → Vue 3 的 `#xxx`；`slot-scope="props"` → `#default="props"`（或具名 `#cell="props"`）。Vue 3 已移除 `slot`/`slot-scope` 属性，统一为 `v-slot` 指令。

---

## 9.2 provide / inject：跨层传值

当数据要在"祖先 → 深层后代"之间传递，逐层 `props` 透传很累赘。`provide/inject` 让祖先直接提供，任意后代注入。

```vue
<!-- 祖先组件 -->
<script setup>
import { provide, ref } from 'vue'
const theme = ref('dark')
provide('theme', theme)        // 提供（key 可为字符串或 Symbol）
provide('changeTheme', (t) => theme.value = t)
</script>

<!-- 深层后代组件 -->
<script setup>
import { inject } from 'vue'
const theme = inject('theme', 'light')         // 第二个参数为默认值
const changeTheme = inject('changeTheme')
</script>
```

注意：`provide` 的值若要让后代响应式更新，应提供 `ref`/`reactive` 本身（如上面的 `theme`），而非它的 `.value`。`inject` 默认不具备响应式的"可写"能力，需要写回时应额外 `provide` 一个修改函数（如 `changeTheme`）。

> codegen-web 的主题偏好通过 `public/index.html` 内联脚本注入 CSS 变量（来源 `login/index.vue:98-99` 注释），走的是全局 CSS 变量方案而非 `provide/inject`；但在多语言、用户信息等"全局只读上下文"场景下，`provide/inject` 是比 Vuex 更轻量的选择。

---

## 9.3 异步组件：按需加载

大组件（如 PDF 渲染器、图表）不进首屏主包，等真正用到再加载。Vue 3 用 `defineAsyncComponent`：

```js
import { defineAsyncComponent } from 'vue'

// 基础用法
const PdfViewer = defineAsyncComponent(() =>
  import('@/components/PdfViewer.vue'))

// 带加载/错误态（适合弹窗类大组件）
const DocxViewer = defineAsyncComponent({
  loader: () => import('@/components/DocxViewer.vue'),
  loadingComponent: Spinner,
  errorComponent: ErrorBox,
  delay: 200,        // 200ms 内完成不显示 loading
  timeout: 8000      // 超时视为失败
})
```

### 真实项目对照：Vue 2 的 () => import()

codegen-web 在 `DocPreviewDialog` 中用选项式 `components` 配合动态 `import()` 实现按需加载。来源：`src/components/DocPreviewDialog.vue:51-55`。

```js
// Vue 2 选项式（真实代码）
components: {
  PdfViewer: () => import(/* webpackChunkName: "pdf-renderer" */ '@/components/PdfViewer.vue'),
  DocxViewer: () => import(/* webpackChunkName: "docx-renderer" */ '@/components/DocxViewer.vue')
}
```

同理 `monitor/index.vue` 用函数 `loadEcharts()` 动态 `import` ECharts 各模块（来源 `:193-216`），加载失败仅降级趋势图区（`chartError`，来源 `:318-320`）。**Vue 3 把这种模式标准化为 `defineAsyncComponent`**，并额外支持 `loadingComponent`/`errorComponent`，比 Vue 2 的裸 `() => import()` 更完善。

---

## 9.4 真实弹窗组合：GenDiffDialog / GenCheckDialog

这两个"拆出来"的弹窗是组件职责单一化的范例。

**GenDiffDialog**：接收 `visible` 与 `tableIds` 两个 prop，打开时自己拉 diff（来源 `src/views/gen/table/GenDiffDialog.vue:64-104`）。

```html
<!-- Vue 2 真实代码：v-model 在 Vue 2 用 :visible + @update:visible 模拟 -->
<el-dialog
  :visible="visible"
  @update:visible="$emit('update:visible', $event)"
  @open="load"
>
  <div v-for="d in list" :key="d.tableName + d.path" @click="active = d">
    <el-tag :type="statusType(d.status)">{{ statusText(d.status) }}</el-tag>
    <span class="diff-path">{{ d.path }}</span>
  </div>
</el-dialog>
```

```js
props: {
  visible: { type: Boolean, default: false },
  tableIds: { type: Array, default: () => [] }   // 工厂函数默认值
},
computed: {
  changedCount() {                                // 派生：变化文件数
    return this.list.filter(d => d.status === 'MODIFIED' || d.status === 'NEW').length
  }
}
```

**GenCheckDialog**：纯展示弹窗，只接收 `visible` 与 `result`（来源 `src/views/gen/table/GenCheckDialog.vue:44-50`），自检请求由父页面发起，它只负责渲染结果——把"取数"和"展示"分离，正是组件拆分的好范例。

**Vue 3 等价写法**：`props` 改为 `defineProps`，`$emit('update:visible')` 改为 `defineEmits` 声明后用 `emit`，父组件侧把 `:visible` + `@update:visible` 合并为一行 `v-model:visible`。

---

## ⚠️ 踩坑提示

1. **作用域插槽 Vue 2 → 3 的破坏性变更**：Vue 2 的 `slot="title"` 与 `slot-scope` 在 Vue 3 已移除，必须改用 `#title` 与 `#default="scope"`。直接保留旧写法会导致插槽内容不渲染且无报错提示，排查困难（codegen-web 的 `monitor/index.vue` 所有 `slot-scope` 都需这样迁移）。
2. **`provide/inject` 响应式陷阱**：`provide('x', ref.value)` 提供的是快照，后代永远拿到初始值；应 `provide('x', ref)` 提供 ref 本身，后代 `inject` 后通过 `.value` 读取才能响应式更新。
3. **异步组件错误边界**：仅用 `() => import()` 无法优雅处理加载失败；Vue 3 的 `defineAsyncComponent({ loader, errorComponent, timeout })` 才能给出降级 UI，避免大组件加载失败时白屏。

## 本章小结

- 具名插槽（`#name`）解决多插槽定位；作用域插槽（`#default="scope"`）让子组件把行/项数据交给父组件自定义渲染。codegen-web 的 `monitor` 用 `slot-scope` 自定义 `el-table` 列，Vue 3 对应 `#default` 写法。
- `provide/inject` 适合跨多层传递全局上下文，需提供 ref 才能保持响应式。
- Vue 3 用 `defineAsyncComponent` 替代 Vue 2 的 `() => import()`，并支持 loading/error 态，codegen-web 的 `DocPreviewDialog` 按需加载渲染器即此模式。
- `GenDiffDialog`/`GenCheckDialog` 展示了"取数"与"展示"拆分的单一职责弹窗设计，以及多 prop + `update:visible` 的双向绑定范式。
- 迁移到 Vue 3 时，`slot`/`slot-scope` 属性是必须改写的高频点。
