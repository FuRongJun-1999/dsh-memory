import test from 'node:test'
import assert from 'node:assert/strict'

import { toolPublicNames } from '../src/tools.js'

// issue #634：0.9.9 起工具名去掉前缀（lingshu_cg -> cg），升级中运行的会话
// 旧名调用变成 unknown tool。toolPublicNames 是「一个工具注册哪些名字」的单点判据：
// 注册面与测试共用，避免两处各写一份。

test('裸名 + 缺省别名：同时给出 cg 与 lingshu_cg', () => {
  assert.deepEqual(toolPublicNames('cg', '', true), ['cg', 'lingshu_cg'])
})

test('关掉别名：只给裸名', () => {
  assert.deepEqual(toolPublicNames('cg', '', false), ['cg'])
})

test('自定义前缀：只给带前缀名，不叠加 lingshu_ 别名', () => {
  assert.deepEqual(toolPublicNames('cg', 'x_', true), ['x_cg'])
})

test('已经以 lingshu_ 开头的工具不重复加前缀', () => {
  assert.deepEqual(toolPublicNames('lingshu_cg', '', true), ['lingshu_cg'])
})

test('mdcg_* 系列同样有别名', () => {
  assert.deepEqual(toolPublicNames('mdcg_reflect', '', true), ['mdcg_reflect', 'lingshu_mdcg_reflect'])
})
