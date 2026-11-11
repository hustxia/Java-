# 第 14 章 基于 axios 的请求层设计

## 本章目标

- 掌握 axios 实例的创建与个性化配置（baseURL / timeout）。
- 理解请求拦截器与响应拦截器的职责边界，能够统一注入 token、解包 `res.data`、按状态码做统一错误处理。
- 会区分「二进制流」与「业务 JSON」两种响应，避免把文件下载当成业务错误。
- 了解取消请求（CancelToken / AbortController）的适用场景。
- 把 API 按资源拆成独立模块，让组件只关心业务语义。
- 通过 codegen-web 的真实 `src/utils/request.js` 与 `src/api/monitor.js`，看一个生产级请求层长什么样。

---

## 14.1 Vue 3 标准写法：先有个 axios 实例

直接 `axios.get(url)` 虽然方便，但项目里往往有多个环境、统一的超时、统一的鉴权头——这些应该收敛到一个实例里。Vue 3（及任何现代前端）推荐这样起步：

```js
// src/utils/request.js
import axios from 'axios'

// 全局只创建一个实例，后续所有请求都走它
const service = axios.create({
  baseURL: import.meta.env.VITE_APP_BASE_API, // Vue 3 + Vite 的环境变量前缀是 VITE_
  timeout: 15000,                             // 15 秒超时，避免界面卡死
  headers: { 'Content-Type': 'application/json' }
})

export default service
```

`import.meta.env.VITE_APP_BASE_API` 是 Vite 读取 `.env` 的方式（详见第 16 章），前缀必须是 `VITE_` 才会暴露到客户端。

---

## 14.2 请求拦截器：统一注入 token

拦截器是 axios 最实用的能力之一。请求发出前，把登录拿到的 token 塞进 `Authorization` 头：

```js
// 请求拦截器：每个请求自动带 token
service.interceptors.request.use(
  config => {
    const token = localStorage.getItem('token')
    if (token) {
      config.headers['Authorization'] = `Bearer ${token}`
    }
    return config // 必须 return，否则请求配置丢失
  },
  error => Promise.reject(error)
)
```

⚠️ 陷阱：拦截器回调里忘了 `return config`，请求会直接挂起。两条分支都必须返回值。

---

## 14.3 响应拦截器：统一解包与错误处理

后端通常返回 `{ code, msg, data }`，约定 `code === 0 || 200` 为成功。响应拦截器负责「剥壳」，让业务代码直接拿到 `res.data`：

```js
service.interceptors.response.use(
  response => {
    const res = response.data
    if (res.code !== 0 && res.code !== 200) {
      // 业务失败：弹提示并 reject，让调用方 try/catch 处理
      showError(res.msg || '请求失败')
      return Promise.reject(new Error(res.msg || '请求失败'))
    }
    return res // 注意：返回的是 res（含 data），不是 response
  },
  error => {
    // HTTP 层错误（网络断开、5xx、401 等）走这里
    showError(error.message)
    return Promise.reject(error)
  }
)
```

**关键点**：`return res` 后业务侧拿到的是「剥壳对象」，所以 API 模块常再 `.then(res => res.data)` 一次（见 14.6）。

---

## 14.4 别把文件下载当成业务错误

`responseType: 'blob' / 'arraybuffer'` 的端点（文件下载、文档预览）成功时返回的是文件本身，失败时后端却用 HTTP 4xx + JSON 体返回错误信息。这类响应必须**跳过业务码校验**，否则会把一个成功的下载误判成错误：

```js
service.interceptors.response.use(
  response => {
    // 二进制流：直接放行，交给调用方自己处理文件
    if (response.config.responseType === 'blob' ||
        response.config.responseType === 'arraybuffer') {
      return response
    }
    const res = response.data
    if (res.code !== 0 && res.code !== 200) { /* ... */ }
    return res
  },
  error => { /* ... */ }
)
```

如果失败流要取其中的文案，需把 ArrayBuffer 解码成 JSON 再读 `msg`（真实项目见 14.7）。

---

## 14.5 取消请求：AbortController

在搜索框输入联想、标签页快速切换等场景，旧请求可能还没返回新请求就发出去了。用原生 `AbortController` 取消上一个请求：

```js
// Vue 3 组合式写法
import { ref } from 'vue'
import request from '@/utils/request'

const controller = ref(null)

async function search(keyword) {
  controller.value?.abort()        // 取消上一次还在飞的请求
  controller.value = new AbortController()
  const res = await request({
    url: '/search',
    params: { keyword },
    signal: controller.value.signal // 把信号挂到请求上
  })
  return res.data
}
```

> 旧版 `CancelToken` 已废弃，统一用原生 `AbortController`。

---

## 14.6 按资源拆 API 模块

不要让组件里散落一堆 `request({ url: '/xxx' })`。按业务资源（user、monitor、gen…）聚合成模块，组件只调用语义化函数：

```js
// src/api/monitor.js
import request from '@/utils/request'

export function getMonitorOverview() {
  return request({ url: '/monitor/overview', method: 'get' }).then(res => res.data)
}

export function getMonitorSeries(metric, minutes = 30) {
  return request({ url: '/monitor/series', method: 'get', params: { metric, minutes } })
    .then(res => res.data)
}
```

组件侧：`const data = await getMonitorOverview()`，干净利落。

---

## 14.7 真实项目对照：codegen-web 的生产级请求层

### 真实文件：`src/utils/request.js`（axios 实例 + 拦截器）

```js
// src/utils/request.js（codegen-web 真实代码，节选）
import axios from 'axios'
import { Message, MessageBox } from 'element-ui' // Vue 2 的 Element UI
import store from '@/store'
import { getToken } from '@/utils/auth'

// 创建 axios 实例：baseURL 读 webpack 的环境变量 VUE_APP_BASE_API
const service = axios.create({
  baseURL: process.env.VUE_APP_BASE_API,
  timeout: 15000
})

// 请求拦截器：注入 Bearer token
service.interceptors.request.use(
  config => {
    const token = getToken()
    if (token) {
      config.headers['Authorization'] = `Bearer ${token}`
    }
    return config
  },
  error => Promise.reject(error)
)

// 401 统一回登录页，且并发请求只弹一次（relogging 标志位）
let relogging = false
function toLogin() {
  if (relogging) return
  relogging = true
  MessageBox.confirm('登录状态已失效，请重新登录', '提示', {
    confirmButtonText: '重新登录', cancelButtonText: '取消', type: 'warning'
  }).then(() => {
    store.dispatch('user/resetToken').then(() => {
      const redirect = encodeURIComponent(window.location.hash.replace(/^#/, '') || '/')
      window.location.href = `/#/login?redirect=${redirect}` // hash 模式回跳
      window.location.reload()
    })
  }).catch(() => { relogging = false })
}

// 二进制响应失败：ArrayBuffer 解码成 JSON 再取 msg
function messageOf(resp, fallback) {
  const data = resp && resp.data
  if (!data) return fallback
  if (data instanceof ArrayBuffer) {
    try {
      const json = JSON.parse(new TextDecoder('utf-8').decode(new Uint8Array(data)))
      return json.msg || json.message || fallback
    } catch (e) { return fallback }
  }
  return data.msg || data.message || fallback
}

// 响应拦截器：二进制流放行，业务码校验，401/网络错误统一提示
service.interceptors.response.use(
  response => {
    if (response.config.responseType === 'blob' || response.config.responseType === 'arraybuffer') {
      return response // 文件下载等直接放行
    }
    const res = response.data
    if (res.code !== 0 && res.code !== 200) {
      const isLoginApi = (response.config.url || '').indexOf('/auth/login') !== -1
      if (res.code === 401 && !isLoginApi) {
        toLogin() // 登录态失效回登录页；登录接口自身的 401 是账号密码错误，不跳转
        return Promise.reject(new Error(res.msg || '登录状态已失效'))
      }
      Message({ message: res.msg || '请求失败', type: 'error', duration: 5000 })
      return Promise.reject(new Error(res.msg || '请求失败'))
    }
    return res
  },
  error => {
    const resp = error.response
    if (resp && resp.status === 401) { // HTTP 401 同样回登录页
      toLogin()
      return Promise.reject(new Error(messageOf(resp, '登录状态已失效')))
    }
    Message({ message: messageOf(resp, error.message), type: 'error', duration: 5000 })
    return Promise.reject(error)
  }
)

export default service
```

**Vue 3 等价要点**：环境变量 `process.env.VUE_APP_BASE_API` → `import.meta.env.VITE_APP_BASE_API`；`import { Message, MessageBox } from 'element-ui'` → `import { ElMessage, ElMessageBox } from 'element-plus'`；`window.location.href = '/#/login'` → `useRouter().push('/login')`（history 模式）；拦截器返回 `res`、调用方再 `.then(res => res.data)` 的逻辑原样保留。

### 真实文件：`src/api/monitor.js`（按资源拆函数，返回 res.data）

```js
// src/api/monitor.js（codegen-web 真实代码，全文件）
import request from '@/utils/request'

export function getMonitorOverview() {
  return request({ url: '/monitor/overview', method: 'get' }).then(res => res.data)
}

export function getMonitorSeries(metric, minutes = 30) {
  return request({ url: '/monitor/series', method: 'get', params: { metric, minutes } }).then(res => res.data)
}

export function getMonitorHttp(minutes = 30, topN = 10) {
  return request({ url: '/monitor/http', method: 'get', params: { minutes, topN } }).then(res => res.data)
}

export function getMonitorBusiness(minutes = 30) {
  return request({ url: '/monitor/business', method: 'get', params: { minutes } }).then(res => res.data)
}
```

这个文件就是 14.6 模式的标准落地：每个函数对应一个监控资源端点，统一 `.then(res => res.data)` 把业务数据交给页面，完全不用关心 baseURL、token、错误弹窗——这些都在 `request.js` 里被统一消化了。

---

## 14.8 本章小结

- axios 实例是请求层的「单一出入口」，baseURL、timeout 在这里一次性定好。
- 请求拦截器做「鉴权注入」，响应拦截器做「解包 + 统一错误提示 + 登录态失效跳转」。
- 二进制响应必须跳过业务码校验；失败流要解码 ArrayBuffer 取文案。
- 取消请求用原生的 `AbortController`（替代已废弃的 CancelToken）。
- API 按资源拆分，组件只调用语义函数，彻底解耦。

## ⚠️ 踩坑提示

1. **拦截器忘了 `return config / res`** 会让请求挂起或拿到 `undefined`。
2. **401 与登录接口自身的错误混为一谈**：codegen-web 特判了 `/auth/login`，避免「账号密码错」被当成「登录态失效」弹出去重登录。升级到 Vue 3 时这个特判逻辑要原样保留。
3. **`relogging` 标志位不能丢**：多请求并发 401（如页面同时发 5 个接口）时，没有这个标志会弹 5 次确认框。Vue 3 重构时记得把这段「只弹一次」的逻辑平移过去。
4. 文件下载接口若被响应拦截器误判成业务错误，会出现「下载成功却报错」的诡异现象——务必按 14.4 放行 `blob/arraybuffer`。
