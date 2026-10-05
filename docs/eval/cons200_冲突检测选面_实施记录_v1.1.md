# cons200 冲突检测选面 修复记录 v1.1-r1（收口轮；按读者反馈逐条修订）——索引序静默截断 → 相关性预筛＋保底面＋面内例外＋超限可观测

**版本行**：v1.1-r1（收口轮；v1.1 主体＋按读者反馈逐条修订——处置明细见 §七）
**落位说明（编排侧收口）**：本文件原名 `docs/eval/undefined_修复记录_v1.0.md`（run args 丢失所致，来由见「『undefined』来由」节）；编排侧收口更名为 `docs/eval/cons200_冲突检测选面_实施记录_v1.1.md`，报告内容未由编排侧改动。**文件名版本（v1.1）与版本行（v1.1-r1）分属落位约定与修订轮次，二者不一致非笔误**。
**日期**：2026-10-03 ｜ **被测面**：`<仓根>` 工作树（**未提交**——`git status --porcelain` 实列 `M md_cg/consistency.py`、`M md_cg/test_mode_parity.py`、`?? md_cg/test_cons200_scan_selection.py`、`?? docs/eval/cons200_冲突检测选面_实施记录_v1.0.md`、`?? .zcode/`）｜ **基线**：HEAD `9a1150dd21f4d7cb0d2a48933ea559a15518f7bd`〔本报告实跑〕

**本报告覆盖的闭环**：第一轮缺口 → 补齐（两最小条件＋三处增补）→ 第二轮复核。

**关联**：
- `docs/eval/cons200_冲突检测选面_实施记录_v1.0.md`（mtime 2026-10-03 10:45，本报告实测）＝**第一轮快照**（23 断言/5 变异/F1「未修」等表述）；本报告为收口轮记录，状态口径以本报告为准（该文档本身未动——报告撰写轮硬边界；是否加指向本报告的注记需改另一文件，留给维护者，见 §六）。
- 设计稿签收点 5（`docs/plans/stg条件化与结构索引_设计_v0.1.md`，第二实现批）；issue #52 同族不同模块（`md_cg/stg.py`）。
- **「undefined」来由（契约偏离声明）**：本工作流 ask 的缺陷/契约字段渲染为 `undefined`（run `dwfrun-9d53a69a` 系 AmendWorkflow 启动、无 `args` 段，`__host.args.defect/contract` 为空 → `String(undefined)`）；按工作树证据（守卫初版、上述实施记录 §五、`.zcode/workflow-drafts/consistency选面修复-第二实现批.dwf.ts:50-52` 的 GAPS 常量）恢复缺陷＝**cons200**、待实施契约＝收口轮两缺口（①面内例外 ②无词面口径定点断言）；编排侧收口已更名为 `cons200_冲突检测选面_实施记录_v1.1.md`。〔工作流采集·修复段〕

**证据分级声明**：

| 标记 | 含义 |
|---|---|
| 〔本报告实跑〕 | 本报告撰写员在本次 ask 内亲手执行并核对（守卫三模式 / mode_parity 正向 / `scripts/run_tests.py md_cg`＋全量 / h4 守卫 / big 库最终版读数复现 / sha256 与行数 / git 面 / 全仓检索 / HEAD 与工作树行号读码） |
| 〔工作流采集·修复段〕 | 修复工作流采集材料（9 条修前复现腿、实施 changes、探针）——**转录**，不代跑不代补 |
| 〔工作流采集·复核段〕 | 两轮独立复核采集材料（判定/证据/uncovered）——**转录** |
| 〔工作流采集·编排侧〕 | 容器两栈退出码——**转录，未复跑**（需容器装置，本次未尝试） |

**行号口径**：改前行号＝`git show HEAD:` 导出后逐行核实；改后行号＝读工作树文件核实——均为〔本报告实跑〕读码所见。

---

## 〇、图例与口径速览（v1.1-r1 新增）

### 0.1 编号体系一览（防撞号）

| 体系 | 含义 | 出处 |
|---|---|---|
| **L1–L9** | §二 修前复现腿编号（L1 条件互斥漏检 … L9 工作树对照） | §二 表 |
| **「L1 直跑」** | 工作纪律第 17 条的「L1 只读判定可直跑」**层级名**——与复现腿 L1 **不同义**（本报告文末已改称「只读直跑」以免再撞） | 文末 |
| **G1–G6** | cons200 守卫的**内容分组**（G1 选面 / G2 对拍 / G3 可观测 / G4 成本 / G5 语义红线 / G6 收口轮缺口闭合） | `md_cg/test_cons200_scan_selection.py:31-51` |
| **A1–A4 / B1–B5 / C1–C6 / D1–D4 / E1–E4 / F1–F4** | 上述六组的**断言编号**（27 条，逐条见 0.2） | 同上 |
| **①–⑥** | 守卫 `--branch-baseline` 的**定点变异编号**（逐条见 0.3） | `test_cons200_scan_selection.py:644-654` |
| **Q 组** | `test_mode_parity` 的**对拍组**（15 项，见 0.4） | `md_cg/test_mode_parity.py` |
| **H-4(a)** | 并发纪律「迭代点取快照」（见 0.5） | 下条 |

### 0.2 守卫断言图例（27 条一句话；分组见 0.1）

| # | 内容（源标签摘要） |
|---|---|
| A1 | 索引序尾部的冲突对（c1 面）被检出（修前扫描面读不到它；选面回退即红） |
| A2 | 尾部冲突对使判定进入 DEFER/强度 ≥ CLASH_HIGH |
| A3 | 索引序尾部的纪律节点（discipline 面）被检出（REJECT） |
| A4 | layer 面：contextual 层冲突对在层过滤后照常检出 |
| B1 | 修后检出集 ⊇ 修前（legacy 形态运行时重建） |
| B2 | 修复有效：存在「修前漏检、修后检出」的新增检出 |
| B3 | 新增检出非空且**只能来自原被切面**（逐条核验：不在修前扫描面内） |
| B4 | 修前扫描面内的检出（保底面）修后逐条仍在 |
| B5 | 尾部冲突对：修前漏检、修后检出（缺陷取证的守卫内复现） |
| C1 | 候选超限 ⇒ truncated=True（修前无任何标记） |
| C2 | 口径：scanned>kept（scanned=预筛后候选数、kept=实际精比数） |
| C3 | kept 覆盖全部相关候选（≥3：a_conf/zz_offline/zz_disc）且 ≤2×MAX_SCAN |
| C4 | 截断附可操作 hint（含「细化生效条件/不适用条件」「条件索引」语义） |
| C5 | 未超限：truncated=False、不附 hint、scanned==kept（口径自洽） |
| C6 | MCP 面（`_consistency_call`）同批读数随返回体透传 |
| D1 | 读盘数＝kept（预筛/选面阶段零读盘；未全量读盘） |
| D2 | 相关候选（a_conf/zz_offline/zz_disc）全部进入精比面（kept≥3） |
| D3 | 无条件内容：剔除档只剔**面外**非纪律候选（面内一律保留；读盘＝kept＝scanned＝201） |
| D4 | 小库溯源：读盘数＝kept 且不超过全库节点数（快照级候选面） |
| E1 | MAX_SCAN==200 一字未动（契约禁止面） |
| E2 | exclude 自排除语义保持（被排除节点不检出不比对） |
| E3 | 四态照旧：无关条件 → ACCEPT/0.0（小库未超限路径） |
| E4 | 面内例外不误伤：无条件内容下面内声明候选与纪律候选仍比对（comparable=2）、判 ACCEPT 不误报 BLINDSPOT；scanned＝面内＋面外纪律 |
| F1 | 面内例外转正（非同源形态）：条目 tags 置空＋盘面 tags=[discipline]＋落修前扫描面内 ⇒ 无词面输入下仍检出 REJECT |
| F2 | 面外非同源残余：修后与修前形态同判（均不检出）；修前形态重建锚点漂移 ⇒ 本断言转红（fail-closed） |
| F3 | 无词面口径定点：scanned＝面内候选＋面外纪律候选、kept＝scanned、truncated=False、不附 hint、读盘＝kept |
| F4 | 结构保证：无词面输入下修前扫描面（200 名）逐位进入精比面/读盘面 |

**「核心 A1/B2/B5 全红即 PASS」的含义与判据**：`--legacy-baseline` 把「修前形态」在运行时源码上重建后跑**全 6 组×27 断言**；退出判据＝**A1、B2、B5 三条全部转红**（源码 `test_cons200_scan_selection.py:762-767`：`core = {l for l in reds if l.startswith("A1 ")/("B5 ")/("B2 ")}`，`len(core) < 3` 才 FAIL）。这三条的语义（0.2）＝「尾部冲突对可检出」「存在修前漏检修后检出的新增」「L1 缺陷的守卫内复现」——即**「这条守卫抓得住 cons200 缺陷本身」的最直接三条**；legacy 模式**不要求**其余断言也转红。

### 0.3 定点变异表（`--branch-baseline`；预期红项数与旧值→新值）

| # | 变异 | 预期红项数（v1.1 实测＝预期） | 首轮旧值〔实施记录 v1.0 §4.1〕 |
|---|---|---|---|
| ① | 选面回索引序截断（修前形态） | 8 | 7 |
| ② | 去掉 truncated/kept 上报与 hint | 11 | 10 |
| ③ | 预筛把真冲突候选剔掉（假阴性） | 19 | 14 |
| ④ | MAX_SCAN 数值偷调大（契约禁止面） | 10 | 8 |
| ⑤ | 剔除档失效（预筛退化，读盘面回到全候选） | 4 | 2 |
| ⑥ | 去掉修前扫描面例外（收口轮①面内例外失效） | 5 | （新增，无旧值） |

⑥ 的红项**具名**（本报告实跑）：**F1、F3、F4、D3、E4**——恰为面内例外（收口轮①）相关的全部断言。

### 0.4 `test_mode_parity` 引用面图例（Q 组）

- **Q 组＝对拍组**：工作树 vs **HEAD 导出树**（`git archive` 只读导出）上同场景跑写链/插件链，比较观察项读数。
- **15 项对拍清单**（本报告实跑输出）：`A_add、E_fresh、E_weights、full_A、full_B、full_C、full_D、full_E_fresh、full_E_weights、matrix、mode_default、plan_C、plan_D、plan_decide、plg_A`。
- **SAME(15)/DIFF(0)**＝15 项中逐位相同 15 项、不同 0 项。
- **豁免语义**：cons200 批给写链 out 的 consistency 读数**新增** `kept`/`truncated` 两键，而 HEAD 导出树没有——豁免＝**跨代键差**（`_KNOWN_EXT_KEYS` `test_mode_parity.py:642`；`_norm_known_ext` `:646-653` 先剔除这两键再比较）。**旧键仍逐位对拍**。
- **「已知扩展在场」断言**（`:692-697`）：工作树写链 out 的 consistency **必须含**这两键（删新键则转红）。
- **负对照**（`:718-720`）：向导出树副本定点注入「写链 A 新增也需确认」差异 ⇒ DIFF 项**恰好** `A_add/full_A`（证明对拍有判别力）。

### 0.5 术语

| 术语 | 定义 | 出处 |
|---|---|---|
| **过滤（谓词与集合）** | 「过滤后索引序前 limit」中：过滤谓词＝两条 `continue`——`exclude` 命中跳过（`consistency.py:591-592`）＋`layer` 不匹配跳过（`:593-594`）；被滤集合＝exclude 指定节点与该 layer 之外的节点；计数基准＝**通过谓词之后**才 `fidx += 1`（`:595-596`），故「面内」＝过滤后按索引序（`nodes.items()` 快照序）前 limit 名 | 读码；守卫同口径 `_pre_face` `:270-281`、`_face_and_disc` `:284-299` |
| **修前扫描面／面内／保底面** | 修前扫描面＝旧选面逐位形态（过滤后索引序前 limit）；「面内」＝`in_before = fidx < lim`（`:595`）；保底面＝修前扫描面 ∩ 候选（`:617-618`） | 读码 |
| **面内例外与预筛的关系** | 预筛 `_sift_score`（`:322-361`）只**排序、不剔除**；唯一剔除档条件是**三合一**：`no_terms and not disc and not in_before`（`:607`）——`in_before` 为真（面内）即豁免剔除；剔除档与排序无关 | 读码 |
| **no_terms（无词面输入）** | `no_terms = not (tw_pos or tw_neg)`（`:587`）：待检输入（content/condition_space/non_applicable_conditions）经 `_new_terms` 解析出的正/负条件**词面皆空**。触发剔除档。例：L3/L4/L7/L8 载荷（「本次操作：删除生产数据…」无 CCG 条件声明）＝无词面；L1/L2/L5 载荷（含 `# 生效条件：生产环境`）＝有词面（不触发剔除档） | 读码 |
| **H-4(a)** | 本仓并发纪律条目「**迭代点取快照**」：凡从 `cg.index` 取回 `nodes` 后、取用前先 `list(...)`——裸迭代在并发写（前台 add/flush 与后台巡检共享同一实例）下触发 `RuntimeError: dictionary changed size during iteration` | `docs/eval/优化第三批_门禁转正与调度止血与门控收口_v1.0.md` §1.3/§3.3（另见 `issue52_..._修复记录_v1.0.md:26` 术语条）；守卫 `md_cg/test_h4_sustain_snapshot.py:2-5` |
| **43/0** | `md_cg/test_h4_sustain_snapshot`（H-4(a) 全 md_cg 域扫描守卫）的读数：**43 通过 / 0 失败 / 0 跳过**——本报告实跑 `python -X utf8 -m md_cg.test_h4_sustain_snapshot`，rc=0 | 本报告实跑 |
| **可观测「四级/五项」称法** | 第一轮复核材料称「四级皆在场」、实列五项（check 返回体／`_consistency.jsonl` 末行／mcp 返回体／writepipe cvd 及 review_queue／pipeline out.consistency）——本报告按实际列举写「五处」并照录材料称法；**MdCG.add 直连面**另见 §四注 | §五/§四 |

---

## 一、缺陷定义与真实站点

### 1.1 缺陷定义

`consistency.check` 的既有节点比对面＝`list(nodes.items())` 快照的**索引序前 `MAX_SCAN`=200 并静默 break**：条件级真冲突（条件互斥＝DEFER 级；纪律违反＝REJECT 级）落在索引序第 200 位之后即**静默漏检**——不抛异常、返回体无截断标记（无 `truncated`/`kept`/`hint`）、判 `ACCEPT`/强度 0.0。

- **缺陷面**＝一切经该函数的检测：写链全部入口（`MdCG.add` 直连 / `writepipe._gate_consistency` / `mdcos.check_consistency`）与 MCP 检测查询面（`mcp_server._consistency_call`）的公共汇聚点（行号见 §1.2）——写入闸与查询同面。
- **规模**：在役库 17882 节点 ⇒ 检测面 ≈1.1%（≈1.1%＝200/17882 的算术值）。**出处＝守卫 docstring `test_cons200_scan_selection.py:6-10` 的材料陈述——本报告未取证**（未触在役数据根；该库测于何时、现规模是否仍为 17882，本报告无法作答）；「索引序最前 `code_*` 占满名额、`mem_*` 几乎从不进面」同为**构述断言**（同出处）。
- **同族不同模块**：issue #52 修的是 `md_cg/stg.py` 时空接口；前序两 commit（`0d3a0ab2`/`9a1150dd`）文件清单均无 `md_cg/consistency.py`〔转录自实施记录 v1.0；其来源为 `git show --stat` 实跑〕。

### 1.2 真实站点（行号为本报告读码所见）

**改前树（HEAD `9a1150dd`，`git show HEAD:md_cg/consistency.py`，805 LF 行）**：

| 站点 | 内容 |
|---|---|
| `md_cg/consistency.py:61`（HEAD） | `MAX_SCAN = 200`——单次检测最多比对的既有节点数 |
| `:478`（HEAD） | `strength, scanned, comparable = 0.0, 0, 0`（`scanned` 初始位） |
| `:496`（HEAD） | `for nid, e in list(nodes.items()):`——索引序快照迭代 |
| **`:501-502`（HEAD）** | **截断主站点**：`if scanned >= int(limit): break`——静默 break，无任何标记 |
| `:503-504`（HEAD） | `scanned += 1`；`node = cg.get(nid) or {}`（每候选一次读盘） |
| `:514-520`（HEAD） | 纪律违反分支——节点不入扫描面时**不可达** |
| `:630-635`（HEAD） | 返回体 `rec` 仅 `scanned`/`comparable`——无 `kept`/`truncated`/`hint` |

**改后树（工作树 `md_cg/consistency.py`，931 行；收口轮最终态）**：

| 站点 | 内容 |
|---|---|
| `:61-64` | `MAX_SCAN = 200` 数值未动；注释改为「相关面/保底面各自的限额」 |
| `:69-75` | `_SCAN_HINT`（截断可操作提示：细化生效条件/不适用条件、建索引方向、明劝阻调大数值） |
| `:322-361` | `_sift_score`：快照级相关性预筛（只读条目 `tags`/`rejection_terms`；零读盘零正文解析） |
| `:487` | `check` 上方「生效条件：」注释（同步面内例外语义） |
| `:505-533` | `check` docstring 选面节（含 `:528-532` 非同源形态诚实边界原文） |
| `:584-585` | `order = list(nodes.items())`（H-4(a)：快照后再迭代） |
| `:591-596` | 过滤谓词（exclude/layer）与 `in_before = fidx < lim`（面内判定；定义见 §0.5） |
| **`:607`** | **面内例外（收口轮①）**：`if no_terms and not disc and not in_before: continue`——剔除永不触及修前扫描面 |
| `:612-621` | 相关面（`_sift_score` 序前 limit）∪ 保底面（过滤后索引序前 limit ∩ 候选）；`scanned`/`kept`/`truncated` 落点 |
| `:634-641` | 精比循环纪律分支（`_ban_hit` 子串命中断 REJECT） |
| `:750-756` | 返回体 `rec`（含 `kept`/`truncated`，旧键全在场） |
| `:759-760` | `truncated` 为真附 `hint` |
| `:772` | `log(cg, rec)`——**无条件**写 `_consistency.jsonl`（截断可观测的留痕面，见 §四注） |

**消费面（`md_cg/mdcg.py` 等未改文件＝HEAD 行号）**：

| 站点 | 内容 |
|---|---|
| `mdcg.py:2169-2185` | `MdCG.add` 直连块：`:2172-2175` `_cons.check(...)`（**不设 limit**，缺省＝MAX_SCAN）；`:2177-2178` REJECT＋`on_conflict="reject"` → 抛 `ConsistencyError`；`:2181-2185` `extra["consistency"]` 只投影五旧键（`verdict/reason/strength/emotional/unresolved_id`） |
| `mdcg.py:1714-1716` | 「非合作写者协议」声明（`_dir_fingerprint` docstring：外部直改文件内容属非合作写者协议，见 readcache 同款声明） |
| `writepipe.py:283-303` | `_gate_consistency`：`:296-302` 调 `cg.check_consistency(...)`（不设 limit）；`:303` `ctx["cvd"] = cvd`（完整读数透传） |
| `mdcos.py:4410-4433` | `check_consistency`：`:4412` `limit=consistency.MAX_SCAN` 缺省；`:4427-4433` 直通 `consistency.check` |
| `mcp_server.py:1285-1310` | `_consistency_call`：`:1301` `limit=int(a.get("limit") or consistency.MAX_SCAN)`；`:1296-1303` 直通 |

---

## 二、修前现场（本工作流采集的复现腿）

〔工作流采集·修复段〕；「修前」＝HEAD 行为。**共同事实：可运行腿全部无未捕获异常/崩溃**——缺陷形态＝静默漏检（L1–L6、L9 对照）与写面静默放行（L7）；L8 的异常是该载荷**应得**处置（对照取证）。库形态：big＝203 候选合成库（201 条带声明填充＋索引序尾部 `zz_tail_offline`〔位次 201，`# 不适用条件：生产环境`〕、`zz_tail_disc`〔位次 202，`tags=[discipline]`、禁令「删除生产数据」〕；前 200 面经脚本逐位核验不含二者）。

**载荷词面归类**（用 §0.5 的 no_terms 定义）：L1/L2/L5 载荷含 `# 生效条件：生产环境`＝**有词面**（不触发剔除档）；L3/L4/L7/L8 载荷＝**无词面**（触发剔除档）。**腿编号 L1–L9 与文末「L1 直跑」（纪律第 17 条层级）不同义**（§0.1）。

| # | 腿 | payload（关键项） | observed（异常/崩溃点） | site | reproduced |
|---|---|---|---|---|---|
| L1 | **核心腿**·条件互斥（DEFER 级）漏检 | 内容＝`# 功能名：生产批处理\n# 生效条件：生产环境\n`（有词面）；big 库；limit 缺省＝MAX_SCAN | **无异常（静默漏检）**；`verdict='ACCEPT' reason='无冲突' strength=0.0 conflicts=[] scanned=200 comparable=200`——尾部真冲突对未入检出，返回体无任何截断标记 | `consistency.py:501-502`（HEAD） | true |
| L2 | 对照·位置性 | 同 L1 载荷＋`limit=300` | 无异常；`DEFER strength=1.0 conflicts=['zz_tail_offline'] scanned=203 comparable=203`——同一循环同一载荷，仅限额越 200 位即检出 ⇒ L1 漏检是**位置性**的 | `consistency.py:496-506`（HEAD 同一循环） | true |
| L3 | **核心腿**·纪律违反（REJECT 级）漏检 | 内容＝`本次操作：删除生产数据，并清理相关日志\n`（无词面）；big 库 | **无异常（静默漏检）**；`ACCEPT/0.0/scanned=200`——REJECT 级真冲突被吞；纪律分支因节点不在扫描面而不可达 | `:501-502`（静默 break）；`:514-520`（不可达分支） | true |
| L4 | 对照·位置性 | 同 L3 载荷＋`limit=300` | 无异常；`REJECT strength=1.0 conflicts=[('discipline','zz_tail_disc',1.0)] scanned=203` | `:496-506`（HEAD） | true |
| L5 | 对照·载荷真实性 | L1/L3 载荷 @ mini 3 节点库（不涉限额） | 无异常；clash→`DEFER 1.0 ['zz_mini_offline']`；disc→`REJECT [('discipline','zz_mini_disc')]`——两载荷均为真冲突 | `:496-506`（未截断路径） | true |
| L6 | 腿·静默性 | 不注入载荷：读 L1 返回体＋big 库根 `_consistency.jsonl` 末行 | 无异常；返回体 keys＝14 个（`actor/comparable/conflict_strength/conflicts/emotional/layer/missing/neg/pos/reason/recursion/scanned/t/verdict`）——**无 `truncated`/`kept`/`hint`**；jsonl 末行同键集；`scanned=200=MAX_SCAN` 且无告警 | `:630-635`（HEAD rec 仅 scanned/comparable） | true |
| L7 | **核心腿**·写面静默放行 | `cg.add('mem_probe_evil', <L3 载荷>, layer='knowledge', consistency=True, on_conflict='reject')` @ big 库 | **无异常抛出**；返回 `'mem_probe_evil'`（落盘 `landed=True`）——REJECT 级纪律违反经写链闸静默落盘（对照 L8） | `mdcg.py:2170-2185`（直连不设 limit）；截断点 `consistency.py:501-502` | true |
| L8 | 对照·写面应拒 | 同 L7 调用 @ mini 库 | **抛 `ConsistencyError`**：`[REJECT] 命中纪律节点的不适用条件（negative.reject）`——该载荷在写面应得的处置 | `mdcg.py:2177-2178` | true |
| L9 | 归因对照·工作树（含未提交修复）同场景检出 | L1/L3 载荷＋新临时库（同构造）@ 工作树代码（HEAD＋未提交 diff） | 无异常；P_CLASH→`DEFER 1.0 ['zz_tail_offline'] scanned=203 kept=202 truncated=True`；P_DISC→`REJECT [('discipline','zz_tail_disc')] scanned=1 kept=1 truncated=False`——与 HEAD 漏检逐位对照，行为差异归因于该批 diff | 工作树 `consistency.py`；对照 HEAD `:501-502` | true |

**L9 采集版本与「哪组数字对应交付代码」（v1.1-r1 补）**：L9 的 P_DISC `scanned=1` 说明其采集版本＝**收口轮①（面内例外）落地前**的工作树 diff（该版本 no_terms 输入下，面内非纪律候选被剔除，候选仅剩面外纪律 1 名）。**最终版（交付代码）同构造读数**（本报告实跑，203 节点同构库）：

| 场景 | 最终版读数〔本报告实跑〕 | L9 采集读数（面内例外前） |
|---|---|---|
| P_CLASH（有词面） | `DEFER 1.0 [zz_tail_offline] scanned=203 kept=202 truncated=True hint=True` | `DEFER 1.0 [zz_tail_offline] scanned=203 kept=202 truncated=True`（两版一致——有词面输入不触发剔除档，面内例外不参与） |
| P_DISC（无词面） | `REJECT 1.0 [zz_tail_disc] scanned=201 kept=201 truncated=False`（面内 200 名豁免剔除 ＋ 面外纪律 1＝201，与 §3.1/§5.2 收口轮②口径一致） | `REJECT [zz_tail_disc] scanned=1 kept=1 truncated=False` |

即：**「交付代码对应哪组数字」＝上表左列**；L9 右列为历史版本读数（其「与 HEAD 对照」的归因价值不受影响）。其余腿（L1–L8）为 HEAD 行为采集，无版本歧义；本报告未对其余腿做最终版逐条重跑（见 §七 条目 18）。

---

## 三、修法契约与落点（含复核缺口补齐）

### 3.1 契约（三条硬线＋可观测＋收口轮两缺口）

〔工作流采集·修复段〕＋守卫 docstring（`test_cons200_scan_selection.py:12-19`/`:21-29`，读码核实）：

| # | 契约 | 机械钉法 |
|---|---|---|
| C1 | **MAX_SCAN 数值不动**（200；数值放大不是修法） | `consistency.py:61-64`；守卫 E1；变异④（偷调 2000 → 红 10） |
| C2 | **修后检出 ⊇ 修前**（结构保证：保底面＝过滤后索引序前 limit ∩ 候选，逐位保留） | `:612-621`；守卫 B1/B3/B4；变异①（回索引序截断 → 红 8）、③（剔真冲突候选 → 红 19） |
| C3 | **预筛不读盘**（快照级；只读条目 `tags`/`rejection_terms`） | `:322-361`；守卫 D1（读盘数==kept）；变异⑤（剔除档失效 → 红 4） |
| C4 | **截断不静默**（`scanned`/`kept`/`truncated`＋超限 `hint`） | `:69-75`/`:759-760`（＋`:772` jsonl 留痕，见 §四注）；守卫 C1–C6；变异②（去上报与 hint → 红 11） |
| **收口轮①** | **面内例外**：剔除永不触及修前扫描面——「修后 ⊇ 修前」成为**与「条目 tags 与盘面 fm.tags 同源」无关的结构保证** | `:607`；守卫 F1/F4；变异⑥（去面内例外 → 红 5） |
| **收口轮②** | **无词面口径定点**：`scanned`＝面内候选＋面外纪律候选、`kept=scanned`、`truncated=False`、不附 hint | 守卫 F3（独立重算 200＋1）；D3/E4 同步改写 |

**判据一字未动**：阈值/覆盖计算/四态路由未改；本批只改**选面与读数**（`consistency.py:533` docstring 同款声明）。

### 3.2 落点表（收口轮最终工作树，读码核实）

- **实现侧**（`md_cg/consistency.py`）：`:607` 面内例外（`and not in_before`）；`:591-596` 过滤与面内判定；`:487`/`:505-533` 注释与 docstring（面内例外＋非同源诚实边界 `:528-532`）；`:612-621` 相关面∪保底面；`:750-760` 读数与 hint；`:772` jsonl 留痕。
- **守卫侧**（`md_cg/test_cons200_scan_selection.py`，791 逻辑行）：新夹具 `_mk_gapface` `:170-187`（非同源·面内 7 节点）/`_mk_tail_residual` `:190-203`（非同源·面外 261 节点）；`_Fixtures.close` `:216-243`（从 `mdcg._LIVE_CGS` 摘除＋优雅 close＋删目录）；助手 `_face_and_disc` `:284-299`（`:291` H-4(a) 快照）；G6 四断言 `:497-562`（F1 `:506`/F2 `:537`/F3 `:548`/F4 `:559`）；D3 `:450-455`、E4 `:488-493`（按面内例外语义改写）；变异 ⑥ 于 `:653`；`_MUTATION_PINS` `:611`、`_mutation_table_gaps` `:615-641`；`_branch_baseline` TABLE-GAPS 接入 `:697-700`＋锚点预检 `:701-707`；`_legacy_baseline` 接入 `:747-750`＋判据 `:762-767`；`main` 接入 `:771-776`；F2 漂移转红 `:517-522`。
- **同步面**（`md_cg/test_mode_parity.py`）：`_KNOWN_EXT_KEYS` `:642`、`_norm_known_ext` `:646-653`、Q 组比较点 `:681-682`、「已知扩展在场」`:692-697`、负对照 `:718-720`——定向豁免 `kept`/`truncated` 两**键**。

### 3.3 复核缺口补齐（第一轮缺口 → 补齐）

〔工作流采集·修复段/缺口补齐段〕：

1. **F1 面内例外（收口轮①）**——第一轮复核 F1「判据分叉缝」的闭合：剔除档加 `and not in_before` 后，非同源形态（条目 tags 置空＋盘面 tags=[discipline]）的面内候选仍进精比面、由**盘面判据**裁决：「修后 ⊇ 修前」不再依赖「同源」前提。自建实测（第二轮复核）：gapface_ns（7 节点，`q_ns` 落面内）→ 现行 `REJECT [(discipline,q_ns)]`、读盘 7==独立重算；面外残余（tailns_ns，261 节点）→ 修后与修前**同判 ACCEPT**（不构成回归，已声明边界）。
2. **无词面口径定点（收口轮②）**——`no_terms` 输入下 `scanned==kept==201`（＝面内 200＋面外纪律 1）、`truncated=False`、不附 hint、读盘 201 名含 `zz_disc`；与独立重算逐位一致（第二轮复核）；守卫 F3/F4 为定点钉。
3. **三处增补**（超出两最小条件字面，对齐姊妹守卫标准，可整段回退）：①**防误删自检**（`_MUTATION_PINS`＋`_mutation_table_gaps`＋三入口 fail-closed rc=2——直查第一轮 uncovered#3「内存删⑥ rc=0」）；②**夹具临时目录残留修复**（根因＝进程退出兜底 `_atexit_flush_all` 对存活实例 `close()` 把 `_index.json`/`.lock` 写回已删根；修后三连跑零残留——uncovered#8 的 cons200 面）；③**H-4(a) 快照纪律**（定义见 §0.5；`consistency.py:585`、守卫 `:291`；h4 域扫描点名后 43/0 复绿——43/0 读数本报告实跑复核，见 §0.5/§四）。
4. **偏离声明**（转录）：D3/E4 因面内例外语义变化必须改写（原 23 断言无法保持原值）；六处变异预期值按实测重校（配对见 §0.3；逐处「恰好命中」与零空转不变）；「报告与工作树漂移」（uncovered#2）＝报告撰写阶段职责——**本报告即该条的收口**（该条所指 `cons200_...实施记录_v1.0.md` 仍为第一轮快照、未改，如实保留）。

### 3.4 同步面豁免的语义与「值漂移谁兜」（v1.1-r1 补）

- **豁免的是什么**：Q 组比较时先经 `_norm_known_ext` 剔除 `kept`/`truncated` 两键再逐位比对——豁免的是**「工作树 vs HEAD 导出树」的跨代键差**（HEAD 侧根本没有这两键，不豁免则必然 DIFF），**不是**说这两键的值可以任选。
- **值由谁兜**：两键的**口径与结构**由 cons200 守卫的 C1–C6/D3/F3 兜（check 层断言：`truncated`⟺`scanned>kept`、`kept`≤2×MAX_SCAN、未超限 `scanned==kept`、超限附 hint、MCP 透传、无词面口径定点）；`mode_parity` 只负责**「键在场」**（`:692-697`）与旧键逐位对拍。即：**跨模式键差豁免、check 层值口径另钉**。
- **豁免后这两键的可观测性还剩几层**：仍有三层——`check` 返回体（含 hint）、`_consistency.jsonl` 留痕（`:772`）、mcp/writepipe/pipeline 各透传面（§五）；`MdCG.add` 直连的返回体投影不含它们（§四注）。

---

## 四、验证数字

### 4.1 本报告实跑（撰写/修订轮亲手执行）

| 项 | 命令（原样） | 结果 |
|---|---|---|
| 守卫·正向 | `python -X utf8 -m md_cg.test_cons200_scan_selection` | **27 通过 / 0 失败，rc=0**（G1 4＋G2 5＋G3 6＋G4 4＋G5 4＋G6 4＝27 断言；逐条内容见 §0.2） |
| 守卫·变异自证 | 同上 `--branch-baseline` | **rc=0**；未变异基线 27 条全绿；六处变异打红 **①8 ②11 ③19 ④10 ⑤4 ⑥5** 逐处==预期（配对与旧值见 §0.3）；**空转断言 0**；判别力自证 PASS |
| 守卫·⑥红项具名 | 定制探针（`G._build_mutant(G._M6)`＋`G._activate`＋`G._run_groups`，内存态、未改文件） | 打红 5 条＝**F1、F3、F4、D3、E4**（面内例外相关断言全数） |
| 守卫·修前形态 | 同上 `--legacy-baseline` | **rc=0**；打红 8 条＝**A1/A3/B2/B3/B5/D3/E4/F3**。判据＝核心 **A1/B2/B5** 全红（源码 `:762-767`，含义见 §0.2 末）；**F1/F4 在该形态下按设计绿**（F1：判据不依赖面内例外——小库不受截断、盘面判据本就判 REJECT，其红项钉是变异⑥；F4：legacy 形态下面内候选仍全部进读盘面，集合包含关系不破）——已由本报告实跑名单（8 条不含二者）与⑥红项名单（含二者）双向证实 |
| 对拍守卫·正向 | `python -X utf8 -m md_cg.test_mode_parity` | **64 通过 / 0 失败，rc=0**；Q 组 SAME(15)/DIFF(0)（15 项清单与判据见 §0.4）；「已知扩展（kept/truncated）在场」PASS；负对照 DIFF 恰好 `A_add/full_A` |
| h4 快照纪律守卫 | `python -X utf8 -m md_cg.test_h4_sustain_snapshot` | **43 通过 / 0 失败 / 0 跳过，rc=0**（「43/0」主语与出处见 §0.5） |
| big 库最终版读数复现（L9 对照） | 自建 203 节点同构库＋`consistency.check` 两载荷 | P_CLASH＝`DEFER 1.0 [zz_tail_offline] scanned=203 kept=202 truncated=True hint=True`；P_DISC＝`REJECT 1.0 [zz_tail_disc] scanned=201 kept=201 truncated=False`（与 L9 采集版本对照见 §二末） |
| targeted 套件 | `python -X utf8 scripts/run_tests.py md_cg` | **234/234 通过，3 跳过，rc=0**（含 `PASS md_cg.test_cons200_scan_selection` / `test_mode_parity` / `test_p11_consistency`） |
| **python 全量** | `python -X utf8 scripts/run_tests.py` | **311/311 通过，5 跳过（依赖缺失/平台不符），rc=0** |
| 文件面 | sha256＋行数＋git 面 | consistency.py `74f7baa7…`（931 行）、test_mode_parity.py `590d533e…`（1393 行）、守卫 `87967bb0…`（791 逻辑行）；HEAD `9a1150dd…`；跑完全部测试后三文件 sha256 与 `git status` 逐位未变 |

**「截断不静默」在 `MdCG.add` 直连链（L7 调用方式）的落点**（v1.1-r1 补，本报告实跑）：`MdCG.add` 的返回体/`extra["consistency"]` 只投影五旧键（`mdcg.py:2181-2185`，兼容边界）——但 `consistency.check` 内部**无条件** `log(cg, rec)`（`consistency.py:772`），故该链的 `_consistency.jsonl` 留痕仍含完整读数。实测：经 `MdCG.add(consistency=True, on_conflict='reject')` 落盘后，库根 jsonl 末行 **17 键含 `hint/kept/truncated`**（`verdict=DEFER scanned=203 kept=202 truncated=True hint=True`）；同链换 L3 载荷（P_DISC）则**抛 `ConsistencyError`**（修复版下写面拒绝）。即：直连面的可观测面＝**库根 jsonl 留痕**（而非该入口返回体/fm 投影）。

### 4.2 工作流采集（转录）

- **探针**（两轮复核材料）：删 `g4_cost` 组 → rc=1（基线 27→23、五处红项失配）；注水恒真断言 → rc=1 且点名「Z9 复核注入恒真断言」为空转；锚点漂移两路径 → ANCHOR-MISS＋rc=2；TABLE-GAPS 防误删自检：删⑥/删④/改名 → 三入口 rc=2（完好表 gaps=[]）；`_Fixtures` 夹具多轮运行后 %TEMP% 零 `mdcg_cons200_*` 残留。
- **复核段自跑**：第一轮＝合成库 20 场景×两树＋四条调用腿（称法见 §5.1）＋守卫三模式＋探针＋对拍；第二轮＝24 场景×两树（含 3 非同源）＋F1/no_terms 自建场景＋防误删自检四入口。
- **容器两栈**〔编排侧，未复跑〕：栈一 **rc=0**（`结果: 22 pass / 0 fail`＋`=== 汇总: 43 pass / 0 fail ===`＋`[PASS] smoke_test (linux)`，两数关系未说明）；栈二 **rc=0**（`# cancelled 0 ｜ # skipped 3 ｜ # todo 0 ｜ # duration_ms 11664.166824`，无 pass 计数）。两栈覆盖内容未随材料提供。
- **部署**〔转录自修复段材料；其确认方式（进程启停时间/端口探测）未随材料提供，本报告**未独立核实**〕：在役常驻 MCP server 进程仍为改动前代码——新选面随**服务重启**生效；本轮未重启/未测重启后成本形态。重启的执行者/时点/补测口径＝材料未含（§六 待决）。

---

## 五、独立复核两轮判定与各自 uncovered

〔工作流采集·复核段〕；两轮复核均**只读**（未编辑工作区文件；开工/终检 sha256 与 git status 逐位一致；实验在系统临时目录沙箱自建、跑完清理；HEAD oracle＝`git archive` 导出树）。前史一句：第一实现批复核为 **DEFER**（实施记录 v1.0 §五；uncovered＝F1/② 等，即收口轮两缺口的出处）→ 收口轮补齐 → 下述两轮为本工作流的复核。

### 5.1 第一轮复核：**ACCEPT**

- **复核对象**：工作树未提交的 cons200 修复（`consistency.py` 选面重构＋`_SCAN_HINT`；守卫 `test_cons200_scan_selection.py`；同步 `test_mode_parity.py`）——开工/终检 sha256：`consistency.py 74f7baa7…`、`test_mode_parity.py 590d533e…`、守卫 `f3269fa8…`（当时版本）。
- **证据**（数字集合写清）：
  - **对拍场景集 20 个**＝12 个未截断（small×10＋empty×2）＋8 个截断；**19/20 个语义面两树读盘序列逐位一致**——其余 **1 个＝递归场景**（材料原注「1 个递归场景不比较」，即该场景不做逐位比较、不计入 19）。8 个截断场景上「修后 ⊇ 修前」成立（20/20 场景成立，含未截断场景的空集情形）；verdict 只变强；12 个未截断场景业务键全等。
  - **退化/容错路径集**（与上述对拍集**不同集**）：截断真发生 **6 个场景**（材料列 5 例不等式：263>202、263>12、263>0、262>201、264>202；第 6 例未列）——**注意**：§§「截断 6 场景」与「8 个截断场景」分属这两个不同的场景集，不是同一批。
  - **调用腿**：材料称「四条调用腿」、实列**五名**——`MdCGOS.check_consistency`（→DEFER/263/202；同载荷无词面→REJECT）、`mcp_server._consistency_call`（kept=202/truncated=True/hint 在场）、`writepipe._gate_consistency`（纪律场景→moved_to=review_queue）、`default_pipeline().execute`（truncated=True/kept=202）、`MdCG.add(consistency=True,on_conflict=reject)`（→抛 ConsistencyError）（称法与列举数不一致，照录）。
  - 守卫三模式 rc=0（27/27；变异 8/11/19/10/4/5；legacy 打红 8 条）；截断时 hint 含三语义；四级可观测在场（**材料称「四级」、实列五项**：check 返回体／`_consistency.jsonl` 末行／mcp／writepipe cvd 及 review_queue／pipeline out.consistency；称谓差异照录，见 §0.5）。
- **结论**：修复在复核范围内成立；**未发现反例**。
- **本轮 uncovered**（材料中被后续引用的编号）：
  - **#2** 报告与工作树漂移（材料层：`cons200_...实施记录_v1.0.md` 仍称 23 断言/5 变异/F1「未修」）；
  - **#3** 防误删自检缺失——内存删变异⑥时 rc=0 不转红（其余变异覆盖其标签，删条目无人察觉）；
  - **#8**（cons200 面）夹具临时目录残留——每次运行残留一个 `mdcg_cons200_*` 目录。
  - 其余编号未随材料提供，如实标注（不补造）。

### 5.2 补齐（§3.3）后，第二轮复核：**ACCEPT**

- **复核对象**：工作树未提交的 cons200 **收口轮**修复；工作树快照：守卫 `87967bb0…`（791 逻辑行，含 TABLE-GAPS/`_MUTATION_PINS`/`_mutation_table_gaps`）、`consistency.py 74f7baa7…`、`test_mode_parity.py 590d533e…`；HEAD `9a1150dd…`。
- **证据**（数字集合写清）：
  - 场景集 **24 个**（含 **3 个非同源形态**）：**22 个可比场景**×两树读盘序列逐位一致——剩余 2 个「不可比」的**判据与场景清单材料未给**（不是按「非同源即不可比」推得的数：3 个非同源场景在 22 个可比集内）；第一轮 20 场景 → 第二轮 24 场景的**差集清单材料未给**（可见新增为非同源形态族）。
  - 截断真发生（263>202、263>12、263>0、262>201、264>202）＝**退化路径集**（与 5.1 的「8 个截断场景」分属两集）；`limit=0/−5`→kept=0/读盘 0 不崩；空库 0 读盘不崩；剔除档真发生（无词面输入候选 201 vs 全量 263）。
  - **六条腿**新旧对照（材料点名：`MdCGOS.check_consistency` / `mcp_server` / `writepipe`×2（两种场景）/ `default_pipeline` / `MdCG.add`）——与第一轮「四条（实列五名）」为**不同腿集**（轮次不同）。
  - F1 缺口闭合（自建非同源形态实测）与 no_terms 口径（`scanned==kept==201`）见 §3.3；守卫三模式 rc=0（六变异逐处==预期）；防误删自检：删⑥ → `gaps=['len:5≠6','缺: ⑥']`、四入口全 rc=2；夹具零残留；同步面 mode_parity rc=0（64/0、SAME(15)/DIFF(0)、负对照精确）。
- **结论**：两条最小条件经自建场景与独立复算均成立；**未发现反例**。
- **本轮 uncovered**（7 条，转录）：
  1. **在役库面未取证**（硬边界：未触在役数据根）：17882 规模真库成本与构成、F4「在役纪律投影节点 tags 词形令 `_is_discipline` 判 False」的实效；
  2. **报告与工作树漂移**（材料层）——`cons200_...实施记录_v1.0.md` 仍为第一轮快照；**本报告即该条的报告侧收口**（该文档本身按硬边界未改；加注记的处置见 §六）；
  3. **F2 诚实边界另一支未独立构造**（面外、无 `rejection_terms` 的旧节点、仅声明生效条件的 pos 面冲突）——仅由守卫 docstring 声明覆盖；
  4. **未复跑项**（按复核任务边界）：全量 `scripts/run_tests.py`、容器两栈、`test_mode_parity --mutate`（其中全量已由**本报告撰写轮**补齐实跑：311/311 rc=0；其余两项仍未复跑）；
  5. **部署面**：在役常驻 MCP 进程须重启生效、重启后成本形态未测；
  6. **H-4(a) 快照纪律**仅读码核到（`consistency.py:585`），未做专项运行时测试（注：h4 守卫本体 43/0 由本报告实跑复核，见 §四）；
  7. 系统临时区仍留有执行者时代的 `cons200_*` 材料目录（非本轮生成、未清理以免动他人材料）。

---

## 六、边界与未覆盖（含面外残余与留池面）

**面外残余（已声明边界；措辞按证据强度修订）**：非同源形态下面外节点（条目未标纪律、盘面是纪律）在候选超限时不被精比。**在复核与实现所检的协作写路径下未发现该形态**（写路径经索引增量日志保持条目与盘面同源；非合作写者协议声明见 `mdcg.py:1714-1716`、`readcache` 同款声明）——但**非合作写者路径在在役库中的实际可达性与规模未取证**（uncovered#1），且「在役纪律投影节点词形是否令 `_is_discipline` 判 False」未取证：故本边界是**已声明的探测边界**，不是「已证明全局不存在」。守卫 F2（`:537`）与 docstring `:528-532` 同款声明；第二轮复核实测两树同判 ACCEPT。

**留池面（本轮仍不修/未测）**：
1. **在役库取证**：17882 规模成本与构成、F4 词形实效（`_is_discipline` 对 `work-discipline` 词形判 False 已实证为纯函数——**本报告实跑**复核：`_is_discipline({'tags': ['work-discipline','discipline:1','harness:all','v1.1']}, ...)`→False，对照 `['discipline']`→True、id 前缀 `discipline_*`→True；原出处＝实施记录 v1.0 §5.2 F4 同款实跑。「纪律 REJECT 面对在役投影节点整体失效」与否取决于在役库构成——未取证不下结论）；
2. **F2 诚实边界的 pos 面覆盖缺口**：设计上由条件索引方向解决（`_SCAN_HINT` 指向设计稿），本批不做覆盖断言；
3. **部署面**：常驻 MCP 重启生效与重启后成本形态未测；**重启的执行者/时点与补测口径＝材料未含（待决，材料侧无此信息）**；
4. **MAX_SCAN 数值与判据阈值**：不改（契约禁止面）——`rejection_terms` 只覆盖负条件面、条件级检测非语义蕴含（模块诚实边界）；
5. **材料层**：`cons200_...实施记录_v1.0.md` 保持第一轮快照（硬边界：本报告只写一个文件）——**是否给它加一行指向本报告的注记**：需改另一文件、超出本报告硬边界，留给维护者；未加注记前的状态口径以本报告为准。

**本报告硬边界遵守情况**：只改本文件（`cons200_冲突检测选面_实施记录_v1.1.md`，v1.1-r1 修订）；未改任何源码；未 `git add/commit/push`；未触在役数据根；报告无明文凭据。

**只读直跑留痕**（工作纪律第 17 条「L1 只读判定可直跑」层级——**非** §二 复现腿 L1）：本报告实跑命令（守卫三模式、⑥红项探针、mode_parity 正向、h4 守卫、big 库读数复现、`scripts/run_tests.py md_cg`、`scripts/run_tests.py` 全量、sha256/行数、`git rev-parse/status/show`、全仓检索）——全部只读判定/临时目录建库，可逆、不改仓库状态；跑完后三文件 sha256 与 `git status` 逐位未变。

---

## 七、读者反馈处置（v1.1-r1 修订明细）

| # | 反馈条目（类别） | 处置 | 落点 |
|---|---|---|---|
| 1 | 断言编号无图例；「核心 A1/B2/B5」无法判断（unclear） | **补证据**：新增 §0.2 全 27 条图例＋legacy 判据源码（`:762-767`）与三条核心语义 | §0.2 |
| 2 | H-4(a) 未展开；「43/0」无主语（unclear） | **补证据**：§0.5 给出 H-4(a) 定义与出处；43/0＝h4 守卫「43 通过/0 失败/0 跳过」（本报告实跑） | §0.5、§4.1 |
| 3 | 「过滤后索引序前 limit」定义缺失（unclear） | **补证据**：§0.5/§1.2 给出谓词、被滤集合、计数基准、与预筛的关系 | §0.5、§1.2 |
| 4 | §5.1/§5.2 数目集合互不闭合（unclear） | **改措辞＋标注**：两处「截断」计数分属两场景集；19/20 例外＝递归场景；四条腿实列五名、第二轮六条腿点名；24/22/2 与 20→24 差集标注「材料未给」 | §5.1、§5.2 |
| 5 | 变异新旧值无法对应（unclear） | **补证据**：§0.3 变异表配对 ①7→8、②10→11、③14→19、④8→10、⑤2→4、⑥新增 5 | §0.3 |
| 6 | legacy 判红机制与 F1/F4 缺席（unclear） | **补证据**：判据＝核心三条全红（源码）；F1/F4 按设计绿＋实测⑥红项名单（F1/F3/F4/D3/E4）双向证实 | §四 4.1 |
| 7 | no_terms 未定义（unclear） | **补证据**：§0.5 定义（`:587`）＋§二 载荷归类注 | §0.5、§二 |
| 8 | 两处「L1」同符号（unclear） | **改措辞**：§0.1 编号体系一览＋文末改称「只读直跑（纪律第 17 条 L1 层级）」 | §0.1、文末 |
| 9 | L9 读数与最终口径对不上、版本未标（unsupported） | **补证据**：§二 L9 加采集版本（面内例外前）＋最终版同构库读数（本报告实跑：P_DISC scanned=201）＋1→201 差异解释 | §二末 |
| 10 | 「截断不静默」在 MdCG.add 落不到实处、四级/五项不符（unsupported） | **补证据**：§四注给出实测落点（库根 jsonl 含读数）；§五按五项照录并注明材料「四级」称法 | §四、§五 |
| 11 | 17882 当事实、未取证（unsupported） | **改措辞**：标注出处与未取证；F4 纯函数实证给双出处（本报告实跑＋实施记录 §5.2 F4） | §1.1、§六 |
| 12 | 面外残余「无此形态」绝对语气（unsupported） | **改措辞**：「协作写路径下未发现该形态」＋协议声明出处＋可达性未取证保留 | §六 |
| 13 | 部署断言无来源（unsupported） | **改措辞**：标注「转录自修复段材料；确认方式未随材料提供，未独立核实」 | §4.2 |
| 14 | 文件名 v1.0 vs 版本 v1.1、是否有 v1.0（next） | **说明**：首部注明「路径由任务指定、版本行由收口轮决定，非笔误」；检索 0 命中已录 | 首部 |
| 15 | 重启由谁/何时/口径（next） | **边界**：材料未含——登记为待决 | §六-3 |
| 16 | 旧文档加注记（next） | **边界**：需改另一文件、超出「只写一个文件」硬边界——留给维护者 | §六-5 |
| 17 | 豁免后 kept/truncated 值漂移谁兜（next） | **补证据**：§3.4 豁免语义（跨代键差）＋值口径由 cons200 守卫兜、mode_parity 只钉在场 | §3.4 |
| 18 | §二是否按交付版本重跑（next） | **部分补**：L9 已给最终版读数；其余腿为 HEAD 行为采集（无版本歧义），重跑全表超出本修订范围——如实标注 | §二末 |
| 19 | 非可比/例外场景内容（next） | **边界**：材料未给清单（如实标注）；不推论其是否落在 F2 类缺口 | §5.1、§5.2 |
