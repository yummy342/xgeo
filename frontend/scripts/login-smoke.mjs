// 账号登录的端到端验证：一个真浏览器，填 FreeModel API Key，进得去，退得出来。
//
// 与另外几个 e2e 不同，这个脚本自带一个**假的 fm-auth**（真服务在线上，
// 单测和 e2e 都不该依赖外网），所以它必须占一个固定端口：服务端要配
// XGEO_AUTH_BASE 指向它。用法（两步）：
//
//   XGEO_ACCOUNTS='e2e@example.com:*' \
//   XGEO_AUTH_BASE=http://127.0.0.1:18871/api/auth \
//     python scripts/geo.py ui --port 8801 --no-open
//
//   GL_URL=http://127.0.0.1:8801 node frontend/scripts/login-smoke.mjs
//
// 断言纪律（上一轮栽过）：不许写恒真的断言，也不许只验「页面渲染出来了」——
// 真正要证的是「凭据换到了会话、会话能进、登出之后进不去」，所以每条都拿
// 服务端的响应状态或下一次访问的结果说话。
import http from 'node:http'

const BASE = process.env.GL_URL || 'http://127.0.0.1:8801'
const AUTH_PORT = Number(process.env.GL_AUTH_PORT || 18871)
const EMAIL = process.env.GL_E2E_EMAIL || 'e2e@example.com'
const KEY = process.env.GL_E2E_KEY || 'sk-fm-e2e-key'

let failed = 0
const check = (name, ok, extra = '') => {
  console.log(`${ok ? '✓' : '✗'} ${name}${extra ? ' — ' + extra : ''}`)
  if (!ok) failed++
}

/* ── 假 fm-auth：只认一个 key，返回线上的响应形状（公开的 console/js/auth.js
      就是这么调的：`data.code === 200 && data.data.api_key`） ── */
const seen = []
const auth = http.createServer((req, res) => {
  const token = new URL(req.url, 'http://x').searchParams.get('token')
  seen.push(token)
  const ok = token === KEY
  const body = JSON.stringify(ok
    ? { code: 200, data: { email: EMAIL, api_key: 'sk-fm-rotated' } }
    : { code: 400, msg: 'Invalid token' })
  res.writeHead(ok ? 200 : 401, { 'Content-Type': 'application/json' })
  res.end(body)
})
await new Promise((r) => auth.listen(AUTH_PORT, '127.0.0.1', r))

const { chromium } = await import('playwright')
const browser = await chromium.launch()
const page = await browser.newPage({ locale: 'en-US' })

// 401 的导航是这条流程的正常组成（登录页本身就是 401 响应、登出后刷新也是），
// 浏览器会把它记成 console error —— 那不是页面出错，所以按响应码过滤掉。
// 真正要看的是 pageerror：Svelte 在没有会话时启动不该抛。
const consoleErrors = []
const pageErrors = []
page.on('console', (m) => {
  if (m.type() !== 'error') return
  if (/Failed to load resource.*40[13]/.test(m.text())) return
  consoleErrors.push(m.text())
})
page.on('pageerror', (e) => pageErrors.push(e.message))

try {
  /* ── 1) 没凭据时看到的是登录页，不是看板 ── */
  const first = await page.goto(BASE, { waitUntil: 'domcontentloaded' })
  check('未登录返回 401', first.status() === 401, 'HTTP ' + first.status())
  await page.waitForSelector('#k', { timeout: 10000 })
  check('登录页给了 API Key 输入框', await page.locator('#go').count() === 1)
  check('老令牌那条路还在界面上', await page.locator('details').count() > 0)

  /* ── 2) 错的 key：留在登录页，并说出原因 ── */
  await page.fill('#k', 'sk-fm-wrong')
  await page.click('#go')
  await page.waitForFunction(() => document.getElementById('e').textContent.trim() !== '',
                             null, { timeout: 10000 })
  const err = (await page.textContent('#e')).trim()
  check('错 key 有明确回话', /无效|Invalid/.test(err), err)
  check('错 key 不给会话', page.url().startsWith(BASE) && await page.locator('#k').count() === 1)

  /* ── 3) 对的 key：进看板，侧栏出现邮箱 ── */
  await page.fill('#k', KEY)
  await page.click('#go')
  await page.waitForSelector('#side .navit', { timeout: 15000 })
  check('凭据真的传给了认证服务', seen.includes(KEY))
  const mail = await page.textContent('#side .who .mail')
  check('侧栏显示登录邮箱', mail.trim() === EMAIL, mail.trim())
  check('侧栏有登出', await page.locator('#side .who .out').count() === 1)

  /* ── 4) 登出：立刻回到登录页，且旧 cookie 不再被认 ── */
  await page.click('#side .who .out')
  await page.waitForSelector('#k', { timeout: 15000 })
  check('登出后回到登录页', true)
  const back = await page.goto(BASE)
  check('登出后看板不再放行', back.status() === 401, 'HTTP ' + back.status())

  check('无未捕获的页面异常', pageErrors.length === 0, pageErrors.slice(0, 2).join(' | '))
  check('无其它 console 报错', consoleErrors.length === 0, consoleErrors.slice(0, 2).join(' | '))
} finally {
  await browser.close()
  auth.close()
}

console.log(failed ? `\n${failed} 项失败` : '\n全部通过')
process.exit(failed ? 1 : 0)
