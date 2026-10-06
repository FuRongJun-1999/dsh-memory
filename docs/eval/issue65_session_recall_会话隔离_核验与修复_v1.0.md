# issue65 · session_recall ③ 近期事件段未按会话隔离——核验与修复报告 v1.0-r1

**日期**：2026-10-07 ｜ **版本**：v1.0-r1（同日按读者反馈逐条修订——处置明细见 §十）｜ **缺陷号**：issue65（外部报告 by ducc239，对 v0.7.5 实测）｜ **被测面**：`<仓根>` 工作树（未提交：`md_cg/mdcos.py`、`md_cg/test_p45_session_identity.py` 两件被改，本报告为第三件新增；`git status --porcelain` 实测两件 `M`）

**证据分级声明**（本报告只写有机械证据的事）：

| 标记 | 含义 |
|---|---|
| 〔本报告实跑〕 | 实施员/撰写员在本工作流内亲手执行并读数：修前/修后隔离库探针、守卫正向与变异自证、ANCHOR-MISS 探针、定向回归、`git status`、python 全量、仓内文件读码与哈希 |
| 〔工作流采集〕 | 本工作流的编排/独立复核阶段采集的读数（修前复现腿（§2.1）、独立复核四态判定、容器两栈）——本文转记处逐条标注 |
| 〔契约给定〕 | 设计者裁决随任务下发的口径（修法形态、语义矩阵、守卫清单、不许动清单） |

**一句话结论**：缺陷成立、缺口唯一（**限本 issue 面内**：`MdCGOS.session_recall` ③ 段未传会话；另有一处同类但属显式开关面的读侧缺口，见 §七-1）——两行过滤按契约落地，修后行为矩阵逐项符合；守卫 **30 → 42** 条断言（新增 R65 组 12 条：编号 `R65.1–R65.9`，其中 R65.4/5/6 各拆两态，对照表见 §5.1）＋**六条定点变异腿逐条恰好命中期望红项**（基线源为运行中实现源码、**不读 git**）；**ANCHOR-MISS 不在六腿之内**，它是另设的 fail-closed 口径（锚点漂移 → 退出码 2，见 §5.4）；定向回归 `md_cg` 组 **249/249**；python 全量 **359/359**（5 跳过）；容器双栈退出码 **0 / 0**（栈一 `linux_verify.sh full` 汇总 49 pass / 0 fail；栈二 TS 144 项 141 通过 / 0 失败 / 3 跳过）；**独立复核 ACCEPT**（四态判定单 ①②③④ 全 PASS，见 §六）。一处**不在授权改动面内**的文档漂移（`src/lib/mdcg_client.ts` 注释把修前行为写成「服务端事实」）如实登记（§七）。

---

## 一、缺陷定义与真实站点

**定义**：`MdCGOS.session_recall` 的「③ 近期事件」段取 `self.recent_events(limit=…)` 时**不传会话**；而 `MdCGSecure.recent_events`（改前 `md_cg/mdcos.py:5142`，改后 `:5165`）**没有 session 形参**（只有 `private`/`secret` 密级档做会话归属判断，默认档 `internal` 全放行）⇒ `recent` 段恒为**全进程窗口**：多窗口/多会话并发时，A 会话语境里混入 B 会话的报文——**静默污染，不报错、不降级**。危害链两条（r1 补证据，各点均读码核实）：
- **注入面**：DSH 侧把窗口文本推入宿主请求上下文——`src/hooks.ts:663-667` 将 `formatSessionWindow` 的输出经 `renderUntrustedMemoryBlock` 推入 `assembly.contexts`（块名 `lingshu:session-window`）。
- **压缩重建面**：zcode 压缩钩子在压缩后取 `session_recall(session=sid)` 的 recent 段拼成「本会话近期对话」重建文本——`scripts/zcode_compact_hook.py:67-71` → `scripts/sync_zcode_session.py:330,344-351`，并经 `_ack_compact`（`zcode_compact_hook.py:74-88`）登记「已履行近 10 轮重建」。修前该段是全窗口，混入的他会话报文会随该文本进入注入/重建。
- **未观测**：「运行时确已发生混入」本身无观测记录（本 workflow 只做了库侧读数）；上述两条为**代码链证据**，非现场取证。

**真实站点**（读码；行号口径见下表内标注——本报告正文其余处引用一律为**改后**工作树行号）：

| 面 | 位置 | 修前形态 |
|---|---|---|
| 缺陷点 | `md_cg/mdcos.py` ③ 段（改前 L3307-3314 → 改后 L3316-3337） | `evs = self.recent_events(limit=…)` → 直接组装 `pack["recent"]`，无会话过滤 |
| 读隔离本体 | `MdCGSecure.recent_events`（改前 L5142-5167 → 改后 `md_cg/mdcos.py:5165-5190`） | 无 `session` 形参；只按 tenant × 密级（＋ private/secret 档的会话归属）过滤 |
| 同族正确形态① | `session_compact` 的 `if session:` 过滤（改前 L3384-3386 → 改后 `md_cg/mdcos.py:3407`） | `if session: evs = [r for r in evs if (r.get("meta") or {}).get("session") == session]` |
| 同族正确形态② | `_session_notes`（`md_cg/mdcos.py:3205`，未漂移） | `session:{sid}` tag 过滤（① 段本就按会话走） |
| 同族正确形态③ | `md_cg/mcp_server.py:2843` `_session_call`（recall 分支 `:2863-2870`） | 已把 `session=a.get("session")` 传进 `session_recall`（`:2864`） |
| 写侧（均已打点） | `src/hooks.ts:698/772`、`MdCGSecure.remember_event`（改前 L5064 → 改后 `md_cg/mdcos.py:5087`） | DSH 窗口写入带 `{session: sid}`；安全档 `remember_event` 对缺会话者 `setdefault` 成本进程会话 |

⇒ **在本 issue 的面内**（`session_recall` ③ 段读侧），缺口只有一处；写侧与 MCP 调用链均正确——与编排侧核验结论一致。**「唯一」的边界**：另有一处**同类**读侧缺口（`recall(include_recent)` 的近期事件尾巴，`md_cg/mdcos.py:1952`），按 ask 口径属显式开关面、登记不回——不计入本节「缺口唯一」，见 §七-1（r1 显式限定）。

---

## 二、修前现场：编排侧复现腿（逐条）＋实施员探针

### 2.1 编排侧采集的复现腿（〔工作流采集〕，逐条列 payload / 异常 / 崩溃点）

以下 ①–⑤ 为缺陷/旁证腿、⑥ 为登记腿、⑦ 为对照基线（非缺陷）；全部在**隔离库**（`tempfile.mkdtemp` 合成库；经 MCP 真实入口 `md_cg.mcp_server._session_call` 与直调 `cg.session_recall(...)` 两条路径读取）逐腿钉死；**全部缺陷腿为非崩溃型**——无异常抛出、无错误消息、**无崩溃点**，缺陷形态是**静默**的数据越界/混入（宿主把 recent 当用户输入处理，这正是本缺陷最危险处）。日志：`%TEMP%/issue65_probe/probe_run3.log:26-54`、`%TEMP%/issue65_probe/probe2_run2.log:2-23`。

**合成库清单（r1 补——全文共 4 个互不相同的隔离库，读数不可跨库比较）**：

| 库 | 构成（均为 `tempfile.mkdtemp` 合成库） | 出现处 |
|---|---|---|
| 库① | 五事件：`A1`/`A2`（属 `session-AAA-0000`）、`B1`（属 `session-BBBB-0000`）、`N0`（缺 `meta.session`）、`AX`（A 的**前缀延伸**会话） | §2.2、§四 |
| 库② | 三事件（会话 A/B 分属两会话）＋腿④追加的无归属事件（共 4 条） | §2.1 腿①–④、腿⑦ |
| 库③ | 三事件 ＋ 两条 `session_note`（A/B 各一） | §2.1 腿⑤ |
| 库④ | 复核自建：`A1`（会话 A）、`B1`（会话 B）、经安全档写侧归属 A 的裸事件、存量裸事件 `L0` | §6.2 |

同一标签（`A1`/`A2`/`AX`/`N0`/`B1`）在**不同库中代表不同事件集**（例如 A 会话读数：库① 修前 5 条 / 修后 2 条 / 修后安全档 3 条；库④ 安全档 2 条——差异源于**库构成**，非实现行为；正文各读数已就近标注库号）。

**腿①（缺陷① · 假会话 id → ③ 段返回全局窗口，应 `[]`）**
- payload：库内置 3 条合成事件——`('user','会话A的第一句话', meta.session='session-AAA')`、`('user','会话B的第一句话', meta.session='session-BBB')`、`('assistant','会话A的第二句话', meta.session='session-AAA')`；读入参 `session='session-zzzz-nope-0000'`（MCP：`{action:'recall', session:'session-zzzz-nope-0000', limit:5, recent_limit:10}`；直调同参）。
- 观测（异常 / 崩溃点）：**无异常、无错误消息、无崩溃点**（`degraded=[]`、`truncated=false`、budget 1200 未触发裁剪）。`recent_len=3`，texts=`['会话A的第二句话','会话B的第一句话','会话A的第一句话']`（两入口读数一致）——**不存在的会话拿到全会话窗口**（修后目标 `recent==[]`）。
- 站点：`md_cg/mdcos.py:3309`（改前，③ 段 `evs=…` 不传会话）；`pack['recent']` 组装 `:3310-3312`；根因面 `:5142`（`recent_events` 无 session 形参）/ 基类 `md_cg/mdcg.py:3040-3050`（无任何会话过滤）。

**腿②（缺陷② · 会话 A 的续接包混入会话 B 报文，含多实例并发形态）**
- payload：库②（同腿① 三事件态）；`session_recall(session='session-AAA')`；另以同 root 另开第二实例 `MdCGSecure(root, principal=Principal(session='session-AAA'))` 再读（模拟多窗口/多会话并发）。
- 观测（异常 / 崩溃点）：**无异常、无崩溃点**；`recent_len=3`，3 条中混入他会话报文 `『会话B的第一句话』`；多实例形态读数相同（3 条含 B）。
- 站点：同腿①。

**腿③（缺陷③ · 会话 B 的续接包混入会话 A 报文）**
- payload：库②（同腿① 三事件态）；`session_recall(session='session-BBB')`。
- 观测（异常 / 崩溃点）：**无异常、无崩溃点**；`recent_len=3`，含会话 A 两条（`『会话A的第二句话』『会话A的第一句话』`）。
- 站点：同腿①。

**腿④（缺陷④ · 指定会话下「缺 meta.session」的无归属事件未被丢弃，应丢弃）**
- payload：库②（在 3 条会话事件之外）追加第 4 条经 `MdCG.remember_event(cg,'user','【无归属】本条事件 meta 中无 session 字段',meta={})` **直写基类路径**的事件（绕过 `MdCGSecure.remember_event` 的 setdefault，模拟无归属事件）；读 `session='session-AAA'` 与 `session='session-BBB'` 两形态。
- 观测（异常 / 崩溃点）：**无异常、无崩溃点**；两会话下 `recent_len=4`，均含该无归属事件（raw 窗口读数 `meta.session=null`）——修前完全不丢。
- 站点：`:3309`（改前无过滤）；写路径 `MdCGSecure.remember_event`（改后 `md_cg/mdcos.py:5080-5091`，`setdefault("session")` 在 `:5087`；无归属事件来自历史数据/直写形态）。

**腿⑤（旁证 · 同一次 session_recall 返回包内段间矛盾）**
- payload：库③（在 3 条会话事件外）＋ `session_note('要点A：本会话在做甲任务', session='session-AAA')` + `session_note('要点B：本会话在做乙任务', session='session-BBB')`；`session_recall(session='session-AAA')`；另同库同数据 `session_compact(session='session-AAA', limit=40)`。
- 观测（异常 / 崩溃点）：**无异常、无崩溃点**。notes 段只回 A 要点（`tags=['session','session:session-AAA']`，B 要点不在）；同一次调用的 recent 段 3 条含 B——**同一返回包内，① 段已隔离、③ 段未隔离**。同族对照 `session_compact(session='session-AAA')` events=2、摘要只含 A（正确过滤）。
- 站点：对照面 `md_cg/mdcos.py:3205-3206`（`_session_notes` 按 `session:{sid}` 过滤）、`:3384-3386`（改前 `session_compact` 按 `meta.session` 过滤，改后 `:3407-3409`）vs `:3309`（改前 recent 段无过滤）。

**腿⑥（登记腿 · `recall(include_recent=True)` 的近期事件尾巴同样不吃 session——判定登记不回）**
- payload：`cg.recall('会话要点', session='session-AAA', include_recent=True, recent_limit=10, budget_tokens=4000)`。
- 观测（异常 / 崩溃点）：**无异常、无崩溃点**；recent 尾巴 3 条含 `『会话B的第一句话』`——同类缺口事实成立；属**显式开关面**、非本 issue 修复目标，按 ask 口径如实登记、本轮不修（见 §七）。
- 站点：`md_cg/mdcos.py:1951-1960`（`:1952` 调 `self.recent_events(limit=…)` 不传会话；`recent_events` 亦无 session 形参）。

**腿⑦（对照基线 · `session='*'` 与 `session=None` → 全局 3 条；非缺陷）**
- payload：库②（三事件态）；`session_recall(session='*')`；`session_recall(session=None)`。
- 观测（异常 / 崩溃点）：两者 `recent_len=3`（全部事件）——`'*'` 修后语义即不过滤、`None` 修后退回旧行为，与修前读数一致，**不构成缺陷**（`reproduced=false`，作为语义矩阵完整性读数记录）。**无异常、无崩溃点**。
- 站点：`:3309`（该段修前不区分这两种输入）。

### 2.2 实施员探针（〔本报告实跑〕隔离库五事件）

**探针（库①）**：`%TEMP%/issue65_probe.py`（系统临时目录，非仓内件），在**合成隔离库**建五条事件：`A1/A2 ∈ session-AAA-0000`、`B1 ∈ session-BBBB-0000`、`N0` **缺 `meta.session`**、`AX ∈ session-AAA-0000-long`（A 的**前缀延伸**，用于钉「严格相等」）。命令：`PYTHONPATH=<仓根> python -X utf8 %TEMP%/issue65_probe.py 修前`。

| session 入参 | 修前 recent（MdCGOS 基类 / MdCGSecure 生产形态） |
|---|---|
| `'session-zzzz-nope-0000'`（假 id） | **5 条**：`['AX','N0','B1','A2','A1']` ← 最直观证据 |
| `'session-AAA-0000'`（A） | **5 条**，混入 `B1`（B 会话报文） |
| `'session-BBBB-0000'`（B） | 5 条（含 A 的两条） |
| `'*'` / `None` / `''` | 5 条 |
| 缺 `meta.session` 的 `N0` 在 `session=A` 下 | **可见**（`True`） |

旁证（同库同跑，修前即为正确形态）：`session_compact(session=A)=2 ｜ (B)=1 ｜ (None)=5`——同族过滤在役，缺陷只在 ③ 段。

**与编排侧读数对拍**：编排侧（三事件分属 A/B）读数为「假 id → 3 条、A → 混入 B、None/"*" → 全局 3 条」；本探针五事件下同形（假 id → 5 条、A → 混入 `B1`、None/"*" → 全局 5 条），**方向与形态逐项一致**，差异仅在事件条数（探针事件数不同）。

---

## 三、修法（照契约实现，逐点声明）

**契约来源与存放位置（r1 补）**：本报告所称「契约」= 本工作流的 `contract` 运行参数——定义原文「设计者裁决的修复契约：缺陷定义 + 必须怎么修 + 不许动什么（会原样进实施员与复现员的 ask）」（工作流真源 `.zcode/workflow-drafts/issue65-修复session_recall-近期事件段会话隔离.dwf.ts:15-18`），随 ask 原样下发给复现/实施/复核三方（同文件 `:104/:123/:141`）。**参数取值不落仓**（运行时注入），故仓内**无契约原文可附**。文本内可核对的契约转记面有三处：① §5.1 的契约条目对照表（R65.1–R65.7）；② 本节的修法两条——可与工作区源码 `md_cg/mdcos.py:3331-3332` 逐字对照；③ 不许动清单——可用 `git status --porcelain` 与 `git diff --stat` 核对（只两件 `M`）。「与契约一致／未削弱契约」诸断言的核对方式即上述三面；若需契约原文附录，须向工作流主会话索取该运行参数值。

**1）③ 段过滤**（`md_cg/mdcos.py:3331-3332`，取 `evs` 之后、组装 `pack["recent"]` 之前）：

```python
            if session and str(session).strip() != "*":
                evs = [r for r in evs if (r.get("meta") or {}).get("session") == session]
```

形态与契约给的两行**逐字一致**（仅缩进随所处 `try` 块）。语义矩阵：真值且非 `"*"` → 只回本会话（`meta.session` **严格相等**；缺 `meta.session` 的事件被丢弃——最坏空窗口，杜绝错块）；显式 `"*"` → 不过滤（跨会话汇总合法用法，与 stg 面 `view_session` 的 `"*"` 同款）；falsy（`None`/`""`）→ 退回旧行为（全局窗口，存量调用面零迁移）；`strip()` 防空白包裹的 `"*"`。

**2）生效条件注释**（本仓惯例：`md_cg/mdcos.py:3234`）追加 ③ 段口径条款（含边界：「会话要点段的 tags 过滤与台账段的不过滤口径不变」）。

**3）docstring**（`md_cg/mdcos.py:3247-3254`）新增「会话口径（issue #65）」段：写明 **③ recent 段跟会话走**、`"*"` = 跨会话汇总、falsy 退回全局窗口，并点明口径分工——① 会话要点段本就按 `session:{sid}` tag 过滤；目标段与任务段是**有意跨会话**的工程面。

**不许动清单遵守**（逐条）：`session_compact` 既有过滤、`_session_notes`、`recent_events` 本体（改前 L5142 → 改后 `md_cg/mdcos.py:5165`）、`recall(include_recent)`（`md_cg/mdcos.py:1952`「近期事件尾巴」，行号未漂移）、`src/hooks.ts` —— **均零改动**（`git status` 只两件 `M`；`recall` 尾巴的判定登记不回见 §七）。

---

## 四、修后行为矩阵（〔本报告实跑〕，同探针同库）

| session 入参 | 修后 MdCGOS（基类） | 判据 |
|---|---|---|
| `'session-zzzz-nope-0000'` | **0 条 `[]`** | 杜绝错块（空窗口） |
| `'session-AAA-0000'` | **2 条** `['A2','A1']` | 只含 A；不含 B、不含裸事件、不含前缀延伸会话 |
| `'session-BBBB-0000'` | **1 条** `['B1']` | 只含 B |
| `'*'` | 5 条（全局） | 显式跨会话汇总 |
| `' * '` | 5 条（全局） | strip 判据 |
| `None` | 5 条（全局） | falsy 退回旧行为 |
| `''` | 5 条（全局） | falsy |
| 裸事件 `N0` 在 `session=A` 下 | **不可见**（`False`）/ 在 `None` 下 **可见**（`True`） | 缺 `meta.session` 丢弃；非指定会话照旧 |
| `session_compact(A/B/None)` | `2 / 1 / 5` | 回归：既有过滤不受影响 |

**生产形态补充（诚实口径 · 库①）**：`MdCGSecure` 实例下 `session=A` 读到 **3 条** = `A1`、`A2` ＋ 裸事件 `N0`——原因是**写侧** `MdCGSecure.remember_event`（改后 `md_cg/mdcos.py:5087`）在写入时对缺会话者 `setdefault("session", principal.session)`，探针的裸事件被**归属成 A**；读侧语义不变（仍严格相等过滤）。即：经安全档写入的事件天然带会话归属，读侧丢弃面只覆盖**存量数据 / 非安全档直写**形态（契约要求的「不许漏」正是为此）。

**勿与 §6.2 库④ 的 2 条混淆（r1 补）**：库④ 的安全档读数 `['A1','N0']` 也是「本会话标记事件＋被归属的裸事件」同构，但只有 **1 条** A 会话标记事件——3 条 vs 2 条的差在**库构成**（库① 的 A 会话有 `A1`/`A2` 两条），不在实现行为。

---

## 五、守卫、定点变异自证与 ANCHOR-MISS

**落点**：扩既有 `md_cg/test_p45_session_identity.py`（30 断言 → **42**），新 R65 组（`md_cg/test_p45_session_identity.py:245-462`，读码口径：R65 分节自 `:245` 起、`_r65_self_proof()` 于 `:462` 结束）。

### 5.1 断言清单（12 条）与契约对照

| 断言 | 契约条目 | 说明 |
|---|---|---|
| R65.1 假会话 id → `recent == []` | R65.1 | 空窗口，杜绝错块 |
| R65.2 会话 A → 恰为 A 的两条 | R65.2 | 用 `AX`（A 的**前缀延伸**会话）把「严格相等」与「前缀/子串匹配」区分开 |
| R65.3 会话 B → 恰为 B 的一条 | R65.3 | — |
| R65.4a `session="*"` → 全局 | R65.4 | 不过滤 |
| R65.4b `session=" * "` → 全局 | （细分子项） | strip 判据的判别力腿 |
| R65.5a/5b `None` / `""` → 全局 | R65.5 | 契约 R65.5 的两态拆成两条，便于变异定点 |
| R65.6a/6b 缺 `meta.session`：指定会话下丢弃 / 非指定会话照旧可见 | R65.6 | 契约的两半，拆成两条 |
| R65.7 `session_compact(A)` 仍只压 A | R65.7 | 回归腿（既有过滤不受影响） |
| R65.8 文档口径在位 | （扩展） | docstring 含「段跟会话走」「跨会话汇总」，且 `def` 上方「生效条件」注释含过滤条款 |
| R65.9 MCP 入口端到端 | （扩展） | 经 `mcp_server._session_call` 走 `action=recall`：本会话只回本会话、假 id 空窗口 |

> **偏离声明（r1 更正）**：契约清单为 R65.1–R65.7。本守卫相对契约的变化分两类：**新增判据 3 条**——R65.4b（strip 判据判别力）、R65.8（文档口径）、R65.9（MCP 端到端），为**加严**；**两态拆分 2 处**——R65.5→5a/5b、R65.6→6a/6b，**覆盖强度与未拆时相同**（拆分本身不加严），其价值在使变异定点可指认、判别力可见。合计 12 条；**零删减**（未削弱契约任一条）；每条都有定点变异钉住（下表）。

### 5.2 正向读数（〔本报告实跑〕）

```
python -X utf8 -m md_cg.test_p45_session_identity        → 通过 42 / 失败 0，退出码 0
python -X utf8 -m md_cg.test_p45_session_identity --self-proof → 六腿全 PASS，退出码 0
```

### 5.3 定点变异自证（`--self-proof`）读数

模式口径：**就地变异运行中的实现源码**（`inspect.getsource` → dedent → `exec` → 临时替换 `MdCGOS.session_recall` → 跑 R65 组 → 复原），**不读 git**（绑提交做基线会在下一次改动即失效，本仓已有两次教训）；每条腿声明**期望红项集合**，实跑红项必须**恰好相等**（多红=断言语义纠缠，少红=该判据空转）。

| 腿 | 变异 | 锚点 | 实跑红项 | 期望 | 判定 |
|---|---|---|---|---|---|
| ① | 删整段会话过滤（回到全进程窗口） | 两行整块 | **5**：R65.1/2/3/6a/**R65.9** | 5 | PASS |
| ② | 删 `"*"` 例外（星号也过滤） | `if session and … != "*":` | **2**：R65.4a / R65.4b | 2 | PASS |
| ③ | 去 `strip`（`" * "` 不再按汇总） | `str(session).strip() != "*"` | **1**：R65.4b | 1 | PASS |
| ④ | 缺 `meta.session` 改 fail-open（放行） | 过滤行 | **4**：R65.1/2/3/6a | 4 | PASS |
| ⑤ | 去 falsy 守卫（`None`/`""` 也过滤） | `if session and …` | **2**：R65.5a / R65.5b | 2 | PASS |
| ⑥ | 文档口径回退（docstring 反转） | `段跟会话走` | **1**：R65.8 | 1 | PASS |

- **未变异基线**：红项 **0**（防「变异模式自己就红」）。
- **复原后重跑全套（A–G + R65）**：退出码 **0（全绿）**。
- **签名区分度**：① 与 ④ 的差恰在 `R65.9`（MCP 腿库内无裸事件，fail-open 不影响它）——即每条腿的红项集合是**唯一指纹**。
- **一处修正如实记录**：变异④ 首跑实红 4 项、期望集先写为 2 项（漏算「fail-open 会让裸事件混进任一按会话腿」）——按实跑修正期望为 4 项并加注理由，**不是**改断言迎合读数（断言自始未动）。

### 5.4 ANCHOR-MISS 与退出码口径（fail-closed）

- 锚点自检：每条锚点在实现源码里**命中次数必须恰为 1**；否则打印 `ANCHOR-MISS 锚点漂移（命中 N 次，期望恰好 1）` 并**退出码 2**（正常跑与自证模式皆然）。
- 〔本报告实跑〕漂移探针（进程内把 `inspect.getsource` 替换为「把锚点句改写」的版本，**不动仓内件**）：输出 `ANCHOR-MISS … '段跟会话走'`，`main()` 返回值 **2** ✔。
- 退出码：`0` 全绿 ｜ `1` 断言失败 ｜ `2` 锚点漂移（优先于 1）。

---

## 六、独立复核（ACCEPT）与它列出的未覆盖面

**判定：ACCEPT**——依据 = **四态判定单 ① PASS ② PASS ③ PASS ④ PASS**，issue65 修复成立。复核的全部判定依据均在复核 ask 内**亲手执行**：只读仓库 + `%TEMP%` 合成库；**未编辑任何工作区文件、未 git add/commit/push**（实验根 `%TEMP%\rev65_issue65` 用毕已删）。

**复核环境**（〔工作流采集〕）：改前实现取真源 `git archive HEAD md_cg data utf8_boot.py` 解到 `%TEMP%`（首次漏 `utf8_boot.py` 致改前守卫 ImportError，补入后跑通——复核如实记录为己方探针环境的准备问题）；**改前树无** `if session and str(session).strip() != "*":` 行、**现行树有**；`mdcos.py` sha256 前16：改前 `8bb2e878c411bb48` / 现行 `62e5ff193c492e5b`〔撰写员复算现行值一致〕。

### 6.1 四态判定单（复核独立读数）

**① 修前各腿输入在现行树 + 退化路径可判定 → PASS**

- 自写驱动 `rev65_driver.py`（对 old/new 两树各起子进程、2 个独立合成库 + 独立 oracle）→ ALL PASS：现行树 **11 个输入 × 2 库**全部无异常，且返回**事件短标签集合**（r1 定义：每个返回事件的**文本前 2 字**，口径同守卫 `_r65_recent` 的 `[:2]`，`md_cg/test_p45_session_identity.py:292`；**与另两处「前缀」用法无关**——§2.2 的 `AX` 是**会话 id** 的前缀延伸会话、`'session-AAA'` 是**会话 id** 的真前缀，均非事件文本标签）**== 独立 oracle**（oracle = 标准库 `json` 直读 `<store>\_recent.jsonl` 按题设语义算出的短标签集合：FAKE→`[]`、A→`['A1','A2']`、AX→`['AX']`、B→`['B1']`、`'session-AAA'`（A 的真前缀）→`[]`、`' session-AAA-0000 '`→`[]`、`'*'`/`' * '`/`' \t* '`/None/`''`→全 5 条）。
- 退化非空池空转判据：4 次运行 `raw_count==5` 全 PASS（库非空而非空转）；裸事件 N0 在 A 下不可见、在 None 下可见（两向钉死）。
- 改前实现同库旁证：A / B / FAKE / None **全部返回 5 条**（含 B1 混入）——**缺陷实存**。

**② 合法输入逐位对照 → PASS**

- old vs new 同库逐位：recent 段 JSON **全等**（`None`/`''`/`'*'`/`' * '`/`' \t* '` × 2 库）、整包（None 输入）JSON 全等、`session_compact` 读数全等 `{A:2, B:1, None:5}`。
- `recent_events` 签名两树均为 `(limit, roles, since, newest_first)`、**无 session 形参**——证修复只能落 `session_recall` ③ 段（与 §一「本 issue 面内缺口唯一」一致）。

**③ 守卫本体 + 变异自证 + 删断言探针 → PASS**

- 改前树同命令 `python -X utf8 -m md_cg.test_p45_session_identity` → rc 0、**30/0**（「30 断言 → 42」成立）；现行树 **42/0**（§5.2，〔撰写员复跑一致〕）。
- 复核自写 `rev65_mutation_sets.py` 收集每腿红项**集合**：①`{R65.1,R65.2,R65.3,R65.6a,R65.9}` ②`{R65.4a,R65.4b}` ③`{R65.4b}` ④`{R65.1,R65.2,R65.3,R65.6a}` ⑤`{R65.5a,R65.5b}` ⑥`{R65.8}`——逐条与声明期望**恰好相等**；①/④ 差恰为 `R65.9`（指纹唯一）；还原后红项 ∅。
- 删断言探针 `rev65_delassert.py`（内存拦 `check`、不改文件）：对照组 rc 0；删 `R65.4b` → rc 1（腿②③转红）；删 `R65.6a` → rc 1（腿①④）；删整组 `R65.*` → 六腿全红 rc 1（「删断言后自证必红」成立）。
- 退出码三态进程级实测：断言失败 → 41/1、rc 1；漂移+断言全假 → rc 2 且 **0 条 `[FAIL]`**（**2 优先于 1**）。

**④ 不得静默可观测面（ANCHOR-MISS fail-closed）→ PASS**

- 漂移探针经 `runpy` 走守卫真实 `__main__` 退出码映射：clean rc 0；`drift_doc`（进程内改写 `inspect.getsource`）→ 打印 `ANCHOR-MISS 锚点漂移（命中 0 次，期望恰好 1）：'段跟会话走'`，正常与 `--self-proof` 两模式均 rc 2；`drift_dup`（锚点块复制成 2 次）→ 打印 3 条「命中 2 次」+ rc 2（>1 也拦）。
- 守卫文件 grep 无 `subprocess`/`git` 调用 →「基线 = 运行中源码、不读 git」成立。

### 6.2 交叉核验与仓库无痕（复核）

- 生产形态（**库④**，`MdCGSecure` + MCP）：A→`['A1','N0']`（= A 会话**一条**标记事件 `A1` ＋ 裸事件被**写侧** `setdefault` 归属 A，`mdcos.py:5087`；与 §四 库① 的 3 条差在库构成，见 §四 注）、FAKE→`[]`、`'*'`→4 条；存量裸事件 L0（绕过 Secure 直写、`meta.session=null`）在 A 下被丢弃——契约「缺 `meta.session` 丢弃」方向正确。
- 全仓调用点清点：生产面仅 `md_cg/mcp_server.py:2864` 与 `scripts/sync_zcode_session.py:330` 调 `MdCGOS.session_recall`，**均传 session**；`md_cg/whitebox_kb/aeis_core/api.py:900` 为同名异法（AEIS 适配器，签名 `session_recall(session_id, query, limit)`）；TS 侧 `src/lib/mdcg_client.ts:351` 透传 session、`src/hooks.ts:658` 传 `sid`——**无漏传点**。〔撰写员补充清点：另有测试面调用（`md_cg/test_lifecycle_retire_leak.py:317`、`md_cg/test_n202_session_notes_visibility.py:234`、`md_cg/test_tasks.py:241` 等，均为测试用）；`scripts/zcode_compact_hook.py:18` 仅注释提及〕
- 行号口径与报告一致：`recent_events` 改前 5142 / 现 5165；③ 段 `evs` 改前 3309 / 现 3318；`compact` 的 `if session:` 改前 3384 / 现 3407〔撰写员以 `git show HEAD:md_cg/mdcos.py` 与工作树读码逐条复核，见 §一/§三〕。
- 仓库无痕：复核前后 `git status --porcelain` **逐字一致**（两 `M` + 一 `??`）、`git diff --stat` 25/253、274 插入不变、`mdcos.py` 哈希复核前后一致〔撰写员复跑 `git status`/`git diff --stat` 读数一致〕。

### 6.3 复核列出的未覆盖面（uncovered）

1. **`recall(include_recent=True)` 的近期事件尾巴**（`md_cg/mdcos.py:1951-1960`）：复核确认「该段调 `self.recent_events(limit=…)`（`:1952`）**不传会话**、因而不过滤」——事实成立，但属显式开关面、非本 issue 目标，**登记不回**（与 §2.1 腿⑥同口径）。〔r1 更正：`recall` 本体**有** `session` 形参（`:1850`）——「确无会话参数」原字样易被读成 recall 无 session；该面若修不需动签名，见 §七-1〕
2. **`src/lib/mdcg_client.ts` 的「不按 session 过滤（服务端事实）」注释**（该 docstring 内「两条服务端事实」块，核心句 `:343-344`）：复核确认**仍在**（本轮未改，如实登记）——修后此句已成漂移源，待主会话收口时同步（见 §七-2）。
3. 复核四态判定覆盖面为**修复本体与守卫**；容器两栈、python 全量等跨面读数不在四态内（见 §八，另标来源）。

---

## 七、未采纳 / 登记项

1. **`recall(include_recent)` 的「近期事件尾巴」（`md_cg/mdcos.py:1951-1960`，`:1952` 调 `self.recent_events(limit=…)` 不传会话）判定登记不回**（契约明示）：该面是 read/recall 的**显式开关**（`include_recent=True` 才取）。**r1 更正（原稿此处有误）**：`recall` 本体**接收 `session` 形参**（`md_cg/mdcos.py:1850`；`use_rrf` 分支把它传给候选层，`:1882`），只是尾部段未把它下传给 `recent_events`（该函数无 session 形参，§一）——**即该面可修，且修法与 ③ 段同款：一行调用点过滤即可，不需动签名**；原稿「无会话参数可用（签名里没有 session）／需动 read op 的签名与调用面」不成立，特此更正。按 ask 口径（显式开关面、非本 issue 修复目标）登记留池，**本轮未修**；是否另开 issue 一次收口（防新调用点重演同类静默混入）属主会话决策——本轮未创建跟踪件。
2. **`src/lib/mdcg_client.ts:342-344` 注释已成漂移源（不在授权改动面内，登记待同步）**：该处把**修前**行为写成「服务端事实」——「① `recent` 段取 `recent_events(limit=recent_limit)` —— **不按 session 过滤**」。修后此句反了。因契约「不许动」清单把改动面锁在 `md_cg/mdcos.py` / 守卫 / 报告三处，**本次未改 TS 注释**；建议主会话收口时同步。
   **同源注释盘点与同步动作归属（r1 补）**：该句另有一份**编译产物**副本 `lib/lib/mdcg_client.d.ts:212-214`（`npm run build` 自真源再生——改真源后重新构建即同步，**不必手改产物**）；除上述产物副本外全仓无第三处（盘点含 `src/` 测试面——无钉住该注释的断言）。仓内其余「不按 session 过滤」字样（`md_cg/mdcos.py:3245/3292`、`md_cg/test_tasks.py:7`）指**任务台账段的有意跨会话口径**（正确、非漂移）。同步动作由**主会话收口**执行（工作流真源 `.zcode/workflow-drafts/issue65-…dwf.ts:3/:244` 明示「提交与 `npm run gate` 留主会话收口」）。
3. **行为面影响（需对外说明——本节即该说明的落点）**：DSH 侧「【本会话近期对话】」块（`src/hooks.ts:658` → `formatSessionWindow`，定义 `:384-406`）此前实际拿到的是**全进程窗口**（跨会话混入），修后才是**本会话**窗口。三个边界（r1 补全，均读码核实）：
   - **非空面**：DSH 写侧每轮把 user/assistant 消息以 `{session: sid}` 写进窗口（`src/hooks.ts:698/772`），故本会话**已有窗口写入**时该块照常非空。
   - **下界面**：若本会话尚无窗口条目（如新会话首轮）或条目全为空文本（`formatSessionWindow` 只收非空 preview，`:395`），返回空串 → **整块不注入**（`:660` 的 `if (winText)`）。即行为变化 =「有内容但可能是他会话」→「本会话内容**或无块**」——原稿「照常非空」未覆盖此下界，r1 更正。
   - **`sid` 为空面（依据更正）**：读侧调用传的是 `sid`（`:658`），未观测到会话时 `sessionIdOf` 返回**空串**（`:416-420`；注释 `:413-415`「空串在上游一律等同『不分会话』（退回旧行为）」）→ `sessionRecall('')` falsy → 退回**全局窗口**（旧行为）。**注意：这与写侧兜底常量不是同一个值**——写侧此时标 `UNASSIGNED_SESSION = 'unassigned'`（**非空**，`src/lib/session_state.ts:37`；`src/hooks.ts:698`）。原稿把两者写成同一来源、读者无法判断常量取值——r1 更正为「依据是 `sessionIdOf` 的空串约定，而非 `UNASSIGNED_SESSION` 等于空串」。由此还产生一档既有（修前即如此、本轮未动）的口径差：`sid` 空时读侧取**全局**、而写侧标 `'unassigned'`——该桶事件在全局读下可见、在任何指定会话读下不可见。
4. **本守卫相对契约的清单变化**（R65.4b/5a/5b/6a/6b/8/9）见 §五 偏离声明——**新增 3 条**（R65.4b/8/9，加严）、**拆分 2 处**（R65.5/6，覆盖强度不变）、**零删减**（r1 更正：原「只加不减」把拆分说成了加严）。

---

## 八、验证读数与范围（逐条命令）

| 项 | 命令 | 读数 |
|---|---|---|
| 修前复现 | `PYTHONPATH=<仓根> python -X utf8 %TEMP%/issue65_probe.py 修前` | 假 id/A/B 均 5 条；裸事件在 `session=A` 下可见（§二） |
| 修后矩阵 | 同探针 `… 修后` | 0 / 2 / 1 / 5 / 5 / 5 / 5；裸事件 A 下不可见（§四） |
| 守卫正向 | `python -X utf8 -m md_cg.test_p45_session_identity` | **42 通过 / 0 失败**，退出码 0 |
| 变异自证 | `python -X utf8 -m md_cg.test_p45_session_identity --self-proof` | 六腿逐条 **恰好**命中期望红项；复原后全套 rc 0；退出码 0 |
| ANCHOR-MISS | 进程内漂移探针（见 §5.4） | `ANCHOR-MISS` ＋ 返回值 **2** |
| 定向回归（ask 指定范围） | `python -X utf8 scripts/run_tests.py md_cg` | **249/249 通过，3 跳过**，退出码 0 |
| python 全量 | `python -X utf8 scripts/run_tests.py`（无参） | **359/359 通过、5 跳过（依赖缺失/平台不符）**，退出码 0（〔工作流采集〕与〔本报告实跑〕复跑一致） |
| 容器栈一（rust:bookworm） | `docker run --rm -v <仓根>:/work -w /work rust:bookworm bash scripts/linux_verify.sh full`（用法行 `scripts/linux_verify.sh:3`；python 全量＋断言判别力自证＋smoke 22/0＋body_e2e_smoke） | 〔工作流采集〕`结果: 22 pass / 0 fail`、`[PASS] smoke_test (linux)`、`=== 汇总: 49 pass / 0 fail ===`，**退出码 0** |
| 容器栈二（node:22-bookworm） | `npm install --include=dev && npm run build && node --import tsx --test test/*.test.ts`（口径见 `docs/eval/发布14_身体×脑组合_v1.0.md:133-134`） | 〔工作流采集〕TS 144 项 **141 通过 / 0 失败 / 3 跳过**；`# cancelled 0 ｜ # skipped 3 ｜ # todo 0 ｜ # duration_ms 12224.823459`，**退出码 0** |
| 单点复核（ask 点名的三个面） | `python -X utf8 -m md_cg.test_lifecycle_retire_leak` / `-m md_cg.test_n202_session_notes_visibility` / `-m md_cg.test_p45_session_identity` | 46/0、36/0、42/0（全 rc 0） |
| 改动面 | `git status --porcelain` | `M md_cg/mdcos.py`、`M md_cg/test_p45_session_identity.py`（＋本报告新增） |

**未跑（如实声明）**：`npm run gate`、提交与推送——按工作流真源（`.zcode/workflow-drafts/issue65-…dwf.ts:3`「提交与 npm run gate 留主会话收口」、`:244`）**由主会话执行**，本工作流不含该步。**来源声明**：python 全量与容器两栈由**工作流脚本阶段**实跑（脚本 `:159-208`；实施/复核两 ask 均明示「不要跑全量与容器——脚本随后会跑」，故实施回报中的「未跑」与本表不矛盾）。本报告撰写 ask 实跑了守卫正向与变异自证（§5.2）与 python 全量（SUMMARY 359/359、5 跳过、退出码 0，与脚本读数一致）；**未重跑**容器两栈与 gate。

**硬边界遵守**：未动任何在役数据根（全部读数取自系统临时目录合成库）；未 `git add/commit/push`；未改 `data/policy.json`；未削弱任何 forbidden 规则。

---

## 九、残留风险

1. **空窗口面**：指定会话时，`meta.session` 缺失的事件一律不可见（契约：最坏空窗口优于错块）。命中条件 = 写侧未打会话标记的**存量/跨进程**事件；本仓三处写侧（DSH `hooks.ts:698/772`、MCP/安全档 `mdcos.py:5087` setdefault、zcode sync）均已打点，故**估计**现役数据面风险≈0。**「≈0」的量化边界（r1 补）**：本报告**未对现役库做盘点**——该估计的依据只有两条：①三处写侧代码事实；②复核实测存量裸事件在指定会话下被丢弃（§6.2）。若需确数，须对在役数据根执行一次「缺 `meta.session` 事件」盘点（本轮未做）。若未来出现新的写入通道，**须同样打 `meta.session`**（否则该通道的报文对本会话不可见）。
2. **`"*"` 的传播面**：`"*"` 是「显式跨会话汇总」的**唯一**开关，与 falsy 语义相反；二者已写进 docstring 与生效条件注释，但**客户端（TS）尚未声明**该口径（见 §七-2/3）——建议随注释同步一并补齐。

---

## 十、读者反馈处置（v1.0 → v1.0-r1）

读者（未参与本次修复）只读 v1.0 后给出 5 条 unclear / 6 条 unsupported / 7 条 nextQuestions；本节逐条处置，落点用 r1 章节号引用。**本轮修订只改本报告文件**（`git status --porcelain` 仍为两件 `M` + 本报告），新增证据全部来自读码（引用处已就地标注）。

### 10.1 unclear（读不懂）——5 条

| # | 反馈要点 | 处置（落点） |
|---|---|---|
| 1 | §6.1① 「返回前缀集合」未定义；与「前缀延伸会话」「真前缀」字面相近 | 改称**事件短标签集合**并给定义（文本前 2 字，同守卫 `[:2]`），注明与另两处**会话 id**「前缀」用法无关（§6.1①） |
| 2 | §七-3 由 `sessionTag = {session: UNASSIGNED_SESSION}` 推 `sessionRecall('')`，未证明常量是空串 | **依据更正**：常量实为 `'unassigned'`（非空，`src/lib/session_state.ts:37`）；但**读侧传的是 `sid`**（`sessionIdOf` 空值＝空串，`src/hooks.ts:416-420`）——结论（空→退回全局窗口）不变，依据改正（§七-3） |
| 3 | 结论段两套计数压缩：9 个编号指 12 条；ANCHOR-MISS 易读成六腿之一 | 拆分表述：「R65.1–R65.9 编号、12 条（4/5/6 拆两态）」；ANCHOR-MISS 明标**不在六腿之内**（结论段、§5.4） |
| 4 | §一「缺口唯一」与腿⑥「同类缺口成立」并读范围不明 | 显式限定「**限本 issue 面内**」＋就地给出边界（§一） |
| 5 | 同一批标签多库复用；A 会话读数散见 5/2/3/2 条无库标注 | 补**库清单（库①–④）**；各读数标库号；3 条 vs 2 条差异归因库构成（§2.1 表、§四 注、§6.2） |

### 10.2 unsupported（文本自身支撑不了）——6 条

| # | 反馈要点 | 处置（落点） |
|---|---|---|
| 1 | 「契约」原文未随报告给出，「与契约一致／未削弱契约」无从核对 | 补**契约来源与存放位置**：契约＝工作流 `contract` 运行参数（真源 `.zcode/workflow-drafts/issue65-…dwf.ts:15-18`，取值不落仓）；给出三处**可核对转记面**（§三 首段） |
| 2 | 「均为加严」把 3 条新增与 3 处拆分混为一谈（「只加不减」同此） | 更正为两类：**新增 3 条＝加严 / 拆分 2 处＝覆盖强度不变 / 零删减**（§5.1 偏离声明、§七-4） |
| 3 | 「recall 无会话参数／需动签名」与腿⑥ payload（recall 收了 session）矛盾 | **更正**：`recall` 本体有 `session` 形参（`md_cg/mdcos.py:1850`）；该面可修、**不需动签名**；原措辞有误（§七-1、§6.3-1） |
| 4 | 「写侧打点 ⇒ 照常非空」未覆盖下界面 | 补**三边界**：非空面／下界面（本会话无窗口条目→整块不注入，`src/hooks.ts:660`）／空 `sid` 面（§七-3） |
| 5 | 危害链「被压缩检查点记入」无证据位 | 补**两条代码链**：注入面 `src/hooks.ts:663-667`；压缩重建面 `zcode_compact_hook.py:67-71 → sync_zcode_session.py:330,344-351`；并明标「运行时混入未观测」（§一） |
| 6 | §九-1「风险≈0」无量化依据，与承认存量裸事件并存 | 明标**未盘点**、依据仅两条；确数须对在役库盘点（§九-1） |

### 10.3 nextQuestions（读者会接着问）——7 条

| # | 问题 | 答复／落点 |
|---|---|---|
| 1 | 契约原文能否附录 | §三 首段：取值不落仓；附录须向主会话索取运行参数值 |
| 2 | TS 注释谁同步、`src/` 侧口径、别处是否同源 | §七-2：另有产物副本 `lib/lib/mdcg_client.d.ts:212-214`（`npm run build` 再生）；全仓无第三处（含测试面）；由**主会话收口** |
| 3 | gate 与提交/推送由谁、何时执行 | §八 末段：工作流真源 `:3/:244` 明示**留主会话收口**；本工作流不含该步 |
| 4 | recall 尾部是否另开 issue、是否一次收口 | §七-1：本轮**未创建跟踪件**，属主会话决策；修法已明确（一行调用点过滤、不动签名），可随该 issue 一次收口 |
| 5 | 复核驱动已删，日后如何复现 | 守卫正向/自证**可随时重跑**（命令见 §5.2）；复核自写驱动（`rev65_*.py`）与实验根已删、**未落仓**——原路径不可重放，需按 §6.1/§6.2 判据重写驱动 |
| 6 | falsy 静默退回全局是否有告警/审计 | **无告警/审计计划**（本轮未加）——falsy 为存量兼容面；如需收窄或告警须另立需求 |
| 7 | DSH 块说明写在哪里、由谁出 | §七-3（本报告该节即说明落点，随报告对外） |

**未采纳的读者意见**：无——18 条全部有对应处置（其中 4 条为**事实性更正**：10.1-2（结论依据换正）、10.2-2（「均加严」改两类）、10.2-3（`recall` 签名）、10.2-4（照常非空补下界）；其余为补证据/补定义/补限定，非仅措辞）。
