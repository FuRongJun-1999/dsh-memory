/**
 * issue762-surrogate-truncation.test.ts · 截断不得劈开代理对（issue #762）
 *
 * 病象：注入文本按 UTF-16 码元 `slice`，预算落点若压在 emoji 两个码元之间，
 * 截断结果就是**孤立高位代理** `\uD83D`；宿主 `JSON.stringify` 写成 `"\ud83d"`
 * ——合法 JSON 文本、非法 Unicode 码元——严格校验的服务端把**整条请求**拒掉
 * （400 INVALID_REQUEST、0 token）。注入文本每轮重拼、每轮写进对话历史 ⇒
 * 一次劈开就让该会话**永久**不可用（历史只增不改）。
 *
 * 覆盖：
 *   ① 复现：原生 `slice` 确实劈开代理对（bug 存在性证据）
 *   ② truncateSafe：任意预算不劈对、输出是原文前缀、不超预算、预算落在 emoji 中间时退回完整码点
 *   ③ stripLoneSurrogates：孤立高位/低位丢弃、合法对保留、幂等
 *   ④ 注入块出口（renderUntrustedMemoryBlock）：孤代理清除、合法 emoji 保留、边界完整
 *   ⑤ 端到端：身份锚点块 / 最近记忆块在**预算边界**处不劈对
 *   ⑥ JSON 面：注入块经 JSON.stringify 后代理转义成对出现
 */
import { test } from 'node:test'
import assert from 'node:assert/strict'
import {
  renderUntrustedMemoryBlock,
  stripLoneSurrogates,
  truncateSafe,
} from '../src/lib/prompt_safety.ts'
import { formatTimelineDecayed, renderIdentityAnchors } from '../src/hooks.ts'

/** 扫孤立代理：高位后必须紧跟低位；低位前必须是高位。 */
function hasLoneSurrogate(s: string): boolean {
  for (let i = 0; i < s.length; i++) {
    const c = s.charCodeAt(i)
    if (c >= 0xd800 && c <= 0xdbff) {
      const n = i + 1 < s.length ? s.charCodeAt(i + 1) : 0
      if (!(n >= 0xdc00 && n <= 0xdfff)) return true
      i++
    } else if (c >= 0xdc00 && c <= 0xdfff) {
      return true
    }
  }
  return false
}

test('#762 复现：原生 slice 会劈开代理对（守卫生效的前提）', () => {
  const half = '😊'.slice(0, 1)
  assert.equal(half.length, 1)
  assert.equal(hasLoneSurrogate(half), true)
  assert.equal(JSON.stringify({ t: half }), '{"t":"\\ud83d"}')
})

test('#762 truncateSafe：任何预算都不劈对、是原文前缀、不超预算', () => {
  const text = 'x😊y😊z'
  for (let n = 0; n <= text.length + 2; n++) {
    const cut = truncateSafe(text, n)
    assert.equal(hasLoneSurrogate(cut), false, `max=${n} 劈开了代理对: ${JSON.stringify(cut)}`)
    assert.ok(cut.length <= n, `max=${n} 超预算: ${cut.length}`)
    assert.equal(text.startsWith(cut), true, `max=${n} 不是前缀`)
  }
})

test('#762 truncateSafe：预算落在 emoji 中间时退回上一个完整码点', () => {
  assert.equal('a😊'.slice(0, 2), 'a\uD83D')   // 修前形态（孤立高位）
  assert.equal(truncateSafe('a😊', 2), 'a')
  assert.equal(truncateSafe('a😊', 3), 'a😊')
  assert.equal(truncateSafe('😊', 1), '')
  assert.equal(truncateSafe('😊', 2), '😊')
  assert.equal(truncateSafe('', 0), '')
})

test('#762 stripLoneSurrogates：孤立代理丢弃、合法对保留、幂等', () => {
  assert.equal(stripLoneSurrogates('a\uD83Db'), 'ab')
  assert.equal(stripLoneSurrogates('a\uDE0Ab'), 'ab')
  assert.equal(stripLoneSurrogates('a😊b'), 'a😊b')
  const once = stripLoneSurrogates('x\uD83D😊\uDE0Ay')
  assert.equal(once, 'x😊y')
  assert.equal(stripLoneSurrogates(once), once)
})

test('#762 注入块出口：孤代理清除、合法 emoji 保留、边界完整', () => {
  const block = renderUntrustedMemoryBlock('正文😊\uD83D尾巴')
  assert.equal(hasLoneSurrogate(block), false)
  assert.ok(block.includes('<untrusted-memory>'))
  assert.ok(block.includes('</untrusted-memory>'))
  assert.ok(block.includes('😊'))   // 合法 emoji 原样保留
})

test('#762 端到端：身份锚点条目在预算边界处不劈对', () => {
  // IDENTITY_ITEM_CHARS = 160；把 emoji 放在第 159–160 个码元
  const preview = 'a'.repeat(159) + '😊' + 'b'.repeat(5)
  const out = renderIdentityAnchors({ items: [{ layer: 'self', preview }] })
  assert.equal(hasLoneSurrogate(out), false, JSON.stringify(out.slice(-8)))
  assert.ok(out.startsWith('  - [self] '))
})

test('#762 端到端：最近记忆块（formatTimelineDecayed）不劈对', () => {
  // 首层 budget = RECALL_BASE_CHARS = 160
  const preview = 'a'.repeat(159) + '😊' + 'b'.repeat(5)
  const out = formatTimelineDecayed({ items: [{ layer: 'contextual', preview }] })
  assert.equal(hasLoneSurrogate(out), false)
})

test('#762 JSON 面：注入块经 JSON.stringify 后代理转义成对', () => {
  const block = renderUntrustedMemoryBlock('a😊b\uD83Dc')
  const json = JSON.stringify({ text: block })
  const escapes = json.match(/\\u[dD][89aAbB][0-9a-fA-F]{2}/g) ?? []
  // 合法 emoji 会写成一对（\ud83d\ude0a）；落单高位只会写一个 ⇒ 计数必须为偶数
  assert.equal(escapes.length % 2, 0, `代理转义未成对：${escapes.join(',')}`)
})
