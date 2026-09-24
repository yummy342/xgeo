// 发布状态判据，四处共用（待发布清单 / 计划页 / 发布页 / 问题库）。
//
// 为什么要有这个文件：`publish.json` 里 ok:true 只说明「这次调用没报错」，
// 不说明「内容对外可见」。半自动渠道的记录也是 ok:true，但它的 state 是
// prepared（备好待人工粘贴）—— 拿 ok 当已发布，看板会说「已发布」而渠道上
// 什么都没有。这个坑踩过一次（三篇文章躺在 dev.to Drafts 里，界面显示已发布），
// 所以判据收在一处，四处都走它。
//
// state 取值：published（对外可见）/ prepared（备好待人工）/ draft（渠道里是草稿）/
//            ""（09-22 之前的旧记录，那时不分草稿与发布，按已发布处理，不制造假警报）

export const isPublished = (r) => ((r && r.state) || 'published') === 'published'
export const isPrepared = (r) => !!r && r.state === 'prepared'

export const hasPublished = (recs) => (recs || []).some(isPublished)
export const hasPrepared = (recs) => (recs || []).some(isPrepared)

// 一个文件聚合后的状态：发布过就算 published；只有备用记录才算 prepared；
// 只有草稿就是 draft；一条记录都没有是 none。
export const stateOf = (recs) => {
  const rs = recs || []
  if (!rs.length) return 'none'
  if (rs.some(isPublished)) return 'published'
  if (rs.some(isPrepared)) return 'prepared'
  return 'draft'
}
