import { toast } from './stores/toast.svelte.js'

// 非 2xx 也尽量读 body：服务端错误响应带具体原因（如「缺凭证：GITHUB_TOKEN」），
// 只报 HTTP 状态码会把可行动的信息丢掉
export const api = async (u, o) => {
  try {
    const r = await fetch(u, o)
    const j = await r.json().catch(() => null)
    if (!r.ok) return (j && j.error) ? j : { error: `HTTP ${r.status}` }
    return j ?? { error: '响应不是 JSON' }
  } catch (e) {
    return { error: '连接失败：服务未响应' }
  }
}

export const post = (u, b) => api(u, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(b),
})

export class ApiError extends Error {}

// 旧代码有 53 处 `if(!r.ok){toast(r.error,'err');...}`，绝大多数只是为了决定
// 要不要继续。request() 把「报错 + 中断」合成一步，调用点只看成功路径。
export async function request(url, opts) {
  const r = await api(url, opts)
  if (r && r.error) {
    toast.error(r.error)
    throw new ApiError(r.error)
  }
  return r
}

export const requestPost = (url, body) => request(url, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
})

// 用了异常，就得有人接住：ApiError 已经在 request() 里弹过 toast，
// 这里吞掉避免控制台刷未处理拒绝；其它异常照常抛出。
if (typeof window !== 'undefined') {
  window.addEventListener('unhandledrejection', (e) => {
    if (e.reason instanceof ApiError) e.preventDefault()
  })
}
