/**
 * prompt-safety.test.ts · 注入边界转义回归守卫（issue #16）
 *
 * 判据一律取自**宿主真函数**，不复制宿主语义：
 *   `@deepseek-ai/dsh-system-prompt` 的 renderContextSections / renderContextSnapshot
 * 是本插件注入面的真实消费者——它们抛错即等于「该轮请求失败 / 会话不可用」。
 *
 * 覆盖：
 *   ① 复现：未转义的裸 `{{` 确实让宿主真函数抛错（bug 存在性证据）
 *   ② 修复：过 escapePromptBraces 后宿主渲染不再抛错，内容仍可辨
 *   ③ 保真：无 `{{` 的文本逐字节不变；转义只插空格、不删改字符
 *   ④ 形态矩阵：组名非法 / 名合法未注册 / 非简单组 / 孤立 `{{` / 三连括号 / 中文混排
 *   ⑤ 幂等：escape(escape(x)) === escape(x)
 *   ⑥ 端到端：含 `{{` 的记忆经 installMemoryHooks 注入后，宿主渲染不抛错
 *      （并与「不转义」对照，证明这道转义是必需的而非装饰）
 */
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { renderContextSections, renderContextSnapshot } from '@deepseek-ai/dsh-system-prompt'
import { escapePromptBraces } from '../src/lib/prompt_safety.ts'
import { installMemoryHooks } from '../src/hooks.ts'

/** 宿主 assembly 最小形态：renderContextSections 只读 contexts 与 variables。 */
function asm(texts: string[]): never {
  return {
    contexts: texts.map((text, i) => ({ name: `c${i}`, text })),
    variables: {},
  } as never
}

/** 会触发宿主四类 throw 的裸文本形态（真源：interpolate 的 ①~④ 分支）。 */
const DANGEROUS: Array<{ name: string; text: string }> = [
  { name: '组名非法（issue 原始形态）', text: 'run: docker inspect --format {{.Architecture}} box' },
  { name: '名合法但未注册', text: '模板里写 {{name}} 会被替换' },
  { name: '名不合规（含空格）', text: '{{a b}} 这种也会炸' },
  { name: '非简单组（嵌套花括号）', text: '{{{x}}} 三重括号' },
  { name: '孤立 {{ 但有后续 }}', text: 'code {{ not a group }} tail' },
]

/** 不含模板锚点 `{{` 的形态（含孤立 `}}`）——转义必须零改写。 */
const BENIGN: string[] = [
  '没有花括号的普通记忆',
  '孤立 close }} 单独出现',
  '单个 { 花括号也不动',
]

/** 宿主对「孤立 `{{`（全文无 `}}`）」宽容（interpolate 走 slice 当字面 prose），
 *  本实现**仍统一打断**：不依赖宿主这一内部宽容细节，换取可机械守卫的不变量
 *  ——输出永不含 `{{`（弱于「有 `}}` 才处理」的条件式规则，但强在可断言）。 */
const LONE_OPEN = '孤立 open {{ 后面没有任何闭合'

test('① 复现：裸 {{ 让宿主 renderContextSections 抛错', () => {
  for (const { name, text } of DANGEROUS) {
    assert.throws(
      () => renderContextSections(asm([text])),
      /malformed prompt variable reference|unknown prompt variable|no value for this assembly/,
      `未转义形态应触发宿主抛错：${name}`,
    )
  }
})

test('② 修复：escapePromptBraces 后宿主渲染不抛错且内容可辨', () => {
  for (const { name, text } of DANGEROUS) {
    const safe = escapePromptBraces(text)
    const sections = renderContextSections(asm([safe]))
    assert.equal(sections.length, 1, `应渲染出一段：${name}`)
    assert.ok(!safe.includes('{{'), `转义结果不得含 {{：${name}`)
    // 可辨性：原始字符序列（去掉空格后）保持不变
    assert.equal(
      safe.split(' ').join(''),
      text.split(' ').join(''),
      `转义只应插入空格：${name}`,
    )
    // renderContextSnapshot（= joinContextSections∘renderContextSections）同样不抛
    assert.ok(renderContextSnapshot(asm([safe])).includes('Current runtime context'))
  }
})

test('③ 保真与典型形态逐值断言', () => {
  assert.equal(escapePromptBraces('{{.Architecture}}'), '{ {.Architecture}}')
  assert.equal(escapePromptBraces('{{{a}}}'), '{ { {a}}}')
  assert.equal(escapePromptBraces('{{{{'), '{ { { {')
  assert.equal(escapePromptBraces('docker --format {{.X}} 与 {{.Y}}'), 'docker --format { {.X}} 与 { {.Y}}')
  // 零改写：不含 {{ 的文本原样返回（同一引用即逐字节相同）
  for (const t of BENIGN) assert.equal(escapePromptBraces(t), t)
  assert.equal(escapePromptBraces('中文{{混排}}英文'), '中文{ {混排}}英文')
  // 孤立 `{{` 亦打断（刻意比宿主报错面更宽，见 LONE_OPEN 注释）
  assert.equal(escapePromptBraces(LONE_OPEN), '孤立 open { { 后面没有任何闭合')
})

test('④ 幂等：escape(escape(x)) === escape(x)', () => {
  for (const { text } of DANGEROUS) {
    const once = escapePromptBraces(text)
    assert.equal(escapePromptBraces(once), once)
  }
})

test('⑤ 对照：孤立 {{ / }} 本身不触发宿主 throw（转义面比报错面更宽，属刻意）', () => {
  for (const t of [...BENIGN, LONE_OPEN]) {
    assert.doesNotThrow(() => renderContextSections(asm([t])), `不应抛错：${t}`)
  }
})

test('⑥ 端到端：含 {{ 的记忆经注入后，宿主真函数可渲染', async () => {
  const listeners = new Map<string, (a: unknown, c: unknown, n: () => Promise<unknown>) => Promise<unknown>>()
  const ctx = {
    logger: { info: () => {}, warn: () => {} },
    on(ev: string, fn: never) { listeners.set(ev, fn as never) },
  } as never

  // 记忆真源（含用户 docker 命令原文）——模拟已沉淀进认知图的节点
  const preview = "docker inspect --format '{{.Architecture}}' 查看镜像架构"
  const mdcg = {
    isReady: () => true,
    async timeline() { return { count: 1, limit: 4, items: [{ id: 'n1', layer: 'contextual', start: 1, end: 2, preview }] } },
  } as never

  installMemoryHooks(ctx, mdcg, {
    userMessage: true,
    assistantMessage: false,
    toolResult: false,
    importance: 0.6,
    autoRecall: true,
    autoRecallLimit: 4,
    desensitize: true,
  })

  const handler = listeners.get('system-prompt/assemble')
  assert.ok(handler, '应注册 system-prompt/assemble 监听')

  const assembly = { contexts: [] as Array<{ name: string; text: string }>, variables: {} }
  await handler(assembly, ctx, async () => undefined)

  const injected = assembly.contexts.find((c) => c.name === 'lingshu:auto-recall')
  assert.ok(injected, '应注入 lingshu:auto-recall context')
  assert.ok(!injected.text.includes('{{'), '注入文本不得含裸 {{')
  assert.ok(injected.text.includes('Architecture'), '注入文本应保留记忆可辨内容')

  // 端到端：宿主真函数消费该注入面不抛错
  assert.doesNotThrow(() => renderContextSnapshot(assembly))
  assert.ok(renderContextSnapshot(assembly).includes('【灵枢最近记忆】'))

  // 对照：同一份注入面若不转义（模拟修复前），宿主必抛 → 证明转义是必需的
  const raw = { contexts: [{ name: 'lingshu:auto-recall', text: `【灵枢最近记忆】\n- [contextual] ${preview}` }], variables: {} }
  assert.throws(() => renderContextSnapshot(raw), /malformed prompt variable reference/)
})
