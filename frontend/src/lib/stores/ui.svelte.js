// 取代旧代码 ui.html:178 的全局 ST，只保留真正跨视图的键。
//
// ST 原来有 18 个键，其中一多半是某一页自己的筛选态，放全局只是历史包袱。
// 已下沉到所属视图 $state 并从这里删除的：
//   gapTab（Gaps）、vfMkt（Verify）、qGroup（Questions）
//
// 尚未迁移的视图（SiteAudit / Competitors / Workbench）仍在读写 ST.ablk /
// ST.agrade / ST.compTab / ST.wbFilter。那些键已不在这里声明——$state 代理
// 支持新增属性，legacy 代码首次写入时会自己创建，行为与旧看板一致。
// 等这三个视图迁移时，它们改成组件内 $state，这些键自然消失。
export const ui = $state({
  // 跳转传参：go(name, { engSel }) / go('workbench', { wq }) / { chanSel } / { assetSel }
  engSel: null,
  wq: null,
  chanSel: null,
  assetSel: null,
  // gapTab 只在「引擎表现 → 发现说错了 → 记一条事实偏差」这一处跨视图传参
  // （ui.html:1271）。它不是页内筛选态——页内那个 tab 在 Gaps 组件自己的 $state 里。
  gapTab: null,
  // 接入引导的跨步骤状态
  obStep: 1,
  obSlug: null,
  obNoSample: false,
  obFail: false,
  obUrl: '',
  obName: '',
  obMkt: 'both',
})
