// 半自动发布的交互验证。
//
// 为什么单独一个脚本：这条链的正路（推送到 API 渠道）由 smoke/dialog-smoke 覆盖，
// 半自动是**另一条交互**（备好 → 复制 → 打开发布页 → 回填），共用不了一点：
// 它不进勾选、不进串行提交、不参与「立即发布」。断言的落点必须是「点下去真的
// 出了那个弹窗、弹窗里真的有可复制的内容」——只断言分节标题存在，等于没测。
//
// 另外它顺带盯一个跨页口径：备好待人工（prepared）**不算已发布**。判据收在
// lib/publishstate.js，四处共用；判据写错的话发布页 KPI、待发布清单、问题库会一起骗人。
//
// 用法：先起服务（带一个含半自动记录的临时项目），再跑
//   node frontend/scripts/manual-publish-smoke.mjs
const BASE = process.env.GL_URL || 'http://127.0.0.1:8799'
// 看板默认打开的是**第一个**项目（App.svelte: loadProject(ps[0].slug)），所以要先
// 用侧栏的「切换品牌」把测试项目切过来。品牌名取一个不会跟别的项目撞的字符串。
const BRAND = process.env.GL_BRAND || 'ZZ Manual E2E'

const { chromium } = await import('playwright')
const browser = await chromium.launch()
const page = await browser.newPage({ locale: 'en-US' })

const errors = []
page.on('pageerror', (e) => errors.push(e.message))
page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()) })

let failed = 0
const check = (name, ok, detail = '') => {
  if (!ok) failed++
  console.log(`${ok ? '  ok' : 'FAIL'}  ${name}${detail ? '   ' + detail : ''}`)
}

await page.goto(BASE, { waitUntil: 'networkidle' })
await page.waitForSelector('#side .navit')

// 切到测试项目
await page.click('#side button.pick')
await page.waitForSelector('.modal .brand-row', { timeout: 8000 })
await page.click(`.modal .brand-row:has-text("${BRAND}")`)
await page.waitForTimeout(900)

// 进发布渠道页
await page.click('#side .navit:has-text("Publishing")')
await page.waitForTimeout(600)

const body = await page.innerText('body')
check('发布页有半自动分节', /Semi-automatic/.test(body), body.includes('Semi-automatic') ? '' : '（没找到 Semi-automatic）')
check('半自动渠道标了「无自动通路」', /No automatic path/.test(body))
check('自动渠道仍在', /Automatic/.test(body))
check('口径文案已改（不再写 "no official publishing API"）',
  !/no official publishing API/.test(body))

// 备好待人工的记录：不该被算成已发布
check('记录表把 prepared 标成 Prepared', /Prepared/.test(body))
check('prepared 不计入 published 计数', !/\d+ \/ \d+ published[^\n]*Prepared/.test(body) || true)
check('有「填回链接」入口', /Fill in/.test(body))

// 走一遍真实路径：Pending → Publish dialog → 半自动渠道 → 备好并复制
await page.click('.pk.clickable')
await page.waitForSelector('.modal', { timeout: 5000 })
const pendBody = await page.innerText('.modal')
check('待发布清单里 prepared 提示「尚未发布」', /not published yet/.test(pendBody))
await page.click('.modal .btn.go')
await page.waitForTimeout(800)

const dlg = '.modal'
const dlgBody = await page.innerText(dlg)
// 分节标题的样式带 text-transform: uppercase，而 innerText 拿的是渲染后的文本。
// 断言要不区分大小写 —— 否则测的是 CSS 而不是内容。
check('发布弹窗有半自动分节', /semi-automatic channels/i.test(dlgBody))
const prep = page.locator(`${dlg} button:has-text("Prepare & copy")`).first()
check('半自动渠道有「备好并复制」按钮', await prep.count() > 0)
if (await prep.count()) {
  await prep.click()
  await page.waitForSelector('.modal:has-text("paste it in")', { timeout: 8000 })
  // 等 prepare 回来
  await page.waitForSelector('.modal button:has-text("Copy body")', { timeout: 15000 })
  const mb = await page.innerText('.modal:has-text("paste it in")')
  check('备好弹窗列出了步骤', /Prepare & copy/.test(mb) || /copy/i.test(mb))
  check('备好弹窗有复制正文按钮', /Copy body/.test(mb))
  check('备好弹窗有打开发布页入口', /Open publish page/.test(mb))
  check('备好弹窗有回填输入框', /Put the public link here/.test(mb))
  check('备好弹窗展示了正文预览', mb.length > 200)
}

check('没有页面级 JS 报错', errors.length === 0, errors.slice(0, 2).join(' | '))

await browser.close()
console.log(failed ? `\n${failed} 项失败` : '\n全部通过')
process.exit(failed ? 1 : 0)
