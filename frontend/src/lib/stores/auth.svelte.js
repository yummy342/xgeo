import { api } from '../api.js'
import { routeFor } from '../navrules.js'

// 身份：怎么进来的、是谁、是不是管理员。
//
// 谁在用它：侧栏（邮箱 + 登出 + 按身份过滤入口）、路由（别把非管理员停在只有
// 管理员能用的页面上）。两处都要，所以放成共享 store，`/api/auth/me` 只发一次。
//
// 身份未知或查不到时一律当作管理员：**隐藏入口只是体验**，服务端每个路由照旧判权，
// 前端这一层不作为边界。
export const auth = $state({ mode: '', email: '', admin: true, loaded: false })

export async function loadAuth() {
  const r = await api('/api/auth/me')
  if (r && !r.error) {
    auth.mode = r.mode || ''
    auth.email = r.email || ''
    auth.admin = r.admin !== false
  }
  auth.loaded = true
}

/** 非管理员落到只有管理员能用的页面时改道总览。
 *  路由层与启动时的默认路由都走这里 —— 只在侧栏隐藏的话，手敲 #settings 或
 *  「项目还没有采样数据 → 默认去设置页」这两条路都绕得过去。 */
export function allowedRoute(name) {
  return routeFor(name, auth.admin)
}
