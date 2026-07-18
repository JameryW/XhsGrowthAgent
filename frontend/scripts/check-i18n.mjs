// INF-09: i18n key consistency check. Ensures en.json and zh-CN.json share the
// same key set (a value diff is fine; missing keys are not). Run via
// `node scripts/check-i18n.mjs`. Exits non-zero on drift so it can gate CI.
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

const __dirname = dirname(fileURLToPath(import.meta.url))
const en = JSON.parse(readFileSync(resolve(__dirname, '../src/locales/en.json'), 'utf8'))
const zh = JSON.parse(readFileSync(resolve(__dirname, '../src/locales/zh-CN.json'), 'utf8'))

function flatKeys(obj, prefix = '', out = new Set()) {
  for (const [k, v] of Object.entries(obj)) {
    const key = prefix ? `${prefix}.${k}` : k
    if (v && typeof v === 'object' && !Array.isArray(v)) flatKeys(v, key, out)
    else out.add(key)
  }
  return out
}

const enKeys = flatKeys(en)
const zhKeys = flatKeys(zh)

const missingInZh = [...enKeys].filter((k) => !zhKeys.has(k))
const missingInEn = [...zhKeys].filter((k) => !enKeys.has(k))

if (!missingInZh.length && !missingInEn.length) {
  console.log(`i18n keys consistent (${enKeys.size} keys)`)
  process.exit(0)
}

if (missingInZh.length) {
  console.error(`Missing in zh-CN (${missingInZh.length}):`)
  missingInZh.slice(0, 30).forEach((k) => console.error(`  - ${k}`))
}
if (missingInEn.length) {
  console.error(`Missing in en (${missingInEn.length}):`)
  missingInEn.slice(0, 30).forEach((k) => console.error(`  - ${k}`))
}
process.exit(1)
