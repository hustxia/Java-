# 第 4 章 响应式核心：数据变了，视图自动变

## 本章目标

读完本章，你将能够：

- 用 `ref` 管理基本类型状态，理解 `.value` 规则与模板自动解包。
- 用 `reactive` 管理对象状态，并认清它的局限性（解构会丢失响应）。
- 区分 Vue 3（`ref`/`reactive`）与 Vue 2（`data()`）的响应式实现差异。
- 对照 codegen-web 的 `data()` 与 `computed`，理解"行为一致、写法不同"。

---

## 4.1 什么是响应式

回顾第 1 章的核心命题：**数据变了，视图自动更新**。这套"自动"机制就叫**响应式**。在 Vue 3 里，响应式靠两个 API 落地：`ref` 和 `reactive`。

## 4.2 ref：管理基本类型

`ref` 用来包裹一个值（数字、字符串、布尔等），返回一个"响应式引用对象"。在**脚本里**访问/修改要加 `.value`；在**模板里** Vue 会自动帮你解包，直接写变量名即可。

```vue
<script setup>
import { ref } from 'vue'
const count = ref(0)          // 基本类型用 ref
const loading = ref(false)

function add() {
  count.value++              // 脚本里必须写 .value
  loading.value = true       // 改 .value 才会触发视图更新
}
</script>

<template>
  <p>点了 {{ count }} 次</p>  <!-- 模板里自动解包，无需 .value -->
  <button :disabled="loading" @click="add">加一</button>
</template>
```

**为什么有 `.value`？** 因为 JavaScript 的基本类型（number/string）是"按值传递"的，没法直接拦截赋值。用对象包一层 `{ value: 0 }`，Vue 就能用 `Proxy` 拦截 `.value` 的读写，从而实现"改值即通知视图"。这是语言限制逼出来的设计。

## 4.3 reactive：管理对象

当状态是一组相关的字段（像表单、配置），用 `reactive` 更自然——它直接让整个对象变成响应式，访问字段**不需要** `.value`。

```vue
<script setup>
import { reactive } from 'vue'
const overview = reactive({            // 对象用 reactive
  sampling: false,
  sampledPoints: 0,
  bufferSize: 360
})

function start() {
  overview.sampling = true             // 直接改字段，不用 .value
  overview.sampledPoints++
}
</script>

<template>
  <p>采样中：{{ overview.sampling }}</p>
  <p>已采样 {{ overview.sampledPoints }} / {{ overview.bufferSize }}</p>
</template>
```

### 4.3.1 reactive 的坑：解构会丢失响应

`reactive` 有个著名陷阱：**把它的字段解构/展开出来后，就不再是响应式的了**。

```js
const state = reactive({ count: 0, name: 'Vue' })
const { count, name } = state     // ❌ 解构后 count/name 变成普通值
// 之后改 count 不会触发视图更新！

// ✅ 正确做法 1：始终通过 state.xxx 访问
state.count++

// ✅ 正确做法 2：用 toRefs 转成 ref 再解构
import { toRefs } from 'vue'
const { count, name } = toRefs(state)  // 现在是 ref，需 .value
```

> 经验法则：**零散的基本类型用 `ref`；成组的对象用 `reactive`，但别随手解构它。**

## 4.4 computed：派生的响应式数据

很多显示值是从其他状态"算"出来的（如百分比、格式化文本）。用 `computed` 声明，它会缓存结果，且依赖变化才重算。

```vue
<script setup>
import { ref, computed } from 'vue'
const heapUsedRatio = ref(0.782)
const heapPercent = computed(() => {     // 派生值，自动随 heapUsedRatio 变
  return Math.min(100, Math.round(heapUsedRatio.value * 1000) / 10)
})
</script>

<template>
  <p>堆使用率 {{ heapPercent }}%</p>
</template>
```

`computed` 默认是"只读"的（getter）。需要可写时传 `{ get, set }` 对象，本书实战再展开。

---

## 4.5 真实项目对照：codegen-web 怎么管状态

codegen-web 是 Vue 2.7 Options API，它没有 `ref`/`reactive`，而是把所有状态塞进 `data()`，把派生值塞进 `computed`。看真实代码：

> 真实代码来自 `src/views/monitor/index.vue`（第 250–306 行，`data()` 与 `computed` 节选）：

```js
export default {
  data() {
    return {
      loading: false,                 // 加载态
      stalled: false,                 // 是否停滞
      overview: {                     // 监控总览对象
        sampling: false,
        intervalMs: 5000,
        sampledPoints: 0,
        bufferSize: 360,
        jvm: { heapUsedRatio: 0 }
      }
    }
  },
  computed: {
    // 派生：把毫秒转成"X 秒"
    intervalText() {
      return Math.round((this.overview.intervalMs || 5000) / 1000) + ' 秒'
    },
    // 派生：堆使用率百分比（与上面 4.4 的例子同款逻辑）
    heapPercent() {
      return Math.min(100, Math.round(this.overview.jvm.heapUsedRatio * 1000) / 10)
    },
    // 派生：根据百分比返回颜色（70/90 分档）
    heapColor() {
      if (this.heapPercent >= 90) return '#e5484d'
      if (this.heapPercent >= 75) return '#d97706'
      return '#3d6df5'
    }
  }
}
```

### 4.5.1 Vue 3 等价写法

把上面这段"翻译"成 Vue 3 主线写法，结构几乎一一对应：

```vue
<script setup>
import { ref, reactive, computed } from 'vue'

// data() 里的字段 → ref / reactive
const loading = ref(false)
const stalled = ref(false)
const overview = reactive({
  sampling: false,
  intervalMs: 5000,
  sampledPoints: 0,
  bufferSize: 360,
  jvm: { heapUsedRatio: 0 }
})

// computed 节 → 直接调用 computed()
const intervalText = computed(() =>
  Math.round((overview.intervalMs || 5000) / 1000) + ' 秒'
)
const heapPercent = computed(() =>
  Math.min(100, Math.round(overview.jvm.heapUsedRatio * 1000) / 10)
)
const heapColor = computed(() => {
  if (heapPercent.value >= 90) return '#e5484d'   // 注意：computed 间引用要 .value
  if (heapPercent.value >= 75) return '#d97706'
  return '#3d6df5'
})
</script>
```

对照要点：

- `data()` 返回的对象 → 拆成若干 `ref` / `reactive`（零散值用 `ref`，对象用 `reactive`）。
- `computed` 选项 → 顶层 `computed()` 调用，返回同名的响应式值。
- **关键差异**：Vue 2 在 `computed` 里通过 `this.xxx` 访问依赖；Vue 3 在 `computed` 回调里通过变量名，且引用另一个 `computed` 要加 `.value`（如 `heapPercent.value`）。
- **结果完全一致**：`intervalText` 显示"5 秒"、`heapPercent` 算出百分比、`heapColor` 按阈值变色——老项目用 `this` 串起依赖，新项目用闭包捕获变量，机制不同，行为相同。

---

## 本章小结

- `ref` 包裹基本类型，脚本里用 `.value`、模板里自动解包；`.value` 是为绕过 JS 基本类型"按值传递"限制而设计。
- `reactive` 让对象整体响应式，但**解构会丢失响应**，需用 `toRefs` 或始终 `state.xxx` 访问。
- `computed` 声明派生值，带缓存、依赖变化才重算，与 Vue 2 的 `computed` 选项行为一致。
- Vue 2 用 `data()` + `computed` 选项、`this` 串依赖；Vue 3 用 `ref`/`reactive` + `computed()`、闭包捕获变量——写法不同，行为一致。

## ⚠️ 踩坑提示

**`reactive` 不能直接整体替换。** 很多人写 `overview = newValue`（重新赋值整个对象），结果新对象不是响应式的，视图不再更新。因为 `reactive` 的响应绑定在"原对象"上，变量只是个引用。正确方式：要么 `Object.assign(overview, newValue)` 原地更新字段，要么干脆用 `ref` 包裹对象（`const overview = ref({...})`，整体替换写 `overview.value = newValue` 是合法的）。codegen-web 里 `this.overview = overview` 这种整体赋值在 Vue 2 能工作，是因为 Vue 2 的 `data()` 已对它做了响应式代理；迁移到 Vue 3 的 `reactive` 时必须改写法，否则会踩空。
