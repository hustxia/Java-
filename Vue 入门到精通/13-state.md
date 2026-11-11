# 第 13 章 状态管理：Pinia 与 Vuex 实战对照

## 本章目标

- 掌握 Pinia 的核心 API：`defineStore`、`state` / `getters` / `actions`，以及 Composition 写法。
- 理解 Pinia 相对 Vuex 3（codegen-web 所用）的简化：去掉 `mutations`、`action` 可同步可异步。
- 以 codegen-web 的 `src/store/index.js`、`modules/user.js`、`modules/permission.js` 为「Vuex 真实模块」范例，看懂用户 / 权限状态如何组织。
- 给出对应逻辑的 Pinia 等价定义。

## 一、Vuex 3 的结构回顾（codegen-web 在用）

codegen-web 用 **Vuex 3**，典型模块包含 `state` / `getters` / `mutations` / `actions` 四件套，且开启 `namespaced: true`。

根 store（`src/store/index.js`）把所有模块聚合、并挂一个全局 `getters`（源码 `src/store/index.js:1-19`）：

```js
import Vue from 'vue'
import Vuex from 'vuex'
import getters from './getters'
import app from './modules/app'
import user from './modules/user'
import permission from './modules/permission'

Vue.use(Vuex)

const store = new Vuex.Store({
  modules: { app, user, permission },   // 三个命名空间模块
  getters                                 // 跨模块派生：token/name/menus 等
})
export default store
```

全局 `getters`（`src/store/getters.js`）把分散在各模块的字段统一映射出来，组件无需关心它属于哪个模块：

```js
const getters = {
  token: state => state.user.token,         // 用户 token
  name: state => state.user.name,
  menus: state => state.permission.menus,   // 后端下发的菜单树
  accessiblePaths: state => state.permission.accessiblePaths
}
```

## 二、真实模块范例：user 与 permission

### user 模块（src/store/modules/user.js）

它持有 `token / name / roles / permissions`，通过 `mutations` 改 state，通过 `actions` 调接口（源码 `src/store/modules/user.js:6-123`）：

```js
const state = { token: getToken(), name: '', roles: [], permissions: [] }

const mutations = {
  SET_TOKEN(state, token) { state.token = token },   // 每个字段一个 mutation（样板代码多）
  SET_NAME(state, name) { state.name = name }
}

const actions = {
  // 登录：调接口 -> commit mutation -> 写本地 token
  login({ commit }, userInfo) {
    return new Promise((resolve, reject) => {
      login(userInfo).then(res => {
        commit('SET_TOKEN', res.data.token)
        setToken(res.data.token)
        resolve()
      }).catch(reject)
    })
  },
  // 登出：清状态 + 清 token + 重置路由（注意 root: true 跨模块提交）
  logout({ commit }) {
    return new Promise(resolve => {
      logout().then(() => {
        commit('RESET_STATE')
        commit('permission/RESET_STATE', null, { root: true })  // 跨命名空间
        removeToken(); resetRouter(); resolve()
      })
    })
  }
}

export default { namespaced: true, state, mutations, actions }
```

### permission 模块（src/store/modules/permission.js）

负责动态路由：`generateRoutes` action 把后端菜单树 `buildRoutes` 成路由并 `commit('SET_ROUTES')`（源码 `src/store/modules/permission.js:111-170`）：

```js
const state = { routes: [], menus: [], allPaths: [], accessiblePaths: [], superAdmin: false, loaded: false }

const mutations = {
  SET_ROUTES(state, payload) {       // 一次性写入多个字段
    state.routes = payload.routes
    state.menus = payload.menus
    state.loaded = true
  },
  RESET_STATE(state) { /* 全部清零 */ }
}

const actions = {
  generateRoutes({ commit }) {
    return getRouters().then(res => {
      const { routes } = buildRoutes(res.data.routers || [])
      commit('SET_ROUTES', { routes, menus: res.data.routers, /* ... */ })
      return routes
    })
  }
}
```

### Vuex 的痛点

- **`mutations` 是强制的样板**：哪怕只是 `state.x = 1`，也要写一个 `SET_X` mutation，异步 action 里再 `commit`。
- **跨模块调用啰嗦**：`commit('permission/RESET_STATE', null, { root: true })`，三个参数容易写错。
- **`mapState` / `mapActions` 辅助函数**虽方便，但类型推导弱、来源仍需查模块。

## 三、Pinia：更简洁的现代方案

Pinia 是 Vue 官方推荐的状态库。**最大变化：去掉了 `mutations`**——`state` 可直接改，`action` 既能写同步逻辑也能 `await` 异步，彻底省掉样板。

### 选项式写法

```js
// stores/user.js
import { defineStore } from 'pinia'

export const useUserStore = defineStore('user', {
  state: () => ({ token: '', name: '', roles: [], permissions: [] }),
  getters: {
    isAdmin: (state) => state.roles.includes('admin')
  },
  actions: {
    async login(userInfo) {                 // action 直接 async，不必包 Promise
      const res = await login(userInfo)
      this.token = res.data.token           // 直接改 state，无需 mutation
      setToken(res.data.token)
    },
    async logout() {
      await logout()
      this.$reset()                         // 内置重置，替代 RESET_STATE
      removeToken(); resetRouter()
    }
  }
})
```

### Composition 写法（推荐，类型友好）

```js
// stores/user.js（组合式）
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

export const useUserStore = defineStore('user', () => {
  const token = ref('')
  const name = ref('')
  const roles = ref([])
  const isAdmin = computed(() => roles.value.includes('admin'))

  async function login(userInfo) {
    const res = await login(userInfo)
    token.value = res.data.token
  }
  return { token, name, roles, isAdmin, login }
})
```

组件中使用（无需 `mapXxx`）：

```vue
<script setup>
import { useUserStore } from '@/stores/user'
const user = useUserStore()
user.login(form)            // 直接调 action
console.log(user.name)      // 直接读 state
</script>
```

## 四、真实对照：把 user / permission 迁到 Pinia

把 codegen-web 的 `user` 模块改写为 Pinia（组合式写法）：

```js
// stores/user.js（Pinia 等价，对应 src/store/modules/user.js）
import { defineStore } from 'pinia'
import { ref } from 'vue'
import { login, logout, getInfo } from '@/api/user'
import { getToken, setToken, removeToken } from '@/utils/auth'

export const useUserStore = defineStore('user', () => {
  const token = ref(getToken() || '')
  const name = ref('')
  const roles = ref([])
  const permissions = ref([])

  async function loginAction(userInfo) {
    const { data } = await login(userInfo)
    token.value = data.token; setToken(data.token)
  }
  async function getInfo() {
    const { data } = await getInfo()
    name.value = data.nickname || data.username
    roles.value = data.roles || ['admin']
    permissions.value = data.permissions || []
  }
  async function logoutAction() {
    await logout()
    token.value = ''; name.value = ''; roles.value = []
    removeToken(); resetRouter()
  }
  return { token, name, roles, permissions, loginAction, getInfo, logoutAction }
})
```

`permission` 模块同理（对应 `src/store/modules/permission.js`）：

```js
// stores/permission.js（Pinia 等价）
import { defineStore } from 'pinia'
import { ref } from 'vue'
import { getRouters } from '@/api/user'

export const usePermissionStore = defineStore('permission', () => {
  const routes = ref([])
  const menus = ref([])
  const accessiblePaths = ref([])
  const loaded = ref(false)

  async function generateRoutes() {
    const { data } = await getRouters()
    const built = buildRoutes(data.routers || [])
    routes.value = built.routes
    menus.value = data.routers
    accessiblePaths.value = collectPaths(data.routers)
    loaded.value = true
    return built.routes
  }
  return { routes, menus, accessiblePaths, loaded, generateRoutes }
})
```

> 迁移要点：原 `mutations`（`SET_TOKEN` / `SET_ROUTES` / `RESET_STATE`）全部消失，改为直接赋值或 `this.$reset()`；跨模块调用从 `commit('x/RESET_STATE', null, { root: true })` 变成 `useXxxStore().xxx()`，语义清晰且无样板。

## 本章小结

- Pinia 用 `defineStore` 定义 store，提供**选项式**与**组合式**两种写法，后者类型推导最佳。
- 核心简化：**删除 `mutations`**，state 可直接改，`action` 同步异步通吃；跨模块直接调用另一个 store 的方法。
- Vuex 3 的 `state/getters/mutations/actions` + `namespaced` + `mapState/mapActions` 是 codegen-web 的真实用法，模块清晰但样板偏多。
- 企业后台的「用户（token/信息/角色）+ 权限（动态路由）」状态，在 Pinia 下用两个 store 即可等价表达，代码量显著下降。

## ⚠️ 踩坑提示

1. **误以为 Pinia 仍需要 mutation**：很多从 Vuex 过来的开发者会下意识写 `mutations`，Pinia 里它不存在——直接 `state.x = y` 或 `this.x = y` 即可，写进 `actions` 也行。
2. **store 必须在 setup / 组件里调用**：`useUserStore()` 依赖当前激活的 Pinia 实例，不要在模块顶层（store 定义之外）调用，否则报「no active Pinia」。`@/stores` 的实例需在 `app.use(pinia)` 之后才可用。
3. **解构会丢失响应式**：`const { name } = useUserStore()` 会让 `name` 变成普通值。要解构请用 `storeToRefs(store)`：`const { name } = storeToRefs(user)`。
4. **`$reset()` 仅选项式 store 默认支持**：组合式 store 需自行实现重置逻辑（或在 actions 里逐个置空），不要直接调 `this.$reset()` 期望生效。
