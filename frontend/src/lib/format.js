// 从 ui.html:145-152 逐字移植。Svelte 模板会自动转义，所以 esc 只有
// 迁移期的 legacy 桥还在用；新写的视图不该再调它。
export const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]))

// NaN 也要落回「—」：`v == null` 只挡 null/undefined，而 `(NaN*100).toFixed()` 是 "NaN%"
export const pct = (v) => (v == null || Number.isNaN(v)) ? '—'
  : (v * 100).toFixed(v > 0 && v < 0.095 ? 1 : 0) + '%'

export const mktLabel = (m) => m === 'cn' ? '国内' : m === 'global' ? '海外' : '通用'
