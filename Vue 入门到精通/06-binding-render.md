# 第 6 章 绑定与渲染指令

## 本章目标

- 掌握 `:class`（对象/数组语法）与 `:style`（对象/数组语法）动态绑定样式。
- 区分 `v-if` 与 `v-show` 的渲染差异，熟练使用 `v-if/v-else-if/v-else` 链式分支。
- 掌握 `v-for` 渲染列表、`:key` 的必要性，以及 `v-for` 与 `v-if` 同元素时的优先级陷阱。

---

## 6.1 :class 动态类名

`:class` 可以绑定字符串、对象或数组，最常用的是**对象语法**（键是类名，值是布尔）。

```vue
<template>
  <!-- 对象语法：值 true 时该类生效 -->
  <i class="pulse" :class="{ off: !overview.sampling }" />
  <span :class="{ bad: errors5xx > 0 }">5xx {{ errors5xx }}</span>
</template>
```

- 对象语法适合"条件开关一类样式"（如危险态标红）。
- 数组语法适合"同时叠加多个类"：`['base', isActive ? 'active' : '']`。
- 普通 `class` 与 `:class` 可以共存，Vue 会自动合并。

---

## 6.2 :style 动态内联样式

`:style` 同样支持对象/数组。对象语法里，**驼峰或短横线字符串都可用作 key**，值一般是字符串或数字。

```vue
<template>
  <!-- 对象语法：直接写样式名 → 值 -->
  <i :style="{ width: item.percent + '%', background: item.color }" />
  <div :style="donutStyle" />
</template>

<script setup>
import { computed } from 'vue'
const donutStyle = computed(() => ({
  background: `conic-gradient(#0f9d58 0 ${rate}%, #f2f4f9 ${rate}% 100%)`
}))
</script>
```

数组语法用于合并多个样式对象：`{ base } :style="[baseStyle, extraStyle]"`。需要动态计算的样式（如进度条宽度、环形图角度）优先用 `:style` 对象语法。

### 真实项目对照：monitor/index.vue 的样式绑定

`SystemMonitor` 大量使用 `:class`/`:style` 做状态可视化。来源：`src/views/monitor/index.vue`。

```html
<!-- 采样心跳点：采样停滞时加 off 类变灰，来源 :12 -->
<i class="pulse" :class="{ off: !overview.sampling }" />

<!-- 5xx 大于 0 时整块标红，来源 :50 -->
<span :class="{ bad: overview.http.errors5xx > 0 }">4xx … 5xx …</span>

<!-- 写盘文件堆叠条：每个色块宽度/背景由数据驱动，来源 :140-145 -->
<i
  v-for="item in writeFileEntries"
  :key="item.status"
  :style="{ width: item.percent + '%', background: item.color }"
/>

<!-- 环形图背景：用 computed 算出的 conic-gradient，来源 :128 -->
<div class="donut" :style="donutStyle"></div>
```

**Vue 3 等价写法**：模板语法完全不变（`:class`/`:style` 在 Vue 2、3 中一致）；区别仅在于 `donutStyle` 在 Vue 3 里是 `computed(() => …)` 返回的 ref，模板中写 `:style="donutStyle"` 即可（Vue 自动解包 ref）。这正是真实代码的 `donutStyle`（来源 `:283-286`）迁移到 Vue 3 的样子。

---

## 6.3 v-if / v-else-if / v-else 与 v-show

`v-if` 是"真正的条件渲染"——不满足时元素不会挂载到 DOM（连同子组件销毁）。`v-show` 只是切 `display: none`，元素始终在 DOM 里。

```vue
<template>
  <!-- v-if 链：三态分支，互斥 -->
  <div v-if="state === 'loading'" class="dp-hint">正在准备预览…</div>
  <div v-else-if="state === 'error'" class="dp-unsupported">预览失败</div>
  <div v-else>内容区</div>

  <!-- v-show：频繁切换、不希望反复销毁/重建 DOM 时用 -->
  <canvas v-show="!loading && !error" ref="canvas" />
</template>
```

**怎么选？**
- 切换**不频繁**、条件为 false 时不需要保留 DOM（如弹窗内容、空态提示）→ `v-if`。
- 切换**频繁**（如 tab 切换、显隐按钮）→ `v-show`，避免反复创建销毁的开销。

### 真实项目对照：多状态分支

`DocPreviewDialog` 用 `v-if/v-else-if/v-else` 处理"加载中 / 不支持 / 出错 / PDF / Docx"五态。来源：`src/components/DocPreviewDialog.vue:20-42`。

```html
<div v-if="state === 'loading'" class="dp-hint">…加载中</div>
<div v-else-if="state === 'unsupported'" class="dp-unsupported">…暂不支持</div>
<div v-else-if="state === 'error'" class="dp-unsupported">…失败</div>
<PdfViewer v-else-if="state === 'pdf'" :data="buffer" />
<DocxViewer v-else-if="state === 'docx'" :data="buffer" />
```

而 `PdfViewer` 用 `v-show` 控制 canvas（来源 `:27`）：因为渲染/隐藏 canvas 频繁发生在缩放、翻页时，`v-show` 比反复挂载更省。

---

## 6.4 v-for 与 :key

`v-for` 渲染列表，必须配合 `:key`——它给每个节点一个稳定身份，让 Vue 高效、正确地做 diff（移动/复用而非重建）。

```vue
<template>
  <!-- key 必须是唯一且稳定的，不要用 index（增删时会错乱） -->
  <i v-for="item in writeFileEntries" :key="item.status" :style="{…}" />
  <div v-for="step in topSteps" :key="step.step">…</div>
</template>
```

**为什么不用 index 当 key？** 列表头插/删除元素时，index 会变，导致 Vue 把"本该复用的节点"误判为不同节点，引发状态错乱（如输入框内容错位）。用业务唯一 id（如 `item.status`、`row.id`）才是正解。

### 真实项目对照：monitor/index.vue 的列表渲染

来源：`src/views/monitor/index.vue:140-149`（写盘文件堆叠条与图例列表），`:163-169`（流水线步骤）。

```html
<i
  v-for="item in writeFileEntries"   <!-- 遍历派生数组 -->
  :key="item.status"                 <!-- 用业务状态名作 key -->
  :style="{ width: item.percent + '%', background: item.color }"
/>
<!-- 同一份数据再渲染一次 kv 列表，key 加前缀避免与上面冲突 -->
<div v-for="item in writeFileEntries" :key="'kv-' + item.status" class="kv">
  <span>{{ item.status }}</span><b>{{ item.value }}</b>
</div>
```

注意第二处循环刻意用 `'kv-' + item.status` 作为 key，避免与上一个 `<i>` 列表的 key 冲突——**同一个组件内 key 只需相对唯一**，但若两个循环渲染相同 id 的数据，加前缀是稳妥做法。

---

## ⚠️ 踩坑提示

1. **`v-for` 与 `v-if` 同元素优先级陷阱**：Vue 2 中 `v-for` 优先级高于 `v-if`，导致每次循环都先判断 `v-if`，既低效又易错。Vue 3 中 `v-if` 优先级更高，二者同元素会报编译警告。**正确做法**：用 `<template v-for>` 包一层，把 `v-if` 放到外层或改用 `computed` 先过滤数据（如真实代码的 `topSteps` 已用 `slice(0,4)` 在 computed 里裁剪）。
2. **用数组 index 当 key**：列表含增删操作时会导致节点复用错误，务必用稳定业务 id。
3. **`v-show` 用在 `v-if` 分支里**：`v-show` 元素始终渲染，若放在被 `v-if` 折叠的父级内，隐藏状态仍占 DOM，应考虑改用 `v-if`。

## 本章小结

- `:class` 对象语法做"条件开关样式"，数组语法做"叠加样式"；`:style` 对象语法做"数据驱动的内联样式"。
- `v-if` 真删除/重建 DOM，适合低频切换；`v-show` 仅切 `display`，适合高频显隐。
- `v-for` 必须配 `:key`，且 key 应取稳定唯一值而非 index。
- codegen-web 的 `monitor` 组件是 `:class`/`:style`/`v-if`/`v-for` 综合实战范本：状态类、进度条、堆叠图、多状态弹窗均围绕"数据驱动视图"展开。Vue 3 迁移时这些模板语法基本零改动。
