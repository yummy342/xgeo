// Workbench 的编辑态保真检查。
//
// 旧实现把编辑内容挂在 textarea 上、靠 oninput 手工镜像回全局 WB.text，
// 每次 render() 都用字符串重建整个 textarea。文本能保住（WB.text 是同步的），
// 但**焦点和光标位置会丢**——元素被换掉了。
//
// 新实现用 bind:value，textarea 不重建。所以断言两件事：
//   1) 点「重新预检」后 textarea 仍是 document.activeElement
//   2) 输入的内容还在
//
// 用法：GL_URL=http://127.0.0.1:8799 node frontend/scripts/workbench-focus.mjs
const BASE = process.env.GL_URL || 'http://127.0.0.1:8799'

const { chromium } = await import('playwright')
const browser = await chromium.launch()
const page = await browser.newPage({ locale: 'en-US' })
const errors = []
page.on('pageerror', (e) => errors.push(e.message))

await page.goto(BASE, { waitUntil: 'networkidle' })
await page.waitForSelector('#side .navit')

await page.evaluate(() => window.go('workbench'))
await page.waitForTimeout(400)

// 选题列表 → 点第一行进编辑态
const first = page.locator('#wbpick > div').first()
if (!(await first.count())) {
  console.log('SKIP  选题池为空，无法测编辑态')
  await browser.close()
  process.exit(0)
}
await first.click()
await page.waitForTimeout(600)

const ta = page.locator('#wbtext')
if (!(await ta.count())) {
  console.log('FAIL  没进编辑态（找不到 #wbtext）')
  await browser.close()
  process.exit(1)
}

const MARK = ' focus-probe-文本 '
await ta.click()
await ta.type(MARK)
const typed = await ta.inputValue()

// 触发一次重渲染。旧实现里 render() 会整块重建视图（含 textarea）；
// 新实现走 Svelte 更新，textarea 元素本身不动。
// 直接调 window.render() 而不是点按钮，免去按钮文案的耦合。
await page.evaluate(() => window.render())
await page.waitForTimeout(600)

const state = await page.evaluate(() => {
  const el = document.getElementById('wbtext')
  return {
    exists: !!el,
    focused: document.activeElement === el,
    activeId: document.activeElement ? (document.activeElement.id || document.activeElement.tagName) : null,
    hasMark: el ? el.value.includes('focus-probe') : false,
  }
})

const textOk = state.hasMark
const focusOk = state.focused

console.log(`  文本保留    ${textOk ? 'ok' : 'FAIL'}   （输入了 ${typed.length} 字符）`)
console.log(`  焦点保持    ${focusOk ? 'ok' : 'FAIL'}   （预检后 activeElement = ${state.activeId}）`)

await browser.close()
console.log(`\n结果: 文本 ${textOk ? '保留' : '丢失'}, 焦点 ${focusOk ? '保持' : '丢失'}, 页面错误 ${errors.length}`)
process.exit(textOk && focusOk ? 0 : 1)
