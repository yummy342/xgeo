# GeoLook 前端

看板的 Svelte 重写。取代原来 `scripts/ui.html` 那个 3023 行单文件。

## 命令

```bash
npm install                                  # 只有开发者需要；部署直接消费已提交的构建产物
npm run dev                                  # vite 5173，/api 与 /files 代理到 8765
npm run build                                # 产物输出到 ../scripts/ui_dist/
node scripts/smoke.mjs                       # 17 路由冒烟（需先起服务）
python scripts/extract-legacy.py             # 重新生成 public/assets/legacy-views.js
```

起服务：

```bash
python scripts/geo.py ui --no-open --port 8765
```

构建产物 `scripts/ui_dist/` **提交进仓库**。这不是风格选择：`npm install` 需要联网，而
本项目要能离线/内网部署，全新克隆没法构建前端。所以 `npm install` 是开发者专属步骤，
部署只消费已提交的文件。

## 结构

17 个视图全部在 `src/views/` 下，`App.svelte` 的 `MIGRATED` 就是完整路由表——
没有 fallback 分支。仍然有一个普通脚本参与加载：

```
index.html
  ├─ <script src="/assets/legacy-views.js">   普通脚本，先执行（58KB）
  │    迁移收尾后剩下的旧辅助函数：纯工具、HTML 片段生成器、弹窗、任务动作。
  │    它们读裸全局名（D / SLUG / ST / RUNNING / KEYS / WB…），由桥注入。
  └─ <script type="module">
       main.js  → installBridge() 把 store 暴露成同名全局
                → mount(App)
       App.svelte → Sidebar + <当前视图> + Modal + Toast
```

`legacy-views.js` 由 `scripts/extract-legacy.py` 从 `scripts/ui.html` 按**保留名单**
生成（不是按行区间——行号会漂移，名单不会）。名单来源是对 `frontend/src` 里
`window.*` 调用的扫描：

```bash
grep -rhoE "window\.[a-zA-Z_][a-zA-Z0-9_]*" frontend/src | sort -u
```

脚本自带两道自检，改名单时会挡住错误：

- 名单里的名字必须在 `ui.html` 里存在（改名了要同步）
- **保留的函数不能引用被丢弃的符号**——这条是必须的：`editFactsSrc` 调的是裸名
  `saveFactsSrc` 而不是 `window.saveFactsSrc`，光靠扫描 `window.*` 定名单会漏掉它

### 还没做完的

- **弹窗仍在 legacy 里**（`factModal`、`pubModal`、`editKey`、`sampleModal`… 22 个）。
  它们读 `window.KEYS` / `PUB` / `SET_CFG` / `WB` / `FACT_CARDS`，所以组件取完数据
  要同步一份回 `window`。这是桥存在的唯一理由，把弹窗改成 Svelte 组件后就能拆。
- **样本复核链依赖旧缓存**：`sampleModal` 保存后靠 `SMP=null` + `loadSamples()` 刷新，
  后者末尾调 `render()` 正好 bump 组件依赖的 tick。Samples 组件只做了展示，
  复核弹窗没迁。
- **ja 字典未补**：`t()` 对 ja 回退到英文源文案。

### 四条容易踩的

- **`installBridge()` 必须在 `mount()` 之前**（见 `main.js`）。`LegacyView` 的
  `$effect` 在挂载瞬间就调用旧视图函数，那一刻全局 `D` 必须已经在。
- **`render()` 不能是 no-op**。旧代码把视图数据塞在模块级缓存里
  （`SMP`/`AS`/`WB`/`KEYS`/`FACT_CARDS`），它们不是响应式的，改完只能靠
  `render()` 刷新。所以桥把它接到 `stores/render.svelte.js` 的计数器上，
  `LegacyView` 依赖这个计数器重算。侧栏的 `renderSide()` 才是真 no-op。
- **动态组件要包 `{#key route.name}`**。不包的话切路由时 Svelte 复用同一个
  组件实例，新视图不渲染，页面停在上一页的内容上——而字符数看起来是正常的，
  只有断言独有文案才抓得到。
- **Svelte 模板里不要套 `esc()`**。旧代码在拼接字符串时手工转义，而 `{expr}`
  已经自动转义，再套一层会显示成 `&amp;lt;`。只有 `{@html}` 里需要手工 `esc`。

### i18n

新视图用英文源 + `t()` 查中文字典（`src/lib/i18n/`）。旧看板是反方向（中文源 +
渲染后 DOM 替换），两者能共存：MutationObserver 只做「中文 → 其他」，而新组件
的输出要么是英文（源文案），要么是中文（`locale=zh` 时，此时 observer 不动）。

两条纪律：

- **每个视图用到的文案必须和视图在同一次提交里补上 `zh.js` 条目**，否则中文
  用户会看到中英混杂。多数中文可以直接从旧视图函数里取——那里本来就是中文源。
- **同一个 key 不能有两个中文含义**。字典是全局的，撞了只会有一个生效（后写的
  覆盖先写的）。已经因此拆过两对：阵地的 `Owner`→`Who`，样本库的
  `Manual`→`Hand-collected`。

ja 字典待 B6 补齐，在那之前 `t()` 对 ja 回退到英文。

## 尚未迁移的问题

- 5 个视图在渲染路径里直接 fetch（`vEngines` / `vPublishing` / `vSettings` /
  `vOnboard` / `vAssets`），其中 `vSettings` 还在渲染里有裸 `setTimeout`。
  B5 统一重构成 `$effect` + store。
- i18n 仍是旧的「渲染后 DOM 替换 + MutationObserver」机制，字典在
  `legacy-views.js` 里。新代码写英文源文案，但整体反向要等 B6。
- 移动端只做到「不再横向溢出」，响应式体系在 B1。
