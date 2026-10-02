# issue50-e · 读面保护只认显式来源（`is_protected` 按分分支来源资格闸）——修复工程报告 v1.1

**日期**：2026-10-02（v1.1 同日，按读者反馈逐条修订——处置明细见 **§七**）｜ **缺陷号**：issue50-e ｜ **被测面**：本仓工作树（未提交——1 改 + 1 新增，见文末 git 面）

**关联**：issue50-d（遗忘闸门重要度同源三件套，commit `a33682eb` → `docs/eval/issue50_重要度同源与保护语义_修复记录_v1.0.md`）。issue50-d 在**写侧**收口「落盘=裁决值 · 保护位只认显式声明」；issue50-e 收口其**读侧半边**——issue50-d 报告 §6.2.2 已把「启发式节点落 0.7x 分后读面按分仍认保护」明确列为留池面（**留池** = 列入该报告 §6.2「明确不修而留池」清单、记录在案待后续批次收口的面——本报告 §6.2 沿用此词），本批即该留池项的收口。

**术语速览**（v1.1 增，回应「行话首现无释义」；全部为本仓既有概念，出处随条标注）：

| 术语 | 释义 |
|---|---|
| **打位** | 给节点 frontmatter 写入 `protected=True`（+ `protection_reason`）保护位——写侧自动保护动作（`md_cg/mdcg.py:2453-2455`）；「只落分、不打位」= 落 importance 分数但不写保护位 |
| **裁决面** | 遗忘闸门 `forgetting.assess` 的裁决输出（verdict + reason，写入时点）——issue50-d 已按 `imp["from"]` 分叉文案 |
| **判定面 / 读面** | `protect.is_protected` 的读时判定（读节点时综合层保护/保护位/分数三判据给「是否受保护」）——本批改动点 |
| **留池** | 「明确不修、记录在案、待后续批次或使用者裁定」的事项清单（各报告 §6.2 的固定栏目） |
| **`(adjusted, skipped)`** | `scrub._apply_offset` 的计数二元组：adjusted = 本次实际执行置信度校准写回的节点数、skipped = 因保护/self 层被跳过的节点数（`md_cg/scrub.py:721` `adjusted = skipped = 0` 起的两个累加变量；守卫 A7 断言文案同口径） |
| **0.775 vs 0.78** | **不是同一值**：0.775 是落盘分（`fm.importance`），0.78 是文案里 `f"{imp:.2f}"` 的**显示舍入**（本报告实跑：`f'{0.775:.2f}'` → `'0.78'`）；「importance=0.78≥0.7」= 落盘 0.775 的两位小数显示 |

**证据分级声明**（本报告只写有机械证据的事）：

- 标 **〔本报告实跑〕** = 本报告撰写员在本 ask 内亲手执行并计数；
- 标 **〔工作流采集〕** = 修复工作流（实施段 / 独立复核段）产出，本报告**转录**，不代跑不代补；
- 标 **〔编排侧〕** = 修复编排侧执行、随任务材料传入的输出（python 全量与容器两栈），本报告转录；
- 源码行号**以本报告读码所见为准**：改后行号 = 读工作树核实〔本报告实跑〕；改前行号 = `git show HEAD:md_cg/protect.py`（HEAD=`a33682eb`）核实〔本报告实跑〕。

---

## 一、缺陷定义与真实站点

### 1.1 缺陷定义（一条：读面把写面明确「未落保护」的节点认回受保护）

issue50-d 落盘了启发式真分：`remember_gated` 启发式路径（无 `importance_hint`）过线时，写侧 `add` 的自动保护位被 source 闸拦下（`md_cg/mdcg.py:2453-2455` 第三判据 `and importance_source != "heuristic"`，本报告读码核实〔本报告实跑〕）——**只落分、不打位**，裁决面 reason 同步分叉为 `启发式 0.78≥0.7（未落保护——保护须显式声明）`（0.78 为 0.775 的 `:.2f` 显示舍入，非同值，见文首术语速览）。但读面 `protect.is_protected` 的按分自动保护分支**不看来源**：`imp >= AUTO_PROTECT_IMPORTANCE` 即返回「重要性保护」。后果是同一节点**写面与读面语义单方面分叉**：

- 写面：`importance=0.775`、`importance_source="heuristic"`、`protected` 无位、审计文案「未落保护」；
- 读面：`is_protected == (True, '重要性保护：importance=0.78≥0.7')`——遗忘/降级搬迁闸要求显式 `override` 才能动这条「写面从未声明保护」的节点，`protect.check` 工具读面报 `protected=true`，`stats` 把它计入自动保护类，scrub 净化与 confidence 校准把它当保护节点跳过。

一句话：**issue50-d 的「保护须显式声明」只落在写侧，读侧按分分支把机器推断的重要度重新认回受保护**——裁决面说未落保护、判定面说受保护，两处文案直接矛盾。

### 1.2 真实站点（行号为本报告读码所见）

**改前树（`git show HEAD:md_cg/protect.py`，HEAD=`a33682eb`，本报告实跑核实）**：

| 站点 | 内容 |
|---|---|
| `md_cg/protect.py:149-150` | **缺陷主站点**：按分分支 `if imp >= AUTO_PROTECT_IMPORTANCE:` / `return True, f"重要性保护：importance={imp:.2f}≥{AUTO_PROTECT_IMPORTANCE}"`——无来源判据，任何来源的分数≥0.70 都触发 |
| `md_cg/protect.py:143-144` | 位分支（对照面）：`if fm.get("protected") is True:` 返回 fm 的 `protection_reason`——显式声明路径，本就不看来源，非缺陷 |
| `md_cg/protect.py:262 → :267-268` | 扩散面①`guard_forget`：`:262` 调 `is_protected`、`:267-268` 抛 `ProtectionError`。生产接线：forget 主路径 `md_cg/mdcos.py:2677`、verify falsified `md_cg/mdcg.py:4500`（本报告读码核实） |
| `md_cg/protect.py:274 → :281-282` | 扩散面②`guard_move`：`:274` 调 `is_protected`、`:281-282` 抛 `ProtectionError`。生产接线：`md_cg/mdcg.py:2306`、`md_cg/mdcg.py:4414`（`_move_layer`）、`md_cg/freshness.py:383`（跨层降级注释「走后缀既有 `_move_layer`（内含 protect.guard_move）」，本报告读码核实） |
| `md_cg/protect.py:408 → :413-414` | 扩散面③`stats`：`:408` 调 `is_protected`、`:413-414` 按 reason 串含 `"importance="` 或以 `"重要性保护"` 开头计 `auto_by_importance` |
| `md_cg/protect.py:250` | 对照组（非缺陷面）：`guard_write → is_immutable`，判据只认层/位、**不读 importance**——启发式分数对不可覆盖闸本就无作用 |

**改后树（读工作树核实〔本报告实跑〕）**：见 §3.2 落点表。按分分支移至 `:173-175` 并加来源资格闸；`_fm` 判定面在索引条目侧 `:100` 与回退读文件侧 `:134` 两处带上 `importance_source` 键（缺键读 `None`）。

---

## 二、修前现场（本工作流采集的复现腿）

以下七条腿均为**修复工作流采集**〔工作流采集〕，全部 `reproduced=true`，实验根均为系统临时目录合成库（`tempfile.mkdtemp`），不触在役数据。改前/改后对拍均为「改后副本」实测，非推断。

**实验库构成**（v1.1 增，回应「三个实验库的节点构成各是什么」——全文共出现**三个**不同的合成库，清单如下〔采集材料 + 守卫源码读码，本报告读码核实〕）：

| 库 | 节点构成 | 出处 |
|---|---|---|
| **复现腿库**（腿①-⑦共用，采集原文「同库」字样） | 五节点：`n_heur`（0.775/heuristic/无位，腿①经 `remember_gated` 造）· `n_legacy`（0.85/带位）· `n_legacy_np`（0.85/无键/无位，腿⑥构造：add 直写后手写盘绕开自动打位 + rebuild_index）· `n_hint`（0.9/hint/带位，腿⑦）· `n_self`（层保护） | 腿④ payload 五节点清单 + 腿①②③⑤⑥⑦ payload 的构造描述；**注入时序采集材料未携带**（见腿①注） |
| **守卫夹具库**（§4.1 守卫 F0/E7 等） | 五节点：`a_heur`（0.775/heuristic/无位）· `a_ref`（0.775/无 source 键/无位——同分缺省对照）· `b_legacy`（0.85/无键/无位）· `c_hint`（0.9/hint/位 True）· `d_self`（0.775/heuristic/self 层） | `md_cg/test_i50e_readside_protection.py:103-114,156-173` 夹具注释与构造（本报告读码） |
| **实施段对拍探针库**（§4.2 对拍读数） | **节点清单采集材料未携带**；机械可证其 ≠ 腿④库：腿④库改前 `protected_count=5`，对拍库改前 `=4` ⇒ 两库构成不同 | §4.2 对拍读数 vs 腿④读数（读数不同的两库不可能是同一库） |

### 腿① 读面按分误保护·is_protected（缺陷主腿）

- **payload**：临时库经真实闸门 `MdCGOS.remember_gated('n_heur', doc, layer='contextual', role='tool-output')`：裁决 ACCEPT、`imp={score:0.775, from:'heuristic'}`；fm/索引/盘面三面实测 `importance=0.775`、`importance_source='heuristic'`、`protected=null`（issue50-d 写面语义，裁决面 reason=`'启发式 0.78≥0.7（未落保护——保护须显式声明）'`）。
- **observed**：`protect.is_protected(cg,'n_heur')` 返回 `(True, '重要性保护：importance=0.78≥0.7')`——读面把写面明确「未落保护」的节点认作受保护，与裁决面文案直接矛盾。改后副本对拍（判据语义 = 修复任务指令所载裁定：仅键缺省/None 或 `=='hint'` 可按分触发，即 §3.1 契约）：`n_heur` 的 `is_protected` 读数行变 `(False,'')`；同库其余对照节点行逐字不变（仅 heuristic 行变）。**腿①注**（v1.1 增）：采集原文作「其余三类节点」——按复现腿库构成（§二上表）除 `n_heur` 外为四节点，若按形态类归并（`n_legacy`/`n_legacy_np` 同为 0.85 存量 legacy 形态算一类）恰为三类；该口径采集原文未定义，两种读法均不影响本腿结论（结论只依赖 n_heur 行变、其余行不变两事实），如实照录不代裁。
- **site**：`md_cg/protect.py:149-150`。

### 腿② guard_forget 拦截（缺陷扩散面·遗忘闸）

- **payload**：同腿①启发式节点 `n_heur`；调用 `protect.guard_forget(cg,'n_heur')`（生产接线：forget 主路径 `md_cg/mdcos.py:2677`、verify falsified `md_cg/mdcg.py:4500`）。
- **observed**：抛 `ProtectionError`：`'节点 n_heur 不可遗忘（重要性保护：importance=0.78≥0.7）；删除需显式 override=True'`——节点无法删除，须 override 才能动。改后副本：`guard_forget` 返回 `None`（放行，不再要求 override）。
- **site**：`md_cg/protect.py:267`（经 `:262` is_protected → `:149-150`）。

### 腿③ guard_move 拦截（缺陷扩散面·降级搬迁闸）

- **payload**：同腿①启发式节点 `n_heur`；调用 `protect.guard_move(cg,'n_heur','knowledge')`（生产接线：`mdcg.py:2306/4414` `_move_layer`、`freshness.py:383` 跨层降级）。
- **observed**：抛 `ProtectionError`：`'节点 n_heur 受写保护（重要性保护：importance=0.78≥0.7）；降级移出保护层需显式 override=True'`。改后副本：返回 `None`（放行）。
- **腿③注·层级方向与「降级」措辞**（v1.1 增，回应「contextual→knowledge 为什么叫降级」；本报告读码）：本仓层生命周期以 **knowledge（知识层）→ contextual（假设/情景层）为「降级」方向**（`md_cg/mdcg.py:84-86`「confidence 跌破该值 → 降级为 contextual（假设层）」、`:4537`「层降级 = 生命周期降级（②）：knowledge→contextual 即 state→demoted」、`:4394` `_move_layer` docstring「把节点搬到另一层（可信度降级用）」）——腿③的 contextual→knowledge 是**回升**方向。站点文案「降级移出保护层需显式 override=True」是 `guard_move` 的**固定文案、不随方向变化**：判定只看「is_protected 为真且目标层不在 `PROTECTED_LAYERS` 即拦」（改后 `md_cg/protect.py:296` 生效条件注释、`:302-303` 保护层互搬放行——对当前层与方向均不作判定）；腿③选回升方向触发，恰证明该闸**不区分方向**，凡误判受保护的节点搬往任何非保护层都要求 override。文案字面对回升方向失配，如实标注。
- **site**：`md_cg/protect.py:282`（经 `:274` is_protected → `:149-150`）。

### 腿④ stats 误分类（缺陷扩散面·保护盘点）

- **payload**：同库五节点（`n_heur` 启发式 0.775 无位 / `n_legacy` 直写 0.85 带位 / `n_legacy_np` 存量 0.85 无键无位 / `n_hint` 0.9 带位 / `n_self` 层保护），`protect.stats(cg)`。
- **observed**：改前 `protected_count=5`、`auto_by_importance=4`、`ids=['n_heur','n_legacy','n_legacy_np','n_hint','n_self']`——启发式节点计入自动保护类与 protected_ids。改后副本：`4/3`、ids 去 `n_heur`（启发式退出该类=预期，非回归）；存量/hint 位节点仍在（其 protection_reason 含 `'importance='` 被分类判据计入，非按分分支贡献）。
- **site**：`md_cg/protect.py:413-414`（经 `:408` is_protected → `:149-150`）。

### 腿⑤ guard_overwrite/is_immutable 对照（边界确认·非缺陷面）

- **payload**：同腿①启发式节点 `n_heur` 及全库节点；`protect.guard_overwrite(cg,nid)` 与 `protect.is_immutable(cg,nid)`（guard_overwrite→guard_write→is_immutable，判据不读 importance）。
- **observed**：改前 `guard_overwrite` 全部返回 `None`（放行）、`is_immutable(n_heur)=(False,'')`、仅 `n_self=(True,'层保护：self（不可篡改层）')`——本就不看 importance，无异常可复现（预期行为）；改后副本逐字不变，is_immutable 零变化与层保护零变化均验证成立（ask 边界③ = 修复任务指令边界③「层保护/fm.protected 位/is_immutable 一律不动」，对应 §3.1 边界③）。**此腿为对照，非缺陷复现。**
- **site**：`md_cg/protect.py:250`（guard_write→is_immutable）。

### 腿⑥ 存量无位节点按分保护（语义①边界锚：键缺省=存量一字不变）

- **payload**：`n_legacy_np`：`importance=0.85`、frontmatter **无 `importance_source` 键**、无 fm.protected 位（add 直写后手写盘绕开自动打位 + rebuild_index 构造，等价维护路径调分/外部手写的存量形态），`is_protected`/`guard_forget`/`guard_move` 实测。
- **observed**：改前 `is_protected=(True,'重要性保护：importance=0.85≥0.7')`（真·按分分支形态）、`guard_forget` 抛 `ProtectionError`（文案同腿②形态）、`guard_move` 同类。改后副本（来源资格闸：`_src is None` 视为存量可按分）**is_protected/guard_forget 两读数逐字不变**——存量零回归锚成立。**腿⑥注**（v1.1 增）：第三项 `guard_move` 的改后读数采集原文未单独记录；同形态存量节点（0.85/无键/无位，即守卫 `b_legacy`，与 `n_legacy_np` 形态完全同构）的 `guard_move` 改后**拦且文案同改前**，由守卫 B3 断言钉住（§4.1，本报告实跑 PASS：`PASS B3 guard_move(b_legacy) 拦且文案同改前形态`）——三项结论在文本内齐备。
- **site**：`md_cg/protect.py:149-150`。

### 腿⑦ hint 节点位分支（语义③边界锚：显式声明不受影响）

- **payload**：`n_hint`：`remember_gated(importance_hint=0.9)` → `fm.protected=True`（写侧 `mdcg.py:2453` 自动打位）、`importance_source='hint'`；`is_protected` 实测。
- **observed**：改前 `is_protected=(True,'importance=0.90≥0.7')`——reason 为 fm.protection_reason 形态，证明走 fm.protected 位分支（改前 `protect.py:143-144`）而非按分分支；改后副本逐字不变。另 note：MERGE 强化（`forgetting.reinforce` 置位）与 is_immutable 层保护读数（`n_self` 两读数逐字）均不在改动面。
- **site**：`md_cg/protect.py:143-144`（改前坐标）。

---

## 三、修法契约与落点

### 3.1 契约（使用者裁定 2026-10-02：读面也只认显式来源）

`is_protected` 的按分自动保护**只对「缺省来源（键缺省/None）或显式 hint」的分数生效**；`"heuristic"` 及其它一切显式非 hint 来源不得由分数触发（落到返回 `(False,'')`，除非命中层保护或 fm.protected 位）。三条边界（`md_cg/protect.py:146-156` docstring，本报告读码核实）：

1. **键缺省 = 存量节点**（既有 `cg.add(importance=0.9)` 直写、维护路径调分等从未有过该键）⇒ 行为一字不变——按「缺省即不认」会大规模改变既有保护面，禁止；
2. **"hint" = 显式声明**（写侧对 hint 过线本就打位，按分分支只是其无位形态的兜底），语义不变；
3. **"heuristic" 及其它显式来源不按分**——机器推断的重要度不构成不可遗忘的依据。层保护（`PROTECTED_LAYERS`）、fm.protected 位、`is_immutable` 一律不动；MERGE 强化（`forgetting.reinforce` 跨 0.7 置 `protected=True`）是「重复确认」的显式动作，不经本分支，不受影响。

配套前提：`_fm` 判定面**恒带** `importance_source` 键——「缺键读 None」覆盖**两类条目来源**（v1.1 改写，原句两个并列项字面几乎相同、语义不清；本报告读码核实）：①**现行写入/重建路径**的索引条目——`_node_entry`（`md_cg/mdcg.py:1881` `"importance_source": fm.get("importance_source")`）与 `_stage`（`:2494` 同口径）**恒落该键**，fm 缺省时值为 `None`（add 缺省 None ⇒ 条目键在值为 None）；②**issue50-d 之前的存量索引条目**（旧库）——条目里根本没有该键，`e.get("importance_source")` 同样得 `None`。两路在判定面等价缺省；另有第三路**回退读文件侧**（`protect.py:134` `f2.get("importance_source")`，fm 文件无该键时也得 None，独立复核 C3b/C3d 实证该腿被消费）——`None` 走闸的真分支 ⇒ 存量按分保护零回归由构造保证。

**两套「边界编号」对照**（v1.1 增，回应「边界④是什么」——本报告 §3.1 与 §6.2.3 各引一套 docstring，编号同名不同系）：

| 编号系 | 出处 | 内容 |
|---|---|---|
| **边界①②③**（§3.1 正文所列） | `md_cg/protect.py:146-156`（`is_protected` docstring） | ①键缺省=存量一字不变 ②hint=显式声明语义不变 ③heuristic 及一切显式来源不按分 |
| **守卫 docstring 边界①-⑤**（§6.2.3 所引） | `md_cg/test_i50e_readside_protection.py:19-29`（守卫模块 docstring） | ①-③与左列同义重述；**④** = MERGE 强化（`forgetting.reinforce` 跨 0.7 置 `protected=True`）是「重复确认」的显式动作，不经本分支、不受影响；**⑤** = 不改 `add()` 的写侧 source 闸（issue50-d 已落）、不改遗忘判据、不改检索面；fm 形态零新增字段 |

### 3.2 落点（改后行号 = 本报告读工作树所见〔本报告实跑〕）

| 文件:行号 | 改动 |
|---|---|
| `md_cg/protect.py:85` | `_fm` 生效条件注释同步：`importance_source` 入判定字段（缺键读 None） |
| `md_cg/protect.py:98-100` | `_fm` 判定 dict 增加 `"importance_source": e.get("importance_source")`（索引条目单点；`_node_entry`/`_stage` 恒落该键，issue50-d 已落，老索引条目缺键时 `.get()` 同样得 None、等价缺省） |
| `md_cg/protect.py:134` | `_fm` 回退读文件分支同步 `fm["importance_source"] = f2.get("importance_source")` |
| `md_cg/protect.py:140-157` | `is_protected` docstring：边界①②③成文（存量一字不变 / hint 显式声明 / 显式来源不按分）+ MERGE reinforce 不经此分支的说明 |
| `md_cg/protect.py:170-175` | **修复本体**：按分分支来源资格闸——`:173` `_src = fm.get("importance_source")`，`:174` 判据 `if imp >= AUTO_PROTECT_IMPORTANCE and (_src is None or _src == "hint"):`，`:175` 返回「重要性保护」；heuristic 落 `(False,'')`（生效条件注释 `:138` 同步） |
| `md_cg/test_i50e_readside_protection.py` | **新建守卫**（649 行、53 断言、7 组：F0 夹具自检 / A 启发式面含 A6 同分缺省对照判别锚 / B 存量零回归锚 / C hint 位分支 / D 层保护与 is_immutable 零变化 / E 改前改后对拍锚 / F 调用方枚举与逐类读数），见 §4.1 |

改动面仅此两文件；`forgetting.py`、`mdcg.py`、`mdcos.py`、`scrub.py`、`self_state.py`、`mcp_server.py` 均**零改动**（读侧消费方全部经 `protect.is_protected` 单点生效，见 §4.1 F 组枚举）。

---

## 四、验证数字

### 4.1 新守卫（正向 + 定点变异自证）〔本报告实跑〕

命令 `python -X utf8 -m md_cg.test_i50e_readside_protection`：

- **正向**：锚点自检 PASS（banned 缺陷形态「无闸按分分支」+ required 新判据锚点；**不以 git HEAD 为基线源**）；**53 通过 / 0 失败 / exit 0**。七组内容：F0 夹具自检（四类节点确实落在契约形态上）、A 启发式面（A1 `is_protected(a_heur)==(False,'')`、A2/A3 遗忘/搬迁放行、A4 覆写恒真锚、A5 check 读面 false、**A6 同分缺省对照 a_ref 逐字同改前——判别力锚：A1 的 False 是「来源」导致而非分数/形态导致**、A7 scrub 不再 skip `(1,0)`、A8 stats 0/0/[]）、B 存量零回归锚（六断言 reason 逐字同改前）、C hint 位分支（五断言）、D 层保护与 is_immutable 零变化（D5 静态源码零改动 + **D6/D7 既有守卫 `test_p9_forget_protect`/`test_i50d_importance_source` 子进程不改断言跑通 rc=0**）、E 对拍锚（变列确实变 + 不变列逐字同 + E8 改前探针字面）、F 调用方枚举（**4 文件、非注释/非 def 的 `is_protected(` 调用恰 7 处**：guard_forget/guard_move/stats、`mcp_server._protect_call` action=check、`scrub.apply` skip_protected 与 `_apply_offset` skip、`self_state.check` 8 保护一致）+ 逐类读数行。
- **`--mutate`**：未变异基线红 0；3 处定点变异红项**全部恰好命中预期表**，exit 0：

| 变异 | 红项数 | 命中 | 红项构成（守卫 `_SRC_MUTATIONS` 表注释 + 实跑输出） |
|---|---|---|---|
| m1「把 heuristic 也认保护」 | **11** | ✓ | A1/A2/A3/A5/A7/A8（启发式读数面 6）+ E1/E2/E3（a_heur 行变列锚）+ E7（stats 聚合）+ F2 a_heur 行；存量/对照/位面全不红——闸只加宽 heuristic 一态，恰证语义按来源分叉 |
| m2「把缺省键也判不认」（禁用缺陷形态） | **10** | ✓ | A6（同分缺省对照）+ B1/B2/B3/B5/B6（存量零回归锚 5）+ E4/E6（b_legacy 行两格）+ E7 + F2 b_legacy 行；B4/E5 走 guard_overwrite 不红（该闸不认分） |
| m3「按分整支删除」 | **10** | ✓ | 与 m2 **同构成**（守卫 `_SRC_MUTATIONS` 注释 + 实跑），逐项列全（v1.1 增）：**A 侧 1 项** = A6（同分缺省对照——按分分支删除后 `a_ref` 读数变 `(False,'')`；A1-A5/A7/A8 不红，启发式行改后本就 False/放行，整支删除不改变其读数，A6 对照断言正是为此设）；**B 侧 5 项** = B1/B2/B3/B5/B6（B4 走 guard_overwrite 不红）；**E 侧 3 项** = E4/E6（b_legacy 行两格）+ E7（stats 聚合）；**F 侧 1 项** = F2 b_legacy 行。合计 1+5+3+1=10；c_hint/d_self 行、a_heur 变列行（E1/E2/E3、F2 a_heur）均不红 |

实施期修正记录〔工作流采集〕：m1 初稿预期 9、实测 11（漏数 E2/E3），已按实测修正 expected 与注释——预期表为实测字面量，非推算。

**变异与锚点的机械性质**（守卫源码 `:513-596`，本报告读码核实〔本报告实跑〕）：变异一律作用在**当前盘实现**上（`inspect.getsource` + 字面替换 + `exec`，不落盘不改源文件）；锚点必须逐字在位，漂移报 `ANCHOR-MISS` 并 **exit 2（fail-closed）**，默认模式同样先跑锚点自检。

### 4.2 回归面与全量

| 检查 | 数字 | 级别 |
|---|---|---|
| 新守卫正向 | 53 通过 / 0 失败 / rc=0 | 〔本报告实跑〕 |
| 新守卫 `--mutate` | 基线红 0，红项 11/10/10 全命中 / rc=0 | 〔本报告实跑〕 |
| 保护族逐项（rc=0）：`test_p9_forget_protect` 37/0 · `test_p9c_dedup_hints` 31/0 · `test_i50b_defer_to_review_queue` 34/0 · `test_i50c_meta_passthrough` 30/0 · `test_i50d_importance_source` 32/0（`--mutate` PASS）· `test_m3_h9_bucket_health_protect_mark` 31/0 · `test_m3_h9_semantic_guard` 41/0 · `test_p16_self_state` 51/0 · `test_n212_n213_n224_generation_gates` 42/0 · `test_p10_identity` 24/0 | 合计 rc=0 | 〔工作流采集〕；其中 p9 与 i50d 两项另经 D6/D7 子进程在本报告实跑中验证 rc=0 |
| 定向套件 `python -X utf8 scripts/run_tests.py md_cg` | 227/227 通过、3 跳过（依赖缺失/平台不符）/ rc=0 | 〔工作流采集〕 |
| **python 全量** `python -X utf8 scripts/run_tests.py` | **304/304 通过，5 跳过**（依赖缺失/平台不符）/ **rc=0**（输出摘要含 `PASS md_cg.test_time_core_lint` 与 `===== SUMMARY 304/304 通过，5 跳过 =====`） | 〔编排侧〕 |
| **容器栈一** | **退出码 0**（输出摘要：`结果: 22 pass / 0 fail`｜`[PASS] smoke_test (linux)`｜`=== 汇总: 38 pass / 0 fail ===`） | 〔编排侧〕 |
| **容器栈二** | **退出码 0**（输出摘要：`# cancelled 0`｜`# skipped 3`｜`# todo 0`｜`# duration_ms 11624.688286`） | 〔编排侧〕 |

**三段分工如实记录**：实施段声明「未跑：全量 run_tests.py 与容器双栈（按任务约定留编排侧；工作流环境无容器，如实记未跑）」〔工作流采集〕；python 全量与容器两栈随后由**编排侧**执行并通过（上表末三行〔编排侧〕）。本报告环节未复跑全量与容器（只写一个文件的硬边界 + 无容器环境），其数字不标〔本报告实跑〕。

**容器两栈读数口径**（v1.1 增，回应「两个数字什么关系」「栈二跑的是什么、多少用例、如何知道它过了」）：

- **两栈的既定命令**（本仓发版门禁，`README.md:584-589`，本报告读码〔本报告实跑〕）：**栈一** = `rust:bookworm bash scripts/linux_verify.sh full`（rust + python 全量含全部守卫 + smoke 端到端）；**栈二** = `node:22-bookworm bash -c "npm install --include=dev && npm run build && node --import tsx --test test/*.test.ts"`（发布件 TS 编译 + node test）。编排侧材料**未声明其所用命令是否即此**——本报告只转录其输出摘要与退出码，不代指。
- **栈一「22 pass / 0 fail」与「38 pass / 0 fail」的关系**：前者按输出行序先于 smoke 行、后者标「汇总」——形态上与「阶段计数 → 全脚本汇总」相容（README 称栈一含 cargo test / python 18 套 / smoke 端到端多阶段），但**阶段构成采集材料未携带**，22 是否 38 的子阶段计数本报告不代裁；机械事实只有三条：两行均 **0 fail**、smoke 行 `[PASS] (linux)`、退出码 0。
- **栈二**：跑的是 node 生态（README 栈二命令含 `npm run build` + `node --import tsx --test test/*.test.ts`；`test/` 目录下现有 **20 个** `.test.ts` 文件，本报告实跑 glob 计数）；输出字段（`# cancelled/# skipped/# todo/# duration_ms`）与 node:test 摘要格式同构，但**编排侧摘要未含 `# pass`/`# fail` 计数行**——用例总数与通过数材料未携带，不代补。能确证的机械事实：退出码 0 且 `cancelled 0 / skipped 3 / todo 0`——node:test 失败用例不止于摘要（编排侧仅传此摘要，不代补其未传的字段）；「栈二过了」在本报告内的依据 = **退出码 0** 这一机械事实 + 摘要内无 fail/cancelled 非 0 项，如实表述为「退出码 0、摘要无失败项」而非「全部通过」。

**改前/改后对拍**〔工作流采集〕：改前/改后探针（隔离临时根合成库）确认**仅 heuristic 行变**——`is_protected` True→False、`guard_forget`/`guard_move` 拦→放、`check.protected` true→false、`stats` `protected_count` 4→3 / `auto` 3→2、`scrub._apply_offset` `(0,1)`→`(1,0)`——记号 = `(adjusted, skipped)`（adjusted=本次执行校准写回的节点数、skipped=因保护跳过的节点数，`md_cg/scrub.py:721` 变量名；改前启发式节点被当保护节点 skip，改后被校准，「机器推断重要度不再免疫净化校准」即此）；**该对拍库 ≠ 腿④复现腿库**（改前 `protected_count` 4 vs 5，机械不同库；两库构成见 §二「实验库构成」表）；存量 0.85 无键与 hint 位节点 reason 逐字不变；`guard_overwrite` 三类均放行不变。

### 4.3 独立复核的对拍（复核段实测，两树等价性）〔工作流采集〕

**编号体系声明**（v1.1 增）：本节出现的 B1-B7、C1-C4d、A2-A4 等编号是**复核探针自身**的组/断言编号，与本报告 §4.1 守卫七组（F0/A-F）**同名不同系**——守卫 B 组=存量零回归锚、C 组=hint 位分支；复核的 B1-B7=两树对拍项、C 组=退化/容错腿。两套编号无对应关系，对照时以节为单位、不跨节混读。

- **独立 oracle 逐字对拍**：复核自写 oracle（三元优先级 + 来源闸，输入取盘上 frontmatter）vs 实现：42 节点多形态池（layer × importance 7 形态 × source 4 形态 × 位面）× `is_protected`/`is_immutable` 共 **84 项全逐字一致（含 reason 串）**。**「source 4 形态」的构成**（v1.1 增）：具名可确证的是 None（缺省）/`"hint"`/`"heuristic"` 三种；**第 4 种形态采集材料未点名**（仅以「3 个 review 节点」侧面出现于复核口径修正记录），本报告不代补其取值——第 4 形态在「显式非 hint 来源」命题上的读面实证由本报告探针补跑（见下）。
- **改前实现 vs 改后同库对拍**：改前实现（`git show HEAD:md_cg/protect.py`，即 `a33682eb` 版，`exec` 加载为独立模块）在**同一库**与改后六面对拍（is_protected/guard_forget/guard_move/guard_overwrite/is_immutable/check）——差异集合**恰等于**预期分叉集合（显式非 hint 来源、无位、过线、非保护层共 7 节点）；`guard_overwrite`/`is_immutable` 零差异；`stats` 差异键恰 `{protected_count, auto_by_importance, ids, by_layer}` 且退出计数==分叉数（B1-B7 PASS）。
- **退化/容错/回退腿实证**（探针1 C 组，**25/25 PASS rc=0**）：C2a 老索引条目 pop 掉 `importance_source` 键后 `_fm` 仍恒带键读 None（不 KeyError）；C2b/C2c 0.75 缺键节点仍按分保护且与改前读数逐字同；**C3a 对 `cg.get` 加 spy 证明 `_fm` 内回退读文件腿被实际调用**（calls 非空，非「没抛异常」式判据），C3b/C3c/C3d 文件 fm 改 hint/删键后 `_fm` 读数跟着变（消费文件值，非死代码）；C1 ghost 节点改前/改后均 `(False,'')`；C4a `'abc'`/C4b None 按容错 0.0 不崩、C4c 字符串 `'0.9'` float 可转按分保护；A2-A4 stats 的 ids/by_layer/auto_by_importance/immutable_ids 与复核独立扫描重算**逐位相等**。
- **「不得静默」可观测面（fail-closed 实证）**：在仓库临时副本（20.3MB，含 `md_cg`+`utf8_boot.py`，工作区未触）上改 `protect.py`：V1 缺陷回归形态（banned 锚重现）→ 默认与 `--mutate` 两模式均打 ANCHOR-MISS 三类齐报（变异锚点缺失/缺陷形态回归/新判据锚点缺失）+ rc=2；V2 语义等价但字面漂移（`((_src is None) or (_src == "hint"))`）→ 同样 ANCHOR-MISS rc=2（**实现改了没同步表即红，不看语义等价**）；V0 副本未改基线 rc=0 无误报（副本上 53 断言亦全过）。
- **删断言探针（自证不可造假）**：内存改 `_GROUPS` 组表（零文件改动）：P-A 删 `g_a` → m1 红 5≠11、m2/m3 红 9≠10 → 自证 FAIL rc=1；P-B 删 `g_e` → 三变异全失配（7/7/7）→ FAIL rc=1；对照 P-C 删 `g_f0`（零红项贡献组）→ 11/10/10 不变仍 PASS rc=0——**红项数机制精确对应断言贡献，非总数敏感的假阳性**。
- **本报告探针补证·显式来源各形态的读面/写面分工**（v1.1 增，隔离临时合成库，`MdCG.add` 直写，跑完清理〔本报告实跑〕）——回应「第 4 种 source 形态从未被点名」与「一切显式非 hint 来源收口」的精确命题：
  - **探针一**（0.9 过线 × 5 形态）：缺省 `None` → 写侧**自动打位**（issue50-d 写侧闸只排 heuristic，`mdcg.py:2453-2455`）→ `is_protected=(True,'importance=0.90≥0.7')`（**位分支**）；`"hint"` → 同上打位走位分支；`"heuristic"` → **不打位** → `(False,'')`（按分分支被本批闸拦）；任意显式串 `"manual"`、`"x"` → **写侧照打位**（≠heuristic 即打）→ `(True,'importance=0.90≥0.7')`（位分支）。
  - **探针二**（同上两节点手工删位，得「显式来源但无位」的纯按分形态）：`"manual"` 无位 → `(False,'')`（按分分支不认任意显式非 hint 串——不止 heuristic）；`"hint"` 无位 → `(True,'重要性保护：importance=0.90≥0.7')`（按分分支兜底，reason 形态区别于位分支）。
  - **精确命题**：本批收口的是**读面按分分支**——「显式非 hint 来源的**分数**不得触发按分保护」；**不是**「显式非 hint 来源一律不受保护」——`"manual"` 等经 issue50-d 写侧闸照样自动打位、走位分支受保护（探针一实证）。§3.1 契约句「除非命中层保护或 fm.protected 位」的限定即为此分工；oracle 对拍（84 项逐字一致）的输入取盘上 frontmatter，位形态一并入池，两口径自洽。

---

## 五、独立复核判定与它列出的 uncovered

**判定：ACCEPT**〔工作流采集〕。依据（复核自述）：全部在系统临时目录合成库独立复现（TEMP 前缀 `i50e_recheck_*`，跑完已清理），**不采信执行者自述**；工作区零写入、零 git 写操作（`git status` 与会话起始逐字一致：`M md_cg/protect.py` + `?? .zcode/` + `?? md_cg/test_i50e_readside_protection.py`）。四组依据见 §4.3（C 组容错腿 / oracle 与两树对拍 / 守卫与变异独立跑 / fail-closed 实证）。

**uncovered 情况（如实）**：本批独立复核的采集记录**未单列 uncovered 名目**——对照的 **T1 是 issue50-d 复核具名的唯一 uncovered 名目**（issue50-d 报告 §五：「T1（MERGE/DROP 分支的传导效应）：复核实测 MERGE/DROP 分支行为两树一致，唯 T1 传导效应除外」——指 MERGE/DROP 两个裁决分支在两树间的传导效应，其展开正文在 issue50-d 采集材料中未随传、只有名目）。本批「无对应物」的含义**只限**：本批复核记录没有具名任何 uncovered 事项；这**不自动等于**复核全覆盖（未具名也可能是复核未列，不必然是复核穷尽），故本报告仍将复核文本明示的边界与口径事项如实转录如下、不代补：

1. **复核探针自身的一次口径修正**（复核段记录）：第一版探针预期只算 heuristic，导致 3 个 review 节点出现「多余」差异；把判据改为 `src not in (None,'hint')` 后全绿——恰证实现按「**一切显式非 hint 来源**」收口，比『只认 heuristic』更贴 docstring 语义③，独立 oracle 同口径逐字吻合。这是复核侧对自身预期的修正记录，非被测物缺陷。
2. **变异红项覆盖面的结构性边界**：m2/m3 下 B4/E5（guard_overwrite 面）不红——该闸走 `is_immutable` 不读分，本就不在缺陷面（§1.2 对照组 + 守卫 `_SRC_MUTATIONS` 注释）。
3. **实施段未跑面**：全量 run_tests.py 与容器双栈按任务约定留编排侧（§4.2 已由编排侧补跑，退出码均 0）。

---

## 六、边界与未覆盖（含本轮明确不修而留池的面）

**硬边界遵守情况**：本批只动 `md_cg/protect.py`、新增 `md_cg/test_i50e_readside_protection.py`；**未** add/commit/push，未触在役数据根。本报告撰写员只新增本文档一个文件：落盘前 `git status --porcelain` 实测为 ` M md_cg/protect.py` + `?? .zcode/` + `?? md_cg/test_i50e_readside_protection.py`（与工作流起始快照逐字一致）〔本报告实跑〕；落盘后终态仅多出本文档这 1 个未跟踪文件（文末附核实）。全文无明文凭据。

### 6.1 语义外延（读码核实〔本报告实跑〕）

资格闸判据是 `_src is None or _src == "hint"`（`protect.py:174`），**不是** `_src == "heuristic"` 的黑名单——即收口对象是「一切显式非 hint 来源」：未来新增任何 source 值自动落入「显式来源不按分」；若某显式来源确需按分保护，须走显式打位路径（fm.protected 位）。独立复核 §4.3 的 oracle 对拍（42 节点 × source 4 形态全逐字一致）即按此口径验证。

### 6.2 明确不修而留池 / 确认不动的面

1. **`stats.auto_by_importance` 的分类判据是 reason 字符串匹配**（改后 `md_cg/protect.py:438-439` `if "importance=" in why or why.startswith("重要性保护")`）：它数的是「reason 形如重要性按分/位打标」，不是「按分分支本次命中」——hint 位节点（fm `protection_reason='importance=0.90≥0.7'` 经位分支返回）与存量按分节点都会被计入 auto（腿④ 实测记录：「存量/hint 位节点仍在，其 protection_reason 含 'importance=' 被分类判据计入，非按分分支贡献」）。字符串粗分类的口径本批不动，如需精确口径须另立批次。
2. **`guard_overwrite` / `is_immutable` / `guard_write` 判据不读 importance 与来源**（「不可遗忘 ≠ 不可覆盖」的设计，`protect.py:22-29` 模块注释）：启发式分数对不可覆盖闸本就无作用；本批按对照腿⑤确认零变化，**不改**。
3. **写侧 add source 闸**（`mdcg.py:2453-2455`，issue50-d 已落）、**裁决面 `forgetting.assess`**、**检索面**：零改动（**守卫模块 docstring 边界⑤**，`md_cg/test_i50e_readside_protection.py:28-29`——编号对照见 §3.1：「不改 add() 的写侧 source 闸、不改遗忘判据、不改检索面；fm 形态零新增字段」）。
4. **MERGE 强化**（`forgetting.reinforce` 跨 0.7 置 `protected=True`）：「重复确认」的显式动作，不经按分分支，不受影响（`protect.py:154-156` docstring；腿⑦ note）。
5. **读侧 7 处调用方全部经 `protect.is_protected` 单点同闸生效**（F 组枚举 4 文件 7 处，§4.1）：`mcp_server.py` / `scrub.py` / `self_state.py` 的行为变化（check 读 false、净化与校准不再 skip）是本修复的**预期传导**，不是独立改动面；新增调用方须同步守卫 F 组枚举表（F1+ 断言钉住完备性）。
6. **容器两栈的复跑**：本报告环节无容器环境，未复跑；数字采编排侧（§4.2）。

---

## 七、v1.1 修订记录（读者反馈逐条处置）

| # | 反馈（类别） | 处置 | 落点 |
|---|---|---|---|
| 1 | 三实验库节点构成（question） | 补「实验库构成」表：复现腿库五节点（n_*）/守卫夹具库五节点（a_*，守卫源码读码）/对拍探针库（清单采集材料未携带；机械证其≠腿④库：改前 protected_count 4 vs 5）；对拍段加交叉引用。「仅 heuristic 行变」的库归属照录 | §二表、§4.2 |
| 2 | contextual→knowledge 为何叫「降级」（question） | 补腿③注：knowledge→contextual 为本仓降级方向（mdcg.py:84-86/:4537/:4394 读码）；腿③为回升方向；guard_move 文案固定不随方向、判定不看方向——字面失配如实标注 | §二腿③注 |
| 3 | 0.775 与 0.78 是否同值（question） | 实跑 `f'{0.775:.2f}'` → `'0.78'`：**非同值**，0.78 是 `:.2f` 显示舍入；术语速览条目 + §1.1 括注 | 术语速览、§1.1 |
| 4 | 容器栈一 22/38 关系；栈二跑什么、多少用例、何以知过（question） | 补「容器两栈读数口径」：README.md:584-589 两栈命令（读码）；22 与 38 的阶段关系材料未携带**不代裁**（机械事实=两行均 0 fail+rc 0）；栈二按 README 命令形态跑 node test、`test/*.test.ts` 实跑 glob 计 **20 文件**、pass/fail 计数行材料未携带**不代补**；「栈二过了」表述收敛为「退出码 0 且摘要无失败项」 | §4.2 |
| 5 | 边界④是什么（question） | 补两套 docstring 编号对照表：protect.py is_protected 边界①②③ vs 守卫模块 docstring 边界①-⑤（④=MERGE reinforce 不经本分支、⑤=不改写侧/遗忘/检索面，全文列出）；§6.2.3 引用改全称带行号 | §3.1 表、§6.2.3 |
| 6 | T1 是什么、本批无它算好算坏（question） | 补 T1 全称与出处（issue50-d 复核唯一 uncovered 名目=MERGE/DROP 分支传导效应，issue50-d 报告 §五）；「本批无对应物」语义限定为「复核记录未具名任何 uncovered，不自动等于全覆盖」 | §五 |
| 7 | `.zcode/` 是什么、终态盘点里算什么（question） | 补说明段：`os.walk` 实测为宿主 ZCode 工作目录（workflows/workflow-drafts/workflow-runs/plans）；角色=宿主会话产物、**非本批修复产物**、起始快照已在；清理/入库归使用者 | 附 |
| 8 | 「ask 语义」未定义（unclear） | 定义为「修复任务指令（编排下发的修复 ask）所载裁定」；腿⑤「ask 语义③」改写为「ask 边界③=层保护/位/is_immutable 不动，对应 §3.1 边界③」 | §二腿①、腿⑤ |
| 9 | 腿①「其余三类节点」「该行」指代断裂（unclear） | 「该行」改明确指称（n_heur 的 is_protected 读数行）；加腿①注：「三类」按形态类归并（两 legacy 节点并一类）可自洽，口径采集原文未定义，两种读法均不影响结论，如实照录不代裁 | §二腿① |
| 10 | 「索引条目缺键与老索引条目缺键」字面重复（unclear） | 配套前提改写为两类条目来源 + 第三路文件侧：①现行 `_node_entry`（mdcg.py:1881）/`_stage`（:2494）恒落键、值可 None；②issue50-d 前存量条目无键、`.get()` 得 None；③回退读文件 `f2.get` 同 None（C3b/C3d 实证消费）——本报告读码核实 | §3.1 配套前提 |
| 11 | m3 红项构成未列全（unclear） | m3 行逐项列全 10 项（A 侧 1：A6；B 侧 5：B1/B2/B3/B5/B6；E 侧 3：E4/E6/E7；F 侧 1：F2 b_legacy 行）+ 不红面说明（与 m2 同构成，守卫注释口径） | §4.1 表 |
| 12 | 两套 A/B/C 编号撞名（unclear） | §4.3 开头加编号体系声明：复核探针编号（B1-B7/C1-C4d/A2-A4）与守卫七组（F0/A-F）同名不同系、无对应关系 | §4.3 |
| 13 | `(1,0)/(0,1)` 记号无解释（unclear） | 术语速览条目（`(adjusted, skipped)`，scrub.py:721 变量名：执行校准写回数/因保护跳过数）+ §4.2 对拍段内联定义 | 术语速览、§4.2 |
| 14 | 行话首现无释义（unclear） | 加「术语速览」块（打位/裁决面/判定面/留池/(adjusted,skipped)/0.775 vs 0.78 六条，各带出处）；引言「留池」首现处内联释义 | 引言、§二 |
| 15 | 腿⑥第三项 guard_move 改后读数缺失（unsupported） | 如实标注采集缺项；补同形态锚：`n_legacy_np` 与守卫 `b_legacy`（0.85/无键/无位）完全同构，其 `guard_move` 改后拦且文案同改前由守卫 B3 钉住（本报告实跑 PASS，输出原文引录）——三项结论文本内齐备 | §二腿⑥注 |
| 16 | 「source 4 形态」第 4 种未点名（unsupported） | §4.3 oracle 条如实声明第 4 形态取值材料未点名、不代补；补本报告两探针实证（隔离临时库，跑完清理）：探针一 5 形态（None/hint/heuristic/manual/x）——写侧只排 heuristic 故 manual/x 照打位走位分支；探针二删位后纯按分形态——manual `(False,'')`、hint 按分兜底 True；命题收窄为「**读面按分分支**不认显式非 hint 分数」，与 §3.1「除非命中层保护或位」限定自洽 | §4.3 补证条 |

**材料缺、如实不代补清单**（本轮新增的「不代补」事项汇总）：对拍探针库节点清单（#1）、腿①「三类」口径（#9）、容器 22/38 阶段关系与栈二 pass/fail 计数（#4）、oracle 第 4 形态取值（#16）。

---

## 附：git 面（本报告终末核实〔本报告实跑〕）

修复批次工作树（与本工作流起始快照一致，落盘前实测）：

```
 M md_cg/protect.py
?? .zcode/
?? md_cg/test_i50e_readside_protection.py
```

本文档落盘后终态在此之上仅多 1 个未跟踪文件：`?? docs/eval/issue50_读面保护只认显式来源_修复记录_v1.0.md`。未 add / 未 commit / 未 push。本文为唯一被修改文档；全文无明文凭据。

**`.zcode/` 是什么**（v1.1 增，回应「它是工作流临时目录还是该被清理的杂物」）：是 **ZCode 宿主（承载本修复工作流与本报告撰写工作流的会话环境）的工作目录**——本报告 `os.walk` 实测其内容为 `workflows/`（工作流定义 `lingshu-defect-fix.dwf.ts`）、`workflow-drafts/`（历史工作流草稿 `*.dwf.ts`，含 issue50 系列各批）、`workflow-runs/`（运行记录 `dwfeval-*.mjs`/`dwfrun-*.mjs`）、`plans/`（会话计划 `plan-sess_*.md`）〔本报告实跑〕。角色：**宿主会话产物、非本批修复产物**——它在本工作流起始快照中已在（issue50-d 批次同样列出），故 git 面声明「与起始快照逐字一致」把它原样计入；终态盘点「仅多 1 个文件」只对**本报告撰写环节**的增量而言。是否清理/入库归使用者，本报告不代裁、只声明「非本批产物、起点已在」。
