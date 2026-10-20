import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'

// issue #590 守卫：自动记忆钩子写入的 condition_space.time_window 必须为 **unix 秒**。
// 病象（修前）：除以 3600000 得到小时索引（如 497905）⇒ stg(op=timeline) 显示 1970 年、排序落到末尾。
test('#590 打点：time_window 用秒，不得用小时索引', () => {
  const src = readFileSync(join(process.cwd(), 'src', 'hooks.ts'), 'utf8')
  assert.ok(!/Date\.now\(\)\s*\/\s*3600000/.test(src),
    'hooks.ts 不得再用 /3600000（小时索引）——那是 1970 年的来源')
  assert.ok(/Date\.now\(\)\s*\/\s*1000/.test(src),
    'hooks.ts 必须用 /1000（unix 秒），与 nodefile.FULL_TIME_WINDOW_MAX 的秒级口径一致')
  const line = src.split('\n').find((l) => l.includes('time_window:')) ?? ''
  assert.ok(/\(seconds\):/, 'time_window 行应当使用 seconds 变量（实际: ' + line.trim() + '）')
})