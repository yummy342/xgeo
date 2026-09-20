<script>
  // 桥接期的视图宿主：把旧视图函数返回的 HTML 字符串塞进来。
  // 旧代码里 render() 是「整块 innerHTML 替换」，这里行为一致——迁移期
  // 这正是想要的：视图行为与旧看板逐像素相同，任何回归必然出在壳里。
  import { project } from '../lib/stores/project.svelte.js'
  import { ui } from '../lib/stores/ui.svelte.js'
  import { renderState } from '../lib/stores/render.svelte.js'
  import { route } from '../lib/router.svelte.js'

  let { name } = $props()

  let html = $state('')

  $effect(() => {
    // 显式读一遍建立依赖：旧视图函数读的是 window 上的全局，
    // Svelte 追踪不到那条路径，只能靠这里把 store 的读取挂上。
    void project.data; void project.slug; void route.name
    void ui.gapTab; void ui.engSel; void ui.wq; void ui.compTab
    void ui.qGroup; void ui.agrade; void ui.ablk; void ui.assetSel
    void ui.chanSel; void ui.vfMkt; void ui.wbFilter
    void ui.obStep; void ui.obSlug; void ui.obFail
    void renderState.tick   // 旧代码里的 render() 调用靠它把我们叫醒

    // 数据未就绪前不能调视图函数：它们直接读 D.analytics，D 还是 null 会炸。
    // 旧代码没这个问题——那时 render() 只在 load() 完成后被调用。
    if (!project.data) { html = ''; return }

    const fn = window.LEGACY_VIEWS?.[name]
    if (!fn) { html = ''; return }

    const out = fn()
    if (out instanceof Promise) {
      // 5 个视图是 async 的（在渲染路径里直接 fetch，B5 会重构掉）。
      // 这里必须防竞态：切换路由时旧请求返回不能覆盖新视图。
      let cancelled = false
      out.then((v) => { if (!cancelled) html = v })
      return () => { cancelled = true }
    }
    html = out
  })
</script>

{@html html}
