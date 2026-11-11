# 第 12 章 Vue Router：从 Vue Router 3 到 4

## 本章目标

- 掌握 Vue Router 4 的核心 API：`createRouter` / `createWebHistory`、路由元信息 `meta`、动态路由、嵌套路由、全局守卫 `beforeEach`。
- 理解 Vue Router 4 相对 Vue 2 用的 Vue Router 3（本项目 codegen-web 所用）的关键差异。
- 以 codegen-web 的 `src/router/index.js` 与 `src/permission.js` 为「企业后台路由组织」真实范例，看懂动态路由 + 权限守卫的落地方式。
- 给出一套等价的 Vue Router 4 写法。

## 一、Vue Router 4 的核心写法

Vue Router 4 用**工厂函数**创建路由实例，不再用 `new VueRouter`：

```js
// router/index.js（Vue Router 4）
import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  { path: '/', component: () => import('@/views/Home.vue'), meta: { title: '首页' } },
  { path: '/user/:id', name: 'User', component: () => import('@/views/User.vue') }
]

const router = createRouter({
  history: createWebHistory(),        // 对应 Vue 2 的 mode: 'history'
  routes
})
export default router
```

- `createWebHistory()` 取代 `mode: 'history'`；还有 `createWebHashHistory()`（hash 模式）。
- 路由懒加载仍是 `() => import('@/views/Xxx.vue')`，Webpack / Vite 自动分包。
- `meta` 用于挂自定义信息（标题、权限码、是否需要登录等），通过 `to.meta` 读取。

## 二、嵌套路由与动态路由

嵌套路由用 `children` 描述层级，父级用 `<router-view>` 作为出口；动态路由用 `:param` 占位：

```js
const routes = [
  {
    path: '/admin',
    component: () => import('@/layout/Admin.vue'),   // 含 <router-view/>
    children: [
      { path: 'list', component: () => import('@/views/admin/List.vue') },
      { path: 'detail/:id', name: 'AdminDetail', component: () => import('@/views/admin/Detail.vue') }
    ]
  }
]
```

**动态注册**：Vue Router 4 用 `router.addRoute(route)`（可带父路由名 `router.addRoute('Admin', child)`）；Vue Router 3 早期是 `router.addRoutes(routes)`，Vue 2.7 已提供单条 `addRoute`。

## 三、全局守卫 beforeEach

守卫签名 `(to, from, next) => {}` 在 Vue Router 4 中 `next` 可选（返回 `false` 取消、返回路由对象重定向）。Vue Router 3 必须显式调用 `next()`：

```js
// Vue Router 4：next 可省略
router.beforeEach((to) => {
  if (to.meta.requiresAuth && !store.token) {
    return { path: '/login', query: { redirect: to.fullPath } }
  }
})
```

## 四、真实项目对照：codegen-web 的路由组织

codegen-web 使用 **Vue Router 3**（`new VueRouter` + `mode: 'history'`）。先看 `src/router/index.js` 的常量路由与实例创建（源码 `src/router/index.js:1-67`）：

```js
import Vue from 'vue'
import VueRouter from 'vue-router'
Vue.use(VueRouter)

// ① 重写 push/replace 吞掉未捕获的 Promise reject（重定向/重复导航会 reject）
const originalPush = VueRouter.prototype.push
VueRouter.prototype.push = function push(location, onResolve, onReject) {
  if (onResolve || onReject) return originalPush.call(this, location, onResolve, onReject)
  return originalPush.call(this, location).catch(err => err)   // 3.1+ 的坑：统一吞异常
}

// ② 常量路由：登录、403、404 + 根路径重定向（业务路由全部动态下发）
export const constantRoutes = [
  { path: '/login', name: 'Login', component: () => import('@/views/login/index.vue'), meta: { title: '登录' }, hidden: true },
  { path: '/', redirect: '/gen/table', hidden: true },
  { path: '*', component: () => import('@/views/error-page/404.vue'), hidden: true }  // 兜底放最后
]

const createRouter = () => new VueRouter({
  mode: 'history',                    // ★ Vue 3 改用 createWebHistory()
  scrollBehavior: () => ({ y: 0 }),
  routes: constantRoutes
})
const router = createRouter()

// ③ 登出时重置路由：用新的 matcher 覆盖，清掉动态路由
export function resetRouter() {
  const newRouter = createRouter()
  router.matcher = newRouter.matcher
}
```

动态路由由 `src/store/modules/permission.js` 的 `generateRoutes` 构建（源码 `src/store/modules/permission.js:16-97`）：它把后端下发的菜单树解析成组件（`resolveComponent` 用 `require.context` 按字符串取 `.vue`），目录节点用 `Layout` 包裹、子菜单挂 `children`，最后 push 一个 `path: '*'` 兜底 404。

真正的**全局守卫**在 `src/permission.js`（非 store 模块），逻辑非常完整（源码 `src/permission.js:9-62`）：

```js
import router from './router'
import store from './store'
import { getToken } from '@/utils/auth'

const whiteList = ['/login', '/404', '/403']

router.beforeEach(async (to, from, next) => {
  document.title = to.meta.title ? `${to.meta.title} - CodeGen 平台` : 'CodeGen 平台'
  const hasToken = getToken()
  if (!hasToken) {                       // 无 token：白名单放行，否则跳登录
    return whiteList.includes(to.path) ? next() : next(`/login?redirect=${to.path}`)
  }
  if (to.path === '/login') return next({ path: '/' })
  try {
    if (!store.getters.name) await store.dispatch('user/getInfo')
    if (!store.getters.routeLoaded) {     // 动态路由只拉一次
      const routes = await store.dispatch('permission/generateRoutes')
      routes.forEach(route => router.addRoute(route))   // Vue 2.7 单条 addRoute
      return next({ ...to, replace: true })   // 注册完重走导航，让 to 匹配新路由
    }
    // 越权判断：菜单存在但不在可访问列表 -> 403；其余未匹配 -> 404
    const allPaths = store.getters.allPaths || []
    const accessiblePaths = store.getters.accessiblePaths || []
    if (allPaths.includes(to.path) && !accessiblePaths.includes(to.path)) return next('/403')
    if (to.matched.length && to.matched.every(m => m.path === '*')) return next('/404')
    next()
  } catch (err) {
    await store.dispatch('user/resetToken')
    next(`/login?redirect=${to.path}`)
  }
})
```

## 五、Vue Router 4 等价写法

把上面的真实结构平移到 Vue Router 4（注意 `createWebHistory`、`addRoute` 不变、`next` 可选、404 用 `path: '/:pathMatch(.*)*'`）：

```js
// router/index.js（Vue Router 4 等价）
import { createRouter, createWebHistory } from 'vue-router'
import Layout from '@/layout/index.vue'
import { getRouters } from '@/api/user'

export const constantRoutes = [
  { path: '/login', name: 'Login', component: () => import('@/views/login/index.vue'), meta: { title: '登录' } },
  { path: '/', redirect: '/gen/table' },
  // Vue 4 的 catch-all 不再用 '*'，而是正则匹配
  { path: '/:pathMatch(.*)*', name: 'NotFound', component: () => import('@/views/error-page/404.vue'), meta: { title: '404' } }
]

const router = createRouter({
  history: createWebHistory(),          // ★ 取代 mode: 'history'
  scrollBehavior: () => ({ y: 0 }),
  routes: constantRoutes
})

// 守卫：next 可省略，用 return 表达重定向
router.beforeEach(async (to) => {
  document.title = to.meta.title ? `${to.meta.title} - CodeGen 平台` : 'CodeGen 平台'
  const hasToken = getToken()
  if (!hasToken) return whiteList.includes(to.path) ? true : `/login?redirect=${to.path}`
  if (to.path === '/login') return { path: '/' }
  if (!store.getters.name) await store.dispatch('user/getInfo')
  if (!store.getters.routeLoaded) {
    const routes = await store.dispatch('permission/generateRoutes')
    routes.forEach(r => router.addRoute(r))   // 单条 addRoute（同 Vue 2.7）
    return { ...to, replace: true }
  }
  if (isForbidden(to)) return '/403'
  return true
})

// 动态路由构建逻辑（resolveComponent / buildRoutes / generateRoutes）与 Vue 2 完全一致，
// 只是最终 router.matcher 重置改为：「重新 addRoute」或直接 router.go(0) 刷新。
export default router
```

## 本章小结

- Vue Router 4 用 `createRouter({ history: createWebHistory(), routes })` 取代 `new VueRouter({ mode: 'history' })`。
- `meta` 承载标题 / 权限等元信息；嵌套路由用 `children`；动态注册用 `router.addRoute`（Vue 4 不再有 `addRoutes`）。
- 全局守卫 `beforeEach`：Vue 4 中 `next` 可省略，直接 `return` 路由对象或 `false` 即可。
- codegen-web 用 Vue Router 3：`constantRoutes` + `resetRouter()`（matcher 覆盖）+ `permission.js` 里的 `beforeEach` 实现「登录鉴权 + 动态路由 + 越权 403」完整链路，是企业后台的经典模板。
- Vue 4 的 catch-all 从 `path: '*'` 改为 `path: '/:pathMatch(.*)*'`。

## ⚠️ 踩坑提示

1. **Vue 4 必须用 `createWebHistory()`**：直接 `new VueRouter` 或漏写 `history` 会报错。迁移时最容易忘记的一处。
2. **动态路由注册后必须重走导航**：`addRoute` 是异步生效的，当前 `to` 还停留在未匹配状态，需要 `return { ...to, replace: true }` 让路由重新解析，否则首帧空白。
3. **catch-all 写法变了**：Vue 4 不再支持 `path: '*'`，要用 `path: '/:pathMatch(.*)*'`，否则动态路由未匹配时不会落到 404 而是白屏。
4. **Vue Router 3.1+ 的 push reject**：本项目的 `originalPush` 重写就是为了吞掉重定向/重复导航的未捕获异常，迁移到 Vue 4 后 `push` 仍返回 Promise，记得用 `await` 或 `.catch` 处理。
