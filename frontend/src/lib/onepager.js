// 「给老板的一页结论」——不是什么弹窗，而是往新窗口写一份独立的、可打印的 HTML。
// 所以它待在 lib 里而不是 components 里：没有 Svelte 参与，纯粹是文本产出。
//
// 原实现见 ui.html:2278 onePager，读全局 D 并调 headline()。
import { project } from './stores/project.svelte.js'
import { toast } from './stores/toast.svelte.js'
import { headline } from './domain.js'
import { esc, pct } from './format.js'
import { t } from './i18n/index.svelte.js'

export function onePager() {
  const d = project.data
  if (!d) return
  const a = d.analytics || {}
  const h = a.health || { subs: {} }

  const w = window.open('', '_blank')
  if (!w) { toast(t('The browser blocked the popup — allow it and try again'), 'err'); return }

  const subs = [
    [t('Mention rate'), h.subs?.mention],
    [t('Cite share'), h.subs?.cite],
    [t('Coverage'), h.subs?.channel],
    [t('Content readiness'), h.subs?.content],
    [t('Fact consistency'), h.subs?.fact],
  ]
  const openP0 = (d.tasks || []).filter((x) => x.status !== 'done' && x.priority === 'P0')
  const brand = d.brand?.name || ''
  const conclusion = headline()[1]

  w.document.write(`<!doctype html><meta charset="utf-8"><title>${esc(brand)} · ${t('GEO one-pager')}</title>
  <style>body{font:15px/1.7 Inter,system-ui,sans-serif;max-width:720px;margin:40px auto;padding:0 24px;color:#111}
  h1{font-size:24px}h2{font-size:16px;margin-top:28px}table{border-collapse:collapse;width:100%}
  td,th{border-bottom:1px solid #ddd;padding:8px;text-align:left;font-size:14px}
  .big{font-size:44px;font-weight:600}.muted{color:#777;font-size:12.5px}</style>
  <h1>${esc(brand)} · ${t('GEO one-pager')}</h1>
  <div class="muted">${t('Data as of')} ${esc(a.latest_date || '—')} · ${t('every number comes from the same question-bank sampling run')}</div>
  <div class="big">${h.score == null ? '—' : h.score}<span style="font-size:16px;color:#777"> / 100 ${t('GEO health score')}</span></div>
  <h2>${t('The five components')}</h2><table>${subs.map(([n, v]) =>
    `<tr><td>${esc(n)}</td><td>${v == null ? t('Not measured') : pct(v)}</td></tr>`).join('')}</table>
  <h2>${t('This round\'s conclusion')}</h2><p>${esc(conclusion)}</p>
  <h2>${t('Next step (P0)')}</h2><ul>${openP0.map((x) =>
    `<li>${esc(x.title)} — ${esc(x.owner)}，${esc(x.effort)}</li>`).join('') || `<li>${t('No P0 blockers')}</li>`}</ul>
  <p class="muted">${t('GEO raises the probability of being cited; it does not promise any engine will cite a given page.')}</p>`)
  w.document.close()
}
