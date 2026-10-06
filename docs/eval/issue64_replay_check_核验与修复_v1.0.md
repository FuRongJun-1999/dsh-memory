# issue64 · replay_check 过严一票否决与空集短路放行——核验与修复报告 v1.0

**日期**：2026-10-06 ｜ **缺陷号**：issue64（外部报告 by angel12538，对 v0.7.5 实测；本工作流修前复现腿与独立复核双重复现）｜ **被测面**：`<仓根>` 工作树（未提交：`md_cg/consolidate.py`、`md_cg/test_p6_consolidate.py` 两件被改，本报告为第三件新增；`git status --porcelain` 实测三件）

**证据分级声明**（本报告只写有机械证据的事）：

| 标记 | 含义 |
|---|---|
| 〔本报告实跑〕 | 报告撰写员在本 ask 内亲手执行并计数：读码行号核实、HEAD/工作树 sha256、守卫 109/0、变异基线六腿、python 全量、git status |
| 〔工作流采集〕 | 本工作流前序阶段（修前复现编排 / 实施 / 独立复核，各角色定义见下「〇、角色与流程链」）实跑读数或材料转记，随任务材料传入；本报告逐处尽量标注来源，未重跑者明写未重跑 |
| 〔对拍〕 | 上述两侧读数逐位一致处 |

**未特别标记的正文行**（如 §三 契约三条、§五 判定依据与 uncovered、§6.1 留池理由）均属以下两类之一，不另含第三种来源：(a) 对源码的读码——同〔本报告实跑〕；(b) 对随任务材料转入文本的转记——同〔工作流采集〕。读者若需逐句溯源，可按此两分法判级。

行号口径：**改前** = HEAD `e3ca39b3` 的 `md_cg/consolidate.py`（sha256 前 16 位 `a831157411989a05`，〔本报告实跑〕`git show HEAD:md_cg/consolidate.py` 计算并与独立复核材料逐字节对拍一致）；**改后** = 工作树（sha256 前 16 位 `e886d8bcc09005c9`，〔本报告实跑〕计算）。两套行号均为读码所见。

**一句话结论**：外部报告的两类主指控全部独立复现成立——`replay_check` 的负条件一票否决把合格负条件误杀为「正例召回失败」（错否决），主流程的负条件空集短路把「缺要素」翻译成「通过」（错接受）；三处修复已落码并有定点变异自证与独立复核（判定 ACCEPT）。附带两处可配置性缺失（两角色预算/超时共用单值、timeout 不可配）同步修复。本轮明确不修的面共 4 条（判据宽严 ×2、防护差异 ×1、计数口径 ×1，逐条见 §6.1）登记留池（§六）。

---

## 〇、角色与流程链（先读·读者导航）

本报告的产出链是一条**动态工作流**（脚本编排、多个子任务接力），共四个角色。「独立复核」之所以独立，是因为它**自建实验台并重跑读数**（自写探针与 oracle、自行提取改前包），不采信实施侧的结论与探针：

| 角色 | 做什么 | 与本报告的关系 |
|---|---|---|
| 修前复现编排侧 | 在隔离环境（系统临时目录合成库 / 直调）**先于改动**复现缺陷，产出四条腿 payload 与读数 | 其读数经〔工作流采集〕传入（§二 主体）；采集时点先于修改，故称「修前现场」 |
| 实施侧 | 落三处代码修改与守卫 R 组，自跑守卫/定向回归 | 其材料（改动清单、守卫读数）经〔工作流采集〕传入 |
| 独立复核侧 | 重建实验台（`git archive HEAD` 提取改前包 + 自建探针与 oracle），对**改前/改后两树**对拍、删断言探针、ANCHOR-MISS 探针 | 其读数与 uncovered（§五）；与实施侧探针不同源，此为「独立」的判据 |
| 报告撰写员（本报告） | 读码核对行号与保真度、重跑守卫/变异基线/python 全量、撰写与修订 | 即〔本报告实跑〕标记的出处 |

流程链一句话：**编排侧复现（修前）→ 实施侧修复 + 守卫 → 复核侧独立对拍 → 本报告汇总**。

### 编号与术语约定（本报告有三套「①②③」，此处一次性对齐）

| 编号套 | 出现处 | 所指 |
|---|---|---|
| **外部报告 A 类①/②/③** | §一、§四 表#9、§6.1 | 外部报告对 `replay_check` 三个判据面的指控：①=`pos_recall` 的负条件一票否决（已修）；②=`neg_separated` 判据里「负条件对正文覆盖率 < 0.5」项（留池）；③=同族宽严（与 `no_conflict` 的覆盖率阈值同族，留池） |
| **修法条目 1/2/3** | §三 | 本次三处修改：1=`replay_check` 撤销一票否决；2=主流程负条件两态拦截；3=CLI 两角色预算/超时单设 |
| **变异腿 ①/②a/②b/②ab/③a/③b** | §四 表#3 | 按**修法条目**编号的六条定点变异腿（**不是**外部报告 A 类编号） |

另有旧称「②因子 / ③因子」（见 §二 腿 A①及其后）：分别指 `neg_separated` 判据里的 `coverage(tw_neg,BODY)<0.5` 项与 `no_conflict` 判据里的 `coverage(tw_pos,neg_text)<0.5` 项；本报告行文中已尽量改用判据全名。

**术语**：「变异（mutation）」在本报告一律指**注入缺陷方向**的定点改写（§四 表#3）；§二 腿 A① 中「删掉缺陷行的副本」是**删除式对照体**（方向相反），不称变异。

---

## 一、缺陷定义与真实站点

### 1.1 缺陷 A：`replay_check.pos_recall` 的负条件一票否决（过严误杀）

**定义**：`pos_recall` 原式带因子 `and not _neg_hit(tw_pos, neg_terms)`——「生效条件任一词（权重 ≥ 0.6）整词出现在不适用条件文本里」即判 `pos_recall=False`。门槛出处（读码）：`_neg_hit` 定义于 `md_cg/mdcos.py:300`，docstring 明写「只认高置信词（权重 ≥ min_weight，默认 0.6）且整词命中（`_term_degree ≥ 0.5`）」；`_term_degree` 定义于 `md_cg/mdcos.py:149`（分级命中函数，不是「子串出现即算」）。而负条件描述的正是**邻近易混情境**，与生效条件共享领域主题词是结构必然（不共享主题词就谈不上「邻近」）⇒ 该因子会**系统性误杀共享主题词的合格负条件**；该因子与 `no_conflict`（覆盖率口径，`<0.5` 才算互相覆盖）同意图且更严。已坐实的量：A① 单样本逐位复现（§二 腿 A①）+ 212 例 replay 直调中 10 例分歧全部属该类（§二末「复核侧扫面」）——本报告不称「大量」，量级以这两处为边界。

**三因子与合成（读码，工作树）**：`replay_check` 产出 `pos_recall` / `neg_separated` / `no_conflict` 三个因子，`ok = pos_recall and neg_separated and no_conflict`（`md_cg/consolidate.py:539`）——三因子全真才判「条件稳定」，任一判负即 `ok=False`。三处覆盖率度量均为 `_weighted_coverage`（定义于 `md_cg/mdcos.py:172`：词权 × 分级命中的加权覆盖率 ∈ [0,1]）。本缺陷①出在第一因子；A 类②/③ 分别是第二、三因子的阈值项（见 §6.1）。

**真实站点**：

- 改前 `md_cg/consolidate.py:510-512`——注释 `:510`、公式 `:511-512`，否决因子在 `:512`（读码所见；〔工作流采集〕材料记为 `:511-512`，指公式两行）。
- 改后撤销于 `md_cg/consolidate.py:524-525`（§三-1）。

**后果**：合格节点 `ok=False` → REJECT（**错否决**）。失效形态不是崩溃。

### 1.2 缺陷 B：主流程负条件空集短路被误判放行（错接受）

**定义**：`consolidate()` 主流程把 grounding 后的空 neg 直接交给 `replay_check`；而 `replay_check` 有 `if neg_terms: … else: neg_separated = True` 短路——「没有负条件」被翻译成「负例分离成立」⇒ `replay.ok=true`。两态（候选**未产出**负条件 / 产出了但**被 grounding 删光**）均无甄别 ⇒ 缺「不适用条件」要素的节点被误判「通过」、落盘并携带 `verification_basis` 声明；`ccg_completeness.complete=false`（ratio=5/6≈0.833，即缺一行）未被拦截。

机制出处（读码）：①「grounding 删光」= `grounding_filter`（`md_cg/consolidate.py:488`）按字段阈值（`DEFAULT_GROUNDING` `:119`）过滤候选，达标线之下者整体丢弃；其打分粒度是 `grounding_score`（`:478`）= 候选短语在正文里的 **bigram 命中率**（字符级支撑度）——「删光」即该字段全部候选的 bigram 命中率未达阈值（域外短语命中率 0.0）。②`ccg_completeness` 由 `md_cg/nodefile.py:448` 计算：按正文「# 字段」声明行（`ccg_mark_present`）统计四要素齐全度，`complete` 与 `ratio` 同源。③「闸门 2」= consolidate 模块头 docstring（`md_cg/consolidate.py:23-41`）定义的白箱三段闸门中的第二段——闸门 1 确定性 grounding（`:25-26`）、**闸门 2 确定性 replay（`:27-38`，即本缺陷落点）**、闸门 3 LLM 验证单元（`:39-41`）。

**真实站点**：

- 改前 `md_cg/consolidate.py:727-739`——`:730` 生成空 neg（`kept.get("不适用条件") or []`）、`:731` 直入 `replay_check`、`:732` 误判为「通过」；短路站点在 `:516-520`（`:519` `else:`、`:520` `neg_separated = True`）（读码所见；〔工作流采集〕材料记 `:728-739` 与 `:519-520`，指向同段）。
- 改后两态拦截于 `md_cg/consolidate.py:749-776`（§三-2）。

**后果**：缺要素节点落盘 + 携带声明（**错接受**）；亦可反过来说——该短路使「负条件被删光」不可能被任何下游检出。

### 1.3 附带缺陷：CLI 两角色预算/超时不可分别单设

**定义**：`--max-tokens` 是**单值**且同时喂 reflect/verify 两角色；`http_llm` 的 `timeout` 恒为模块默认 120（两 lambda 均未传，CLI 无入口）；`--reflect-max-tokens` / `--verify-max-tokens` / `--timeout` / `--reflect-timeout` / `--verify-timeout` 五个参数名全缺。

**真实站点**（读码所见）：

- 改前 `:1479`（`--max-tokens` 单值参数）、`:1533-1535` 与 `:1540-1542`（两 lambda 均写 `max_tokens=a.max_tokens`、均未传 timeout）、`:279-280`（签名 `timeout: int = 120`）。
- 改后落点 `:1526-1541` 参数、`:1596-1613` 透传（§三-3）。
- 相关机制出处（读码）：`resolve_max_tokens` 定义于 `md_cg/consolidate.py:228`（三级解析：显式参数 > env `MDCG_LLM_MAX_TOKENS` > `DEFAULT_MAX_TOKENS`）；「不带参回落 `resolve_max_tokens`」即指 `max_tokens=None` 时走该链取字面默认值。

**后果**：思考模型（reflect）与判决模型（verify）的预算/超时需求可不同，却无法分别调整；HTTP 超时不可配。

---

## 二、修前现场（本工作流采集的复现腿，逐条列 payload / 异常 / 崩溃点）

四条腿均为〔工作流采集〕的编排侧独立复现（隔离于实施侧探针）；每腿 payload 与读数原样列出。**跨腿共同结论先行**：四条腿**均无异常抛出、无崩溃点**——本缺陷的失效形态是错接受/错否决（独立复核明确修正：「同批输入在改动前实现上也不抛（pre.json 实测 0 异常）——『不再崩』成立但不是缺陷形态」，§五）。

### 腿 A① —— `replay_check` 负条件一票否决（唯一判负因子）

- **payload**：直调 `md_cg.consolidate.replay_check`；`pos=["海边甜品店 招牌蛋糕 做法"]`，`neg=["海边甜品店 的其它蛋糕 冷藏流程"]`，`BODY="# 功能名：海边甜品店招牌蛋糕做法\n海边甜品店招牌蛋糕做法：海边甜品店以招牌蛋糕为主打，蛋糕胚烘焙后冷藏定型，再以海岛水果与淡奶油裱花装饰。\n"`（自建合成体，体量/词面与编排侧探针等价）。运行：`cwd=%TEMP%\issue64_repro_v7gqwuxu`，`PYTHONPATH=<仓根>`，`PYTHONDONTWRITEBYTECODE=1 python -B -X utf8 leg_a1.py`。
- **observed**：返回 `{"pos_recall": false, "neg_separated": true, "no_conflict": true, "ok": false}`（与探针逐键一致）。逐因子读数：`coverage(tw_pos,BODY)=0.7981>0`（pos_recall 首因子为真）；`_neg_hit(tw_pos,NEG)=true`（**唯一杀手**）；`neg_separated` 的覆盖率项 `coverage(tw_neg,BODY)=0.4016<0.5`、`no_conflict` 的覆盖率项 `coverage(tw_pos,neg_text)=0.3702<0.5`，均未触发。反事实（内存按公式重算、不改文件）：删该因子后 `pos_recall=true`、`ok=true`。代码级对照自证：临时目录副本删掉 `and not _neg_hit(tw_pos, neg_terms)` 一行、以 `md_cg.consolidate_mutant` 名加载（不碰工作区）——真身 `ok=false` / **删行对照体** `ok=true`（这是**反向对照**：删掉缺陷行判负消失，证明该行是唯一杀手；与 §四「变异」的注入方向相反，勿混）。
- **异常/崩溃点**：**无异常**。站点 = 改前 `:510-512`。

> **样本对照提示（本报告内有两个同族 A① 样本，勿混）**：本腿用**编排侧合成体**（上列 BODY），其上读数 = `0.7981 / 0.4016 / 0.3702`；附录「最小复现」与守卫 R1 组用**守卫内联 BODY**（`md_cg/test_p6_consolidate.py:140-142`），其上读数 = `0.402 / 0.37`（即 R1b 断言名所称「②=0.402 / ③=0.37」）。两组词面不同、各自独立测量，不互相复现；「0.402/0.37 与 0.4016/0.3702」为同一判据面、两样本词面的读数对（0.402↔0.4016、0.37↔0.3702，前者为后者四舍五入）。

### 腿 B 态1 —— 候选有负条件但被 grounding 删光 → 放行

- **payload**：隔离临时库（`tempfile.mkdtemp(prefix='issue64_legB_state1_neg_dropped_all_')`）+ `MdCGOS(root).add('n1', 微分方程夹具 BODY)`；reflect 打桩返回 `{"生效条件":["微分方程","数值方法"],"子功能":["建模","求解"],"执行":"使用数值方法迭代求解","不适用条件":["冰川溶洞探险装备清单"]}`（域外 → grounding 0.0）；verify 打桩返回 `"{}"`；`consolidate(root, apply=True, …)`；并在进程内包裹 `replay_check` 记录主流程实参。运行：`PYTHONPATH=<仓根> python -B -X utf8 leg_b.py`。
- **observed**（仪器化证据）：主流程实际传入 `replay_check` 的 `neg=[]`（空列表）→ 命中 `:519-520` 短路。`rep={targeted:1, accepted:1, rejected:0, deferred:0, written:1, reasons:{}}`；落盘 `fm.llm_consolidation.grounding.不适用条件={"scores":{"冰川溶洞探险装备清单":0.0},"kept":0}`；`llm_consolidation.replay={"pos_recall":true,"neg_separated":true,"no_conflict":true,"ok":true}`；`llm_consolidation.verification_basis="stub 验证声明"`；正文无「# 不适用条件」行（有「# 验证方式」行）；`fm.non_applicable_conditions=[]`；`fm.verification_basis="other"`；`nodefile.ccg_completeness.complete=false` `ratio=0.833`；节点文件被改写；演化台账 `_evolution/ledger.md` 证据行「grounding通过 · replay通过 · stub 验证声明」——**缺「不适用条件」要素却携 replay通过 与 verification_basis 声明落盘**。与探针读数逐项一致。
- **异常/崩溃点**：**无异常**。站点 = 改前 `:727-739`（`:730` 生成空 neg、`:731` 传入、`:732` 误判）+ 短路 `:516-520`。

### 腿 B 态2 —— 候选根本没有「不适用条件」键 → 放行

- **payload**：同态1 隔离库夹具；reflect 打桩候选改为 `{"生效条件":["微分方程","数值方法"],"子功能":["建模","求解"],"执行":"使用数值方法迭代求解"}`（无负条件键）；verify 打桩 `"{}"`。运行：`PYTHONPATH=<仓根> python -B -X utf8 leg_b.py`（第二用例）。
- **observed**：主流程传入 `neg=[]`；`rep accepted=1/written=1/rejected=0/reasons={}`；落盘 `grounding.不适用条件=null`（无该字段明细，与态1 的 `kept=0` 明细可甄别）；`replay.ok=true`；正文无「# 不适用条件」行；`fm.non_applicable_conditions=[]`；`ccg_completeness.complete=false`（`ratio=0.8333`——与态1 的 `0.833` 为**同一读数**（5/6）的两种精度写法，非两态差异；§一 1.2 统一写作 `ratio=5/6≈0.833`）。**两态（被删光 / 未产出）在修前均无甄别、均放行。**
- **异常/崩溃点**：**无异常**。站点 = 改前 `:730-739`。

### 腿附带参数 —— 单值喂两角色、timeout 不可配、新参数名全缺

- **payload**：subprocess 跑 `python -B -X utf8 -m md_cg.consolidate --help`（`cwd=%TEMP%`，`PYTHONPATH=<仓根>`）；进程内打桩 `http_llm` 后调用 `_cli(["--root",<临时库>,"--apply","--max-tokens","7777"])` 及不带 `--max-tokens` 各一次，记录两角色实收参数。运行：`PYTHONPATH=<仓根> python -B -X utf8 leg_cli.py`。
- **observed**：`help rc=0`；含 `--max-tokens=true`；`--reflect-max-tokens` / `--verify-max-tokens` / `--timeout` / `--reflect-timeout` / `--verify-timeout` **均=false（参数名全缺）**。`inspect.signature(http_llm)` 显示 `timeout: int = 120`（模块级默认，CLI 无入口覆盖）。带 `--max-tokens 7777` 时两角色实收 `[{role:reflect, max_tokens:7777, timeout_passed:false},{role:verify, max_tokens:7777, timeout_passed:false}]`（同一单值喂两角色；两 lambda 均未传 timeout → 真身走 120 默认）；不带参时两角色 `max_tokens=null`（回落 `resolve_max_tokens`）。两轮 `rep.written=1`。
- **异常/崩溃点**：**无异常**。站点 = 改前 `:1479`、`:1533-1535`、`:1540-1542`、`:279-280`。

### 复核侧扫面（独立复核，〔工作流采集〕——注意树别）

**树别先行**：复核侧把**修前各腿的同一批输入**同时喂给**改前包**（`git archive HEAD` 提取的 `pre_pkg`）与**现行树**两份实现。下述条目 1-3（B1/B2、15/15 例）是**现行（修后）树**的读数——「`rejected=1` / `samples.replay=None`」正是修后拦截生效的形态，**不是**修前现场（修前现场见 §二 各腿：`accepted=1/written=1/reasons={}`）；条目 4-6 是两版本同批与两式对照。

1. `probe_sweep.py`（同一批输入分别喂 HEAD 版与现行版）：**现行树** 15 全链例 + 空池 + 212 例 replay 直调，异常数 0；`B1_neg_dropped_all → rejected=1/reasons={"neg_dropped_all":1}`、`B2_neg_absent → {"neg_absent":1}`、`samples[0].reason` 同名且 `replay=None`（未进 replay 即被拦）——即两态拦截在现行树上生效。
2. 退化路径「真发生」的判据（非只看没抛）：B1 样本 `samples[0].grounding_neg={"scores":{"量子色动力学格点规范场论":0.0},"kept":0}` 而候选该字段非空 ⇒ 确系「产出后被 grounding 删光」，不是输入本来就空。
3. 独立扫描互证（现行树）：枚举库内全部文件 sha256，15/15 例满足 `written=0 ⇔ 节点文件集与哈希逐字未变`、`written=1 ⇔ 变化`（空池=0 节点零计数不抛，节点集为空与扫描一致）。
4. 退化输入无异常（两版本同批）：neg 为空串/空表/`[None,"   "]`/标量串、pos 全幻觉、空正文节点、空库。
5. 212 例 replay 直调（两式逐例比对）：oracle 由复核侧自写——`pos_recall_new = pos_text 非空 ∧ coverage>0`；`old = 上式 ∧ ¬_neg_hit`。判定：202 全等、10 分歧且全部恰为旧式一票否决类（`pos_recall` False→True，`neg_separated`/`no_conflict` 逐位不变）、非法分歧 0、两侧例外 0。**分类规则如实标注**：「全等 / 旧式一票否决类分歧」的判据=上述两式逐位比对；「非法分歧 / 两侧例外」是复核侧自写的两类兜底项，其判据**未随任务材料提供**，本报告只转记读数为 0，未能核实其定义。
6. A① 样本中间量独立重算：`legacy_neg_hit=True`、`neg_separated` 项 `cov=0.4016`、`no_conflict` 项 `cov=0.3702`（与守卫 R1b 的 0.402/0.37 为同一判据面、两样本词面的舍入口径；样本对照见 §二 腿 A①尾注）。

---

## 三、修法契约与落点（三处，均在 `md_cg/consolidate.py`；行号为工作树读码所见）

> 编号提示：本节三条即**修法条目 1/2/3**（与外部报告 A 类①②③、变异腿 ①~③b 的对照见 §〇 约定表）。

**契约三条（修法 1/2/3）**：1 撤销过严因子——`pos_recall` 只认「生效条件在正文上有覆盖率」，自否定职责由 `no_conflict` 覆盖率口径承担；2 负条件两态拦截——缺「不适用条件」要素（未产出 / 被 grounding 删光）直接 REJECT，不得因空集短路被判「通过」；3 CLI 两角色预算/超时可分别单设，原单值语义作共用缺省保留。

### 1) `replay_check`：撤销负条件一票否决（`:507-541`）

- 改后 `:524-525`：`pos_recall = bool(pos_text) and _weighted_coverage(tw_pos, body) > 0.0`（删除 `and not _neg_hit(tw_pos, neg_terms)`）。
- docstring `:513-517` 与上方「生效条件：」注释 `:507` 同步写明撤销理由；模块头 docstring 闸门 2 条目同步（`:27-38`）。
- **未动**：`neg_separated`（`:529-533`）与 `no_conflict`（`:535-537`）判据本体、`replay_check` 其余返回键与语义。

### 2) `consolidate()` 主流程：负条件两态拦截（`:749-776`）

`grounding_filter`（`:745`）之后、`replay_check`（`:778`）之前：

- `neg_cand = cand.get("不适用条件") or []`（`:757`；`:758-760` 标量化与去空白项）→ 空 ⇒ `rejected+=1` + `_bump("neg_absent")` + samples 带 `reason:"neg_absent"`、`replay:None`、`continue`（`:761-768`）；
- `neg_cand` 非空而 grounding 后 `neg` 空 ⇒ `rejected+=1` + `_bump("neg_dropped_all")` + samples 带 `reason:"neg_dropped_all"`、`replay:None`、`continue`（`:769-776`）。
- 两态都**不进 verify、不落盘**；原 `if not kept or not replay["ok"]`（`:779-786`）代码行保持原样。`consolidate()` docstring 同步（`:675-683`）。
- **独立复核修正（如实）**：修后 `kept=={}` 时两态拦截先行 `continue` ⇒ `:781` 的 `grounding_failed` 分支不再可达（详见 §五-1）——「grounding_failed / replay_failed 语义不变」的表述不精确：代码行未动属实，但 `grounding_failed` 不再是可达结论（两态都是 REJECT、都不落盘，属报表口径）。

### 3) CLI：两角色 max-tokens / timeout 可分别单设（`:1526-1541` 参数、`:1596-1613` 透传）

- 新增 `--reflect-max-tokens`（`:1531-1532`）/ `--verify-max-tokens`（`:1533-1534`）——缺省 None → 回落 `--max-tokens`；新增 `--timeout`（`:1535-1537`，默认 120）/ `--reflect-timeout`（`:1538-1539`）/ `--verify-timeout`（`:1540-1541`）——缺省 None → 回落 `--timeout`；原 `--max-tokens`（`:1526-1530`）语义不变（共用缺省）。
- 透传：`refl_mt`/`refl_to`（`:1596-1599`）→ reflect lambda `:1600-1602`；`ver_mt`/`ver_to`（`:1607-1610`）→ verify lambda `:1611-1613`；`--self-verify` 复用反思侧（`:1603-1604`）。
- `http_llm` 本体未改（`:285-286` 签名原样），docstring 补 timeout 来源一句（`:293-294`）。

### 「不许动」清单核对（本报告读码核实）

`no_conflict` / `neg_separated` 判据本体 ✅未动｜`grounding_filter` / `DEFAULT_GROUNDING` 阈值 ✅未动（`:119` 原值 `{"生效条件":0.5,"子功能":0.5,"执行":0.5,"不适用条件":0.34}`）｜`replay_check` 其余返回键与语义 ✅未动｜**ccgc 路代码面 ✅未动**——依据：本次改动面不含 ccgc 相关文件（`git status --porcelain` 实测仅两改一新增）；此处「ccgc 路」= `md_cg/ccgc.py` 的编译-签章路径（签章拒绝码表 E040-E043 见 `md_cg/ccgc.py:65-68`，`E041`=自证拒绝判据见 `md_cg/audit.py:485-518`），与 consolidate 路（`md_cg/consolidate.py`）为并列两路；本报告只核对「改动面未含」，不展开其内部语义｜改动文件面：仅 `md_cg/consolidate.py`、`md_cg/test_p6_consolidate.py` 与本报告（`git status --porcelain` 实测）。

---

## 四、验证数字

| # | 项 | 命令（原样） | 结果 | 来源 |
|---|---|---|---|---|
| 1 | 守卫（含 R 组） | `python -X utf8 -m md_cg.test_p6_consolidate` | **109 通过 / 0 失败**，退出码 **0**（既有 82 项 + R 组 27 项） | 〔本报告实跑〕 |
| 2 | R 组断言构成 | 同上输出逐条计数 | 27 = R1 3（R1a-c）/ R2 3（R2a-c）/ R3 5（R3a-e）/ R4 5（R4a-e）/ R5 3（R5a-c）/ R6 8（R6a + 四参数名 + R6b/R6c/R6d）。**各组语义**：R1=撤销①的复现样本、R2=自否定兜底不退化、R3/R4=B 类两态全链 REJECT、**R5=不误伤组**（合法候选照常 `accepted=1/written=1`、`replay.ok=True`、「# 不适用条件」照常落盘；`md_cg/test_p6_consolidate.py:296-312`）、R6=CLI 组。**「四参数名」是哪四个**（`md_cg/test_p6_consolidate.py:326-328`）：`--reflect-max-tokens` / `--verify-max-tokens` / `--reflect-timeout` / `--verify-timeout`——即四个**角色级**新增参数；§一 所列的第五个参数 `--timeout` 是共用缺省，不入帮助文本断言，而由 R6d 行为面直接使用并断言实收 7.0（`md_cg/test_p6_consolidate.py:340-358`） | 〔本报告实跑〕 |
| 3 | 变异自证 | `python -X utf8 -m md_cg.test_p6_consolidate --mutation-baseline` | 未变异基线红项 0；六腿红项 **3 / 2 / 5 / 10 / 1 / 1** 全等于登记值；退出码 **0** | 〔本报告实跑〕 |
| 4 | 删断言探针（复核） | 内存态删组后重跑守卫 | 删 R3 组 → 退出码 1（②b 红项 0≠5）；删 R4 组 → 退出码 1（②a 0≠2）；删 R2 组 → 退出码 1（① 2≠3） | 〔工作流采集〕 |
| 5 | ANCHOR-MISS 门 | 内存态锚点漂移探针（替身/重复/两条漂移） | 默认与 `--mutation-baseline` 两模式均退出码 **2**（fail-closed，打印 ANCHOR-MISS 清单） | 〔工作流采集〕 |
| 6 | python 全量 | `python -X utf8 scripts/run_tests.py` | **359/359 通过，5 跳过（依赖缺失/平台不符）**，退出码 **0**。口径：`359/359`=**可运行目标** 359 个全过；`5 跳过` 是**另计**的 5 个目标（不在 359 内），目标总数 = 359 + 5 = 364（打印式见 `scripts/run_tests.py:283-284`：「通过数/可运行数，跳过数」） | 〔本报告实跑〕（与〔工作流采集〕数字一致） |
| 7 | 容器栈一 | `docker run --rm -v <仓根>:/work -w /work rust:bookworm bash scripts/linux_verify.sh full` | 退出码 **0**（`结果: 22 pass / 0 fail`；`[PASS] smoke_test (linux)`；`=== 汇总: 49 pass / 0 fail ===`） | 〔工作流采集〕（本报告未重跑） |
| 8 | 容器栈二 | `docker run --rm -v <仓根>:/work -w /work node:22-bookworm bash scripts/verify_linux_node.sh` | 退出码 **0**（`# cancelled 0` ｜ `# skipped 3` ｜ `# todo 0` ｜ `# duration_ms 12470.924826`） | 〔工作流采集〕（本报告未重跑） |
| 9 | 修前/修后对拍（A 类①） | 同脚本复跑 | `pos_recall` false→**true**、`ok` false→**true**；②/③ 读数不变（0.402 / 0.37） | 〔工作流采集〕 |
| 10 | 修前/修后对拍（B 类两态） | 隔离库全链 | `accepted=1/written=1` → **`rejected=1/written=0`**；`reasons` 由 `{}` → `{"neg_dropped_all":1}` / `{"neg_absent":1}`（可甄别）；盘上内容逐字未变 | 〔工作流采集〕 |
| 11 | 合法输入不误伤 | 两例合法全链（复核材料记作 `L1`/`L2`——**样本名**，与纪律 17 的只读层级「L1 直跑」同名不同义）+ 212 例 replay 直调 | 合法全链归一化 3 处墙钟时间戳（`created_at` / `condition_space.time_window` / `llm_consolidation.at`）后逐位全等；212 例中 202 全等、10 分歧恰为旧式一票否决类、非法分歧 0 | 〔工作流采集〕 |
| 12 | 修前退化输入异常数 | `probe_sweep.py` | 异常 0（**缺陷形态是错接受/错否决，不是崩溃**） | 〔工作流采集〕 |

**变异腿红项名单**（〔本报告实跑〕输出逐条）：① 恢复一票否决 → R1a、R1b、R2c；②a `if not neg_cand:`→`if False:` → R4b、R4e；②b `if not neg:`→`if False:` → R3a-R3e；②ab 两态整体删除 → R3 五 + R4 五；③a reflect 侧未透传单设 → R6b；③b verify 侧未透传单设 → R6c。**缺口如实登记**：R6a + 四参数名断言走 subprocess 跑盘上模块，内存变异打不到 ⇒ 不登记变异腿（判别力由四参数名逐一断言承担，§五-2）。

**变异基线机制**：锚点 = 守卫文件内**联的源码文本**（`_MUTATIONS` 表，`md_cg/test_p6_consolidate.py:382-406`），不读 git HEAD（全文件无 git 调用）；锚点缺失/不唯一 → ANCHOR-MISS → 退出码 2（`_anchor_report` :409-423、`main` :470-479）；变异为内存态源码替换、不落文件（`_mutate` :426-434）。

---

## 五、独立复核判定与它列出的 uncovered

### 判定：**ACCEPT**

依据（**复核侧原文，随任务材料传入**〔工作流采集〕）：按工作纪律第5条 验证纪律——入库前必须过回放/断言/回归验证，未验证不固化。L1 直跑留痕（此处「L1」=纪律 17 的只读判定层级，与 §四 表#11 的样本名 `L1`/`L2` 同名不同义）：`python -X utf8 -m md_cg.test_p6_consolidate` 与 `--mutation-baseline`——只读判定（产物落点=仅系统临时目录合成库，跑完清理；不改仓库/外部状态），秒级-分钟级，可逆。复核为本次工作流内独立于实施侧的执行（实验台、探针、oracle 均自建）。

**复核手段（全部〔工作流采集〕实跑）**：① 双树对拍——`git archive HEAD md_cg` 提取 `%TEMP%/issue64_review/pre_pkg`（consolidate.py sha256=`a831157411989a05` 与 HEAD blob 逐字节相同）；现行树 `e886d8bcc09005c9`；② `probe_sweep.py` 15 全链例 + 空池 + 212 例 replay 直调，异常 0；③ 自写 oracle 逐例判定；④ 删断言探针；⑤ ANCHOR-MISS 探针（替身/重复/漂移三式均退出码 2）；⑥ 两态可观测面独立复得（`reasons` 键可区分 `neg_absent`/`neg_dropped_all`、`samples` 带 `reason` 且 `replay=None`；`_cli` stdout（`consolidate.py:1626` 打印 rep）实测含 `"reasons": {"neg_dropped_all": 1}` 与 `"written": 0`）；⑦ 工作区完整性——跑前跑后工作区 sha256 与 `git status` 与会话起始逐字一致；收尾删除 18 个 `i64_*` 与 45 个 `mdcg_p6_*` 残留（实验库根全部 `tempfile.mkdtemp`）；**更早运行遗留 2538 个未动**——「属他人产物」为复核侧判据的转记，其判定依据未随任务材料提供、本报告未能核实，此处只转记「删 63 留 2538」这一动作边界。

### 它列出的 uncovered（逐条）

1. **`grounding_failed` 分支修后不可达**（非阻断发现）：实测 pre 三例 `D_empty_body` / `D_hallu_pos_neg_absent` / `D_hallu_pos_neg_dropped`（复核探针内例名）的 reason 由 `grounding_failed` 变 `neg_absent`/`neg_dropped_all`；全仓 grep 仅该代码站点与报告提及、无下游消费者。**被修正的原句出处**：实施材料原表述为「原 `:779-786` 与 `grounding_failed`/`replay_failed` 语义保持」（随任务材料传入；本报告 §三-2 转记其大意）——独立复核指出其不精确：代码行未动属实，但 `grounding_failed` 不再是可达结论。**「报表」指什么**：`consolidate()` 返回的 `rep` 字典（`reasons` 计数与 `samples` 为其字段），`_cli` 在 `md_cg/consolidate.py:1626` 原样打印同一 `rep` JSON（可选 `--report` 落盘）；节点 frontmatter 的 `llm_consolidation` 证据摘要由 `_evo_evidence`（`md_cg/consolidate.py:604`）拼接、并投影到演化台账 `_evolution/ledger.md` 的证据行。「分支不可达」= 在两态输入下 `grounding_failed` 不会再出现在 `reasons` 里——属**报表口径**的可见性变化，不是落盘行为变化（两态都是 REJECT、都不落盘）。
2. **R6 的变异覆盖缺口**：R6a + 四参数名断言走 subprocess 跑**盘上模块**，内存态变异打不到 ⇒ 不登记变异腿；判别力由「四个参数名逐一断言」承担（删任一参数即红）。
3. **删断言探针的边界（自指守卫固有）**：删 R3 组 + 同删 ②b 与 ②ab 两条变异腿 → 退出码 0（**静默**）——属自指守卫固有边界，若不声明即风险，记入守卫面残留风险。
4. **修前实现同批输入亦不抛异常（0 异常）**：「不再崩」成立但不是缺陷形态；本缺陷形态是错接受/错否决。
5. **生产两 lambda 的真实网关未验证**：超时/预算**单设**只在打桩层面验证（R6b/R6c/R6d 与 ③a/③b 变异腿）；未对真实网关发请求（零 token；不越界）。

### 复核/复现材料清单（读者可得性）

本报告引用的前序阶段材料均**未入库**（由各阶段在系统临时目录生成，或仅为材料内名称）；本报告已把其 payload/读数原文转记在对应章节。

| 材料 | 出处（角色/位置） | 读者当前可否取到 |
|---|---|---|
| `leg_a1.py` / `leg_b.py` / `leg_cli.py` | 修前复现编排侧；`%TEMP%\issue64_repro_v7gqwuxu` 等临时目录 | 否（未入库；payload 与读数已转记于 §二） |
| `probe_sweep.py` | 独立复核侧；系统临时目录 | 否（未入库；读数见 §二末「复核侧扫面」） |
| `pre.json` | 独立复核侧（改前包同批输入的异常计数） | 否（未入库；本报告转记「0 异常」） |
| `%TEMP%/issue64_review/pre_pkg` | 独立复核侧（`git archive HEAD` 提取的改前包，consolidate.py sha256=`a831157411989a05`） | **可复现**：同一命令（§附 复现命令末行） |
| `D_empty_body` 等三例 / `S2` / `S4` | 复核材料内例名（样本本体未随材料提供） | 否（只存名称） |
| 「复核侧原文」（ACCEPT 依据、uncovered 各条） | 本工作流独立复核阶段材料 | 否（本报告已逐条转记，本节即其出处） |

---

## 六、边界与未覆盖（含本轮明确不修而留池的面）

### 6.1 本轮明确不修（登记留池，修复范围严格限于 §三 三处；共 4 条 = 判据宽严 ×2 + 防护差异 ×1 + 计数口径 ×1）

1. **A 类②**（`neg_separated` 判据里「负条件对正文覆盖率 < 0.5」项过严）：判据设计边界——词面判据无法区分「复制正文」与「用正文词描述的邻近情境」，S2/S4 样本连续过渡（样本名见 §五 材料清单）；若后续要收 ② 的边界，需先立设计稿（不在本缺陷范围）。
2. **A 类③同族宽严问题**：外部报告对 ③ 的原文**未随材料提供**（材料只给「同族宽严」概括）；实施契约明令不动 ③ 本体——即 `neg_separated`（`:529-533`）与 `no_conflict`（`:535-537`）的**覆盖率阈值判据**；③ 兜底不退化由 R2 钉住。
3. **「B 路（consolidate）无 E04x 签章闸而 ccgc 路有」**：术语先定义——两路=**consolidate 固化路**（`md_cg/consolidate.py`，本报告被测文件）与 **ccgc 编译-签章路**（`md_cg/ccgc.py`；E04x 是其签章拒绝码表 `:65-68`：E040 无验证签章 / E041 自证拒绝 / E042 验证未通过）；「签章闸」=后者对「验证方 ≠ 编译执行者」的机械拒绝机制。本条属两路防护**设计差异**，非本缺陷面；本报告只核到「本轮改动面未含 ccgc 相关文件」（§三 清单），不裁决该差异。
4. **「短流水（<N 字符）计入 rejected 污染计数」**：计数口径问题（短文本判据、报表分桶——「报表」定义见 §五-1），非本缺陷面。

### 6.2 未覆盖 / 残留风险

- 真实 reflect/verify 网关零请求：预算/超时单设的生产面仅打桩验证（§五-5）。
- A②/③ 的连续过渡区间（S2/S4）未建独立样本库。
- `grounding_failed` 可达性（修后不可达）留作报表口径观察项（§五-1）。
- 删断言 + 删对应变异腿的**双删静默**边界为自指守卫固有（§五-3），无法在本守卫内自证完全。
- 容器两栈（§四-7/8）与复核类读数（§四-4/5、§五）来源为**本工作流前序阶段实跑**，本报告未重跑；本报告实跑面 = 读码行号核实、sha256、守卫 109/0、变异基线六腿、python 全量 359/359、`git status`。如后续阶段数字需对拍，以各自阶段实跑为准。
- 未提交状态：`git status --porcelain` 仅两改一新增；未 `git add`/`commit`/`push`；未动在役数据根与 `data/policy.json`。

---

## 七、开放问题（读者提问的处置）

以下 9 条来自读者反馈的后续提问；能给事实的给事实，属工作流外决策的明确标注「本报告不裁决」、不预告时间。

1. **三件改动何时入库**：截至本报告，`git status --porcelain` 仅两改一新增，未 `git add`/`commit`/`push`；入库/发版/给外部报告者回执均属工作流外决策，本报告不裁决、无时间表。
2. **外部报告 issue64 原文**：未随本工作流材料提供；本报告的「两类主指控 / A 类①②③」是对材料中要点的转述，无法与原文逐字对照。
3. **真实网关上的预算/超时单设**：未做、未排期；本报告只登记「仅打桩面验证」这一事实（§五-5）。
4. **同类「负条件空集」是否存在于 consolidate 之外的写入路径**：本报告**未排查**（工作面限于 consolidate 路）；§6.1-3 只登记两路防护差异，不等于已排除其它路径。
5. **A 类②/③ 的影响面 / `S2`、`S4` 样本本体**：影响面量化未做；`S2`/`S4` 为复核材料内样本名，样本本体未提供（§五 材料清单）。
6. **复现材料能否随报告提供**：所列材料均未入库（§五 材料清单）；是否随报告发布/入库属工作流外决策。
7. **自指守卫盲区是否加 CI 兜底门**：§五-3 的「双删静默」是自指守卫固有边界；是否加外部计数/断言门属工作流外决策，本报告不裁决。
8. **2538 个更早残留**：复核侧只记录「未动」（§五 复核手段⑦）；是否需要清理及影响，本报告未能核实，登记为待决项。
9. **版本与回执**：缺陷针对 v0.7.5 实测、修复当前停在工作树（未提交）；进哪个版本、是否回执外部报告者，属工作流外决策。

---

## 附：复现命令

```text
# 守卫（含 R 组；仓根执行）
python -X utf8 -m md_cg.test_p6_consolidate
# 定点变异自证（六腿红项数须与登记值相等）
python -X utf8 -m md_cg.test_p6_consolidate --mutation-baseline
# python 全量
python -X utf8 scripts/run_tests.py
# 容器两栈（镜像与命令形态见脚本头注 / 既有记录）
docker run --rm -v <仓根>:/work -w /work rust:bookworm bash scripts/linux_verify.sh full
docker run --rm -v <仓根>:/work -w /work node:22-bookworm bash scripts/verify_linux_node.sh
# 复核侧实验台第一步：提取改前包（HEAD 版 md_cg 子树）
git archive HEAD md_cg | tar -x -C <目标目录>
```

A 类① 最小复现（存为 `%TEMP%/probe_a.py` 后 `python -X utf8 %TEMP%/probe_a.py`；仓根不可直接以 `-c` 传中文——规避 Windows shell 的 GBK 解码）：

```python
from md_cg.consolidate import replay_check
POS = ["海边甜品店 招牌蛋糕 做法"]
NEG = ["海边甜品店 的其它蛋糕 冷藏流程"]
BODY = "海边甜品店招牌蛋糕做法：奶油打发后低温烘焙，成品当日冷藏保存。"
print(replay_check(POS, NEG, BODY))
# 修前：{'pos_recall': False, 'neg_separated': True, 'no_conflict': True, 'ok': False}
# 修后：{'pos_recall': True,  'neg_separated': True, 'no_conflict': True, 'ok': True}
```

B 类两态全链复现：打桩 reflect 恒返回 `R_CAND_DROP`（态1，含域外负条件）/ `R_CAND_ABSENT`（态2，无负条件键）（`md_cg/test_p6_consolidate.py:149-155`）、verify 恒返回 `"{}"`，`consolidate(root, apply=True, …)` 于 `tempfile.mkdtemp` 隔离库；R3/R4 组即该复现的守卫化（修后 `rejected=1`、`reasons` 记 `neg_dropped_all`/`neg_absent`、不落盘）。
