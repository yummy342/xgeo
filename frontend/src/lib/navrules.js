// 身份 → 界面规则的**纯**部分：隐藏哪些入口、非管理员改道哪去。
//
// 单独一个文件是为了能直接断言：nav.js 依赖 i18n store（`$state`），纯 node 里
// import 不了，于是这两条规则一度只有浏览器 e2e 覆盖 —— 而 npm test 不跑 e2e。
// 判权在服务端每个路由上，这里只是体验，所以「身份未知」一律不隐藏、不改道。
export const ADMIN_ONLY = new Set(['engines', 'settings'])

// 导航表放在这里（纯数据，不依赖 i18n）—— 审计脚本要用**真表**断言，
// 否则新增一个管理页却忘了进 ADMIN_ONLY 时，那几条断言照样全绿。
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

/** 按身份过滤导航分组。`admin` 为 true 或未知 → 原样返回。 */
export function filterNav(groups, admin) {
  if (admin !== false) return groups
  return groups.map((g) => ({ ...g, items: g.items.filter(([k]) => !ADMIN_ONLY.has(k)) }))
}

/** 非管理员落到只有管理员能用的页面时改道总览。 */
export function routeFor(name, admin) {
  return admin === false && ADMIN_ONLY.has(name) ? 'overview' : name
}
