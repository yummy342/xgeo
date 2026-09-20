import { project, actions, loadProject } from './stores/project.svelte.js'
import { ui } from './stores/ui.svelte.js'
import { jobs } from './stores/jobs.svelte.js'
import { openModal, closeModal } from './stores/modal.svelte.js'
import { toast } from './stores/toast.svelte.js'
import { requestRender } from './stores/render.svelte.js'
import { route, go } from './router.svelte.js'

// 迁移期的桥。legacy-views.js 是从 ui.html 抽出的旧视图，全是普通全局函数，
// 它们读 D/SLUG/ST/R 这些裸全局名。这里用 getter 把 store 暴露成同名全局，
// 于是旧视图不改一行就能在新壳里跑。
//
// 用 getter 而不是快照：旧代码里有 `ST.gapTab = x` 这类直接改写，
// 必须是同一个对象才能改到 store 上。
//
// 退出条件：B6 删掉本文件与 legacy-views.js。如果 B2-B3 走完桥没有变小，
// 说明迁移没在推进，该停下来重新评估。

function def(name, get, set) {
  Object.defineProperty(window, name, { get, set, configurable: true })
}

export function installBridge() {
  def('D', () => project.data)
  def('SLUG', () => project.slug)
  def('ST', () => ui)
  def('R', () => route.name)
  def('ACTIONS', () => actions.map)
  def('EXPD', () => project.data?.expand ?? null,
    (v) => { if (project.data) project.data.expand = v })
  def('RUNNING', () => jobs.running, (v) => { jobs.running = v })
  def('LASTJOB', () => jobs.lastJob, (v) => { jobs.lastJob = v })
  def('LOGOFF', () => jobs.offset, (v) => { jobs.offset = v })
  def('POLL', () => jobs.poll, (v) => { jobs.poll = v })

  Object.assign(window, {
    // 旧签名是 toast(msg, kind)，kind 为 'err' 时是错误条
    toast: (m, k = '') => (k === 'err' ? toast.error(m) : toast(m)),
    modal: openModal,
    closeModal,
    go,
    load: (slug, keep) => loadProject(slug, keep),
    // render() 必须真触发重渲染：旧代码的模块级缓存（SMP/AS/WB/KEYS）不是
    // 响应式的，改完只能靠它刷新。renderSide() 才是 no-op——侧栏由 Svelte 渲染。
    render: requestRender,
    renderSide: () => {},
  })
}
