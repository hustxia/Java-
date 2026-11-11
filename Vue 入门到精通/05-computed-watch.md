# 第 5 章 计算属性与侦听器

## 本章目标

- 掌握 `computed` 的「派生状态 + 缓存 + 依赖追踪」三件套，并写出带 setter 的计算属性。
- 区分 `watch`（回调式、可配 `deep`/`immediate`）与 `watchEffect`（立即执行、自动追踪）的适用场景。
- 对照 codegen-web（Vue 2.7 Options API）理解 Vue 3 的等价写法，体会响应式心智模型的一致性。

---

## 5.1 computed：派生状态，而非方法

模板里经常需要"由已有数据算出来的展示值"，例如把毫秒转成 `12:03:45`。新手容易写成方法不断调用，但**方法每次渲染都会重算**，而 `computed` 会缓存结果——只在依赖变化时重算一次。

```vue
<script setup>
import { ref, computed } from 'vue'

const intervalMs = ref(5000)

// 只依赖 intervalMs，intervalMs 不变它就不会重算
const intervalText = computed(() => Math.round(intervalMs.value / 1000) + ' 秒')

// 带 setter 的计算属性：既能读也能写（写会反向改依赖）
const fullName = computed({
  get: () => firstName.value + ' ' + lastName.value,
  set: (val) => {
    const [first, last] = val.split(' ')
    firstName.value = first
    lastName.value = last
  }
})
</script>
```

要点：
- 依赖是「自动追踪」的——函数里读到的响应式变量，都会成为它的依赖。
- 缓存意味着 `intervalText` 在多个地方引用，也只算一次。
- 不要在 `computed` 里做副作用（请求、改 DOM），那是 `watch` 的活。

### 真实项目对照：monitor/index.vue 的 computed

codegen-web 的 `SystemMonitor` 组件用 Vue 2 选项式 `computed` 把一堆原始指标「翻译」成展示用的值。来源：`src/views/monitor/index.vue:264-306`。

```js
// Vue 2 选项式（真实代码）
computed: {
  intervalText() {                       // 采样间隔 → "5 秒"
    return Math.round((this.overview.intervalMs || 5000) / 1000) + ' 秒'
  },
  heapPercent() {                        // 比率 0.812 → 81.2
    return Math.min(100, Math.round(this.overview.jvm.heapUsedRatio * 1000) / 10)
  },
  heapColor() {                          // 根据百分比选颜色
    if (this.heapPercent >= 90) return '#e5484d'  // 红：危险
    if (this.heapPercent >= 75) return '#d97706'  // 橙：警告
    return '#3d6df5'                              // 蓝：正常
  }
}
```

**Vue 3 等价写法**（`<script setup>`）：

```js
// Vue 3：把 this.overview 换成响应式 ref/对象，其余逻辑完全一致
const heapPercent = computed(() =>
  Math.min(100, Math.round(overview.value.jvm.heapUsedRatio * 1000) / 10))
const heapColor = computed(() => {
  if (heapPercent.value >= 90) return '#e5484d'
  if (heapPercent.value >= 75) return '#d97706'
  return '#3d6df5'
})
```

注意 `heapColor` 依赖的是另一个 `computed`（Vue 2 里是 `this.heapPercent`），Vue 的响应式系统会正确串起这条依赖链。**这就是"派生状态"的本质：展示值层层由底层数据算出来，模板无需关心怎么算。**

---

## 5.2 watch：你想"看到变化后做点什么"

当数据变化时需要执行副作用（发请求、写 localStorage、弹提示），用 `watch`。它像"盯梢"：指定一个源，变化时回调。

```js
import { ref, watch } from 'vue'

const visible = ref(false)

// 回调式：第一个参数是新值，第二个是旧值
watch(visible, (newVal, oldVal) => {
  if (newVal) openPreview()   // 打开弹窗时加载数据
  else reset()                // 关闭时重置
})

// 立即执行一次（immediate）并深度监听对象内部变化（deep）
watch(() => props.doc, (doc) => load(doc), { immediate: true, deep: true })
```

- `immediate: true`：组件创建时先跑一次回调（不用等首次变化）。
- `deep: true`：监听对象/数组内部字段变化（有性能成本，尽量监听具体字段而非整个对象）。

### 真实项目对照：DocPreviewDialog.vue 的 watch

`DocPreviewDialog` 用 `watch` 监听 `visible` 开关，自动加载或重置。来源：`src/components/DocPreviewDialog.vue:90-98`。

```js
// Vue 2 选项式（真实代码）
watch: {
  visible(val) {
    if (val) this.open()   // 弹窗打开 → 拉取文档元数据
    else this.reset()      // 弹窗关闭 → 清空状态
  }
}
```

**Vue 3 等价写法**：

```js
watch(() => props.visible, (val) => {
  if (val) open()
  else reset()
}, { immediate: true })
```

---

## 5.3 watchEffect：自动追踪，立即执行

`watchEffect` 更简单：你写一个函数，里面用到哪些响应式数据，就自动监听哪些。首次立即执行一次。适合"数据一变我就重算/重渲染"的场景。

```js
import { ref, watchEffect } from 'vue'

const keyword = ref('')
const list = ref([])

// 函数体内读了 keyword、page，它们都会成为依赖
watchEffect(async () => {
  list.value = await fetchList(keyword.value, page.value)
})
```

`watch` vs `watchEffect` 怎么选？
- 需要知道**变化前后的值**，或要 `deep`/`immediate` 精确控制 → `watch`。
- 只想"只要相关变量变了就重跑一段逻辑"，不关心新旧值 → `watchEffect`。

---

## 5.4 Vue 2 与 Vue 3 的心智对照

| 能力 | Vue 2 选项式 | Vue 3 Composition |
| --- | --- | --- |
| 派生状态 | `computed: { x() {} }` | `const x = computed(() => …)` |
| 监听单个值 | `watch: { x() {} }` | `watch(x, cb)` |
| 立即+自动追踪 | 需手动 `immediate` | `watchEffect(fn)` |

两者的响应式原理一致（依赖收集 + 派发更新），只是 API 形态从"选项对象"变成"可组合的函数"，后者能在多个组件间复用同一段逻辑。

---

## ⚠️ 踩坑提示

1. **`computed` 里写副作用**：算属性应当是"纯函数"。在里面发请求或 `console.log` 改状态，会导致缓存失效和难以追踪的更新循环。
2. **`watch` 对象忘了 `deep`**：监听 `props.doc`（对象）时若只写 `watch(() => props.doc, cb)`，doc 内部字段变了不会触发；要么加 `deep: true`，要么精准监听具体字段 `watch(() => props.doc.id, cb)`。codegen-web 的 `monitor` 组件改用 `fetchAll` 轮询而非深度监听，正是为了避免这种隐性触发。

## 本章小结

- `computed` 用于**派生状态**，带缓存、自动追踪依赖；可用对象形式写 getter/setter。
- `watch` 适合"变化后做副作用"，支持 `immediate`/`deep`；`watchEffect` 立即执行且自动收集依赖，写法更简洁。
- codegen-web 的 `intervalText`、`heapPercent`、`heapColor` 是"层层派生"的典型；`DocPreviewDialog` 的 `watch(visible)` 是"开关驱动副作用"的典型。
- Vue 2 选项式与 Vue 3 组合式在响应式心智上一致，迁移时主要是把 `this.xxx` 换成 `xxx.value` 并改为函数调用。
