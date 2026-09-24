// 构建产物完整性。
//
// 产物是提交进仓库的（离线部署要求），而 dashboard.py 不再有回退分支——
// 产物不对就是页面打不开或跑的是旧代码。这里只做确定性检查，不看时间戳：
//   1. index.html 引用的 assets/ 文件必须存在
//   2. ui_dist 里不能有 index.html 没引用的残留 js/css（上一次构建的碎片）
//
// 用法：node frontend/scripts/dist-integrity.mjs [--strict]
import { readFileSync, readdirSync, existsSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const DIST = join(dirname(fileURLToPath(import.meta.url)), '..', '..', 'scripts', 'ui_dist')
const STRICT = process.argv.includes('--strict')

if (!existsSync(join(DIST, 'index.html'))) {
  console.log('✗ 没有构建产物 scripts/ui_dist/index.html —— 先跑 npm run build')
  process.exit(STRICT ? 1 : 0)
}

const html = readFileSync(join(DIST, 'index.html'), 'utf8')
const refs = [...html.matchAll(/(?:src|href)="\/?(assets\/[^"]+)"/g)].map((m) => m[1])
const problems = []

for (const r of refs) {
  if (!existsSync(join(DIST, r))) problems.push(`index.html 引用了不存在的 ${r}`)
}

const onDisk = readdirSync(join(DIST, 'assets')).filter((f) => /\.(js|css)$/.test(f))
const referenced = new Set(refs.map((r) => r.replace(/^assets\//, '')))
for (const f of onDisk) {
  if (!referenced.has(f)) problems.push(`残留产物 assets/${f}（index.html 没引用它，是上一次构建的碎片）`)
}

if (problems.length) {
  console.log(`✗ 构建产物有问题（${problems.length} 条）：`)
  for (const p of problems) console.log(`  - ${p}`)
} else {
  console.log(`✓ 构建产物完整（index.html 引用 ${refs.length} 个，assets/ 无残留）`)
}
if (STRICT && problems.length) process.exit(1)
