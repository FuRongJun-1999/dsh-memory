# issue50 · 半重复待定复核（forgetting 分支④ 结构性不可达）修复记录 v1.0

> **日期**：2026-10-01 ｜ **缺陷号**：issue50-a ｜ **被测面**：`<仓根>` **工作树（未提交）**——1 个已修改跟踪件（`md_cg/forgetting.py`）＋ 1 个未跟踪新守卫（`md_cg/test_i50a_half_dup_defer.py`）＋ 未跟踪 `.zcode/`（工作流草稿面，非本次产物）。
> **契约**：动态工作流 `dwfrun-4e2ef43d-…` 的 `args.contract`——「只加一行定点补丁：分支④ 判据删去 `and imp["score"] < IMPORTANCE_MIN`；其余六条分支的判据/顺序/文案与五个常量零改动；不得改断言迁就实现」。
>
> **证据分级（本报告不越界陈述）**：
> - **§一、§三**＝本次**读码实读**（行号以本次读码为准，**每处同时给出 `git HEAD`（修前）与工作树（修后）两个行号**，并给出 `git diff` 原文与前后 SHA256）。
> - **§二**＝**工作流采集**的修前复现腿（逐条转述其 payload / 观察 / 站点）。其中腿 1·2（改前误判 ACCEPT）**由本报告独立复跑**（§一.4）、腿 4 的扫描**由本报告等价补跑**（§一.6）、腿 5 的在役读数**由本报告复核并进一步拆解**（§一.5、§四.7）；其余腿本报告**未重跑**，只转述。
> - **修订说明（v1.0-r1，2026-10-01，按读者反馈）**：本稿为同一文件的第一版修订——补 §一.5（生产侧证据）、§一.6（腿 4 等价补跑）、§4.1 的逐条断言清单，更正 4 处行号/口径/算术错误（§1.2 文案行号、§4.6 分母、§4.9 网格算术、§4.7 数据根断定），并在 §4.3/§4.9 补出两处引用出处。凡**读数未变**，只补出处与口径，不改数字。
> - **§四**＝**每条数字均标出「本报告实跑」还是「工作流采集」**；本报告实跑的给出确切命令原文与读数。
> - **§五**＝独立复核（不同执行体）的判定、其自列边界，及**本报告能否复现其读数**（含一处**未复现**的分歧，如实列出）。
> - **§六**＝边界、未覆盖、与本轮**明确不修而留池**的面。
> - **硬边界遵守**：本报告只写本文件；未改源码；未 `git add/commit/push`；未改守卫一字；全部实验根为 `%TEMP%` 下的 `tempfile.mkdtemp`（已清理）；**本报告不含任何明文凭据**。本报告**未跑**容器两栈（§4.8 给出理由），**未做**灵枢记忆归档（工作纪律第 16 条）——显式声明，非静默跳过。

---

## 一、缺陷定义与真实站点

### 1.1 缺陷定义

主动遗忘闸门 `md_cg/forgetting.py::assess` 的裁决链里，第 ④ 条分支（**半重复 → DEFER「待定复核」**）在本批修复前写作：

```python
elif red["max"] >= DUP_DROP and imp["score"] < IMPORTANCE_MIN:
```

该合取的第二个合项**在用户消息通道上结构性不可达**，于是整条分支从未被进入——半重复（`dup∈[0.60,0.85)`）的内容不是走「待定复核」，而是掉进第 ⑤ 条分支判 **ACCEPT** 直接落库。

**缺陷性质＝静默错误裁决，不是崩溃**：不抛异常、不留 ERROR、留痕写得整整齐齐（`verdict=ACCEPT`、`reason='重要度 0.60≥0.3'`），只是「本应存在的第三种输出」被静默吃掉。可观测后果＝`_forgetting.jsonl` 的 **DEFER 计数为 0**——本该是「变更确认」输入端的那条回路从不产生输入。⚠ **适用范围以 §1.5 的生产侧读数为准**：不是「没有半重复写入到达闸门」，而是**到达过 8 次、全被判 ACCEPT**；「恒为 0」仅对 `external_surprising`（user 通道）且 `hint≥0.30` 的调用成立，对 `role=assistant` 或 `hint<0.30` 的调用不成立（§1.3）。

### 1.2 真实站点（修前 / 修后双行号）

| 面 | 修前（`git HEAD` = `4383e3fd`） | 修后（工作树） | 位移原因 |
|---|---|---|---|
| **判据本体（唯一行为改动）** | `md_cg/forgetting.py:318` `elif red["max"] >= DUP_DROP and imp["score"] < IMPORTANCE_MIN:` | `md_cg/forgetting.py:329` `elif red["max"] >= DUP_DROP:` | 上方 docstring 增 11 行（`+11`）⇒ 其后整段下移 11 行 |
| 分支④ 的 reason 文案 | `:319-321`（3 行：`:319` `verdict, why = "DEFER", (f"半重复 …`；`:320` `f" 且重要度 {imp['score']:.2f}<{IMPORTANCE_MIN}"`；`:321` `f"（待定复核）")`） | `:330-332`（3 行，同构；中间行换成 `f" 且未触发不可遗忘保护"`） | 两侧**各 3 行**（与 §3.2 的 diff hunk `@@ -315,9 +326,9 @@` 两侧行数相等一致）；文案由「且重要度 x<0.3」改为「且未触发不可遗忘保护」 |
| `assess` 的 CCG 生效条件注 | `:239`（注里写「否则 `red["max"]≥DUP_DROP 且 imp["score"]<IMPORTANCE_MIN`→DEFER」） | `:239`（改为「否则 `red["max"]≥DUP_DROP`→"DEFER"（**与 imp 无关**）」） | 同文件单行改写，**该文件该处无净行数变化**（下一行仍是 `def assess`） |
| 模块 docstring 裁决序第 4 条 | `:36` `4) 半重复 且 不重要       → DEFER` | `:36` `4) 半重复 且 未触发保护   → DEFER ← 与重要度无关：半重复是「变更确认」的输入端` | 单行改写 |
| `assess` docstring 的 issue50-a 段 | **无** | `:265-274`（新增 11 行：缺陷成因 + 处置 + 「保护面零回归」依据） | 新增段 |

**机理三件套（都在同一文件，均本轮零改动）**：
- `:68-69` `SOURCE_WEIGHT["external_surprising"] = 1.00`；
- `:74` `EXTERNAL_ROLES = ("user",)`（⇒ 用户消息的来源类别恒为 `external_surprising`）；
- `:224-236` 启发式 `importance_score`：`s = 0.5*novelty + 0.3*SOURCE_WEIGHT[kind] + 0.2*lf`。

⇒ 对 `role="user"`：`s = 0.5·novelty + 0.30 + 0.2·lf ≥ 0.30`，而 `:61 IMPORTANCE_MIN = 0.30`、且比较用**严格 `<`**（`:318`）⇒ 第二个合项**恒假**，分支④ 恒不可达。（唯一缺口是 `novelty=1` 且 `lf=0` 时 `s=0.30` 恰等于阈值——`0.30 < 0.30` 仍为假。）

**插件侧同源口径（读码复核，未改）**：`src/index.ts:168` `importance: z.number().default(0.6)` → `src/hooks.ts:479-482` `memorize('user', (g) => g.remember(safe, { role: 'user', …, importance: opts.importance, … }))`；跨进程入口 `md_cg/mcp_server.py:2932` `importance_hint=a.get("importance")`。⇒ **插件缺省口径**下用户消息带 `hint=0.60 ≥ 0.30`，同样被合取挡住。
⚠ **证据边界（不越界）**：上面只能支撑「缺省值是 0.6」，**支撑不了**「真实入路都按 0.6 走」——`importance` 是用户可配项（`src/index.ts:168` 的 schema 允许改），且插件 TS 侧本报告只读码、**未跑测试、未重编译**（§六.2）。上文 §1.5 给出的 8 行在役留痕其 `importance.from="hint"` 且 `score=0.6`，是「实际发生过按 0.6 写入」的生产侧支持，但仍不构成「所有用户消息都走 0.6」。

### 1.3 精确的适用面（**不是**全局死码）

工作流腿 4 的反例探针（本报告未重跑，转述）表明：`role="assistant"`（`self_generated`，权重 0.50）且 `hint=None`、`dup=0.8085`、短内容时 `imp=0.2948<0.30` ⇒ 旧④ **可达**；`role=None`（`unknown`，0.60）时 `imp=0.3247` 仍 ACCEPT。另有独立复核的全组合扫描佐证：`hint=0.1` 时旧④ 命中、`hint=None` 的子网格旧④ **0 命中**（该扫描的网格口径与算术更正见 §4.9）。

⇒ 准确表述是：**「结构性不可达」只对 `external_surprising`（`role="user"`）来源、以及任何 `hint ≥ 0.30` 的调用成立**——而这恰是缺陷所指的「用户消息＝变更确认输入端」。本报告 §六 不把它写成「全局死代码」。

### 1.4 本报告实跑的现场复现（独立于采集腿的等价复现）

命令（脚本落 `%TEMP%/i50a_probe_report.py`，隔离 `tempfile.mkdtemp` 合成库，跑完已删）：

```
python -X utf8 %TEMP%\i50a_probe_report.py
```

读数（原文照录；`改前`＝把分支④ 合取加回当前源码后 `exec` 出的等价改写，非 git HEAD 全文）：

```
-- hint=0.60（插件缺省口径）
   改前: ACCEPT | 重要度 0.60≥0.3 | dup=0.7302 | imp=0.6(hint)
   现行: DEFER | 半重复 0.73∈[0.6,0.85) 且未触发不可遗忘保护（待定复核） | dup=0.7302 | imp=0.6(hint)
   判据面 kind=external_surprising novelty=0.2698
-- hint=None（启发式）
   改前: ACCEPT | 重要度 0.63≥0.3 | dup=0.7302 | imp=0.6349(heuristic)
   现行: DEFER | 半重复 0.73∈[0.6,0.85) 且未触发不可遗忘保护（待定复核） | dup=0.7302 | imp=0.6349(heuristic)
   判据面 kind=external_surprising novelty=0.2698
```

**两路（显式 hint 与启发式）都复现了缺陷现场与修复结果**：同一输入、同一重复度 `dup=0.7302`，改前 ACCEPT / 现行 DEFER；`importance.from` 两枝一致（未漂移）。

### 1.5 生产侧证据：在役留痕里「本应 DEFER 却被 ACCEPT 吃掉」的 8 行（**本报告实跑**）

**命令**（只读打开在役留痕，未写入）：

```
python -X utf8 -c "import io,json,collections; rows=[json.loads(l) for l in io.open(r'<在役库根>\_forgetting.jsonl',encoding='utf-8',errors='replace') if l.strip()]; …"
```

留痕记录**不存 `role` 字段**（字段集合＝`t / node_id / layer / verdict / reason / importance / entropy / actor`），但每条带 `entropy.source_kind`——它是 `role` 的纯函数投影（`forgetting.py:90-102`），故可等价替代 `role` 做通道归因。交叉表（215 行）：

| `entropy.source_kind` | `dup<0.60` | `dup∈[0.60,0.85)` | `dup≥0.85` | 合计 |
|---|---|---|---|---|
| `external_surprising`（＝`role="user"` 通道） | ACCEPT 170 | **ACCEPT 8** | MERGE 14 | 192 |
| `unknown` | ACCEPT 16 | 0 | 0 | 16 |
| `internal_deterministic` | ACCEPT 7 | 0 | 0 | 7 |

⇒ **8 行**是 `external_surprising`、`dup∈[0.60,0.85)`（半重复）、`verdict=ACCEPT`——正是**新判据下应判 DEFER 的那一类**：

| `node_id` | layer | `entropy.duplicate_ratio` | `reason` | `importance` |
|---|---|---|---|---|
| `mem_1789124989698` | contextual | 0.6667 | 重要度 0.60≥0.3 | `{'score': 0.6, 'from': 'hint'}` |
| `mem_1789142956583` | contextual | 0.8182 | 重要度 0.60≥0.3 | `{'score': 0.6, 'from': 'hint'}` |
| `mem_1789143039561` | contextual | 0.6667 | 重要度 0.60≥0.3 | `{'score': 0.6, 'from': 'hint'}` |
| `mem_1789274945060` | contextual | 0.6538 | 重要度 0.60≥0.3 | `{'score': 0.6, 'from': 'hint'}` |
| `mem_1789309358900` | contextual | 0.6458 | 重要度 0.60≥0.3 | `{'score': 0.6, 'from': 'hint'}` |
| `mem_1789559591422` | contextual | 0.7000 | 重要度 0.60≥0.3 | `{'score': 0.6, 'from': 'hint'}` |

（上表为本次输出**逐行照录**的 6 行；计数语句给出这一类合计 **8 行**，另 2 行的 `node_id`/`dup` **未在本报告的输出截断内**，故不在此表列出——**本报告不凭计数补造未打印的字段**。）

**这一读数把「DEFER 计数为 0」的两种解释分开了**：不是「从来没有半重复的用户写入到达闸门」，而是**到达过 8 次、全部被判 ACCEPT**（`importance.from="hint", score=0.6` 即插件缺省入路）。§1.1 的「DEFER 计数恒为 0」据此**限定其范围**：对 `external_surprising`（user）通道、`hint≥0.30` 的调用成立；对 `role=assistant` 或 `hint<0.30` 的调用**不成立**（§1.3 已给反例，两者不冲突）。

### 1.6 腿 4 的等价补跑：8 个重复度档 → dup / novelty / imp 的逐一对应（**本报告实跑**）

工作流腿 4 的原 payload 列了 8 个 `duplicate_ratio` 档（0.60/0.65/0.70/0.73/0.76/0.80/0.84/0.849），观察却只给 7 个 `imp` 值且未写哪一档被排除。本报告**用自建内容族**（`BASE`/`FILL` 各 600 互异汉字，按「前 k 字取 BASE」线性调覆盖面，`forgetting.py` 的 bigram 覆盖率构造）**等价补跑**同一扫描（`role="user"`、`hint=None`、隔离 `tempfile` 库；`改前`＝把分支④ 合取加回后 `exec` 的等价改写）：

| 目标 dup | 实测 dup | novelty | imp（heuristic） | 改前 verdict | 现行 verdict |
|---|---|---|---|---|---|
| 0.600 | **0.5994**（< DUP_DROP，**出窗口**） | 0.4006 | 0.7003 | ACCEPT（走 ① 保护） | ACCEPT |
| 0.650 | 0.6494 | 0.3506 | 0.6753 | ACCEPT（走 ⑤） | **DEFER** |
| 0.700 | 0.6995 | 0.3005 | 0.6502 | ACCEPT（走 ⑤） | **DEFER** |
| 0.730 | 0.7302 | 0.2698 | 0.6349 | ACCEPT（走 ⑤） | **DEFER** |
| 0.760 | 0.7593 | 0.2407 | 0.6203 | ACCEPT（走 ⑤） | **DEFER** |
| 0.800 | 0.7997 | 0.2003 | 0.6001 | ACCEPT（走 ⑤） | **DEFER** |
| 0.840 | 0.8401 | 0.1599 | 0.5799 | ACCEPT（走 ⑤） | **DEFER** |
| 0.849 | 0.8498 | 0.1502 | 0.5751 | ACCEPT（走 ⑤） | **DEFER** |

**⇒ 「8 档 → 窗口内 7 个样本」的机制由此得解**：0.600 那档因内容离散（bigram 覆盖率不是连续量）**实测落在 0.5994 < `DUP_DROP`**，被窗口排除；其余 7 档全部落在 `[0.60,0.85)`。窗口内 `imp` 随 dup 单调下降，最小值 0.5751（dup→0.85 端）**仍 ≥ 0.30**，与腿 4 的断言「窗口内 imp 下界 0.45 ≥ 0.30」方向一致；**理论下界** `inf = 0.30 + 0.5·(1−0.85) = 0.375` 与本表不矛盾（本表 `lf=1.0`，故落在 0.375 之上）。
⚠ **本表不是腿 4 的复现**：内容族不同，故 `imp` 的具体数值与腿 4 的 `[0.5716,…,0.4504]` **不同**（腿 4 的内容更短、`lf≈0.38`）。本报告补的是**同一结论的独立读数**与**8→7 的解释**，不声称复现其数值。

---

## 二、修前现场（工作流采集的复现腿，逐条）

> **谁跑的**：本表全部 7 条腿＝本工作流采集（改动前/隔离对拍树上采集）；本报告**未重跑**这 7 条腿本身，其中腿 1·2 的等价复现见 §一.4，腿 4 的等价补跑见 §一.6，腿 5 的在役读数复核与构成拆解见 §一.5 / §四.7。
> **崩溃点声明**：本缺陷**无崩溃腿**——7 条腿全部**无异常抛出**，「缺陷」表现为**静默错误裁决**（独立复核亦就此声明：「该缺陷无『崩溃腿』（缺陷本体是结构性不可达分支而非崩溃）」）；唯一的异常出现在**修复后的连带红项**里（§四.5 的 H4 `TypeError`），那是测试面断言，不是产品面崩溃。

| # | 腿 | payload（确切输入） | 观察（修前） | 站点（修前行号） | 谁跑的 |
|---|---|---|---|---|---|
| 1 | 构造期装载 · assess 直调 | 隔离临时库 + 1 个 contextual 种子节点；`assess(content=种子正文+31 个唯一字符后缀, layer='contextual', role='user', importance_hint=0.60, node_id=None)`；实测 `duplicate_ratio=0.7262`（半重复，∈[0.60,0.85)） | **无异常**。`verdict=ACCEPT`（新判据应为 DEFER）；`reason='重要度 0.60≥0.3'`；`importance={'score':0.6000,'from':'hint'}`；命中的是分支 ⑤（`:322-323`），分支 ④（`:318-321`）**从未被进入** | `forgetting.py:318-321`（分支④ 合取 `and imp["score"] < IMPORTANCE_MIN`） | 采集 |
| 2 | 构造期装载 · 启发式路径 | 同腿 1 库，`importance_hint=None`，`dup≈0.73` | **无异常**。`verdict=ACCEPT`；`reason='重要度 0.52≥0.3'`；`importance={'score':0.5229,'from':'heuristic'}`；`entropy.source_kind='external_surprising'`。机理：启发式第二项恒 `0.3*1.00=0.30=IMPORTANCE_MIN`，`novelty≥0`、`lf≥0` ⇒ `imp≥0.30` 恒成立（比较用严格 `<`）⇒ ④ 的合取恒假 | `forgetting.py:318-321` + `:68-73` + `:74` + `:224-236` | 采集 |
| 3 | 重放面 · `remember_gated` 端到端（插件用户消息真实入路） | `remember_gated(node_id='n_user_1', layer='contextual', role='user', importance=0.60)`，`dup≈0.73`；载荷来源＝插件真实缺省（`src/hooks.ts:479-482` + `src/index.ts:168`；跨进程同源 `mcp_server.py:2932`） | **无异常**。`verdict=ACCEPT`；`gate.reason='重要度 0.60≥0.3'`；**节点落盘=True（节点数 1→2，半重复内容成为新节点）**；`_forgetting.jsonl={'ACCEPT':1}`；`writelimit.check` 返回 `None`（未拦截）⇒ 确由 `forgetting.assess` 裁决 | `forgetting.py:318-321`（经 `mdcos.py:3667-3669` 调用 `assess`） | 采集 |
| 4 | 结构性扫描 · ④ 窗口内 imp 下界 | `assess(role='user', importance_hint=None)`，`duplicate_ratio` 扫 0.60/0.65/0.70/0.73/0.76/0.80/0.84/0.849 | 窗口内 7 个样本 `imp=[0.5716,0.5384,0.5229,0.5007,0.4767,0.4572,0.4504]`，最小 **0.4504 ≥ 0.30**；按「`verdict==DEFER` 且 reason 含半重复」机械判定，分支④ 命中集合 **= []（空）⇒ 不可达**。理论下界 `inf = 0.30 + 0.5*(1-0.85) = 0.375`。**反例探针**：`role=assistant`（`self_generated` 0.50）`hint=None, dup=0.8085` 短内容 → `imp=0.2948<0.30` → 旧④ 可达；`role=None`（`unknown`）`dup=0.8085` → `imp=0.3247` 仍 ACCEPT。**本报告等价补跑见 §1.6**：8 个目标档里 0.600 那档实测 0.5994 出窗口 ⇒ 窗口内恰 7 个样本（本条腿「8 档→7 样本」由此得解）；但 §1.6 的 `imp` 数值出自本报告自建的内容族，**与腿 4 的 `[0.5716,…,0.4504]` 不同**，本报告不复现其数值 | `forgetting.py:318`、`:61`、`:94-95`、`:68-73` | 采集（§1.6 为本报告补跑） |
| 5 | 留痕面 · `_forgetting.jsonl` DEFER 计数 | 同一隔离库连续 6 次 `remember_gated(role='user', importance=0.60)`，`dup` 依次 0.6630/0.7176/0.7262/0.7625/0.8026/0.8356（后缀字符池互不相交，避免人造高覆盖） | **无异常**。逐条 `verdict` 全为 ACCEPT；`forgetting.summary(cg)={'total':6,'by_verdict':{'ACCEPT':6}}` ⇒ **DEFER 计数=0、DROP 计数=0**。与在役库 215 条留痕（ACCEPT 201 / MERGE 14 / DROP 0 / DEFER 0）同形 | `forgetting.py:318-321` | 采集（在役库读数本报告已独立复核，见 §四.7） |
| 6 | 改前/改后对拍（隔离副本 A=原样 / B=打补丁） | 同一脚本同一隔离模板跑两遍，仅以 `--repo` 切枝；8 个用例：全新 / dup≈0.73 / dup≈0.76 / dup≈0.96 / 精确重复 / tool-output dup≈0.84 / hint=0.9 半重复 / hint=0.60 半重复。A 枝先验证：8 行读数与真仓 pre 读数**逐行完全一致**（副本未引入偏差） | 逐行：① 全新 user 不变；② dup≈0.73 **ACCEPT→DEFER**；③ dup≈0.76 **ACCEPT→DEFER**；④ dup≈0.96 MERGE 不变；⑤ 精确重复 MERGE 不变；⑥ tool-output dup≈0.84 DROP 不变；⑦ hint=0.9 半重复 ACCEPT 不变；⑧ hint=0.60 半重复 **ACCEPT→DEFER**。汇总：**变 3 行**（全部满足 `dup∈[0.60,0.85)` 且非保护、ACCEPT→DEFER）、不变 5 行、越界 **0** 行 ⇒ 不动面判据成立（`compare.py` rc=0）；`importance.from` 8 行两枝一致 | `forgetting.py:318-321`（对拍中唯一被改动的行） | 采集 |
| 7 | 回归面（真仓全量 + 双枝对照） | 未改动真仓（HEAD `4383e3fd`）跑 `python scripts/run_tests.py` 全量；再跑 P9 / P9c / writelimit / p2_mcp 四项；再在隔离枝 A/B 复跑同四项 + 10 个闸门邻接模块；另做定点变异自证 | ① 未改动树全量 **299/299 通过、5 跳过、rc=0**；② 未改动树四守卫逐项 rc=0（P9 37/0、P9c 31/0、writelimit 全过、p2_mcp 64/0）；③ 隔离枝：repoA 四项 rc=0；**repoB（打补丁）`test_writelimit rc=1`**；④ 转红断言＝`md_cg/test_writelimit.py:123-127` 的 E1（假定「半重复→ACCEPT」）；⑤ 闸门邻接 10 模块 A/B rc 全一致，唯一差异项即 `test_writelimit`；`test_b1b2_write_face` 两枝同 rc=1 系拷贝枝缺 `scripts/linkref_backfill.py`（`FileNotFoundError`），属**拷贝伪失败**非补丁所致；⑥ 定点变异：真仓 4 红（A×2+B×2）rc=1；打补丁枝 0 红 rc=0；把分支④ 条件改回合取 → 4 红；把 `DUP_DROP` 改成 0.9 → 6 红。**【口径注：腿 7⑥ 与 §4.2 不是同一套用例集】** 本条的变异跑在**工作流的临时库探针**上（用例面＝A×2 + B×2 共 4 例，见其「真仓 4 红（A×2+B×2）」原文），而 §4.2 跑的是**26 断言守卫** `md_cg/test_i50a_half_dup_defer.py --mutate`（用例面＝F/A/B/C/E 五组 26 条）。**同一变异在两套不同用例集上的红项数必然不同**：改回合取 4（腿 7⑥）vs 6（§4.2）、`DUP_DROP→0.9` 6（腿 7⑥）vs 9（§4.2）。两组数各自自洽，**分母不同**，不是互相否证 | `forgetting.py:318-321`；转红断言 `test_writelimit.py:125-127` | 采集 |

---

## 三、修法契约与落点

### 3.1 契约（冻结，只此一条行为改动）

> 分支④ 判据删去 `and imp["score"] < IMPORTANCE_MIN`，半重复（且未触发保护）一律 DEFER，**与重要度解耦**；分支顺序与其余六条分支的判据/文案、五个判据常量、`writelimit.py`、`mdcos.remember_gated` 的落库动作**均不动**；**不得改断言迁就实现**。

⚠ **摘录范围更正（补读者所指的出处）**：上面这段只是工作流契约的**补丁面**。§4.3 引用的那条**变异要求**（「`DUP_DROP` 改成 0.9 → B 组必红」）出自契约的**另一块**——本批交付物的 `baselineMode` / `mutationSummary`（其原文自述「契约指定」）。**v1.0 原稿把两者混在 §3.1 的现象里，使读者在 §3.1 找不到该条**，属本报告摘录不全；现已把出处标出，正文按实测回报保留（§4.3）。

### 3.2 `git diff` 实测（本报告实跑，原文照录）

```
$ git -C <仓根> diff --stat -- md_cg/forgetting.py
 md_cg/forgetting.py | 19 +++++++++++++++----
 1 file changed, 15 insertions(+), 4 deletions(-)
```

四处 hunk（唯一行为改动＝第一处）：

```diff
@@ -33,7 +33,7 @@            # 模块 docstring 裁决序
-    4) 半重复 且 不重要       → DEFER
+    4) 半重复 且 未触发保护   → DEFER ← 与重要度无关：半重复是「变更确认」的输入端
@@ -236,7 +236,7 @@          # assess 的 CCG 生效条件注（单行）
-… 否则 red["max"]≥DUP_DROP 且 imp["score"]<IMPORTANCE_MIN→"DEFER"；否则 …
+… 否则 red["max"]≥DUP_DROP→"DEFER"（**与 imp 无关**）；否则 …
@@ -261,6 +261,17 @@          # assess docstring 新增 issue50-a 段（+11 行）
+    issue50-a（2026-10-01）：分支 ④「半重复 → DEFER」此前写作
+    `red["max"] >= DUP_DROP and imp["score"] < IMPORTANCE_MIN`，**结构性不可达**：…
+    处置：**删去 `and imp["score"] < IMPORTANCE_MIN`**，…
@@ -315,9 +326,9 @@          # ★ 唯一行为改动 ★
-    elif red["max"] >= DUP_DROP and imp["score"] < IMPORTANCE_MIN:
+    elif red["max"] >= DUP_DROP:
         verdict, why = "DEFER", (f"半重复 {red['max']:.2f}∈[{DUP_DROP},{DUP_MERGE})"
-                                f" 且重要度 {imp['score']:.2f}<{IMPORTANCE_MIN}"
+                                f" 且未触发不可遗忘保护"
                                 f"（待定复核）")
```

**前后指纹（本报告实跑）**：

```
HEAD   sha256: 3022181b99888d70da58bd3ace2a094e98e428360b38f33a050f2c8518549caa   (49,838 B)
工作树 sha256: 94f1447c8b5da8ac496a650f97078f664a9422da1cadabad07592a9e62c035a8   (50,818 B)
```

（与工作流交付物声明的前 16 位 `3022181b99888d70…` / `94f1447c8b5da8ac…` 逐位一致。）

### 3.3 落点清单

| 落点 | 位置（工作树） | 性质 |
|---|---|---|
| 分支④ 判据 | `md_cg/forgetting.py:329` | **行为改动（唯一）** |
| 分支④ reason 文案 | `md_cg/forgetting.py:330-332` | 文案 |
| `assess` CCG 生效条件注 | `md_cg/forgetting.py:239` | 注释 |
| `assess` docstring issue50-a 段 | `md_cg/forgetting.py:265-274` | 注释 |
| 模块 docstring 裁决序第 4 条 | `md_cg/forgetting.py:36` | 注释 |
| 新守卫 | `md_cg/test_i50a_half_dup_defer.py`（408 行 / 19,464 B，未跟踪） | 守卫（26 断言 + 9 处定点变异） |

### 3.4 裁决序（修后，与修前逐条对照）

`① 重要度≥0.70 → ACCEPT（保护优先）` → `② internal_deterministic 且 dup≥0.60 → DROP` → `③ dup≥0.85 → MERGE` → **`④ dup≥0.60（未触发保护）→ DEFER`** → `⑤ 重要度≥0.30 → ACCEPT` → `⑥ 新信息≥0.15 → ACCEPT` → `⑦ 其余 → DEFER`。**顺序未变；④ 仍排在 ③ 之后、⑤ 之前，故「≥0.85 走 MERGE」「<0.60 走 ⑤/⑥」两端不受影响**（守卫 B 组钉死）。

**不动面（本轮零改动，逐项核）**：其余六条分支的判据与文案；五个常量 `DUP_MERGE=0.85 / DUP_DROP=0.60 / NOVELTY_MIN=0.15 / IMPORTANCE_MIN=0.30 / PROTECT_IMPORTANCE=0.70`（`forgetting.py:58-62`）；`md_cg/writelimit.py`；`mdcos.remember_gated` 的落库动作（`md_cg/mdcos.py:3667-3681`）。

---

## 四、验证数字

### 4.1 守卫（**本报告实跑**）

```
$ python -X utf8 -m md_cg.test_i50a_half_dup_defer
锚点自检：PASS（test_i50a_half_dup_defer.py；不以 git HEAD 为基线源）
… 26 条 PASS …
issue50-a 守卫：26 通过，0 失败      → 退出码 0
```

**断言数 26 / 通过 26 / 退出码 0**；分组计数 F 6 + A 8 + B 5 + C 3 + E 4 = 26（`test_i50a_half_dup_defer.py:236` `_GROUPS = (g_f, g_a, g_b, g_c, g_e)`，本报告读码核对一致）。

**⚠ 组序说明：没有 D 组**。守卫的分组函数元组是 `(g_f, g_a, g_b, g_c, g_e)`（`test_i50a_half_dup_defer.py:236`），字母从 C 直接跳到 E——`g_d` **不存在**（不是本报告漏列）；`--mutate` 的「删断言探针」也只操作 `g_a/g_b/g_e`（§5.1-4）。

**逐条断言清单**（`#` 为守卫内的断言编号；「位置」＝该断言 `ok(...)` 所在行，本报告读码所得）：

| # | 断言（守卫里的判据原文摘要） | 位置 |
|---|---|---|
| F1 | 全新内容 `dup<0.60` | `:132` |
| F2 | 边界下侧 `dup<0.60`（卡在 `DUP_DROP` 之下） | `:133` |
| F3 | 边界上侧 `dup∈[0.60,0.85)` | `:135` |
| F4 | 贴近 `DUP_MERGE` 仍 `∈[0.60,0.85)` | `:137` |
| F5 | 近重复 `dup≥0.85` | `:139` |
| F6 | 精确重复 `dup==1.0` | `:140` |
| A1 | 边界上侧 `dup=0.6074` + `hint=0.60` → DEFER | `:147` |
| A2 | `dup=0.7302` + `hint=0.60` → DEFER（改前走⑤误判 ACCEPT） | `:151` |
| A3 | `dup=0.7302` + `hint=None`（启发式 `0.6349≥0.30`）→ 仍 DEFER | `:155` |
| A4 | `dup=0.7609` + `hint=0.60` → DEFER | `:160` |
| A5 | `dup=0.8384`（贴近 `DUP_MERGE`）+ `hint=0.60` → DEFER | `:163` |
| A6 | 半重复 + `hint=0.9` → ACCEPT（① 保护优先不受本批影响） | `:167` |
| A7 | 保护优先分支的 `dedup_skipped` 仍非空 | `:169` |
| A8 | 分支④ 文案如实（含「半重复」「未触发不可遗忘保护」、不含「重要度」） | `:173` |
| B1 | `dup=0.9612≥0.85` → MERGE（③ 仍先于 ④，分支③ 文案原样） | `:182` |
| B2 | `dup=0.8998≥0.85` → MERGE | `:186` |
| B3 | 精确重复（`dup=1.0`）→ MERGE | `:189` |
| B4 | `dup=0.5994<0.60` → ACCEPT（④ 不外溢到 `DUP_DROP` 之下） | `:192` |
| B5 | 全新内容（`dup=0.0258`）→ ACCEPT | `:196` |
| C1 | `role=tool-output` + `dup=0.6074∈[0.60,0.85)` → DROP（② 先于 ④） | `:204` |
| C2 | 贴近 `DUP_MERGE` 仍 DROP，分支② 文案原样 | `:208` |
| C3 | 反向腿：`tool-output` 全新内容仍 ACCEPT（C 组不是恒判 DROP） | `:211` |
| E1 | ① 保护优先仍最先（`dup=0.96` + `hint=0.9` → ACCEPT，未被 ③ 抢走） | `:219` |
| E2 | ⑤ `重要度≥IMPORTANCE_MIN` → ACCEPT，文案原样 | `:223` |
| E3 | ⑥ `新信息≥NOVELTY_MIN` → ACCEPT，文案原样 | `:226` |
| E4 | 五个判据常量原样（本批不改任何常量值） | `:228` |

⇒ §4.2 与 §4.3 里出现的编号（A1–A5、A8、B4、C1、C2、E4…）**都可按本表回指到具体断言**。**A1–A8 与 §4.5 的 `test_writelimit` E1 不是同一编号体系**（前者是 issue50-a 守卫的 A 组，后者是 `md_cg/test_writelimit.py` 的 E 节断言）——两处同名不同源，阅读时以文件名区分。

### 4.2 定点变异自证（**本报告实跑**）

```
$ python -X utf8 -m md_cg.test_i50a_half_dup_defer --mutate
  未变异基线：红项=0
  变异「④ 分支加回重要度合取（改回缺陷形态）」→ 红项=6  命中预期
  变异「④ 分支整条删除」→ 红项=6  命中预期
  变异「③ 分支整条删除（≥0.85 不再 MERGE）」→ 红项=3  命中预期
  变异「① 保护分支失能（PROTECT_IMPORTANCE 抬到 1.1）」→ 红项=3  命中预期
  变异「DUP_DROP 抬到 0.9（契约指定；④ 窗口变空）」→ 红项=9  命中预期
  变异「DUP_DROP 降到 0.30（④ 的入口边界下移）」→ 红项=2  命中预期
  变异「DUP_MERGE 降到 0.60（③ 抢在 ④ 之前）」→ 红项=7  命中预期
  变异「IMPORTANCE_MIN 抬到 1.1（⑤ 失能）」→ 红项=2  命中预期
  变异「NOVELTY_MIN 抬到 1.1（⑥ 失能）」→ 红项=2  命中预期

定点变异自证：PASS（每处判据都有变异钉死，且红项数逐处吻合）   → 退出码 0
```

**9 处变异（4 源码 + 5 常量），红项数 6/6/3/3/9/2/7/2/2，未变异基线 0，退出码 0**。

### 4.3 契约变异「`DUP_DROP` 改成 0.9 → B 组必红」**实测不成立**（按实测回报）

契约指定「`DUP_DROP 改成 0.9 → B 组必红`」**不成立**：分支链 `①→②→③(0.85)→④` 中 ③ 在 ④ 之前，抬高 `DUP_DROP` 只把 ④ 的窗口变成**空集** ⇒ 受影响的是 **A 组**（半重复落回 ⑤→ACCEPT）与 **C 组**（tool-output 落回 ⑤），B 组两端（「≥0.85→MERGE」「<0.60→ACCEPT」）**都不动**——实测该变异红项 **9**（= A1-A5 + A8 + C1 + C2 + E4），**B 组 0 红**。为满足「`DUP_DROP` 常量必须能打红 B 组」的本意，补了反方向变异 `DUP_DROP→0.30`（④ 入口边界下移）→ 红项 **2**（B4 + E4）。⇒ 本报告实跑读数与上述逐处吻合（§4.2）。常量类变异红项数均含 E4（「五常量原样」断言）**+1**，属设计使然。

**出处与「本意」两句话的来路（补读者所指的出处）**：本条变异要求**不在** §3.1 所摘的补丁条款内，出自本批交付物的 `baselineMode` / `mutationSummary`——其中把该处变异标为「**契约指定**」，并在实测不符后写下「为满足『`DUP_DROP` 常量必须能打红 B 组』的**本意**，补了反方向变异 `DUP_DROP→0.30`」。本报告 §4.2 第 5 行（`DUP_DROP→0.9`，红 9）与第 6 行（`DUP_DROP→0.30`，红 2）就是这两条，**红项数由本报告实跑复核**（§4.2 原文照录）。⇒ 该「本意」是被补的**代理判据**，不是契约原文；「B 组必红」这一形式要求在 `DUP_DROP→0.9` 上确实打不出，本报告照实回报而不改成好看的说法。

### 4.4 锚点 fail-closed（**本报告实跑**）

**名词定义（v1.0 原稿缺，补读者所指）**——四个词全部来自新守卫 `md_cg/test_i50a_half_dup_defer.py`：

- **锚点自检**＝守卫运行前的自检：`main()`（`:392`）先调 `_anchor_check()`（`:316-330`），返回非空即打印 `ANCHOR-MISS …` 并 **`return 2`**（fail-closed）；默认模式与 `--mutate` 模式都先做这一步。
- **`_assess_src()`**（`:291-292`）＝`inspect.getsource(forgetting.assess)`，即**当前盘**上 `assess` 的源码（守卫明示**不以 `git HEAD` 为基线源**，`:42`/`:398`）。
- **`_anchor_check()`**（`:316-330`）＝对着该源码做三件事：① `_SRC_MUTATIONS` 的 4 个变异锚点字面量必须在位；② `_ANCHORS_BANNED`（缺陷形态合取 `and imp["score"] < IMPORTANCE_MIN`）**不得**出现在 `assess` 的可执行行里（`_code_face()` 剥掉 docstring/整行注释，`:295-313`）；③ `_ANCHORS_REQUIRED`（「半重复」「未触发不可遗忘保护」「待定复核」）必须出现。三条各产一条说明，返回**说明列表**。
- **`ANCHOR-MISS`**＝上述说明的打印前缀（`:357`），用于「实现改了却没同步变异表/文案」时**当场拒绝**而不是静默放行。

| 注入 | `_anchor_check()` 返回条数 | `main()` 返回码（退出码） |
|---|---|---|
| 把 `_assess_src` 换成**完全漂移**的源码 | **7 条**（4 条变异锚点缺失 + 3 条新文案锚点缺失） | `2`（打印 ANCHOR-MISS 后 fail-closed） |
| 把源码换成**缺陷形态回归**（合取改回 + 文案抹掉，本报告自建重建） | **4 条**（含「缺陷形态回归：assess 可执行行里仍有 `and imp["score"] < IMPORTANCE_MIN"`」） | `2` |
| **现状（不注入）** | **0 条**（本报告实跑 `len(_anchor_check())` = 0） | `0`（同 §4.1 的守卫退出码 0） |

（第三行的 `main()` 返回码 0 与 §4.1 的守卫退出码 0 是**同一次运行**的两个投影——避开 v1.0 用「由 §4.1 得 0」跨节借读数的写法。）

⚠ **一处未复现的分歧（如实列出）**：独立复核报告「把 `_assess_src` 换成缺陷形态源码后返回 **3** 条」。本报告实跑得到 **7** 条（完全漂移）/ **4** 条（我自建的缺陷形态重建）——**我无法重建出恰好 3 条的那个输入**。结论层面无分歧（fail-closed 都成立、都返回 2）；数字层面的差异源于「换了多少源码」，本报告只报我实测到的数。

### 4.5 既有断言冲突面：`md_cg/test_writelimit.py` 转红（**本报告复刻实跑**）

**稳定转红**（§4.6 稳定性分析）：`python -X utf8 -m md_cg.test_writelimit` → `AssertionError: [FAIL] E1 knowledge 不聚合不限流`，**退出码 1**。该断言原文（**未改一字**）：

```python
# md_cg/test_writelimit.py:122-127
writelimit._save(cg, {"sigs": {}, "rate": {}})   # 清状态隔离本节
r_k1 = _write("wl_k1", "知识条目甲乙丙丁1号", layer="knowledge")
r_k2 = _write("wl_k2", "知识条目甲乙丙丁2号", layer="knowledge")
check("E1 knowledge 不聚合不限流",
      r_k1["verdict"] == "ACCEPT" and r_k2["verdict"] == "ACCEPT",
      f"{r_k1.get('gate')}/{r_k2.get('gate')}")
```

E 节标题是「层豁免」，而合取式把「**半重复→ACCEPT**」当成了前提。本报告**复刻实跑**该节并与改前对拍（脚本落 `%TEMP%/i50a_e1_pairs.py`，隔离库）：

```
改前（分支④ 带重要度合取）: r_k1=ACCEPT | r_k2=ACCEPT | 重要度 0.42≥0.3                 | dup=0.7777777777777778
    E1 断言 (双 ACCEPT) -> True
改后（现行工作树）        : r_k1=ACCEPT | r_k2=DEFER  | 半重复 0.78∈[0.6,0.85) 且未触发不可遗忘保护（待定复核） | dup=0.7777777777777778
    E1 断言 (双 ACCEPT) -> False
```

⇒ **该红项确由本次修复引起（非环境抖动）**：两条载荷仅尾字不同，`second-write dup=0.7778 ∈ [0.60,0.85)`，`imp=0.4211`（启发式，`external_surprising`）；修复后判 DEFER，断言转红。

**同文件连带四处（含上文已单列的 E1）**：工作流那条「全量红项=4」是在**它自己的隔离副本**上把 `check()` 的 assert **降级为收集**（临时改写副本里的 `check()`，不动真仓文件、不改追踪面）后重跑该模块得到的；**本报告未做该降级**——真仓跑法下 `test_writelimit` 在 E1 处即 assert 中止，根本跑不到 H 组，故本报告改用复刻脚本 `%TEMP%/i50a_h_probe.py`（**复刻** E/H 两节的判据面，不 import 该测试模块）在隔离临时根上逐条实测（**本报告实跑**）：

| 断言 | 位置 | 本报告复刻读数 |
|---|---|---|
| E1 | `:125-127` | `False`（见上） |
| H1 `dry["groups"] >= 1 and dry["members"] >= 4` | `:168-169` | `False`（`groups=0 members=0`） |
| H3 「整理聚合」∈ m0.content and "wl_t1" ∈ … | `:177-178` | `False` |
| H4 `m1["frontmatter"]` | `:180-181` | **抛 `TypeError`**（`m1=None`，`NoneType` 不可下标） |

根因同上：H 组用 `MDCG_WRITELIMIT=0` 直造 5 条同构短骨架（`"巡检批次{i}收官记忆"`）期望全落盘，修复后**仅首条落盘**（本报告实测落盘节点= `['wl_t0']`，5 条里 1 条）；H2（节点总数不变）与 F/G/I 组不受影响（本报告实测 H2 = `True`，即 `2 → 2` 节点数不变）。**这四条断言本报告与工作流均未改**（契约：不许改断言迁就实现）。

**分母与口径对账（补读者所指）**：本处「四处」＝ E1/H1/H3/H4 四条**断言级**红项；工作流的「全量红项=4」是同一集合的另一记法（它在副本上收集全部红项）。两处**指向同一组**，不是两个不同读数。§六.1 的「唯一稳定红项」指的是**模块级**（`md_cg.test_writelimit` 一个模块 rc=1），与本处的断言级计数不冲突。

### 4.6 `python` 全量（**本报告实跑两遍**）

| 运行 | 命令 | 读数 |
|---|---|---|
| 本报告 run#1 | `python -X utf8 scripts/run_tests.py` | `===== SUMMARY 298/300 通过，5 跳过（依赖缺失/平台不符） =====`；失败：`md_cg.test_p31_insight, md_cg.test_writelimit`；退出码 **1** |
| 本报告 run#2 | 同上（复跑） | `===== SUMMARY 299/300 通过，5 跳过 =====`；失败：`md_cg.test_writelimit`；退出码 **1** |
| 工作流采集 | 同上 | `299/300 通过` 同摘要；失败：`md_cg.test_writelimit, scripts.test_utf8_boot_guard` |

**稳定性判定（本报告实跑）**——三个候选失败里**只有 `md_cg.test_writelimit` 是稳定红**：

```
python -X utf8 -m md_cg.test_p31_insight      → 70 通过 / 0 失败，rc=0（连跑 6 轮，6/6 rc=0，失败轮数=0）
python -X utf8 -m scripts.test_utf8_boot_guard → SUMMARY 30/30 通过，rc=0
python -X utf8 -m md_cg.test_writelimit        → AssertionError(E1)，rc=1
```

⇒ 工作流与我 run#1 各自出现的**第二个**失败项（`scripts.test_utf8_boot_guard` / `md_cg.test_p31_insight`）**在单跑下均通过**（p31 连跑 6 轮全绿），属**全量跑内的次序/状态相关抖动**；`test_writelimit` 的失败则由 §4.5 的改前/改后对拍钉死为**本次修复所致**。本报告不把「299/300」写成「全绿」。

**分母 299 ↔ 300 的差异（补读者所指）**：`scripts/run_tests.py:61` 用 `glob.glob(os.path.join(_REPO, "md_cg", "test_*.py"))` **自动收集** `md_cg/` 下所有 `test_*.py`。新守卫 `md_cg/test_i50a_half_dup_defer.py` 正落在这个 face 内，于是：**工作树（含新守卫）＝ 300 个目标**、**改前树（HEAD 检出，无该文件）＝ 299 个目标**。本报告实跑佐证：`python -X utf8 scripts/run_tests.py --list | tail -1` → `共 305 个`（＝ 300 执行 + 5 跳过），且该清单里含 `md_cg    md_cg.test_i50a_half_dup_defer`（本报告实跑 grep「i50a」所得）。⇒ **腿 7 的「299/299」与本节表格里的「…/300」是两棵不同的树**（前者＝工作流那份不含新守卫的未改动树），不是同一读数的两种写法；两棵树上 5 个跳过项相同。
**这同时回答了「既然全量会收集它，为何 §4.1 还要单独跑」**：全量跑只印一行 `PASS md_cg.test_i50a_half_dup_defer`（本报告 run#1 日志实测如此），**不印 26 条断言、不印 9 处变异表**；§4.1/§4.2 的逐条读数只能由单独跑取得。

**其他针对性套件（本报告实跑）**：`md_cg.test_i50a_half_dup_defer` PASS、`md_cg.test_p9_forget_protect` 37/0、`md_cg.test_p9c_dedup_hints` 31/0、`md_cg.test_p2_mcp` 64/0（工作流同一组读数一致）。

### 4.7 在役库留痕只读核验（**本报告实跑**）

```
$ python -X utf8 -c "…读 <在役库根>\_forgetting.jsonl…"
<在役库根> isdir= True
   _forgetting.jsonl exists= True
   行数= 215 verdict 分布= {'ACCEPT': 201, 'MERGE': 14}
   mtime= 2026-09-27 08:05
MDCG_ROOT env= None
```

**215 行 / ACCEPT 201 / MERGE 14 / DEFER 0 / DROP 0**，`mtime` 仍为 2026-09-27（**未被本次读取改动**）。这与缺陷论断「DEFER 计数为 0」**逐数字吻合**。
**构成拆解另见 §1.5**（同一份留痕的交叉表：`external_surprising` 192 / `unknown` 16 / `internal_deterministic` 7，以及**本应 DEFER 却被 ACCEPT 的 8 行**）——「DEFER=0」由此不再有两种解释。

⚠ **路径更正与「在役」的证据边界（补读者所指）**：

| 命题 | 本报告能给的证据 | 判定 |
|---|---|---|
| 工作流腿 5 提到的「路由记忆指向的在役库根」不存在（本机绝对路径字面量已按发布门禁 R3 口径抹除） | `os.path.isdir(...)` = `False`（本报告实跑） | **成立** |
| `<在役库根>` 存在且是一个 MCG 数据根 | 目录内含 `_index.json`、`_forgetting.jsonl`、`_keys.json`、`_audit.jsonl` 等面；`contextual` 435 节点、`knowledge` 1247 节点（本报告实跑列目录） | **成立** |
| 该目录的 `_forgetting.jsonl` 由 DSH 插件/codebuddy 写入过 | 215 行里 `actor` 分布 = `{'dsh-memory': 194, 'codebuddy': 21}`；`dsh-memory` 与插件缺省 actor 同名（`src/index.ts:202` `actor: z.string().default('dsh-memory')`） | **成立（「曾由插件写到此处」）** |
| **它「是当前的」在役数据根** | **给不出**。插件解析优先级是 `env MDCG_ROOT` → `<用户级状态根>/paths.json` → 配置项 → 默认 `<用户级状态根>/data/mdcg`（`src/index.ts:189-197`）；本机 `MDCG_ROOT` **未设**（实跑 `os.environ.get("MDCG_ROOT")` 返回 `None`），且在 `~/.zcode`、`~/AppData/Roaming`、`~/.dsh`、`~/.config` 下**未找到 `paths.json`**（本报告实跑 glob）。⇒ **插件此刻解析到哪个根，本报告无法证明**；该路径也可能只是**历史写入根**或另一检出 | **未验证（已如实标注）** |

⇒ 结论按证据分层：**「在役读数为 215/201/14/0/0」是本报告独立复现的读数（只读、`mtime` 未改）**；而**「该路径就是插件当前在役根」是不成立的推断**——v1.0 原稿写成「**实际的**在役数据根是…」属**超出证据的断定**，现更正为「本机存在的一个由插件/codebuddy 写入过的 MCG 数据根」。腿 5 的「无法确认在役读数」仍然部分成立：**读数本身可复核，但「它是不是当前在役」不能**。**本次只做只读打开，未写入、未改 mtime。**

### 4.8 容器两栈（**本报告未跑，转述工作流采集**）

| 栈 | 退出码（工作流采集） | 读数（工作流采集） |
|---|---|---|
| 容器栈一（`docker … scripts/linux_verify.sh`，linux 侧 rust+python 十套） | **0** | `结果: 22 pass / 0 fail`；`[PASS] smoke_test (linux)`；`=== 汇总: 38 pass / 0 fail ===` |
| 容器栈二（node 侧） | **0** | `# cancelled 0`、`# skipped 3`、`# todo 0`、`# duration_ms 11928.979557` |

**本报告未跑这两栈**，仅转述工作流数字。理由与同批前例（`docs/eval/issue43_默认策略与键类型闸_v1.1.md` §6.2）相同：跑它们会向仓库写入构建产物（`target/`、`lib/`、`node_modules` 等），超出本次「只写报告文件、不改工作区」的硬边界。⇒ 状态＝**未跑**，不是「通过」。

### 4.9 与工作流交付物声明的其余差异（逐位对拍）

独立复核从 `git show HEAD:md_cg/forgetting.py` `exec` 出改前实现，与现行实现同一 cg 跑 **1188 格**：**verdict 差异恰 150 格，全部＝改前 ACCEPT→现行 DEFER**，全落在预测面（`kind≠internal_deterministic ∧ dup∈[0.60,0.85) ∧ 0.30≤imp<0.70`），反向无漏判；1038 格 verdict 相同，其中 963 格 reason 逐位相同、75 格为④ 文案变更（旧「且重要度 x<0.3」→新「且未触发不可遗忘保护」，仅当 `hint<0.3` 令双方同判 DEFER 时出现）。

⚠ **算术与口径更正（补读者所指）**：v1.0 原稿把该网格写成「10 个重复度档 × 9 角色 × 12 hint × 2 标题」，四因子相乘＝**2160**，与 1188 **对不上**——**原稿的因子分解是错的**。本报告复核：`11 × 9 × 12 = 1188`（可行的一组分解），故 1188 更可能出自「11 档 × 9 角色 × 12 hint」之类；**真实网格构成本报告无法确定**（产生它的脚本是工作流内部件，未随交付物给出、不在本仓追踪面内），只能照录总数 1188 与其 150/1038/963/75 四个读数。原稿同处又把「`hint=None` 的 90 格」当作子网格——`10 × 9 = 90` 只与「档 × 角色」自洽，**与含 hint 维的四因子分解不自洽**，属同一处摘录错误的连带：现更正为「`hint=None` 的**子网格**旧④ 0 命中」，**不再给其格数**（§1.3 同改）。

其真实性入口端到端（**工作流内部暂存脚本 `stage5b.py`**——**不在本仓追踪面内**，本报告**无法定位该文件、也未重跑**；工作流记其在仓根以 `python -X utf8 stage5b.py` 运行，每腿独立新库以隔离 writelimit 级联）：差异腿恰为 `half_hint0.6` 与 `half_nohint` 两条半重复腿（ACCEPT→DEFER），其余腿（全新/精确重复/tool-output/hint=0.9 保护）`verdict+reason+落库数` 逐位一致；**每条差异腿落库数 2→1**（DEFER 确不落库、只留痕）。**以上为工作流采集，本报告未重跑**（§一.4、§一.6 与 §4.5 是本报告对同一结论的独立、小规模复现）。

---

## 五、独立复核判定与其自列边界

**判定：ACCEPT**（不同执行体，四态执行）。

### 5.1 复核依据（转述）

1. **被测物**：`git diff -- md_cg/forgetting.py` 亲看，唯一行为改动＝`:329` 分支④ 判据由 `elif red["max"] >= DUP_DROP and imp["score"] < IMPORTANCE_MIN:` → `elif red["max"] >= DUP_DROP:`，其余全是注释/docstring；守卫＝未跟踪新件 `md_cg/test_i50a_half_dup_defer.py`。
2. **①各腿不崩 + 半重复腿真发生**：8 条腿——复核原文括号里只写出 7 项（保护/DROP/MERGE/半重复/重要度/新信息/精确重复），**第 8 条按其紧接的下文推断为「退化路径腿」**（该段后半单列「退化路径真发生（非『空池也不抛』）：空池 `compared=0/with=None/max=0.0` … 空正文同样 `max=0.0/with=None` 且不走④」）；⚠ 这一项是**依其上下文推断**，复核未逐条编号，本报告不代为断定其完整清单。全部 8 条无异常，落点与其**独立编码的 oracle**（不复用 `assess` 自身逻辑）逐腿一致；半重复腿真发生且可判定区分：独立逐节点扫描 3 节点 `n1=0.7302/n3=0.6074/n2=0.2892`，与 `redundancy` 的 `with='n1'/max=0.730210/compared=3` 逐位一致；**退化路径真发生**（空池 `compared=0/with=None/max=0.0` → verdict=ACCEPT，而非伪造成半重复 DEFER；空正文同理）。
3. **②与改前逐位对照**：见 §4.9。
4. **③守卫本体与变异自证**：`python -X utf8 -m md_cg.test_i50a_half_dup_defer` → 退出码 0、「26 通过，0 失败」；`--mutate` → 退出码 0、基线 0 红、9 处逐处吻合（与 §4.1/§4.2 本报告读数**一致**）。另做**删断言探针**（内存改 `G._GROUPS`，文件字节级前后一致已断言）：删 `g_a` → `_mutate_mode()` 返回 1 且 5 处红项数不符；删 `g_b` → 返回 1/2 处；删 `g_e` → 返回 1/6 处 ⇒「删掉某组断言后自证会红」成立。**本报告未复跑该删断言探针**，只转述。
5. **④不得静默的可观测面**：把 `_assess_src` 换成缺陷形态源码 → `_anchor_check()` 报 3 条、`main()` 返回 2 并打印 ANCHOR-MISS（本报告实跑为 7/4 条，见 §4.4 分歧）；修复本体的「不得静默」面：prefeed 半重复 → `verdict=DEFER/decision=defer`，`_forgetting.jsonl` 真写 DEFER 行、`summary.by_verdict={DEFER:1}`、`history` 可见（`node_visible=True`）；真实入口下留痕 `by_verdict` 由改前 `{ACCEPT:4,DROP:3}` 变为 `{ACCEPT:3,DEFER:2,DROP:2}`——**本应「从不产生输入」的回路现在有输出**。

### 5.2 复核自列的边界（其原文要点 + 本报告复现情况）

| 复核自列 | 本报告复现情况 |
|---|---|
| 「该缺陷**无崩溃腿**（缺陷本体是结构性不可达分支而非崩溃）」；①的「不再崩」面作「各腿不崩 + 退化路径真发生」执行并如实标注 | **已复核**：§二 崩溃点声明、§一.4 两腿均无异常 |
| 全部实验根 = `tempfile.mkdtemp`（`%TEMP%`），已清理（`i50a*` 共删 1294+7，剩 0） | 本报告同法（`i50a_*` 前缀临时根，已删）；**未**复现其删除计数 |
| `git status --porcelain` 与开工快照逐字相同，未加任何文件、未 `git add/commit/push`、未编辑工作区任何文件、未改守卫一字（字节级核对） | **已复核（并更正）**：本报告收尾实跑 `git status --porcelain` = ` M md_cg/forgetting.py` / `?? .zcode/` / `?? md_cg/test_i50a_half_dup_defer.py` / `?? docs/eval/issue50_半重复待定复核_修复记录_v1.0.md`——前两项与开工快照一致，后两项为本工作流新增未跟踪件；**复核方原话未含其自己的报告文件，本报告按实跑读数列出** |
| 在役库读数（215/201/14/0/0）只读核验、`mtime` 未被改 | **已独立复现**（§4.7，含构成拆解与 8 行「本应 DEFER」的直接证据）；⚠ 但「该路径＝插件当前在役根」**本报告无法证明**（`MDCG_ROOT` 未设、未找到 `paths.json`），已在 §4.7 按证据分层标注 |
| **未跑**全量与容器（遵嘱） | 本报告**跑了 python 全量两遍**（§4.6），**未跑**容器两栈（§4.8） |

### 5.3 复核的 uncovered（其未覆盖、并显式点名的面）

- **容器两栈未跑**（其流程内注明「未跑全量与容器（遵嘱）」）——本报告同样未跑（§4.8）。
- **在役库只做只读核验**：修复后 DEFER 是否真写进**在役库**的留痕、在役库的写面行为**未被验证**；被验证的只有隔离合成库与（只读的）在役留痕计数。
- **无崩溃面无独立崩溃复现**：缺陷的「崩溃腿」不存在，故复核未提供崩溃类证据（其 ① 以「各腿不崩 + 退化路径真发生」替代）。
- **锚点条数分歧未收敛**（本报告 §4.4）：复核报 3 条、本报告实测 7/4 条，双方未对齐到同一注入输入。

---

## 六、边界与未覆盖

> 本节各项**无独立小标题**；下文与全文出现的 **§六.1 … §六.5** 即指下面 1. – 5. 各条（1. 留池面 / 2. 未覆盖未跑 / 3. 未做归档 / 4. 写动作 / 5. 读者追问答复）。

1. **本轮明确不修而留池的面**：
   - **`md_cg/test_writelimit.py` 的 E1 / H1 / H3 / H4 四条既有断言**（`:125-127`、`:168-169`、`:177-178`、`:180-181`）——它们把「半重复必 ACCEPT」写成前提，修复后转红（§4.5）。**契约明令不许改断言迁就实现**，故本轮**原样保留、未改一字**；处置（改断言语义 / 改其夹具 / 认作预期变更）**留待编排侧裁定**。这是本批唯一稳定红项。
   - **`md_cg/writelimit.py` 与 `mdcos.remember_gated` 的落库/聚合动作**——契约划为不动面，本轮零改动。
   - **插件侧缺省 `importance=0.6` 的口径**（`src/index.ts:168`）——本轮不改（是设计口径，不是缺陷；缺陷是它被合取挡住）。
   - **分支④ 与重要度解耦后的语义外溢**：`dup∈[0.60,0.85)` 且未触发保护的输入，其 `verdict` 不再受重要度影响；独立复核的 1188 格扫描给出差异 **150 格，全为 ACCEPT→DEFER**（另 75 格仅 reason 文案变更，出现在双方同判 DEFER 的 `hint<0.3` 面）。该外溢是修复的**本意**，本报告只标注其量级，不主张「零影响」。
2. **未覆盖 / 未跑（逐条显式）**：
   - **容器两栈**（§4.8）：未跑，只转述工作流数字 0/0。
   - **改前树的 `python` 全量**：本报告**未**在「HEAD 检出的原样树」上跑全量；**工作流腿 7 在它自己的未改动树上跑过**（其读数 299/299、5 跳过、rc=0，分母无新守卫文件故比本节少 1，见 §4.6 的分母说明）——该条属**工作流采集，本报告未重跑**。本报告对改前/改后的差异用的证据是隔离枝对拍（§4.5）与守卫变异自证（§4.2），**不是**全量级证据。
   - **在役库写面**：修复后在役库是否会真产出 DEFER 留痕——**未验证**（只做了只读计数核验，§4.7）。
   - **插件 TypeScript 侧**：只读码（`src/hooks.ts:479-482`、`src/index.ts:168`），**未跑 TS 测试/未重编译**。
   - **`scripts.test_utf8_boot_guard` / `md_cg.test_p31_insight` 在全量跑内的偶发红**：单跑均绿（p31 连跑 6 轮 6/6 rc=0），本报告**只定位到「非稳定红」**，**未查明**其抖动根因（次序/共享状态/时基）——如需结论须另开调查。
   - **删断言探针**（复核 ③ 的「删 g_a/g_b/g_e 后自证会红」）：**本报告未复跑**，仅转述。
   - **锚点条数**（3 vs 7/4）：分歧未收敛（§4.4）。
3. **未做收尾归档**：本报告**未**执行工作纪律第 16 条的记忆归档（本轮任务是「撰写并落盘报告」，归档动作不在本 ask 范围内）——显式声明，非静默跳过。
4. **本次会话对本仓库的全部写动作**：仅本文件 `docs/eval/issue50_半重复待定复核_修复记录_v1.0.md`（初稿撰写 + 本轮修订，均在同一个文件上）。收尾 `git status --porcelain` 实跑读数＝ ` M md_cg/forgetting.py` / `?? .zcode/` / `?? md_cg/test_i50a_half_dup_defer.py` / `?? docs/eval/issue50_半重复待定复核_修复记录_v1.0.md`——**前两项与开工快照一致；后两项是本工作流新增的未跟踪件**（v1.0 原稿漏列了本文件自身，此处更正）。未 `git add/commit/push`；未改源码与守卫；未触碰在役数据根（只读）。
5. **读者追问的直接答复（只答本报告有证据的部分）**：
   - **修复后产生的 DEFER 由谁消费？** 读码所得：`mdcos.remember_gated` 对 DEFER **不落盘、不入任何队列**，只把 `{"verdict", "node_id", "gate"}` 回传调用方（`md_cg/mdcos.py:3670-3672`；对比 `v == "ACCEPT"` 才走 `self.add(...)`）。留痕的**读侧**有两条：MCP 工具 `mdcg_forgetting_history`（`md_cg/mcp_server.py:3536-3537` → `cg.forgetting_history`）与 `forgetting.summary`（`md_cg/mdcos.py:3546`，随健康度/洞察读数一起返回）。⇒ **回路接通到「有输出、且可读」，但没有自动消费方**——本报告**未找到**任何自动取走 DEFER 的点；「谁该取走」属产品/流程决定，不在本报告证据面内。
   - **显式传 `importance` 的调用在修复后行为如何？** 本报告实跑三路对拍（`dup=0.7302`，改前＝合取加回的等价改写）：`hint=0.1` → 改前 DEFER / 现行 DEFER（**verdict 不变**，仅 reason 文案不同；⚠ 该次对拍的「改前」实现保留了新文案，**故 reason 不作数**，真实 HEAD 文案为「且重要度 0.10<0.3」）；`hint=0.9` → 改前 ACCEPT / 现行 ACCEPT（① 保护面**零变化**）；`hint=0.6` → **ACCEPT→DEFER**。⇒ 受影响带＝`dup∈[0.60,0.85)` 且 `0.30≤imp<0.70`，与 §4.9 的 150 格一致；`>0.7` 与 `<0.3` 两端的 verdict 不变。
   - **`test_writelimit` 会挡 CI/发布吗？** **本报告未验证**仓库 CI 口径（未核查 `.github/workflows` 的 gate 链是否把 `scripts/run_tests.py` 全量纳入）。只报事实：该模块 rc=1（§4.5）。是否阻断发布由仓库流程决定。
   - **`test_p31_insight` / `scripts.test_utf8_boot_guard` 的偶发红是既存还是本次引入？** **未查明**。已知：两者单跑全绿（p31 连跑 6 轮 6/6 rc=0、utf8_boot_guard 30/30 rc=0），且工作流的第二个失败项与我的不同 ⇒ **不是固定失败**；但据此**不能**断定与本次修复无关（本次只改 forgetting 的判据行，两者是否绕经该分支本报告未追）。要结论须另开调查。
   - **在役库修复后会不会真写出 DEFER 留痕？** **仍未验证**（§六.2 同一项）；本轮只做到「在役留痕构成拆解＋8 行被吃掉的直接证据」（§1.5）。

---

## 附：本报告实跑命令清单（可复现）

```bash
python -X utf8 -m md_cg.test_i50a_half_dup_defer            # 26 通过 / 0 失败，rc=0
python -X utf8 -m md_cg.test_i50a_half_dup_defer --mutate   # 基线 0 红；9 处 6/6/3/3/9/2/7/2/2；rc=0
python -X utf8 scripts/run_tests.py                          # run#1 298/300（失败 test_p31_insight + test_writelimit）；run#2 299/300（失败 test_writelimit）；两遍均 rc=1
python -X utf8 scripts/run_tests.py --list | tail -1          # 共 305 个（= 300 执行 + 5 跳过；清单内含 md_cg.test_i50a_half_dup_defer）
python -X utf8 -m md_cg.test_writelimit                      # AssertionError(E1)，rc=1
python -X utf8 -m md_cg.test_p31_insight                     # 70/0，rc=0（连跑 6 轮均 rc=0）
python -X utf8 -m scripts.test_utf8_boot_guard               # 30/30，rc=0
python -X utf8 -c "from md_cg import test_i50a_half_dup_defer as T; print(len(T._anchor_check()), T.main())"   # 0 0（现状锚点）
python -X utf8 -c "…读 <在役库根>\_forgetting.jsonl，按 entropy.source_kind × dup 分档 × verdict 交叉…"  # 215 行；external_surprising×[0.60,0.85)×ACCEPT = 8
python -X utf8 %TEMP%/i50a_sweep.py                          # 腿 4 等价补跑：8 档 → dup/novelty/imp 逐档；0.600 实测 0.5994 出窗口
git -C <仓根> diff --stat -- md_cg/forgetting.py   # 15 insertions(+), 4 deletions(-)
python -X utf8 %TEMP%/i50a_probe_report.py                   # 改前 ACCEPT / 现行 DEFER（hint=0.60 与 hint=None 两路）
python -X utf8 %TEMP%/i50a_e1_pairs.py                       # E1 断言：改前 True / 改后 False
python -X utf8 %TEMP%/i50a_h_probe.py                        # E1 False；H1 False(groups=0)、H2 True、H3 False、H4 TypeError；落盘=1/5
```
