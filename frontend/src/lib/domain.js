// 领域函数：判据、排序、片段生成。原来住在 legacy 的全局作用域里读 window.D，
// 搬到这里之后读 project store——组件在模板或 $derived 里调用它们时，
// 对 store 的读取会正常建立响应式依赖。
//
// 其中三个返回 HTML 字符串（diagTag / distRows / progBar），调用方用 {@html} 渲染。
// 它们内部对数据做了 esc()（数据来自服务端），文案部分走 t()。
import { t } from './i18n/index.svelte.js'
import { esc, pct } from './format.js'
import { project } from './stores/project.svelte.js'

const analytics = () => project.data?.analytics || {}
const expand = () => project.data?.expand || null

/** 诊断标签。数据为空时给一个破折号占位。 */
export function diagTag(d) {
  if (!d) return '<span style="font-size:12px;color:var(--t600)">—</span>'
  const cls = d.sev === 'P0' ? 'tag-accent' : d.sev === 'P1' ? 'pill-warn' : d.sev === 'P2' ? 'tag-dim' : 'pill-good'
  return `<span class="tag ${cls}" title="${esc(d.detail)}" style="cursor:help">${esc(d.type)}</span>`
}

/** 品牌提及分布条。me = 自己的品牌名，命中时高亮并加星。 */
export function distRows(list, me) {
  const max = ((list || [])[0] || {}).rate || 1
  return (list || []).map((x) => {
    const mine = x.name === me
    return `<div class="row" style="gap:8px;padding:4px 0">
      <span style="width:132px;flex:none;font-size:12.5px;${mine ? 'color:var(--a300)' : ''};overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${esc(x.name)}">${esc(x.name)}${mine ? ' ⭑' : ''}</span>
      <div class="bar" style="flex:1;height:6px"><div style="height:100%;width:${Math.max(3, Math.round(x.rate / max * 100))}%;background:${mine ? 'var(--a400)' : '#595d6c'};border-radius:4px"></div></div>
      <span style="width:86px;flex:none;text-align:right;font-size:11.5px;color:var(--t400)">${pct(x.rate)} · ${x.hits} ${t('hits')}</span></div>`
  }).join('') || `<div class="muted" style="font-size:12px">${t('No entity was mentioned this round')}</div>`
}

/**
 * 任务级 before/after 进度条：首测(f) → 当前(p) → 目标。
 * 完成度算法按方向分两种：lte 看「从基线降到目标走了多远」，gte 看距目标的比例。
 */
export function progBar(p, f) {
  if (!p) return ''
  const fmt = (v) => v == null ? '—' : (p.pct ? pct(v) : v)
  const op = p.op === 'lte' ? '≤' : '≥'
  let ratio
  if (p.op === 'lte') {
    const b = (f && f.cur != null ? f.cur : null) ?? p.base ?? Math.max(p.cur, p.target, 1)
    ratio = b > p.target ? (b - p.cur) / (b - p.target) : (p.cur <= p.target ? 1 : 0)
  } else {
    ratio = p.target ? p.cur / p.target : 0
  }
  ratio = Math.max(0, Math.min(1, ratio))
  return `<div style="margin-top:5px;max-width:280px">
    <div style="font-size:11px;color:var(--t500)">${esc(p.label)}${t(': first')} ${fmt(f && f.cur)} → ${t('now')} <b style="color:var(--t300)">${fmt(p.cur)}</b> · ${t('target')} ${op}${fmt(p.target)}</div>
    <div class="bar" style="margin-top:3px;height:5px"><div style="height:100%;width:${Math.round(ratio * 100)}%;background:${ratio >= 1 ? 'var(--a400)' : 'var(--accent)'};border-radius:4px"></div></div></div>`
}

/** 某个问题的拓词需求标记。没有拓词数据时返回空串。 */
export function demandTag(qid) {
  const d = expand()?.q_demand?.[qid]
  if (!d) return ''
  const tip = t('Matched {n} autocomplete terms: {list}')
    .replace('{n}', String(d.n)).replace('{list}', (d.terms || []).join(' / '))
  return ` <span class="tag ${d.new ? 'tag-accent' : 'tag-dim'}" style="font-size:10px" title="${esc(tip)}">🔥 ${d.new ? t('Rising demand') : t('Has search demand')}</span>`
}

export function demandRank(qid) {
  const d = expand()?.q_demand?.[qid]
  return d ? (d.new ? 2 : 1) : 0
}

/** 选题排序：需求上升的排前面，品牌点名题沉底，其余保持原序。 */
export function demandSort(qs) {
  if (!expand()) return qs
  const idx = new Map(qs.map((q, i) => [q.id, i]))
  return qs.slice().sort((a, b) => {
    if ((a.brand_probe ? 1 : 0) !== (b.brand_probe ? 1 : 0)) return a.brand_probe ? 1 : -1
    const d = demandRank(b.id) - demandRank(a.id)
    return d || idx.get(a.id) - idx.get(b.id)
  })
}

/** 总览首屏的结论标题与解释，按健康分走三条分支。 */
export function headline() {
  const a = analytics()
  const h = a.health || { subs: {} }
  const tr = a.trend || []
  if (h.score == null) {
    return [t('No sampling data yet'), t('Run one round from Settings → Run tasks to start diagnosing.')]
  }
  const prev = tr.length > 1 ? tr[tr.length - 2] : null
  const dm = prev && prev.mention != null && tr[tr.length - 1].mention != null
    ? ((tr[tr.length - 1].mention - prev.mention) * 100).toFixed(1) : null
  const cite = h.subs?.cite
  const m = h.subs?.mention

  if ((m || 0) === 0) {
    return [t('AI has never mentioned you unprompted'),
      t('Across {n} samples this round, unprompted mention rate is 0 — you are not ranked low, you are simply not in the candidate set. Fix content gaps and P0 channels first, not more channels.')
        .replace('{n}', String(tr.length ? tr[tr.length - 1].samples : 0))]
  }
  if ((cite || 0) < 0.05) {
    return [t('AI mentions you now, but barely cites you'),
      t('Mention rate {m}{delta}, but cite share only {c} — people hear about you, yet there is nothing of yours to cite. Ship extractable content first.')
        .replace('{m}', pct(m))
        .replace('{delta}', dm ? t(' (from {d}pp last round)').replace('{d}', (+dm > 0 ? '+' : '') + dm) : '')
        .replace('{c}', pct(cite))]
  }
  return [t('Mentions and citations are rising together'),
    t('Mention {m}, citation {c}. Keep the content cadence and start expanding channels.')
      .replace('{m}', pct(m)).replace('{c}', pct(cite))]
}

/** 某阵地承接哪些问题：按 fits 声明的问题组 + 市场匹配过滤。 */
export function chanFitQs(c) {
  return (analytics().questions || []).filter((q) => !q.brand_probe
    && (c.fits || []).includes(q.group)
    && (q.market === 'both' || q.market === c.market))
}

/** 某个问题是否已经铺到某个阵地。 */
export function distOf(qid, chid) {
  return !!(((project.data?.distribution || {})[qid] || {})[chid])
}

/** 片段类型 → 最该写它的那些问题组（对应 blueprint 的 GROUP_PLAN） */
const BLOCK_GROUP = {
  '对比': ['比较', '替代'],
  '操作步骤': ['场景'],
  '定义': ['价格', '风险', '品牌验证'],
  '数字事实': ['推荐', '比较', '场景'],
  'FAQ': ['价格', '风险'],
}

/**
 * 行动计划 → 内容工作台的落点解析：尽量落到「这条任务最该写的那道题」，
 * 而不是列表页。三级降级：任务资产里带的 qid → 片段类型对应的组 →
 * 英文类任务找海外题 → 选题池顶部。
 *
 * 返回 qid，调用方自己决定怎么跳（导航不属于领域层）。
 */
export function taskWbTarget(task) {
  for (const a of (task.assets || [])) {
    const m = String(a).match(/\bq\d{3}\b/)
    if (m) return m[0]
  }
  const qs = demandSort((analytics().questions || []).filter((q) => !q.brand_probe))
  const undone = qs.filter((q) => q.content !== '已成稿')

  const bm = (task.title || '').match(/「(定义|数字事实|对比|操作步骤|FAQ)」/)
  if (bm) {
    const hit = undone.find((q) => (BLOCK_GROUP[bm[1]] || []).includes(q.group))
    if (hit) return hit.id
  }
  if (/英文|中英/.test(task.title || '')) {
    const hit = undone.find((q) => q.market === 'global')
    if (hit) return hit.id
  }
  return (undone[0] || qs[0] || {}).id || null
}
