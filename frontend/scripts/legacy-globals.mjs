// 迁移期那座桥把 store 挂成旧代码读的裸全局（window.WB / window.PUB / window.KEYS…）。
// 桥已拆除，写入点也该一起没了——留着就是「等 X 迁走再删」这类没人兑现的承诺，
// 而且写进 window 的东西永远不参与 Svelte 的响应式，是两套状态。
//
// 用法：node frontend/scripts/legacy-globals.mjs [--strict]
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, dirname, relative } from 'node:path'
import { fileURLToPath } from 'node:url'

const SRC = join(dirname(fileURLToPath(import.meta.url)), '..', 'src')
const STRICT = process.argv.includes('--strict')

function walk(dir, out = []) {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name)
    if (statSync(p).isDirectory()) walk(p, out)
    else if (/\.(svelte|js)$/.test(p)) out.push(p)
  }
  return out
}

// 只看「写」：window.X = … / window['X'] = …
// 读、window.open、window.addEventListener、window.location 都不算
const WRITE = /window(?:\.([A-Z][A-Z0-9_]*)|\[['"]([A-Z][A-Z0-9_]*)['"]\])\s*=[^=]/g

const hits = []
for (const file of walk(SRC)) {
  const src = readFileSync(file, 'utf8')
  src.split('\n').forEach((line, i) => {
    const stripped = line.replace(/\/\/.*$/, '')
    for (const m of stripped.matchAll(WRITE)) {
      hits.push({ file: relative(SRC, file).replace(/\\/g, '/'), line: i + 1, name: m[1] || m[2] })
    }
  })
}

if (hits.length) {
  console.log(`✗ 还有 ${hits.length} 处往 window 上挂全局状态：`)
  for (const h of hits) console.log(`  ${h.file}:${h.line}  window.${h.name}`)
  console.log('  桥已拆除，这些写入点没有读者了——删掉，或改成 store / props。')
} else {
  console.log('✓ src/ 里没有 window 全局写入')
}
if (STRICT && hits.length) process.exit(1)
