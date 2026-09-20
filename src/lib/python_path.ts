/**
 * python_path.ts —— Python 解释器的**平台感知**解析（issue #19）
 *
 * 要解决的问题（首次安装即失效，且不自愈）
 * ------------------------------------------------
 * 解释器默认值此前是**字面量 `'python'`**。Linux/macOS 按 PEP 394 只要求提供
 * `python3`——发行版默认状态就是这样，不是用户把环境装坏了。于是 `spawn('python')`
 * 抛 `ENOENT`，桥重试 8 次后进入 failed 终态：插件看起来装好了，工具不注册、
 * 记忆只读（`guest`）、必须重启 DSH 才会再试一次。同时日志被
 * `灵枢调用超时（60000ms）：initialize` 刷屏，把人引向「超时/性能」的错误方向，
 * 而第一因是更早一行不起眼的 `spawn … ENOENT`。
 * Windows 上 `python` 通常存在，所以该缺陷只在作者机器之外暴露。
 *
 * 解析顺序（高 → 低）
 * ------------------------------------------------
 *   ① `config.python` —— 用户显式配置，**原样尊重**（本模块不介入）
 *   ② env `MDCG_PYTHON` —— 容器 / CI 固定解释器；命名风格与既有
 *      `MDCG_ROOT` / `MDCG_CHILD_CWD` 一致
 *   ③ 平台默认：`win32` → `python`（**逐字节保持既有行为**）；其它 → `python3`
 *
 * 边界（诚实声明，勿据此扩大承诺）
 * ------------------------------------------------
 * - **不做** PATH 扫描式候选回退（`python3` → `python3.12` → `python` 取首个存在）：
 *   隐式行为在跨平台/多环境（conda、pyenv、WSL）下难以预测，且失败模式从
 *   「明确 ENOENT」退化为「悄悄选了另一个解释器」。解释器名特殊时请显式配置
 *   或设 `MDCG_PYTHON`。
 * - md_cg 侧**不挑** Python 版本：只要存在解释器即可（issue 复现方实测 conda 的
 *   `python3.12` 亦正常握手）。
 * - 本模块只**解析名字**，不校验可执行文件是否真的存在（校验属调用方职责，
 *   且 `stat` 结果会被 PATH/沙箱差异推翻）。
 */

/** 解释器覆盖的环境变量名（与 MDCG_ROOT 等同风格，便于容器固定）。 */
export const PYTHON_ENV_VAR = 'MDCG_PYTHON'

/**
 * 解析默认 Python 解释器（issue #19）。
 *
 * 参数刻意做成**可注入**（platform / env）而非直接读全局：默认值此前写死导致的
 * 正是「不可测 → 只在作者机器上成立」，注入后回归测试可在任意平台断言三分支。
 */
export function defaultPython(
  platform: string = process.platform,
  env: Readonly<Record<string, string | undefined>> = process.env,
): string {
  const explicit = (env[PYTHON_ENV_VAR] ?? '').trim()
  if (explicit) return explicit
  return platform === 'win32' ? 'python' : 'python3'
}

/** 自检命令文案（按平台给出**可照抄**的写法，issue #19 影响面第 4 条）。 */
export function selfCheckCommand(python: string = defaultPython()): string {
  return `${python} -m md_cg.mcp_server`
}

/**
 * spawn 失败（ENOENT）时的修复指引。
 *
 * 为什么值得单列一条日志：该缺陷的原始日志把「解释器名不匹配」伪装成
 * 「调用超时」，用户按超时方向排查只会浪费一轮；把成因与三条修法写在
 * **同一行**，可诊断性直接闭环。
 */
export function explainMissingPython(python: string): string {
  return `解释器「${python}」不可执行（ENOENT）。Linux/macOS 发行版按 PEP 394 只提供 `
    + 'python3（这是默认状态，不是环境损坏）。修法（任一）：'
    + "① cordis.yml 的 config.python 设为 'python3'（优先级最高）；"
    + '② 设环境变量 MDCG_PYTHON=python3（容器/CI 推荐）；'
    + '③ 确认 python3 在 PATH 中（which python3）。改完需重启 DSH。'
}

export default { defaultPython, selfCheckCommand, explainMissingPython, PYTHON_ENV_VAR }
