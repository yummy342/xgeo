// 侧栏导航结构。取代 legacy 的 NAV 常量（原来由 installBridge 挂成 window.GL_NAV）。
//
// 分组的顺序就是产品的主线：现状 → 诊断 → 提升 → 成效，最后是账号类。
// 标签用英文源文案，中文由 t() 查字典。
import { t } from './i18n/index.svelte.js'

export const NAV = [
  { key: 'status', label: 'STATUS · HOW AI SEES ME', items: [
    ['overview', 'Overview'], ['engines', 'Engines'], ['competitors', 'Competitors'],
    ['questions', 'Questions'], ['samples', 'Samples'],
  ] },
  { key: 'diagnosis', label: 'DIAGNOSIS · WHY', items: [
    ['siteaudit', 'Site Audit'], ['gaps', 'Gap Diagnosis'],
    ['channels', 'Channel Map'], ['facts', 'Brand Facts'],
  ] },
  { key: 'action', label: 'ACTION · WHAT TO DO', items: [
    ['plan', 'Action Plan'], ['workbench', 'Workbench'], ['assets', 'Assets'],
  ] },
  { key: 'results', label: 'RESULTS · DID IT WORK', items: [
    ['verify', 'Verification'], ['report', 'Reports & Delivery'],
  ] },
  { key: 'account', label: 'ACCOUNT', items: [
    ['settings', 'Settings'], ['publishing', 'Publishing'],
  ] },
]

/** 侧栏角标：各视图当前最该看的那个数字。没有就留空。 */
export function badgeFor(data, key) {
  if (!data) return ''
  const a = data.analytics || {}
  switch (key) {
    case 'questions':
      return String(data.question_count || '')
    case 'siteaudit':
      return data.audit?.avg_score != null ? String(data.audit.avg_score) : ''
    case 'assets':
      return data.lint?.total ? '!' + data.lint.total : ''
    case 'engines':
      return String((a.engines || []).length || '')
    case 'plan': {
      const n = (data.tasks || []).filter((x) => x.status !== 'done').length
      return n ? String(n) : ''
    }
    case 'gaps': {
      const q = (a.questions || []).filter((x) => x.content !== '已成稿' && !x.brand_probe).length
      return q ? String(q) : ''
    }
    case 'verify': {
      const n = (a.q_delta || []).filter((x) => (x.after || 0) > (x.before || 0)).length
      return n ? String(n) : ''
    }
    default:
      return ''
  }
}

/** 「只有管理员能用」的入口：这两页都读 /api/keys，租户会话点进去只吃 403。
 *  隐藏它们纯属体验，判权在服务端每个路由上 —— 身份未知时**不隐藏**。 */
export const ADMIN_ONLY = new Set(['engines', 'settings'])

/** 按身份过滤后的导航。`admin` 为 true 或未知 → 原样返回。 */
export function navFor(admin) {
  if (admin !== false) return NAV
  return NAV.map((g) => ({ ...g, items: g.items.filter(([k]) => !ADMIN_ONLY.has(k)) }))
}

export const LANGS = [['zh', '中'], ['en', 'EN'], ['ja', '日']]
export const NAV_LABELS = (g) => t(g.label)
