// 弹窗的交互验证。
//
// smoke.mjs 只断言页面渲染出内容，所以它漏掉过一件事：样本复核弹窗依赖的
// 全局刷新链被删掉后，页面看起来完全正常，但点开样本、保存，是一点反应都没有。
//
// 这个脚本存在的理由就是那类 bug，所以断言必须落在**列表本身变了**上——
// 只断言「重开弹窗能读回备注」是没用的：备注是从服务端按 key 取的，列表刷不刷新
// 都读得回来（实测：把 onchanged 整个置空，那种断言照样通过）。
// 真正会红的判据是顶部「N reviewed by hand」计数跟着涨了。
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
const bail = (msg) => {
  console.log(`FAIL  ${msg}`)
  process.exitCode = 1
}

const countText = () => page.locator('#main .count').innerText()
const editedOf = (s) => {
  const m = s.match(/(\d+)\s+reviewed by hand/)
  return m ? Number(m[1]) : 0
}

// ---- 样本复核弹窗 ----
await page.click('#side .navit[data-route="samples"]')
await page.waitForTimeout(600)

const rows = page.locator('#main table tbody tr')
const n = await rows.count()
if (!n) {
  // 以前这里是「SKIP 然后 exit 0」——测试静默消失，等于没有这条防线
  await browser.close()
  bail('样本库为空：复核往返无从验证。先跑一期采样（设置 → 运行任务 → AI 答案采样）再跑本脚本。')
  process.exit(1)
}

// 挑一条还没人工复核过的：复核过的再存一次不会让计数变化，断言就没鉴别力
let target = -1
for (let i = 0; i < n; i++) {
  if (!/\bManual\b/.test(await rows.nth(i).innerText())) { target = i; break }
}
if (target < 0) {
  await browser.close()
  bail(`${n} 条样本都已人工复核过，本脚本需要至少一条未复核的样本来验「保存后列表会变」。`)
  process.exit(1)
}

const before = editedOf(await countText())
await rows.nth(target).locator('button', { hasText: /^View$/ }).first().click()
await page.waitForTimeout(700)

const dialog = page.locator('.modal .box')
check('弹窗打开', await dialog.count() > 0)

const note = dialog.locator('input.input').last()
const hasNote = await note.count() > 0
check('复核表单可编辑', hasNote)

if (hasNote) {
  const MARK = `smoke-${Date.now()}`
  await note.fill(MARK)
  await dialog.locator('button', { hasText: /^Save$/ }).first().click()
  await page.waitForTimeout(1200)

  check('保存后弹窗关闭', await page.locator('.modal .box').count() === 0)

  // 核心断言：列表被重新取数了，计数跟着涨。刷新链断了这条必红。
  const after = editedOf(await countText())
  check('保存后列表计数 +1', after === before + 1, `${before} → ${after}`)

  // 重开同一条样本，备注应当已经落库
  await rows.nth(target).locator('button', { hasText: /^View$/ }).first().click()
  await page.waitForTimeout(700)
  const reopened = page.locator('.modal .box input.input').last()
  const val = await reopened.inputValue()
  check('备注已持久化', val === MARK, val === MARK ? '' : `读回 "${val}"`)

  // 还原：清空备注。manual_override 清不掉（任何一次保存都会打上），
  // 所以计数会停在这一格——这是数据侧的既成事实，不是断言失败。
  await reopened.fill('')
  await page.locator('.modal .box button', { hasText: /^Save$/ }).first().click()
  await page.waitForTimeout(1000)
}

await browser.close()

if (errors.length) {
  console.log(`\n控制台错误 ${errors.length} 条:`)
  for (const e of errors.slice(0, 8)) console.log('  ' + e)
}
console.log(`\n结果: 弹窗交互 ${failed ? '有失败' : '全部通过'}, 页面错误 ${errors.length}`)
process.exit(failed || errors.length ? 1 : 0)
