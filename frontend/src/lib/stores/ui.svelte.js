// 取代旧代码 ui.html:178 的全局 ST，只保留真正跨视图的键。
//
// ST 原来有 18 个键，其中一多半是某一页自己的筛选态，放全局只是历史包袱。
// 全部已下沉到所属视图的 $state：gapTab（Gaps）、vfMkt（Verify）、qGroup（Questions）、
// ablk/agrade（SiteAudit）、compTab（Competitors）、wbFilter（Workbench）。
// 这里只剩真正跨视图的键。
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
