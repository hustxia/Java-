# 第 8 章 组件基础

## 本章目标

- 掌握组件的全局注册与局部注册，理解何时用哪种。
- 掌握 `props` 的声明、类型、默认值与校验；理解「单向数据流」。
- 掌握 Vue 3 的 `defineEmits` 自定义事件，以及插槽 `slot` 的基础用法。
- 对照 codegen-web 真实组件（`DocPreviewDialog`、`PdfViewer`）看 props/emits/slot 落地。

---

## 8.1 组件注册：全局 vs 局部

**全局注册**一次，全应用可用的组件（适合通用基础组件）：

```js
// main.js
import { createApp } from 'vue'
import App from './App.vue'
import BaseButton from './components/BaseButton.vue'

createApp(App).component('BaseButton', BaseButton).mount('#app')
```

**局部注册**仅在当前组件可用（推荐，便于 tree-shaking 和依赖追踪）：

```vue
<script setup>
import PdfViewer from '@/components/PdfViewer.vue'
</script>

<template>
  <PdfViewer :data="buffer" />
</template>
```

绝大多数业务组件用局部注册。codegen-web 在 `DocPreviewDialog` 中就用了局部注册（见 8.3）。

---

## 8.2 props：父传子的数据通道

`props` 是父组件传给子组件的数据，**只读**——子组件不能直接修改 prop（这是单向数据流）。

```vue
<script setup>
// 数组写法（仅声明名字）
// const props = defineProps(['data', 'visible'])

// 对象写法：类型 + 默认值 + 校验（推荐）
const props = defineProps({
  data: { type: Object, required: true },      // 必填
  visible: { type: Boolean, default: false },  // 带默认值
  doc: { type: Object, default: null },
  // 自定义校验函数
  page: {
    type: Number,
    default: 1,
    validator: (v) => v > 0
  }
})
</script>
```

要点：
- 类型可以是 `String/Number/Boolean/Object/Array/Function/Promise` 等。
- 对象/数组的默认值必须用**工厂函数**返回（`default: () => []`），否则所有实例共享同一引用。
- 子组件要改数据时，应通过 `emits` 通知父组件去改，或本地 `data`/`computed` 派生。

### 真实项目对照：PdfViewer.vue 的 props

`PdfViewer` 接收 PDF 的 `ArrayBuffer` 并渲染。来源：`src/components/PdfViewer.vue:39-44`。

```js
// Vue 2 选项式（真实代码）
props: {
  // ArrayBuffer（axios arraybuffer 取流）
  data: { type: Object, required: true }
}
```

**Vue 3 等价写法**：

```js
const props = defineProps({
  data: { type: Object, required: true }
})
```

`DocPreviewDialog` 同样用 props 接收 `visible` 与 `doc`（来源 `:56-59`），且 `doc` 用 `default: null` 允许空值——父组件没传文档时显示默认标题。

---

## 8.3 局部注册 + 异步组件的真实案例

`DocPreviewDialog` 在 `components` 选项里局部注册了两个体积大的渲染器，并用 `() => import()` 做异步加载（按需加载，不进主包）。来源：`src/components/DocPreviewDialog.vue:51-55`。

```js
// Vue 2 选项式（真实代码）
components: {
  PdfViewer: () => import(/* webpackChunkName: "pdf-renderer" */ '@/components/PdfViewer.vue'),
  DocxViewer: () => import(/* webpackChunkName: "docx-renderer" */ '@/components/DocxViewer.vue')
}
```

**Vue 3 等价写法**（用 `defineAsyncComponent` 更语义化，见第 9 章）：

```js
import { defineAsyncComponent } from 'vue'
const PdfViewer = defineAsyncComponent(() =>
  import('@/components/PdfViewer.vue'))
```

模板中直接用局部组件标签：`<PdfViewer v-else-if="state === 'pdf'" :data="buffer" />`（来源 `:40`）。

---

## 8.4 emits：子传父的自定义事件

子组件通过 `emit` 向父组件"喊话"，父组件用 `@事件名` 监听。Vue 3 推荐用 `defineEmits` 显式声明。

```vue
<script setup>
const emit = defineEmits(['update:visible', 'download'])

function close() {
  emit('update:visible', false)   // 通知父组件关闭弹窗
}
</script>
```

### 真实项目对照：DocPreviewDialog 的 close

`DocPreviewDialog` 的 `close` 方法通过 `$emit` 把 `visible` 改回 false，实现"弹窗自己关闭、父组件状态同步"。来源：`src/components/DocPreviewDialog.vue:173-175`。

```js
// Vue 2 真实代码
close() {
  this.$emit('update:visible', false)
}
```

父组件则写成 `:visible.sync`（Vue 2）或 `v-model:visible`（Vue 3）来接收。这正是双向绑定弹窗的标准模式。

---

## 8.5 单向数据流：黄金法则

父 → 子的数据只能"流下去"，子组件**不要**直接改 prop。若需要基于 prop 算出本地状态，用 `computed` 或本地 `data`：

```vue
<script setup>
const props = defineProps({ doc: Object })
// 派生：从 prop 算出展示值（不修改 prop）
const sizeText = computed(() => formatSize(props.doc?.fileSize))
// 本地可变副本：需要编辑时拷贝一份
const localName = ref(props.doc?.name ?? '')
</script>
```

codegen-web 的 `DocPreviewDialog` 正是如此：`doc` 是只读 prop，组件内部用 `state`/`buffer` 等 `data` 字段维护可变状态（来源 `:60-71`），绝不写 `this.doc = …`。

---

## 8.6 插槽 slot 基础

插槽让父组件往子组件指定位置"塞内容"，实现内容分发。

```vue
<!-- 子组件 Card.vue -->
<template>
  <div class="card">
    <slot>默认内容（父没传时显示）</slot>
  </div>
</template>

<!-- 父组件：包裹的内容会填进 slot -->
<Card>这是卡片主体</Card>
```

### 真实项目对照：弹窗标题插槽

`DocPreviewDialog` 用 `<div slot="title">` 自定义 `el-dialog` 的标题区（带文件名 + 徽标 + 操作按钮）。来源：`src/components/DocPreviewDialog.vue:11-17`。

```html
<!-- Vue 2 具名插槽写法（真实代码） -->
<div slot="title" class="dp-head">
  <span class="dp-name">{{ doc ? doc.originalName : '文档预览' }}</span>
  <span v-if="badge" class="dp-badge" :class="badge.cls">{{ badge.text }}</span>
  <span class="dp-spacer" />
  <el-button type="text" @click="download">下载</el-button>
</div>
```

**Vue 3 等价写法**（具名插槽用 `v-slot`/`#`，见第 9 章）：

```html
<template #title>
  <div class="dp-head">…</div>
</template>
```

---

## ⚠️ 踩坑提示

1. **对象/数组 prop 的默认值**：必须写 `default: () => ({})` 而非 `default: {}`，否则多个组件实例会共享同一对象引用，改一个影响全部。
2. **直接修改 prop 对象内部**：虽然 Vue 不直接报错（对象引用没变），但违反单向数据流，会让数据来源难以追踪。应 `emit` 让父组件改，或本地派生副本。
3. **未声明就 `emit` 事件**：Vue 3 中若用 `defineEmits` 声明了事件，控制台会检查未声明事件并警告；显式声明既防错也利于类型推导。codegen-web 弹窗的 `@update:visible` 若漏声明，Vue 3 会给出开发期警告。

## 本章小结

- 组件分全局注册（通用基础件）与局部注册（业务件，利于 tree-shaking）。
- `props` 是父→子单向通道，需声明类型、默认值与校验；对象/数组默认值用工厂函数。
- Vue 3 用 `defineEmits` 声明并触发自定义事件，子→父通信；配合 `v-model:xxx` 实现弹窗双向绑定。
- 真实 `DocPreviewDialog`/`PdfViewer` 展示了 props 接收、异步局部注册、`$emit('update:visible')`、具名插槽标题等核心套路。
- 单向数据流是黄金法则：子组件不写 prop，可变状态用本地 `data`/`computed` 派生。
