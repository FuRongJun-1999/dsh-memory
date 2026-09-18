# 缺陷与修正：pos_check 把「相邻符号的注释」误报为本符号位置错误（BAD_POS 虚高）

- 提出时间：2026-09-19 03:0x（环二第 542 轮）
- 处置：编外（本侧）自检 → 修正判据与基线 → 复测 → 提交本说明
- 状态：待编外复核（Zero-Trust）。

## 1. 缺陷

`pos_check.py`（注释位置自检）对每个符号从 `first`（装饰器行/定义行）**往上扫 3 行**，只要扫到
`# 生效条件：` 且 `idx+1 < first` 就记 `bad`。但紧邻符号的版式是
`mark, def A, mark, def B` —— 检查 B 时会扫到 **A 的注释**，于是被误判为
`ABOVE_DECORATOR/GAP`。

实测：`task/iter-reach-c2` 报 `bad=4`；而按「只认属于本符号的两个合法锚点」全库扫描
（紧贴 `def/class` 行上方 `node.lineno-2`，或装饰器上方 `first-2`），
发布线上 legacy 位置标记数 = **0** —— 即这 4 条全是误报。

另：`changed` 列表原用 `git diff main <branch>`，而本地 `main` 可能落后发布线几十个提交
（工作树陈旧），会把大量与本次候选无关的文件也纳入检查，放大误报面。

## 2. 修正（`C:\\Users\\FuRongJun\\.mdcg\\_coord\\pos_check.py`）

1. 只认两个合法锚点：`node.lineno-2`（紧贴定义行上方）与 `first-2`（装饰器上方）；
   其它位置出现的注释属于**相邻符号**，不计入本符号判定。
2. 基线改用 `origin/main`（与 collect_files2 / unit_review / apply_batch 同口径）。

## 3. 实测

- 修正后 `pos_check task/iter-reach-c2` → `BAD_POS 0`（修正前 `bad=4`）。
- 同轮新落地候选 `POS_CHECK ok=29 bad=0`、`ok=19 bad=0`，不再出现虚假 bad。

## 4. 边界

- 本修正只改**自检工具的判据**，不影响落地判据（内部独立复核 ACCEPT ∧ 零删除 ∧ 干净树回归绿）。
- 「合法锚点」两个位置都合规：规范位置在装饰器之下；装饰器之上是历史位置，
  现有语料已无此类（实测 0），新写入一律规范位置。
