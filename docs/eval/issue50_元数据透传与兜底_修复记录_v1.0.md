# issue50-c · 遗忘闸门 DEFER 出口元数据透传与 node_id 兜底——修复记录 v1.0

> **日期**：2026-10-01 ｜ **缺陷号**：issue50-c ｜ **被测面**：`<仓根>` 工作树（未提交）
> **关联**：issue50-a（`forgetting` 分支④「半重复→DEFER」结构性不可达）→ `docs/eval/issue50_半重复待定复核_修复记录_v1.0.md`；
> issue50-b（DEFER 出口接线入队）→ `docs/eval/issue50_待定复核入队_修复记录_v1.0.md`；本轮落修的是 **issue50-b 报告 §5.2 所列 uncovered 的 F1/F2 两项**。
> **证据口径**：〔实跑〕= 我（报告撰写员）在本会话亲自执行并读到输出；〔采集〕= 本工作流复现阶段所得，我未重跑；〔复核实跑〕= 本工作流**独立复核阶段**所得，我未重跑（其探针在仓外临时目录）。

---

## 零、口径

### 0.1 三棵树与本文行号

| 名称 | 是哪棵树 | 本文哪里用它 |
|---|---|---|
| **修前**（= 缺陷现场） | 已应用 issue50-a / issue50-b、**未应用 issue50-c** 的 `md_cg/mdcos.py` | §一.3 的「修前」列、§二各腿的站点列 |
| **当前盘**（= 修后） | `<仓根>` 工作树（a + b + c 都在） | 全文「修后」与所有〔实跑〕读数 |
| **HEAD** | `git -C … diff` 的对照面（a/b/c 三批**均未提交**，故 HEAD 里 `mdcos.py` 三个改动都不存在） | §三.1 的 diff hunk 读数 |

**行号来源（不是两种做法，只有一种）**：本文所有「修前」行号**不是本报告侧换算的结果，而是转引** issue50-b 报告 §3.1/§1.3 的表（该表由 b 报告实跑 `git diff` 得出，我读其正文转抄而来）。所有「当前盘」行号均为**本次读码所见**。两者是**同一棵树上的两种坐标**（同一处代码在修前树与当前盘上行号不同），不一致时以当前盘为准并列出差额；§二各腿站点列因此是**转引来的修前坐标**，不是我从当前盘反推的。

### 0.2 本轮的位置：把 b 批「留池」的 F1/F2 落修

issue50-b 报告 §5.2 列出的两项已复现发现、§6.2 第 2/4 条把它列为「本轮明确不修、留池的面」，本轮即这两项：

- **F1（扩面修）**：DEFER 出口入队时**只传 content/layer/sensitivity**，调用方声明的其余 meta 全丢 → 「同一声明」下 DEFER→accept 与直接 ACCEPT 的节点 frontmatter 不等价；
- **F2（捩点收口）**：`node_id=None` 时 `propose` 造 pid 的 `node_id + str(...)` 抛 `TypeError`。

### 0.3 结论摘要

| 项 | 值 | 来源 |
|---|---|---|
| F1 缺陷（**修前**） | 「同一声明」下两条落地路径元数据不等价：DEFER→accept 节点丢 tags / condition_space / verification_basis / non_applicable_conditions / derived_from / derived_relation（role 亦是）；**修前**该路 `bucket_zh` 亦**不生成**（本次实跑复现模拟修前入队：`keys=23` / `bucket_zh` 缺键 / `tags=[]`）。**修后**这些键两路**逐位相等**（含 `bucket_zh`），见 §4.1/§4.7 | §一.1〔读码〕+ §二 L1〔采集〕+ §4.7〔实跑〕 |
| F2 缺陷 | `remember_gated(None, 半重复, …)` 崩 `TypeError: unsupported operand type(s) for +: 'NoneType' and 'str'` | §一.2〔读码〕+ §二 L2〔采集〕 |
| 修法 | F1：入队把本闸收到的 meta 随 `**kw` 交给 `self.propose`（`tags`/`condition_space` 落 rec 专属槽、其余落 `extra`），accept 分支**既有**映射把它写回 fm，`review_decide` 零行为改动；F2：`_nid` 兜底成内容派生 id（复用 `forgetting._prefeed_id`），非静默写返回体 | §三〔实跑 `git diff`〕 |
| 行为改动面 | `mdcos.py` **唯一行为改动** = DEFER 分支内的入队调用改为 `**kw` 透传 + `_nid` 兜底 + 兜底标注；其余 diff 全是注释 / docstring / `# 生效条件` 行 | §三.1 |
| 守卫 | 新建 `md_cg/test_i50c_meta_passthrough.py`（592 行），**30 断言 / 30 通过 / 0 失败，rc=0**；`--mutate` 11 处变异红项 `11/5/4/6/1/3/5/1/2/1/1` 逐处命中，rc=0 | §4.1/§4.2〔实跑〕 |
| 删断言 / fail-closed 探针 | 内存删 `g_a` → 变异①红项 11→3（红项 = B1/B2/B3）；内存删 `g_c` → `_mutate_mode()` rc=1 并点名 ④⑤ 红项数不符；注入假锚点 → `_anchor_check()` 1 条 + rc=2 | §4.3〔实跑·本会话新增〕 |
| python 全量 | `python -X utf8 scripts/run_tests.py` **连跑两次** → 两次均 **rc=0、SUMMARY 302/302 通过、5 跳过**（221.6 s / 223.6 s，读数逐字相同）。**与采集值（300/302、两项失败、rc=1）不一致**，差异项即采集所报的 `md_cg.test_issue39_utf8_stdio` 与 `scripts.test_utf8_boot_guard`，我单跑两项均绿；**未做归因实验** | §4.5〔实跑〕 |
| 容器两栈 | 栈一 rc=0（`smoke_test` 自报 22 pass/0 fail；`linux_verify.sh` 自计数 38 pass/0 fail）；栈二 rc=0（TAP：`# cancelled 0` / `# skipped 3` / `# todo 0`）。**我未运行**（docker 在 PATH，本轮未起容器） | §4.6〔采集〕 |
| 独立复核 | 判定 **ACCEPT**（依据四态判定单）。其 uncovered 清单**原文未随材料给到我**，见 §5.2 | §五〔转述 + 实跑〕 |
| 硬边界 | 全部实验根在 `%TEMP%` 隔离目录；未触在役数据根；未 `git add`/`commit`/`push`；本次只写入本报告一个文件 | §6.3 |

### 0.4 术语与计数口径（正文首次出现即在此定义）

| 术语 | 本文含义 |
|---|---|
| **四态** | 遗忘闸门 `forgetting.assess` 的四种裁决：**ACCEPT**（落盘）/ **MERGE**（并入既有）/ **DROP**（丢弃、正文进 `_forgetting.jsonl`）/ **DEFER**（不落盘，交待定复核） |
| **四态判定单** | 复核方按四态术语（成立 / 削弱 / 证伪 / 待定）出具的判定；本次材料的最终结论是「**成立**（= 全量判定 **ACCEPT**）」，**判定单原文未随材料给我**（§5.1） |
| **捩点** | 本文指「一条判定链上的临界分支点」——F2 的捩点即「`node_id` 是否非空字符串」，四态出口在此分岔（§1.2） |
| **红项** | 守卫里**被判失败的断言条数**（源码里即 `_FAIL` 列表的长度）；`--mutate` 的判据是「红项数**恰好**等于该变异预设的预期值」，不符即记 FAIL（§4.2/§4.3） |
| **留池** | 已取证、但本轮**明确决定不修**、留给后续批次的问题面（§6.1 逐条列） |
| **扩面修** | 由另一批（issue50-b）取证上报、本轮**扩大修复面**把它一并修掉——本文的 F1 即「b 批只修了 `sensitivity` 一个成员，本轮把整组 meta 补上」 |
| 〔实跑〕/〔采集〕/〔复核实跑〕 | 三种证据口径，定义见文首「证据口径」行；**〔采集〕与〔复核实跑〕在本文内不可自证**（探针在仓外、我未重跑），保留它们的目的是让读者看到判定链的完整输入 |

---

## 一、缺陷定义与真实站点

### 1.1 F1：同一声明在两条落地路径上元数据不等价

`remember_gated` 的 DEFER 出口（issue50-b 接线）把正文送进审核队列，但**入队时只带 content / layer / sensitivity**。accept 分支只能从队列记录取值（`rec.tags` / `rec.condition_space` / `**extra`），于是调用方在写入时声明的其余 meta 在 DEFER→accept 这条路上整段消失。两者本应等价——它们由**同一份声明**产生、落进**同一张 frontmatter**。

判定「缺陷」而非「设计」的直接证据是**同一条链上的对照**：直接 ACCEPT 路走 `add(**kw)`，声明原样落盘；DEFER 路的入队单点没有带上这组 meta，accept 便无从取值。缺陷的失配点因此在**入队单点**，不在裁决面。

### 1.2 F2：缺 id 时 DEFER 出口以异常崩出

`propose` 造 pid 用 `node_id + str(time.time()) + uuid.uuid4().hex`（`mdcos.py:2063-2064`，本次读码）。`node_id=None` 时该拼接抛 `TypeError`。

**三条腿的真实行为（本次实跑钉死，见 §4.7）**：`remember_gated(None, …)` 在四条出口上的表现**并不同构**——

| 出口 | 是否经 `add(node_id, …)` | 缺 id 时的实测行为 | 代码依据（本次读码） |
|---|---|---|---|
| ACCEPT | **是** | **`ValueError`**：`非法 node_id 类型：None（NoneType）——node_id 必须是字符串…` | `mdcos.py:3709-3712` |
| MERGE | 否（走 `forgetting.reinforce(self, tgt, …)`，**不传 node_id**） | **无异常**，`verdict=MERGE` | `mdcos.py:3723-3734` |
| DROP | 否（`node_id` 只作 `record_drop` 的**记录字段**，不参与拼接） | **无异常**，`verdict=DROP` | `mdcos.py:3743-3747` |
| DEFER | 否（走 `self.propose(_nid, …)`，pid 拼接用 node_id） | **修前 `TypeError` 崩出**；修后兜底（§3.3） | `mdcos.py:3794-3795` + `:2063-2064` |

即缺陷边界是：**只有 DEFER 出口以 `TypeError` 崩出**（新引入面），ACCEPT 出口维持既有 fail-closed 的 `ValueError`，MERGE / DROP 两条路对缺 id **本就无异常**（本轮不动、也不改其行为）。

### 1.3 真实站点（修前 / 当前盘双列）

| 站点 | 修前（issue50-b 落地态） | 当前盘（issue50-c 后） | 说明 |
|---|---|---|---|
| DEFER 分支 | `mdcos.py:3727-3749`（b 报告 §3.1 表） | **`mdcos.py:3748-3797`**（本次读码） | 本轮在此扩为 50 行 |
| **F1 丢失点**（入队单点调用） | **`mdcos.py:3747-3749`** —— `out["proposed"] = self.propose(node_id, content, layer=layer, sensitivity=kw.get("sensitivity"), defer_reason=_why)` 3 行，**未透传 kw** | **`mdcos.py:3794-3795`** —— `out["proposed"] = self.propose(_nid, content, layer=layer, **kw, defer_reason=_why)` | 修前坐标与 b 报告 §3.1 表逐字吻合 |
| **F1 落盘映射点**（accept 分支，本轮零改动） | `mdcos.py:2553`（`tags`）/ `:2560-2562` / `:2573-2574`（`add(... condition_space=item.get("condition_space"), **extra)`） | **同左**（该分支本轮只加注释，逐行未动） | 与 §二 L1 站点列的 `mdcos.py:2546-2569` 是什么关系：那是**采集给的修前坐标下的「accept 分支整体区间」**（含上文注释与 `edit` 分支取值的几行），本列是**当前盘上该区间内的关键三行**；二者是「范围 vs 关键行」、且坐标树不同，故行号不逐行对映 |
| **F2 崩溃点** | `mdcos.py:2063-2064` | 同（本轮零改动） | `pid = "prop_" + _sig(node_id + str(time.time()) + uuid.uuid4().hex)` |
| F2 栈帧中的壳层 | 采集所记 `MdCGSecure.propose` 在 `:4322` | **`mdcos.py:4367`**（本次读码；当前盘 `:4322` 是 `_index_sensitivity` 的 `# 生效条件` 注释行） | 采集坐标为修前树的读数 |
| 兜底形态复用点 | `forgetting.py:879`（`_prefeed_id`） | **`forgetting.py:879-880`**（`def` 在 879、返回式在 880） | `"pre_" + sha1((content or ""))[:12]` |

其他相关当前盘锚点（本次读码）：`class MdCGOS` `:429`、`propose` `:2016`、`review_decide` `:2464`、`remember_gated` `:3602`、`class MdCGSecure` `:4137`。

---

## 二、修前现场（本工作流采集的复现腿，逐条列 payload / 异常 / 崩溃点）

> **口径**：本节两腿全部 `reproduced=true`，为**采集**所得（在**修前树**上跑，隔离临时根 + `MdCGSecure(autoflush=1, designer-cli 本地身份)`），**我未重跑**；站点列的行号是**转引** issue50-b 报告 §1.3 换算表所得的**修前坐标**（不是本报告侧换算，见 §0.1）。

### L1（F1 主腿）同一声明下「直接 ACCEPT」vs「DEFER→经队列 accept」两节点 frontmatter 逐键对拍

- **载荷**：同一声明 `META = tags=["decl-a","decl-b"] / condition_space={"zone":"i50c","axis":"meta"} / verification_basis="test" / non_applicable_conditions=["不适用-i50c-甲"] / derived_from="src" / relation="derived_from"`，外加 `role="user"`、`layer="knowledge"`、`importance_hint=0.6`。
  - 直接 ACCEPT 路：全新内容 doc（标题 + 600 互异汉字 FILL，字符集 0x8000+，与 src 的 0x9e00+ 不重叠）→ `assess` 判 ACCEPT；
  - DEFER 路：先注入基线 doc（BASE=600 互异汉字 0x4e00+），再写半重复 doc（`BASE[:436]+FILL[:164]`，`dup≈0.7310∈[DUP_DROP,DUP_MERGE)`）→ `assess` 判 DEFER → `out["proposed"]=pid` → `review_decide(pid,"accept")`。
  - 命令：`PYTHONUTF8=1 python -X utf8 %TEMP%\i50c_repro\i50c_repro.py`
- **观测（无异常，静默缺陷）**：直接 ACCEPT 路 `verdict=ACCEPT`；DEFER 路 `verdict=DEFER`、`accept.ok=True`。采集所报键数为「两节点 frontmatter 共 **27 键，DIFF 9 键**」。缺陷键（声明元数据在 DEFER 路丢失）：`tags ["decl-a","decl-b"]→[]`；`condition_space {"zone":"i50c","axis":"meta","time_window":[…]}→` 仅剩默认 `{"time_window":[…]} `；`verification_basis "test"→null`；`non_applicable_conditions ["不适用-i50c-甲"]→["无"]`；`derived_from ["src"]→缺键`；`derived_relation "derived_from"→缺键`；`role "user"→缺键`。
  - **「DIFF 9」与上述枚举凑不上，本报告不代它补全**：枚举共 **11** 项 = 缺陷键 7（tags / condition_space / verification_basis / non_applicable_conditions / derived_from / derived_relation / role）+ `importance` 1 + 非缺陷固有差异 3（`id` / `created_at` / `reviewer`）；去掉 importance 亦得 10。采集材料**未附那 9 键的键名清单**，故此处保留「采集所报 9」与其枚举原文，**不推测缺的是哪两键**（要钉死需在修前树上重跑对拍，属改状态动作，本轮未做）。
  - 本报告侧**可自证**的同类读数是 §4.1 的守卫对拍表（见 §4.7 汇总）：两路 fm 并集 **27** 键 = 直接路 **25** 键 + DEFER 路 **27** 键，差异恰为白名单 2 条（`defer_reason` / `reviewer`），白名单外差异 **0**。**两侧载荷不同**（守卫用另一组 `META` 取值与同名节点 id `n`），故「27」与采集的 27 只是数目巧合，**不等于键集相同**。
  - 另 `importance 0.6→0.5`（属「裁决用与落盘记的重要度不同源」口径，**本批另有裁定、不改**；腿 1b 不传 `importance_hint` 时两侧皆 0.5，证明元数据丢失与重要度无关）。
  - 非缺陷固有差异：`id`（两节点本就不同 id）、`created_at`、`reviewer`（accept 路经 `review_decide` 补设）。
- **队列面机制证据**：`rec.tags=[]`、`rec.condition_space={}`、`rec.extra` 键仅 `['defer_reason','sensitivity']`——即入队时只带 content/layer/sensitivity/defer_reason。**`sensitivity` 在 `extra` 里的原因**：它**不在** `propose` 的形参表里（`mdcos.py:2016-2018`），而是 `**kw` 的成员，故随 `"extra": kw`（`:2075`）整包落盘；它与 rec 顶层的同名键（`:2073`）**两层同现**、并不冲突（§3.2 详述）。修后同位置实跑见 §4.7。
- **站点**：丢失点修前 `mdcos.py:3747`（DEFER 分支的 `self.propose(...)` 未透传 kw；转引自 b 报告 §3.1 表）；落盘映射点修前 `mdcos.py:2546-2569`（accept 分支只从队列 rec 取 tags/condition_space/extra 调 `add`，为采集给的**区间**；当前盘对应关键三行见 §1.3 表）。

### L2（F2 捩点）`remember_gated(None, 半重复内容, …)` 的崩点

- **载荷**：隔离临时根 + `MdCGSecure(autoflush=1)`；先 `add` 基线节点 doc（BASE=600 互异汉字）；再调 `cg.remember_gated(None, doc("半重复标题", BASE[:436]+FILL[:164]), layer="knowledge", role="user", gated=True, importance_hint=0.60)`。
- **观测（异常/崩溃点）**：抛 `TypeError: unsupported operand type(s) for +: 'NoneType' and 'str'`。栈内仓内帧：修前 `mdcos.py:3747 in remember_gated`（DEFER 分支调 `self.propose(None, …)`）→ `MdCGSecure.propose` → `mdcos.py:2063 in MdCGOS.propose`（`pid = "prop_" + _sig(node_id + str(time.time()) + uuid.uuid4().hex)`，`node_id=None` 参与 `+` 拼接）。
- **站点**：修前 `mdcos.py:2063`。

---

## 三、修法契约与落点

### 3.1 逐行落点（实跑 `git diff -- md_cg/mdcos.py` 核对；diff 净增 4 个 hunk）

| 行 | 内容 | 类别 |
|---|---|---|
| `:3788-3789` | `_why = "遗忘闸门：" + str(verdict.get("reason") or "待定复核")` / `_dup_with = (verdict.get("redundancy") or {}).get("with")` | 行为代码（issue50-b 遗留，未动） |
| `:3790-3791` | `if _dup_with:` / `_why += "（重复对象 %s）" % _dup_with` | 行为代码（issue50-b 遗留，未动） |
| **`:3792-3793`** | **F2**：`_nid = node_id if isinstance(node_id, str) and node_id else \` / `    forgetting._prefeed_id(content)` | 行为代码（本轮） |
| **`:3794-3795`** | **F1**：`out["proposed"] = self.propose(_nid, content, layer=layer, **kw, defer_reason=_why)` | 行为代码（本轮） |
| **`:3796-3797`** | **F2 非静默**：`if _nid != node_id:` / `    out["proposed_id_fallback"] = _nid` | 行为代码（本轮） |
| `:3601` | `# 生效条件：…` 的 DEFER 段改为「不落盘、经既有入队单点 `self.propose` 把**正文 + 声明 meta（`**kw`）+「为何待定」**送进审核队列（返回体带 `proposed=pid`；node_id 非字符串时兜底成内容派生 id 并写 `proposed_id_fallback`）」 | 注释（diff hunk `@@ -3593,7 +3598,7 @@`，净 0 行） |
| `:3613-3639` | docstring 新增段：issue50-b 段 `:3613-3620`、**issue50-c F1 段 `:3622-3630`**、**F2 段 `:3632-3634`**、接线边界段 `:3636-3639`（diff hunk `@@ -3605,6 +3610,34 @@`，净 +28 行；采集所记「3622-3637」以本次读码为准） | 注释 |
| `:3748-3787` | DEFER 分支前半：issue50-b 段 + **issue50-c F1 段（`:3765-3776`）+ F2 段（`:3778-3787`）** 的说明性注释（diff hunk `@@ -3712,6 +3745,56 @@`，净 +50 行） | 注释 |
| `:2547-2551` | review_decide accept 分支的 **F1 对口注释**（diff hunk `@@ -2544,6 +2544,11 @@`，净 +5 行） | 注释（**零行为改动**） |

「净增 hunk」的读数说明：四个 hunk 中只有 `:3792-3797` 这 6 行是行为代码，其余净增行**全部是注释/docstring**。

### 3.2 F1 契约：meta 随入队落进队列记录，**桶路由与直接 ACCEPT 同源**

- 入队改走 `self.propose(_nid, content, layer=layer, **kw, defer_reason=_why)`。
- `propose` 的形参决定桶（`mdcos.py:2016-2018` 本次读码）：`tags` / `condition_space` / `verify` 落 **rec 专属槽**（rec 构造 `:2066-2068`：`"tags": list(tags or [])`、`"condition_space": condition_space or {}`），**其余键落 `extra`**（`:2075` `"extra": kw`）。
- **`sensitivity` 是特例（两层同现，不是冲突）**：它**不在** `propose` 的形参表里，所以既随 `kw` 整包落进 `extra`，又由 `:2073` 单独抄一份到 rec 顶层（N201：读侧可见性过滤免挖 extra）。实跑读数（§4.7）：`rec["sensitivity"]='internal'` 且 `rec["extra"]["sensitivity"]='internal'`。§二 L1 记的「修前 `extra` 仅 `['defer_reason','sensitivity']`」与本节并不矛盾——修前的 `extra` 之所以只有这两键，是因为**调用方**当时只传了这两个 kw；修后调用方传全了 meta，`extra` 即扩为 8 键（§4.7），而 **`propose` 自身一行未动**（§3.6），差异全部来自「调用方传了什么」。
- accept 分支**早已**把这三槽映射回 `add`（`:2553` `tags = list(item.get("tags") or [])`、`:2573-2574` `nid = self.add(item["id"], content, layer=layer, tags=tags, condition_space=item.get("condition_space"), **extra)`）——**故 `review_decide` 不需改一行**（本轮的 diff 在该分支只加了注释）。
- 语义即「与直接 ACCEPT 走 `add(**kw)` 的口径同源」：同一声明的两条落地路径由同一组键驱动落盘。**不新增队列字段、不新增队列类型、不新增第二套入队实现。**

### 3.3 F2 契约：缺 id 兜底 + 非静默

- `_nid` 只对 `node_id` 非字符串/空值时兜底，形态**复用仓内既有单点** `forgetting._prefeed_id`（`forgetting.py:879-880`：`"pre_" + sha1((content or ""))[:12]`）——不是新造 id 形态。
- 兜底事实写进返回体 `out["proposed_id_fallback"]`（**非静默**——调用方可判、可检索）；**不写入 forgetting 留痕行**（该行形状由 issue50-b 冻结）。
- 返回体 `node_id` 不强改（C3 断言：`node_id` 原样为 `None`，不伪装成派生 id）。

### 3.4 覆盖面边界（哪些 DEFER **不**走本分支）

| 情形 | 是否入队 | 依据 |
|---|---|---|
| 遗忘闸门自身 DEFER | **入队（且带 meta）** | `mdcos.py:3748-3797` |
| 限流（ratelimit）DEFER | 否 | 已在 DEFER 分支之前 `return`——语义是「先别写」，原文在 recent 时间线，不是内容待定 |
| `gated=False` 旁路 | 否 | 直接 ACCEPT 写盘并返回 `bypass` |
| ACCEPT 后 `on_conflict=defer` 降级 DEFER | 否 | 该 `v` 在 `if v == "ACCEPT"` 内就地改写，不进 DEFER 分支 |

### 3.5 测试面落点与**一处实施清单路径更正**〔实跑 `git diff` + 读码〕

- **新建守卫** `md_cg/test_i50c_meta_passthrough.py`（592 行；A/B/C/D 四组 30 断言 + 11 处定点变异 + 锚点 fail-closed）。本次读码结构锚点：`_WHITELIST` `:202`、`_NAMED` `:210`、`_EXTRA_KEYS` `:218`、`g_a` `:222`、`g_b` `:254`、`g_c` `:295`、`_MUTATIONS` `:416`、`_ANCHORS_REQUIRED` `:497`、`_anchor_check` `:512`、`_mutate` `:526`、`_with_patched` `:534`、`_mutate_mode` `:543`。
- **同步既有守卫锚点**：`md_cg/test_i50b_defer_to_review_queue.py` 的变异锚点与文案随实现同步（`:21-24` docstring、`:368-371` `_PROPOSE_BLOCK`、`:389` `_MUTATIONS` 内一条、`:438-440` `_ANCHORS_REQUIRED`）——**红项数 20/5/3/1/5/1/1 逐处不变**（§4.4 我实跑核对 rc=0）。
- **更正（实施清单所载路径与实际不符）**：实施清单把上述锚点同步记为 `md_cg/test_writelimit.py:21-24/368-371/389/438-440`。**本次读码核对：该文件全文仅 217 行**（`:21-24` 是 `import` 区），不含 `:368-371/389/438-440`；这些行号实际落在 **`md_cg/test_i50b_defer_to_review_queue.py`**（逐行内容见上）。以本次读码为准。
- **`md_cg/test_writelimit.py` 的「当前树相对 HEAD 的 diff」**（措辞澄清：a/b/c 三批**均未提交**，故该 diff **≠「本轮改动」**；且**我没有改过这个文件**——它出现在本文，是因为它与本批同处一个未提交工作树）：① E 节判据按标题意图重编码（E1 改判「限流器未介入」= 两条写入 gate 均无 `limiter` 键；新增 E2 钉住「knowledge 半重复交遗忘闸门判 DEFER，`dup=0.7778`」），注释标注 **issue50-b**；② **H 节夹具改法**（`MDCG_WRITELIMIT=0` 绕限流 → `gated=False` 直写，「H 节四条断言一字未动」），注释同样标注 issue50-b。**批归属未定论**：实施清单未把 H 节夹具列为本轮改动，而 issue50-b 报告 §4.3/§6.2 记载 b 时点 H 节仍红且「H 节未获授权」；本轮**未做归因实验**，故只报读数与 diff 原文，不裁定其属哪一批（→ §7 Q4）。
- **守卫白名单（B 组逐键读数的允许差异，恰 4 条）**：`defer_reason`（issue50-b 引入的「为何待定」文案，仅 DEFER 路有）、`reviewer`（accept 路径的裁决归属留痕，硬边界不许削弱）、`created_at`（两次落盘时刻不同，非调用方声明的 meta）、`condition_space`（**仅其派生键 `time_window`** 随之变，其余键必须逐位相等）。

### 3.6 未动的面（按文件点明属主）

- **`forgetting.py`**：`assess` 的判据/常量/分支次序——其工作树改动**属 issue50-a 批**（§6.1），本轮未触碰。
- **`mdcos.py`**：`propose`（`:2016`）与 `review_decide`（`:2464`）——**本轮零行为改动**（`review_decide` 只加注释 `:2547-2551`；`propose` 一行未动，两路差异全在调用方传了什么）。
- **其余**：`writelimit.py`、`writepipe` 的 audit 入队路径、`review_cli`。

---

## 四、验证数字

### 4.1 守卫〔实跑〕

```
python -X utf8 -m md_cg.test_i50c_meta_passthrough
→ 锚点自检：PASS（test_i50c_meta_passthrough.py；不以 git HEAD 为基线源）
→ A0/A0b/A0c + A1×6 + A3×2（A 组 11）/ B1..B5（B 组 5）/ C1..C7（C 组 7）/ D1..D7（D 组 7）
→ issue50-c 守卫：30 通过，0 失败        rc=0
```

- **断言数 30 / 通过 30 / 失败 0 / rc=0**（我本次执行，逐行读到）。构成：A 修复面 11 + B 白名单 5 + C None 捩点 7 + D 裁决既有职责 7。
- A 组关键读数：六键（`tags` / `condition_space`（除派生 `time_window`）/ `verification_basis` / `non_applicable_conditions` / `derived_from` / `relation`→`fm.derived_relation`）**在位且逐位相等**，另有 `role` / `bucket_zh` 佐证键相等（A3）——**同时防「两路都缺」的假等价**。**`bucket_zh` 的时点须分清**：修前它在 DEFER 路**不生成**（§0.3 那行说的是修前），修后两路**均生成且逐字相等**（A3 说的是修后）——本次实跑的两个时点读数见 §4.7。
- B 组逐行对拍表（两路 fm 键的**并集 = 27 键**：直接路 25 键 + DEFER 路 27 键，差集即白名单 2 条 `defer_reason` / `reviewer`）：白名单外的 fm 差异为 **0**；`only-in-DIRECT` 为空；`condition_space` 差异仅限派生 `time_window`，且该差异经 B4 证明真实存在（非被掩盖）。
- C 组：`node_id=None` 不抛异常（改前为 `TypeError`）、判 DEFER、返回体 `node_id` 原样 `None`、队列条目 id == `forgetting._prefeed_id(content)` 且以 `pre_` 开头、返回体 `proposed` == 队列 pid、`proposed_id_fallback` 有值、accept 后落盘节点正文逐字相等。
- D 组：幂等对账（同 pid 再裁 `already_decided`）、自验违例检测（`verify_readonly`）、reject/noop 不落盘、merge 不适用条件并集、裁决留痕仍在。

### 4.2 定点变异〔实跑〕

```
python -X utf8 -m md_cg.test_i50c_meta_passthrough --mutate   → rc=0
  未变异基线：红项=0
  ① DEFER 出口不透传 meta（退回只传 sensitivity）      → 红项 11  命中预期
  ② 只丢 condition_space（连带桶路由变化）            → 红项  5  命中预期
  ③ 只丢 derived_from（连同其派生 derived_relation）  → 红项  4  命中预期
  ④ 去掉 node_id=None 兜底（退回 TypeError）          → 红项  6  命中预期
  ⑤ None 兜底但静默（不写 proposed_id_fallback）      → 红项  1  命中预期
  ⑥ accept 不再映射 tags（削弱既有映射）              → 红项  3  命中预期
  ⑦ accept 不再映射 condition_space（削弱既有映射）   → 红项  5  命中预期
  ⑧ 去掉幂等对账 already_decided（既有职责）          → 红项  1  命中预期
  ⑨ 去掉自验违例检测 verify_readonly（既有职责）      → 红项  2  命中预期
  ⑩ noop 不再短路（落到 merge 分支）                  → 红项  1  命中预期
  ⑪ merge 不再并集不适用条件（既有职责）              → 红项  1  命中预期
  定点变异自证：PASS（每处判据都有变异钉死，且红项数逐处吻合）
```

- **红项数序列 = 11 / 5 / 4 / 6 / 1 / 3 / 5 / 1 / 2 / 1 / 1**（我本次执行，逐行读到；与采集所列逐处相同）。
- **基线源口径**：变异一律作用在**当前盘实现**的 `getsource` 副本上（`_mutate` 在内存 exec，不落盘、不改源文件），**不以 git HEAD 为基线源**。另有 7 处既有判据锚点与 5 条必需锚点全在位（`_ANCHORS_REQUIRED`，ANCHOR 自检 PASS）。

### 4.3 删断言探针与 fail-closed 探针〔实跑·本会话新增，只改内存〕

自写探针 `%TEMP%\i50c_probe_selfcheck.py`（只改内存 `_GROUPS` / `_MUTATIONS`，**未改任何仓库文件**）：

```
基线 _run_groups 红项 = 0
变异① 未删组：红项=11（预期 11）
删 g_a 后：变异① 红项=3  实际红项=['B1 白名单外的 fm 差异为 0（逐行读数）',
                                  'B2 DEFER 路不缺任何 fm 键（无 only-in-DIRECT）',
                                  'B3 condition_space 的差异**仅限**派生的 time_window']
删 g_a 后：基线 _run_groups 红项 = 0
删 g_c 后：变异④（去 None 兜底）红项 = 0
删 g_c 后：变异⑤（兜底但静默）红项 = 0
注入假锚点：_anchor_check 缺失条数 = 1   （ANCHOR-MISS 变异锚点缺失：假锚点探针）
注入假锚点：_mutate_mode() rc = 2        （锚点自检：FAIL（fail-closed，exit 2））
```

补跑「删 `g_c` 后整跑变异模式」：

```
删 g_c → 变异④ 红项=0  **红项数不符（预期 6）**
          变异⑤ 红项=0  **红项数不符（预期 1）**
          定点变异自证：FAIL
DEL_G_C_RC= 1
```

- **删 `g_a`（A 修复面）⇒ 变异①的 11 个红项掉到 3 个，剩下的恰是 B1/B2/B3**——与采集所记逐字一致，证明「删掉一组断言后自证会红」。
- **删 `g_c`（C None 捩点）⇒ ④/⑤ 的实测红项数为 0 ≠ 预期 6/1**，`_mutate_mode()` 据此判 FAIL 并返回 **rc=1**（采集用「落红」表述同一事实：该两处变异被记为不符）。
- **锚点漂移 fail-closed**：注入假锚点 ⇒ `_anchor_check()` 返回 1 条缺失说明、`_mutate_mode()` 返回 **2**，不执行任何变异。

### 4.4 定向套件〔实跑〕

| 命令 | 读数 | rc |
|---|---|---|
| `-m md_cg.test_i50a_half_dup_defer` | 26 通过 / 0 失败 | 0 |
| `-m md_cg.test_i50b_defer_to_review_queue` | 34 通过 / 0 失败 | 0 |
| `-m md_cg.test_i50b_defer_to_review_queue --mutate` | 7 处变异红项 20/5/3/1/5/1/1 逐处命中，定点变异自证 PASS | 0 |
| `-m md_cg.test_i50c_meta_passthrough` | 30 通过 / 0 失败 | 0 |
| `-m md_cg.test_i50c_meta_passthrough --mutate` | 见 §4.2，11 处逐处命中 | 0 |
| `-m md_cg.test_writelimit` | `All writelimit tests passed.` | 0 |
| `-m md_cg.test_p9_forget_protect` | 37 通过 / 0 失败 | 0 |
| `-m md_cg.test_p9c_dedup_hints` | 31 通过 / 0 失败 | 0 |
| `-m md_cg.test_p2_mcp` | 64 通过 / 0 失败 | 0 |
| `-m md_cg.test_issue39_utf8_stdio` | `20 passed, 0 failed, 0 skipped (live=13)` | 0 |
| `-m scripts.test_utf8_boot_guard` | `SUMMARY 30/30 通过（正向 13/13 + 定点变异 17/17）` | 0 |

（上表数字均为我本次执行、逐行读到；与采集所列 targetedSuite 读数逐项吻合。）

### 4.5 python 全量〔实跑〕

```
python -X utf8 scripts/run_tests.py        （仓根，无参数，工作目录 <仓根>）
第 1 次：===== SUMMARY 302/302 通过，5 跳过（依赖缺失/平台不符） =====   用时 221.6 s ；rc=0
第 2 次：===== SUMMARY 302/302 通过，5 跳过（依赖缺失/平台不符） =====   用时 223.6 s ；rc=0
```

- **同一命令连跑两次，读数逐字相同（302/302、rc=0）**——不是一次侥幸；这是「302/302 凭什么采信」的直接依据（我全程单进程串行跑该脚本，没有并行争抢，见下条）。
- **与采集值不一致，如实列出**：采集记为「`300/302` 通过、5 跳过、**失败 `md_cg.test_issue39_utf8_stdio` 与 `scripts.test_utf8_boot_guard`**、rc=1」。我的读数分母同为 302、失败面为 **0**；这两项在我两次全量里均 `PASS`（`md_cg.test_issue39_utf8_stdio` 为第 59 行、`scripts.test_utf8_boot_guard` 为第 306 行），单跑亦全绿（§4.4）。
- **未归因（仍如实声明）**：本轮**未做归因实验**，即**未**把采集那次的两项失败复现出来（要复现得回到采集时的并发环境，本轮无此条件）。仓内 `scripts/run_tests.py` 自述有「负载敏感（性能阈值断言），并行争抢会假红——仅串行执行」的跳过项，采集时段本工作流可能同时在跑容器栈；此为**推测，未验证**，不作因果断言。此项是采集与实跑之间**唯一**的分歧点。
- 5 个跳过项（我这两次读到的完整名单与原因）：`md_cg.test_md_access_parity`、`md_cg.test_p44_md_whitebox`（白箱库 `whitebox_kb/wisdom/wisdom-book-cloud.db` 未生成）；`md_cg.test_wisdom_md_store`（md 语料真源 `_md_cg_wisdom_graph/` 未生成）；`swarm.tests.bench_swarm_parallel`、`swarm.tests.bench_swarm_scale`（负载敏感，仅串行执行）。

### 4.6 容器两栈退出码〔采集，**我未运行**〕

| 栈 | 形态 | 读数（采集） | 退出码 |
|---|---|---|---|
| 栈一 | `docker … scripts/linux_verify.sh`（linux 侧 rust + python 十套） | `结果: 22 pass / 0 fail`；`[PASS] smoke_test (linux)`；`=== 汇总: 38 pass / 0 fail ===` | **0** |
| 栈二 | Node TAP（`npm test`） | `# cancelled 0` / `# skipped 3` / `# todo 0` / `# duration_ms 11503.1857` | **0** |

本机 `docker` 可执行在 PATH（`<Program Files>\Docker\Docker\resources\bin\docker.EXE`，本次实跑 `shutil.which` 读到），**本轮未执行任何容器**，故两栈读数一律为〔采集〕转述，我未复跑。

### 4.7 读者反馈取证〔实跑·本会话新增，隔离临时根，不改仓库文件〕

针对读者提出的三处存疑，本会话新写一个探针（`%TEMP%\i50c_feedback_probe.py`，复用守卫的夹具常量）真跑，读数如下。

**（一）`remember_gated(None, …)` 在四条出口上的真实行为**——**不是三条腿同构**：

```
  ACCEPT  exc=ValueError     verdict=None    exc msg: 非法 node_id 类型：None（NoneType）——node_id 必须是字符串：…
  MERGE   exc=None           verdict=MERGE
  DROP    exc=None           verdict=DROP
```

- 只有 **ACCEPT** 腿经 `add(node_id, …)`（`mdcos.py:3709-3712`）⇒ 抛 `ValueError`（既有 fail-closed）；
- **MERGE** 腿走 `forgetting.reinforce(self, tgt, …)`（`:3731-3734`），**根本不传 node_id** ⇒ 无异常；
- **DROP** 腿把 node_id 只当 `record_drop` 的**记录字段**（`:3744-3747`）⇒ 无异常；
- **DEFER** 腿是唯一在 pid 拼接处用 node_id 的出口 ⇒ 修前 `TypeError`（§二 L2）。

**（二）`bucket_zh` 的三条路三时点**（复用同一份 `META`、同名节点 id）：

```
  直接 ACCEPT      : keys=25  bucket_zh=['标签甲','标签乙','功能名','新写入标题','生效条件','任意情境']  tags=['标签甲','标签乙']
  修后 DEFER→accept: keys=27  bucket_zh=[同上，逐字相同]                                              tags=['标签甲','标签乙']
  模拟修前 DEFER   : keys=23  bucket_zh=None（缺键）                                                   tags=[]
```

- 「修前不生成」与「修后两路相等」**都成立**——它们是**两个时点**：§0.3 那行说的是修前，§4.1 A3 说的是修后；
- 「模拟修前」= 直接调 `cg.propose(NID, content, layer="knowledge", sensitivity="internal", defer_reason=…)` 再 `review_decide(accept)`，即复刻 issue50-b 落地态的入队载荷。

**（三）三个「键数」各是什么**（27 并集 / 27 采集 / 26 oracle）：

| 数字 | 是谁 | 口径 |
|---|---|---|
| **27** | 本次守卫 B 组的对拍表行数 | **并集** `sorted(set(fm_direct) \| set(fm_defer))` = 直接路 **25** + DEFER 路 **27**；差集 = 白名单 2 条（`defer_reason` / `reviewer`） |
| **27** | §二 L1 采集所报「两节点共 27 键」 | **采集腿自己的载荷**（另一组 `META` 取值、另一套 id）；**与上一行只是数目巧合，键集不保证相同** |
| **26** | §5.1 复核「独立 oracle」 | **oracle 自己那组载荷**（其键名清单未随材料给我） |

**（四）`sensitivity` 的两层**（回应「两处说法冲突」）：

```
  rec 顶层键  : [..., 'sensitivity', ...]        rec['sensitivity'] = 'internal'
  rec.extra 键: ['defer_reason','derived_from','importance','non_applicable_conditions','relation','role','sensitivity','verification_basis']
                                                 rec['extra']['sensitivity'] = 'internal'
  rec.tags = ['标签甲','标签乙']   rec.condition_space = {'observation_position': 'pos-x'}
```

两层同现是**设计如此**（§3.2）：`sensitivity` 不在 `propose` 形参表里，故随 `extra` 整包落盘，又由 `:2073` 另抄一份到 rec 顶层；**两处说法都对**。

---

## 五、独立复核判定与它列出的 uncovered

### 5.1 判定：**ACCEPT**（转述）

- 依据为四态判定单：issue50-c（F1 DEFER 出口 meta 透传 + F2 `node_id=None` 兜底）判定 = **【成立 / ACCEPT】**。「四态判定单」即复核方用**四态术语（成立 / 削弱 / 证伪 / 待定）**给出的一份判定；本次材料只把最终结论（**成立（= ACCEPT）**）与依据交给我，**判定单原文未随材料给我**。
- 复核范围与独立性：全部实验在 `%TEMP%/i50c_review` 与 `%TEMP%/i50c_*` 合成库跑，结束已清理（原文记「113→0，二次测量 12→0」——**采集材料未说明这两个数数的是什么**（临时文件？目录？合成库条目？），本报告不代它解释，只照录；可确定的是：其所述「工作区文件零改动」我本次复核确认——`git status` 与起始逐字相同；未 `git add`/`commit`/`push`、未用 `stash`）。
- 复核的三组实验（均〔复核实跑〕，我未重跑）：**① 修前崩溃腿现行不再崩 + 退化路径真发生**（现行 `probe.py <仓根> none` → 无异常、`verdict=DEFER`、`proposed_id_fallback=pre_d29863d9537d` 且 == 独立调用 `forgetting._prefeed_id(content)`、独立解析 `inbox.jsonl` 得 `queue_n=1`、accept 后落盘节点「**独立文件系统扫描出的正文与输入逐字相等**」（`content_match_fs=true`）、每次 `fs_node_ids == index_node_ids`）；**② 合法输入与改动前逐位对照**（ACCEPT 腿 HEAD vs 现行 11 项状态键全同、fm「去时间量逐位相等」；DEFER 腿 pre-c vs 现行，差异**恰为 F1 承诺补回的键**；（另用**独立 oracle** 自算 fm diff：**该 oracle 自己那组载荷是 26 键**，差异仅 `['defer_reason','reviewer']`，与守卫白名单一致；**26 ≠ 本报告守卫的并集 27**，因两者载荷不同——详见 §4.7 的「三个键数」对照）；**③ 删断言探针 / 非静默可观测面**（删组探针、fail-closed 探针、经 `mcp_server.call_tool` 读 DEFER 出口）。
- 与我的独立读数交叉：复核【③】的**删断言探针与 fail-closed 探针两项，我在 §4.3 用自己的探针独立复现**（删 `g_a` → 变异①红项 11→3 且红项 = B1/B2/B3，逐字一致；假锚点 → `_anchor_check()` 1 条 + rc=2，一致）；复核【③】所述「删 `g_c` → EXIT=1」，我在 §4.3 复到同一退出码（`_mutate_mode()` rc=1，④⑤ 红项数不符）。

### 5.2 复核的未覆盖面（标题承诺的「复核所列清单」原文**未随材料给我**）

**先把来源说清**：本次 ask 交给我的复核材料**只给了判定（ACCEPT）与其依据，未附独立的 uncovered 清单原文**，所以本节**不**是「复核编号的清单」，而是**本报告从材料明文读数中提取**的未覆盖面——每条都标了它出自哪里、是复核探针的读数还是别的材料的原文：

- **第 1、3 条**：取自复核探针的明文读数（`probe_none_legs.py` 的分腿结论、ask 材料 F1 腿 1b）；
- **第 2 条**：取自复核探针 `probe_mcp.py` 的明文读数；
- **第 4 条**：取自 **issue50-b 报告** §5.2/§6.2-3（不是本次复核材料）。

即：**这 4 条不是「复核列出的清单」，而是「材料里能读到的未覆盖面」**；复核是否另有未列出的项，本报告无从得知（→ §7 Q5）。

1. **`node_id=None` 只在 DEFER 腿收口**（出处：复核 `probe_none_legs.py`；我已用自写探针**独立复现同一结论**，§4.7）：None-id 在 **ACCEPT 腿仍 `ValueError`**（既有 fail-closed，未动）、**MERGE 腿无异常**、**DROP 腿无异常**、**只有 DEFER 腿曾 `TypeError`**——本轮只收口了唯一崩出的那条腿，ACCEPT 腿的 fail-closed 行为**保持原样**。
2. **生产入口的兜底使该面不可达**（出处：复核 `probe_mcp.py`）：`node_id=""` 经 MCP 出口被 `mint_auto_id` 兜成 `mem_…`（`fallback` 键为 `None`）——即生产入口本就不会把空 id 送到本闸；F2 属**防守性收口**，不是生产路径上的活缺陷。**CLI / 插件入路是否也都经 `mint_auto_id` 兜底，未逐条排查。**
3. **「裁决用与落盘记的重要度不同源」不在本批**（出处：ask 材料 F1 腿 1b）：`importance 0.6→0.5` 的差异属**另有裁定**的口径问题，本批**不修**；腿 1b 已证「不传 `importance_hint` 时两侧皆 0.5」，即元数据丢失与重要度无关。
4. **`defer_reason` 落在 accept 后节点 frontmatter**（出处：issue50-b 报告 §5.2/§6.2-3，本轮未动）：它是 issue50-b 已取证并如实上报的取舍，本轮沿用，未改。

---

## 六、边界与未覆盖

### 6.1 本轮明确不修、留池的面

1. **重要度不同源**（§5.2-3）：`importance_hint` 在两条路径上的取值口径不一致，属**另有裁定**的问题，本轮不动、也不靠本批守卫混淆（守卫改用显式 `importance=` 使两侧同源，见守卫 docstring `:37-39`）。
2. **其余出口的缺 id 行为**（实测见 §4.7）：**ACCEPT 腿维持既有 fail-closed `ValueError`**（未改成兜底）；**MERGE / DROP 两腿本就无异常**（它们不经 `add`），本轮不动。本批只把 DEFER 腿的「抛 `TypeError` 崩出」改成「兜底 + 标注」，**不统一三条腿的行为**——是否统一属使用者裁定（→ §7 Q1）。
3. **`defer_reason` 落 accept 后 frontmatter**（§5.2-4）：沿用 issue50-b 的取舍。
4. **`forgetting.py` 未改**：其工作树改动属 **issue50-a** 批（分支④删去 `and imp["score"] < IMPORTANCE_MIN`，我实跑 `git diff` 核对：改动仅在分支④判据、文案、`# 生效条件` 行与 docstring 的 issue50-a 段），本轮未触碰。
5. **`test_writelimit.py` H 节四条断言一字未动**：该文件的当前树 diff 只改 E 节判据与 H 节夹具造法，未改任何 H 节断言。
6. **`test_writelimit.py` H 节夹具改动的批归属未定论**（§3.5）——只报读数，不裁定。

### 6.2 未跑 / 未验（如实声明）

- **容器两栈**（§4.6）：〔采集〕所得，**我未运行**（本机 docker 可执行在 PATH，本轮未起容器）。
- **修前现场两腿**（§二）：〔采集〕所得，**我未重跑**（复现需把 `mdcos.py` 退回 issue50-c 之前，属改状态动作，本轮未做）。
- **复核的三组实验**（§5.1）：〔复核实跑〕，**我未重跑**；其中「删断言探针」「fail-closed 探针」两项我用**自写内存探针独立复现**（§4.3），其余未重跑。
- **CLI / 插件（DSH 等）入路**是否都经 `mint_auto_id` 兜底：**未逐条排查**。
- **python 全量读数与采集值的分歧**（§4.5）：**未归因**。
- 我本次实跑的是：守卫默认模式与 `--mutate`、i50a/i50b 守卫（含 `--mutate`）、`test_writelimit`、`test_p9_forget_protect`、`test_p9c_dedup_hints`、`test_p2_mcp`、`test_issue39_utf8_stdio`、`scripts.test_utf8_boot_guard`、`scripts/run_tests.py`（**两次**）、自写内存探针（删组 / 假锚点 / 删组后整跑变异）、**本会话新增的取证探针**（None-id 三腿 / `bucket_zh` 三条路 / rec 键层，见 §4.7），以及若干读码、`git diff`、`git status`、`shutil.which`。

### 6.3 硬边界

- 全部实验根在系统临时目录（`tempfile.mkdtemp`）且各自清理；**未触碰在役数据根**；
- **未 `git add` / `commit` / `push`**；本次只写入本报告一个文件；
- 本轮 `git status --porcelain` 与工作流起始逐字相同（`M md_cg/forgetting.py`、`M md_cg/mdcos.py`、`M md_cg/test_writelimit.py` + 3 个未跟踪守卫 + 2 份既有报告 + `.zcode/`）；
- 报告不含明文凭据。

---

## 七、读者问答（逐条回应，含「本报告答不了、须使用者裁定」的项）

| # | 读者问 | 本条处置 |
|---|---|---|
| Q1 | MERGE / DROP 对非字符串 node_id 的真实行为？是否要统一？ | **已答**（§1.2 表 + §4.7 一）：ACCEPT = `ValueError`；**MERGE / DROP 无异常**（二者不经 `add`）。是否把三条腿统一成「兜底 + 标注」**超出本批范围**，属使用者裁定（§6.1-2） |
| Q2 | `bucket_zh` 在 DEFER→accept 路到底生不生成？F1 是否有残留？ | **已答**（§4.7 二）：修前**不生成**；修后**两路均生成且逐字相等**。F1 承诺的「两条路径元数据等价」在该键上**已达成**，无残留 |
| Q3 | 302/302 凭什么采信？要不要串行重跑钉死？ | **已补跑**（§4.5）：同一命令**连跑两次**读数逐字相同（302/302、rc=0）。仍**未**做的是「复现采集那次的两项失败并归因」 |
| Q4 | `test_writelimit.py` 的 E 节 / H 节改动归哪一批？会否与本批一起提交？ | **本报告答不了**：三批均未提交、无中间提交点，无法从 git 判定；注释标注 issue50-b，但 b 报告 §4.3/§6.2 的记载与之不符（§3.5）。提交策略属使用者裁定 |
| Q5 | 复核的 uncovered 清单原文在哪？§5.2 那 4 条是不是全部？ | **本报告答不了**：材料**未附**清单原文（§5.2 首段已声明那 4 条的来源构成）；是否另有未列项，须**向复核方索取原文** |
| Q6 | F2 既然生产入口不可达，为何仍按缺陷落修？风险与优先级？ | **理由（本报告判定）**：① 它是 issue50-b 接线**新引入**的面（非既有行为）；② 缺 id 时 DEFER 出口崩出会**连带丢掉唯一的落点证据**（队列条目 + `proposed` 句柄），即「待定复核」整链在缺 id 时失效；③ 与 F1 同处一个出口、同批成本极低。**风险**：低（改的是新引入路径；返回体**新增**键、不改既有键）。**优先级**：中低（生产入口经 `mint_auto_id` 兜底，不可达） |
| Q7 | 27 / 26 / DIFF 9 三个数字以哪个为准？差的那一键是什么？ | **已答**（§4.7 三 + §二 L1）：27 = 守卫**并集**（直接 25 + DEFER 27）；27 = 采集腿自己的载荷（数目巧合、键集不保证同）；26 = 复核 oracle 自己那组。**「DIFF 9」与采集枚举凑不上（枚举 11 项），采集未附键名清单，本报告不推测缺哪两键** |
| Q8 | 「另有裁定」的重要度不同源，裁定内容与落地时点？ | **本报告答不了**：ask 材料未给裁定内容与时点。可确定的只有：本批不修；守卫改用显式 `importance=` 使两侧同源（守卫 docstring `:37-39`） |
| Q9 | 这些改动何时提交？回归是否只在未提交状态下成立？ | **提交时点属使用者裁定**（§6.3：本轮未 add/commit/push）。**回归的成立条件**：我实跑的守卫与全量跑的都是**当前工作树（未提交态）**；若提交内容与该工作树逐字相同，读数可沿用；**本轮无法预先保证**，提交后如有任何改动须重跑 |

---

## 附：本次实跑命令清单（含 argv，可复现）

```bash
# 守卫：默认 / 定点变异
python -X utf8 -m md_cg.test_i50c_meta_passthrough            # 30 通过 / 0 失败；rc=0
python -X utf8 -m md_cg.test_i50c_meta_passthrough --mutate   # 基线红 0；11 处 11/5/4/6/1/3/5/1/2/1/1；rc=0

# 定向套件
python -X utf8 -m md_cg.test_i50a_half_dup_defer              # 26/0；rc=0
python -X utf8 -m md_cg.test_i50b_defer_to_review_queue       # 34/0；rc=0
python -X utf8 -m md_cg.test_i50b_defer_to_review_queue --mutate  # 7 处 20/5/3/1/5/1/1；rc=0
python -X utf8 -m md_cg.test_writelimit                       # All writelimit tests passed.；rc=0
python -X utf8 -m md_cg.test_p9_forget_protect                # 37/0；rc=0
python -X utf8 -m md_cg.test_p9c_dedup_hints                  # 31/0；rc=0
python -X utf8 -m md_cg.test_p2_mcp                           # 64/0；rc=0
python -X utf8 -m md_cg.test_issue39_utf8_stdio               # 20 passed / 0 failed；rc=0
python -X utf8 -m scripts.test_utf8_boot_guard                # SUMMARY 30/30；rc=0

# 全量（工作目录 = 仓根；连跑两次）
python -X utf8 scripts/run_tests.py                           # SUMMARY 302/302 通过，5 跳过；rc=0；221.6 s / 223.6 s

# 内存探针（仓外一次性文件，跑完即弃；只改内存，不改仓库文件）
python -X utf8 %TEMP%\i50c_probe_selfcheck.py                 # 删 g_a / 删 g_c / 假锚点 三组读数
python -X utf8 -c "<删 g_c 后整跑 G._mutate_mode()>"            # DEL_G_C_RC=1

# 读者反馈取证探针（§4.7；仓外一次性文件，隔离临时根，只读）
python -X utf8 %TEMP%\i50c_feedback_probe.py                  # None-id 三腿 / bucket_zh 三条路 / rec 键层
```

> 采集与复核阶段的命令口径见 `docs/eval/issue50_待定复核入队_修复记录_v1.0.md`（issue50-b）与 `docs/eval/issue50_半重复待定复核_修复记录_v1.0.md`（issue50-a）。
