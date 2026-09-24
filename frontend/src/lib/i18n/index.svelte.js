import { zh } from './zh.js'

// 新视图的 i18n：英文是源语言，直接写在代码里；中文走字典。
//
// 这与旧看板的机制方向相反（旧的是中文源 + 渲染后 DOM 替换），但两者能共存：
// MutationObserver 只做「中文 → 其他」，而这里的输出要么是英文（源），
// 要么是中文（locale=zh 时的字典值，此时 observer 不翻译）。
// 所以迁移期不会互相踩。
//
// B6 废弃旧机制时，ja 字典在这一并补齐；在那之前 ja 回退到英文源文案。
function detect() {
  try {
    const s = localStorage.getItem('ulang')
    if (s === 'zh' || s === 'en' || s === 'ja') return s
  } catch {
    /* 隐私模式下 localStorage 会抛 */
  }
  const n = (navigator.language || '').toLowerCase()
  return n.startsWith('zh') ? 'zh' : n.startsWith('ja') ? 'ja' : 'en'
}

export const i18n = $state({ locale: detect() })

const dicts = { zh }

/** 查不到就原样返回英文源文案——这是刻意的降级，不是遗漏。 */
export function t(s) {
  return dicts[i18n.locale]?.[s] ?? s
}

/** 供外部（含迁移期的旧 setLang）同步语言状态。 */
export function setLocale(l) {
  i18n.locale = l
  try { localStorage.setItem('ulang', l) } catch { /* 忽略 */ }
}
