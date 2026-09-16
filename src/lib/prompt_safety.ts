/**
 * prompt_safety.ts · 注入边界文本安全（宿主严格模板的转义）
 *
 * ── 根因（issue #16，2026-09-16）────────────────────────────────────────
 * dsh 宿主 `@deepseek-ai/dsh-system-prompt` 的 `interpolate()` 会对**每个
 * section / context** 文本做严格 `{{variable}}` 插值，且**四类一律 throw**：
 *   ① `{{` 之后能找到 `}}` 但不成简单组（GROUP_AT = /^\{\{([^{}]*)\}\}/ 不匹配）
 *   ② 组成立但名不匹配 /^[a-z][a-z0-9_]*$/（如 `{{.Architecture}}`）
 *   ③ 名合法但未注册（如 `{{name}}`）
 *   ④ 已注册但值为 undefined
 * `renderContextSections()` 逐 context 调用它，throw 直接冒泡到
 * `system-prompt/assemble` → **该轮请求整体失败**。
 *
 * ── 伤害路径 ───────────────────────────────────────────────────────────
 * 自动记忆把用户命令原样沉淀（如 `docker inspect --format '{{.Architecture}}'`）
 * → auto-recall 把含裸 `{{` 的预览推入 `assembly.contexts`
 * → 宿主每轮 assemble 必抛 → **会话永久不可用**（记忆永久在库，非偶发故障）。
 *
 * ── 处置：为何只在注入边界转义，不在写入侧 ────────────────────────────
 *   ① 记忆真源必须保真：`{{.Architecture}}` 是用户命令原文，写入侧转义会
 *      不可逆失真，且 cg(op=read) / 工具面 / 检索都依赖原文（= 污染真源）；
 *   ② 伤害面就是「注入到 prompt 的文本」，在注入边界处理即**最小充分**；
 *   ③ 与写入侧 desensitize 不冲突：脱敏是**隐私**要求（不许落盘），
 *      转义是**渲染安全**要求（落盘保真、渲染时规避）——层次不同。
 *
 * ── 转义策略：确保文本中不出现连续两个 `{` ────────────────────────────
 * 依据（宿主源码 `lib/index.js:109-116`）：`interpolate` 以
 * `text.indexOf("{{")` 为**唯一扫描锚点**；破坏 `{{` 序列后循环不进入，
 * 文本走 `text.slice(last)` 原样返回。
 *   · `}}` 无需处理——它只在 `{{` 成组时参与解析，锚点已破即无意义；
 *   · 逐对打断（而非 `split('{{').join(...)`）：后者对 `{{{a}}}` 会产出
 *     `{ {{a}}}`——新锚点仍在（相邻 `{` 重新合成），不幂等也不安全；
 *   · 跨 context 拼接安全：`joinContextSections` 以 `"\n\n"` 分隔并带固定
 *     前缀（`lib/index.js:85-87`，前缀以 `.` 结尾），边界不会合成新 `{{`；
 *   · 为何不用零宽字符：显示上「看起来一样」但复制会带入不可见字符
 *     （终端粘贴即出错）——诚实性优先，宁可让改写可见。
 *
 * 幂等：结果中不存在 `{{`，重复调用结果不变。
 * 边界：本函数只服务**注入到宿主 prompt 的文本**；记忆真源与工具返回原文
 *       一律不动（工具结果不进 assembly 插值面）。
 */

/** 宿主严格模板的扫描锚点。 */
const TEMPLATE_OPEN = '{{'

/**
 * 把文本中每一对相邻的 `{` 打断（插入半角空格），使其不再包含 `{{`。
 *
 * 不含 `{{` 的文本**原样返回**（零改写，保真）。
 * 例：`{{.Architecture}}` → `{ {.Architecture}}`；`{{{a}}}` → `{ { {a}}}`。
 */
export function escapePromptBraces(text: string): string {
  if (!text.includes(TEMPLATE_OPEN)) return text
  let out = ''
  for (let i = 0; i < text.length; i++) {
    const ch = text.charAt(i)
    out += ch
    // 该 `{` 与下一个字符构成锚点 → 立即插入空格打断
    if (ch === '{' && text.charAt(i + 1) === '{') out += ' '
  }
  return out
}
