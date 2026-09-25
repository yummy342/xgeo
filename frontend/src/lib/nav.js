// 侧栏导航结构。取代 legacy 的 NAV 常量（原来由 installBridge 挂成 window.GL_NAV）。
//
// 分组的顺序就是产品的主线：现状 → 诊断 → 提升 → 成效，最后是账号类。
// 标签用英文源文案，中文由 t() 查字典。
//
// 导航表本身搬去了 navrules.js（纯数据）：那边不依赖 i18n store，npm test 里的
// 审计脚本能拿**真表**断言 —— 自己造夹具的话，新增一个管理页却忘了进 ADMIN_ONLY
// 时那些断言照样全绿。这里只留依赖 t() 的映射与角标。
import { t } from './i18n/index.svelte.js'
import { NAV, filterNav } from './navrules.js'

export { ADMIN_ONLY, NAV } from './navrules.js'

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

/** 按身份过滤后的导航。`admin` 为 true 或未知 → 原样返回。 */
export function navFor(admin) {
  return filterNav(NAV, admin)
}

export const LANGS = [['zh', '中'], ['en', 'EN'], ['ja', '日']]
export const NAV_LABELS = (g) => t(g.label)
