// 桥接期的重渲染信号。
//
// 旧代码把视图状态塞在模块级缓存里（SMP / AS / WB / KEYS / FACT_CARDS …），
// 它们不是响应式的：`loadSamples()` 改完 SMP 必须显式调 render() 才会重绘。
// 所以桥的 render() 不能是 no-op——它是这些缓存唯一的刷新入口。
//
// B3 把缓存逐个搬进各视图的 $state 后，这个文件会随之失去用途。
export const renderState = $state({ tick: 0 })

export function requestRender() {
  renderState.tick++
}
