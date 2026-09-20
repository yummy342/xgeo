// 17 条路由的冒烟验证：起一个真浏览器，逐条切路由，断言视图渲染出内容且控制台无错误。
// 用 DOM 断言而不是截图比对——截图会被旧帧、字体、动画时序干扰，断言不会。
//
// 用法：先起服务，再跑
//   python scripts/geo.py ui --no-open --port 8799
//   node frontend/scripts/smoke.mjs
const BASE = process.env.GL_URL || 'http://127.0.0.1:8799'

const ROUTES = [
  'overview', 'engines', 'competitors', 'questions', 'samples',
  'siteaudit', 'gaps', 'channels', 'facts',
  'plan', 'workbench', 'assets',
  'verify', 'report',
  'settings', 'publishing', 'onboard',
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
// 等 boot() 跑完：侧栏出现说明 installBridge 和数据都就绪了
await page.waitForSelector('#side .navit', { timeout: 10000 })

// 已迁到 Svelte 的视图 → 它独有的一段文案。用来证明这条路由走的是新组件，
// 而不是悄悄退回 LegacyView（两者都会渲染出内容，只看长度分不出来）。
const MIGRATED = {
  facts: 'Discipline:',                            // Facts.svelte 独有的英文源文案
  channels: 'Build cadence in phases',             // Channels.svelte
  plan: 'Auto-verify',                             // Plan.svelte
  samples: 'reviewable and correctable',           // Samples.svelte
}

let failed = 0

const navCount = await page.locator('#side .navit').count()
// NAV 是 16 项：onboard 是接入引导页，不出现在导航里
console.log(`侧栏导航项: ${navCount}（应为 16）`)
if (navCount !== 16) failed++

for (const r of ROUTES) {
  await page.evaluate((name) => window.go(name), r)
  await page.waitForTimeout(250)
  const text = (await page.locator('#main').innerText()).trim()
  const marker = MIGRATED[r]
  const markerOk = !marker || text.includes(marker)
  const ok = text.length > 20 && markerOk
  if (!ok) failed++
  const mark = marker ? (markerOk ? '  [svelte]' : '  ← 没走新组件') : ''
  console.log(`${ok ? '  ok' : 'FAIL'}  ${r.padEnd(12)} ${String(text.length).padStart(6)} 字符${mark}`)
}

// 语言切换：写 localStorage 后重载，已迁移的视图应显示中文（字典命中）。
// 这条同时说明新组件的 t() 和旧看板的 ULANG 读的是同一个来源。
// 循环最后停在 onboard，reload 前先切回 facts（hash 会被 boot() 读出来）
await page.evaluate(() => { localStorage.setItem('ulang', 'zh'); window.go('facts') })
// 必须 reload：语言是在模块加载时读一次，而改 hash 不会触发页面重载
await page.reload({ waitUntil: 'networkidle' })
await page.waitForSelector('#side .navit')
const zhText = (await page.locator('#main').innerText()).trim()
const zhOk = zhText.includes('纪律：')
if (!zhOk) failed++
console.log(`${zhOk ? '  ok' : 'FAIL'}  中文回退      已迁移视图的文案走 zh 字典`)

await browser.close()

if (consoleErrors.length) {
  console.log(`\n控制台错误 ${consoleErrors.length} 条:`)
  for (const e of consoleErrors.slice(0, 10)) console.log('  ' + e)
}
console.log(`\n结果: ${ROUTES.length - failed}/${ROUTES.length} 路由渲染成功, 导航 ${navCount} 项, 控制台错误 ${consoleErrors.length}`)
process.exit(failed || consoleErrors.length ? 1 : 0)
