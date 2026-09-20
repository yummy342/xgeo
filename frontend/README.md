# GeoLook 前端

看板的 Svelte 实现。取代原来 `scripts/ui.html` 那个 3023 行单文件——那份连同迁移期的桥已经删掉了。

## 命令

```bash
npm install        # 只有开发者需要；部署直接消费已提交的构建产物
npm run dev        # vite 5173，/api 与 /files 代理到 8765
npm run build      # 产物输出到 ../scripts/ui_dist/
```

起服务与验证：

```bash
python scripts/geo.py ui --no-open --port 8765

node scripts/smoke.mjs            # 16 路由渲染 + 语言回退 + 控制台无错
node scripts/responsive.mjs       # 逐路由断言不横向溢出（GL_WIDTH 调宽度）
node scripts/dialog-smoke.mjs     # 样本复核弹窗：改→存→重开读回
node scripts/workbench-focus.mjs  # 编辑态：文本保留 + textarea 未被重建
```

前两个和最后两个都需要先起服务；它们用 `GL_URL` 覆盖地址，默认 `http://127.0.0.1:8799`。

构建产物 `scripts/ui_dist/` **提交进仓库**。这不是风格选择：`npm install` 需要联网，而本项目要能离线/内网部署，全新克隆没法构建前端。所以 `npm install` 是开发者专属步骤，部署只消费已提交的文件。

## 结构

```
src/
  main.js  App.svelte          壳：路由分发 + Sidebar + Modal + Toast
  app.css                      Nocturne 设计令牌 + 组件类 + 布局工具
  views/                       17 个视图，与路由表一一对应
  components/                  9 个共用组件 + 11 个弹窗
  lib/
    api.js                      api / post / request（统一错误 toast 与防重入）
    domain.js                   判据、排序、片段生成（diagTag/distRows/progBar/…）
    jobs.svelte.js              任务动作：runAction / watchJob / stopJob / setMonitor
    nav.js                      侧栏导航结构与角标
    onepager.js                 「给老板的一页结论」（往新窗口写独立 HTML）
    router.svelte.js            hash 路由 + popstate
    format.js  i18n/  stores/
```

`App.svelte` 的 `MIGRATED` 就是完整路由表，没有 fallback 分支。

### 四条容易踩的

- **动态组件要包 `{#key route.name}`**。不包的话切路由时 Svelte 复用同一个组件实例，
  新视图不渲染，页面停在上一页的内容上——而字符数看起来是正常的，只有断言独有文案才抓得到。
- **Svelte 模板里不要套 `esc()`**。`{expr}` 已经自动转义，再套一层会显示成 `&amp;lt;`。
  只有 `{@html}` 里需要手工 `esc`。
- **带 runes 的模块必须以 `.svelte.js` 结尾**。`lib/jobs.svelte.js` 用了 `$state`，
  叫 `jobs.js` 时构建通过、浏览器报 `$state is not defined`。
- **组件内的 grid 要自己给子项 `min-width: 0`**。`app.css` 里那条只匹配内联 grid；
  组件级 grid 里放一张 `min-width: 820px` 的表格，整列会被顶穿。

### 异步请求要防竞态

两处曾经因此写错文件：`Assets.open()` 与 `Workbench.loadFile()`。快速连点两个文件时，
先发的响应可能后到——头部显示 B、正文是 A，按保存就把 A 写进了 B。
两处都用请求序号丢弃过期响应（Workbench 还在预检那次二次往返后再查一次）。

### i18n

英文是源语言，直接写在代码里；中文走 `lib/i18n/zh.js` 的字典，查不到就原样返回英文
（刻意的降级，不是遗漏）。

两条纪律：

- **每个视图用到的文案必须和视图在同一次提交里补上 `zh.js` 条目**，否则中文用户会看到中英混杂。
- **同一个 key 不能有两个中文含义**。字典是全局的，撞了只会有一个生效（后写的覆盖先写的）。
  已经因此拆过两对：阵地的 `Owner`→`Who`，样本库的 `Manual`→`Hand-collected`。

**ja 字典未补**：`t()` 对 ja 回退到英文。

## 还没做完的

- **ja 字典**（见上）。
- **`lib/onepager.js` 与 `lib/domain.js` 里的一部分判据逻辑可以搬到后端**：
  `headline()` 是「健康分 → 结论文案」的决策树，`taskWbTarget()` 是从任务推断该写哪道题——
  它们是领域规则，放在后端更合适，前端只负责渲染。现在留在这里是因为后端还没有对应接口。
- **`window.KEYS` / `PROJECTS` / `SET_CFG` / `PUB` 的同步已全部删除**，但
  `/api/keys`、`/api/projects`、`/api/config`、`/api/publish` 仍被多个视图各取一份。
  真要做多客户产品时，这些该收进 store 统一管理。
