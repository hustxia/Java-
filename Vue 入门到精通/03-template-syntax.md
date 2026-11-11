# 第 3 章 模板语法：把数据"写"进页面

## 本章目标

读完本章，你将能够：

- 用插值 `{{ }}` 在模板里输出数据与表达式结果。
- 区分 `v-text` / `v-html` 的用途与安全隐患。
- 掌握 `v-bind`（缩写 `:`）绑定属性、`v-on`（缩写 `@`）监听事件。
- 认出 Vue 的常用指令（`v-if` / `v-for` / `v-model` / `v-show` 等）。
- 对照 codegen-web 的 `monitor/index.vue` 真实模板，看到"真实模板长什么样"。

---

## 3.1 插值：{{ }} 是最常用的语法

插值用双大括号把 JavaScript 表达式"包"进模板，Vue 会把它替换成计算结果，并且**数据变化时自动更新**。

```vue
<script setup>
import { ref } from 'vue'
const title = ref('系统监控')
const count = ref(8)
</script>

<template>
  <h1>{{ title }}</h1>                  <!-- 输出文本：系统监控 -->
  <p>共 {{ count }} 项</p>               <!-- 插值里可直接写表达式 -->
  <p>{{ count > 5 ? '较多' : '正常' }}</p> <!-- 三元表达式也行 -->
  <p>{{ title.toUpperCase() }}</p>        <!-- 可调用方法 -->
</template>
```

⚠️ 插值里**只能写单个表达式**，不能写语句（如 `if`、`for`、变量声明）。需要复杂逻辑时，请放到 `computed` 或 `methods` 里（见第 4 章）。

## 3.2 v-text 与 v-html

`{{ }}` 其实等价于 `v-text`，后者把文本作为指令写：

```vue
<p v-text="title"></p>   <!-- 等价于 <p>{{ title }}</p> -->
```

`v-html` 则不同——它**把字符串当作 HTML 解析并插入**，而不是纯文本：

```vue
<script setup>
const html = ref('<b>加粗内容</b>')
</script>

<template>
  <div v-html="html"></div>   <!-- 渲染出真正的 <b> 加粗内容 </b> -->
</template>
```

> **安全红线**：`v-html` 会执行任意 HTML，若内容来自用户输入或接口，极易引发 XSS 攻击。本书案例一律只在"内容可信"场景（如后台富文本回显）使用，且绝不对用户输入直接 `v-html`。

## 3.3 v-bind：动态绑定属性（缩写 `:`）

静态属性直接写，动态（依赖数据）的属性前面加 `:`（即 `v-bind:` 的缩写）。

```vue
<script setup>
const imgUrl = ref('/logo.png')
const isActive = ref(true)
const status = ref('normal')
</script>

<template>
  <img :src="imgUrl" />                         <!-- 动态绑定 src -->
  <div :class="{ off: !isActive }"></div>       <!-- 对象语法：条件加类 -->
  <div :class="['card', status]"></div>         <!-- 数组语法：拼接多个类 -->
  <button :disabled="isActive">提交</button>    <!-- 动态绑定布尔属性 -->
</template>
```

`:class` 的对象语法 `{ off: !isActive }` 特别常用：当 `!isActive` 为真时，元素加上 `off` 这个 class。本书后续大量用到。

## 3.4 v-on：监听事件（缩写 `@`）

事件监听用 `@`（即 `v-on:` 的缩写），`@click`、`@input`、`@submit` 等。

```vue
<script setup>
import { ref } from 'vue'
const loading = ref(false)
function fetchAll() { loading.value = true }   // 事件处理函数
</script>

<template>
  <button @click="fetchAll">立即刷新</button>         <!-- 点击触发 -->
  <button :loading="loading" @click="fetchAll">刷新</button>
</tempalte>
```

事件还能内联表达式：`@click="count++"`；传参：`@click="del(item.id)"`。进阶还有事件修饰符（`.stop`、`.prevent`、`.once`），后面实战会用到。

## 3.5 指令概览

除了上面几个，Vue 还有一组"指令"（带 `v-` 前缀的特殊属性）：

| 指令 | 作用 | 简述 |
| --- | --- | --- |
| `v-if` / `v-else-if` / `v-else` | 条件渲染 | 不满足时**不创建** DOM |
| `v-show` | 条件显示 | 始终创建，靠 `display:none` 切换 |
| `v-for` | 列表渲染 | 遍历数组/对象，`key` 必填 |
| `v-model` | 表单双向绑定 | 输入即更新数据（下一章展开） |
| `v-bind` (`:`) | 动态属性 | 见 3.3 |
| `v-on` (`@`) | 事件监听 | 见 3.4 |

`v-if` vs `v-show`：**频繁切换用 `v-show`（开销小）**，**一次性条件用 `v-if`（不渲染无用 DOM）**。

---

## 3.6 真实项目对照：codegen-web 的模板长什么样

光看玩具例子不够。下面直接看 codegen-web 真实监控页的模板片段，你会发现"真实模板"不过是把上面这些语法组合起来。

> 真实代码来自 `src/views/monitor/index.vue`（第 1–23 行，状态条与告警区）：

```vue
<template>
  <!-- 采样停滞告警：v-if 控制是否出现 -->
  <el-alert v-if="stalled" type="error" :closable="false" show-icon class="stall-alert">
    <span slot="title">
      采样停滞：最近一次采样在 {{ lastSampleText }}，已超过 15 秒未更新。
    </span>
  </el-alert>

  <!-- 状态条 -->
  <div class="status-bar">
    <!-- :class 对象语法：采样关闭时加 off 类 -->
    <i class="pulse" :class="{ off: !overview.sampling }" />
    <span class="st-text">
      <!-- 插值 + 三元表达式 -->
      <b>{{ overview.sampling ? '采样正常' : '采样停滞' }}</b>
      <em>·</em> 每 {{ intervalText }}一次
      <em>·</em> 最近采样 <span class="mono">{{ lastSampleText }}</span>
    </span>
    <el-tag size="mini" type="info">已采样 {{ overview.sampledPoints }} / {{ overview.bufferSize }} 点</el-tag>
    <!-- @click 绑定刷新方法，:loading 绑定加载态 -->
    <el-button size="mini" icon="el-icon-refresh" :loading="loading" @click="fetchAll">立即刷新</el-button>
  </div>
</template>
```

再看一段 `v-for` 与 `:key`、`:style` 的真实用法（同一文件第 139–149 行，写盘文件分布条）：

```vue
<!-- v-for 遍历数组，:key 用 item.status 作唯一标识 -->
<div class="stack">
  <i
    v-for="item in writeFileEntries"
    :key="item.status"
    :style="{ width: item.percent + '%', background: item.color }"  <!-- :style 动态样式 -->
  />
</div>
<!-- 再来一个 v-for 渲染文字说明 -->
<div v-for="item in writeFileEntries" :key="'kv-' + item.status" class="kv">
  <span>{{ item.status }}</span><b>{{ item.value }}</b>
</div>
<div v-if="!writeFileEntries.length" class="empty">暂无写盘记录</div>
```

### 3.6.1 Vue 3 等价写法

上面这段代码，Vue 3 里**几乎不用改**——`v-if` / `v-for` / `:class` / `:style` / `@click` 在 Vue 3 完全保留。唯一的差异在"数据来源"：codegen-web 的 `overview`/`loading`/`stalled` 来自 Vue 2 的 `data()`，而 Vue 3 里它们会是 `ref` / `reactive`（第 4 章详解）。模板层面的语法高度兼容，这正是 Vue 渐进迁移的红利。

---

## 本章小结

- 插值 `{{ }}` 输出表达式结果，且自动响应更新；只能写表达式，不能写语句。
- `v-text` 输出纯文本；`v-html` 输出真实 HTML——后者有 XSS 风险，慎用。
- `v-bind`（`:`）动态绑属性/类/样式；`v-on`（`@`）监听事件。`:class` 的对象/数组语法很常用。
- 指令全家桶：`v-if`/`v-show`/`v-for`/`v-model` 等。`v-if` 不渲染、`v-show` 只隐藏。
- 真实模板（codegen-web）就是把上述语法组合使用，且 Vue 2 与 Vue 3 的模板语法高度一致。

## ⚠️ 踩坑提示

**`v-for` 和 `v-if` 不要写在同一个元素上。** 在 Vue 2 里 `v-for` 优先级更高，会导致 `v-if` 在每次循环中执行；在 Vue 3 里 `v-if` 优先级更高，又拿不到 `v-for` 的变量——两边行为还不一样，极易出 bug。正确做法：用 `<template v-for>` 包一层，把 `v-if` 放到内层或外层容器上，例如 codegen-web 里用 `v-if="!writeFileEntries.length"` 单独控制"空态"，而不是和 `v-for` 挤在一起。
