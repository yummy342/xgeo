// 取代旧代码 ui.html:178 的全局 ST。
// 注意：ST 实际有 18 个键在用，这里沿用了完整的 10 个声明键 + 8 个视图里
// 动态创建的键（ablk/agrade/assetSel/chanSel/compTab/qGroup/vfMkt/wbFilter）。
// B3 会把后 8 个收进各自视图的局部状态——它们是每视图筛选态，放全局只是历史包袱。
export const ui = $state({
  // 跨视图
  gapTab: 'content',
  engSel: null,
  wq: null,
  obStep: 1,
  obSlug: null,
  obNoSample: false,
  obFail: false,
  obUrl: '',
  obName: '',
  obMkt: 'both',
  // 每视图筛选态（待 B3 下沉）
  ablk: null,
  agrade: null,
  assetSel: null,
  chanSel: null,
  compTab: null,
  qGroup: null,
  vfMkt: null,
  wbFilter: null,
})
