// 17 条路由的冒烟验证：起一个真浏览器，逐条切路由，断言视图渲染出内容且控制台无错误。
// 用 DOM 断言而不是截图比对——截图会被旧帧、字体、动画时序干扰，断言不会。
//
// 用法：先起服务，再跑
//   python scripts/geo.py ui --no-open --port 8799
//   node frontend/scripts/smoke.mjs
const BASE = process.env.GL_URL || 'http://127.0.0.1:8799'

// 侧栏能点到的 16 条。onboard 不在里面——它是接入引导页，没有导航入口，
// 只在「一个项目都没有」时自动出现，所以下面单独验证它的渲染。
const ROUTES = [
  'overview', 'engines', 'competitors', 'questions', 'samples',
  'siteaudit', 'gaps', 'channels', 'facts',
  'plan', 'workbench', 'assets',
  'verify', 'report',
  'settings', 'publishing',
]

const { chromium } = await import('playwright')
const browser = await chromium.launch()
// 必须显式指定：Playwright 默认跟随系统语言，在中文机器上会拿到 zh-CN，
// 于是 t() 返回中文、下面那些英文断言全部落空。
const page = await browser.newPage({ locale: 'en-US' })

const consoleErrors = []
page.on('console', (m) => { if (m.type() === 'error') consoleErrors.push(m.text()) })
page.on('pageerror', (e) => consoleErrors.push('pageerror: ' + e.message))

await page.goto(BASE, { waitUntil: 'networkidle' })
// 等 boot() 跑完：侧栏出现说明数据和路由都就绪了
await page.waitForSelector('#side .navit', { timeout: 10000 })

// 已迁到 Svelte 的视图 → 它独有的一段文案。用来证明这条路由走的是新组件，
// 而不是悄悄退回 LegacyView（两者都会渲染出内容，只看长度分不出来）。
const MIGRATED = {
  facts: 'Discipline:',                            // Facts.svelte 独有的英文源文案
  channels: 'Build cadence in phases',             // Channels.svelte
  plan: 'Auto-verify',                             // Plan.svelte
  samples: 'reviewable and correctable',           // Samples.svelte
  verify: 'Per-question before',                   // Verify.svelte（别选依赖数据的段落，
                                                   // 数据为空时那一段根本不渲染）
  assets: 'deployable artifacts',                  // Assets.svelte
  gaps: 'fix them in order',                       // Gaps.svelte
  questions: 'source of every number',             // Questions.svelte
  report: 'Three people need',                     // Report.svelte
  workbench: 'write right here',                   // Workbench.svelte
  siteaudit: 'SITE AUDIT',                         // SiteAudit.svelte — 用 kicker，
                                                   // 有站点/无站点两个分支都有它
  competitors: 'COMPETITORS',                      // Competitors.svelte — 同样用 kicker
  publishing: 'PUBLISHING',                        // Publishing.svelte
  engines: 'ENGINES',                              // Engines.svelte
  overview: 'OVERVIEW',                            // Overview.svelte
  settings: 'grouped by what changing it affects', // Settings.svelte
}

let failed = 0

const navCount = await page.locator('#side .navit').count()
// NAV 是 16 项：onboard 是接入引导页，不出现在导航里
console.log(`侧栏导航项: ${navCount}（应为 16）`)
if (navCount !== 16) failed++

// 账号块只在账号档渲染。这条档位（默认档）没有账号可说，侧栏必须与加登录之前
// 逐字一致 —— 令牌档同理，服务端不知道你是谁。
const whoCount = await page.locator('#side .who, #side .mail, #side .out').count()
if (whoCount !== 0) failed++
console.log(`${whoCount === 0 ? '  ok' : 'FAIL'}  账号块       ${whoCount} 个元素（应为 0）`)

for (const r of ROUTES) {
  await page.click(`#side .navit[data-route="${r}"]`)
  await page.waitForTimeout(250)
  const text = (await page.locator('#main').innerText()).trim()
  const marker = MIGRATED[r]
  const markerOk = !marker || text.includes(marker)
  const ok = text.length > 20 && markerOk
  if (!ok) failed++
  const mark = marker ? (markerOk ? '  [svelte]' : '  ← 没走新组件') : ''
  console.log(`${ok ? '  ok' : 'FAIL'}  ${r.padEnd(12)} ${String(text.length).padStart(6)} 字符${mark}`)
}

// onboard：接入引导页没有导航入口，只在「一个项目都没有」时自动出现，
// 所以上面那 16 条覆盖不到它。走深链进来单独验一次——它同样是迁移过来的视图，
// 一样会坏，只是没人点得到而已。
await page.goto(`${BASE}/#onboard`, { waitUntil: 'networkidle' })
await page.reload({ waitUntil: 'networkidle' })   // 只改 hash 不会重载，boot() 也就不重跑
await page.waitForTimeout(400)
const obText = (await page.locator('#main').innerText()).trim()
const obMarkers = ['ONBOARDING', 'Site domain', 'Create and start the automatic run']
const obOk = obMarkers.every((m) => obText.includes(m))
if (!obOk) failed++
console.log(`${obOk ? '  ok' : 'FAIL'}  ${'onboard'.padEnd(12)} ${String(obText.length).padStart(6)} 字符`
  + `${obOk ? '  [svelte]' : '  ← 没渲染出引导页'}`)

// 语言切换：写 localStorage 后重载，视图应显示中文（字典命中）。
// 必须 reload —— 语言在模块加载时读一次。
await page.evaluate(() => localStorage.setItem('ulang', 'zh'))
await page.reload({ waitUntil: 'networkidle' })
await page.waitForSelector('#side .navit')
await page.click('#side .navit[data-route="facts"]')
await page.waitForTimeout(300)
const zhText = (await page.locator('#main').innerText()).trim()
const zhOk = zhText.includes('纪律：')
if (!zhOk) failed++
console.log(`${zhOk ? '  ok' : 'FAIL'}  中文回退      视图文案走 zh 字典`)

await browser.close()

if (consoleErrors.length) {
  console.log(`\n控制台错误 ${consoleErrors.length} 条:`)
  for (const e of consoleErrors.slice(0, 10)) console.log('  ' + e)
}
const TOTAL = ROUTES.length + 1   // + onboard（深链单独验）
console.log(`\n结果: ${TOTAL - failed}/${TOTAL} 页面渲染成功`
  + `（含深链的 onboard）, 导航 ${navCount} 项, 控制台错误 ${consoleErrors.length}`)
process.exit(failed || consoleErrors.length ? 1 : 0)
