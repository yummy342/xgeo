// 弹窗的交互验证。
//
// smoke.mjs 只断言页面渲染出内容，所以它漏掉过一件事：样本复核弹窗依赖的
// 全局刷新链被删掉后，页面看起来完全正常，但点开样本、保存，是一点反应都没有。
// 这个脚本存在的理由就是那类 bug——它真的点、真的改、真的存。
//
// 用法：先起服务，再跑
//   node frontend/scripts/dialog-smoke.mjs
const BASE = process.env.GL_URL || 'http://127.0.0.1:8799'

const { chromium } = await import('playwright')
const browser = await chromium.launch()
const page = await browser.newPage({ locale: 'en-US' })

const errors = []
page.on('pageerror', (e) => errors.push(e.message))
page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()) })

await page.goto(BASE, { waitUntil: 'networkidle' })
await page.waitForSelector('#side .navit')

let failed = 0
const check = (name, ok, detail = '') => {
  if (!ok) failed++
  console.log(`${ok ? '  ok' : 'FAIL'}  ${name}${detail ? '   ' + detail : ''}`)
}

// ---- 样本复核弹窗 ----
await page.click('#side .navit[data-route="samples"]')
await page.waitForTimeout(600)

const viewBtn = page.locator('#main button', { hasText: /^View$/ }).first()
if (!(await viewBtn.count())) {
  console.log('SKIP  样本库为空，跳过复核弹窗验证')
} else {
  await viewBtn.click()
  await page.waitForTimeout(700)

  const dialog = page.locator('.modal .box')
  check('弹窗打开', await dialog.count() > 0)

  // 表单字段存在且有初值
  const note = dialog.locator('input.input').last()
  const hasNote = await note.count() > 0
  check('复核表单可编辑', hasNote)

  if (hasNote) {
    const MARK = `smoke-${Date.now()}`
    await note.fill(MARK)
    // 保存：按钮文案是 Save，位置在右下
    await dialog.locator('button', { hasText: /^Save$/ }).first().click()
    await page.waitForTimeout(1200)

    check('保存后弹窗关闭', await page.locator('.modal .box').count() === 0)

    // 重开同一条样本，备注应当已经落库
    await viewBtn.click()
    await page.waitForTimeout(700)
    const reopened = page.locator('.modal .box input.input').last()
    const val = await reopened.inputValue()
    check('备注已持久化', val === MARK, val === MARK ? '' : `读回 "${val}"`)

    // 还原：清空备注，避免污染数据
    await reopened.fill('')
    await page.locator('.modal .box button', { hasText: /^Save$/ }).first().click()
    await page.waitForTimeout(1000)
  }
}

await browser.close()

if (errors.length) {
  console.log(`\n控制台错误 ${errors.length} 条:`)
  for (const e of errors.slice(0, 8)) console.log('  ' + e)
}
console.log(`\n结果: 弹窗交互 ${failed ? '有失败' : '全部通过'}, 页面错误 ${errors.length}`)
process.exit(failed || errors.length ? 1 : 0)
