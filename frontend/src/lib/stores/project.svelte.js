import { api } from '../api.js'

// 取代旧代码的全局 D / SLUG / EXPD / ACTIONS。
// data 字段结构与 GET /api/p/<slug> 的返回一一对应，另外挂上 /api/files 与
// /api/expand 的补充字段（旧代码也是这么拼在 D 上的）。
export const project = $state({
  slug: null,
  data: null,
  error: null,
  loading: false,
})

export const projects = $state({ list: [], error: null })
export const actions = $state({ map: {} })

// ui.html:2970 逐字移植：analytics 出错时服务端返回 {error}，不是抛异常，
// 这个补丁把缺字段补齐，免得每个视图各自判空。
function normAnalytics(a) {
  a = (a && !a.error) ? a : {}
  const h = a.health = a.health || {}
  h.subs = h.subs || {}
  h.measured = h.measured || []
  a.trend = a.trend || []
  a.engines = a.engines || []
  a.questions = a.questions || []
  a.competitors = a.competitors || {}
  a.q_delta = a.q_delta || []
  a.factcheck = a.factcheck || []
  return a
}

/** 一个项目都没有时（接入引导页）用的空载荷，形状与真实载荷一致。 */
export function clearProject() {
  project.slug = null
  project.error = null
  project.data = { brand: {}, tasks: [], analytics: normAnalytics(null) }
}

export async function loadActions() {
  const r = await api('/api/actions')
  actions.map = (r && !r.error) ? r : {}
}

export async function loadProjects() {
  const r = await api('/api/projects')
  if (!Array.isArray(r)) {
    projects.error = (r && r.error) || '连接失败：服务未响应'
    projects.list = []
    return null
  }
  projects.error = null
  projects.list = r
  return r
}

/** 载入一个项目的全量数据。keep=true 时保留当前路由（刷新用）。 */
export async function loadProject(slug, keep = false) {
  project.loading = true
  project.slug = slug
  const d = await api('/api/p/' + encodeURIComponent(slug))
  const aerr = d.error || (d.analytics && d.analytics.error)
  d.brand = d.brand || {}
  d.tasks = d.tasks || []
  d.analytics = normAnalytics(d.analytics)

  if (aerr) {
    project.data = d
    project.error = aerr
    project.loading = false
    return { error: aerr }
  }

  const f = await api('/api/files/' + slug)
  d.samples_sheets = f.samples || []
  d.deliveries = f.deliveries || []
  d.reports = f.reports || []

  const ex = await api('/api/expand/' + slug)
  d.expand = (ex && !ex.error && ex.terms) ? ex : null

  const jr = await api('/api/jobs?slug=' + encodeURIComponent(slug))
  d.running_job = (jr && jr.running) || null

  project.data = d
  project.error = null
  project.loading = false
  return { error: null, data: d }
}
