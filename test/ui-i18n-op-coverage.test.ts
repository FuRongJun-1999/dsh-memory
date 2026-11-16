/**
 * 守卫 · 翻译覆盖度（issue #970）：cg 的 39 个 op 必须有英文条目。
 *
 * 语言键可继续加，但**每个语言都不得缺 op**——缺译会静默回退中文，
 * 那样「英文界面」就会中英混杂，属于「看起来做了、其实没做」。
 */
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const app = readFileSync(new URL('../ui/minimal/payload/web/app.js', import.meta.url), 'utf8')

// cg 的 39 个 op（真源：md_cg 的 cg 工具 op 枚举）
const CG_OPS = ('route read write verify review protect identity consistency metacognition self_state ' +
  'evolution sustain scrub predict causal forget goal task recent state_view state_event info ' +
  'index_code index_doc ref whitebox theory link session ingest export maintain consolidate ' +
  'insight ccg status edges audit help').split(' ')

test('C1 cg 39 个 op 一个不缺（缺译会静默回退中文）', () => {
  const missing = CG_OPS.filter(op => !new RegExp('\\n        ' + op + ':\\s*\'').test(app))
  assert.deepEqual(missing, [], '缺少英译的 op：' + missing.join(', '))
  assert.equal(CG_OPS.length, 39, 'op 清单本身应为 39 个')
})
