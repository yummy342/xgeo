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

### 两条容易踩的

- **`installBridge()` 必须在 `mount()` 之前**（见 `main.js`）。`LegacyView` 的
  `$effect` 在挂载瞬间就调用旧视图函数，那一刻全局 `D` 必须已经在。
- **`render()` 不能是 no-op**。旧代码把视图数据塞在模块级缓存里
  （`SMP`/`AS`/`WB`/`KEYS`/`FACT_CARDS`），它们不是响应式的，改完只能靠
  `render()` 刷新。所以桥把它接到 `stores/render.svelte.js` 的计数器上，
  `LegacyView` 依赖这个计数器重算。侧栏的 `renderSide()` 才是真 no-op。

## 尚未迁移的问题

- 5 个视图在渲染路径里直接 fetch（`vEngines` / `vPublishing` / `vSettings` /
  `vOnboard` / `vAssets`），其中 `vSettings` 还在渲染里有裸 `setTimeout`。
  B5 统一重构成 `$effect` + store。
- i18n 仍是旧的「渲染后 DOM 替换 + MutationObserver」机制，字典在
  `legacy-views.js` 里。新代码写英文源文案，但整体反向要等 B6。
- 移动端只做到「不再横向溢出」，响应式体系在 B1。
