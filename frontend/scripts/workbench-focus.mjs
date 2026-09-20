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

await page.click('#side .navit[data-route="workbench"]')
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

// 给当前这个 textarea 节点打个标记。这一步是断言的核心：旧实现每次重渲染
// 都用字符串重建整个 textarea，节点会被换掉、标记随之消失；新实现只更新状态，
// 节点还是同一个。
await page.evaluate(() => { document.getElementById('wbtext').dataset.probe = 'kept' })

// 走真实路径触发重渲染：点「Re-check」会发请求并刷新预检面板。
const recheck = page.locator('.editor-bar button', { hasText: /Re-check|重新预检/ }).first()
await recheck.click()
await page.waitForTimeout(1200)

const state = await page.evaluate(() => {
  const el = document.getElementById('wbtext')
  return {
    sameNode: el ? el.dataset.probe === 'kept' : false,
    hasMark: el ? el.value.includes('focus-probe') : false,
    // 光标位置也一并看看：节点被换掉的话它会回到 0
    caret: el ? el.selectionStart : -1,
  }
})

const textOk = state.hasMark
const nodeOk = state.sameNode

console.log(`  文本保留    ${textOk ? 'ok' : 'FAIL'}   （输入了 ${typed.length} 字符）`)
console.log(`  节点未重建  ${nodeOk ? 'ok' : 'FAIL'}   （预检后光标在 ${state.caret}，输入长度 ${typed.length}）`)

await browser.close()
console.log(`\n结果: 文本 ${textOk ? '保留' : '丢失'}, textarea ${nodeOk ? '未被重建' : '被重建了'}, 页面错误 ${errors.length}`)
process.exit(textOk && nodeOk ? 0 : 1)
