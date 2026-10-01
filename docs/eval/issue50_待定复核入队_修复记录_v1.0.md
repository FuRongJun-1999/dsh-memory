# issue50-b · 遗忘闸门 DEFER 待定复核入队——修复记录 v1.0

> **日期**：2026-10-01 ｜ **缺陷号**：issue50-b ｜ **被测面**：`D:\program\dsh-memory-main` 工作树（未提交）
> **关联**：issue50-a（forgetting 分支④「半重复→DEFER」结构性不可达）→ `docs/eval/issue50_半重复待定复核_修复记录_v1.0.md`；
> 设计依据 → `docs/plans/记忆自处理三档自治_设计_v0.2.md`（§八.2 在 `:145-152`，落码顺序在 `:184`）
> **证据口径**：〔实跑〕= 我（报告撰写员）在本会话亲自执行并读到输出；〔采集〕= 本工作流复现阶段所得；〔复核实跑〕= 本工作流**独立复核阶段**所得，我未重跑（其探针在仓外临时目录）。

---

## 零、口径（先读这一节，正文所有行号与状态词都按它换算）

### 0.1 三个「改前」不是同一棵树

| 名称 | 是哪棵树 | 怎么取到 | 本文哪里用它 |
|---|---|---|---|
| **改前-A** | issue50-a 与 issue50-b **都未应用** | `git archive 4383e3fd` 检出副本（复核阶段确认其代码与 HEAD 逐字相同） | §4.5 的「改前」列 |
| **改前-B**（= 缺陷现场） | **已应用 issue50-a、未应用 issue50-b** | = `git show HEAD:md_cg/mdcos.py`（本批改动未提交，故 HEAD 即改前）；等价于「当前工作树去掉 §三.1 的 3 处改动」 | §一、§二全部腿、§三、§4.5 的「探针」列 |
| **改后** | 当前工作树（a + b 都在） | 工作树 | 全文「改后」 |

**取证**：§二 各腿所引的 5 处改前行号（`mdcos.py` 的 `3671` / `3672` / `3690` / `3702` / `3717-3723`）与 `git show HEAD:md_cg/mdcos.py` **逐处相同**（本次实跑核对）——所以「改前-B = HEAD 树」不是推断，是逐处吻合的读数。

**由此产生的两处看似矛盾、实则两棵树**：同一个 k、同一个 `dup`，在 §二 L7 判 DEFER（改前-B：半重复已判 DEFER）、在 §4.5 判 ACCEPT（改前-A：还不存在半重复判 DEFER 这条分支，落在分支⑤「重要度 0.60≥0.30」）。**issue50-b 的单变量基线是改前-B**（§二 L7 的探针列、复核的 probe2 oracle 均如此），§4.5 的改前-A 是 a+b 的合并口径，不能当 b 的单变量证据。

### 0.2 两套「DEFER」与两类编号

| 词 | 含义 | 出处 |
|---|---|---|
| **运行时裁决 DEFER** | 遗忘闸门四态之一（`forgetting.assess` 的返回 `verdict`），指「本次写入不落盘、待定」 | 代码：`md_cg/forgetting.py:329-332` |
| **复核判定 DEFER** | **复核意见书的状态词**——复核没有把本批判成「可放行」，而是留了须使用者裁定的项 | 复核阶段交给本文的输入 `独立复核=DEFER` |

两者同形不同义；§五 内的「DEFER」一律指后者。

| 词 | 本文用法 |
|---|---|
| 「现由」 | 复核材料的小节原词；本文改称**「复核另列的、守卫未覆盖的已复现发现」**（§5.2） |
| 「不得静默」 | 复核为该批设的一类探针（不许失败静默）；本文改称**「fail-closed 与可观测面读数」**（§5.3） |
| 「越界面」 | **需使用者裁定、写入者不得自裁的面**（本批实施边界之外） |
| 「硬边界③」 | 采集材料的实施边界条目之一，原文片段为「**禁止改 `review_decide`**」。采集材料未把该清单全文给我，故本文只引片段、不代它编号 |
| 「设计文档 §八.2」 | `docs/plans/记忆自处理三档自治_设计_v0.2.md:145-152`；其 `:184` 规定本批只「按标题意图重编码 `test_writelimit.py` 的 **E 节**断言」，并要求 §八① 与「遗忘 DEFER → 复核队列」接线**必须同批落** |

### 0.3 计数口径（两个口径结论不同）

- **代码落点口径**：本批**行为改动 1 处** —— `md_cg/mdcos.py:3727-3749` 一个新增分支（§3.1）。
- **可观测行为口径**：**3 类变化** —— ① DEFER 出口新增入队；② `node_id=None` 由「静默返回 DEFER」变为 `TypeError`（§6.2-4）；③ 越权层由「静默返回」变为 `AccessDenied`（§6.2-5）。后两类不在新增分支里，是**接线带来的连带语义变化**，本文单列。

### 0.4 结论摘要

| 项 | 值 | 来源 |
|---|---|---|
| 缺陷 | 遗忘闸门 DEFER 出口只写一行 `_forgetting.jsonl` 裁决留痕——不落盘、不入审核队列、正文零去向，而裁决文案自称「待定**复核**」 | §一〔读码〕+ §二 L1〔采集〕 |
| 修法 | 接线**既有入队单点** `self.propose`：正文进审核队列、`extra.defer_reason` 记「为何待定」，零新增队列字段/类型 | §三〔实跑 `git diff`〕 |
| 行为改动面 | 代码落点 **1 处**；可观测行为 **3 类**（口径见 §0.3） | §三 |
| 守卫 | `md_cg/test_i50b_defer_to_review_queue.py`，34 断言，**34 通过 / 0 失败，rc=0**；`--mutate` 7 处变异红项 20/5/3/1/5/1/1 逐处命中，rc=0 | §4.1/§4.2〔实跑〕 |
| 生产入口端到端 | MCP 工具面 `mdcg_remember`（**非**守卫内部路径）实跑 4 例：3 例 DEFER → 队列 1 条、正文与原文字节相等、`mdcg_get` 返 `not_found`（未落盘） | §4.6〔实跑·本批新增〕 |
| python 全量 | 三次读数**均 rc=1**、均 5 跳过：`299/301`（失败 2 项）与 `300/301`（失败 1 项）两次。`md_cg.test_writelimit` **三次全红**；`scripts.test_utf8_boot_guard` **三次里红 1 次**（不稳定，未归因） | §4.3〔实跑〕 |
| 容器两栈 | 栈一 rc=**0**（`smoke_test` 自报 22 pass/0 fail；`linux_verify.sh` 自计数 38 pass/0 fail）；栈二 rc=**0**（Node TAP：# cancelled 0 /# skipped 3 /# todo 0） | §4.4〔采集，未重跑〕 |
| 独立复核 | 判定 **DEFER**（复核未放行；越界面须使用者裁定），另列 uncovered F1–F4 | §五〔复核实跑〕 |

---

## 一、缺陷定义与真实站点

### 1.1 缺陷定义

主动遗忘闸门 `remember_gated` 把一次写入裁成四态（ACCEPT / MERGE / DROP / DEFER）。其中 **DEFER 的语义是「待定复核」**——但改前这条出口**只写一行裁决留痕**：内容既不落盘、也不进审核队列（无收件箱），留痕里也没有正文。于是裁决文案承诺了一个不存在的动作：审计面写着「待定复核」，实际没有任何可复核的入口，正文随之零去向。

与**同一条链**上的 DROP 出口不对等，这是判定「缺陷」而非「设计」的直接证据：

- DROP 走 `forgetting.record_drop`（`md_cg/forgetting.py:421-463`），落 `dropped_content` / `trace_id` / `content_sha1` / `content_chars`（`:444-452`），返回体带可检索去向单；
- DEFER 改前只有 `forgetting.log(...)` 那一行（改前-B：`md_cg/mdcos.py:3717-3723`），键集不含任何 content 形态字段（§二 L1 实测 8 键）。

严重性来源：issue50-a 把「半重复」从「落成近似重复节点」改为判 DEFER 之后，这条出口会**把「噪声节点」缺陷换成「不落盘且无收件箱」缺陷**——被判定为待定复核的内容其正文不可回取。

### 1.2 真实站点（**当前工作树**行号）

| 站点 | 行 | 说明 |
|---|---|---|
| 裁决后返回体构造 | `md_cg/mdcos.py:3679-3683` | `verdict = forgetting.assess(...)`；`v = verdict["verdict"]`；`out = {...}` |
| if/elif 链 | `md_cg/mdcos.py:3684` / `:3702` / `:3714` | `if v == "ACCEPT"` / `elif v == "MERGE"` / `elif v == "DROP"`——**改前此链无 `DEFER` 分支**，DEFER 落空直达留痕块（缺陷本体：出口未接线） |
| **新增的 DEFER 分支** | `md_cg/mdcos.py:3727-3749` | 本批唯一行为改动（§3.1 给逐行映射） |
| DEFER 唯一出口（改前行为） | 改前-B `:3717-3723` → 当前 `:3752-3758` | `if v != "DROP": forgetting.log(self, {...})`——只留痕 |
| 对照：DROP 全文去向 | `md_cg/mdcos.py:3714-3726` → `md_cg/forgetting.py:421-463`（`:444-452`） | DROP 有全文去向单，DEFER 改前无对等物 |
| 对照：既有入队单点（审计/策略闸） | `md_cg/writepipe.py:282-333`：入队 `cg.propose` 在 `:318-322`，`moved_to="review_queue"` 在 `:325`；`_gate_audit` 的入队点 `:255-262`（`cg.propose` `:255-258`，`tags/condition_space` 在 `:257`，`moved_to="review_queue"` 在 `:260`） | 队列本身可用且有既有单点——L3 证明队列可承载并回取正文 |

### 1.3 采集腿行号 → 当前行号换算表（**修**：原稿「位移 = +12」只对分支之前成立）

位移是**两段**的：新增 docstring/注释把 `mdcos.py` 的分支链整体下推 **+12**；紧随其后的新增 DEFER 分支（`3727-3749`，**23 行**）再把**它之后**的块下推 **+12+23 = +35**。

| 结构 | 改前-B（= `git show HEAD:md_cg/mdcos.py`） | 当前工作树 | 位移 |
|---|---|---|---|
| 返回体构造 `out = {...}` | `:3671` | `:3683` | **+12** |
| `if v == "ACCEPT"` | `:3672` | `:3684` | +12 |
| `elif v == "MERGE"` | `:3690` | `:3702` | +12 |
| `elif v == "DROP"`（含块体 `:3702-3714`） | `:3702` | `:3714` | +12 |
| `elif v == "DEFER"` | **不存在** | `:3727-3749` | 新增 23 行 |
| 留痕块头部注释两行 | `:3715-3716` | `:3750-3751` | **+35** |
| `if v != "DROP":` | `:3717` | `:3752` | +35 |
| `forgetting.log(...)` 六行 | `:3718-3723` | `:3753-3758` | +35 |
| `return out` | `:3724` | `:3759` | +35 |

**留痕块长度不变**：采集所引「`:3717-3723`」= `if v != "DROP":` + `forgetting.log` 六行 = **7 行**；当前对应 `:3752-3758` 同样 **7 行**。（原稿把块头的两行注释算进当前区间写成 `:3750-3758`，才出现「7 行变 9 行」的自相矛盾；此处更正。）

`test_writelimit.py` 同法换算（改前-B 取 `git show HEAD:md_cg/test_writelimit.py`；E 节重编码净增 **17 行**，故 E 节之后一律 **+17**）：

| 结构 | 改前-B | 当前 | 位移 |
|---|---|---|---|
| E 节分界 | `:120` | `:120` | 0 |
| E1 断言 | `:125-127` | `:130-134` | 重编码（原位） |
| E2 断言 | — | `:138-144` | 新增 |
| F1 | `:135-136` | `:152-153` | +17 |
| G1 | `:153-156` | `:170-173` | +17 |
| H 节分界 | `:158` | `:175` | +17 |
| H1 | `:168-169` | `:185-186` | +17 |
| H2 | `:172-174` | `:189-191` | +17 |
| H3 | `:177-178` | `:194-195` | +17 |
| H4 | `:179-182` | `:196-199` | +17 |
| I 节分界 | `:184` | `:201` | +17 |

（原稿引采集腿的「红在 H1(`:170`)」是按 **+17 应为 `:187`** 的矛盾来源：该 `:170` 是 L6 那次实验里**临时副本**（把 `check` 换成 `print` 后）的运行栈行号，与仓库文件不能直接换算。本文一律改用**仓库文件行号**：H1 的 `check(` 在改前-B `:168`、在当前 `:185`。）

---

## 二、修前现场（本工作流采集的复现腿，逐条列载荷 / 观测 / 站点）

> **口径**：本节所有腿的「改前 / 现状」= **改前-B**（已应用 issue50-a、未应用 issue50-b）。全部腿 `reproduced=true`；隔离根一律 `tempfile.mkdtemp`，不触在役数据根。

### L1（缺陷主腿）遗忘闸门 DEFER 出口不入队、正文零去向

- **载荷**：隔离根 `mkdtemp(prefix='i50b_A_')` 合成库；`cg.add('base1', CCG六要素文档(标题='基线节点标题', 正文=600 互异汉字 BASE), layer='contextual', importance=0.5)`；随后 `cg.remember_gated('new1', 同模板文档(标题='新写入标题', 正文=BASE[:436]+FILL[:464]), layer='contextual', role='user', importance_hint=0.60)`。
- **观测（异常/崩溃点）**：`verdict=DEFER`；`gate.reason='半重复 0.73∈[0.6,0.85) 且未触发不可遗忘保护（待定复核）'`；`dup=0.7302`；**`gate` 无 `limiter` 键**（⇒ 确系遗忘闸门裁决，非限流）；`cg.get('new1')=None`；`review_list()` 长度=0；**`inbox.jsonl` 不存在**；`_forgetting.jsonl` 1 条 DEFER 行，键集 `['actor','entropy','importance','layer','node_id','reason','t','verdict']`——无 `content` / `dropped_content` / `text` 任一键；「正文可从队列逐字取回」= **False**。无异常抛出（静默缺陷）。
- **站点**：改前-B `md_cg/mdcos.py:3671`（out 构造）与 `:3717-3723`（留痕块；DEFER 在 `:3672/3690/3702` 的 if/elif 链里无分支）。

### L2（对照）DROP 分支有 `record_drop` 全文去向，DEFER 无对等物

- **载荷**：同 L1 隔离根与同一半重复载荷，`role='tool-output'`（internal_deterministic）。
- **观测**：`verdict=DROP`；`review_list()=0`；`_forgetting.jsonl` 1 条 DROP 行，键集含 `dropped_content`/`trace_id`/`content_sha1`/`content_chars`/`session`；`dropped_content == ' '.join(原文.split())` 为 True；`content_chars=665` == 原文空白归一后长度 665；`trace_id='drop-new1-1790854459432'`（示例值）。
- **站点**：改前-B `md_cg/mdcos.py:3702-3714`；`md_cg/forgetting.py:421-463`（`:444-452` 落 `dropped_content`/`trace_id`）。

### L3（对照）队列条目由审计/策略闸另一条链喂养

- **载荷**：隔离根 + 空规则策略文件 `{"forbidden": [], "required": []}`（env `MDCG_POLICY_FILE`）；`writepipe.install_default_gates(WritePipeline()).execute(cg, {'content_kind':'text','content':'无规则可判的内容','layer':'knowledge'})`。
- **观测**：`out.moved_to='review_queue'`，`pid='prop_519ac0406b44'`；`review_list()` 长度=1；该条 `content` 与原文字符串逐字相等=True。⇒ **队列本身可承载并回取正文**，L1 的空队列是遗忘闸门出口未接线所致，不是队列不可用。
- **站点**：`md_cg/writepipe.py:200-278`（`_gate_audit`），入队点 `:255-262`；另一入队点 `:318-322`（`_gate_consistency`，`on_conflict=defer`）。

### L4（既有语义，改动后须保持）限流 DEFER 不入队

- **载荷**：隔离根，`contextual` + `role=user` 连写 9 条互异模板串（`'盘点条目甲乙丙丁戊{i}号'`）。
- **观测**：第 9 条 `verdict=DEFER`；`gate.reason='ratelimit:contextual:user:>8in60s'`；**`gate` 含 `limiter` 键=True**；`review_list()=0`；节点未落盘。
- **站点**：改前-B `md_cg/mdcos.py:3641-3666`（`writelimit.check` 的 DEFER 出口，`:3657-3665` 只 `forgetting.log`）；当前树同块在 `:3653-3678`。

### L5（命令级）`test_writelimit` E 节旧编码转红

- **载荷（命令）**：`cd D:/program/dsh-memory-main && python -X utf8 -m md_cg.test_writelimit`。
- **观测（异常/崩溃点）**：`rc=1`；`AssertionError: [FAIL] E1 knowledge 不聚合不限流 …`（`r_k1.verdict='ACCEPT'`（保护分支）/ `r_k2.verdict='DEFER'`，`reason='半重复 0.78∈[0.6,0.85) 且未触发不可遗忘保护（待定复核）'`，`duplicate_ratio=0.7777777777777778`，`duplicate_with='wl_k1'`）；**堆栈停在 `test_writelimit.py:125`**（`check` 的 assert 在 `:37`）。
- **站点**：改前-B `md_cg/test_writelimit.py:125-127`。

### L5b（供本批重编码用）E 节「按标题意图」新编码在改前树上已成立

- **载荷**：隔离根真跑 E 节两条写入：`remember_gated('wl_k1','知识条目甲乙丙丁1号',layer='knowledge',role='user')` 与 `('wl_k2','知识条目甲乙丙丁2号')`。
- **观测**：`r_k1.verdict='ACCEPT'`，`r_k2.verdict='DEFER'`（`dup=0.7778`）；旧判据（r_k1 且 r_k2 皆 ACCEPT）=False；**新判据（两条 gate 都无 `limiter` 键）=True**；两条 gate 键集均 `['dedup_skipped','entropy','importance','reason','redundancy','verdict']`（无 limiter）；knowledge 半重复判 DEFER=True。
- **站点**：改前-B `md_cg/test_writelimit.py:120-127`（E 节）；对照 G 节 limiter 口径 `:140-156`（当前 `:157-173`）。

### L6（未点名的第二处掩盖红）H 节 H1/H3/H4，成因是 issue50-a

- **载荷**：把 `test_writelimit.py` 复制到系统临时目录（相对 import 改绝对、`sys.path` 插入 cwd），仅把 E1 的 `check` 换成 `print` 后运行；再把 H1-H4 也换成 `print` 复跑。**绝不改仓库文件**。
- **观测（异常/崩溃点）**：E1 放开后红在 **H1**；把 H1 也放开后红在 **H3**；**H4 同红**，而 H2 绿、F1/G1/I1/I2 绿。原判据逐字：
  - H1 = `check("H1 dry-run 盘出同构组", dry["groups"] >= 1 and dry["members"] >= 4, str(dry["groups"]))` → 实测 `groups=0 members=0`；
  - H3 = `check("H3 主节点收编成员清单", "整理聚合" in (m0.get("content") or "") and "wl_t1" in (m0.get("content") or ""))` → 判据 False；
  - H4 = `check("H4 成员降权 + tidy:converged", "tidy:converged" in (m1["frontmatter"].get("tags") or []) and float(m1["frontmatter"]["importance"]) <= 0.3, str(m1["frontmatter"].get("importance")))` → **抛 `TypeError: 'NoneType' object is not subscriptable`**（m1=wl_t1 未落盘）。
  - **根因实测**：`MDCG_WRITELIMIT=0` 下写 5 条 `'巡检批次{i}收官记忆'`（role=user），现状每条 `dup=0.75`→DEFER（仅第 1 条 ACCEPT，`nodes=1`）；用 in-memory 变异把分支④还原为改前合取后 5 条全 ACCEPT，`nodes=5`，`tidy dry groups=1 members=4` ⇒ **H 节红确由 issue50-a 引起**。
- **站点**：改前-B `md_cg/test_writelimit.py:158-182`（H 节整体；H1 的 `check(` 在 `:168`）；成因 `md_cg/forgetting.py:329-332`（分支④）。
- **注**：该腿实验里出现的运行栈行号取自**临时副本**（`check` 已被换成 `print`），与仓库文件不可直接换算；本文不再引用那些数字。「H1 红」这一事实由 §4.3 我本次实跑独立确认（当前树 `:185`）。

### L7 改前-B vs 目标模型对拍：3 个半重复位置

- **载荷**：隔离根逐条 `mkdtemp`；基线节点为 BASE，新载荷 k∈{436,455,503}（`role=user`, `hint=0.60`）；**探针**列 = in-memory 包装器（DEFER 且 gate 无 limiter 时调 `cg.propose(node_id, content, layer)`），仅进程内 monkeypatch、**不落任何文件**。
- **观测**：k=436 `dup=0.7302`：改前-B → DEFER / 队列 0 条 / 回取否；探针 → DEFER / 队列 1 条 / 回取是。k=455 `dup=0.7609`：同形。k=503 `dup=0.8384`：同形。⇒ 在**未打补丁**的树上，三个位置一律 0 条且不可回取（缺陷腿成立）；「改后可回取原文」在当时只由 in-memory 探针给出，**故当时不据此声称修复有效**——该缺口已由 §4.1 守卫与 §4.6 端到端实跑补上。
- **站点**：改前-B `md_cg/mdcos.py:3717-3723`（缺 propose 调用处）。

### L8 不动面：全新写入与 ≥0.85 合并两条路径改前-B/探针逐行一致

- **载荷**：同 L7，k=0（全新，`dup=0.0258`）与 k=579（近重复，`dup=0.9612`）各跑改前-B/探针两遍。
- **观测**：k=0：两列均 ACCEPT、队列 0；k=579：两列均 MERGE、队列 0。⇒ 该两条路径不受本批影响。
- **站点**：`md_cg/forgetting.py:326-328`（分支③ MERGE）、`:333-336`（分支⑤/⑥ ACCEPT）。

### L9 双跑/幂等取证：`mdcg_remember` 不过 audit；`op=write` 链不双跑；同内容幂等

- **载荷**：(a) `inspect.getsource(mcp_server)` 取 `'if name == "mdcg_remember":'` 起 2600 字片段，逐行筛 `writepipe`/`audit`/`propose`/`remember_gated`；(b) 隔离根 `gated=true` 走 writepipe 全链 `pipe.execute`，audit 用真实默认策略（未设 `MDCG_POLICY_FILE`），再以 in-memory 探针替换 `MdCGOS.remember_gated` 连跑两次同内容。
- **观测**：(a) 片段内 `writepipe`/`audit` **仅出现在注释**，无调用；该分支直接调 `cg.remember_gated`（`mcp_server.py:3326`），无 `cg.propose` ⇒ 插件真实入路**不过 audit**。(b) 首次 `out.verdict=audit` 的 `{'state':'ACCEPT',…}`、`moved_to='defer'`（gated 出口），末列队=0（改前-B）；开探针后第 1 次队列=1、第 2 次同内容队列仍=1 且 `dedup=True`。
- **站点**：`md_cg/mcp_server.py:3315-3341`；`md_cg/writepipe.py:610-643`（`install_default_gates` 的默认链序：before = linkref → deps → **audit → consistency → gated** → 链尾执行器，注册行 `:638-640`；本次读码确认）、`:228-260`（audit 非 ACCEPT 短路，ACCEPT 返 `None` 在 `:237-238`）；`md_cg/mdcos.py:2016`（`MdCGOS.propose`）与 `:4318-4319`（`MdCGSecure.propose` 覆写：先 `require_layer_write` 再 super；采集所记 `:4284` 为同一处，当前行号 `:4318`）。

### L10 全量回归基线（采集时）

- **载荷（命令）**：`cd D:/program/dsh-memory-main && python -X utf8 scripts/run_tests.py`。
- **观测**：`rc=1`；`===== SUMMARY 299/300 通过，5 跳过（依赖缺失/平台不符）=====`；失败：**`md_cg.test_writelimit`（唯一失败项，即 L5 的 E1）**。受影响守卫单跑均 rc=0：`md_cg.test_i50a_half_dup_defer`（26 通过/0 失败）、`md_cg.test_p9_forget_protect`（37/0）、`md_cg.test_p9c_dedup_hints`（31/0）、`md_cg.test_p2_mcp`（64/0）。
- **站点**：`scripts/run_tests.py`；失败断言改前-B `md_cg/test_writelimit.py:125`。

---

## 三、修法契约与落点

### 3.1 唯一行为改动（实跑 `git diff -- md_cg/mdcos.py` 核对，逐行映射）

`md_cg/mdcos.py:3727-3749` 新增分支，紧随 DROP 分支；各行的实际行号如下（原稿「上行至 `:3742` 为其注释块」无法映射，此处补全）：

| 行 | 内容 | 类别 |
|---|---|---|
| `:3727` | `elif v == "DEFER":` | 行为代码 |
| `:3728-3742` | 注释块（15 行，自「issue50-b（2026-10-01）」至「B2 同一漏传族）」） | 注释 |
| `:3743` | `_why = "遗忘闸门：" + str(verdict.get("reason") or "待定复核")` | 行为代码 |
| `:3744` | `_dup_with = (verdict.get("redundancy") or {}).get("with")` | 行为代码 |
| `:3745-3746` | `if _dup_with:` / `_why += "（重复对象 %s）" % _dup_with` | 行为代码 |
| `:3747-3749` | `out["proposed"] = self.propose(node_id, content, layer=layer, sensitivity=kw.get("sensitivity"), defer_reason=_why)`（3 行） | 行为代码 |

其余 `mdcos.py` diff 仅两处非行为改动：`# 生效条件：` 首行（`:3596`，DEFER 由「只留痕」改为「不落盘、经既有入队单点 `self.propose` 把正文与为何待定送进审核队列（返回体带 `proposed=pid`），并照旧只记 forgetting 留痕」）与 docstring 新增段（`:3608-3618`）。

### 3.2 复用既有单点，零新增协议

- 入队走 `MdCGOS.propose`（`md_cg/mdcos.py:2016`）：幂等对账键 `payload_hash=_sig(content)`（`:2034`），锁内「查重→入队」原子（`:2043-2056`）——**同内容重复写入不长第二条**；
- 「为何待定」写进 rec 的既有任意槽 `"extra": kw`（`:2075`），密级 `sensitivity` 落 rec 顶层（`:2073`）；
- **未新增队列字段、未新增队列类型、未新增第二套入队实现**（与 `writepipe._gate_audit`、`_gate_consistency` 同一条链）。

### 3.3 覆盖面边界

| 情形 | 是否入队 | 依据 |
|---|---|---|
| 遗忘闸门自身 DEFER | **入队** | `md_cg/mdcos.py:3727-3749` |
| 限流（ratelimit）DEFER | 否 | 已在 `:3653-3678` 提前 `return`——语义是「先别写」，原文在 recent 时间线，不是内容待定 |
| `gated=False` 旁路 | 否 | `:3644-3648` 直接 ACCEPT 写盘并返回 `bypass` |
| ACCEPT 后 `on_conflict=defer` 降级 DEFER | 否 | `:3693` / `:3698`（`v` 在 `if v == "ACCEPT"` 内就地改写，不进 DEFER 分支） |
| MERGE / DROP | 否 | 各自原出口不变（DROP 仍走 `record_drop` 全文去向） |

### 3.4 未动的面

`forgetting.assess` 判据/常量/分支次序（本批未改 `forgetting.py`；该文件工作树改动属 issue50-a，见 §6.1）、`writelimit.py`、`writepipe` 的 audit propose 路径、`review_cli` / `review_decide`。

### 3.5 守卫落点

新建 `md_cg/test_i50b_defer_to_review_queue.py`（538 行）：A–F 六组 34 断言 + 自带 `--mutate` 定点变异自证 + 静态锚点 fail-closed。结构锚点（本次读码）：`_GROUPS` `:346`、`_SRC_MUTATIONS` `:371`、`_gated_src` `:449`、`_anchor_check` `:453`、`_mutate_src` `:473`、`_mutate_mode` `:490`、`main` `:517`。全部用例在隔离临时根 + designer-cli 本地身份真跑，退出前 `close()` 再删根。

### 3.6 测试面重编码

`md_cg/test_writelimit.py` E 节（当前 `:125-144`；模块 docstring `:9`）：E1 判据由「r_k2 判 ACCEPT」改为「**限流器未介入** = 两条写入的 gate 均无 `limiter` 键」（与 G 节 `rec.get("limiter")` 同口径；旧判据是旧遗忘闸门裁决的**副产物**，非层豁免的证据）；新增 E2 钉住新行为（knowledge 层半重复、两条载荷仅尾字不同、实测 `dup=0.7777777777777778` → 遗忘闸门判 DEFER，且带 `redundancy` 读数、无 `limiter` 键）。**除 E 节外未改任何既有断言**（授权面见 §0.2「设计文档 §八.2」）。

---

## 四、验证数字

### 4.1 守卫〔实跑〕

```
python -X utf8 -m md_cg.test_i50b_defer_to_review_queue
→ 锚点自检：PASS（test_i50b_defer_to_review_queue.py；不以 git HEAD 为基线源）
→ A11 / B4 / C5 / D5 / E4 / F5 全 PASS
→ issue50-b 守卫：34 通过，0 失败        rc=0
```

- **断言数 34 / 通过 34 / 失败 0 / rc=0**（我本次执行，逐行读到）。
- A 组：A4 队列面正文与原文**逐字相等**（含换行/空白）；A8 DEFER 不落盘；A9 forgetting 留痕行仍在且形状不变（无 `limiter` 键）；A10 返回体 `proposed == 队列 pid`；A11 队列读面 `review_list()` 同样能取回正文。
- B 组：换 `node_id` 同内容再写 → 队列仍 1 条（payload_hash 幂等）。
- C 组：`accept` 后正文真的落盘且逐字相等；`reject` 后不落盘。
- F 组：一次写入 → 队列恰 1 条（`writepipe` 全链：audit 判 ACCEPT 时未入队、gated 判 DEFER 时入队，不双跑）。

### 4.2 定点变异〔实跑〕

```
python -X utf8 -m md_cg.test_i50b_defer_to_review_queue --mutate   → rc=0
  未变异基线：红项=0
  ① DEFER 出口不接线（删掉 propose 调用）→ 红项 20   命中预期
  ② 入队正文传成空串（正文可取回必红）  → 红项  5   命中预期
  ③ 限流 DEFER 也入队（违背先别写语义）→ 红项  3   命中预期
  ④ gated=False 旁路也入队             → 红项  1   命中预期
  ⑤ 双跑（第二路绕开幂等键）           → 红项  5   命中预期
  ⑥ DEFER 不写 forgetting 留痕         → 红项  1   命中预期
  ⑦ defer_reason 文案清空              → 红项  1   命中预期
  定点变异自证：PASS
```

（变异作用在**当前盘实现**的 `getsource` 副本上、exec 执行，**不以 git HEAD 为基线源**。）

### 4.3 python 全量〔实跑：同一命令跑了三次〕

```
python -X utf8 scripts/run_tests.py
第 1 次（管道取尾）  ：SUMMARY 299/301 通过，5 跳过 ；失败：md_cg.test_writelimit, scripts.test_utf8_boot_guard
第 2 次（完整捕获）  ：FULL_SUITE_RC=1 ；SUMMARY 300/301 通过，5 跳过 ；失败：md_cg.test_writelimit
第 3 次（抓 SKIP 名单）：RC=1 ；SUMMARY 300/301 通过，5 跳过 ；失败：md_cg.test_writelimit
```

- **第 2、3 次 rc=1**；第 1 次是管道取尾，**未取到 python 自身退出码**（读到的是它已判 2 项失败）。
- **`md_cg.test_writelimit` 三次全红**（本批的确定失败面）。
- **`scripts.test_utf8_boot_guard` 三次里只红 1 次**（第 1 次），另两次全量判 PASS；**四次单跑全部 rc=0、`SUMMARY 30/30 通过（正向 13/13 + 定点变异 17/17）`**，覆盖三种形态：`python -X utf8 -m scripts.test_utf8_boot_guard`（带 `PYTHONUTF8=1`/`PYTHONIOENCODING=utf-8`）、`python -X utf8 <repo>/scripts/test_utf8_boot_guard.py`（同上 env，×2）、`python -X utf8 <repo>/scripts/test_utf8_boot_guard.py`（**裸跑，不额外设 env**）。⇒ **该项读数不稳定，本文未归因**（与 `mdcos.py`/`forgetting.py` 无调用交集；本批未做归因实验），不作因果断言。
- 失败项 1 详情：`python -X utf8 -m md_cg.test_writelimit` → **rc=1**，`AssertionError: [FAIL] H1 dry-run 盘出同构组 0`，栈停在 `md_cg/test_writelimit.py:185`（断言实现 `:37`）；**E1/E2 已绿**（E1「knowledge 层豁免：限流器未介入」、E2「半重复交遗忘闸门判 DEFER（dup=0.7778）」）。
- **5 个跳过项（第 3 次读数的完整名单与原因）**：

| 跳过项 | 原因 |
|---|---|
| `md_cg.test_md_access_parity` | 依赖白箱库 `whitebox_kb/wisdom/wisdom-book-cloud.db`（`.gitignore` 忽略，需本地生成） |
| `md_cg.test_p44_md_whitebox` | 同上 |
| `md_cg.test_wisdom_md_store` | 依赖 md 语料真源 `_md_cg_wisdom_graph/`（`.gitignore` 忽略，组 D 需本地真源） |
| `swarm.tests.bench_swarm_parallel` | 负载敏感（性能阈值断言），并行争抢会假红——仅串行执行 |
| `swarm.tests.bench_swarm_scale` | 同上 |

- 采集基线〔采集〕：同命令得 `299/300 通过，5 跳过`，唯一失败 `md_cg.test_writelimit`。分母 300→301 与通过数 299→300 的自洽（推断，未逐件比对清单）：第 2/3 次的通过面 = 采集基线通过面 + 本批新增守卫件 `md_cg.test_i50b_defer_to_review_queue` 入列并转绿。

### 4.4 容器两栈退出码〔采集，我未重跑〕

| 栈 | 形态 | 读数 | 退出码 |
|---|---|---|---|
| 栈一 | `docker run --rm -v <repo>:/work -w /work rust:bookworm bash scripts/linux_verify.sh [full\|core]`（用法见 `scripts/linux_verify.sh:3`） | `smoke_test` 自报 **`结果: 22 pass / 0 fail`**；脚本自计数 **`=== 汇总: 38 pass / 0 fail ===`** | **0** |
| 栈二 | `npm test`（= `npm run build && node --import tsx --test "test/*.test.ts"`，见 `package.json` scripts.test） | TAP 汇总 `# cancelled 0` / `# skipped 3` / `# todo 0` / `# duration_ms 11963.466483` | **0** |

**22 与 38 各自是谁**（本次读码拆解，修正原稿「同一括号里列四项」的含混）：

- **22** = `smoke_test` **进程自身的断言计数**，由它自己打印（`hive/hive_mcp/smoke_test.py:290`：`print(f"\n结果: {PASS} pass / {FAIL} fail")`），**不是**脚本的记录条数。
- **38** = `scripts/linux_verify.sh` 的 `record` 计数合计（计数器在 `:11-15`，汇总行在 `:115`，退出码在 `:116` 的 `[ "$fail" -eq 0 ]`）：`cargo test` 1 条（`:22`）+ `cargo build --release` 1 条（`:27`，仅 full）+ **md_cg 模块 23 条**（`:41-52`）+ **hive 文件 4 条**（`:54-59`）+ **定点变异自证 7 条**（`:88-99`）+ hive 变异 1 条（`:102-107`）+ `smoke_test` 1 条（`:112`，仅 full）= **38**。core 模式为 **36**。
- 因此「python 套件」段的实际条数是 **27**（23 + 4），与 22 无关。

### 4.5 改前/改后对拍与复核自建腿〔采集 / 复核实跑〕

- **改前-A vs 改后**（复核阶段：`4383e3fd` 副本 = 当前树去掉 a 与 b 两批改动）：半重复 `k=360 dup=0.6074`｜改前-A `ACCEPT`(reason=重要度 0.60≥0.3)、队列 0 条、无条目可取、落盘=True ｜改后 `DEFER`、队列 1 条、正文逐字等于原文=True、落盘=False。`k=436 dup=0.7302`、`k=503 dup=0.8384` 同行同形。不动面：`k=0 dup=0.0258`（改前-A / 改后均 ACCEPT，队列 0、落盘 True，触发不可遗忘保护）逐行不变；`dup=0.9612`（均 MERGE，`merged_into=base`、`base.merge_count=1`）逐行不变。**口径提醒**：这一栏的「改前-A」不含 issue50-a，故其 ACCEPT 是 a+b 合并效应，不是 b 的单变量基线（§0.1）。
- **b 的单变量对拍**（复核实跑 `probe2_oracle.py`）：oracle = `git show HEAD:md_cg/mdcos.py` 里**改前的 `remember_gated` 源文本**抽出、dedent、exec，**两侧共用同一份 `forgetting.py`**（= 当前工作树那份，含 issue50-a）。12 例中 **8 例 verdict+reason+节点集+forgetting 留痕（t 与含时间戳的 trace_id 归一后）逐位相同**；**4 例差异全部是 assess 判 DEFER 者**（c2/c3/c5/c8），差异恰为「新增 `proposed` 键 + 队列 1 条」，verdict/reason/节点集/留痕行其余字段仍逐位相同。
- **其余复核腿**：`probe1_legs.py` 30 通过 0 失败（含**独立 payload/bigrams/_coverage 扫描**：半重复腿 `gate.redundancy=('base',0.730210,1)` 与其逐位相同；退化腿空池 → ACCEPT 且队列 0，未被伪判 DEFER）；`probe4_silent.py` 见 §5.3；删断言探针（内存改 `_GROUPS`，文件 sha256 前=后）：删 `g_a`…`g_f` → `_mutate_mode()` 均返回 1。

### 4.6 生产入口（MCP 工具面）端到端〔实跑·本批新增，回答读者第一问〕

前几节的第一手证据都是**守卫内部路径**。为回答「生产入口有没有端到端跑过一次」，本轮补跑：仓外临时脚本经 **真 stdio MCP 服务**（`python -m md_cg.mcp_server`，`MDCG_ROOT`=隔离根、`MDCG_MCP_SURFACE=full`、`MDCG_ACTOR=i50b-e2e`）调**生产工具** `mdcg_remember` / `mdcg_get` / `mdcg_review_list`；基线与载荷**标题互异**（避开同构聚合 `CONVERGE` 与限流），逐例各用一个隔离根。

| 例（新增长度 f） | verdict | `dup` | `gate.limiter` | `proposed` | `mdcg_get("w")` | 队列条数 / 正文逐字相等条数 | `proposed == pid` |
|---|---|---|---|---|---|---|---|
| f=60 | MERGE | 0.8816 | null | false | — | — | — |
| f=100 | **DEFER** | 0.8199 | null | **true** | `{"ok": false, "error": "not_found"}`（未落盘） | 1 / **1** | **true** |
| f=150 | **DEFER** | 0.7540 | null | **true** | `{"ok": false, "error": "not_found"}` | 1 / **1** | **true** |
| f=220 | **DEFER** | 0.6777 | null | **true** | `{"ok": false, "error": "not_found"}` | 1 / **1** | **true** |

- 队列里该条的 `extra.defer_reason` 实测 = `'遗忘闸门：半重复 0.82∈[0.6,0.85) 且未触发不可遗忘保护（待定复核）（重复对象 base）'`（f=100 例；f=150/220 同形）。`gate.limiter` 为 null ⇒ 确系遗忘闸门裁决而非限流。
- **结论**：**生产入口（`mcp_server.py:3315-3341` → `remember_gated`）的 DEFER → 审核队列链路已端到端跑过**，正文逐字可回取、返回体 `proposed` 即队列 `pid`、「为何待定」在位、节点未落盘。
- **复现要点**：探针脚本是一次性仓外文件（`%TEMP%/i50b_e2e_probe.py`，跑完即弃）；等价复现只需按上列 env 起 `python -X utf8 -m md_cg.mcp_server`，走标准 MCP stdio（`initialize` → `notifications/initialized` → `tools/call`），依次调 `mdcg_remember`（先写基线，再以 `gated=true`+`role=user`+`layer=contextual`+`importance_hint=0.6` 写半重复载荷）、`mdcg_get`、`mdcg_review_list`。**注意两点**：基线标题须与载荷标题不同（否则被同构聚合 `CONVERGE` 拦走）；判落盘要看 `mdcg_get` 的 `{"ok": false, "error": "not_found"}`，不能看返回值的真值性。
- **如实记录探针自身的两处缺陷（修正前的读数不作为证据）**：① **探针 v1** 把新增内容给到 464 字，`dup` 只到 0.5053 → 落在 ACCEPT（`dup` 是「新内容被既有节点覆盖的比例」，`md_cg/forgetting.py:106-109`、`:201`，新内容越长该比值越低），且基线与载荷同标题触发了限流侧的 `CONVERGE`；② **探针 v2 首跑**把 MCP `mdcg_get` 的返回**真值性**当落盘判据，而它对不存在节点返回 `{"ok": false, "error": "not_found", …}`（`mcp_server.py:3460-3469`），非空 dict 被 `bool()` 判真 → 误报「落盘」。两处均已修正后重跑（上表为修正后的读数）。

---

## 五、独立复核判定与它列出的 uncovered

### 5.1 判定：**复核判定 DEFER**（§0.2 的第二个含义：复核未放行）

- **作者与独立性**：本节全部内容来自本工作流的**独立复核阶段**（其探针在仓外 `%TEMP%/i50b_review/`，被测物为 `git diff -- md_cg/mdcos.py`）。我（报告撰写员）只**转录**；其中仅**守卫文件 sha256 与 §4.1/§4.2 的跑数**是我实跑（守卫文件 `sha256` 前缀 **d23e45c3**，与复核所记相符），其余标〔复核实跑〕的读数我**未重跑**。
- **被测物**〔复核实跑〕：`git diff -- md_cg/mdcos.py` 的唯一行为改动 = `md_cg/mdcos.py:3727-3749` 新增 `elif v == "DEFER":` → `out["proposed"] = self.propose(...)`；其余为 docstring / 注释 / `# 生效条件` 首行；另改 `md_cg/test_writelimit.py` E 节。改动前后指纹：`forgetting.py` 与守卫文件哈希不变（守卫跑前=跑后）。
- **未放行的原因**：不是判据不全，而是**存在须使用者裁定的项**（§6.4）；复核据此把状态留在 DEFER，未升级为可放行。

### 5.2 uncovered（复核另列的、守卫未覆盖的已复现发现；均〔复核实跑〕）

- **F1 meta 透传面缺失**：同一声明 META（tags/condition_space/verification_basis/non_applicable_conditions/derived_from/relation）下，「DEFER→accept」节点 vs「直接 ACCEPT」节点 frontmatter 差异：`tags []` vs `['t1','t2']`、`condition_space {}` vs `{'a':1,…}`、`verification_basis None` vs `'data'`、`derived_from` 缺 vs `['base']`、`role` 缺 vs 有、`importance 0.5` vs `0.6`（hint 丢失）；且 DEFER→accept 节点**多出 frontmatter 键 `defer_reason`**（盘上文件实测 `defer_reason: "遗忘闸门：半重复 0.73∈[0.6,0.85) 且未触发不可遗忘保护（待定复核）（重复对象 base）"`，`tags: []`）。队列记录本身 `tags=[]`/`condition_space={}`，与同族入队点 `writepipe._gate_audit`（`:255-258` 传 `tags`/`condition_space`，字段值取自 `:257`）不一致——**本批只修了 `sensitivity` 一个成员**。
- **F2 `node_id=None` 崩点**：`remember_gated(None, 半重复, …)` 改前-B → 无异常 `verdict=DEFER`；现行 → `TypeError: unsupported operand type(s) for +: 'NoneType' and 'str'`（propose 的 `pid = "prop_" + _sig(node_id + str(time.time()) …)`，`md_cg/mdcos.py:2063`；本次读码确认 `:2063` 即该拼接表达式）。**生产入口不可达**：`mcp_server.py:3321`（`nid = a.get("node_id") or mint_auto_id(cg)`）与 `writepipe.py:135`（`"nid": a.get("node_id") or mint_auto_id(cg)`，本次读码确认）都有兜底；CLI / 插件入路未逐条排查（见 §6.3）。
- **F3 未闭合红**：`python -X utf8 -m md_cg.test_writelimit` → 退出码 **1**，`AssertionError: [FAIL] H1 dry-run 盘出同构组 0`（**本次我实跑独立确认**；E1/E2 已绿）。机制钉死：`MDCG_WRITELIMIT=0` 下连写 5 条同构短骨架 → 1 ACCEPT + 4 DEFER(`dup=0.75`) → 落盘仅 `wl_t0` → `tidy groups=0`。**归因隔离实验**（三副本同探针）：`4383e3fd` 副本 → 落盘节点 `[wl_t0..wl_t4]`、H1/H2/H3/H4 全 True；**仅 issue50-a 副本与当前工作区读数完全相同**（落盘 `[wl_t0]`、`dry.groups=0`、H1 False、H2 True、H3 False、H4 TypeError）⇒ 三条转红系 **issue50-a** 所致，与 issue50-b 无因果。
- **F4 夹具清理 best-effort**：Windows 上重复跑后 `%TEMP%` 下 `i50b_*` 残留 150 个（内含 `_index.json` / `_index.json.lock`）；复核时已全部清除（清理后 0）。**我本次实跑复现了同一形态**：跑过守卫与 §4.6 探针后，`%TEMP%` 里留下 36 个 `i50b_case_*` / `i50b_wp_*` 根（各自只含 `_index.json` + `_index.json.lock`，mtime 19:58–20:19，即本会话内），且删除过程中多次出现 Windows `WinError 2`（文件已被并发清掉/锁未释放）——**「best-effort」这个定性由此得到第一手印证**；我已在撰写本报告时清空（清后 `i50b_*` 计数 = 0）。

### 5.3 fail-closed 与可观测面读数〔复核实跑〕

- **锚点 fail-closed**（内存注入 `_gated_src`）：完全漂移 → `_anchor_check()` 10 条 / `main()` rc=2 且打印 `ANCHOR-MISS`；摘掉 propose 接线 → 5 条 / rc=2；限流 DEFER 也接线（违契约）→ 1 条 / rc=2；不注入 → 0 条 / rc=0。
- **真实入路可观测**：队列 jsonl `extra.defer_reason` 在位且 `content` 逐字相等；读面 `cg.review_list()` 命中且 `pid==proposed`；`forgetting_history` verdict=DEFER、`summary.by_verdict={'DEFER':1}`；`cg.get('w') is None`；accept 后正文逐字落盘。（其中「读面命中且 `pid==proposed`、正文逐字相等」已由我 §4.6 经 MCP 工具面独立复现。）

---

## 六、边界与未覆盖

### 6.1 issue50-a 与 issue50-b 的分界

工作树 `md_cg/forgetting.py` 的改动**属 issue50-a**（实跑 `git diff` 核对）：分支④ 删去 `and imp["score"] < IMPORTANCE_MIN`（`:326-332`：分支③ MERGE 在 `:326-328`，分支④ DEFER 在 `:329-332`），文案由「且重要度 x<0.30」改为「且未触发不可遗忘保护」，并同步 `# 生效条件：` 首行与 docstring 的 issue50-a 段。**本批（issue50-b）未改 `forgetting.py`**；H 节红是 issue50-a 的既成后果。

### 6.2 本轮明确不修、留池的面

1. **`test_writelimit` H1/H3/H4**（F3）：按契约「除 E 节外不许改任何既有断言」原样保留——`docs/plans/记忆自处理三档自治_设计_v0.2.md:184` 只授权「按标题意图重编码 `test_writelimit.py` 的 **E 节**断言」，H 节未获授权。归因已钉死为 issue50-a。
2. **F1 meta 透传面**：tags/condition_space/verification_basis/derived_from/role/importance 在 DEFER→propose→accept 链路丢失；`defer_reason` 落进 accept 后节点 frontmatter。修法需要 propose/review_decide 侧的「只存队列、不落 fm」槽，属扩面。
3. **`extra.defer_reason` 随既有 extra 通道写进 accept 后 frontmatter**（实测 `frontmatter.defer_reason='…'`）：propose 的 record 里除 `extra` 外没有该槽，而采集材料明示的硬边界之一是「**禁止改 `review_decide`**」 ⇒ 已取证并如实上报，未擅自扩面。
4. **F2 `node_id=None` 的 TypeError**：生产入口不可达；「静默返回 DEFER」→「抛异常」的语义变化未收口。
5. **越权身份（`layers_allow` 排除该层）**：原先在 DEFER 出口静默返回，现由 `self.propose` 的层写闸抛 `AccessDenied`（fail-closed，语义更诚实）——行为变化已上报，未另设兼容层。
6. **F4 夹具清理 best-effort**（Windows 文件锁），未改为强制清理。
7. **`scripts.test_utf8_boot_guard` 的不稳定红**（§4.3）：三次全量里红 1 次、单跑四种形态全绿 ⇒ **未归因**。该守卫与 `mdcos.py` / `forgetting.py` 无调用交集，本批未做归因实验，**不作任何因果断言**。

### 6.3 未跑 / 未验（如实声明）

- **容器两栈**（§4.4）：〔采集〕所得，**我未重跑**（本机有 `docker` 可执行，本轮未执行容器）。
- **改前/改后对拍、probe1/2/4/5、删除断言探针、ANCHOR-MISS 注入**（§4.5、§5.3）：〔复核实跑〕，**我未重跑**。
- **生产入口的其它入路**：`mdcg_remember` 已端到端跑过（§4.6）；**CLI 与插件（DSH/CodeBuddy 等）入路未逐条排查**，它们是否都经 `mint_auto_id` 兜底未核。
- 我本次实跑的是：守卫默认模式、`--mutate`、`-m md_cg.test_writelimit`、`scripts/run_tests.py`（三次）、`scripts/test_utf8_boot_guard.py`（四种形态）、§4.6 的仓外 MCP 端到端探针、若干读码与 `git diff` / `git show HEAD:` / `sha256`。

### 6.4 需使用者裁定（复核把状态留在 DEFER 的具体项）

1. **带红交付**：本批交付时全量仍红在 `md_cg.test_writelimit`（H1/H3/H4，归因 issue50-a）——是否接受带红交付；H 节由谁、何时修（谁授权重编码 H 节）。
2. **F1 是否扩面**：DEFER→accept 节点丢 tags/condition_space/verification_basis/derived_from/role 与 importance hint ——使用者从队列回看这次修复会看到这些缺失，是否本轮扩面修。
3. **`defer_reason` 落 accept 后 frontmatter** 这一取舍是否接受（在「禁止改 review_decide」的边界下，propose 的 record 里没有别的槽）。
4. **F2（`node_id=None` → TypeError）与 F4（best-effort 清理）** 是否收口。
5. **`scripts.test_utf8_boot_guard` 不稳定红**是否归因、是否按 CI 偶发阻断处置。
6. **提交策略**：设计文档 `:184` 明确「§八① 与「遗忘 DEFER → 复核队列」接线**必须同批落**」⇒ 提交面应同批；具体是一个 commit 还是同批两个 commit 由使用者定。
7. **越权层 → `AccessDenied`** 的语义变化是否接受。

### 6.5 硬边界

- 全部实验根在系统临时目录（`tempfile.mkdtemp`）且跑完清理；**未触碰在役数据根 `D:\program\AEIS`**；
- **未 `git add` / `commit` / `push`**；本次只写入本报告一个文件；
- 报告不含明文凭据。

---

## 附：本次实跑命令清单（含 argv/env，可复现）

```bash
# 守卫（默认 / 定点变异）
python -X utf8 -m md_cg.test_i50b_defer_to_review_queue            # 34 通过 / 0 失败；rc=0
python -X utf8 -m md_cg.test_i50b_defer_to_review_queue --mutate   # 基线红 0；7 处变异 20/5/3/1/5/1/1；rc=0

# 单模块：确定失败面
python -X utf8 -m md_cg.test_writelimit                            # rc=1；[FAIL] H1（:185）；E1/E2 已绿

# 全量（三次；第 3 次为抓 SKIP 名单那次）
python -X utf8 scripts/run_tests.py                                # 均 rc=1；299/301 与 300/301；5 跳过

# utf8 守卫单跑（四种形态；§4.3 的读数取自带 env 的文件路径形态）
PYTHONUTF8=1 PYTHONIOENCODING=utf-8 python -X utf8 -m scripts.test_utf8_boot_guard          # rc=0，30/30
PYTHONUTF8=1 PYTHONIOENCODING=utf-8 python -X utf8 scripts/test_utf8_boot_guard.py          # rc=0，30/30（×2）
python -X utf8 scripts/test_utf8_boot_guard.py                                               # rc=0，30/30（裸跑）

# 端到端：MCP 工具面（§4.6；脚本在仓外，stdin/stdout 走 JSON-RPC，MDCG_ROOT=隔离根）
python -X utf8 %TEMP%/i50b_e2e_probe.py                            # 4 例：MERGE / DEFER×3（一次性探针，本轮用完即弃）
```

> 采集阶段的命令清单见 `docs/eval/issue50_半重复待定复核_修复记录_v1.0.md` 附录（issue50-a 口径）。
