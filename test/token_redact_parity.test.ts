/**
 * token_redact_parity.test.ts · 自动记忆脱敏的**残余面**守卫（PR#46 合并当批加固）
 *
 * 背景：PR#46（贡献者 @heimixieb，issue #45）给 `SENSITIVE_PATTERNS` 补了自家令牌形态，
 * 方向正确且主线用例已闭合（真令牌在普通语境下整段吃掉，见 token_desensitize.test.ts）。
 * 但复核发现它仍有**同一形态的残余面**：整条令牌规则一旦失配，裸 id 规则会**只吃掉 id
 * 段**、把 secret 留成明文——PR 用「完整令牌规则排在前面」修掉了其中一个触发点（顺序），
 * 另有三处触发点未覆盖：
 *   ① 前导为词字符（`k_mdcg1.…`）⇒ 原式的 `\b` 失效；
 *   ② role 含非字母（`sub-agent1`）⇒ role 字符类 `[A-Za-z]+` 失配；
 *   ③ secret 短于 16 字符 ⇒ secret 字符类下限 `{16,}` 失配。
 * 三者都让整条失配、而裸 id 命中，产物形如 `mdcg1.designer.[已过滤:令牌id].SECRET…`。
 *
 * 本测锁四件事：
 *   ① 真令牌（8 个角色）在普通语境下整段吃掉，secret 无残片；
 *   ② 上述三个触发点 + 顺序交换序 → secret 一律无残片（**核心不变式**：id 规则不得
 *      只吃 id 而把 secret 留下）；
 *   ③ 与写入闸门 `data/policy.json` 的禁表同口径：凡禁表 #10/#11 命中的语料，TS 侧必须
 *      同样命中、且输出中不得残留被禁表命中的原文（两闸不得分叉——issue #45 的根因就是
 *      两份表脱节，这条守卫是「建议 2」的机械形态，先落地，架构取舍另议）；
 *   ④ 形态假设不漂移：从 `md_cg/tokens.py` 读出角色表、token_id/secret 的生成式，断言本
 *      测与实现同源（改了令牌格式而没改本测 ⇒ 立刻红）。
 *
 * 哑值一律非真凭据：`tk_0123456789abcdef` / 随机生成的样本仅用于形态检验，非任何已签发令牌。
 */
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { randomBytes } from 'node:crypto'
import { desensitize, SENSITIVE_PATTERNS } from '../src/hooks.ts'

const POLICY = JSON.parse(readFileSync('data/policy.json', 'utf8')) as { forbidden: string[] }
const TOKENS_PY = readFileSync('md_cg/tokens.py', 'utf8')

/** 与实现同源的构造法：token_id = 'tk_' + 12 位 hex；secret = 43 字符 url-safe。 */
function makeTokId(): string {
  return 'tk_' + randomBytes(6).toString('hex')
}
function makeSecret(): string {
  return randomBytes(32).toString('base64url')
}
function makeToken(role: string, id = makeTokId(), secret = makeSecret()): string {
  return `mdcg1.${role}.${id}.${secret}`
}

/** 全角色（与 tokens.py 的 ROLE_SPECS 对齐，④ 会机械核对）。 */
const ROLES = ['designer', 'orchestr', 'record', 'reflect', 'verify', 'output', 'sustain', 'guest']

/** 按给定规则链复跑脱敏（SENSITIVE_PATTERNS 的 order 可交换 ⇒ 可验证顺序无关性）。 */
function redactWith(
  pats: Array<{ re: RegExp; label: string }>,
  text: string,
): string {
  let out = text
  for (const { re, label } of pats) {
    re.lastIndex = 0
    out = out.replace(re, `[已过滤:${label}]`)
  }
  return out
}

/** 把 policy 的 forbidden 翻成 JS 正则：只容忍 Python 的 `(?i)` 内联标志，其它不兼容要崩出来。 */
function policyRe(pat: string): RegExp {
  let src = pat
  let flags = ''
  const m = /^\(\?([a-z]+)\)/.exec(src)
  if (m) {
    src = src.slice(m[0].length)
    if (m[1] !== 'i') throw new Error(`policy 模式含 JS 无法表达的内联标志 (?${m[1]})：${pat}`)
    flags = 'i'
  }
  try {
    return new RegExp(src, flags)
  } catch (e) {
    throw new Error(`policy 模式无法在 JS 侧表达（两闸无法对齐，须人工裁决）：${pat} —— ${e}`)
  }
}

// 令牌形态相关的禁表条目：写入闸门侧 #10（裸 id）与 #11（完整令牌）。
const POLICY_TOKEN_RES = POLICY.forbidden.filter((_, i) => i === 9 || i === 10).map(policyRe)
const POLICY_ALL_RES = POLICY.forbidden.map(policyRe)

function policyHits(text: string, res = POLICY_ALL_RES): string[] {
  return POLICY.forbidden.filter((_, i) => res === POLICY_ALL_RES || i === 9 || i === 10)
    .filter((p, _i) => policyRe(p).test(text))
}

test('① 真令牌（全角色）整段吃掉，secret 不留残片', () => {
  for (const role of ROLES) {
    const secret = makeSecret()
    const tok = makeToken(role, makeTokId(), secret)
    const out = desensitize(`用令牌 ${tok} 调发布接口`)
    assert.ok(out !== null, `${role}: 非纯凭据消息不得返回 null`)
    assert.ok(!out.includes(secret), `${role}: secret 段残留明文：${out}`)
    assert.ok(!out.includes('mdcg1.'), `${role}: 令牌前缀残留：${out}`)
    assert.ok(out.includes('[已过滤:令牌]'), `${role}: 未整段吃掉：${out}`)
  }
})

test('② 三处失配触发点 + 顺序交换序：secret 一律无残片', () => {
  const secret = makeSecret()
  const id = makeTokId()
  // 第三列＝整条规则是否**应当**命中（前缀随之消失）。secret 短于 8 时整条规则本就
  // 不该命中（那是形态判断，不是缺陷），此时只要求「尾巴被 id 规则带走」。
  const cases: Array<[string, string, boolean]> = [
    ['前导词字符（`\\b` 失效）', `k_${makeToken('designer', id, secret)}`, true],
    ['前导字母数字', `a${makeToken('designer', id, secret)}`, true],
    ['role 含非字母', `令牌 ${makeToken('sub-agent1', id, secret)} 到此`, true],
    ['secret 短于 8', `令牌 ${makeToken('designer', id, 'short')} 到此`, false],
    ['五段（异常形态）', `令牌 mdcg1.designer.${id}.${secret}.extra 到此`, true],
  ]
  for (const [name, text, fullRule] of cases) {
    const out = desensitize(text)
    assert.ok(out === null || !out.includes(secret), `${name}: secret 残留明文：${out}`)
    assert.ok(out === null || !/\[已过滤:令牌id\]\.[A-Za-z0-9_-]{8,}/.test(out),
      `${name}: id 被吃掉而 secret 留在占位符后：${out}`)
    if (fullRule) assert.ok(out === null || !out.includes('mdcg1.'), `${name}: 令牌前缀残留：${out}`)
  }
  // 顺序交换：把「裸 id」规则挪到「完整令牌」之前——顺序不再允许成为泄漏条件。
  // 交换序下前缀可能留下（`mdcg1.designer.[已过滤:令牌id]`），但**凭据本体不得留下**。
  // 注意：JS 无负索引，`arr[-1]` 是 undefined（本测首版即栽在此，守卫自己抓出来）。
  const n = SENSITIVE_PATTERNS.length
  const swapped = [
    ...SENSITIVE_PATTERNS.slice(0, n - 2),
    SENSITIVE_PATTERNS[n - 1],
    SENSITIVE_PATTERNS[n - 2],
  ]
  const tok = makeToken('designer', id, secret)
  const outSwap = redactWith(swapped, `令牌 ${tok} 请妥善保管`)
  assert.ok(!outSwap.includes(secret), `交换序下 secret 残留（顺序仍被当作安全性质）：${outSwap}`)
  assert.ok(!/\[已过滤:令牌id\]\.[A-Za-z0-9_-]{8,}/.test(outSwap),
    `交换序下 id 与 secret 被拆开：${outSwap}`)
})

test('③ 与写入闸门禁表同口径：禁表 #10/#11 命中的语料，TS 必须同样命中且不残留凭据', () => {
  // 语料带 secret（有凭据本体才可判残片）：parity 只看「两侧是否同判」，
  // 残片看「TS 输出里 secret 是否还在」——早先只比对整段匹配，导致
  // 「id 被吃、secret 留守」这种泄漏在 parity 视角下看不出来（红基线实测），故收紧。
  const corpus: Array<{ text: string; secret?: string }> = []
  for (const role of ROLES) {
    const secret = makeSecret()
    corpus.push({ text: `设为 MDCG_TOKEN=${makeToken(role, makeTokId(), secret)} 再重启`, secret })
  }
  const s1 = makeSecret()
  corpus.push({ text: `用令牌 ${makeTokId()} 调用发布接口`, secret: s1 })  // 裸 id：secret 不在文中
  const s2 = makeSecret()
  corpus.push({ text: `令牌 ${makeToken('designer', makeTokId(), 'short')} 到此`, secret: s2 })
  const s3 = makeSecret()
  corpus.push({ text: `令牌 ${makeToken('sub-agent1', makeTokId(), s3)} 到此`, secret: s3 })
  const s4 = makeSecret()
  corpus.push({ text: `k_${makeToken('designer', makeTokId(), s4)}`, secret: s4 })

  for (const { text, secret } of corpus) {
    const polHit = POLICY_TOKEN_RES.some((re) => (re.lastIndex = 0, re.test(text)))
    const tsLabels = SENSITIVE_PATTERNS.filter(({ re }) => (re.lastIndex = 0, re.test(text))).map((p) => p.label)
    const tsHit = tsLabels.some((l) => l === '令牌' || l === '令牌id')
    assert.equal(tsHit, polHit, `两闸分叉（禁表命中=${polHit}，TS 命中=${tsHit}）：${text}`)
    if (!polHit) continue
    const out = desensitize(text)
    // 凭据本体（secret 段）不得以明文留在 TS 输出——这是本测的核。
    assert.ok(out === null || !(secret && out.includes(secret)),
      `禁表命中却让 secret 明文穿过了 TS 脱敏：${text} ⇒ ${out}`)
  }
})

test('④ 形态假设与实现同源（改了令牌格式而没改本测 ⇒ 立刻红）', () => {
  // 角色表
  const roleBlock = /ROLE_SPECS = OrderedDict\(\[([\s\S]*?)\n\]\)/.exec(TOKENS_PY)
  assert.ok(roleBlock, 'tokens.py 的 ROLE_SPECS 块未找到（形态已变，须人工复核本测）')
  const pyRoles = [...roleBlock![1].matchAll(/\("([a-z0-9_-]+)",\s*\{/g)].map((m) => m[1])
  assert.deepEqual([...pyRoles].sort(), [...ROLES].sort(), `角色表不一致：py=${pyRoles} ts=${ROLES}`)
  // token_id / secret 生成式
  assert.match(TOKENS_PY, /token_id,\s*secret\s*=\s*"tk_"\s*\+\s*secrets\.token_hex\(6\)/,
    'token_id 不再是 `tk_` + token_hex(6)（12 位 hex）——本测的形态假设需同步')
  assert.match(TOKENS_PY, /secrets\.token_urlsafe\(32\)/,
    'secret 不再是 token_urlsafe(32)——本测的形态假设需同步')
  assert.match(TOKENS_PY, /return f"\{PREFIX\}\.\{role\}\.\{token_id\}\.\{secret\}"/,
    'make_token 的四段拼装式已变——本测的形态假设需同步')
})

test('⑤ 前缀不误伤：半段/短尾/普通文本原样保留；短尾文件名不被吞', () => {
  const keep = [
    '令牌很重要，tk_ 是前缀，mdcg1.designer 是角色',
    'tk_0123 只有四位，不是令牌 id',
    '用户喜欢猫，上次聊了冒泡排序的实现',
  ]
  for (const k of keep) assert.equal(desensitize(k), k, `误伤：${k} ⇒ ${desensitize(k)}`)
  // 真 id 后的短文件名尾巴（`.py` 2 字符 < 下限 4）不被吞——id 照脱敏、尾巴照留。
  assert.equal(desensitize('用 tk_0123456789abcdef.py 举例'), '用 [已过滤:令牌id].py 举例')
})
