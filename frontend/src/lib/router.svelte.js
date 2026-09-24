import { ui } from './stores/ui.svelte.js'
import { allowedRoute } from './stores/auth.svelte.js'

// 与 ui.html:2959 的 VIEWS 键一一对应
export const ROUTES = [
  'overview', 'engines', 'competitors', 'questions', 'samples',
  'siteaudit', 'gaps', 'channels', 'facts',
  'plan', 'workbench', 'assets',
  'verify', 'report',
  'settings', 'publishing', 'onboard',
]

export const route = $state({ name: 'overview' })

/** 取代 ui.html:184 的 go()。路由是 hash 的，Svelte 负责重渲染。 */
export function go(name, extra, fromPop) {
  if (!ROUTES.includes(name)) name = 'overview'
  // 非管理员不进只有管理员能用的页面（手敲 hash、浏览器后退、深链都走这里）
  name = allowedRoute(name)
  route.name = name
  if (extra) Object.assign(ui, extra)
  if (!fromPop) {
    history.pushState({ r: name, engSel: ui.engSel, wq: extra?.wq || null }, '', '#' + name)
  }
  scrollTo(0, 0)
  document.getElementById('side')?.classList.remove('open')
}

/** 读 hash 里的深链（旧代码 load() 末尾那段）。 */
export function routeFromHash() {
  const h = (location.hash || '').replace('#', '')
  return ROUTES.includes(h) ? h : null
}

export function syncHash(name) {
  history.replaceState({ r: name, engSel: ui.engSel, wq: null }, '', '#' + name)
}

if (typeof window !== 'undefined') {
  window.addEventListener('popstate', (e) => {
    const s = e.state
    if (!s || !s.r) return
    if (s.engSel !== undefined) ui.engSel = s.engSel
    if (s.r === 'workbench' && s.wq) ui.wq = s.wq
    go(s.r, null, true)
  })
}
