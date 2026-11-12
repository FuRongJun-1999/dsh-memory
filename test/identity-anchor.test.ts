import test from 'node:test'
import assert from 'node:assert/strict'

import { formatTimelineDecayed, renderIdentityAnchors, IDENTITY_MAX_ITEMS } from '../src/hooks.js'

// issue #635：self/anchor（永久层）被 RECALL_SKIP_LAYERS 跳过，用户写完「我是谁」
// 永远不会被自动注入。本组守卫钉住两条：
//   ① 既有行为不变（默认不渲染永久层）；
//   ② 新增独立身份块只吃永久层、有独立条数/字数上限。

const payload = {
  items: [
    { layer: 'contextual', preview: '最近聊过发布窗口' },
    { layer: 'self', preview: '我叫灵枢，说话用中文' },
    { layer: 'anchor', preview: '画我用月光契约那张参考图' },
    { layer: 'knowledge', preview: 'BM25 默认关' },
  ],
}

test('① 既有块默认跳过 self/anchor（行为不变）', () => {
  const text = formatTimelineDecayed(payload)
  assert.ok(text.includes('发布窗口'))
  assert.ok(text.includes('BM25'))
  assert.ok(!text.includes('我叫灵枢'))
  assert.ok(!text.includes('参考图'))
})

test('② 身份块只取永久层', () => {
  const id = renderIdentityAnchors(payload)
  assert.ok(id.includes('我叫灵枢'))
  assert.ok(id.includes('参考图'))
  assert.ok(!id.includes('发布窗口'))
  assert.ok(!id.includes('BM25'))
})

test('③ 身份块条数受限', () => {
  const many = { items: Array.from({ length: 10 }, (_, i) => ({ layer: 'self', preview: '身份 ' + i })) }
  const id = renderIdentityAnchors(many)
  assert.equal(id.trim().split('\n').length, IDENTITY_MAX_ITEMS)
})

test('④ 无永久层时身份块为空（不 push 空块）', () => {
  assert.equal(renderIdentityAnchors({ items: [{ layer: 'knowledge', preview: 'x' }] }), '')
  assert.equal(renderIdentityAnchors(null), '')
})

test('⑤ 身份块同样过脱敏（凭据不原样进入上下文）', () => {
  const id = renderIdentityAnchors({ items: [{ layer: 'self', preview: '我的 key 是 sk-live-ABCDEFGHIJKLMNOP' }] })
  assert.ok(!id.includes('sk-live-ABCDEFGHIJKLMNOP'))
})
