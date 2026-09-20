// i18n 缺口扫描：代码里 t('...') 用到的键，字典里没有的就回退成英文。
// 用法：node frontend/scripts/i18n-audit.mjs [--strict]
//   --strict：有缺口就 exit 1（给 npm test 用）
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

const dictSrc = readFileSync(join(SRC, 'lib/i18n/zh.js'), 'utf8')
// 键可能是 'x':、"x": 或 x: —— 含撇号的键（"This round's conclusion"）会写成双引号
const dict = new Set()
for (const m of dictSrc.matchAll(/^\s*(['"])((?:(?!\1)[^\\]|\\.)+)\1\s*:/gm)) {
  dict.add(m[2].replace(/\\(['"])/g, '$1'))
}
for (const m of dictSrc.matchAll(/^\s*([A-Za-z_$][\w$]*)\s*:/gm)) dict.add(m[1])

// t('...') / t("...")，只取单行字面量
const CALL = /\bt\(\s*(['"])((?:(?!\1)[^\\]|\\.)*)\1/g
const missing = new Map()
const keys = new Set()
for (const file of walk(SRC)) {
  if (file.endsWith('zh.js')) continue
  const src = readFileSync(file, 'utf8')
  for (const m of src.matchAll(CALL)) {
    const key = m[2].replace(/\\(['"])/g, '$1')
    keys.add(key)
    if (!dict.has(key)) {
      if (!missing.has(key)) missing.set(key, [])
      missing.get(key).push(relative(SRC, file).replace(/\\/g, '/'))
    }
  }
}

console.log(`i18n 键 ${keys.size} 个，字典 ${dict.size} 条，缺 ${missing.size} 条`)
for (const [key, files] of [...missing].sort()) {
  console.log(`  ✗ ${JSON.stringify(key)}  ← ${files[0]}${files.length > 1 ? ` 等 ${files.length} 处` : ''}`)
}
if (!missing.size) console.log('  ✓ 没有缺口')
if (STRICT && missing.size) process.exit(1)
