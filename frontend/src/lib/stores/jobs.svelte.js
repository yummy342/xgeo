// 取代 ui.html:177 的 RUNNING / LASTJOB / LOGOFF / POLL。
// 轮询逻辑本身仍在 legacy-views.js 的 pollJob 里（B5 连同 Settings 一起重写），
// 这里只提供它读写的四个全局。
export const jobs = $state({
  running: null,
  lastJob: null,
  offset: 0,
  poll: null,
})
