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
const page = await browser.newPage()

const consoleErrors = []
page.on('console', (m) => { if (m.type() === 'error') consoleErrors.push(m.text()) })
page.on('pageerror', (e) => consoleErrors.push('pageerror: ' + e.message))

await page.goto(BASE, { waitUntil: 'networkidle' })
// 等 boot() 跑完：侧栏出现说明 installBridge 和数据都就绪了
await page.waitForSelector('#side .navit', { timeout: 10000 })

let failed = 0

const navCount = await page.locator('#side .navit').count()
// NAV 是 16 项：onboard 是接入引导页，不出现在导航里
console.log(`侧栏导航项: ${navCount}（应为 16）`)
if (navCount !== 16) failed++

for (const r of ROUTES) {
  await page.evaluate((name) => window.go(name), r)
  await page.waitForTimeout(250)
  const text = (await page.locator('#main').innerText()).trim()
  const ok = text.length > 20
  if (!ok) failed++
  console.log(`${ok ? '  ok' : 'FAIL'}  ${r.padEnd(12)} ${String(text.length).padStart(6)} 字符`)
}

await browser.close()

if (consoleErrors.length) {
  console.log(`\n控制台错误 ${consoleErrors.length} 条:`)
  for (const e of consoleErrors.slice(0, 10)) console.log('  ' + e)
}
console.log(`\n结果: ${ROUTES.length - failed}/${ROUTES.length} 路由渲染成功, 导航 ${navCount} 项, 控制台错误 ${consoleErrors.length}`)
process.exit(failed || consoleErrors.length ? 1 : 0)
