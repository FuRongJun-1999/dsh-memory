# cons200 · 冲突检测选面（索引序截断 → 相关性预筛＋保底面＋超限可观测）——实施记录 v1.0

> **注记（2026-10-03 收口轮 · 编排侧）**：本文件为**第一轮现场记录**（23 断言/5 变异，F1『未修』等表述为当时状态）。收口轮（面内例外＋无词面口径断言＋三处增补：27 断言/6 变异；第一轮 DEFER → 补齐 → 第二轮 ACCEPT）见 `docs/eval/cons200_冲突检测选面_实施记录_v1.1.md`——状态口径以后者为准。

**日期**：2026-10-03 ｜ **被测面**：`D:\program\dsh-memory-main` 工作树（**未提交**——`git status --porcelain` 实列 `M md_cg/consistency.py`、`M md_cg/test_mode_parity.py`、`?? md_cg/test_cons200_scan_selection.py`、`?? .zcode/`；本报告落盘前实测）｜ **基线**：HEAD `9a1150dd21f4d7cb0d2a48933ea559a15518f7bd`（`git rev-parse HEAD` 实跑核实）

**关联**：
- 设计稿 `docs/plans/stg条件化与结构索引_设计_v0.1.md`——本批为其**待签收点 5**（读码核实 `:107` 与签收记录 `:122`：「同族 `consistency.check` 的 `MAX_SCAN=200` 选面（字典序前 200 → 应改相关性/条件预筛）……**纳入本线第二实现批**（主体批不含；批间独立复核）」）的落地；
- 前序批 `docs/eval/issue52_条件先行与截断可观测_修复记录_v1.0.md`（同族缺陷，但**不同模块**：issue52 修的是 `md_cg/stg.py` 时空接口的 `_scan`/`_cap_hits`/`_with_scan_reads`，本缺陷在 `md_cg/consistency.py`，前序两 commit 均未触及——`git show --stat 0d3a0ab2`、`git show --stat 9a1150dd` 实跑核实：两 commit 的文件清单中**均无** `md_cg/consistency.py`）。

**证据分级声明**（本报告只写有机械证据的事）：

| 标记 | 含义 |
|---|---|
| 〔本报告实跑〕 | 本报告撰写员在本次 ask 内亲手执行并计数（守卫三模式 / mode_parity 正负两模式 / p11 / python 全量 / git 面 / 行号读码 / 设计稿签收点读码） |
| 〔工作流采集·修复段〕 | 修复工作流采集材料（13 条修前复现腿 / 实施 changes / targetedSuite / 修后对照与成本读数），本报告**转录**，不代跑不代补 |
| 〔工作流采集·复核段〕 | 修复工作流的独立复核段采集材料（三腿与退化路径 / 逐位对照 / 守卫本体自证 / F1–F4 发现 / 复核裁定 DEFER），本报告转录 |
| 〔工作流采集·编排侧〕 | 随任务材料传入的编排侧输出（容器两栈退出码），本报告转录、**未复跑**（本机无容器环境） |

行号口径：改后行号＝读工作树核实〔本报告实跑〕；改前行号＝`git show HEAD:md_cg/consistency.py` 导出后逐行核实〔本报告实跑〕。

**术语速览**：
- **修前扫描面**＝旧选面逐位形态：`exclude`/`layer` 过滤后的**索引序**（`list(nodes.items())` 快照序）前 `limit` 名；
- **预筛**（`_sift_score`）＝快照级相关性打分（只读索引条目既有键 `tags`/`rejection_terms`），零读盘零正文解析；
- **相关面**＝预筛序（rank/score 降序 + id 升序终键）前 `limit`；**保底面**＝修前扫描面 ∩ 候选，逐位保留——「修后检出 ⊇ 修前」的结构性保证；
- **剔除档**（唯一）＝「**新节点**未声明可展开条件（`tw_pos`/`tw_neg` 皆空）时的**非纪律候选**」。「新节点」＝**待检测/待写入的输入**（`check(content=…)` 的 content），**不是库内候选**；`tw_pos`/`tw_neg`＝新节点正/负条件词面经 `expand_query_terms_weighted` 展开的 `{词: 权重}` 词典（`consistency.py:542-543`，读码核实）；「非纪律候选」＝库内既有节点条目中 `_is_discipline` 判否者。触发与否**由输入决定**、与库内候选构成无关（判据对象、c1–c4 定义与「可证无产出」论证见 §3.1 附）。
- **读数** `scanned`/`kept`/`truncated`（**修后口径**）＝预筛后候选数 / 实际精比数 / `scanned>kept`（超限附 `hint`）——**修前 `scanned` 是另一口径（已精比数），见下方「口径变更（必读）」**。
- **相关面**排序规则（`consistency.py:344-361/595-596`，读码核实）：排序键＝`(-rank, -score, str(nid))` 三段（rank 降序 → 同 rank 按 score 降序 → 再同按 id 升序终键），取前 `limit`。rank 四档：**3**＝纪律（tags/前缀命中）；**2**＝`rejection_terms` 与 `tw_pos`/`tw_neg` 有整词交集；**1**＝`rejection_terms` 非空但无交集；**0**＝其余。score＝rank2 的**连续分**（由 `_weighted_coverage` 加权覆盖 ×10000 取整，0..10000），其余档恒 0（score 与「连续分」是同一物）。
- **判定态四态**＝`ACCEPT / REJECT / DEFER / BLINDSPOT`（`consistency.py:99` `VERDICTS`，读码核实）——`ACCEPT` 无冲突 / `REJECT` 硬冲突（自否定、纪律）/ `DEFER` 条件互斥待辨 / `BLINDSPOT` 无法建立比对路径。**注意同名不同义**：§五的「**裁定：DEFER**」是**独立复核段的裁定语汇**（语义＝复核未放行、列缺口待补），与检测判定无关。

**口径变更（必读）**：`scanned` 修前/修后**同名字段、两种口径**——**修前＝已精比数**（循环内 `scanned += 1` 后即比对，到 `limit` 即 break；HEAD 版 `:501-504`，读码核实），故腿 1 读数「scanned: 200」＝已比对 200 个；**修后＝预筛后候选数**（截断前；现行 `:603`）。`comparable`（两代同义）＝声明了正/负条件（`e_pos` 或 `e_neg` 非空）并**实际进入条件比对**的既有节点数（在 `if not e_pos and not e_neg: continue` 之后自增：HEAD 版 `:508-510`、现行 `:612-614`，读码核实）；修前 `comparable ≤ scanned`、修后 `comparable ≤ kept`。§5.1 所述 sp4/sp9「读数面不一致」（scanned 0↔7、comparable 0↔1）即本口径变更的直接产物——业务字段（verdict/reason/conflicts/…）全同。

---

## 一、缺陷定义与真实站点

### 1.1 缺陷定义

**一句话**：`consistency.check` 的既有节点比对面＝`list(nodes.items())` 的**索引序前 `MAX_SCAN`=200 并静默 break**——条件级真冲突（条件互斥＝DEFER 级；纪律违反＝REJECT 级）若落在索引序第 200 位之后，即**静默漏检**：不抛异常、返回体无截断标记、判 ACCEPT/0.0。该函数是**写链全部入口**（`mdcg.add` 直连 / `writepipe._gate_consistency` / `mdcos.check_consistency`）与 **MCP 检测查询面**（`_consistency_call` 的 check action，腿 8 即此面）的公共入口——缺陷面＝**一切经该函数的检测**（写入闸与查询同面），不止写入。

- **与 issue #52 同族、不同模块**：同族＝「按索引序截断＋静默」；不同面＝issue52 修的是 `md_cg/stg.py` 的时空三接口（`_scan`/`_cap_hits`/`_with_scan_reads`，本报告读码核实 `stg.py:168-203/207-221/245-261`），本缺陷在 `md_cg/consistency.py`。{工作流采集·修复段} 佐证：全仓 `MAX_SCAN` 仅被 `consistency.py`/`mdcos.py`/`mcp_server.py` 引用，**无测试文件引用**；issue52 守卫中 `S.consistency(...)` 的 `truncated/kept/scanned`（A5/B7）来自 `stg.py` 时空接口而非本模块。
- **在役规模**：在役库 17882 节点 ⇒ 检测面 ≈1.1%（出处：守卫 docstring `test_cons200_scan_selection.py:6-8`，读码核实；≈1.1%＝200/17882 的算术值）。「索引序最前的 `code_*` 索引节点占满名额、`mem_*` 记忆节点几乎从不进面」为**构述断言**（同出处：守卫 docstring 与实施段材料）——**本报告未附在役库构成读数**（§5.2 F4 同款局限：复核亦未去在役库取证）。

### 1.2 真实站点（行号为本报告读码所见）

**改前树**（HEAD 版 `md_cg/consistency.py`，805 行＝**LF 计数口径**；`splitlines()` 计 806，因末行无换行符；本报告导出后逐行核实）：

| 站点 | 内容 |
|---|---|
| `md_cg/consistency.py:61`（HEAD） | `MAX_SCAN = 200`——单次检测最多比对的既有节点数 |
| `md_cg/consistency.py:496`（HEAD） | `for nid, e in list(nodes.items()):`——索引序快照迭代 |
| **`md_cg/consistency.py:501-502`**（HEAD） | **截断主站点**：`if scanned >= int(limit): break`——静默 break，无任何标记 |
| `md_cg/consistency.py:503-504`（HEAD） | `scanned += 1`；`node = cg.get(nid) or {}`（每候选一次读盘；截断同时省读盘） |
| `md_cg/consistency.py:630-635`（HEAD） | 返回体 `rec` 仅含 `scanned`/`comparable`，**无** `truncated`/`kept`/`hint` |
| `md_cg/consistency.py:478`（HEAD） | `strength, scanned, comparable = 0.0, 0, 0`（`scanned` 初始位） |

**改后树落点**（工作树 `md_cg/consistency.py`，914 行＝LF 计数口径（`splitlines()` 计 915）；详见 §3.2）。

**消费面（本报告读码核实，改后树行号）**：

| 站点 | 内容 |
|---|---|
| `md_cg/mdcg.py:2170-2185` | `MdCG.add` 直连 `consistency.check`（`:2172-2175`）；`:2177-2178` REJECT+`on_conflict=reject` → 抛 `ConsistencyError`；`:2181-2185` `extra["consistency"]` 只挑 `verdict/reason/strength/emotional/unresolved_id` 五旧键（新键不进该处，天然向后兼容） |
| `md_cg/writepipe.py:283-350` | 写链闸 `_gate_consistency`（函数读数核实起止 `:283-350`）：`:296-302` 调 `cg.check_consistency(...)`（不设 limit，缺省=MAX_SCAN）；`:303` `ctx["cvd"] = cvd`（**完整读数透传**，新键随链尾 out 可见）；`:304`/`:312` 只消费 `verdict` |
| `md_cg/mdcos.py:4410-4433` | `MdCGOS.check_consistency`：哨兵剔除后直通 `consistency.check`（`:4427-4433`），完整返回 |
| `md_cg/mcp_server.py:1285-1310` | MCP 面 `_consistency_call`：`:1301` `limit=int(a.get("limit") or consistency.MAX_SCAN)`（缺省即 MAX_SCAN）；`:1296-1303` 直通 `cg.check_consistency` |

---

## 二、修前现场（本工作流采集的 13 条复现腿）

**共同事实**：可运行腿全部**无异常抛出**——本缺陷是**静默漏检型**（腿 1–5、8–11）与**写面静默放行型**（腿 7），腿 6 的异常是该载荷**应当**得到的处置（对照取证）。逐条如下〔工作流采集·修复段〕；「修前」＝改动前树（HEAD）行为。**本表全部 `scanned` 读数均为修前口径（已精比数）**，与 §3 之后的修后口径（预筛后候选数）不同义——见文首「口径变更（必读）」。

| # | 腿 | payload（关键项） | observed（异常/崩溃点） | 站点 | reproduced |
|---|---|---|---|---|---|
| 1 | **核心腿**·选面截断（索引序前 200）——条件互斥（DEFER 级）漏检 | 222 节点合成库（`%TEMP%\cons200_pre_*`）；内容＝生产批处理（`# 生效条件：生产环境`）；limit 缺省=MAX_SCAN=200；库内索引序 `zzz_clash` 在**220 位**（前 200 名单切片 `cut_slice_198_201=[aaa_198,aaa_199,aaa_200]`，`zzz_*` 两节点在 220/221 位，均不在前 200 内） | **无异常（静默漏检）**；`consistency.check` 读数 `{verdict: ACCEPT, conflict_strength: 0.0, n_conflicts: 0, scanned: 200, comparable: 200, reason: "无冲突"}`；期望 DEFER/conflicts=[zzz_clash]。`scanned=200` 恰等于 MAX_SCAN——循环在索引序第 201 个（`aaa_200`）处 break，索引位 220 的冲突对**从未进入比对面**；默认 depth 复核同漏检 | `md_cg/consistency.py:501-502`（改前）`if scanned >= int(limit): break`；返回体 `:630-635` 无截断标记 | true |
| 2 | 对照①——同库同载荷、limit=300（越过被切面）→ 检出 | 同上库；仅 limit=300 | `{verdict: DEFER, conflict_strength: 1.0, conflicts_with: [zzz_clash], scanned: 222, comparable: 222}`——同一循环、同一载荷，冲突对入面即检出；证明腿 1 漏检是**位置性**的（被切面＝索引位 ≥200） | `md_cg/consistency.py:496-506`（改前，同一循环） | true |
| 3 | 对照②——同载荷入 ≤200 节点库（默认 limit 不切）→ 检出（载荷真实性对照） | 2 节点小库（`%TEMP%\cons200_mini_*`）；同载荷；limit 缺省 | `{verdict: DEFER, conflict_strength: 1.0, conflicts_with: [zzz_clash], scanned: 2, comparable: 2}`——不涉及任何限额改动，默认口径下小库即检出，证明载荷本身为真冲突 | `md_cg/consistency.py:496-506`（未截断路径对照） | true |
| 4 | 纪律命中（**REJECT 级**）落索引尾——直连漏检 | 222 节点库；内容＝「删除生产数据」；limit 缺省；库内 `zzz_disc`（tags=[discipline]，负面条件＝删除生产数据）在**221 位** | **无异常**；`{verdict: ACCEPT, n_conflicts: 0, scanned: 200, comparable: 200, reason: "无冲突"}`；期望 `REJECT/conflicts=[{type: discipline, with: zzz_disc}]`——REJECT 级真冲突在索引尾被静默吞掉 | `md_cg/consistency.py:501-502`（改前）；返回体 `:630-635` 无标记 | true |
| 5 | 对照③——同库同载荷 limit=300 → REJECT(discipline) | 同腿 4 库；limit=300 | `{verdict: REJECT, conflicts: [{type: discipline, with: zzz_disc}], scanned: 222}` | `md_cg/consistency.py:496-506`（同一循环） | true |
| 6 | 对照④——≤200 节点库写面带 `on_conflict=reject`：同载荷被拒（异常取证） | 3 节点小库；`MdCGOS.add(consistency=True, on_conflict=reject)`；内容＝「删除生产数据」 | **抛 `ConsistencyError`**：msg＝`[REJECT] 命中纪律节点的不适用条件（negative.reject）`，`landed=false`——这是该载荷在写面上**应当**得到的处置 | `md_cg/mdcg.py:2177-2178`（REJECT+reject → 抛异常） | true |
| 7 | **写面带**（>200 节点库）——同载荷 `add(on_conflict=reject)` **未抛错、静默落盘** | 222 节点库；同 API 同载荷 | **无异常抛出**（`raised=null`）；`returned_nid="mem_evil"`、`landed=true`、`fm_consistency={verdict: ACCEPT, reason: "无冲突", strength: 0.0, emotional: approaching}`——对照腿 6，同一载荷在大库写面上静默放行并落盘 | `md_cg/mdcg.py:2170-2185`（add 直连，走同一截断）；调用面 `writepipe.py:296` / `mdcos.py:4410-4433` / `mcp_server.py:1296-1303`（均透传且不设 limit） | true |
| 8 | MCP 面 `_consistency_call`——缺省 limit 同漏检 | 222 节点库；`{action: check, content: 生产批处理载荷, layer: knowledge, depth: 0}`（limit 缺省） | default_limit：`{verdict: ACCEPT, n_conflicts: 0, scanned: 200}`；同载荷显式 limit=300：`{verdict: DEFER, scanned: 223}` | `md_cg/mcp_server.py:1285-1303`（limit 缺省回落 MAX_SCAN） | true |
| 9 | 写链闸 `writepipe._gate_consistency`——返回 None（不拦）且 cvd=ACCEPT | 222 节点库；生产批处理载荷；最小 ctx（a.content/a.layer/cg/nid），调用真实闸函数 | `{gate_return: null, cvd_verdict: ACCEPT, cvd_scanned: 200}`——闸不拦（仅 REJECT 才拦），cvd 透传口径同样是漏检读数 | `md_cg/writepipe.py:283-302`（调用点 `:296`） | true |
| 10 | 截断**无可观测标记**——返回体与 `_consistency.jsonl` 均无 truncated/kept | 222 节点库；`consistency.check` 返回体 + `root/_consistency.jsonl` 末行 | `result_keys=[actor, comparable, conflict_strength, conflicts, emotional, layer, missing, neg, pos, reason, recursion, scanned, t, verdict]`；`has_truncated=false`、`has_kept=false`；`scanned=200=MAX_SCAN`；留痕末行同键集、`log_has_truncated=false`——截断完全静默 | `md_cg/consistency.py:630-635`（改前；rec 仅 scanned/comparable）；截断点同 `:501-502` | true |
| 11 | 修前成本基线（旧「索引序前 200 精比」耗时/读盘次数；每库 20 rep、预热 3、串行） | 221 节点库与 1001 节点库；包装 `cg.get` 计数（每次 open 读一个节点文件） | 221 库：默认限 **21.07ms / 200 次读** / ACCEPT（漏检）；全量 22.71ms / 221 次读 / DEFER。1001 库：默认限 **20.23ms / 200 次读** / ACCEPT（漏检）；全量 100.7ms / 1001 次读 / DEFER——旧路径成本恒 200 次读盘、~20ms，与库规模无关 | `md_cg/consistency.py:496-506`（每候选一次 `cg.get`，见 `:504`）；`mdcg.get` 每次 open 读盘 | true |
| 12 | 边界自证——仅用临时目录、工作区未改动（**非缺陷腿**） | 脚本 `%TEMP%\cons200_repro\repro_cons200.py`；4 个 `tempfile.mkdtemp` 根 | `only_temp=true`（脚本内断言：全部库根 realpath 前缀=%TEMP%）；`script_in_repo=false`；运行后 `git status --porcelain` 仅 `?? .zcode/`、HEAD 未变、`git diff/--cached` 为空 | n/a | true |
| 13 | 背景读数——既有 consistency 套件全绿、issue52 守卫覆盖的是 stg 面而非本模块（**非缺陷腿**） | `python -X utf8 -m md_cg.test_p11_consistency`；读码 `test_issue52_scan_condition_first.py:297-388` | P11：**45 通过 / 0 失败**（改动前树上全绿——现有守卫对 `md_cg/consistency.py` 的 MAX_SCAN 截断零覆盖）；issue52 守卫的 `truncated/kept/scanned`（A5/B7）来自 `md_cg/stg.py` 时空接口；`git show --stat 0d3a0ab2` 改 `stg.py` 等、`9a1150dd` 改 `mdcg.py`/`stg.py`/`stgidx.py`/测试——**两 commit 均未触及 `consistency.py`** | `md_cg/stg.py:168-261`（issue52 已修面）vs `md_cg/consistency.py:61/496-506`（未修面） | true |

---

## 三、修法契约与落点

### 3.1 契约（三条硬线＋可观测＋偏离声明）

| # | 契约 | 机械钉法（守卫/变异） |
|---|---|---|
| C1 | **MAX_SCAN 数值不动**（200；数值放大不是修法，契约禁止面） | `consistency.py:61`；守卫 E1（`_cons.MAX_SCAN == 200`）；变异④（MAX_SCAN=2000 偷调 → 红 8） |
| C2 | **不得削弱真冲突检出**：「修后检出 ⊇ 修前」为**结构性保证**——保底面（过滤后索引序前 limit ∩ 候选）逐位保留修前扫描面 | `consistency.py:598-602`；守卫 B1/B3/B4；变异①（选面回索引序截断 → 红 7）、③（预筛剔真冲突候选 → 红 14） |
| C3 | **预筛不读盘**（快照级：只读索引条目既有键 `tags`/`rejection_terms`） | `consistency.py:322-361`；守卫 D1（读盘数==kept）；变异⑤（剔除档失效 → 红 2） |
| C4 | **截断不静默**：`scanned`（预筛后候选数）/`kept`（实际精比数）/`truncated`（scanned>kept）＋ 超限附可操作 `hint`（细化生效条件/不适用条件；建条件索引方向；明文劝阻调大数值） | `consistency.py:69-75`（`_SCAN_HINT`）、`:736-744`；守卫 C1–C6；变异②（去掉上报与 hint → 红 10） |

**判据一字未动**：阈值（CLASH_HIGH/LOW、SAME_COND_HIGH、SLOT_HIGH、CONCLUSION_SAME、SELF_NEGATION）、覆盖计算、四态路由均未改；本批只改**选面与读数**（`consistency.py:522` docstring 同款声明）。

**偏离声明（明说）**〔工作流采集·修复段〕：此处「契约」＝**实施批约定**（实施说明原文，见采集材料；其全文**未随材料提供**，本报告无法给出文档出处；本报告 §3.1 C 表是同套硬线的重述，C2 即其「不得削弱真冲突检出」一条）。契约第 2 点字面「候选超限时按相关性取前 N（MAX_SCAN 为上限）」实现为「**相关面前 limit ∪ 保底面**（过滤后索引序前 limit ∩ 候选），两面上限各 limit（≤2×MAX_SCAN）」——若精比面严格限 limit，修前扫描面内排序落后的候选会被挤出，「修后检出 ⊇ 修前」无法硬保证（实施批硬线优先，即本报告 C2）；**MAX_SCAN 数值未动**；精比读盘 ≤400 次 vs 修前 200 次（同量级；全量读盘 17882 次 ≈1.54s，见 §4 成本）。

**附·剔除档判据对象与触发条件**（回应「剔除档按什么判、为何 §4.2 P1/P2 的 scanned 差 262 倍」）：
- **判据对象**：剔除档只看两件事——**待检输入**（`tw_pos`/`tw_neg` 是否皆空）与**库内候选的纪律资格**（`_is_discipline` 以条目 `tags`/id 前缀判定），**不看候选其它属性**。含词面的输入（§4.2 的 P1）⇒ 不触发、全部候选保留；无词面输入（P2）⇒ 触发、非纪律候选整批剔出、只剩纪律候选。
- **c1–c4 定义与出处**（`consistency.py:626-628/636-637`，读码核实）：**c1**＝新节点**正**条件词权 × 旧节点**负**条件词面覆盖（`_cov(tw_pos, " ".join(e_neg))`）；**c2**＝新**负** × 旧**正**；**c3**＝新**正** × 旧**正**；**c4**＝新**负** × 旧**负**。c1/c2 合成条件互斥强度 `c=max(c1,c2)`（`:628`）；c3/c4 合成同条件重合度 `same_cond`（`:638`），供结论槽取值分歧（L1-c）判定。
- **「可证无产出」论证**：c1–c4 与分歧判定**全部以 `tw_*` 为乘子**（代码形态 `_cov(tw_pos, …) if (tw_pos and e_neg) else 0.0`）——`tw_pos`/`tw_neg` 皆空时四者恒为 0，故此时非纪律候选**不可能**产出 `conflicts` 或 `divergences`；而纪律违反走 `_ban_hit(content, e_neg)` 子串命中（`:618`，不看词权），故纪律候选一律保留。剔除档只剔「条件皆空时不可能有产出的非纪律候选」。
- **P1/P2 读数差解释**（§4.2 修后对照）：P1 输入＝`# 生效条件：生产环境`（词面非空）⇒ 不触发 ⇒ 候选全保留，scanned=263；P2 输入＝「删除生产数据」（无 CCG 条件声明）⇒ 触发 ⇒ 只剩纪律候选 `zz_disc`，scanned=1。**差值由输入决定，与候选自判无关**。守卫 D3 同款实证：无条件内容下读盘 200→1、kept=1。

### 3.2 落点表（改后行号＝本报告读码核实；工作树 `md_cg/consistency.py` 914 行＝LF 计数口径（`splitlines()` 计 915，两版末行均无换行符）——与改前 805 行＋`git diff --numstat` 的「+117/−8」逐行吻合：805+117−8=914）

| 行（现树） | 内容 |
|---|---|
| `:61-64` | `MAX_SCAN = 200` 数值未动；注释同步为「相关面/保底面各自的限额（非索引序前 N）」 |
| `:69-75` | 新增 `_SCAN_HINT`（截断可操作提示；与 stg `_CAP_HINT`（`stg.py:245-249`）同口径精神） |
| `:322-361` | 新增 `_sift_score`：快照级相关性预筛单点（纪律 rank3 > 词面整词交集 rank2＋`_weighted_coverage` 连续分 > 负条件迹象 rank1；零读盘零正文解析；复用 `_is_discipline`/`_cov` 既有单点，不引入第二套条件解析）。诚实边界（docstring `:338-342`）：`rejection_terms` 只覆盖负条件面，「旧节点仅声明生效条件」在快照无字段可判——不做任何剔除，只排序 |
| `:571-606` | `check` 选面重构：预筛剔除档（**唯一**：`tw_pos`/`tw_neg` 皆空时的非纪律候选，可证无产出；纪律违反走 `_ban_hit` 故保留）→ 候选面 → 精比面＝相关面前 limit ∪ 保底面；`scanned`/`kept`/`truncated` 落点 |
| `:734-744` | 返回体新增 `kept`/`truncated`（旧键 `scanned`/`comparable`/`verdict`/`conflicts` 等全在场，向后兼容）；`truncated` 为真时附 `hint` |
| `:505-522` | `check` docstring 选面契约（含诚实边界：`rejection_terms` 只覆盖负条件面） |

**预筛论证（报告节）**〔工作流采集·修复段〕：
- **信号**＝快照既有键：`tags`（`_is_discipline` 单点）与 `rejection_terms`（`mdcg.rejection_index_terms` 单点生成）；
- **廉价性**＝零读盘零正文解析——守卫 G4 用读盘计数断言 `gets==kept` 机械证明预筛阶段零读盘；
- **漏检风险与兜底**＝`rejection_terms` 只覆盖负条件面，「旧节点仅声明生效条件（正文 `# 生效条件：` 行）」的 pos 面在快照无字段可判 → 一律不剔除只排序（宁多勿漏）、由保底面 + `truncated` 可观测兜底（已写入 docstring 诚实边界）。

### 3.3 守卫与对拍同步

- **新增守卫** `md_cg/test_cons200_scan_selection.py`（**521 行**，本报告读码核实）：5 组 23 断言（G1 选面 A1–A4 / G2 对拍 B1–B5 / G3 可观测 C1–C6 / G4 成本 D1–D4 / G5 语义红线 E1–E4）；三模式：正向、`--branch-baseline`（定点变异自证）、`--legacy-baseline`（修前形态重建应转红）；ANCHOR-MISS 退出码 **2** fail-closed；基线源＝运行时源码 `inspect.getsource`（`_build_mutant`，`:408-421`），**不以 git HEAD 为基线**。
- **既有对拍守卫同步** `md_cg/test_mode_parity.py`：对写链 out 的 consistency 读数新增 `kept`/`truncated` **定向豁免**（`_KNOWN_EXT_KEYS` `:642`、`_norm_known_ext` `:645-653`，Q 组比较点 `:681-682`）＋「新键在场」断言（`:693-698`，删新键让对拍变绿即转红）；旧键仍逐位对拍。改动量 +40/−3（`git diff --numstat` 实跑；docstring 说明 `:32-36`）。

---

## 四、验证数字

### 4.1 本报告实跑（撰写会话内亲手执行）

| 项 | 命令（原样） | 结果 |
|---|---|---|
| 守卫·正向 | `python -X utf8 -m md_cg.test_cons200_scan_selection` | 退出码 **0**；**23 通过 / 0 失败**（逐条计数：G1 4＋G2 5＋G3 6＋G4 4＋G5 4） |
| 守卫·变异自证 | `python -X utf8 -m md_cg.test_cons200_scan_selection --branch-baseline` | 退出码 **0**；未变异基线 23 全绿；五处变异**各自恰好命中**：①**7** ②**10** ③**14** ④**8** ⑤**2**；**空转断言 0**（每条断言至少被一处变异打红）；判别力自证 PASS |
| 守卫·修前形态 | `python -X utf8 -m md_cg.test_cons200_scan_selection --legacy-baseline` | 退出码 **0**；修前形态打红 **7** 条：**A1/A3/B2/B3/B5/D3/E4**——**判据**（读码 `test_cons200_scan_selection.py:498-502`）＝核心三条 **A1/B2/B5** 全部转红即 PASS（**不要求恰好 7 条**；7 为实测值）。「打红」＝修前形态下守卫**按设计**报出的红、**不是失败**——守卫本身 rc=0 判 PASS |
| 对拍守卫·正向 | `python -X utf8 -m md_cg.test_mode_parity` | 退出码 **0**；**64 通过 / 0 失败**；Q 组 **SAME(15)/DIFF(0)**（写链 A/E 全线＋full 档全线＋矩阵/缺省/plan 面）；「新键在场」PASS（A_add/full_A/full_C 的 consistency 均含 kept/truncated）；负对照（导出树副本注入 A 面差异）DIFF **恰好** A_add/full_A |
| 对拍守卫·变异 | `python -X utf8 -m md_cg.test_mode_parity --mutate` | 退出码 **0**；定点变异自证 **PASS**——变异表 `_SRC_MUTATIONS`（`test_mode_parity.py:1052-1138`，**8 处①–⑧**）＋**1 处自检钉**（不占编号），全部「命中预期」（预期＝表内第 7 元素；以下为**本报告实跑输出逐条**）：①档位不生效 **5** ②accept 不执行 **13** ③回滚不落盘 **5** ④执行记录不落 mutation **14** ⑤写链 full 档放行分支失效 **4** ⑥freshness 档名分叉 **2** ⑦weights 档名分叉 **2** ⑧空池注入 **11**；自检钉（防误删自检剥除）**3** |
| consistency 既有套件 | `python -X utf8 -m md_cg.test_p11_consistency` | 退出码 **0**；**45 通过 / 0 失败** |
| python 全量 | `python -X utf8 scripts/run_tests.py` | 退出码 **0**；`===== SUMMARY 311/311 通过，5 跳过（依赖缺失/平台不符） =====`（清单含 `PASS md_cg.test_cons200_scan_selection` 与 `PASS md_cg.test_mode_parity`） |
| git 面 | `git rev-parse HEAD` / `git diff --numstat` / `git status --porcelain` | HEAD=`9a1150dd21f4d7cb0d2a48933ea559a15518f7bd`；numstat：`consistency.py +117/−8`、`test_mode_parity.py +40/−3`；status：2 M＋2 ??（见文首）；本报告落盘后实测新增 1 项 `?? docs/eval/cons200_冲突检测选面_实施记录_v1.0.md`（本文档），源码与两处已跟踪改动均未再动 |

**守卫读数定义**：「红 N」＝该处定点变异打红的断言条数；预期值＝守卫源码变异表 `_MUTATIONS`（`test_cons200_scan_selection.py:396-405`）每条的**第三个元素**；判据＝「打红集合大小 == 预期」（比较逻辑 `:469-475`）；「空转断言 0」＝`never = 全部断言标签 − 各变异红项并集` 为空（`:476-479`）。

### 4.2 工作流采集（转录）

**修复段**：
- targeted：`python -X utf8 scripts/run_tests.py md_cg` → **234/234 通过**（3 跳过：依赖缺失/平台不符），FAIL 行数 0，rc=0；含 `PASS md_cg.test_cons200_scan_selection` 与 `PASS md_cg.test_mode_parity`（同步口径后）；另单跑全绿：`test_p11_consistency` 45/0、`test_neg_tail_honesty` 44/0、`test_recall_face_guards` 41/0、`test_b3_merge_keeps_content` 31/0、`test_neg_condition_hits` 39/0、`test_issue52_scan_condition_first` 36/0、`test_i50a` 26/0。
- 修后检出对照（264 节点合成库；`git show HEAD:md_cg/consistency.py` 源码 exec 取证，不触碰工作树）：修前 P1 `DEFER` 仅检出 `a_conf`（`zz_offline` 漏检）、P2 `ACCEPT` 无检出（`zz_disc` 漏检）；修后同场景 P1 `DEFER` 检出 `[a_conf, zz_offline]`（scanned=263 kept=202 truncated=True）、P2 `REJECT` 检出 `[zz_disc]`（scanned=1 kept=1，剔除档读盘 200→1）——**新增检出全部落原被切面**。**P1/P2 的 scanned 差 262 倍由「输入是否含词面触发剔除档」所致，解释见 §3.1 附**。
- 成本读数（串行，rep=7 取中位数；**适用域见句内标注**）：预筛+排序 **12.39ms**@**17882 条合成快照**（＝模拟在役规模索引条目形态的替身，**替身构造细节未随材料提供、在役代表性未声明**；该读数为**纯预筛**、零读盘）；旧前 200 精比 17.16ms@**264 节点真库**（单次读盘+解析≈0.086ms ⇒ **全量**读盘 17882 次≈1.54s，预筛为其 0.8%）；修后真库整检 **17.58ms vs 修前 17.16ms（+2.4%）**，读盘 **202 vs 200**（**同为 264 节点库读数**）。**在役 17882 规模的真库「预筛＋精比」合体成本未测**（材料未含）——「+2.4%」只在该 264 节点库规模上成立；可核算关系：预筛随候选数（快照级、零读盘）、精比随 kept（≤400 次读盘＋解析）。
- 部署说明：在役常驻 MCP server 进程仍为改动前代码（其 consistency 读数无 kept/truncated），**新选面随服务重启生效**；实施批按其任务约定未 commit（采集原文「依契约不 git add/commit/push」——**该约定文本未随材料提供**，本报告不补出处；本报告撰写任务的同款硬边界见 §六文末）。
- 归档（纪律第 16 条）：写入灵枢记忆 `mem_1790993715298_149edf`（CCG 六要素）并读回确认可检索。

**复核段**：见 §5。

**编排侧（转录、未复跑）**：容器两栈退出码均 **0**——栈一采集原文并列**两个数**：`结果: 22 pass / 0 fail` 与 `=== 汇总: 43 pass / 0 fail ===`（**两数关系、各覆盖哪些套件未说明**；另有 `[PASS] smoke_test (linux)` 标记）；栈二原文 `# cancelled 0 ｜ # skipped 3 ｜ # todo 0 ｜ # duration_ms 12018.080547`（**无 pass 计数**）。采集原文为碎片化摘要、两栈覆盖内容未说明；本机无容器环境，**未复跑**——由这些碎片无法评估两栈覆盖什么；如需可核验的容器面结论，应由编排侧补全原始日志或复跑。

---

## 五、独立复核判定与它列出的 uncovered

**裁定：DEFER**（**复核段裁定语汇**，语义＝复核未放行、列缺口待补；与检测判定四态同名不同义，见文首术语速览）〔工作流采集·复核段〕。复核全部读数在系统临时目录合成库上自跑（沙箱 `%TEMP%\cons200_review_9sc6teil`，跑完已删）；HEAD 版 oracle＝`git archive HEAD md_cg utf8_boot.py package.json` 导出树；子进程恒 `PYTHONUTF8=1`＋`PYTHONDONTWRITEBYTECODE=1`＋`MDCG_AUX_ROOT=临时目录`，未碰 `~/.mdcg` 与在役库；工作区终检 `git status --porcelain --untracked-files=all` 与开工逐字一致、HEAD 仍 `9a1150dd`。

**本节标签出处注**（这些标签只出现在复核段材料里，本报告只能就出现处转述）：`L1–L4`＝`harness.py legs` 四条腿（L4＝输入「删除生产数据」；L1/L2/L3 见 5.1）；`bp*/tp*/np*/sp*`＝复核退化/容错场景编号——**其脚本与完整场景矩阵未随材料提供**，本报告仅能转述材料中出现的编号结论（bp4＝无条件内容 cand=1；bp1/bp5/tp1/np1＝截断真发生；sp12/sp13＝limit 0/−5；sp4/sp9＝无词面场景）；`A5/B7`＝issue52 守卫（`test_issue52_scan_condition_first.py`）的断言编号（其读数来自 stg 面，见腿 13）；「26 场景」＝复核退化路径场景总数（材料原文）。「**13 键**」＝复核对拍脚本选定的比较键集——**清单未随材料提供、无法列出**；可核对的现存事实：改前返回体实测 **14 键**（腿 10：actor/comparable/conflict_strength/conflicts/emotional/layer/missing/neg/pos/reason/recursion/scanned/t/verdict）、改后 **16 键**（读码 `consistency.py:734-738`＝上列 14 键＋`kept`/`truncated`；超限时另 +`hint` `:744`）——复核 13 键与这两组的关系（同集？剔哪键？）**无法由现有材料判定**。

### 5.1 复核证据（三条硬线独立复现＋守卫自证）

- **三腿与退化/容错路径**：`harness.py legs`（`MdCGOS.check_consistency` / `mcp_server._consistency_call` / `writepipe._gate_consistency`＋`default_pipeline().execute`）在 263 节点合成库上两树 0 异常：现行树 L4（输入「删除生产数据」）=REJECT 命中 `zz_disc`，HEAD 树=ACCEPT（纪律节点在索引序 262 位，修前选面读不到）——修前腿的漏判当场复现；L1/L2/L3 修前仅检出 `a_conf`，修后 +`zz_offline`（读数 scanned=262/kept=202/truncated=True/hint=True）。退化路径用**可判定比较**（非「没抛异常」）：26 场景以 CountingCG 记录实际 `cg.get` 集合，与复核者按设计稿文字独立重算的精比面逐位比对，全部 `读盘面==face:True` 且 scanned/kept/truncated 与 oracle 全等；bp4 无条件内容 cand=1（剔除档真发生）、bp1/bp5/tp1/np1 截断真发生、sp12/sp13（limit=0/−5）kept=0 且读盘 0 次不崩、空库 BLINDSPOT/ACCEPT 不崩。
- **逐位对照**：小库/空库 11 个含词面场景（含 depth=3 递归、exclude、condition_space、空值哨兵）现行 vs HEAD **13 键逐位一致（含读盘面）**；两个**无词面**场景 sp4/sp9 读数面不一致：scanned 0↔7、comparable 0↔1、读盘 []↔7（verdict/reason/conflicts/missing/recursion/emotional/strength **全同**）。复核另证「**在『条目 tags 与盘面 fm.tags 同源』前提下**剔除档不可能翻 verdict」：`_dedup` 会 strip，故 pos or neg 非空 ⟺ tw_pos or tw_neg 非空（fuzz `expand_query_terms_weighted` 24 个非空串均非空），唯一读 comparable 的 BLINDSPOT 支路与剔除档互斥；grep 确认 comparable/scanned 无功能消费者（`writepipe.py:304/312` 只读 verdict）。**该前提一旦被破坏（反例）见 §5.2 F1**。
- **守卫本体与自证**：`python -X utf8 -m md_cg.test_cons200_scan_selection` → 23 断言全绿 rc=0；`--branch-baseline` → 五处变异打红 7/10/14/8/2 **逐处==预期**、无空转、rc=0；`--legacy-baseline` → 打红 7 条（含 A1/B2/B5 核心）rc=0。删断言探针（内存改组表/包 ok，不改文件）：删 `g3_reads` → rc=1（变异②③④条数失配）；删 `g4_cost` → rc=1（①③⑤失配）；追加恒真断言 → rc=1 且点名「空转断言」；只屏蔽单条 A4 → rc=1（③ 13≠14）。fail-closed 探针：变异表/legacy 锚点漂移 → 均 ANCHOR-MISS＋**rc=2**。另跑被同步改动的 `test_mode_parity` → 64 通过 0 失败 rc=0，Q 组 15 SAME/0 DIFF，负对照注入 A 面差异仍**精确** DIFF 到 A_add/full_A（定向豁免未把对拍打瞎）。
- **不得静默可观测（四级实测）**：带 kept/truncated/hint 的读数在 check 返回体、`_consistency_call`、`writepipe._gate_consistency` 的 `ctx[cvd]`、`default_pipeline().execute` 的 `out[consistency]`（out keys=[committed,consistency,id,ok,verdict]；consistency 内 scanned=262/kept=202/truncated=True/hint=True）四级皆在场；同场景 HEAD 树四级皆无这些键。

### 5.2 复核列出的 uncovered（转 ACCEPT 前的缺口）

- **F1·判据分叉缝（复核段新发现）**：预筛判据与判定判据**不同源**——预筛 `_is_discipline({"tags": e.get("tags")}, nid)`（读**内存索引条目**快照）vs 内层 `_is_discipline(fm, nid)`（读**盘面** fm）。术语：**盘面**＝节点 `.md` 的 frontmatter（`cg.get` 读盘所得 `fm`）；**条目**＝内存索引快照 `cg.index["nodes"][nid]`；**非合作写者**＝不经写路径（add/update 等）直接改写 `.md` 内容的一方（`mdcg.py:1714-1716` `_dir_fingerprint` docstring 同款声明：「外部直改文件内容属非合作写者协议」）。两树跑**同一形态**（盘面 `fm.tags=[discipline]`、只把内存条目 tags 置空）：现行树把该候选**剔掉** → 输入「删除生产数据」判 ACCEPT；HEAD 树读盘面 → REJECT。即源码/docstring「唯一剔除档=可证无产出」的证明缺一条前提：**「条目 tags == 盘面 fm.tags」**。**归属**：该判据分叉由**本批预筛新增**（修前循环直接 `cg.get` 读盘、单判据面，不存在第二判据）——但**触发**它需非合作写者存在。可达性：协作写路径实测保持同源（同 id upsert 改 tags 后 entry==disk==[discipline]），三个 `index[nodes]` 直写点均重算条目；只有非合作写者改盘不重建索引才分歧（仓内确有直写 `.md` 的合法管线 `scripts/discipline_nodes.py:243-249` `_write_node` / `:337` 写回；但该管线只改 condition_space/nac/body、**不动 tags**）→ **缝真实、当场复现，但复核未能证明其在在役协议下可达**；修复方向（显式同源前提 / 预筛改读盘面 / 加同源断言）与「预筛零读盘」契约存在取舍，留池另裁（§六-1）。
- **F2·诚实边界非空话**：`rejection_terms` 为空的旧节点在超限时不进精比面，修后同漏（np1 修前=修后=[]），而全扫 limit=1e6 检出 `zz_needle`——**真漏检**，但 truncated=True+hint 在场，与 docstring 声明一致。
- **F3·新增 `e.get` 面不可达**：保留有效指纹注入 `nodes={"s00":null}` 后 `MdCGOS` 构造本身先抛 AttributeError（`_count_buckets`，`mdcg.py:1741-1747`），两树一致——非本批问题。
- **F4·纪律词形不一致（本报告实跑补证）**：在役纪律投影节点 tags=`["work-discipline","discipline:N",…]`（`scripts/discipline_nodes.py:281`），而 `DISCIPLINE_TAGS`＝`("discipline","纪律","work_discipline","rule","规则","戒律")`（`consistency.py:97`）＋ id 前缀 `discipline_`/`work_discipline`（`:157-161`）——**词形不一致**。**本报告实跑**（纯函数调用、未触在役库）：`_is_discipline({"tags": ["work-discipline","discipline:1","harness:all","v1.1"]}, "mem_1790993715298_149edf")` → **False**（对照：精确 `discipline` → True、`work_discipline` → True、id 前缀 `discipline_*` → True）。**条件推论**（需在役库取证才能定论）：**若**在役纪律投影节点全部为该词形，则 `_is_discipline` 对其恒 False ⇒ 纪律 REJECT 分支（`consistency.py:618`：`_is_discipline(fm, nid) and e_neg and _ban_hit(...)`）对它们不生效——但不排除其它路径兜住（其禁令仍作为负条件进入普通条件比对 c1 面；实际覆盖效果未取证）；库里是否另有其它词形/兜底面，**复核与本报告均未取证，不下结论**。
- **②「合法输入逐位一致」对无词面输入不成立（读数面）**：sp4/sp9 的 scanned/comparable/读盘面差异（见 5.1）＝文首「口径变更（必读）」所述的口径差（业务字段全同、非行为差异）——需给新口径一条定点断言（复核转 ACCEPT 的第二条件）。

**转 ACCEPT 的最小条件（复核原文口径）**：把「条目 tags 与盘面 fm 同源」写成显式前提（或预筛改读盘面/加同源断言），并给 scanned/comparable 在无词面输入下的新口径一条定点断言。

---

## 六、边界与未覆盖（含本轮明确不修而留池的面）

**本轮明确不修、留池的面**：

1. **F1 同源缝**（条目 tags 与盘面 fm.tags 的同源前提）——未修。修复方向已由复核给出（显式前提/预筛改读盘面/加同源断言），涉及「预筛零读盘」与「同源」两条契约的取舍，另立裁定。
2. **scanned/comparable 无词面输入的新口径定点断言**——未加（复核转 ACCEPT 的第二条件）。
3. **F2 覆盖缺口**（旧节点仅声明生效条件、无 `rejection_terms` 的 pos 面冲突，在超限且不落保底面时可能不被精比）——设计上由**条件索引方向**解决（`_SCAN_HINT` 与 docstring 均指向设计稿），本批不做覆盖断言。
4. **F4 词形不一致**（在役纪律投影节点 tags 与 `DISCIPLINE_TAGS`）——需在役库取证后再定，本轮不动。
5. **在役生效面**：常驻 MCP server 进程仍跑改动前代码，新选面随**服务重启**生效；实施批按其任务约定未 commit（采集原文「依契约不 git add/commit/push」，**约定文本未随材料提供**）。重启后**每次写入都会执行该检测**（写链调用面读码核实：`mdcg.py:2170-2175`、`writepipe.py:296`），成本形态＝预筛（快照级、零读盘）＋精比（≤400 次读盘）；其**在役规模的实际总耗时未测**（§七 Q2）。
6. **MAX_SCAN 数值与判据阈值**：不改（契约禁止面）。

**已声明的诚实边界**（随实现写入 docstring）：本模块是条件级（结构化）冲突检测，非语义蕴含证明；`rejection_terms` 只覆盖负条件面；预筛零读盘、信息不足者不剔除只排序；保底面 + truncated 兜底。

**成本边界**：精比读盘 ≤2×MAX_SCAN＝400 次 vs 修前 200 次（同量级）；预筛 12.39ms@17882 条**合成快照**（模拟在役规模；替身构造未随材料提供）、为全量读盘（≈1.54s）的 0.8%；修后真库整检 +2.4%（17.58 vs 17.16ms，**264 节点库**）。**在役 17882 规模的真库合体成本未测**（§七 Q2）。

## 七、状态、未测面与待决（回应读者问题）

**当前状态（截至本报告落盘）**：实施完成；守卫/回归/对拍/全量全绿（§四）；工作树**未提交**（§六-5）；独立复核裁定 **DEFER**（§五），两条「转 ACCEPT 的最小条件」**均未做**（§六-1/2 留池）。「补齐后转 ACCEPT 再提交」还是「带留池直接合入」＝**编排/设计侧决策，不在本报告材料内**。与设计稿的关系：签收点 5 已签收「纳入本线第二实现批（主体批不含；**批间独立复核**）」（`docs/plans/stg条件化与结构索引_设计_v0.1.md:107/:122`，读码核实）——本批即该条落地，§五 的复核即该条所称「批间独立复核」。

**逐问可答边界**（对应读者 nextQuestions；能答的在正文，不能答的如实标未测）：
- **Q2·在役合体成本**：未测（材料未含在役规模真库读数）；重启后**每次写入都付**该检测（写链调用面见 §六-5），成本形态＝预筛（快照级、零读盘）＋精比（≤400 读盘），在役数值无读数。
- **Q3·F2 在役占比**：未测（材料未含）；在役用户可见的兜底＝`truncated=True`+`hint`（文案给出「细化条件/建索引」方向，`consistency.py:69-75`/`:744`）；「条件索引方向」的落地时点＝设计线后续批（本报告无时点材料）。
- **Q4·F1 关闭路径**：所需取证＝证明「改盘不改索引且改 tags」的非合作写者存在（或不存在）；或按最小条件改判据同源。裁定归属＝设计线（本报告无该材料，不代言）。
- **Q5·F4 严重性**：见 §5.2 F4——本报告已把「`_is_discipline` 对该词形判 False」从读码推断升级为**实跑验证**；「纪律 REJECT 面对在役投影节点整体失效」是否成立取决于在役库构成（是否全为该词形、有无其它词形/兜底路径）——**在役取证未做**，是待决项。
- **Q6·兼容边界**：`MdCG.add` 直连面 `extra["consistency"]` 只投影五旧键（`mdcg.py:2181-2185`，读码）——该面**看不到** kept/truncated（是否算 C4「不静默」的缺口＝设计裁定，本报告如实标注现状）；`writepipe`/`mdcos`/`mcp_server` 面完整透传（新键在场）。对拍侧：kept/truncated 的**值不参与**跨面对拍（`_norm_known_ext` 先剔除再比较，`test_mode_parity.py:645-653`、比较点 `:681-682`），只做「在场」断言（`:693-698`）。
- **Q7·legacy 判据**：见 §4.1 该行——判据＝核心三条 **A1/B2/B5** 全部转红即 PASS（`test_cons200_scan_selection.py:498-502`），**不要求「恰好 7 条」**；「打红」是该模式的设计期望，守卫 rc=0 判 PASS。
（Q1「状态与下一步」已由本节开头段覆盖。）

**硬边界遵守情况**：本报告撰写员**只新增本文档一个文件**；**未**改任何源码、**未** `git add/commit/push`、未触在役数据根。落盘前 `git status --porcelain` 实测：` M md_cg/consistency.py`、` M md_cg/test_mode_parity.py`、`?? .zcode/`（宿主目录，会话起始即存在）、`?? md_cg/test_cons200_scan_selection.py`；本报告落盘使未追踪清单新增一项（本文档）。

**报告撰写会话实跑的命令留痕（L1 直跑）**：`python -X utf8 -m md_cg.test_cons200_scan_selection`（正向/`--branch-baseline`/`--legacy-baseline` 三模式）、`python -X utf8 -m md_cg.test_mode_parity`（正向/`--mutate`）、`python -X utf8 -m md_cg.test_p11_consistency`、`python -X utf8 scripts/run_tests.py`、`git rev-parse/diff --numstat/status/show --stat`、`git show HEAD:md_cg/consistency.py` 导出读码——全部只读判定/临时目录建库，可逆、不改仓库状态。
