# XGEO 前端

看板的 Svelte 实现。取代原来 `scripts/ui.html` 那个 3023 行单文件——那份连同迁移期的桥已经删掉了。

## 命令

```bash
npm install        # 只有开发者需要；部署直接消费已提交的构建产物
npm run dev        # vite 5173，/api 与 /files 代理到 8765
npm run build      # 产物输出到 ../scripts/ui_dist/
npm test           # 静态断言，不需要起服务
```

`npm test` 串起三条 grep 级断言，缺一条就红：

```
scripts/i18n-audit.mjs       t('...') 用到的键 vs zh.js 字典，缺条目 = 回退成英文
scripts/legacy-globals.mjs   src/ 里不许再出现 window.<大写> = …（迁移期的桥已拆）
scripts/dist-integrity.mjs   index.html 引用的产物必须存在，assets/ 不许有构建碎片
```

真浏览器的四条要另外跑，先起服务：

```bash
python scripts/geo.py ui --no-open --port 8799
npm run test:e2e

node scripts/smoke.mjs            # 16 路由 + 深链的 onboard + 语言回退 + 控制台无错
node scripts/responsive.mjs       # 逐路由断言不横向溢出（GL_WIDTH 调宽度）
node scripts/dialog-smoke.mjs     # 样本复核弹窗：改→存→列表计数 +1→重开读回
node scripts/workbench-focus.mjs  # 编辑态：文本保留 + textarea 未重建 + 预检真重算
```

四条都用 `GL_URL` 覆盖地址，默认 `http://127.0.0.1:8799`。它们的判据都按
「把目标 bug 重新引入，这条会不会红」验过一遍——只断言「页面有内容」的检查
挡不住迁移期那类「视图没重渲染、悄悄退回旧组件」的故障。

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

四处曾经因此读到错的、或写错文件。快速连点两个文件/切两次项目时，先发的响应可能后到：

| 位置 | 后果 |
|---|---|
| `Assets.open()` / `Workbench.loadFile()` | 头部显示 B、正文是 A，按保存就把 A 写进了 B |
| `loadProject()`（`stores/project.svelte.js`） | 切项目时把新项目的数据覆盖成旧项目的 |
| `Workbench.loadQuestion()` | qid 是 B，sources 却是 A 的文件 |

都用请求序号丢弃过期响应。`loadFile` 还有第二次往返（预检），回来时要再查一次序号。
新增异步取数时照这个模式写，别省。

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
