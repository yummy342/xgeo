// 窄屏溢出检查：375px 下逐路由断言没有横向滚动。
// 旧看板有 15 处写死的内联 grid-template-columns，只有 .kpis 和 .wb3 背后
// 有媒体查询，其余在窄屏完全不塌——这个脚本就是用来量化那件事的。
const BASE = process.env.GL_URL || 'http://127.0.0.1:8799'
const WIDTH = Number(process.env.GL_WIDTH || 375)

const ROUTES = [
  'overview', 'engines', 'competitors', 'questions', 'samples',
  'siteaudit', 'gaps', 'channels', 'facts',
  'plan', 'workbench', 'assets',
  'verify', 'report',
  'settings', 'publishing', 'onboard',
]

const { chromium } = await import('playwright')
const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: WIDTH, height: 900 } })

await page.goto(BASE, { waitUntil: 'networkidle' })
await page.waitForSelector('#side .navit', { timeout: 10000 })

let bad = 0
for (const r of ROUTES) {
  await page.evaluate((name) => window.go(name), r)
  await page.waitForTimeout(250)
  const m = await page.evaluate(() => ({
    scroll: document.documentElement.scrollWidth,
    client: document.documentElement.clientWidth,
    // 找出真正撑宽页面的元素，便于定位
    worst: (() => {
      let el = null, w = 0
      for (const n of document.querySelectorAll('#main *')) {
        const r = n.getBoundingClientRect()
        if (r.right > w) { w = r.right; el = n }
      }
      return el ? `${el.tagName.toLowerCase()}.${(el.className || '').toString().split(' ')[0]}` : ''
    })(),
  }))
  const over = m.scroll - m.client
  const ok = over <= 1
  if (!ok) bad++
  console.log(`${ok ? '  ok' : 'FAIL'}  ${r.padEnd(12)} 溢出 ${String(over).padStart(4)}px  ${ok ? '' : '← ' + m.worst}`)
}

await browser.close()
console.log(`\n${WIDTH}px 下: ${ROUTES.length - bad}/${ROUTES.length} 路由无横向溢出`)
process.exit(bad ? 1 : 0)
