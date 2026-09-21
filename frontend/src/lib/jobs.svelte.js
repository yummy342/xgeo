// 任务动作：启动、轮询、停止、看日志。取代 legacy 的 runAction / pollJob /
// stopJob / showLog / setMonitor。
//
// 旧版把日志直接往 #joblog 的 textContent 上追加，所以「无限增长」是免费的。
// 这里日志是响应式状态，每次追加都会重渲染——必须给缓冲设上限。
// 上限是安全的，因为轮询游标（offset）单独存在一个普通变量里，不从字符串派生。
import { api, post } from './api.js'
import { toast } from './stores/toast.svelte.js'
import { jobs } from './stores/jobs.svelte.js'
import { project } from './stores/project.svelte.js'
import { t } from './i18n/index.svelte.js'

const LOG_CAP = 512 * 1024

export const jobLog = $state({ text: '', status: '', label: '' })

function appendLog(chunk) {
  let next = jobLog.text + chunk
  if (next.length > LOG_CAP) next = next.slice(-LOG_CAP)
  jobLog.text = next
}

export function statusLabel(status) {
  return {
    running: t('running'), done: t('finished'), failed: t('failed'),
    stopped: t('stopped'), interrupted: t('interrupted'),
  }[status] || status || ''
}

/** 接回一个已经在跑的任务（刷新后用）：日志从头拉一遍，然后继续轮询。 */
export async function resumeJob(jobId) {
  // 已经接过、或已经处理过这个任务，就直接返回。任务结束时 watchJob 会把
  // jobs.running 置回 null，而 App 的 $effect 依赖它 —— 少了这道闸就会无限
  // 重跑（每轮一个请求 + 一条 toast，日志缓冲被反复清空）。
  // 用 lastJob 而不是「曾经接过」的标记：那种标记只写不复位，切到别的项目
  // 再切回来时会把「A 的任务还在跑」挡在门外 —— 界面显示空闲，实际在跑。
  if (!jobId || jobs.running === jobId || jobs.lastJob === jobId) return
  jobs.offset = 0
  jobLog.text = ''
  jobs.lastJob = jobId
  jobs.running = jobId
  await watchJob(jobId)
}

/** 启动一个后台任务。返回 job 对象，失败返回 null。 */
export async function runAction(action, params) {
  const slug = project.data?.slug
  if (!slug) { toast(t('No project loaded'), 'err'); return null }
  const r = await post('/api/run', { slug, action, params: params || {} })
  if (!r.ok) { toast(r.error || t('Could not start'), 'err'); return null }

  jobs.running = r.job.id
  jobs.lastJob = r.job.id
  jobs.offset = 0
  jobLog.text = ''
  jobLog.status = 'running'   // 上一轮的状态留着的话，新任务一进来就被当成已结束
  jobLog.label = r.job.label || action
  toast(t('Started: {label}').replace('{label}', r.job.label || action))
  watchJob(r.job.id)
  return r.job
}

/** 按字节偏移轮询日志。自递归 setTimeout —— 每跳都等上一次响应，不会重入。 */
export async function watchJob(jobId) {
  clearTimeout(jobs.poll)
  if (!jobId) return
  jobs.running = jobId

  const r = await api(`/api/job/${jobId}?offset=${jobs.offset}`)
  if (r.error) {
    jobs.running = null
    toast(t('Lost track of the job'), 'err')
    return
  }

  jobs.offset = r.offset
  if (r.log) appendLog(r.log)
  jobLog.status = r.job.status
  jobLog.label = r.job.label || jobLog.label

  if (r.job.status === 'running') {
    jobs.poll = setTimeout(() => watchJob(jobId), 900)
    return
  }

  jobs.running = null
  toast(`${r.job.label} ${r.job.status === 'done' ? t('finished') : t('ended')}`,
    r.job.status === 'done' ? '' : 'err')
}

/** 一次性把某个任务的完整日志拉回来（切回设置页时回填）。 */
export async function loadJobLog(jobId) {
  if (!jobId) return
  const r = await api(`/api/job/${jobId}?offset=0`)
  if (r.error) return
  jobLog.text = (r.log || '').slice(-LOG_CAP)
  jobLog.status = r.job.status
  jobLog.label = r.job.label || ''
}

export async function stopJob() {
  if (!jobs.running) return
  await post(`/api/job/${jobs.running}/stop`, {})
  toast(t('Stop signal sent'))
}

export function stopPolling() {
  clearTimeout(jobs.poll)
}

/** 周期复跑：days=0 关闭。 */
export async function setMonitor(days) {
  const slug = project.data?.slug
  if (!slug) return false
  const next = days ? new Date(Date.now() + days * 864e5).toISOString().slice(0, 10) : null
  const r = await post('/api/config/' + slug, {
    monitor: days ? { every_days: days, next_run: next } : {},
  })
  if (!r.ok) { toast(t('Failed: {e}').replace('{e}', r.error || ''), 'err'); return false }
  toast(days
    ? t('On: a full cycle every {d} days, first at {n}').replace('{d}', String(days)).replace('{n}', next)
    : t('Recurring run turned off'))
  return true
}
