// 身份 → 界面规则的断言（纯函数，不起浏览器）。
//
// 为什么单独一条：这两条规则（非管理员看不到 engines/settings、落到那两页时改道
// 总览）原来只有 e2e 覆盖，而 e2e 不在 npm test 里 —— 少列一项 ADMIN_ONLY 之类的
// 回归要等有人手动跑 e2e 才会红。
import { ADMIN_ONLY, filterNav, routeFor } from '../src/lib/navrules.js'

let failed = 0
const check = (name, ok, extra = '') => {
  console.log(`${ok ? '✓' : '✗'} ${name}${extra ? ' — ' + extra : ''}`)
  if (!ok) failed++
}

const NAV = [
  { key: 'a', items: [['overview', 'Overview'], ['engines', 'Engines']] },
  { key: 'b', items: [['settings', 'Settings'], ['plan', 'Action Plan']] },
]

const admin = filterNav(NAV, true)
check('管理员看到全部', admin.flatMap((g) => g.items).length === 4)

const tenant = filterNav(NAV, false)
const keys = tenant.flatMap((g) => g.items).map(([k]) => k)
check('非管理员看不到管理员入口', !keys.includes('engines') && !keys.includes('settings'),
      keys.join(','))
check('其余入口一个不少', keys.length === 2 && keys.includes('overview') && keys.includes('plan'))
check('分组结构保留', tenant.length === NAV.length && tenant[1].items.length === 1)

check('身份未知时不隐藏', filterNav(NAV, undefined).flatMap((g) => g.items).length === 4)

check('非管理员落到管理员页时改道总览', routeFor('settings', false) === 'overview')
check('非管理员能停在普通页', routeFor('plan', false) === 'plan')
check('管理员不受影响', routeFor('settings', true) === 'settings')
check('身份未知时不改道', routeFor('settings', undefined) === 'settings')
check('ADMIN_ONLY 只列那两页', ADMIN_ONLY.size === 2 && ADMIN_ONLY.has('settings'))

console.log(failed ? `\n${failed} 条不通过` : '\n通过')
process.exit(failed ? 1 : 0)
