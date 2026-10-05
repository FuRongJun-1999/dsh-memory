/**
 * token_desensitize.test.ts · 自动记忆脱敏对**本项目自有令牌形态**的守卫（issue #45）
 *
 * 背景：批次71 把 `\btk_[0-9a-f]{8,}\b` 加进**写入闸门**的禁表（data/policy.json），
 * 但自动记忆链路走 `mdcg_remember(gated=true)`、**不过 audit**——`src/hooks.ts` 的
 * SENSITIVE_PATTERNS 是这条路上唯一的防线。此前它认得 sk-/Bearer/password/手机号，
 * 唯独不认自家令牌：用户粘一次令牌即以明文落进共用记忆库（实测见 issue #45）。
 *
 * 本测锁三件事：
 *   ① 裸令牌 id（`tk_` + 12 位 hex）被过滤；
 *   ② 完整令牌 `mdcg1.<role>.<token_id>.<secret>` **整段吃掉**，secret 不留残片；
 *   ③ 前缀不误伤（`tk_ 是前缀` / `mdcg1.designer 是角色` 这类正常文本原样保留）。
 *
 * 哑值一律非真凭据：`tk_0123456789abcdef` 由固定字符串拼装，非任何已签发令牌。
 */
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { desensitize } from '../src/hooks.ts'

const TOK_ID = 'tk_0123456789abcdef'
const TOK_FULL = `mdcg1.designer.${TOK_ID}.WPK16Yq2xR9tLmN0pQrS5uVwX8yZaB3cD4eF6gH7i`
const REDACTED = '[已过滤:令牌id]'
const REDACTED_FULL = '[已过滤:令牌]'

test('① 裸令牌 id 被过滤', () => {
  const out = desensitize(`用令牌 ${TOK_ID} 调用发布接口`)
  assert.ok(out !== null, '非纯凭据消息不得返回 null')
  assert.ok(!out.includes(TOK_ID), `令牌 id 未过滤：${out}`)
  assert.ok(out.includes(REDACTED), `未见占位符：${out}`)
})

test('② 完整令牌整段吃掉，secret 不留残片', () => {
  const out = desensitize(`设为 MDCG_TOKEN=${TOK_FULL} 再重启`)
  assert.ok(out !== null)
  assert.ok(!out.includes('WPK16Y'), `secret 段残留明文：${out}`)
  assert.ok(!out.includes(TOK_ID), `token_id 段残留：${out}`)
  assert.ok(!out.includes('mdcg1.'), `令牌前缀残留：${out}`)
  assert.ok(out.includes(REDACTED_FULL), `未见占位符：${out}`)
})

test('③ 纯令牌消息 → null（跳过写入，不进记忆库）', () => {
  assert.equal(desensitize(TOK_FULL), null)
  assert.equal(desensitize(TOK_ID), null)
})

test('④ 顺序回归：完整令牌先于裸 id 匹配', () => {
  // 若裸 id 规则排在前面，会先吃掉 token_id 段、把 secret 留成明文
  // （实测错误产物形如 `mdcg1.designer.[已过滤:令牌id].WPK16Y…`）。
  const out = desensitize(`令牌 ${TOK_FULL} 请妥善保管`)
  assert.ok(out !== null)
  assert.ok(!out.includes('WPK16Y'), `顺序错误导致 secret 残留：${out}`)
  assert.ok(!/\[已过滤:令牌id\]\.[A-Za-z0-9_-]{16,}/.test(out), `完整令牌被拆开：${out}`)
})

test('⑤ 前缀不误伤：普通文本原样保留', () => {
  const keep = '令牌很重要，tk_ 是前缀，mdcg1.designer 是角色'
  assert.equal(desensitize(keep), keep)
  const other = '用户喜欢猫，上次聊了冒泡排序的实现'
  assert.equal(desensitize(other), other)
})

// ————— N269：语言面 / 标签面词形补齐（与 hooks.ts:66 的界面承诺同面）—————
// 缺陷形态（本轮复核实测）：下列词形此前**整条原样通过**——凭据明文经该路落进记忆库；
// 该路（mdcg_remember(gated=true)）不过 audit，SENSITIVE_PATTERNS 是唯一防线。

test('⑥ 语言面词形：密碼 / パスワード / 口令 与既有「密码」同口径（N269）', () => {
  const cases: Array<[string, string]> = [
    ['繁体 密碼', '密碼：abcdefgh1234'],
    ['日文 パスワード', 'パスワード：abcdefgh1234'],
    ['中文 口令', '口令：abcdefgh1234'],
    ['口令+是 分隔', '口令是abcdefgh1234'],
  ]
  for (const [name, text] of cases) {
    const out = desensitize(`我的配置 ${text} 请妥善保管`)
    assert.ok(out !== null, `${name}: 非纯凭据消息不得返回 null`)
    assert.ok(!out.includes('abcdefgh1234'), `${name}: 凭据明文残留：${out}`)
    assert.ok(out.includes('[已过滤:密码]'), `${name}: 未命中（界面承诺的默认过滤形同虚设）：${out}`)
  }
})

test('⑦ 标签面词形：密钥 / token / secret / creds 的「标签: 值」形态不得漏检（N269）', () => {
  const cases: Array<[string, string, string]> = [
    ['中文 密钥', '密钥：abcdefgh1234', 'abcdefgh1234'],
    ['token:', 'token: abcdefgh1234', 'abcdefgh1234'],
    ['secret=', 'secret=abcdefgh1234', 'abcdefgh1234'],
    ['creds=', 'creds=abcdefgh1234', 'abcdefgh1234'],
    ['全角拼写 ＴＯＫＥＮ：', 'ＴＯＫＥＮ：ａｂｃｄｅｆｇｈ１２３４', 'ａｂｃｄｅｆｇｈ１２３４'],
  ]
  for (const [name, text, secret] of cases) {
    const out = desensitize(`我的配置 ${text} 请妥善保管`)
    assert.ok(out !== null, `${name}: 非纯凭据消息不得返回 null`)
    assert.ok(!out.includes(secret), `${name}: 凭据明文残留：${out}`)
    assert.ok(out.includes('[已过滤:密钥]'), `${name}: 未命中：${out}`)
  }
})

test('⑧ 误伤边界：标签后是中文说明/低熵值时不动（与「密码是重要的安全概念」同口径）', () => {
  for (const k of [
    'token: 这句是中文说明文字',
    'secret: 待办事项',
    '口令：不是凭据只是说明',
    '密钥：管理很重要',
    '令牌很重要，tk_ 是前缀',
  ]) {
    assert.equal(desensitize(k), k, `普通文本被误伤：${k} ⇒ ${desensitize(k)}`)
  }
})
