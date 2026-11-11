# 第 7 章 事件处理与表单绑定

## 本章目标

- 掌握 `v-on`（简写 `@`）绑定事件，以及 `.stop`/`.prevent`/`.once`/`.self` 等事件修饰符与按键修饰符。
- 掌握 `v-model` 在 input / textarea / select / checkbox / radio 上的用法，以及 `.lazy`/`.number`/`.trim` 修饰符。
- 了解 Vue 3 组件的「多 `v-model`」能力；对照 codegen-web 登录表单看 `v-model` + 校验的真实落地。

---

## 7.1 v-on：事件绑定与修饰符

用 `@事件名="处理器"` 监听 DOM 事件。处理器可以是内联表达式，也可以是方法名。

```vue
<template>
  <button @click="fetchAll">立即刷新</button>
  <el-button @click="submit" :loading="loading">登录</button>
</template>
```

事件修饰符让你不必在方法里写 `event.preventDefault()` 之类样板代码：

- `.stop`：等价于 `event.stopPropagation()`，阻止冒泡。
- `.prevent`：等价于 `event.preventDefault()`，阻止默认行为。
- `.once`：事件只触发一次。
- `.self`：只有事件源是自身时才触发（点子元素不触发）。

```vue
<!-- 阻止表单默认提交 + 阻止冒泡 -->
<form @submit.prevent.stop="onSubmit">
  <!-- 按键修饰符：回车即登录 -->
  <input @keyup.enter="handleLogin" />
</form>
```

常用按键修饰符：`.enter`、`.tab`、`.esc`、`.space`、`.up`/`.down`/`.left`/`.right`，以及可直接用 `KeyCode`（如 `@keyup.13`）。

---

## 7.2 v-model：双向绑定

`v-model` 本质是语法糖：根据元素类型自动用对的值属性和事件。常见用法：

```vue
<script setup>
import { ref } from 'vue'
const username = ref('')
const password = ref('')
const remember = ref(true)
const role = ref('dev')
const city = ref('')
</script>

<template>
  <!-- 文本 / 文本域：绑定 value + input 事件 -->
  <input v-model="username" placeholder="用户名" />
  <textarea v-model="password"></textarea>

  <!-- 单个复选框：绑定布尔 -->
  <input type="checkbox" v-model="remember" /> 记住我

  <!-- 多个单选：同一 v-model 配合 value -->
  <input type="radio" v-model="role" value="dev" /> 开发
  <input type="radio" v-model="role" value="ops" /> 运维

  <!-- 下拉选择 -->
  <select v-model="city">
    <option value="bj">北京</option>
    <option value="sh">上海</option>
  </select>
</template>
```

`v-model` 修饰符：
- `.lazy`：从 `input` 事件改为 `change` 事件同步（失焦才更新）。
- `.number`：自动把输入转成数字。
- `.trim`：自动去除首尾空格。

```vue
<input v-model.number="age" />     <!-- 得到 Number -->
<input v-model.trim="name" />      <!-- 自动去空格 -->
```

### 真实项目对照：login/index.vue 的表单

codegen-web 登录页用 `el-form` 包装，输入框通过 Element UI 的 `el-input` 实现 `v-model`。来源：`src/views/login/index.vue:15-53`。

```html
<!-- Vue 2 真实代码：el-form 绑定 model + rules 做校验 -->
<el-form ref="loginForm" :model="loginForm" :rules="loginRules">
  <el-form-item prop="username">
    <el-input v-model="loginForm.username" placeholder="用户名" />
  </el-form-item>

  <el-form-item prop="password">
    <el-input
      v-model="loginForm.password"
      type="password"
      @keyup.enter.native="handleLogin"   <!-- 回车登录 -->
    />
  </el-form-item>

  <el-button :loading="loading" @click.native.prevent="handleLogin">
    登 录
  </el-button>
</el-form>
```

```js
// 数据与校验规则（来源 :63-74）
data() {
  return {
    loginForm: { username: 'admin', password: 'admin123' },
    loginRules: {
      username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
      password: [{ required: true, message: '请输入密码', trigger: 'blur' }]
    }
  }
}
```

**Vue 3 等价写法**：`<script setup>` 中把 `data()` 改为 `ref`/`reactive`，`el-input` 的 `v-model` 写法不变；事件修饰符在 Vue 3 里去掉了 `.native`（原生事件直接 `@keyup.enter`）。校验逻辑仍由 `el-form` 的 `:rules` 承载。

---

## 7.3 方法里的事件：monitor 的 @click="fetchAll"

非表单场景的点击事件同样简洁。来源：`src/views/monitor/index.vue:22`。

```html
<!-- Vue 2 真实代码 -->
<el-button size="mini" icon="el-icon-refresh" :loading="loading" @click="fetchAll">
  立即刷新
</el-button>
```

`fetchAll` 是组件方法（来源 `:361-391`），点击后并发拉取多个监控接口并刷新图表。Vue 3 写法完全一致：`@click="fetchAll"` 不变，只需把 `fetchAll` 定义在 `<script setup>` 顶层即可。

---

## 7.4 Vue 3 的多 v-model（组件）

Vue 2 组件想双向绑定多个字段要用 `v-model` + `.sync` 或 `update:` 事件；Vue 3 原生支持**多个 `v-model`**，每个绑定到不同 prop：

```vue
<!-- 父组件：同时双向绑定 visible 与 tableIds -->
<GenDiffDialog v-model:visible="show" v-model:tableIds="ids" />

<!-- 子组件通过 defineModel（Vue 3.4+）或普通 prop + emit 实现 -->
<script setup>
const visible = defineModel('visible', { type: Boolean })
const tableIds = defineModel('tableIds', { type: Array })
</script>
```

这正好对应 codegen-web 里弹窗用 `:visible` + `@update:visible` 的写法（见第 8、9 章 `GenDiffDialog`）。Vue 3 用 `v-model:visible` 一行替代，更紧凑。

---

## ⚠️ 踩坑提示

1. **Vue 2 的 `.native` 修饰符在 Vue 3 已移除**：Vue 2 里监听组件根元素原生事件要写 `@click.native`（如 `login/index.vue` 的 `@click.native.prevent`）；Vue 3 中组件默认继承原生监听器，直接 `@click.prevent` 即可，写 `.native` 反而报错。
2. **`v-model.number` 对空输入**：输入框清空时 `number` 修饰符可能返回空字符串而非 `0`，做数值计算前仍需兜底判断。
3. **`v-model` 用在 `v-for` 渲染的数组项上**：应绑定 `v-model="items[index].field"` 而非直接用 `v-model="item.field"`（循环变量 `item` 是只读解构），否则改值不会回写数组。

## 本章小结

- `v-on`（`@`）绑定事件，`.stop`/`.prevent`/`.once`/`.self` 修饰符减少样板代码；按键修饰符 `@keyup.enter` 常用于"回车提交"。
- `v-model` 统一了 input/textarea/select/checkbox/radio 的双向绑定；`.lazy`/`.number`/`.trim` 处理同步时机与格式。
- 真实案例 `login/index.vue` 展示了 `el-input v-model` + `el-form :rules` 的表单校验组合；`monitor/index.vue` 的 `@click="fetchAll"` 是方法事件的典型。
- Vue 3 用多 `v-model:xxx` + `defineModel` 取代 Vue 2 的 `.sync`，更直观。迁移时注意去掉 `.native` 修饰符。
