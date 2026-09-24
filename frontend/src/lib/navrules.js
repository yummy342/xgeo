// 身份 → 界面规则的**纯**部分：隐藏哪些入口、非管理员改道哪去。
//
// 单独一个文件是为了能直接断言：nav.js 依赖 i18n store（`$state`），纯 node 里
// import 不了，于是这两条规则一度只有浏览器 e2e 覆盖 —— 而 npm test 不跑 e2e。
// 判权在服务端每个路由上，这里只是体验，所以「身份未知」一律不隐藏、不改道。
export const ADMIN_ONLY = new Set(['engines', 'settings'])

/** 按身份过滤导航分组。`admin` 为 true 或未知 → 原样返回。 */
export function filterNav(groups, admin) {
  if (admin !== false) return groups
  return groups.map((g) => ({ ...g, items: g.items.filter(([k]) => !ADMIN_ONLY.has(k)) }))
}

/** 非管理员落到只有管理员能用的页面时改道总览。 */
export function routeFor(name, admin) {
  return admin === false && ADMIN_ONLY.has(name) ? 'overview' : name
}
