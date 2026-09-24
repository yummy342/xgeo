// 渲染外链前的唯一守卫。
//
// 为什么要有这个文件：发布记录里的 url 有两个来路 —— 渠道响应直接落库的
// （webhook 端点可以回 `javascript:...`），以及人工回填的（用户输入）。
// 绑到 href 上点一下就执行。之前 Publishing.svelte 与 ManualPublishDialog
// 各写了一份同样的判据，PendingDialog 那份漏了 —— 收在一处，新加渲染点也就不容易漏。
//
// 只放行 http(s)：`javascript:`、`data:`、协议相对地址（`//evil`）一律当纯文本显示。
export const safeUrl = (u) => (/^https?:\/\//i.test(u || '') ? u : '')
