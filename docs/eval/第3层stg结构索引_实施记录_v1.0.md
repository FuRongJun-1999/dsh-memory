# 第 3 层 stg 结构索引（装载期内存倒排＋写路径增量维护 · 条件资格首验 · 回退可观测）——实施记录 v1.0

**日期**：2026-10-03 ｜ **被测面**：`<仓根>` 工作树（未提交——3 个已跟踪文件被改＋2 个新增文件；git status 实列 3 M＋3 ??，第三个 ?? 为宿主目录 `.zcode/`，见文末 git 面）｜ **基线**：HEAD `0d3a0ab2`（`git rev-parse HEAD` 实跑核实）

**关联**：
- 设计稿 `docs/plans/stg条件化与结构索引_设计_v0.1.md`（本次随批修订，含 2026-10-03 使用者签收记录）——本批为其 **§三「第 3 层设计」** 的落地；
- 前序批 `docs/eval/issue52_条件先行与截断可观测_修复记录_v1.0.md`（第 1/2 层；其 §六留池「第 3 层结构索引与条件资格」由本批接续）。

**证据分级声明**（本报告只写有机械证据的事）：

| 标记 | 含义 |
|---|---|
| 〔本报告实跑〕 | 本报告撰写员在本次 ask 内亲手执行并计数（守卫两模式 / python 全量 / `git grep` 零实现面 / 行号读码核实 / git 面） |
| 〔工作流采集·修复段〕 | 修复工作流采集材料（7 条修前复现腿 / 实施 changes / targetedSuite），本报告**转录**，不代跑不代补 |
| 〔工作流采集·复核段〕 | 修复工作流的独立复核段采集材料（ACCEPT 判定 / 三臂 battery / fuzz / 退化与注入探针），本报告转录 |
| 〔编排侧〕 | 随任务材料传入的编排侧输出（容器两栈），本报告转录、未复跑 |

行号口径：改后行号＝读工作树核实〔本报告实跑〕；改前行号＝`git show HEAD:<path>` 核实〔本报告实跑〕。

**术语速览**（出处随条标注：标 `stgidx.py` 的条目出自**本批新增文件**；标 `stg.py`/`mdcg.py` 的含本批新增落点；行号＝现树读码；本批之前不存在的概念会注明）：

| 术语 | 释义 |
|---|---|
| **第 1/2/3 层** | 设计稿 §二/§三的分层：**第 1 层**＝全量快照遍历＋条件过滤（**正确性基线路径**——索引路径必须与它逐位一致）；**第 2 层**＝截断可观测（`truncated`＋hint＋近期优先兜底）——两者由前序批（issue52）落地；**第 3 层**＝结构索引（条件维倒排直取）＋条件资格首验，即**本批**（设计稿 §3.1） |
| **三表 / 三张表** | 结构索引 `StgIndex` 的三张倒排（`md_cg/stgidx.py:148`）：`by_session`（`None`＝无会话归属桶）/ `by_layer` / `by_time`（升序 `(t, id)`）＋ `pos`（物理位序）＋ `cls`（每节点分类记录）。**不变量**：恒为快照 keys 的划分，自检单点 `stgidx.verify`（`:85`） |
| **物理序（pos）** | 快照 `index["nodes"]` 的 dict 插入序＝基线 `_scan` 的候选序；索引子集取数后须按 `pos` 回排以复现它（`stgidx.py:19-20` 注释） |
| **unassigned 桶** | 无会话归属节点（`session` 为 `None`）的兜底桶；具体会话视图**不得**混入它（设计稿 §六-4；守卫 G3） |
| **nonfinite** | 时间戳为 NaN/±inf 的节点单列：NaN 在基线上**会**命中时间窗（保守超集，逐条精确判定仍在 `_scan` 侧）、±inf 永不命中（`stgidx.py:22-26` 注释） |
| **观察轴 / 效力轴（time_axis）** | stg 的时间轴开关：`observed`（缺省）＝观察轴，读 `temporal`（回退 `condition_space.time_window`）；`effective`＝效力轴，读 `effective_from` / `effective_until`。单点 `stg._interval`（`stg.py:44`，委托 `trust.time_window_of` :393 与 `trust.time_axis_of` :378）；非法轴抛 ValueError。`by_time` 表按观察轴建，故非观察轴查询不索引时间维（§六-5） |
| **代际（generation）** | 表绑定的快照身份：`StgIndex.index_obj is cg.index` 判据（`md_cg/stg.py:287`）；整体换过快照＝代际不符 ⇒ 丢陈旧表并回退上报 |
| **回退 reason / fallback** | 索引不可服务时 `meta` 里的非空原因串（9 个字面量全清单见 §3.3）；`path=full` 表示本查询实走第 1 层全量 |
| **flag** | `MDCG_STG_INDEX`（结构索引）/ `MDCG_STG_QUALIFY`（条件资格首验）；取值 `"1"/"true"/"True"` 为开，缺省关（`md_cg/stg.py:275` `_flag_on`） |
| **只上报不过滤** | 资格首验的契约红线：`qualification` 只挂到返回条目上，不动成员/次序/截断面（`md_cg/stg.py:441`；硬过滤另立裁定） |
| **签收点 1–5** | 设计稿 §六「待签收点」（逐条裁决请求）与 §八「签收记录」（2026-10-03 使用者逐条签收：1 索引形态主案「同意」/ 2 路径等价为唯一准入「同意」/ 3 资格首验只上报不过滤（硬过滤另立裁定）「同意」/ 4 unassigned 语义保持现状「确认」/ 5 `consistency.check` `MAX_SCAN=200` 选面「纳入本线第二实现批」） |

---

## 一、缺陷定义与真实站点

### 1.1 缺陷定义

**一句话**：设计稿 §三定义的**第 3 层缺位**——三接口（timeline / anchors / consistency）的候选面恒为**全量快照遍历**（O(N)，改前树 `md_cg/stg.py:141` 逐条全库），session / layer / time_window 条件只能在遍历**之后**过滤；同时条件资格（`judge_qualification`）未进 stg 读面，索引化所需的回退/可观测面（reason / meta）在改前树**无实现点**。

- 前序批（issue52）已把「条件先行＋截断可观测」收口，但候选面仍是全量——设计稿 §3.1 目标形态＝「触碰节点数从 N(全库) 降到 域内 ∩ 条件匹配 ∩ 邻域」；本批实测收敛读数见 §4。
- **本批改动为「新能力实施」，不是崩溃修复**：修前 7 条复现腿中 **6 条可运行腿的 observed 全部为「无异常」读数、第 7 条无可断言对象**（`reproduced=false`；§二逐条列），其语义是**基线取证**——为「flag 开/关逐位等价」这一唯一准入判据（设计稿 §四-1、§六-2）建立逐位靶子，并取证 flag 缺席面（改前树两 flag 零实现，见 §1.2 机械甄别）。
- 一处**行为差异的风险面**已预判并被守卫/复核覆盖：索引物理序（快照插入序）与时间序、id 字典序互相错位（修前腿 1/4 的取证形态），取数面若不回排 `pos` 即无法复现基线候选序（变异④、守卫 G1）。

### 1.2 真实站点（行号为本报告读码所见）

**改前树**（`git show HEAD:md_cg/stg.py` / `md_cg/mdcg.py`，本报告实跑核实）：

| 站点 | 内容 |
|---|---|
| `md_cg/stg.py:119` | `def _scan(cg, layer=None):`——遍历单点定义（逐条过滤/条目化内联其中，无 `nodes` 参数） |
| **`md_cg/stg.py:141`** | **全量遍历主站点**：`for nid, e in list(cg.index["nodes"].items()):`——三接口候选面恒为全量（AST 判据 `scan_ast_slices=[]`、`scan_src_line=141`〔工作流采集·修复段〕） |
| `md_cg/stg.py:347 / 392 / 433` | timeline / anchors / consistency 三接口共性调用点 `for n in _scan(cg, layer=layer):`（本报告实跑核对 HEAD 版全部 `_scan(` 调用点，三处全中） |
| `md_cg/stg.py:160` | 旧快照回退分支 `fm, _content = cg._read(e)`（既有兼容路径，本批不动） |
| `md_cg/stg.py:280 / 343 / 350 / 359` | `_view_session` 定义 / timeline 会话归一 / 会话过滤 / `items.sort(key=(start,end,id))`——第 3 层必须逐位保住这些语义 |
| `md_cg/mdcg.py:1454` | 装载完成点 `self.index = self._load_index()`——其后**无**索引三表构建（现树该行 1460） |
| `md_cg/mdcg.py:2996 / 3006` | `_stage` / `_unstage` 写路径——**无**结构索引同钩（现树 3017 / 3062） |
| `md_cg/mdcg.py:1740 / 1794 / 1977` | `compact_index` / `flush` / `rebuild_index`——整体换快照路径**无**索引失效点 |
| flag 面（本报告实跑） | `git grep -E "MDCG_STG_(INDEX|QUALIFY)" HEAD -- md_cg src dsh test scripts` → **rc=1 零命中**（本报告实跑的五个代码路径面内；设计稿等 `docs/` 面不在该条 grep 路径内） |
| 索引/回退面（本报告实跑） | `git grep -E "by_session\|fallback_reason\|index_hit\|index_miss" HEAD -- …` → **rc=1 零命中**；`by_time` 8 处全为 `trust.filter_by_time` 族（mdcg.py:3566、mdcos.py:820/1283/5146、provenance.py:528、test_retr_s8_time.py:151/153、trust.py:556 定义）；`by_layer` 在改前为**统计用途**（export.py 导出统计等），无倒排取数实现 |
| `md_cg/mcp_server.py:1044 / 3153` | stg 工具面 `layer` 声明为 string（`:1044`）；`_stg_call` 三分支**原样透传**（`:3153` timeline 分支）——不校验，见 §5.2 分叉 |

**改后树**：落点表见 §3.2。

---

## 二、修前现场（本工作流采集的 7 条复现腿）

**共同事实**：6 条可运行腿**无异常抛出、无崩溃**（observed 列即逐条读数；本批语义＝基线取证）；第 7 条（表缺失回退面）在改前树**无可断言对象**——属第 3 层新增面，如实记 `reproduced=false`。逐条如下〔工作流采集·修复段〕。表内读数记号（`hash_biz`/`hash_full`、`*_ids`/`*_eq_*` 等）均为采集脚本自产（脚本未随材料提供）；读者点名的两处记号已就地注明（腿 1 摘要记号、腿 2 布尔读数）。

| # | 腿 | payload | observed（异常/崩溃点） | 站点 | reproduced |
|---|---|---|---|---|---|
| 1 | 构造期装载（flag 关 · >5000 节点合成库 · 三接口逐位快照） | lib_big 合成库 5203 节点：4900 填充（sess_o1/sess_o2 交错，temporal=2e6+i）＋200 目标节点（session=target-sess，temporal=1e6+i，id=zz_target_\* 字典序落索引尾部）＋100 无会话（m_unassigned_\*）＋3 倒置（z_bad_\*）；close 落快照后重开装载；flag 未设 | 无异常。装载走快照路径：nodes=5203 / `_index.json` 在 / fingerprint_match=true / load 0.03s；索引尾 3=zz_target_0197..0199、zz_target_0000 位置 5003。`timeline(session=target-sess)`：count=200 scanned=5203 kept=200 truncated=false——索引第 5003 位的目标会话节点被条件先行全覆盖（第 1/2 层已收口，此为**等价性基线锚点**）。20 条查询（Q1-Q20）返回体逐位留档：run1/out/default.json（Q1 hash_biz=9f196e20…、Q3 hash_full=22027553…、Q15 hash_biz=f231733a…）。串行计时（全量遍历 5203，5 次中位）：T1 timeline(target) 3.8ms / T2 timeline(\*) 无截断 6.2ms / T3 anchors(时间窗) 8.3ms / T4 consistency 全量 9.5ms（记号口径：`hash_biz`/`hash_full`＝采集脚本对返回体的两种摘要（业务字段 / 含读数全量），其精确定义与复算脚本**未随材料提供**；`run1/out/default.json`＝材料中的留档相对路径，根目录**未随材料提供**；「索引尾 3」＝快照物理序最后 3 项、「位置 5003」＝0-based 下标——其前恰有 4900＋100＋3＝5003 个节点（nid 字典序：`m_unassigned_*`/`z_bad_*` 均小于 `zz_target_*`；本报告读码＋算术核实） | `md_cg/mdcg.py:1454`（装载完成点）；`md_cg/stg.py:141`（全量遍历） | true |
| 2 | 重放面（写钩 `_stage`/`_unstage` · rebuild/compact/重开装载后逐位一致） | lib_write 63 节点库（50 填充＋10 目标＋3 无会话）；操作序列：add b_new_0001 → rebuild_index → _unstage(zt_00)+删文件 → flush+compact_index → 重开装载；flag 未设（「删文件」＝删除 zt_00 节点对应文件，执行者/脚本未随材料提供） | 无异常。count 10→11（新节点时间最新居首位）；rebuild 后物理序由追加序变 sorted（b_new_0001 位置 63→50，append_is_sorted=false / rebuild_is_sorted=true；两枚布尔读数为采集脚本产出，其脚本与判据未随材料提供），而查询返回体与 rebuild 前逐位相同（hash_full/hash_biz 均相等）——结果与索引物理序无耦合；`_unstage`+删文件后 count=10 且 zt_00 不在；compact 后重开装载 hash 与删除后逐位相同 | `md_cg/mdcg.py:2996`（_stage）、`:3006`（_unstage）、`:1977`（rebuild）、`:1740`（compact）、`:1794`（flush）（改前树行号，本报告已对 HEAD 核实） | true |
| 3 | 多会话交错＋无会话节点（unassigned 语义现状） | 同一 5203 库；3 个具体会话（sess_o1/sess_o2/target-sess）交错＋100 条无 session 节点＋sess_bad；查询 timeline 各会话视图/跨会话/anchors；含空白会话值归一探测 | 无异常。`timeline(session=target-sess)` items 的 session 值集合={target-sess}、无 unassigned id 混入（target_view_unassigned_ids=[]）；`session="*"` 与缺省均 count=5203（含无会话节点，cross_eq_default=true）；anchors（时间窗，无会话维度）返回全部 100 条 m_unassigned_\*；会话值归一（`"  target-sess  "`→strip）count=200 | `md_cg/stg.py:343-350`（timeline 会话过滤与 cross 判据）、`:280`（_view_session 定义） | true |
| 4 | 时间序与 id 字典序错位（目标会话节点落索引尾部） | 目标节点 temporal 最旧（1e6+i）而 id=zz_target_\* 字典序最大；填充 temporal=2e6+i；无会话节点 temporal=3e6+i；查询 desc/asc/max_scan=10 | 无异常。timeline desc 头部=zz_target_0199..、尾部=zz_target_0150（按时间倒序而非 id 序）；desc=False 升序；max_scan=10 时保留 zz_target_0199..0190（近期优先保留最新而非 id 尾部）；count 恒=条件命中总数；索引物理序（rebuild 后 sorted 写盘）与查询输出无耦合 | `md_cg/stg.py:359`（items.sort 键）；`md_cg/mdcg.py:1969-1974`（_scan_nodes 按 nid 排序写盘＝索引物理序） | true |
| 5 | 截断语义继承（truncated/scanned/kept/近期优先/hint） | 5203 条跨会话命中（默认 max_scan=5000）；consistency 在 5203 候选上三档（默认/100/None）；anchors 全命中 bbox | 无异常。`timeline(session="*")`：count=5203 kept=5000 truncated=true，hint 在场且含「细化生效条件」「条件索引」字样；anchors（bbox 全覆盖）同型读数；consistency 默认 scanned=5203 kept=5000 truncated=true（3 条倒置因时间不可判定先被截→issues=0）、max_scan=100→kept=100、max_scan=None→kept=5203 truncated=false 且 issues=3（z_bad_0..2） | `md_cg/stg.py:169`（_cap_hits）、`:215`（_with_scan_reads）、`:208`（_CAP_HINT 文案）（第 1/2 层落点） | true |
| 6 | flag 缺席面（`MDCG_STG_INDEX=1` / `MDCG_STG_QUALIFY=1` 行为零变化） | 同库同 20 条查询，子进程 env 置两 flag=1 重跑（default 臂自动 spawn flags 臂，同脚本同载荷） | 无异常。两臂 58 个 hash 键（全量＋业务字段）逐位一致 equal=true；两臂返回体 leak 检查全 false（无 qualification / index_hit / index_miss / fallback / index_tables 键）；`git grep -E "MDCG_STG_(INDEX\|QUALIFY)" -- md_cg src dsh test scripts` → rc=1 零命中（五个代码路径面内；该命令的路径面不含 `docs/`，设计稿在 `docs/plans/` 下的命中与否不由该命令判定） | 改动前树无实现点（`stg.py`/`mdcg.py` 无 flag 读取；`mcp_server.py:3131` `_stg_call` 原样透传）；设计稿 §3.5 预定落点 | true |
| 7 | 回退路径（表缺失时） | 不适用——改动前树无索引三表，无表可缺，无法注入 | **未复现**（无可断言对象；此非实验失败，系该面属第 3 层新增）：「表缺失/代际不符 ⇒ 回退第 1 层＋meta reason」在改动前树不存在。机械甄别：`by_session` 在 md_cg rc=1 零命中；`by_time` 8 处全部为 `trust.filter_by_time`（检索时间算子，trust.py:556）；`by_layer` 为统计用途；`fallback_reason`/`index_hit`/`index_miss` 零命中。既有最近似回退＝旧快照缺 temporal/spatial 键时 `_scan` 回退 `cg._read` 读文件（实测 lib_snap 库 timeline(session=target) count=2 命中）——该面仍成立但语义不同。基线对应物＝腿 1 的 flag 关全量遍历路径（已取证） | `md_cg/stg.py:160`（既有回退分支）；三表构建点在改前树不存在 | false |

---

## 三、修法契约与落点

### 3.1 契约（设计稿 §3.2/§3.4/§3.5/§四/§五/§六＋守卫钉住的红线）

| # | 契约 | 机械钉法 |
|---|---|---|
| C1 | **flag 默认关**：`MDCG_STG_INDEX` / `MDCG_STG_QUALIFY` 未设＝第 1 层路径；关臂返回体与第 1/2 层**逐位一致**（不落 `index` 键） | `stg.py:269/271/275/328`；守卫 G1b、G5j；变异⑫（红 3） |
| C2 | **只改取数面、不改语义面**：逐条构造与过滤（layer/可见性/条目化）单点 `_scan_one`，全量遍历与索引子集共用；第 1/2 层条件先行与无切片红线一字未动 | `stg.py:134/168`；守卫 G7b（AST 判据：`_scan` 内无切片子表达式）；变异③（红 1） |
| C3 | **逐位等价为唯一准入**：flag 开/关业务字段逐位一致（`meta` 计数除外）；开臂候选面必须**真收窄**（子集≥全量时走 full 并报 `no_convergence`） | 守卫 G1（A01–A21）、G1c；变异⑧（红 14） |
| C4 | **回退即回报（禁止静默）**：表缺失/构建失败/代际不符/表-快照残余不一致/迭代期旧快照条目/无条件维/未收窄 → 回退全量并带**非空 reason** | `_index_pairs` 全路径（`stg.py:321-362`）；守卫 G5a–G5i（G5a＝表规模读数==快照实况；G5b–G5i＝回退面）；变异⑨（红 14） |
| C5 | **资格只上报不过滤**：复用 read 面唯一单点 `MdCG.judge_qualification`，不动成员/次序/截断面；密文不可解 ⇒ 不附（不伪造状态） | `stg.py:405/441`；守卫 G6a–G6e；变异⑩（红 4）、⑪（红 3） |
| C6 | **写路径同钩增量维护**：写/删只经 `_set_index_entry` / `_remove_index_entry` 单点（桶计数与结构索引同钩）；整体换快照三路（重载/compact/rebuild）显式失效、下次访问惰性重建；flush 不失效 | `mdcg.py:3024/3041/3057` 与失效点 `:1683/1801/2006`、`flush:1808`；守卫 G2a–G2i；变异①（红 3）②（红 2）⑬（红 2）⑭（红 1） |
| C7 | **不引入第二套解析**：时间走 `trust.time_window_of`（与 `_interval` 同源）、会话走 `_view_session`、资格走 `judge_qualification`；索引划分不变量自检单点 `stgidx.verify` | `stgidx.py:56/85`；守卫 G7a（stg 侧 `judge_qualification` 恰一处调用，不另写第二套资格判据） |

### 3.2 落点表（改后行号＝本报告读码核实）

| 文件 | 行（现树） | 内容 |
|---|---|---|
| `md_cg/stgidx.py`（新增 281 行） | `:56` `time_of`（观察轴起点，复用 `trust.time_window_of`）/ `:73` `build`（O(N) 惰性构建）/ `:85` `verify`（划分不变量自检）/ `:148` `StgIndex` / `:169` `add` / `:182` `remove` / `:192` `_classify` / `:209` `_unclassify` / `:232` `range_ids`（二分区间，含同刻并列尾巴）/ `:244` `subset`（多维修交集，time 维先回排 pos）/ `:277` `size` | 第 3 层结构索引**单点**：三表＋pos＋cls；`nonfinite` 单列；`broken` 标记（增量期异常 ⇒ 读侧整表回退重建） |
| `md_cg/stg.py`（702 行） | `:134` `_scan_one`（逐条单点）/ `:168` `_scan(cg, layer, nodes=)`（候选面可换）/ `:253` `_with_scan_reads(index_meta)`（关臂不落 index 键）/ `:269` `_INDEX_ENV`、`:271` `_QUALIFY_ENV`、`:275` `_flag_on`、`:280` `_index_bundle`、`:307` `_index_meta_hit`、`:314` `_index_meta_full`、`:321` `_index_pairs` / `:405` `_qual_node_dict`、`:441` `_attach_qualification` / `:527` timeline（by_session，接线 `:552/:557`）、`:584` anchors（by_time 区间＋blocked，接线 `:621/:627`）、`:657` consistency（by_layer，接线 `:675/:676`） | 读侧编排：直取、回退、可观测、资格只上报 |
| `md_cg/mdcg.py`（4764 行） | `:1459` `self._stg_index=None`（惰性槽，装载完成后首次 stg 需要时构建）/ `:3017` `_stage`、`:3062` `_unstage`（委托）/ `:3024` `_set_index_entry`、`:3041` `_remove_index_entry`（桶计数＋结构索引同钩单点）/ `:3057` `_invalidate_stg_index` 及三处失效点 `:1683`（`_maybe_reload_index`）、`:1801`（`compact_index`）、`:2006`（`rebuild_index`）/ `:1808` `flush`（**不**失效，注释 `:1809-1811` 声明） | 写侧同钩＋失效编排 |
| `md_cg/test_stgidx_index_parity.py`（新增 1020 行） | `_SRC_MUTATIONS` `:691-798`（17 处定点变异表）/ `_MUTATION_IDS` `:802` / `_table_gaps` `:822` / `_table_integrity_check` `:862` / `_selfcheck_judge` `:877` / `_anchor_check` `:941` / `_branch_baseline` `:958` / `main` `:1007` | 守卫：G1–G7 共 **51** 条断言＋17 处定点变异＋防误删自检＋ANCHOR-MISS fail-closed（退出码 2） |

### 3.3 回退 reason 全清单（读码核实）

`_index_bundle`（`:280`）：`tables_missing`、`build_failed`（`:299`）、`generation_mismatch`（`:291`）、`table_snapshot_mismatch`（`:294`，键数型）；`_index_pairs`（`:321`）：`table_snapshot_mismatch`（`:354`，残余型）、`entry_file_read`（`:360`）、`no_condition_dimension`（`:340`）、`no_convergence`（`:346`）；anchors 侧 `blocked`：`time_axis_not_indexed`（`:616`）、`inverted_query_window`（`:620`）。

（「材料口径八类」的来源＝工作流采集·修复段的实施说明原文：`_index_pairs:321（八类回退 reason：tables_missing/generation_mismatch/table_snapshot_mismatch/entry_file_read/time_axis_not_indexed/inverted_query_window/no_condition_dimension/no_convergence）`——即上列**除 `build_failed` 外**的 8 个；本报告读码在 `_index_bundle`（`stg.py:299`）另见 `build_failed`，故合计 **9 个字面量**。每条回退路径都同时落 `path=full`＋`index_miss`＋非空 `fallback`。）

---

## 四、验证数字

### 4.1 本报告实跑

| 项 | 命令（本报告原样） | 结果 |
|---|---|---|
| 守卫默认模式 | `python -X utf8 -m md_cg.test_stgidx_index_parity` | 退出码 **0**；**51 通过 / 0 失败**（逐条计数：G1 23＝A01–A21 两臂等价 21 条＋G1b/G1c 形态钉住 2 条、G2 9、G3 1、G4 1、G5 10、G6 5、G7 2） |
| 守卫变异自证 | `python -X utf8 -m md_cg.test_stgidx_index_parity --branch-baseline` | 退出码 **0**；未变异基线 51 全绿；17 处变异**各自恰好命中**：①3 ②2 ③1 ④3 ⑤9 ⑥1 ⑦8 ⑧14 ⑨14 ⑩4 ⑪3 ⑫3 ⑬2 ⑭1 ⑮1 ⑯5 ⑰12；空转断言 0；判别力自证 PASS |
| python 全量 | `python -X utf8 scripts/run_tests.py` | 退出码 **0**；`===== SUMMARY 310/310 通过，5 跳过（依赖缺失/平台不符） =====`；清单内含 `PASS md_cg.test_stgidx_index_parity` |
| 改前树零实现面 | `git grep -E "MDCG_STG_(INDEX\|QUALIFY)" HEAD -- md_cg src dsh test scripts` 等 | rc=1 零命中（flag 面、by_session/fallback_reason/index_hit/index_miss 面）；`by_time` 8 处全为 `trust.filter_by_time` 族 |
| git 面 | `git status --porcelain` / `git rev-parse HEAD` | 3 M＋3 ??（含宿主 `.zcode/`）；HEAD=`0d3a0ab2d35d3100e3a5b31737fc722c3ec81bf7`；全量测试跑后状态不变 |

**守卫读数定义**（读码核实，适用于下表与全文）：
- **「红 N」**＝该处定点变异打红的断言条数；
- **预期值**＝守卫源码变异表 `_SRC_MUTATIONS`（`test_stgidx_index_parity.py:691-798`）每条的**第 6 个元素**；`--branch-baseline` 逐处替换源码后跑全部断言组，判据＝「打红集合大小 == 预期」（比较逻辑 `:983-995`）；
- **「恰好命中」**＝不多红、不少红（上判据全过）；
- **「空转断言 0」**＝没有任何一处变异能打红的断言数为 0（`never = 全部断言标签 − 各变异红项并集`，`:998-1001`）——即每条断言都至少被一处变异打红（有判别力）。

### 4.2 工作流采集（转录）

**修复段**：
- targeted：`python -X utf8 scripts/run_tests.py md_cg` → **233/233 通过、3 跳过、退出码 0**（较改前 232 恰增新守卫 1 件；含 `md_cg.test_issue52_scan_condition_first` 36/36 保绿）；
- 改前树基线对拍（`git archive HEAD` 到系统临时目录、33 用例）：关臂逐位 **0/33 不一致**、开臂业务字段 **0/33 不一致**；
- 收敛读数（5320 节点合成库、串行 9 次中位）：`timeline(session=sess_target)` 3.749→0.174ms（scanned 5320→120）、`anchors` 时间窗 6.883→0.077ms（5320→51）、`timeline(session=s1)` 4.366→1.447ms（5320→1265）、冷态含 O(N) 构建 8.3ms。（「→」两端：左＝第 1 层**全量臂**、右＝第 3 层**索引臂**——按同一读数内 scanned 全量→子集的口径标注；材料原文未逐字标明两端旗标/树。本读数与 §二腿 1 的 T1=3.8ms **不是同一读数**：腿 1 是 5203 库上的纯全量基线锚点，本项是 5320 库上的两臂对照。）

**复核段**（§五 详列）：三臂 battery（A=HEAD·flag 关 vs B=现行·flag 关 vs C=现行·flag 开）：A/B 严格逐位仅 3 处原始差异（1 处复核自加的存在性探针 `meta.index_attr_present`＋2 处运行期环境量 `_fingerprint`），**剔除后 0**；B/C 业务字段 0 差异；66 点 0 异常。（66 操作点口径＝4 合成库 ×（timeline/anchors/consistency 读面＋add/覆写迁移/删除/flush/rebuild/compact 写面＋全量状态摘要）；C 臂 index 读数（`analyze.py`）：命中面真收敛——tl_target scanned=120/full=5325、an_win=51、an_tie=2（同刻并列窗）、tl_nosuch=0；回退面 reason 全覆盖且 `path=full`。）随机对拍 200 轮 0 异常 0 差异；退化输入 34 点（不可哈希 session/layer 值、±inf/NaN 时间、字符串窗口、None token、falsy 层/会话、非 dict 条目；off/on 两遍×两树）非法输入异常类型＋消息逐字一致；注入探针 12/12（`fallback_probe.py`；`tables_missing`/`build_failed`/`generation_mismatch`/`table_snapshot_mismatch` 两型；每条＝reason 在场＋path=full＋scanned==全量节点数＋结果==关臂）；空池 4 点（em.\*）良构；legacy 旧快照（装载后条目缺 temporal/spatial 键=8，两臂同）；NaN 保守超集（材料原文：「窗 [inf,inf]：取 3 候选、逐条复核后 2 命中==关臂」；机制读码：时间窗索引取数恒并入 nonfinite 桶（`stgidx.py:256-257`），窗 [inf,inf] 时区间取数为空、候选＝nonfinite 全部（3 条）——「逐条复核」＝候选仍逐条经语义面精确判定（`time_relation`），2 条命中与关臂相等：**超集只多取候选、不放大结果**）；删断言探针（摘 g2→RC 1 且 ①/②/⑭ 红 0≠3/2/1、⑤8≠9、⑦5≠8、⑧13≠14、⑯3≠5、⑰4≠12；摘 g4→RC 1 且 ⑮ 红 0≠1）、fail-closed 三注入→RC 2、真锚点漂移→RC 2＋ANCHOR-MISS 点名 `MdCG._set_index_entry`、删表条目→`_table_gaps` 报缺号（两个形态）。

**编排侧**：
- **容器栈一：退出码 1**（读数两段并列：`结果: 22 pass / 0 fail`；`[PASS] smoke_test (linux)`；`=== 汇总: 39 pass / 2 fail ===`——两段的包含关系未随材料提供，本报告如实并列、不合并）；
- **容器栈二：退出码 0**（读数：`# cancelled 0 ｜ # skipped 3 ｜ # todo 0 ｜ # duration_ms 12100.223292`）。

### 4.3 数字口径说明

- 三处库规模 **5203 / 5320 / 5325** 分属三个不同夹具实例（修前腿 / 守卫-实施夹具 / 复核夹具），数字按来源分开、不合并；5325 的挂靠读数＝复核段 C 臂 `full=5325`（§4.2）。
- **容器栈一退出码 1（39 pass / 2 fail）**：2 fail 的条目清单与归因**未随材料提供**，本报告如实转写、不代跑、不作红绿归因猜测（§六列未覆盖）。同一栈内 `结果: 22 pass / 0 fail` 与 `=== 汇总: 39 pass / 2 fail ===` 两段的**包含关系**（孰为子集/总账）同样未随材料提供——不合并、不判定。

---

## 五、独立复核判定与未覆盖

### 5.1 判定与依据

**判定：ACCEPT**〔工作流采集·复核段〕。依据（复核自述）：
- 只读执行，**未编辑工作区任何文件**（复核自述：复核前后 `git status` 一致——3 处 M＋2 处 ??；本报告实跑当刻为 3 M＋3 ??，差 1 项＝宿主目录 `.zcode/`（非本批交付面）——M 数（3）与交付面 ?? 数（`stgidx.py`、`test_stgidx_index_parity.py`）两口径一致）；
- 全部实验根在系统临时目录（`stgidx_review_rc1`，含守卫夹具残留共 33 个目录已清理）；
- 未 `git add` / `commit` / `push`。

**oracle**＝改动前实现＝仓 HEAD `0d3a0ab2` 整树（`git archive HEAD` 提取到系统临时目录：2158 文件，实证无 `md_cg/stgidx.py`、`stg.py` 无 index 面、`mdcg.py` 无 `_stg_index`）。

复核覆盖面（自述要点）：三臂 battery 与改前逐位一致（见 §4.2）；随机对拍 200 轮；退化输入 34 点；跨实例（他进程写→重载）路径；注入探针 12/12；空池；legacy 旧快照；守卫两模式独立跑（退出码 0；红项数与声明一致）；删断言探针；fail-closed 三注入；可观测面（flag 关不落 `index` 键；开臂回退恒带非空 reason＋`path=full`＋`index_miss`，命中带 `path=index`/`size`/`full_nodes`；表规模读数独立重算一致；截断面 `truncated/kept/hint` 两臂一致）。

### 5.2 复核列出的未阻断分叉（唯一一条）

**不可哈希 `layer`（list/dict）在 flag 开时抛 `TypeError: unhashable type: 'list'`**（已独立复现）：
- 复现：`timeline(cg, layer=['knowledge'], limit=5)`；
- 出处：`stgidx.subset` 的 `self.by_layer.get(layer, [])`（本报告读码核实＝`md_cg/stgidx.py:252`；同形路径 `by_session.get(session)` 在 `:249`）；
- 对照：HEAD 与关臂对同输入返回**空视图**（count=0 / scanned=0）；
- 可达面：`mcp_server.py:1044` 声明 `layer` 为 string，但 `_stg_call`（`:3153`）直通不校验，故 MCP 面可被畸形参数触达；
- 定性（复核自述）：**默认关不受影响**；方向为 **fail-closed（非静默错值）**；属 **schema 外输入**；
- 处置：本轮**不修**，留池（§六-4）。

### 5.3 复核未覆盖（材料可见范围内）

- 容器两栈读数：复核段材料未见引用（容器读数由编排侧另行采集，见 §4.2）；
- 在役库（AEIS 数据面）实测读数：设计稿 §八签收附加要求「实施后须实测——在役库上的路径等价读数与遍历面收敛读数」；本报告材料范围内给出的收敛读数为**合成库（5320 节点）**读数，在役库读数**未随材料提供、本报告未跑**（§六列未覆盖）。

---

## 六、边界与未覆盖（含本轮明确不修而留池的面）

**本轮明确不修而留池**（设计稿 §五/§六与复核结论）：

1. **默认开关**：不改默认启用（先 flag、逐项验证、再讨论默认开启）——`MDCG_STG_INDEX` / `MDCG_STG_QUALIFY` 默认关，关臂＝第 1 层路径（守卫 G1b/G5j 钉住）。
2. **资格硬过滤**：首验只**上报**不过滤；硬过滤（与 read 面同权）另立裁定（设计稿 §六-3；§八签收记录：该项「同意」——签收原话与五条明细见设计稿 §八）。
3. **`consistency.check` 的 `MAX_SCAN=200` 选面**（字典序前 200 → 应改相关性/条件预筛）：签收记录明确「纳入本线**第二实现批**」（批间独立复核）。
4. **schema 外输入**（不可哈希 layer/session）：复核已列唯一分叉（§5.2），fail-closed、默认关不受影响；本轮不收紧工具面校验，留池。
5. **非观察轴不索引**：`anchors` 在 `time_axis != "observed"` 时时间维不索引（回退带 `time_axis_not_indexed`）——表按观察轴建，换轴不预筛，语义由基线同点（`_interval`）保证（`stg.py:609-620`）。
6. **跨进程共享**：索引是**进程内**派生结构，各进程自建（`stgidx` 模块 docstring 的「不适用条件」）；无共享过期面，亦无跨进程一致性承诺。**部署假设未随材料给出**：构建是**惰性**的（装载后首次 stg 访问才建、写路径零成本——`stg.py:279`/`mdcg.py:3023`），长驻进程内重复查询可摊薄 O(N) 构建（5320 库冷态 8.3ms）；若部署为「每查询起新进程」，每次首查须付构建成本——该形态的成本收益对照**未做**（材料无读数，本报告不代算，列入下方待对账）。
7. 其它设计稿 §五已声明边界：不改 `max_scan` 数值与第 1/2 层语义；不做 FTS（full-text search，全文检索）替代；不动写入侧磁盘格式（索引为内存派生＋同钩维护）。

**本报告未能覆盖/核实的**：

- **容器栈一退出码 1 的 2 fail 条目与归因**：材料只给汇总读数（39 pass / 2 fail），未给失败条目清单；本报告未复跑（容器不在本报告可及范围），**不作归因猜测**。附注：复核 ACCEPT 的覆盖面与容器读数是**两条独立采集线**（复核段材料未引用容器读数）——本报告不主张「该红栈不影响结论」，只如实登记红栈与其未归因状态；
- **在役库（AEIS 数据面）实测读数**（§5.3）：设计稿 §八签收附加要求「实施后须实测——在役库上的路径等价读数与遍历面收敛读数」的补跑时点与责任人**未随材料提供**，本报告不代答、不代排期；
- 改前树基线对拍（33 用例）、三臂 battery、fuzz 200 轮、退化 34 点、注入探针等复核实验：本报告**转录**材料读数，未复跑（本报告实跑项＝守卫两模式、python 全量、`git grep` 零实现面、行号读码核实、git 面）。

**待对账（读者问询项，材料未提供、本报告不代答）**：

- **flag 何时开**：「逐项验证」的判据＝设计稿 §四 五条验收判据（等价性 / 收敛性 / 不劣化 / 可观测 / 守卫与定点变异）；默认开启的判据与时点未随材料提供。§5.2 分叉的 `_stg_call` 校验收紧与 flag 默认开启的先后关系亦未裁定——本轮仅记「不收紧」（§六-4）。
- **提交与排期**：本批改动何时提交、设计稿的「随批修订＋2026-10-03 签收记录」是否随批提交、留池项（资格硬过滤、`consistency` `MAX_SCAN=200` 选面）的排期——均未随材料提供（本报告不含提交动作与排期决定）。
- **材料取阅位置**：本报告证据源（工作流采集·修复段/复核段、编排侧输出、腿 1 的 `run1/out` 留档）的独立留档位置**未随材料提供**——本报告无法给出取阅路径。
- **进程生命周期假设**（见 §六-6）：长驻 vs 每查询新进程两形态下构建成本的摊销对照未做。

---

## 附：git 面〔本报告实跑〕

工作树（`git status --porcelain`，本次核实；全量测试跑后不变）：

```
 M docs/plans/stg条件化与结构索引_设计_v0.1.md
 M md_cg/mdcg.py
 M md_cg/stg.py
?? .zcode/
?? md_cg/stgidx.py
?? md_cg/test_stgidx_index_parity.py
```

`git diff --stat`：3 files changed, 359 insertions(+), 52 deletions(-)（设计稿 +12 / mdcg.py 77 处变化 / stg.py 322 处变化）；新增未追踪 `md_cg/stgidx.py` **281 行**、`md_cg/test_stgidx_index_parity.py` **1020 行**（读码计数）。

未 `git add` / 未 `commit` / 未 `push`（复核段自述一致；提交时点与排期见 §六「待对账」）。本文档落盘后，工作树在这之上仅多 1 个未追踪文件：`docs/eval/第3层stg结构索引_实施记录_v1.0.md`。本报告未改源码、未改上述任何既有文件。


---

## 附：编排侧收口注记（v1.1，2026-10-03）

1. **容器栈一 2 fail 定因与处置**（本报告 §五 列示的未归因项）：两腿＝
   `md_cg.test_issue52_scan_condition_first --branch-baseline / --legacy-baseline`——
   **不是代码回归**，是该守卫的 fail-closed 行为**按设计工作**：它检测到 `_scan` 结构被本批
   改造（实现改了却没同步 `_MUTATIONS`）→ 报 `ANCHOR-MISS` + 退出码 2。
   处置＝按新结构同步五组锚（①三接口候选行 ②读数上报段 ⑥`_sec` 判定 ⑦旧快照回退 ⑧layer 过滤），
   并在 `_MUTATIONS` 头部加维护记录。同步后逐项复验（编排侧亲跑）：
   - 主模式 36/36；`--branch-baseline` 八处变异红项数与预期**逐项一致**（24/15/3/4/4/3/1/2）；
     `--legacy-baseline` 修前形态打红 28 条（含 A1/A3 核心）→ 三模式全绿；
   - python 全量 **310/310**；容器栈一 **41 pass / 0 fail**；栈二 **96 / 0 / 3**。
2. **在役库实测（设计稿 §八 签收附加要求 · 只读）**：
   - **等价**：flag 关/开两臂，timeline / anchors / consistency 业务字段**逐位一致**；
   - **收敛**：timeline 全量遍历(关) **44.84 ms** → 索引取数(开) **0.86 ms**（**52.07×**，在役 17882 节点）；
   - 索引 meta：`path=index / index_hit=1 / fallback=null / size={nodes:17882, sessions:204, layers:8, timed:17882, untimed:0}`。
3. **留池登记（非本批引入，会话归属面）**：收口核查中确认——常驻 MCP 重启后进程随机
   session 水印更替（`security.py` 既有随机回退的既有行为），跨重启写入落于不同水印；
   与「会话归因通道未接通」同族，留池待裁，不在本批范围。
4. **裁决**：工作流独立复核的 ACCEPT 维持；容器红栈按上述处置转绿，**未改动任何业务代码**。
