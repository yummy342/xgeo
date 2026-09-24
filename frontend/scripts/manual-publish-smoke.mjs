// 半自动发布的交互验证。
//
// 为什么单独一个脚本：这条链的正路（推送到 API 渠道）由 smoke/dialog-smoke 覆盖，
// 半自动是**另一条交互**（备好 → 复制 → 打开发布页 → 回填），共用不了一点：
// 它不进勾选、不进串行提交、不参与「立即发布」。
//
// 断言纪律（第一版踩过）：不许写 `A || true` 这种恒真句，也不许拿「弹窗里有 copy
// 字样」当「备好成功」——那个词在别处也有。每条都要能因为功能坏了而变红。
//
// 用法：先备 fixture（见下），再起服务，最后跑本脚本。
//   cd <repo>
//   mkdir -p work/zz-ui/content && cp work/<已有项目>/geo.json work/zz-ui/geo.json
//   # 把 work/zz-ui/geo.json 的 brand.name 改成 ZZ Manual E2E（换项目用得到）
//   printf '# T\n\n正文 %s\n' "$(seq 1 40 | tr '\n' ' ')" > work/zz-ui/content/a.md
//   python scripts/geo.py publish --slug zz-ui --platform sohu --path content/a.md
//   python scripts/geo.py ui --port 8799 --no-open &
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

// 切到测试项目；找不到就直接说清怎么建，别让它超时成一条看不出原因的失败
await page.click('#side button.pick')
await page.waitForSelector('.modal .brand-row', { timeout: 8000 })
const pick = page.locator(`.modal .brand-row:has-text("${BRAND}")`)
if (!(await pick.count())) {
  console.error(`\n找不到测试项目「${BRAND}」。建 fixture 的步骤见本文件头部注释。`)
  await browser.close()
  process.exit(1)
}
await pick.click()
await page.waitForTimeout(900)

// 进发布渠道页
await page.click('#side .navit:has-text("Publishing")')
await page.waitForTimeout(600)

const body = await page.innerText('body')
check('发布页有半自动分节', /semi-automatic/i.test(body))
check('半自动渠道标了「无自动通路」或「回退」', /no automatic path|fell back to semi/i.test(body))
// 发布页的渠道按市场分组、每行一个通路徽标（不是按通路分节 —— 那是发布弹窗里的）。
// 用精确文本比，`/automatic/i` 会把 "Semi-automatic" 也命中。
const chips = await page.locator('.tag.path').allInnerTexts()
check('渠道行标了通路（自动/半自动两种都有）',
  chips.some((x) => x.trim().toLowerCase() === 'automatic') && chips.some((x) => /semi/i.test(x)),
  `共 ${chips.length} 行`)
check('口径文案已改（不再写 "no official publishing API"）',
  !/no official publishing API/.test(body))
check('有回填入口（记录表那行的 Fill in）', /fill in/i.test(body))

// 备好待人工的记录：KPI 那栏必须单独算，不能混进 published
const kpi = await page.innerText('.pub-kpis')
check('KPI 把已备好单列', /prepared/i.test(kpi), kpi.replace(/\n/g, ' ').slice(0, 90))
// fixture 里只有一篇成稿、且它只有一条 prepared 记录 —— 所以已发布数必须是 0。
// 判据写成「等于 0」而不是「不含 prepared 字样」：后者写歪一点就变成恒真。
check('KPI 的已发布数不含已备好', /\b0 published\b/.test(kpi), kpi.replace(/\n/g, ' ').slice(0, 90))

// 走一遍真实路径：Pending → 发布弹窗 → 半自动渠道 → 备好并复制
await page.click('.pk.clickable')
await page.waitForSelector('.modal', { timeout: 5000 })
check('待发布清单里 prepared 提示「尚未发布」',
  /not published yet/i.test(await page.innerText('.modal')))
await page.click('.modal .btn.go')
await page.waitForTimeout(800)

const dlg = '.modal:has-text("Publish to channels")'
check('发布弹窗有半自动分节', /semi-automatic channels/i.test(await page.innerText(dlg)))
// 半自动渠道不能进勾选集合（进了就会被串行外发循环带走）
const semiRow = page.locator(`${dlg} .chan.semi`).first()
check('半自动渠道行没有勾选框', (await semiRow.locator('input.chk').count()) === 0)
const prep = page.locator(`${dlg} button:has-text("Prepare & copy")`).first()
check('半自动渠道有「备好并复制」按钮', (await prep.count()) > 0)

await prep.click()
const mDlg = '.modal:has-text("paste it in and publish")'
await page.waitForSelector(`${mDlg} button:has-text("Copy body")`, { timeout: 15000 })
const mb = await page.innerText(mDlg)
check('备好弹窗有复制正文按钮', /copy body/i.test(mb))
check('备好弹窗有打开发布页入口', /open publish page|open the channel backend/i.test(mb))
check('备好弹窗有回填输入框', /put the public link here/i.test(mb))
// 正文预览真的渲染了内容（不是只挂了个空 div）
const previewText = await page.locator(`${mDlg} .preview, ${mDlg} textarea.plain`).first().inputValue()
  .catch(async () => page.locator(`${mDlg} .preview, ${mDlg} textarea.plain`).first().innerText())
check('备好弹窗渲染出正文', (previewText || '').trim().length > 20,
  `(${(previewText || '').trim().length} 字)`)
check('预览里没有换行转义残留', !/\\n/.test(previewText || ''))

// 回填：这条链的最后一公里，之前一条断言都没覆盖
const urlIn = page.locator(`${mDlg} input.urlin`)
await urlIn.fill('https://example.test/published-1')
await page.click(`${mDlg} button:has-text("Recorded as published")`)
await page.waitForTimeout(1200)
const afterBody = await page.innerText('body')
check('回填后记录表出现该链接', /example\.test\/published-1/.test(afterBody))
check('回填后 KPI 的已备好数归零或下降', !/· 1 prepared/i.test(await page.innerText('.pub-kpis')))

check('没有页面级 JS 报错', errors.length === 0, errors.slice(0, 2).join(' | '))

await browser.close()
console.log(failed ? `\n${failed} 项失败` : '\n全部通过')
process.exit(failed ? 1 : 0)
