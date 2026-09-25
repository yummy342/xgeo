// 身份 → 界面规则的断言（纯函数，不起浏览器）。
//
// 为什么单独一条：这两条规则（非管理员看不到 engines/settings、落到那两页时改道
// 总览）原来只有 e2e 覆盖，而 e2e 不在 npm test 里 —— 少列一项 ADMIN_ONLY 之类的
// 回归要等有人手动跑 e2e 才会红。
import { ADMIN_ONLY, NAV, filterNav, routeFor } from '../src/lib/navrules.js'

let failed = 0
const check = (name, ok, extra = '') => {
  console.log(`${ok ? '✓' : '✗'} ${name}${extra ? ' — ' + extra : ''}`)
  if (!ok) failed++
}

// 用**真表**：自己造一份夹具的话，新增一个管理页却忘了进 ADMIN_ONLY 时
// 这些断言照样全绿 —— 那就白写了。
const flat = (groups) => groups.flatMap((g) => g.items).map(([k]) => k)
const ALL = flat(NAV)

check('管理员看到全部', flat(filterNav(NAV, true)).length === ALL.length)
check('身份未知时不隐藏', flat(filterNav(NAV, undefined)).length === ALL.length)

check('ADMIN_ONLY 里的每一项都真的在导航里', [...ADMIN_ONLY].every((k) => ALL.includes(k)),
      [...ADMIN_ONLY].join(','))

const tenant = flat(filterNav(NAV, false))
check('非管理员看不到管理员入口', !tenant.some((k) => ADMIN_ONLY.has(k)), tenant.join(','))
check('非管理员其余入口一个不少', tenant.length === ALL.length - ADMIN_ONLY.size,
      `${tenant.length} vs ${ALL.length - ADMIN_ONLY.size}`)
check('分组结构保留', filterNav(NAV, false).length === NAV.length)

check('导航项不重复', new Set(ALL).size === ALL.length)

check('非管理员落到管理员页时改道总览', routeFor('settings', false) === 'overview')
check('非管理员能停在普通页', routeFor('plan', false) === 'plan')
check('管理员不受影响', routeFor('settings', true) === 'settings')
check('身份未知时不改道', routeFor('settings', undefined) === 'settings')
check('ADMIN_ONLY 只列那两页', ADMIN_ONLY.size === 2 && ADMIN_ONLY.has('settings'))

console.log(failed ? `\n${failed} 条不通过` : '\n通过')
process.exit(failed ? 1 : 0)
