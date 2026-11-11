# 第 16 章 工程化、部署与 Vue 2 → Vue 3 迁移清单

## 本章目标

- 用 Vite 收口工程化：类型检查（vue-tsc）、构建优化、环境变量（`.env`）。
- 掌握 history 模式下的 nginx 部署与 fallback 配置。
- 落地四类性能优化：路由懒加载、组件按需、图片与图标优化。
- **重点**：拿到一份可执行的「Vue 2.7 → Vue 3 迁移清单」，每条都对照 codegen-web 真实文件给出改动点。
- 用 codegen-web 的真实结构（`src/main.js`、`store/modules/user.js`、`router/index.js`、`utils/request.js`）画出「这个后台升级到 Vue 3 究竟要改什么」。

---

## 16.1 Vite 工程化

### 16.1.1 类型检查 vue-tsc

Vite 本身不做类型检查（只转译）。生产构建前用 `vue-tsc` 跑一遍：

```bash
# package.json scripts
npm run type-check   # vue-tsc --noEmit
npm run build        # vue-tsc --noEmit && vite build
```

```json
// tsconfig.json 关键项
{
  "compilerOptions": {
    "target": "ESNext",
    "module": "ESNext",
    "moduleResolution": "bundler",
    "strict": true,
    "jsx": "preserve"
  },
  "include": ["src/**/*.ts", "src/**/*.vue"]
}
```

### 16.1.2 构建优化

```js
// vite.config.js
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  build: {
    rollupOptions: {
      output: {
        // 把体积大的依赖单独拆 chunk，利用浏览器长效缓存
        manualChunks: {
          echarts: ['echarts'],
          'element-plus': ['element-plus']
        }
      }
    },
    chunkSizeWarningLimit: 1500
  }
})
```

### 16.1.3 环境变量 `.env`

```bash
# .env.development
VITE_APP_BASE_API = '/dev-api'

# .env.production
VITE_APP_BASE_API = 'https://api.example.com'
```

代码里用 `import.meta.env.VITE_APP_BASE_API` 读取（**只有 `VITE_` 前缀的变量才会暴露给客户端**）。这与 codegen-web 的 `process.env.VUE_APP_BASE_API`（webpack 约定）是一一对应的，迁移时把前缀从 `VUE_APP_` 改成 `VITE_` 即可。

---

## 16.2 部署：nginx 反向代理 + history 模式 fallback

Vue Router 用 `history` 模式（codegen-web 也是 `mode: 'history'`）时，深链接刷新会 404——因为 `/gen/table` 在服务端没有真实文件。nginx 必须做两件事：代理 API、把未命中静态资源的请求 fallback 到 `index.html`。

```nginx
server {
  listen 80;
  server_name admin.example.com;
  root /usr/share/nginx/html;
  index index.html;

  # 反向代理后端 API（解决跨域，前端只访问同源路径）
  location /prod-api/ {
    proxy_pass http://backend:8080/;   # 末尾斜杠：去掉 /prod-api 前缀
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
  }

  # history 模式兜底：非文件请求一律回 index.html，交给前端路由
  location / {
    try_files $uri $uri/ /index.html;
  }

  # 静态资源长效缓存
  location ~* \.(js|css|png|woff2)$ {
    expires 30d;
    add_header Cache-Control "public, immutable";
  }
}
```

⚠️ 漏掉 `try_files ... /index.html` 会导致刷新子路由直接 404。codegen-web 用的也是 history 模式，上线部署务必配这一行。

---

## 16.3 性能优化四板斧

### 16.3.1 路由懒加载

codegen-web 的 `router/index.js` 已经用函数式 `component: () => import('@/views/...')` 做懒加载（每个路由一个独立 chunk）。Vue 3 + Vite 下写法完全一致，可进一步加魔法注释分组：

```js
{ path: '/gen/table', component: () => import(/* webpackChunkName: "gen" */ '@/views/gen/table.vue') }
```

### 16.3.2 组件按需

Element Plus 用 `unplugin-vue-components` 自动按需引入，打包时不拉全量库：

```js
// vite.config.js
import Components from 'unplugin-vue-components/vite'
import { ElementPlusResolver } from 'unplugin-vue-components/resolvers'

plugins: [vue(), Components({ resolvers: [ElementPlusResolver()] })]
```

### 16.3.3 图片优化

- 用 `vite-imagetools` 或构建期压缩，优先 `webp`。
- 大图走 CDN + `loading="lazy"` 懒加载。
- SVG 图标用 `vite-svg-loader` 直接当组件引入，不占额外请求。

### 16.3.4 图标优化

codegen-web 用的是 `el-icon-refresh` 这类字体图标（Element UI）。Element Plus 推荐用 `@element-plus/icons-vue` 的 SVG 图标，按需引入、tree-shaking 友好：

```js
import { Refresh } from '@element-plus/icons-vue'
// 模板：<el-icon><Refresh /></el-icon>
```

---

## 16.4 重点：Vue 2.7 → Vue 3 迁移清单

下面每一条都给出「旧写法 → 新写法」以及 codegen-web 里对应的真实位置。

### 16.4.1 Options API → `<script setup>`

| Vue 2（codegen-web 真实） | Vue 3 |
| --- | --- |
| `data() { return {...} }` | `const x = ref(0)` / `reactive({...})` |
| `computed: { ... }` | `const y = computed(() => ...)` |
| `methods: { foo(){} }` | 直接 `function foo(){}` |
| `mounted() {}` / `beforeDestroy() {}` | `onMounted()` / `onBeforeUnmount()` |
| `this.$refs.xxx` | `const xxx = ref(null)` 模板 `ref="xxx"` |

真实对照：`src/views/monitor/index.vue` 的 `data/computed/methods/mounted/beforeDestroy` 整体改为 `<script setup>`（本章 16.3 之前的章节已逐段示范）。

### 16.4.2 Vuex → Pinia

codegen-web 的 `src/store/modules/user.js` 是典型的 Vuex module（`state / mutations / actions`，`namespaced: true`）。迁移到 Pinia 后，mutation 被取消，action 直接改 state：

```js
// Pinia 等价（对应 store/modules/user.js）
import { defineStore } from 'pinia'
import { login, logout, getInfo } from '@/api/user'
import { getToken, setToken, removeToken } from '@/utils/auth'

export const useUserStore = defineStore('user', {
  state: () => ({
    token: getToken(), name: '', avatar: '', roles: [], permissions: [],
    themePref: ''
  }),
  actions: {
    async login(userInfo) {
      const { data } = await login({ username: userInfo.username.trim(), password: userInfo.password })
      this.token = data.token
      setToken(data.token)
    },
    async getInfo() {
      const { data } = await getInfo()
      this.name = data.nickname || data.username
      this.roles = data.roles || ['admin']
      this.permissions = data.permissions || []
    },
    logout() { this.$reset(); removeToken() }
  }
})
```

调用方从 `this.$store.dispatch('user/login')` 变为 `useUserStore().login(...)`。注意 Vuex 的 `commit('permission/RESET_STATE', null, { root: true })` 跨模块调用在 Pinia 里改为分别 `usePermissionStore().$reset()`。

### 16.4.3 filters 移除

Vue 3 彻底移除 `filters`。真实项目里若用过 `{{ value | fmt }}`（codegen-web 监控页没用 filter，而是用 `methods` 里的 `fmtMs/fmtPct`），全部改用**方法或 computed**：

```vue
<!-- Vue 2：{{ ms | fmtMs }}  →  Vue 3 -->
<span>{{ fmtMs(ms) }}</span>
```

如果 filter 是全局注册的（如 `Vue.filter('parseTime', ...)`），迁移时把它改成导出的纯函数再 `import` 使用。

### 16.4.4 事件总线 `$on/$off` 移除

Vue 3 实例不再有 `$on/$off/$once`。codegen-web 若用了 `Vue.prototype.$bus = new Vue()` 做跨组件通信，改用轻量库 **mitt**：

```js
// eventBus.js
import mitt from 'mitt'
export const bus = mitt()

// 发送：bus.emit('refresh', payload)
// 接收：bus.on('refresh', handler)；卸载时 bus.off('refresh', handler)
```

### 16.4.5 v-model 变更

- 自定义组件 `v-model` 的 prop/事件从 `value` + `input` 改为 **`modelValue` + `update:modelValue`**。
- `.sync` 修饰符被**移除**，统一用 `v-model:xxx`：

```vue
<!-- Vue 2: <Child :title.sync="t" />  →  Vue 3 -->
<Child v-model:title="t" />
```

codegen-web 的 `el-dialog` 用的是 `:visible.sync`，迁移到 Element Plus 的 `el-dialog` 要改回 `v-model="visible"`（Element Plus 内部已适配新 v-model）。

### 16.4.6 异步组件 API

```js
// Vue 2：() => import('@/views/x.vue')（函数直接当组件）
// Vue 3 显式 API（可带 loading 兜底）
import { defineAsyncComponent } from 'vue'
const X = defineAsyncComponent({
  loader: () => import('@/views/x.vue'),
  loadingComponent: Loading,
  errorComponent: ErrorComp
})
```

### 16.4.7 全局 API 改为 createApp().use()

真实文件 `src/main.js` 现在是 `new Vue({ router, store, render: h => h(App) }).$mount('#app')` + `Vue.use(ElementUI)`。Vue 3 改为：

```js
import { createApp } from 'vue'
import ElementPlus from 'element-plus'
import App from './App.vue'
import router from './router'
import { createPinia } from 'pinia'

const app = createApp(App)
app.use(createPinia())
app.use(router)
app.use(ElementPlus, { size: 'medium' })
app.mount('#app')
```

`Vue.config.productionTip`、`Vue.directive` 等全局静态调用都要改成 `app.xxx`。

### 16.4.8 第三方库兼容

| 库 | Vue 2（codegen-web） | Vue 3 |
| --- | --- | --- |
| UI | `element-ui`（`Vue.use(ElementUI)`） | `element-plus`（`app.use(ElementPlus)`） |
| 路由 | `vue-router@3`（`mode: 'history'`） | `vue-router@4`（`history: createWebHistory()`） |
| 状态 | `vuex@3` | `pinia` |
| 请求 | `axios`（不变） | `axios`（不变） |

vue-router@4 把 `mode: 'history'` 换成 `history: createWebHistory()`，`new VueRouter` 换成 `createRouter`，`*` 通配路由换成 `path: '/:pathMatch(.*)*'`（codegen-web 的 `router/index.js` 第 48 行 `{ path: '*', ... }` 必须改）。

---

## 16.5 真实收尾：codegen-web 升级到 Vue 3 要改什么

综合上面的清单，把四个真实文件逐一过一遍：

**1. `src/main.js`（入口）**
- `new Vue().$mount()` → `createApp(App).mount('#app')`
- `Vue.use(ElementUI)` → `app.use(ElementPlus)`
- `Vue.config.productionTip = false` → `app.config.productionTip = false`（或删，Vue 3 默认无此提示）
- 引入 `createPinia().use(pinia)`；`import 'element-plus/dist/index.css'` 替换 `element-ui/lib/theme-chalk/index.css`

**2. `store/modules/user.js`（Vuex module）**
- `state/mutations/actions + namespaced` → `defineStore('user', { state, actions })`，删掉所有 `mutations`，`commit` 改成直接 `this.xxx =`
- `dispatch('user/resetToken')`（见 `request.js` 的 `toLogin`）→ `useUserStore().resetToken()`
- 跨模块 `commit('permission/RESET_STATE', null, { root: true })` → 调 `usePermissionStore().$reset()`

**3. `router/index.js`（vue-router@3 → @4）**
- `new VueRouter({ mode: 'history' })` → `createRouter({ history: createWebHistory() })`
- `Vue.use(VueRouter)` → `app.use(router)`
- `*`（通配）→ `path: '/:pathMatch(.*)*'`
- 函数式 `() => import()` 懒加载写法保留（已符合 Vue 3）

**4. `utils/request.js`（请求层）**
- `process.env.VUE_APP_BASE_API` → `import.meta.env.VITE_APP_BASE_API`
- `import { Message, MessageBox } from 'element-ui'` → `import { ElMessage, ElMessageBox } from 'element-plus'`
- `window.location.href = '/#/login'` → `router.push('/login?redirect=...')`（history 模式，去掉 `#`）
- 其余拦截器逻辑（token 注入、`relogging` 标志、`messageOf` 解码、blob/arraybuffer 放行）**原样保留**，它们是业务正确性的关键

**附带**：所有 `.vue` 文件 `slot="header"` → `#header`、`slot-scope` → `#default`、`this.$refs` → `ref()`，监控页整体改 `<script setup>`。

---

## 16.6 全书收口：本书知识点 → codegen-web 真实文件映射表

| 本书章节 / 知识点 | codegen-web 对应真实文件 | 说明 |
| --- | --- | --- |
| 第 14 章 请求层 / 拦截器 / 按资源拆 API | `src/utils/request.js`、`src/api/monitor.js` | 实例 + 双拦截器 + 业务码解包 + 二进制放行；API 按监控资源拆函数 |
| 第 15 章 Element / ECharts 集成 | `src/views/monitor/index.vue`、`src/main.js` | el-* 组件齐用；ECharts 异步 chunk + init/dispose/resize + chartError 降级 |
| 第 16 章 路由懒加载 | `src/router/index.js` | 全部 `() => import()` 函数式懒加载 |
| 第 16 章 Vuex 状态管理 | `src/store/modules/user.js` | state/mutations/actions + namespaced |
| 第 16 章 入口与全局 API | `src/main.js` | `new Vue()` + `Vue.use(ElementUI)` + 主题初始化 |
| 第 16 章 history 模式部署 | `src/router/index.js`（mode: 'history'） | 上线需 nginx `try_files` fallback |
| 第 16 章 升级到 Vue 3 | 上述全部文件 | 见 16.4 / 16.5 迁移清单 |

这张表既是本书的索引，也是一份「拿真实项目练手」的行动清单：你完全可以 clone codegen-web，照着 16.5 的四条把整个后台迁到 Vue 3——它已经具备了绝大多数后台管理系统的典型结构（请求层、Vuex、动态路由、Element UI、ECharts 监控页），是绝佳的迁移练习场。

---

## 16.7 本章小结

- Vite 工程化三件事：vue-tsc 类型检查、manualChunks 拆包、`.env` 的 `VITE_` 前缀。
- 部署 history 模式务必配 nginx `try_files ... /index.html`，否则刷新子路由 404。
- 性能四板斧：路由懒加载、组件按需、图片 webp + 懒加载、SVG 图标按需。
- 迁移清单八条中最易漏：`.sync`→`v-model:xxx`、filters 移除、`$on/$off`→mitt、`*` 通配路由改 `pathMatch`、`request.js` 的 `relogging` 与 blob 放行必须原样保留。
- codegen-web 是贯穿全书的真实案例，迁移清单可直接作为你升级自己项目的检查表。

## ⚠️ 踩坑提示

1. **环境变量前缀写错**：webpack 用 `VUE_APP_`，Vite 用 `VITE_`。迁移时漏改前缀，运行时会读到 `undefined` 导致请求打到空 baseURL，页面全 504。
2. **`*` 通配路由不兼容 vue-router@4**：旧写法 `{ path: '*' }` 在 @4 会报错，必须改成 `path: '/:pathMatch(.*)*'`，否则构建即崩。
3. **保留 `relogging` 标志位的语义**：这是 codegen-web 请求层「401 只弹一次」的关键。迁移成 Vue 3 时若图省事删掉，多接口并发 401 会连弹多个确认框，体验灾难。
4. **blob/arraybuffer 放行不能丢**：下载接口若被新写的响应拦截器误判成业务错误，会出现「文件其实下载成功了却报错」的诡异现象。
5. **`el-dialog` 的 `.sync` 改 `v-model`**：升级 Element Plus 后，`<el-dialog :visible.sync>` 必须改 `v-model`，否则弹窗无法关闭。
