/**
 * fullwidth_redact.test.ts · 自动记忆脱敏的**全角形态**守卫（M5）
 *
 * 背景（探针实测）：`src/hooks.ts` 的 SENSITIVE_PATTERNS 值类字符集此前全是半角
 * ——`[A-Za-z0-9_@#$%^&*!.-]`、`[^\s,，。;；]`、`sk-` 后限定 `[A-Za-z0-9_-]{8,}`。
 * 于是 `密码：ｐａｓｓｗｏｒｄ１２３４５６` / `ａｐｉ＿ｋｅｙ＝…` / `sk-ａｂｃｄ…`
 * 这类**全角写法全部漏检**（filtered=false）——用户把凭据经全角输入法粘一次，
 * 明文即落进共用记忆库。全角形态是独立 Unicode 区段（U+FF01-U+FF5E ↔ U+0021-U+007E），
 * `\w`/`\d`/`\b` 一律不认，必须显式列出。
 *
 * 修复取向（②「两向都要测」+ ③「选了哪条路、依据是什么」）
 * ----------------------------------------------------------
 * 取**显式两宽字符类**（值类与词形都列全角形态、`\b` 换两宽 lookaround），
 * **不做**「先全角→半角归一化再匹配」。依据与代价：
 *   · NFKC 归一化会**改变长度**（`㍿`→`株式会社`、半角カナ `ﾊﾟ`→`パ`）⇒ 匹配片段
 *     无法映射回原文偏移，替换要么错位要么漏改（静默失真）；
 *   · 退一步「归一化后整段替换」= 把正文里的全角标点统统半角化 ⇒ **改写记忆真源**，
 *     与「原文保真、只在注入边界改写」的既有纪律相悖；
 *   · 归一化还会抹平 `．`(U+FF0E，`.` 的全角形态) 与 `。`(U+3002，中文句号) 的
 *     区别，值类边界随之漂移 —— 下组 ④ 把这条边界钉成断言（句读处**必须**停）。
 * 故本测同时锁三面：① 两宽同判（同形即同过滤）；② 反归一化（普通文本逐字节零改写）；
 * ③ 误伤面（普通中文句子 / 空值 / 占位符 / 跨句不吞并）。
 *
 * 判据的非循环性：样本的「全角性」由 **Unicode NFKC 归一化**裁定（平台真源，
 * `full.normalize('NFKC') === half`），**不用**实现里的换算公式——否则实现错、
 * 守卫同错同绿。
 *
 * 哑值一律非真凭据：样本值由 `abcdefgh1234` / `0123456789abcdef` 这类固定串拼装，
 * 非任何已签发令牌。
 */
import { test } from 'node:test'
import assert from 'node:assert/strict'
import {
  TOKEN_VALUE_CHARS,
  WORD_CHARS,
  desensitize,
  SENSITIVE_PATTERNS,
} from '../src/hooks.ts'

/** 把凭据样本包进普通句子——保证脱敏后仍有残余文本（可判「值是否残留」）。 */
const wrap = (s: string): string => `我的配置 ${s} 请妥善保管`

interface Pair {
  name: string
  /** 半角形态（既有行为面）。 */
  half: string
  /** 其全角同形（修复面）——由 NFKC 裁定同形，非本实现的公式生成。 */
  full: string
  label: string
  /** 值本体（半角形态的子串）；全角侧按**同索引**取（全角映射逐字符一一对应，长度不变）。 */
  val: string
}

const PAIRS: Pair[] = [
  {
    name: 'sk- 密钥',
    half: 'sk-abcdefgh1234',
    full: 'ｓｋ－ａｂｃｄｅｆｇｈ１２３４',
    label: 'API密钥',
    val: 'abcdefgh1234',
  },
  {
    name: 'api_key=',
    half: 'api_key=abcdefgh1234',
    full: 'ａｐｉ＿ｋｅｙ＝ａｂｃｄｅｆｇｈ１２３４',
    label: 'API密钥',
    val: 'abcdefgh1234',
  },
  {
    name: 'apikey:',
    half: 'apikey:abcdefgh1234',
    full: 'ａｐｉｋｅｙ：ａｂｃｄｅｆｇｈ１２３４',
    label: 'API密钥',
    val: 'abcdefgh1234',
  },
  {
    name: 'access_token=',
    half: 'access_token=abcdefgh1234',
    full: 'ａｃｃｅｓｓ＿ｔｏｋｅｎ＝ａｂｃｄｅｆｇｈ１２３４',
    label: 'API密钥',
    val: 'abcdefgh1234',
  },
  {
    name: 'password=',
    half: 'password=abcdefgh1234',
    full: 'ｐａｓｓｗｏｒｄ＝ａｂｃｄｅｆｇｈ１２３４',
    label: '密码',
    val: 'abcdefgh1234',
  },
  {
    name: 'pwd:',
    half: 'pwd:abcdefgh1234',
    full: 'ｐｗｄ：ａｂｃｄｅｆｇｈ１２３４',
    label: '密码',
    val: 'abcdefgh1234',
  },
  {
    name: 'Bearer 令牌',
    half: 'Bearer eyJhbGciOiJIUzI1NiJ9abcdefgh',
    full: 'Ｂｅａｒｅｒ ｅｙＪｈｂＧｃｉＯｉＪＩＵｚＩ１ＮｉＪ９ａｂｃｄｅｆｇｈ',
    label: '令牌',
    val: 'eyJhbGciOiJIUzI1NiJ9abcdefgh',
  },
  {
    name: '中文密码（冒号分隔）',
    half: '密码:password123456',
    full: '密码：ｐａｓｓｗｏｒｄ１２３４５６',
    label: '密码',
    val: 'password123456',
  },
  {
    name: '身份证号',
    half: '11010119900307789X',
    full: '１１０１０１１９９００３０７７８９Ｘ',
    label: '身份证号',
    val: '11010119900307789X',
  },
  {
    name: '手机号',
    half: '13812345678',
    full: '１３８１２３４５６７８',
    label: '手机号',
    val: '13812345678',
  },
  {
    name: '四段自有令牌',
    half: 'mdcg1.designer.tk_0123456789abcdef.WPK16Yq2xR9tLmN0pQrS5uVwX8yZaB3cD4eF6gH7i',
    full: 'ｍｄｃｇ１．ｄｅｓｉｇｎｅｒ．ｔｋ＿０１２３４５６７８９ａｂｃｄｅｆ．'
      + 'ＷＰＫ１６Ｙｑ２ｘＲ９ｔＬｍＮ０ｐＱｒＳ５ｕＶｗＸ８ｙＺａＢ３ｃＤ４ｅＦ６ｇＨ７ｉ',
    label: '令牌',
    val: 'WPK16Yq2xR9tLmN0pQrS5uVwX8yZaB3cD4eF6gH7i',
  },
  {
    name: '裸令牌 id + secret 尾',
    half: 'tk_0123456789abcdef.WPK16Yq2xR9tLmN0',
    full: 'ｔｋ＿０１２３４５６７８９ａｂｃｄｅｆ．ＷＰＫ１６Ｙｑ２ｘＲ９ｔＬｍＮ０',
    label: '令牌id',
    val: 'WPK16Yq2xR9tLmN0',
  },
]

test('① 两向同判：同形即同过滤，且值不残留（半角/全角逐条对拍）', () => {
  for (const c of PAIRS) {
    // 先由**平台归一化**裁定这对样本确实互为两宽同形（非本实现的公式）
    assert.equal(c.full.normalize('NFKC'), c.half,
      `${c.name}: 全角样本的 NFKC 应还原为半角形态`)
    assert.notEqual(c.full, c.half, `${c.name}: 两宽样本不得逐字节相同`)

    const i = c.half.indexOf(c.val)
    assert.ok(i >= 0, `${c.name}: 值本体取不到`)
    const fullVal = c.full.slice(i, i + c.val.length)

    for (const [width, text, secret] of [
      ['半角', c.half, c.val],
      ['全角', c.full, fullVal],
    ] as const) {
      const out = desensitize(wrap(text))
      assert.ok(out !== null, `${c.name}(${width}): 非纯凭据消息不得返回 null`)
      assert.ok(!out.includes(secret), `${c.name}(${width}): 凭据值残留明文：${out}`)
      assert.ok(out.includes(`[已过滤:${c.label}]`),
        `${c.name}(${width}): 未见 ${c.label} 占位符：${out}`)
    }

    // 纯凭据消息（整条都是值）→ null（跳过写入），两宽一致
    assert.equal(desensitize(c.full) === null, desensitize(c.half) === null,
      `${c.name}: 两宽的「整条跳过」命运必须一致`)
  }
})

test('② 混宽单串：半角/全角混排一律命中（两宽类天然覆盖混合写法）', () => {
  const mixed: Array<{ text: string; label: string; secret: string }> = [
    { text: '密码：ｐａｓｓｗｏｒｄ123456', label: '密码', secret: 'ｐａｓｓｗｏｒｄ123456' },
    { text: 'ｓｋ－ａｂｃｄ１２３４', label: 'API密钥', secret: 'ａｂｃｄ１２３４' },
    { text: '密码＝password123456', label: '密码', secret: 'password123456' },
    { text: 'Bearer ＸＹＺ１２３４５６７８', label: '令牌', secret: 'ＸＹＺ１２３４５６７８' },
    { text: 'ａｐｉ＿ｋｅｙ＝abcdefgh1234', label: 'API密钥', secret: 'abcdefgh1234' },
  ]
  for (const { text, label, secret } of mixed) {
    const out = desensitize(wrap(text))
    assert.ok(out !== null, `混宽样本不得整条消失（应有残余文本）：${text}`)
    assert.ok(!out.includes(secret), `混宽凭据值残留：${text} ⇒ ${out}`)
    assert.ok(out.includes(`[已过滤:${label}]`), `混宽样本未命中：${text} ⇒ ${out}`)
  }
})

test('③ 反归一化：本实现不改写非凭据字符（全角标点/全角字母/可归一化字符逐字节保留）', () => {
  // 这些文本 NFKC 都会变（全角→半角、㍿→株式会社、①→1、Ⅳ→IV），若走了「归一化后
  // 整段替换」这条路，它们必然被改写——本组是「没走那条路」的机械证据。
  const nfkcSensitive = [
    '全角字母 ａｂｃ 与全角标点 ：＝＿ 。，；！？ 原样保留',
    '株式会社㍿ 与 ① 序号、Ⅳ 罗马数字',
    '密码学是重要的安全概念，全角符号 ＿ 与 ＝ 的用法',
    '普通中文句子，含标点。全角数字２０２４年。',
  ]
  for (const k of nfkcSensitive) {
    assert.equal(k.normalize('NFKC') === k, false,
      `样本需可被 NFKC 改写才有判别力（否则本组退化为恒真）：${k}`)
    assert.equal(desensitize(k), k, `普通文本被误伤/被改写：${k} ⇒ ${desensitize(k)}`)
  }
  // 无全角字符的普通中文句子：同样原样返回（误伤面）
  const plain = ['密码是重要的安全概念', '用户喜欢猫，上次聊了冒泡排序的实现']
  for (const k of plain) assert.equal(desensitize(k), k, `普通文本被误伤：${k}`)
})

test('④ 误伤边界：空值/占位符不动，全角句读处停（不跨句吞并）', () => {
  // 空值 / 占位符：规则要求值本体存在 → 不得命中
  for (const k of ['密码：', '密码：<你的密码>', 'api_key=', 'pwd：', '密码：   ']) {
    assert.equal(desensitize(k), k, `空值/占位符被误伤：${k} ⇒ ${desensitize(k)}`)
  }
  // 误伤方向补强（守卫员 2026-09-30 独立加样，行为经探针实测取得）：
  //   · 中文密码规则的值类两宽后仍**不含中文** ⇒ 「密码：<中文说明>」不得被吞；
  //   · 手机号/身份证规则的收手靠两宽 lookaround：11 位之后仍有数字、18 位之后
  //     仍有一位，都不得被**截取**（这两条是「多认」时必须守住的误伤边界）。
  for (const k of [
    '密码：这是中文说明，不要在别处写密码',
    '订单号 1381234567890123456789 很长，不是手机号',
    '身份证 1101011990030778901 多一位，不是身份证',
  ]) {
    assert.equal(desensitize(k), k, `误伤方向样本被改写：${k} ⇒ ${desensitize(k)}`)
  }
  // 空串：无内容可写（既有语义：过滤后无残余 → 整条跳过）
  assert.equal(desensitize(''), null, '空串应整条跳过')
  // 只剩占位符：同样整条跳过（既有语义，不许因全角改动而变）
  assert.equal(desensitize('[已过滤:密码]'), null, '只剩占位符应整条跳过')
  assert.equal(desensitize('[已过滤:密码]  '), null, '只剩占位符与空白应整条跳过')

  // 全角句读是**边界**：值在 。／，／；／！／？ 处停，不得吞掉下一句
  const sent = '密码：ａｂｃｄｅｆ１２３４。这是下一句，普通文本'
  const out = desensitize(sent)
  assert.ok(out !== null, '含残余正文不得整条消失')
  assert.ok(!out.includes('ａｂｃｄｅｆ'), `凭据值残留：${out}`)
  assert.ok(out.includes('。这是下一句，普通文本'),
    `全角句号处必须收住，不得跨句吞并：${out}`)
  for (const [mark, tail] of [['，', '逗号后正文'], ['；', '分号后正文'], ['！', '叹号后正文']] as const) {
    const o = desensitize(`密码：ａｂｃｄｅｆ１２３４${mark}${tail}`)
    assert.ok(o !== null && o.includes(`${mark}${tail}`),
      `全角标点 ${mark} 处必须收住：${o}`)
  }
  // 刻意收进值类的 `．`（U+FF0E 是 `.` 的全角形态，不是中文句号 `。`）——
  // 与半角 `[.-]` 同口径：整值被吃，属刻意的「多认」，不是误伤。
  assert.equal(desensitize('密码：ａｂｃｄ．ｅｆｇｈ１２３４'), null,
    '`．` 是 `.` 的全角形态、属值类（与半角口径一致）')
})

test('⑤ 结构不变量：每条规则的词形/值类两宽齐备（新增规则不得只写半角）', () => {
  assert.ok(SENSITIVE_PATTERNS.length >= 9, '规则条数异常（少于此前的九条）')
  for (const { re, label } of SENSITIVE_PATTERNS) {
    assert.match(re.source, /[\uFF01-\uFF5E]/,
      `规则「${label}」的字符集未含全角形态（M5 回归）：${re.source}`)
  }
})

test('⑥ 全角纯凭据消息 → null（不进记忆库），与半角同命', () => {
  for (const s of ['密码：ｐａｓｓｗｏｒｄ１２３４５６', 'ｓｋ－ａｂｃｄｅｆｇｈｉｊｋｌｍｎ',
    'ａｐｉ＿ｋｅｙ＝０１２３４５６７８９０１２３']) {
    assert.equal(desensitize(s), null, `全角纯凭据消息应整条跳过：${s}`)
  }
})

test('⑦ 同源：两条令牌规则的字面量字符类与共享字符集常量一致（防漂移）', () => {
  // 令牌规则**必须**保持 `/…/g` 字面量（md_cg/test_token_lowercase_form.py 的
  // G7d~G7g 逐行抽取字面并用 Python `re` 复跑），因此无法用 twoWidth() 组合——
  // 代价是字符类在规则里再写一遍。本组把「再写一遍」钉成与常量同源：
  // 改了常量却没改规则（或反之）⇒ 立刻红。
  const tokFull = SENSITIVE_PATTERNS.find(
    (p) => p.label === '令牌' && p.re.source.includes('mdcg1'))
  const tokId = SENSITIVE_PATTERNS.find((p) => p.label === '令牌id')
  assert.ok(tokFull, '未找到四段令牌规则（label=令牌 且含 mdcg1）')
  assert.ok(tokId, '未找到裸令牌 id 规则（label=令牌id）')
  for (const [name, src] of [['四段令牌', tokFull!.re.source], ['裸 id', tokId!.re.source]] as const) {
    assert.ok(src.includes(`[${TOKEN_VALUE_CHARS}]`),
      `${name}：令牌值类字面量与 TOKEN_VALUE_CHARS 不同源 ⇒ ${src}`)
    assert.ok(src.includes(`[${WORD_CHARS}]`),
      `${name}：词字符类字面量与 WORD_CHARS 不同源 ⇒ ${src}`)
  }
  // 判别力自证：类文本改动一位即不再匹配（否则本组只是恒真）
  assert.ok(!tokFull!.re.source.includes(`[x${TOKEN_VALUE_CHARS}]`),
    '同源判据须有判别力（多一个字符即应不匹配）')
  // 两条规则仍须是「半角拼写可见」的字面量（Python 形态守卫的抽取前提）
  assert.ok(tokFull!.re.source.includes('mdcg1') && tokId!.re.source.includes('tk_'),
    '令牌规则须保留半角字面拼写（否则 Python 形态守卫 G7d 抽不到）')
  assert.ok(SENSITIVE_PATTERNS.every((p) => !p.re.source.includes('\n')),
    '规则源不得跨行（逐行抽取的字面扫描前提）')
})
