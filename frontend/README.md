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

## 迁移期结构

现在有两套东西同时在跑，边界是**「legacy 字符串函数 vs Svelte 组件」，不是「旧文件 vs 新文件」**：

```
index.html
  ├─ <script src="/assets/legacy-views.js">   普通脚本，先执行
  │    从 ui.html 抽出的 17 个旧视图。返回 HTML 字符串。
  │    读一堆裸全局名（D / SLUG / ST / R / RUNNING / EXPD）。
  └─ <script type="module">                   Vite 打包的新壳
       main.js  → installBridge() 把 store 暴露成同名全局（用 getter，
                  旧代码里 `ST.gapTab = x` 这类直接改写要能写回 store）
                → mount(App)
       App.svelte → Sidebar（Svelte）+ LegacyView（{@html} 塞旧视图输出）
                    + Modal + Toast
```

于是旧视图一行不改就能在新壳里跑，每批替换几个，未替换的行为与旧看板完全一致。
任何回归必然出在壳里（约 200 行）。

`lib/legacy.js` 的 `installBridge()` 是唯一的临时代码。如果逐视图迁移推进到一半
而它没有变小，说明迁移没在动，该停下来重新评估。

### 已迁到 Svelte 的视图

在 `App.svelte` 的 `MIGRATED` 里登记，登记了就绕开 `LegacyView` 走新组件。
`scripts/smoke.mjs` 里的 `MIGRATED` 映射会给每条已迁路由断言一段独有文案——
两个实现都会渲染出内容，只看长度分不出有没有真的走新组件。

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
