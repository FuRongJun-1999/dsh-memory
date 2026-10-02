# issue52 · 条件先行与截断可观测（stg `_scan` 索引序切片·静默截断）——修复工程报告 v1.1

**日期**：2026-10-03（v1.1 同日，按读者反馈逐条修订——处置明细见 **§七**）｜ **缺陷号**：issue52 ｜ **被测面**：`D:\program\dsh-memory-main` 工作树（未提交——5 个已跟踪文件被改 + 新增守卫 `md_cg/test_issue52_scan_condition_first.py`；另有未追踪设计稿与宿主目录，见文末 git 面）

**关联**：
- 设计稿 `docs/plans/stg条件化与结构索引_设计_v0.1.md`（未追踪）——本批为第 1/2 层实施，第 3 层（结构索引 + 条件资格）留池另立；设计稿 §一立约动因即本 #52 的在役复现。
- 同族根因谱系（"理论/工程脱节"）：设计稿 §一对照表第 3 行「限额＝该建索引/细化条件的压力信号」vs 工程实现成「字典序切片」，本项即其修复。

**证据分级声明**（本报告只写有机械证据的事）：

| 标记 | 含义 |
|---|---|
| 〔本报告实跑〕 | 本报告撰写员在本次 ask 内亲手执行并计数（守卫三模式 / python 全量 / cogmap 门禁 / **在役库只读复算** / **B·D 探针** / **腿①小库对拍** / **temp 实查** / 行号读码核实 / git status） |
| 〔工作流采集·修复段〕 | 修复工作流采集材料（8 条修前复现腿 / 实施 changes / targetedSuite），本报告**转录**，不代跑不代补 |
| 〔工作流采集·复核段〕 | 修复工作流的独立复核段采集材料（DEFER 判定 / 四组复核实验），本报告转录 |
| 〔编排侧〕 | 随任务材料传入的编排侧输出（容器两栈），本报告转录、未复跑 |

行号以本报告读码所见为准：改后行号 = 读工作树核实〔本报告实跑〕；改前行号 = `git show HEAD:md_cg/stg.py`（HEAD=`4a138d9f`）核实〔本报告实跑〕。

**术语速览**（v1.1 增，回应「行话首现无释义」；全部为本仓既有概念，出处随条标注）：

| 术语 | 释义 |
|---|---|
| **cross（跨会话视图）** | `session` 缺省 / 空串 / `"*"` 时的视图（`_view_session` 归一后 `sid in ("", "*")`，`md_cg/stg.py:343-344`）——不按会话过滤、读遍所有会话；返回体 `session` 字段回带 `None`。对照面＝**本会话视图**（其它值，只留 `frontmatter.session` 精确相等者） |
| **旧快照** | `index["nodes"][nid]` 条目**缺 `temporal`/`spatial` 键**的索引（旧版本写盘格式）；`_scan` 遇之回退 `cg._read(e)` 读节点文件（判据 `md_cg/stg.py:146` → 回退 `:159-162`），保证旧索引升级后时空字段不静默全空。守卫变异⑦（删回退分支→红 1，D4）与断言 D4 钉住它 |
| **H-4(a)** | 本仓并发纪律条目「迭代点取快照」：凡从 `cg.index` 取回 `nodes` 后、取用前先 `list(...)`（裸迭代在并写下触发 `RuntimeError: dictionary changed size during iteration`）。出处：`docs/eval/优化第三批_门禁转正与调度止血与门控收口_v1.0.md` §1.3「H-4 · N138：共享 `index['nodes']` 字典上的裸迭代 × 并发写」与 §3.3「H-4① 迭代点取快照」（H-4＝该批缺陷条目号；本报告读码核实）。`md_cg/stg.py:136` 与守卫 `:217` 注释沿用该编号 |
| **断言标签 A\*/B\*/C\*/D\*/E\*** | 守卫 `test_issue52_scan_condition_first.py` 的组内编号：G1=A1-A8（条件先行）、G2=B1-B9（截断可观测）、G3=C1-C3（兜底选序）、G4=D1a-D6c（语义红线）、G5=E1（结构）。本报告引用时随文注内容；A1＝「运行期追加序：会话条件命中不被切片吞掉（count=2）」、A3＝「跨会话视图 count=全库 8（修前被静默切为 3）」、C1＝「timeline 超限保留最近 4 条（id 序 t09..t06；字典序切片会保最旧的 t00..t03）」 |
| **Z1 / B 探针** | 复核「删断言探针」的标签：A/C/D/E＝内存删组/删断言/塞假断言/抹锚点四探针；**Z1** 是 D 探针自造的**假断言**名（塞一条无变异能打红的断言以验收空转判据；探针脚本未随材料保留，本报告以等价探针实测该机制，§4.2③）；**B 探针**＝删掉整条变异③而不删断言（§4.2③残余）。 |
| **并集判据** | `--branch-baseline` 的空转检查机制：`reddened` 为**各变异红项集合的并集**（`reddened |= set(reds)`），仅「从未出现在并集里的断言」报空转（守卫 `:603-627`）；它**不检查每条变异是否被表覆盖**——故删掉整条变异不会被自证发现（§4.2③与 §五）。 |
| **在役读数（时点性）** | 在役库 `D:\program\AEIS\data\mdcg\_index.json` 是**活跃写入面**（本报告复算时点：全库最近 1h 新增 7379 条）——任何在役数字必须带**时点与口径**才可对拍（v1.1 新增警示，§4.2④） |

---

## 一、缺陷定义与真实站点

### 1.1 缺陷定义

**一句话**：`md_cg/stg.py::_scan` 把「单次扫描限额 `max_scan`（默认 5000）」实现在**条件过滤之前**的索引序切片上——`list(cg.index["nodes"].items())[:max_scan]`——限额不是「超出该收敛」的压力信号，而是「按 id 字典序静默砍尾巴」。库超 5000 节点后四条后果（复现腿逐条实证，见 §二）：

- **(a) 条件命中被永久排除**：本会话记忆 / layer / 时间窗的命中项落在切片外即消失——运行期新写入节点恰落索引尾部，故「今天新归档的记忆一条都召不回」（腿②在合成库成立）；
- **(b) 选面是无意义的 id 字典序**：时间倒序与归属都还没参与；
- **(c) 截断完全静默**：返回体无任何标记——『该会话没有记忆』与『记忆被切掉』返回体逐位相同（腿⑦）；「读不全」与「读不到」不可区分；
- **(d) 被排除集合随索引物理序漂移**：运行期追加序 vs rebuild 后 `sorted` 写盘序——同库同数据同查询，仅 `rebuild_index()` 即翻转（腿⑥）。**漂移发生在 rebuild / 跨进程重载边界**；同一索引物理序下的重复调用恒同（与 §二「恒态（非抖动）」是两个时间尺度，v1.1 点破）。

扩散面：三接口 timeline / anchors / consistency 共用 `_scan` 同病（HEAD 版调用点 `stg.py:274/304/335`，本报告实跑 grep 核实）；MCP 面 `_stg_call` 不透传 `max_scan`（腿⑤，客户端无法用参数绕过）；DSH 侧 auto-recall（`src/hooks.ts:423`）直连 timeline 默认口径（腿⑧）——三者叠加即**超阈值库上 auto-recall 的注入面被切片锁死：切片外新归档记忆零注入、能注入的只剩切片内旧条目**（在役历史读数：切片内 25 条全 `code_*`；v1.1 按读者反馈收窄措辞，原「恒不注入」过强，见 §七 S2）。

**症状形态 = 静默错答，非崩溃**：全部**运行**复现腿（腿①-⑦）**无异常抛出、无崩溃**——本缺陷没有红灯可看，这是它最贵之处（腿⑧为只读源码核对，异常/崩溃栏不适用）。

### 1.2 真实站点（行号为本报告读码所见）

**改前树**（`git show HEAD:md_cg/stg.py`，HEAD=`4a138d9f`，本报告实跑核实）：

| 站点 | 内容 |
|---|---|
| `md_cg/stg.py:130` | **缺陷主站点**：`for nid, e in list(cg.index["nodes"].items())[:max_scan]:`——条件过滤之前按 id 字典序切片 |
| `md_cg/stg.py:119` | `_scan` 签名 `def _scan(cg, layer=None, max_scan=5000):`——5000 默认深种在扫描层（inspect 签名读数：timeline/anchors/consistency 的 max_scan 默认均=5000〔工作流采集〕） |
| `md_cg/stg.py:274 / 304 / 335` | timeline / anchors / consistency **三接口共性调用点**：`for n in _scan(cg, layer=layer, max_scan=max_scan):`（本报告实跑核对 HEAD 版 `_scan(` 全部调用点所得，三处全中） |
| `md_cg/stg.py:274-277` | session 条件过滤在 `_scan` **返回之后**——切片先于条件发生 |
| `md_cg/stg.py:283-287` | 修前返回体仅 `count / limit / session / items` 四键——无 truncated/scanned/kept 任一标记 |
| `md_cg/stg.py:304-312` | anchors 时间窗判定（q_t/q_b 过滤）同样在 `_scan` 之后 |
| `md_cg/stg.py:335-351` | consistency 判定循环同样在 `_scan` 之后——切片外的自洽性异常静默消失 |
| `md_cg/stg.py:256` | `def timeline(..., max_scan=5000, ...)`——默认限额入口（anchors/consistency 同形） |
| `md_cg/mcp_server.py:3131`（HEAD） | `_stg_call` 入口；三分支 `if op ==` 行 = `:3145 / :3152 / :3156`（HEAD）——**三分支调用均不含 max_scan**，参数被丢弃 |
| `md_cg/mdcg.py:1974` vs `:2996-2998` | 索引物理序的两个来源：rebuild = `return {k: nodes[k] for k in sorted(nodes)}`（字典序写盘）；运行期 `_stage` = `self.index["nodes"][node_id] = entry`（增量尾部追加）——被排除集合随重排漂移 |
| `src/hooks.ts:423` | DSH auto-recall 逐字 `await graph.timeline(recallLimit, sid ? { session: sid } : {}))`——不传 max_scan，恒默认口径（全 `src/` 仅此一处 timeline 调用〔工作流采集〕；本报告读码复核 422-423 两行逐字一致〔本报告实跑〕） |

**改后树**：读工作树核实〔本报告实跑〕，落点表见 §3.2。

---

## 二、修前现场（本工作流采集的复现腿）

八条腿全部 `reproduced=true`（采集材料原值）〔工作流采集·修复段〕；其中**腿①-⑦ 为运行复现、腿⑧ 为源码形态核对**（未运行 TS 栈）——「无异常抛出、无崩溃」一语的适用范围＝腿①-⑦（§七 S1 修正）。**逐条共同事实**：症状一律为静默错答（返回体错值或键缺失），且同一索引物理序下重复调用恒态（非随机抖动；跨 rebuild 的漂移见腿⑥）。

**修前树同场景四读数**（采集材料所载）：`timeline(session='sess-A', max_scan=3) count=0`、`cross count=3`、`anchors count=0`、`consistency scanned=3`，且四者均无 truncated 键。其中 **cross＝跨会话视图**（定义见术语速览）：同一 5 节点小库上，切片保留前 3 项（`aaa_00/01/02`，全 sess-B）故 count=3——它与腿①「`max_scan=None` 时 count=1」（**本会话视图**的命中数）是**两个视图的读数**，不是同一读数的两个值（v1.1 回应「数字对不上」，§七 U1）。本报告以同构小库实跑对拍〔本报告实跑〕（临时库，跑完即删）：修复后 `cross, max_scan=3` → count=5 / scanned=5 / kept=3 / truncated=True / ids=`['zzz_target','aaa_03','aaa_02']`；修复后 `session='sess-A', max_scan=3` → count=1 / kept=1 / truncated=False / ids=`['zzz_target']`。

| # | 腿 | 症状一句话 | 发作点（site） |
|---|---|---|---|
| ① | timeline·小限额等价放大 | 条件命中被切 + 截断静默 | `stg.py:130`（切片）→ 条件过滤 `stg.py:274-277`（其后） |
| ② | timeline·真规模默认口径（5021 节点） | 默认 count=0；cross 5000 vs 全量 5021；新写节点仍召不回 | `stg.py:130` + `stg.py:256`（默认 5000）；索引序 `mdcg.py:1974 / 2996-2998` |
| ③ | anchors·time_window 条件命中被切 | 小库与真规模 count=0（None 对照=1） | `stg.py:130` → 条件判定 `stg.py:304-312` |
| ④ | consistency·扫描面被静默截断 | 切片外异常漏检、读数无标记 | `stg.py:130` → 判定循环 `stg.py:335-351` |
| ⑤ | MCP 面 `_stg_call` 不透传 max_scan | 参数被丢弃（param_dropped=true） | `mcp_server.py:3145 / 3152 / 3156`（HEAD 三分支 `if` 行） |
| ⑥ | 索引序漂移 | 同库同数据同查询，rebuild 前后翻转（flipped=true） | `mdcg.py:1974` vs `2996-2998` → 消费点 `stg.py:130` |
| ⑦ | 截断静默不可区分 | 「目标在库被切」与「会话不存在」返回体逐位相同 | `stg.py:283-287` |
| ⑧ | 临床面（DSH auto-recall） | 源码核对：恒默认口径；未运行 TS 栈 | `src/hooks.ts:423` |

### 腿① timeline·小限额等价放大（条件命中被切 + 截断静默）

- **payload**：临时库 A（5 节点）：`aaa_00..aaa_03`（session=sess-B，temporal=100..103）+ `zzz_target`（session=sess-A，temporal=999，id 字典序尾部）；调用 `stg.timeline(cg, session='sess-A', max_scan=3)`。
- **异常/崩溃**：无异常抛出（**静默错答，非崩溃**）。
- **observed**：`count=0`、`items=[]`（切片=前 3 项，目标在切片外）；同条件 `max_scan=None` 时 `count=1`、`ids=['zzz_target']`（目标确在库、条件本身可命中）→ **切片是唯一障碍**；返回体顶层键 `['count','items','limit','session']`，无 truncated/scanned/kept 任一标记（has_truncated=false）；重复调用恒 0（同一索引物理序下恒态，非抖动）。
- **site**：`md_cg/stg.py:130`（切片）；session 条件过滤在 `md_cg/stg.py:274-277`（`_scan` 返回之后）。
- 日志：`%TEMP%\issue52_repro_v0om5r8a\exp1.log.txt`（该实验根**仍存在**，见 §五.4）。

### 腿② timeline·真规模默认口径 >5000 节点（默认 max_scan=5000 未改）

- **payload**：临时库 C：5021 节点（5020×`aaa_XXXX` sess-B + `zzz_target9` sess-A temporal=999999，索引尾部）；`stg.timeline(cg, session='sess-A')` 默认口径（MCP/auto-recall 形态）；随后 `cg.add('zzz_newmem', session='sess-A')` 再测。
- **异常/崩溃**：无异常抛出。
- **observed**：默认 `count=0`（无上限 `max_scan=None` 时 count=1）；cross 视图默认 count=5000 而全量 5021（静默切 21 条，含目标）；新写入的 sess-A 节点 `zzz_newmem` 以增量序落索引尾部，默认仍 count=0（无上限时 count=2）→ **『今天新归档的记忆一条都召不回』在合成库成立**；全程无截断标记。inspect 签名读数：timeline/anchors/consistency 的 max_scan 默认均=5000。
- **site**：`md_cg/stg.py:130` + `stg.py:256`（默认 5000）；索引序来源：`md_cg/mdcg.py:1974`（重建 sorted(nid) 写盘）/ `mdcg.py:2996-2998`（运行期增量尾部追加）。
- 日志：`%TEMP%\issue52_repro_v0om5r8a\exp2.log.txt`。

### 腿③ anchors·time_window 条件命中被切

- **payload**：库 A：`stg.anchors(cg, time_window=[998,1000], max_scan=3)`（目标 temporal=999 在切片外）；库 D（5021 节点）默认口径同形。
- **异常/崩溃**：无异常抛出。
- **observed**：小库 count=0（`max_scan=None` 时 count=1、ids=['zzz_target']）；真规模默认 count=0（无上限 count=1、ids=['zzz_target9']）；返回体键 `['count','items','query']` 无截断标记。
- **site**：`md_cg/stg.py:130`（切片）→ 条件判定（q_t/q_b 过滤）在 `md_cg/stg.py:304-312`（`_scan` 之后）。
- 日志：exp1.log.txt / exp3.log.txt。

### 腿④ consistency·扫描面被静默截断（切片外异常漏检）

- **payload**：库 A 7 节点：切片内 `aaa_000_inv` 与切片外 `zzz_inv` 各为倒置 time_window（[90,80] / [1990,1980]），`stg.consistency(cg, max_scan=3)` 与 `max_scan=None` 对照；库 D 5021 节点默认口径。
- **异常/崩溃**：无异常抛出。
- **observed**：cut 版 `scanned=3`、`issues=1`（只含切片内 `aaa_000_inv`）；无上限 `scanned=7`、`issues=2`（多出切片外 `zzz_inv`）→ **切片外自洽性异常静默消失且读数无标记**；真规模默认 scanned=5000 而全量 5021；返回体键 `['issues','items','limit','scanned']`，has_truncated=false。
- **site**：`md_cg/stg.py:130`（切片）→ 判定循环 `md_cg/stg.py:335-351`。
- 日志：exp1.log.txt / exp3.log.txt。

### 腿⑤ MCP 面 `_stg_call` 不透传 max_scan（参数被丢弃）

- **payload**：`ms._stg_call(cg, {'op':'timeline','session':'sess-A','max_scan':3})`；对照直调 `stg.timeline(..., max_scan=3)`；另 `ms.call_tool(cg,'stg',{同参})`。
- **异常/崩溃**：无异常抛出（参数被静默丢弃）。
- **observed**：`_stg_call` 带 max_scan=3 得 count=1（等于不传时），直调 stg 同参得 count=0（param_dropped=true 断言成立）；`call_tool` 路径 count=1（恒默认 5000 口径）→ **客户端无法用参数绕过截断**。
- **site**：`md_cg/mcp_server.py:3145 / 3152 / 3156`（HEAD 三分支 `if op ==` 行逐点；采集原区间 3145-3155 的右端盖不住 anchors 调用行 3156，v1.1 按读码逐点列出，§七 S4）。工作树对应三分支行 = `:3152 / :3159 / :3163`。
- 日志：exp1.log.txt。

### 腿⑥ 索引序漂移（同库同数据同查询，rebuild 前后结果翻转）

- **payload**：库 B：先 add `zzz_target`(sess-A) 再 add 4×`aaa_*`(sess-B)；`stg.timeline(cg2, session='sess-A', max_scan=1)` 在 `cg2.rebuild_index()` 前后各调用一次。
- **异常/崩溃**：无异常抛出。
- **observed**：增量插入序（`['zzz_target','aaa_00','aaa_01',...]`）下 count=1、ids=['zzz_target']；rebuild（sorted 写盘，`['aaa_00'..'aaa_03','zzz_target']`）后 count=0、ids=[]；**flipped=true**——盘面与查询均未变，仅索引物理序改变即翻转。
- **site**：`md_cg/mdcg.py:1974`（重建=sorted(nid)）vs `md_cg/mdcg.py:2996-2998`（运行期尾部追加）；消费点 `md_cg/stg.py:130`。
- 日志：exp1.log.txt。

### 腿⑦ 截断静默·『读不全』与『读不到』不可区分

- **payload**：库 D 5021 节点：`stg.timeline(cg, session='sess-A')`（目标在库但被切）vs `stg.timeline(cg, session='sess-X')`（不存在的会话）。
- **异常/崩溃**：无异常抛出。
- **observed**：两返回体**除 session 字段外逐位相同**（count=0 / limit=50 / items=[] / 键集 `['count','items','limit','session']`；identical_but_session_field=true）→ 调用方无法从返回体区分『该会话没有记忆』与『记忆被切掉』。
- **site**：`md_cg/stg.py:283-287`（返回体仅 count/limit/session/items，无截断读数）。
- 日志：exp3.log.txt。

### 腿⑧ 临床面（DSH auto-recall 直连默认口径）——只读源码核对，未运行 TS 栈

- **payload**：只读读取 `src/hooks.ts:411-423`；另对 `src/*.ts` 全文检索 'timeline'。
- **异常/崩溃**：不适用（只读核对，未起进程）。
- **observed**：`src/hooks.ts:422-423` 逐字为 `const text = formatTimelineDecayed(` / `await graph.timeline(recallLimit, sid ? { session: sid } : {}))`——不传 max_scan（`recallLimit` 为 `limit`，≤10，`hooks.ts:407`）；全 src 目录 timeline 调用仅此一处 → **该路径恒默认 5000 口径：超阈值库上注入面被切片锁死——切片外新归档记忆零注入，能注入的只剩切片内旧条目**（在役历史读数：切片内 25 条全 `code_*`）。消费面读码〔本报告实跑〕：`formatTimelineDecayed`（`hooks.ts:265-287`）**只消费 `payload.items`**（逐条取 layer/preview 渲染），不读 count/truncated/kept 任何读数。
- **site**：`src/hooks.ts:423`。
- **声明**：本腿为源码形态核对，**未运行 DSH 宿主/TS 栈**；「零注入」结论为源码路径 + 在役读数推得，宿主端到端未跑（归主会话/使用者排期，§七 Q6）。

---

## 三、修法契约与落点

### 3.1 契约（设计者裁定，2026-10-03）

裁定原文（采集材料所载）：「遇到更多的检索节点，应该要建立索引，明确检索条件，和不适用条件，而不是扩大节点数」。

- **第 1 层·条件先行**：条件过滤（session/layer/时间窗）先于截断——截断只作用于**条件命中集**；
- **第 2 层·截断可观测**：命中集超限时按时间倒序保留近期（id 终键兜底，与索引物理序无关），并在返回体上报 `truncated`/`scanned`/`kept`/`hint`——**禁止静默**；
- **禁止面**：`max_scan` 数值不放大（默认 5000 不动、不改 `None`）；时间倒序只作截断发生时的兜底选序，**不作条件先行的替代**；MCP 面本批不开 `max_scan` 入参（数值不是修法）；
- **第 3 层（留池）**：session/layer/time 结构索引 + 条件资格进 stg，另立 `docs/plans/stg条件化与结构索引_设计_v0.1.md`。

### 3.2 落点表（读工作树核实〔本报告实跑〕；changes 清单来源〔工作流采集·修复段〕）

| 落点 | 内容 |
|---|---|
| `md_cg/stg.py:119-165` | `_scan` 去掉索引序切片与 `max_scan` 形参；只做遍历 + layer/可见性过滤，条件命中全量返回；**保留 `list(...)` 快照迭代**（H-4(a) 并发纪律，见术语速览——去掉的只是切片，不是快照）；旧快照缺键回退读文件路径保留（`:160-162`） |
| `md_cg/stg.py:169-183` | 新增 `_cap_hits`：只作用于条件命中集；不过限时不改序不标记（逐位兼容）；超限时 `sorted(hits, key=recency_key, reverse=True)[:cap]`，负数归 0 |
| `md_cg/stg.py:187-204` | 选序键 `_tl_recent` / `_an_recent` / `_co_recent`——时间倒序 + **id 稳定终键**（结果与索引物理序无关） |
| `md_cg/stg.py:208-211` | `_CAP_HINT` 文案：含「细化生效条件/不适用条件」「建立条件索引」语义，明文劝阻调大 max_scan |
| `md_cg/stg.py:215-220` | `_with_scan_reads`：读数/标记统一出口（scanned/kept/truncated + truncated 时 hint） |
| `md_cg/stg.py:322-367` | `timeline`：session/时间条件先定命中集（`:350-355`）→ `count`=条件命中总数（截断前，`:356`）→ 截断（`:357`）→ 读数（`:360-367`） |
| `md_cg/stg.py:371-413` | `anchors`：时间窗/bbox 命中集先定（`:392-403`，无时间区间者截断时先被截）→ 截断（`:405`）→ 读数（`:409-413`） |
| `md_cg/stg.py:417-456` | `consistency`：候选先定（`:433`）→ 按时间倒序截断（`:435`）→ 逐条检查；`scanned`=遍历读数、`kept`=实际检查数、`truncated`/`hint` 上报 |
| `md_cg/mcp_server.py:3130-3172` | `_stg_call` 仅注释/docstring 同步（返回体原样透传；max_scan 本批不入参）——**零功能改动**；docstring 载「在役对照 timeline(session=…) 由 25 恢复为 229」 |
| `md_cg/provenance.py:434`、`md_cg/test_n204_n205_n226_n227_n228_n229_exit_gates.py:19` | stg.py 行号引用随实现位移同步（133/172→138/233）——**复核判定此两处改锚有误，见 §五** |
| `scripts/linux_verify.sh:49`、`:89-101` | 新守卫入容器 python 清单与判别力自证清单（`--branch-baseline`/`--legacy-baseline`） |
| `md_cg/test_issue52_scan_condition_first.py:1-676` | 新建守卫（36 断言 + 八处定点变异自证 + 修前形态重建 + ANCHOR-MISS 退出码 2） |

---

## 四、验证数字

### 4.1 守卫断言与判别力〔本报告实跑〕

落笔前亲跑（工作树）：

| 命令 | 结果 | 退出码 |
|---|---|---|
| `python -X utf8 -m md_cg.test_issue52_scan_condition_first` | **36 通过 / 0 失败**（G1 条件先行 8 + G2 截断可观测 9 + G3 兜底选序 3 + G4 语义红线 15 + G5 结构 1） | 0 |
| 同上 `--branch-baseline` | 未变异基线 36 全绿；八处变异打红 **24 / 15 / 3 / 4 / 4 / 3 / 1 / 2**，各自**恰好**命中预期、无空转断言 | 0 |
| 同上 `--legacy-baseline` | 修前形态重建打红 **28 条**（含 A1/A3 核心断言——内容见术语速览），判定 PASS | 0 |

八处定点变异明细（`_MUTATIONS`，名称读码核实〔本报告实跑〕，红项数为实跑得数）：

| # | 变异 | 红项数（预期=实得） |
|---|---|---|
| ① | 条件过滤移回截断之后（三接口候选集切片）——契约点名 | 24 |
| ② | 去掉 truncated 上报（读数/hint 一并消失）——契约点名 | 15 |
| ③ | 截断选序改回字典序——契约点名 | 3 |
| ④ | `_scan` 恢复索引序切片（回退 5000） | 4 |
| ⑤ | max_scan 默认改 None（契约禁止面） | 4 |
| ⑥ | `_sec` 可见性闸绕过 | 3 |
| ⑦ | 去掉旧快照回退读文件分支 | 1 |
| ⑧ | layer 过滤失效 | 2 |

基线源 = `inspect.getsource(stg)` **运行时源码**（非 git HEAD——基线绑提交即失效）；锚点漂移报 ANCHOR-MISS + 退出码 2（fail-closed）。

### 4.2 独立复核实验〔工作流采集·复核段〕（③④ 为 v1.1 重写/增补）

- **① 各腿 + 退化路径（真实 MdCGOS 库，temp；oracle=独立目录扫描，自解析 md frontmatter，不用 md_cg 任何代码）**：**21 PASS / 0 FAIL**。(a) 5001 节点真实库 `timeline(session='sess_today')` → ids==oracle、count=1、scanned=5001、truncated=False；同库喂改前实现（git HEAD 运行时装载）→ count=0、ids=[]；`rebuild_index` 后逐位一致。(b) **232 节点在役等价库** `timeline(session='sess_live', max_scan=25)` → count=229==oracle、kept=25、truncated=True、保留集==oracle 最近 25 条（m0204..m0228）；改前 → count=22、选面=索引序前 25 条。**v1.1 补算术**：232 库＝`_mk_live` 的 229 条 `sess_live` 命中 + 3 条异会话填充（守卫 `:173-183`）；`max_scan=25` 切片＝前 25 项＝3 条填充 + **22 条命中**——改前 count=22 由此而来（v1.1 回应「改前到底 25 还是 22」，§七 U2）。(c) anchors 时间窗（修前 count=0→现 2）、consistency 遍历面（修前 scanned=3→现 10）、MdCGSecure 可见性、空池（count=0/scanned=0/truncated=False 且无 hint）各腿均与 oracle 一致。(d) 退化路径『真发生』的见证：旧快照缺键时 `cg._read` 被调 5 次（扫描 3 + 预览 2）；再把 `_read` 换成返回 None → count=0/ids=[]（对照证明该分支承重）。
- **② 合法输入逐位对照**：基线=`git show HEAD:md_cg/stg.py` 运行时装载（已核该源含 `[:max_scan]`、无 `_cap_hits`），同库同调用逐个比对。**24 例**（timeline 缺省/*/session/layer/desc/limit=0/time_axis=effective/max_scan=None/==限额边界；anchors 时间窗/bbox/limit=None/错误面 `need_time_window_or_bbox`；consistency layer/limit；MdCGSecure 面；旧快照回退面）剥掉新增键 `{scanned, kept, truncated, hint}` 后 **dict 全等**、且 truncated=False 且无 hint。**唯一差异项**：`max_scan=-1`（改前 count=9 静默丢尾 → 现行 count=10/kept=0/truncated=True），属 `_cap_hits` 文档化的有意语义变更，守卫未断言它（见 §五）。
- **③ 守卫本体与判别力（复核亲跑；v1.1 补「并集判据」展开与本报告实跑复验）**：主模式 36 通过/0 失败/rc=0；`--branch-baseline` rc=0 红 24/15/3/4/4/3/1/2；`--legacy-baseline` rc=0 红 28 条（含 A1/A3）。删断言探针（复核跑，仅内存改组表/变异表/源码串，文件未改）：A 删 g3 组 → rc=1（③号变异红 0≠预期 3）；C 组内只删 C1 → rc=1（红 2≠3）；D 塞假断言 → rc=1（空转断言点名 Z1）；E 抹掉变异①锚点 → rc=2（ANCHOR-MISS）。**「并集判据」是什么**（v1.1 展开）：空转检查的集合是 `reddened`＝**各变异红项集合的并集**（守卫 `:603-627` `reddened |= set(reds)`），只有「从未出现在并集里」的断言才报空转——它不检查「每条变异是否仍被表覆盖」。**残余（复核已复现；本报告实跑复验〔本报告实跑〕）**：删掉整条变异③（保留全部断言）→ **rc=0 仍 PASS**——C1/C2/C3 已被其它变异（如变异①）的打红并集覆盖，空转检查照过、且「恰好命中」检查因该表目消失而根本不再执行。本报告复验命令与读数：内存删变异③后跑 `_branch_baseline` → 7 条变异全部「恰好命中」、无空转报出、**RC=0**（修复前 8 处→删后 7 处，数字 `24/15/4/4/3/1/2` 全 OK）。机理旁证（本报告实跑）：往组表塞一条恒真断言 `ZZ_FAKE_ALWAYS_GREEN` → rc=**1**、报「空转断言（无任何变异能打红）：ZZ_FAKE_ALWAYS_GREEN」——该探针即 Z1 类机制的等价实测（Z1 本体脚本未随材料保留，不代补其内容）。残余的兜底：真实回归仍由 C1（内容见术语速览）等断言兜住——删变异③只是「自证表被删项不被发现」，不改变实现代码。
- **④ 在役只读核验与「在役数字簇」映射（v1.1 重写：补时点维度 + 本报告复算）**：
  - **转录面（复核段原文）**：纯字节 json.load `D:\program\AEIS\data\mdcg\_index.json`（前后 size/mtime 一致、不构造任何 MdCG）＝**17850 节点**；会话 `sess_1b7a945d2eee` 切片内 25 条全 `code_*`、被排除 206 条含 17 条 `mem_*`（材料记「文档记 25/204/15——差的 2 条即其后新归档的 `mem_*`」）。
  - **本报告复算**（同一文件、同一只读形态〔本报告实跑〕；命令形态：`json.load` → `keys=list(nodes)` → 切片 `[:5000]` 与 `[5000:]` 分别按 session 过滤计数 + `created_at` 分桶 + `mem_*` 清单；另用三接口替身 cg（`index`/`_read`/`get`，不构造 MdCG、不写盘）调修复后 `stg.timeline(session=…)`）：17850 节点（与转录一致）；**修前等价计数**（文件序切片 + session 精确匹配 + iv 可判定）＝**2182**（全 `code_*`；字典序口径 2184，两口径同量级）；**修复后读数**＝`count=7607 / scanned=17850 / kept=5000 / truncated=True`（hint 在场；items 前 3 条为最新 3 条 `mem_*`）；三元组（切片内/切片外/切片外 `mem_*`）＝**（2182, 5425, 17）**；全库 190+ 个会话逐一扫描：**无任何会话**匹配 (25, 204, 15) 或 (25, 206, 17)。
  - **映射表（v1.1 新增：每个数字的口径与归属）**：

    | 时点/口径 | 切片内 | 切片外（被排除） | 切片外 `mem_*` | 修后 count 口径（=切片内外合计） | 出处 |
    |---|---|---|---|---|---|
    | 改造当天文档时点 | 25 | 204 | 15 | **229** | 守卫 docstring `:7-9` / 设计稿 `:3-4`（「默认口径 count=25 且全为 code_*，被切 204 条含 15 条 mem_*」） |
    | 复核时点 | 25 | 206 | 17 | 231 | 复核④（「差的 2 条即其后新归档的 mem_*」→ 229+2） |
    | **t−1h 重建（本报告实跑）** | **25** | **203** | **15** | 228 | `created_at` 分布：切片内 1h 前＝25、切片外 1h 前＝203、`mem_*` 中 15 条 1h 前已在 |
    | 本报告复算时点 | 2182 | 5425 | 17 | 7607 | 本报告实跑（§上） |

  - **闭合证据（本报告实跑）**：该会话全库 7607 条中 **7379 条 `created_at` 落在最近 1h**（＝全库最近 1h 写入 7379，即这一小时的写入全部属于该会话）；切片内 **2182 = 25（1h 前）+ 2157（最近 1h）**；切片外 **5425 = 203（1h 前）+ 5222（最近 1h）**。⇒ **「25」＝本报告复算时点 1 小时前的切片内计数**；文档/复核读数与「t−1h 重建」逐项吻合（25 ✓、`mem_*` 15 ✓）；切片外 204/206 vs 203 差 1~3（端点/归属口径细节未随材料携带，如实列示、不代裁）。⇒ **转录与复算的差＝时点差，不是口径矛盾**；本报告复算时点该会话仍被灌入（1h 内 +7379 条），在役读数必须带时点（术语速览「在役读数（时点性）」）。
  - **`mem_*` 17 条清单（本报告实跑；`id | created_at | time_window 起`）**：`mem_1790886647495_98d4ee | 10-02 11:22:28`、`mem_1790920222222_811995 | 10-02 13:50:22`、`mem_1790928718772_d3dc1f | 10-02 16:11:58`、`mem_1790929887625_14d4c6 | 10-02 16:31:28`、`mem_1790940427663_2cea04 | 10-02 19:27:08`、`mem_1790950852436_b8b374 | 10-02 22:20:52`、`mem_1790958239513_20ecfe | 10-03 00:24:16`、`mem_1790966310900_0dfb1d | 10-03 02:38:33`、`mem_1790967742083_d5ac98 | 10-03 03:02:22`、`mem_1790968454022_f2f1ff | 10-03 03:14:14`、`mem_1790972338945_7fb3d9 | 10-03 04:19:02`、`mem_1790974803253_5372a7 | 10-03 05:00:03`、`mem_1790978846044_ac0ac1 | 10-03 06:07:26`、`mem_1790978888645_c05e8d | 10-03 06:08:08`、`mem_1790979391309_2ef1a2 | 10-03 06:16:31`、`mem_1790979749161_9dd5ef | 10-03 06:22:29`、`mem_1790980310667_baa2e0 | 10-03 06:31:50`（17 条全在切片外、`temporal=None`、时间由 `time_window` 承载）。**15→17 的「差 2 条」**：17 条中**恰 2 条**（`9dd5ef` 06:22:29、`baa2e0` 06:31:50）的 `created_at` 落在最近 1h 内——复核「其后新归档」的推断与时点分布自洽（v1.1 回应 S5；文档 15 条的原始清单未随材料携带，不另裁具体名单）。
  - **「与 #52 临床面吻合」的可检验重述**（v1.1 修正措辞）：`mem_*` 全部落在切片外（17/17）✓、切片内全 `code_*`（2182/2182）✓——#52 的症状面（新归档 `mem_*` 恒在切片外、修前无法召回）在当前时点仍成立，且风险面**仍在扩大**（1h 内切片外该会话 +5222 条）。#52 的原始症状描述在仓内可查面＝守卫 docstring `:7-9` 与设计稿 `:3-7`（引文见映射表）；GitHub issue 原文未随采集材料传入，不代补（§七 Q1）。
  - **未做（如实）**：**未做完整 MdCG 栈在在役库上的调用**（材料纪律「不构造任何 MdCG」保持）；本报告做的是「在役数据 + 替身 cg」的只读调用与纯字节统计（前后 `size/mtime` 一致已核〔本报告实跑〕）。

### 4.3 python 全量与容器两栈

| 检查 | 读数 | 退出码 | 来源 |
|---|---|---|---|
| python 全量：`python -X utf8 scripts/run_tests.py` | `===== SUMMARY 309/309 通过，5 跳过（依赖缺失/平台不符） =====` | 0 | 〔本报告实跑〕（与复核段转录值逐字一致） |
| 容器栈一：`linux_verify.sh`（容器内） | 段内『结果: 22 pass / 0 fail』、`[PASS] smoke_test (linux)`、汇总『=== 汇总: 41 pass / 0 fail ===』 | 0 | 〔编排侧转录〕；本报告环节无容器环境，未复跑；22 与 41 的阶段构成材料未携带，不代裁（§七 Q7） |
| 容器栈二（node 生态） | `# cancelled 0` / `# skipped 3` / `# todo 0` / `# duration_ms 11406.909902` | 0 | 〔编排侧转录〕；摘要未含 `# pass`/`# fail` 计数行——表述收敛为「退出码 0 且摘要无失败项」，不写「全部通过」 |

**新守卫与容器的关系（读码核实〔本报告实跑〕）**：`scripts/linux_verify.sh:49` 已把 `test_issue52_scan_condition_first` 加入容器 python 套件清单、`:101-102` 加入两组基线自证清单（`--branch-baseline`/`--legacy-baseline`）——**清单已入**；「容器里是否已执行过含新守卫的清单」未随转录材料携带，不代证。本机三模式 36/36、24-15-3-4-4-3-1-2、红 28 已实跑（§4.1）。

补充套件读数〔工作流采集·修复段 targetedSuite〕：`python -X utf8 scripts/run_tests.py md_cg` → **232/232 通过、3 跳过、EXIT=0**（首轮唯一红项 `test_h4_sustain_snapshot` 因 `_scan` 首版裸迭代被判红，回修保留 `list()` 快照后转绿，单跑 43/43）；单跑 `test_p47_session_view` 38/38、`test_retr_s8_time` 31/31、`test_h2_session_view_norm` 17/17、`test_p32_backfill` 59/59、`test_n204_n205_n226_n227_n228_n229_exit_gates` PASS=45/FAIL=0、`test_issue52` 36/36。

---

## 五、独立复核判定与它列出的 uncovered

**判定：DEFER**〔工作流采集·复核段〕。依据（复核自述）：

- 【判定】修复本体（条件先行 + 截断可观测）独立复现全绿、守卫有判别力；
- DEFER 的**唯一实质理由**＝本次 diff 自身把**两处源码行号锚改错**、且使仓内 **cogmap 门禁在交付树上为红**（均非行为问题，改正/重算即转 ACCEPT）。

**本报告对两条 DEFER 理由的复核（读码/实跑〔本报告实跑〕）**：

1. **cogmap 门禁为红**：`python -X utf8 scripts/cogmap_sync.py check` → **退出码 1，2 个问题**——README COGMAP 段实际 `#L3143/L3145/L3152/L3156` vs 期望（真源 AST）`#L3150/L3152/L3159/L3163`；FUNCMAP:stg 段实际 `#L3143` vs 期望 `#L3150`。行号差异本源核实：HEAD 版 `mcp_server.py` 的 relation/timeline/anchors/consistency 分支在 `3143/3145/3152/3156`，工作树因本次在 `_stg_call` 内插行在 `3150/3152/3159/3163`（`def _stg_call` 两版同在 3131，插行在函数体内）⇒ 主会话发版清单的 `cogmap_sync.py build` 尚未执行。
2. **两处源码注释锚改错**：`md_cg/provenance.py:434` 与 `md_cg/test_n204_n205_n226_n227_n228_n229_exit_gates.py:19` 把 `stg.py:133/172` 改成 `stg.py:138/233`；核对——HEAD 版 `stg.py:133`=`if _sec is not None and not _sec(e):`、`:172`=`if not guard(e):`（**正是接线点**）；工作树 `:138`= `_scan` docstring 的收尾 `"""`、`:233`=`if not e:`（`_preview` 索引缺失早退）——**均非接线点**；真接线点在 `:144` / `:238`。⇒ 复核判定成立。

**复核列出的残余与未覆盖面**（转录 + v1.1 本报告补验；复核材料未以「uncovered」一词单列名目）：

1. **守卫自证残余（并集判据）**：删掉整条变异③而不删断言 → rc=0 仍 PASS。v1.1 已展开机制（§4.2③）并**本报告实跑复验**（删后 7 条全 OK、RC=0）；真实回归仍由 C1 等断言兜住。
2. **`max_scan=-1` 未被守卫断言**：现行语义（负值归 0 → 截空、truncated=True）是 `_cap_hits` 文档化的有意变更，24 例对拍中为唯一差异项（§4.2②）。
3. **临床面未运行**：DSH/TS 栈（`src/hooks.ts:423` 路径）只做源码形态核对，未运行宿主端到端（腿⑧声明）。
4. **实验面清理声明（v1.1 修正）**：复核段称「全部实验根在 `%TEMP%\i52*`，跑完已删（复查 glob 为空）、工作区零写入」。本报告实查〔本报告实跑〕：`%TEMP%\issue52_repro_v0om5r8a`（修前复现腿实验根，含 `exp1/2/3.py` 与 `exp1/2/3.log.txt`）**仍存在**；`%TEMP%\i52*` 现有 **11 项**（`i52_base_mmhsho5f`、`i52_baseline.py`、`i52_bench_li3zo106`、`i52_commit_msg.txt`、`i52_mdcg_regression.log`、`i52_mdcg_regression2.log`、`i52_probe.py`、`i52_v02_commit.py`、`i52_v02_msg.txt`、`i52perf_aae6j5j1`、`i52t_45d60rey`；mtime 2026-10-01 ~ 10-03 07:01）。⇒ 与「glob 为空」声明不符；**归属不代裁**（可能含实施段遗留与新产生项；本报告自身临时根 `i52rev_*` 已清理，复查为空）。「工作区零写入」一项本报告可佐证：运行前后 `git status --porcelain` 逐位一致（§6.1）。
5. **在役读数时点性（v1.1 新增）**：复核④与本报告复算的差已定位为**时点差**（§4.2④ 映射表）；后续任何在役对拍必须带时点与口径。

---

## 六、边界与未覆盖（含本轮明确不修而留池的面）

### 6.1 硬边界遵守情况

本批只动 `md_cg/stg.py`、`md_cg/mcp_server.py`（注释）、`md_cg/provenance.py`（锚）、`md_cg/test_n204_...py`（锚）、`scripts/linux_verify.sh`（清单），新增 `md_cg/test_issue52_scan_condition_first.py`；**未** add/commit/push，未触在役数据根（在役库只读核验与本站复算均为纯字节/替身只读，未构造 MdCG、未写盘，前后 `size/mtime` 一致）。本报告撰写员只改本文档一个文件：落盘前 `git status --porcelain` 实测为 5 个 M + 3 个未追踪件（与工作流起始快照逐位一致）〔本报告实跑〕；落盘后终态仅本文档这 1 个文件有内容变更（文末附核实）。全文无明文凭据。

### 6.2 明确不修而留池 / 确认不动的面

1. **第 3 层结构索引与条件资格**（session/layer/time 倒排、`judge_qualification` 进 stg）：另立 `docs/plans/stg条件化与结构索引_设计_v0.1.md`（未追踪），本批只落第 1/2 层。设计稿 §四已载验收判据（等价性：flag 开/关三接口返回体除 `meta` 计数外逐位一致；收敛性：`meta` 读数显示实际触碰从 N 降到条件命中量级）——**动作与排期归主会话/使用者，本报告不代裁**（§七 Q9）。
2. **`max_scan` 数值面**：不放大、默认不改 None（契约禁止面；守卫 D1a-c 钉住）；MCP 面不开显式入参（守卫 B9 钉住「入参 max_scan=2 无效、kept=5000」）。
3. **`max_scan=-1` 语义变更**：文档化、故意、未断言（§五.2）。
4. **索引物理序漂移的根因未统一**：`mdcg.py:1974`（sorted 写盘）vs `:2996-2998`（增量尾部）两源并存——本批只保证**结果与索引物理序无关**（id 终键兜底），索引序本身留原样；**无排期材料，记录在案待后续批次**（§七 Q9）。
5. **守卫自证残余**：删整条变异项不自证（并集判据 + 硬编码『八处』）——§五.1。
6. **DSH/TS 栈端到端未运行**（临床面只做源码核对）；宿主端排期归主会话/使用者（§七 Q6）。
7. **cogmap 锚与两处注释锚待改正/重算**（非行为问题，改正即转 ACCEPT）。**转 ACCEPT 的动作清单**（§七 Q3）：`python scripts/cogmap_sync.py build`（重算 README/映射表锚点）+ 两处注释锚改回真接线点（`:144`/`:238`，或随实现重定位后同步）。其余发版门禁见 `package.json` 的 `gate` 单点（9 条腿：check_unreachable / check_publish_artifact / check_publish_smoke / cogmap_sync check / link_check / workspace_index check / verify_discipline / gate_rust_crate_test / gate_rust_parity〔本报告读码〕）——本报告未逐条跑该清单。
8. **MCP 面 `max_scan` 入参的静默丢弃（v1.1 新增留池）**：契约「数值不是修法」决定本批不开入参，但「传了被丢弃且无任何告警」（腿⑤现状保留）本身是静默的——与「禁止静默」原则的这条残余不一致归**后续批次/使用者裁定**（§七 Q5；本报告不代裁其是否冲突）。
9. **在役读数的时点口径（v1.1 新增留池）**：在役库为活跃写入面，本次已完成一次带时点的映射（§4.2④）；「在役对拍须带时点」宜写入后续在役核验的惯例（本报告只建议，不代裁流程）。

---

## 七、v1.1 修订记录（读者反馈逐条处置）

| # | 反馈（类别） | 处置 | 落点 |
|---|---|---|---|
| U1 | cross 全文无定义；L61 cross=3 与腿① count=1「对不上」（unclear） | 术语速览加「cross（跨会话视图）」条目（定义 + 代码出处 `stg.py:343-344`）；§二开头重写：cross=3 与 count=1 是**两个视图**的读数，并补**本报告实跑**同构小库对拍（修后 cross max_scan=3 → count=5/kept=3/truncated=True；修后本会话 count=1） | 术语速览；§二 |
| U2 | 在役数字簇无映射表（25/204/15 指什么、「文档」是哪份、232 库与 17850 库关系、改前 25 还是 22）（unclear） | §4.2④ 重写：新增**映射表**（含时点列与出处）——25/204/15＝改造当天文档时点（守卫 docstring `:7-9`/设计稿 `:3-4`）切片内/切片外/切片外 `mem_*`；「232 节点在役等价」＝temp 合成库（229 命中+3 填充），与 17850 在役库是**等价对照**非同一库；改前 25（在役默认口径历史读数）× 22（232 库 `max_scan=25` 切片＝3 填充+22 命中，§4.2①(b) 补算术）；并补**本报告复算**（2182/5425/17、修后 count=7607）与**闭合证据**（25＝1h 前切片内；2182=25+2157；全库最近 1h 写入 7379） | §4.2④、§4.2①(b) |
| U3 | A1/A3、C1、Z1、H-4(a) 无定义（unclear） | 术语速览加「断言标签」条目（A1/A3/C1 内容摘要）、「Z1 / B 探针」、「H-4(a)」（含出处 `docs/eval/优化第三批_..._v1.0.md` §1.3/§3.3）；§4.1/§五 引用处随文注 | 术语速览；§4.1；§五 |
| U4 | 「并集判据」未展开；B 探针前文不存在（unclear） | §4.2③ 展开机制（`reddened` 并集、守卫 `:603-627`）+ **本报告实跑复验**（删变异③ → 7 条全 OK、RC=0）+ 等价探针实测空转判据（塞 `ZZ_FAKE_ALWAYS_GREEN` → RC=1 点名）；术语速览「并集判据」「Z1/B 探针」条目 | §4.2③；术语速览 |
| U5 | 表头「5 改 + 1 新增源码件 + 1 新增守卫」与文末对不上（unclear） | 表头改「5 个已跟踪文件被改 + **新增守卫** `md_cg/test_issue52_scan_condition_first.py`；另有未追踪设计稿与宿主目录」——消除重复计数（v1.0 的「新增源码件」与「新增守卫」实为同一文件，表述有误） | 表头；§6.1 |
| U6 | 「旧快照」无解释（unclear） | 术语速览加「旧快照」条目（缺 `temporal`/`spatial` 键 → `_read` 回退，判据 `stg.py:146` → `:159-162`；变异⑦/D4 钉住；覆盖升级兼容风险面） | 术语速览；§3.2 |
| U7 | 「时好时坏」与「恒态（非抖动）」表面矛盾（unclear） | 两处点破：漂移发生在 **rebuild/跨进程重载边界**（腿⑥）；同一索引物理序下重复调用恒同（腿①）——两种时间尺度 | §1.1(d)；§二；腿① |
| S1 | 「八条腿全部」被腿⑧自证否掉（unsupported） | 改为「八条腿 `reproduced=true`（采集原值）；腿①-⑦ 运行复现、腿⑧ 源码形态核对」；「无异常抛出」适用范围＝腿①-⑦；腿⑧ 异常/崩溃栏「不适用」 | §二；§1.1 |
| S2 | 「恒不注入」与自身在役数据不符（unsupported） | 改为「注入面被切片锁死：切片外新归档记忆**零注入**、能注入的只剩切片内旧条目（历史读数 25 条全 `code_*`）」；并注明该结论为源码路径+转录读数推得、宿主端未跑 | §1.1；腿⑧ |
| S3 | 「与 #52 临床面吻合」无依据（unsupported） | §4.2④ 重写为可检验形式（`mem_*` 17/17 在切片外、切片内 2182/2182 全 `code_*`）；并交代可查症状面＝守卫 docstring `:7-9` + 设计稿 `:3-7`；GitHub issue 原文未随材料携带、不代补 | §4.2④ |
| S4 | 腿⑤ site 区间 3145-3155 盖不住 3156（unsupported） | site 改逐点列出 `md_cg/mcp_server.py:3145 / 3152 / 3156`（HEAD 三分支 `if` 行；工作树 3152/3159/3163），并注明采集原区间右端不足 | 腿⑤；§1.2 表 |
| S5 | 「差的 2 条即其后新归档的 `mem_*`」是推断（unsupported） | 补 17 条 `mem_*` 全清单（id/created_at）；**恰 2 条落在最近 1h 内**（`9dd5ef` 06:22:29、`baa2e0` 06:31:50）使该推断与时点分布自洽；文档 15 条原始清单未随材料携带，不另裁名单 | §4.2④ |
| Q1 | #52 原始症状描述是什么；「吻合」按什么判定？ | 可查症状面＝守卫 docstring `:7-9` + 设计稿 `:3-7`（报告引文）；GitHub issue 原文未随材料携带（不代补）；「吻合」已重写为可检验断言（S3） | §4.2④ |
| Q2 | 修复后代码在真实在役库跑过吗？ | **未做完整栈在役调用**（材料纪律「不构造任何 MdCG」保持）；本报告做了「在役数据 + 替身 cg」只读调用（count=7607/scanned=17850/kept=5000/truncated=True，§4.2④）；「25→229」的验证在 temp 的 **232 节点合成等价库**上做（§4.2①(b)） | §4.2④ |
| Q3 | 落地还差哪些动作、谁做、何时；转 ACCEPT 条件；还有别的门禁吗？ | 动作清单＝`cogmap_sync.py build` + 两处注释锚改正（复核判定：改正/重算即转 ACCEPT）；其余门禁＝`package.json` `gate` 9 条腿（读码列名，未逐条跑）；**排期归主会话/使用者，不代裁** | §6.2.7 |
| Q4 | count 语义变化，消费方要跟着改吗？ | 读码：DSH 侧消费面 `formatTimelineDecayed`（`hooks.ts:265-287`）**只取 `items`**（不读 count/truncated），未截断输入已证逐位兼容（§4.2②）——该消费方无需因 count 语义变更而改；**消费方审计未做**（是否另有 count 依赖方归后续核验，不代裁） | 腿⑧；§6.2.3 |
| Q5 | MCP 仍丢弃 max_scan 与「禁止静默」冲突吗？算留池吗？ | 如实列为**留池+残余不一致**（§6.2.8）：契约「数值不是修法」不开入参，但「静默丢弃」无告警与禁止静默原则存在张力——归后续批次/使用者裁定，本报告不代裁 | §6.2.8 |
| Q6 | DSH/TS 端到端由谁何时跑？ | 宿主端到端未跑（腿⑧）；排期归主会话/使用者，本报告不代裁 | §6.2.6；腿⑧ |
| Q7 | 容器栈 22/41 覆盖哪些阶段；新守卫在容器里跑过吗？ | 构成材料未携带（不代裁）；新守卫**已入容器清单**（`linux_verify.sh:49/101-102`，本报告读码）；「容器内已执行含新守卫的清单」未随材料携带，不代证；本机三模式已实跑（§4.1） | §4.3 |
| Q8 | 修前复现腿实验根是否已清理？ | **本报告实查**：`%TEMP%\issue52_repro_v0om5r8a` **仍存在**（含 `exp1/2/3.py`、`exp1/2/3.log.txt`）；`%TEMP%\i52*` 存在 11 项（列出，mtime 2026-10-01~10-03 07:01）——与复核「glob 为空」声明不符，归属不代裁；本报告自身临时根已清理 | §五.4 |
| Q9 | 第 3 层与索引序两源的下一步/判据/排期？ | 第 3 层验收判据＝设计稿 §四（等价性/收敛性，引述）；索引序两源＝记录在案、无排期材料；**动作与排期归主会话/使用者，不代裁** | §6.2.1/6.2.4 |

**材料缺、如实不代补清单**（v1.1 汇总）：GitHub issue #52 原文（Q1）、容器两栈阶段构成（Q7）、切片外 204/206/203 的口径细节（§4.2④）、Z1 探针脚本本体（§4.2③）、文档「15 条 mem_*」原始清单（S5）。

---

## 附：git 面（本报告终末核实〔本报告实跑〕）

修复批次工作树（与本工作流起始快照一致，落盘前实测）：

```
 M md_cg/mcp_server.py
 M md_cg/provenance.py
 M md_cg/stg.py
 M md_cg/test_n204_n205_n226_n227_n228_n229_exit_gates.py
 M scripts/linux_verify.sh
?? .zcode/
?? docs/plans/stg条件化与结构索引_设计_v0.1.md
?? md_cg/test_issue52_scan_condition_first.py
```

本文档（v1.1 修订）为唯一内容被修改的文件——文件名不变，仍为 `docs/eval/issue52_条件先行与截断可观测_修复记录_v1.0.md`。未 add / 未 commit / 未 push。全文无明文凭据。本报告本次修订引入的临时根 `i52rev_*` 已清理（复查为空）；复现腿实验根 `issue52_repro_v0om5r8a` 与 `i52*` 残留如实列于 §五.4，是否清理归使用者（非本报告产物或归属未定）。


---

## 附：编排侧收口注记（v1.1，2026-10-03）

本批收口由编排会话（非工作流）执行，以下全部读数为编排侧亲跑：

1. **DEFER 两理由的处置**（复核预置条件：「改正/重算即转 ACCEPT」）：
   - 两处源码注释锚已改正：`md_cg/provenance.py:434` 与 `md_cg/test_n204_n205_n226_n227_n228_n229_exit_gates.py:19`
     中的 `stg.py:138/233` → **`stg.py:144/238`**（与 §五 判定的真接线点一致；改后逐行回读确认：
     `:144` = `if _sec is not None and not _sec(e):`、`:238` = `if not guard(e):`）；
   - `python -X utf8 scripts/cogmap_sync.py build` 重挂 → `check` **通过**
     （cg 36 op / stg 4 op / whitebox 6 action / mdcg_* 31；双文档标记段、op/工具引用、文件链接、
     锚点、FUNC_DESC 覆盖全部一致，rc=0）。
2. **编排侧独立复跑**（与工作流转录逐项核对一致）：
   - 守卫：`python -X utf8 -m md_cg.test_issue52_scan_condition_first` → **36 通过 / 0 失败**；
     `--branch-baseline` → 判别力自证 PASS（八处变异各自恰好命中、无空转断言）；
   - python 全量：`scripts/run_tests.py --jobs 4` → **309/309 通过，5 跳过**（退出码 0）；
   - 容器栈一（`rust:bookworm` × `linux_verify.sh full`）→ **41 pass / 0 fail**
     （新守卫 `--branch-baseline` / `--legacy-baseline` 两腿已在容器清单并 PASS）；
   - 容器栈二（`node:22-bookworm` × TS）→ **pass 96 / fail 0 / skipped 3**。
3. **实验面清理**：本任务链在临时区留下的实验根（修前复现腿与实施/复核探针）于收口时统一清理
   ——关键读数已转录于本报告 §四，不依赖临时件存续。
4. **裁决**：按复核预置条件，本批 DEFER → **ACCEPT**（改正 + 重算已完成、四项复跑逐项一致）。
   复核原始 DEFER 判定与其列出的残余/未覆盖面保留上文原样，供追溯。
