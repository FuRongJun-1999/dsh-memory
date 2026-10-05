# issue50-d · 遗忘闸门重要度同源与保护语义（落盘=裁决值 · 保护位只认显式声明 · 审计文案分叉）——修复工程报告 v1.0-r1

**日期**：2026-10-02（v1.0-r1 同日，按读者反馈逐条修订——处置明细见 **§七**）｜ **缺陷号**：issue50-d ｜ **被测面**：`<仓根>` 工作树（未提交——4 改 + 1 新增，见文末 git 面）

**关联**：issue50-a（半重复 DEFER 结构性不可达 → `docs/eval/issue50_半重复待定复核_修复记录_v1.0.md`）· issue50-b（DEFER 出口接线 → `docs/eval/issue50_待定复核入队_修复记录_v1.0.md`）· issue50-c（DEFER 元数据透传与 node_id 兜底 → `docs/eval/issue50_元数据透传与兜底_修复记录_v1.0.md`）。issue50-d 是遗忘闸门三问裁决中「重要度一问」的收口：**审计面文案、落盘分、保护位三者首次同源一致**。

**先补「三问」定义**（v1.0-r1 增，出处 `md_cg/forgetting.py:21-39` 模块 docstring，本报告读码〔本报告实跑〕）：

> 遗忘闸门 = 写入情景层记忆前的三问筛选（`forgetting.assess`，`md_cg/forgetting.py:240`），四态裁决 ACCEPT 写入 / MERGE 并入既有 / DROP 丢弃 / DEFER 待定：
>
> - **Q1 重复？** `redundancy` = 新内容被既有同层节点覆盖的最大比例（bigram 覆盖率）；
> - **Q2 重要？** `importance` = 显式 `importance_hint` 优先，否则启发式（新奇 / 来源 / 长度三因子，公式见 §2 腿①注）——**本批修的就是这一问的落盘与文案**；
> - **Q3 惊奇？** `self_info` = −log2(dup+ε)（bit，代理量，非香农熵）。
>
> 裁决顺序（顺序即语义）：① 重要度 ≥0.7 → ACCEPT（保护优先）→ ② 确定性内部产生且冗余 → DROP → ③ 冗余 ≥0.85 → MERGE → ④ 半重复且未触发保护 → DEFER → ⑤ 重要度 ≥0.30 → ACCEPT → ⑥ 新信息 ≥0.15 → ACCEPT → ⑦ 其余 → DEFER。

**证据分级声明**（本报告只写有机械证据的事）：

- 标 **〔本报告实跑〕** = 本报告撰写员在本 ask 内亲手执行并计数；
- 标 **〔工作流采集〕** = 修复工作流（实施段 / 独立复核段）产出，本报告**转录**，不代跑不代补；
- 源码行号**以本报告读码所见为准**：改后行号 = 读工作树核实；改前行号 = `git show HEAD:md_cg/<file>` 读 HEAD 树核实（本报告执行）。

---

## 一、缺陷定义与真实站点

### 1.1 缺陷定义（一对同源缺陷 + 一条通道事实）

遗忘闸门 `forgetting.assess` 的重要度一问（Q2），**裁决面**算出了区分度良好的分（启发式 0.775/0.88 量级），但**落盘面**把区分信息全部丢掉，并且**审计文案在声称未发生的事**：

| # | 缺陷 | 一句话定义 |
|---|---|---|
| ① | 审计面文案与落盘状态背离 | 启发式路径（不传 `importance_hint`）过线时，裁决 `reason` 同样输出「重要度 …（触发不可遗忘保护）」，但落盘 `importance=0.5`（默认）且无保护位——审计面在声称落盘面未发生的保护 |
| ② | 落盘重要度是常数 | 启发式裁决值（0.775/0.88 互不相同）落盘一律 0.5；插件缺省通道落盘恒等于声明常数（0.6）——**门禁算出的分在落盘瞬间全部丢弃**，落盘重要度不携带任何区分信息 |

缺陷②的下游含义（F 组只读验证，见 §2 腿④）：排序消费的是**落盘值**——落盘恒常数时，破序键全库并列退化到 id 序、0.775 本应进入的 freshness 刷新档（importance ≥0.7，见 §2 腿④注的阈值指名）对 0.5 永不生效、兜底池序失真。

### 1.2 真实站点（行号为本报告读码所见）

**改前树（`git show HEAD:` 核实）**：

| 站点 | 内容 |
|---|---|
| `md_cg/forgetting.py:308-309` | 保护分支 `verdict, why = "ACCEPT", (f"重要度 {imp['score']:.2f}≥{PROTECT_IMPORTANCE}" f"（触发不可遗忘保护）")`——reason 不分叉 `imp["from"]`，启发式过线同样声称「触发不可遗忘保护」（缺陷①文案侧） |
| `md_cg/mdcos.py:3706-3707` | ACCEPT 分支 `if hint is not None and "importance" not in kw: kw["importance"] = hint`——启发式路径 `hint=None` 整段不触发，裁决值 `imp["score"]` 就在 `out["gate"]` 里却不落盘（缺陷②成因主环） |
| `md_cg/mdcg.py:2042` | `add` 签名 `importance: float = 0.5`——回落默认值的出处 |
| `md_cg/mdcg.py:2438-2442` | 自动保护位 `if (float(importance or 0.0) >= protect.AUTO_PROTECT_IMPORTANCE and not fm.get("protected")):`——只看落盘那个 0.5，`<0.7` 不打位（缺陷①落盘侧） |

**两个保护常量同值**（v1.0-r1 增，本报告读码核实）：裁决面用 `PROTECT_IMPORTANCE = 0.70`（`md_cg/forgetting.py:62`），落盘面用 `AUTO_PROTECT_IMPORTANCE = 0.70`（`md_cg/protect.py:46`）——**两个模块各自定义、数值同为 0.7**，跨模块同一口径（`forgetting.py:256-257` 注释亦声明与 writelimit 对齐）。另有第三个同值阈值：`REFRESH_PARAMS["rehearsal_threshold"] = 0.7`（`md_cg/freshness.py:97`，freshness 刷新乘子档）——三处同值、**语义不同面**（裁决保护线 / 落盘保护位线 / 刷新乘子档），本报告此后一律带限定词指名。

**改后树（读工作树核实）**：见 §3.2 落点表。

---

## 二、修前现场（本工作流采集的复现腿）

以下四条腿均为**修复工作流采集**〔工作流采集〕，全部 `reproduced=true`，实验根均为 `%TEMP%` 合成库（`tempfile.mkdtemp`），不触在役数据。

**腿①注·启发式分公式与逐项复算**（v1.0-r1 增，回答「0.775/0.88 怎么来的」；公式出处 `md_cg/forgetting.py:224-236`，本报告读码）：

```
启发式（hint=None 时）：s = 0.5·novelty + 0.3·SOURCE_WEIGHT[kind] + 0.2·lf
  SOURCE_WEIGHT（forgetting.py:68-73）：external_surprising=1.00 / unknown=0.60
    / self_generated=0.50 / internal_deterministic=0.25
  lf = min(1.0, len(完整入参 content)/200.0)   ← 含 CCG 六要素标签行
```

- 腿① `u_heur_new`：role=`tool-output` ∈ INTERNAL_ROLES → kind=`internal_deterministic`（权 0.25）；全新库 novelty=1.0；完整 content（240 字正文 + 标签行）≥200 字符 → lf=1.0 ⇒ **s = 0.5·1.0 + 0.3·0.25 + 0.2·1.0 = 0.775** ✓（`md_cg/test_i50d_importance_source.py:94-97` 夹具注释有同款复算）。
- 腿① `u_unk`：role 缺省 → kind=`unknown`（权 0.60）⇒ **s = 0.5 + 0.18 + 0.2 = 0.88** ✓。
- 同理可复算 issue50-a docstring 引用的编排侧读数 0.711（`t_heur`，正文 140 字但完整 content 含标签行达饱和）等——**分的差异由 role 权重与长度饱和决定，不由「载荷不同」笼统决定**（详见腿②的 t_heur 同分说明）。
- 守卫 docstring 引用的**「编排侧」**一词：指修复编排工作流的改前基线实测（其字面量已固化在 `md_cg/forgetting.py:267-268` issue50-d docstring：「u_heur_new 裁决 0.837/落盘 0.5；t_heur 裁决 0.711/落盘 0.5」与 `md_cg/test_i50d_importance_source.py:8-10`）；0.837 与腿① 0.775 的差异同为载荷成分差异（novelty/lf 不同），**同现象**=文案声称保护而落盘 0.5。

### 腿① 启发式 ACCEPT：审计面文案声称「触发不可遗忘保护」，落盘面无保护（缺陷①）

- **payload**：隔离库 `MdCGOS(tempfile.mkdtemp('i50d_gate_'))`；`cg.remember_gated("u_heur_new", <CCG六要素长文·正文240字·词根阿尔法>, layer="contextual", role="tool-output")`——无 `importance_hint`；对照腿 `cg.remember_gated("u_unk", <CCG六要素长文·240字·词根变压器>, layer="contextual")`（role 缺省 = unknown 权 0.60）。
- **observed**：`u_heur_new`：verdict=ACCEPT，`gate.importance={score:0.775, from:'heuristic'}`，reason=`'重要度 0.78≥0.7（触发不可遗忘保护）'`；`cg.get` 直读 `fm.importance=0.5`、`fm.protected=None`；**盘上节点文件直读仅一行 `importance: 0.5`、无 protected/protection_reason 行**。`u_unk`：verdict=ACCEPT，`gate.importance={score:0.88, from:'heuristic'}`，reason 同款『触发不可遗忘保护』；落盘同样 0.5、无保护位。**异常类型=审计面文案与落盘状态背离（非崩溃型）**。分值由来见腿①注（0.775=0.5+0.075+0.2，0.88=0.5+0.18+0.2）。
- **site**：`md_cg/forgetting.py:308-309`（改前 reason 不分叉）；落盘侧成因链 `md_cg/mdcos.py:3706-3707` → `md_cg/mdcg.py:2042` → `md_cg/mdcg.py:2438-2442`。

### 腿② 启发式裁决值落盘即丢：不同来源的裁决值全落常数 0.5（缺陷②主证据）

- **payload**：同库注入两条启发式写入：`u_heur_new`（role=tool-output，裁决 0.775）与 `u_unk`（role 缺省，裁决 0.88）；另在独立库以 role=tool-output 注入 140 字正文载荷腿 `t_heur`（裁决 0.775）。
- **observed**：三条启发式腿裁决值 **0.775/0.88/0.775**，落盘 `fm.importance` **全部=0.5**（盘面直读三处均仅 `importance: 0.5`）；`fm.importance_source` 键在所有节点不存在（`_node_entry` `mdcg.py:1858-1926` 改前现状无此键）。裁决值仅存活于 `remember_gated` 返回体 `out['gate']['importance']` 与 `_forgetting.jsonl` 留痕——**落盘重要度不携带任何区分信息**。`u_heur_new` 与 `t_heur` **同分 0.775 不是巧合**：同 role（SOURCE_WEIGHT 同 0.25）、novelty 均 1.0、完整 content 均达长度饱和（lf=1.0）⇒ 公式三项全同（v1.0-r1 更正：v1.0 写「载荷不同数值不同」不成立，t_heur 与 u_heur_new 即同分反例，已在腿①注更正归因）。顺带核对（采集原文标注『硬边界②』，即本批**不动 writelimit** 的边界，v1.0-r1 改为内联文字）：`writelimit.check` 的保护豁免（`md_cg/writelimit.py:130` 生效条件注释 + `:143-148` 同函数豁免实现，**同一站点**）读的是调用方原始 `importance_hint` 形参，不读落盘 importance，与本缺陷无耦合。
- **site**：`md_cg/mdcos.py:3706-3707`（`hint 非 None` 才透传，启发式 `hint=None` 整段不触发）；回落默认值 `md_cg/mdcg.py:2042`。

### 腿③ 显式 hint 面对照：0.9 保护一致（零回归面）；0.6 插件缺省通道常数透传（缺陷②插件侧事实）

- **「插件」指谁**（v1.0-r1 增，出处 issue50-a 修复记录 `docs/eval/issue50_半重复待定复核_修复记录_v1.0.md:48-49`，读码复核）：**宿主侧记忆插件（TS）**——`src/index.ts:168` `importance: z.number().default(0.6)`（zod schema 缺省值）→ `src/hooks.ts:479-482` `memorize('user', (g) => g.remember(safe, { role: 'user', …, importance: opts.importance }))` → 跨进程入口 `md_cg/mcp_server.py:2932` `importance_hint=a.get("importance")`。⇒ 插件**缺省口径**下用户消息带 `hint=0.60`。证据边界（issue50-a :49 原文）：只支撑「缺省值是 0.6」，不支撑「真实入路都按 0.6 走」——`importance` 是用户可配项，且在役留痕中 `importance.from="hint"` 且 `score=0.6` 只证明「实际发生过按 0.6 写入」。腿③ 的 `plug_a`/`plug_b` 即该缺省口径的**合成复现腿**，非真实调用记录。
- **payload**：`k_hint09`：`cg.remember_gated("k_hint09", <CCG文·60字>, layer="contextual", importance_hint=0.9)`；`plug_a`/`plug_b`：两个独立库各 `remember_gated(<id>, <CCG文·80字·词根减速器/联轴器>, layer="contextual", importance_hint=0.6)`。
- **observed**：`k_hint09`：verdict=ACCEPT、gate 0.9(from 'hint')、reason 同款『触发不可遗忘保护』、落盘 `fm.importance=0.9` + `protected=True` + `protection_reason='importance=0.90≥0.7'`（盘面三行齐全）——**显式面文案与落盘一致，无背离**（v1.0-r1 措辞更正：触发线是 0.7 不是 0.9——0.9 是载荷值，0.9≥0.7 过线打位；0.6<0.7 不过线不打位）。`plug_a`/`plug_b`：verdict=ACCEPT（分支⑤）、gate 0.6(from 'hint')、reason=`'重要度 0.60≥0.3'`、落盘均=0.6 无保护位——**两条不同内容落同一常数 0.6**，插件缺省通道落盘重要度同样不携带区分信息（裁决值恒等于 hint 常数）。
- **site**：`md_cg/mdcos.py:3706-3707`（hint 非 None 时 `kw["importance"]=hint` 原样透传）；保护位经 `md_cg/mdcg.py:2438`（AUTO_PROTECT_IMPORTANCE=0.7 线）只对过线载荷（0.9）打位。

### 腿④ F组·假设链只读验证：重要度→排序→下游使用（只取事实，未改检索面、未承诺改善）

- **payload**：隔离库直写（`cg.add`，不走闸门）：`F_imp05`/`F_imp09` 同正文（汽轮机660MW）importance 0.5/0.9；`F_rel_low`（高词面相关，importance=0.1）；`F_irrel_high`（仅部分词面交集「汽轮机厂」，importance=0.95）；query=`'汽轮机额定功率'`，`cg.search(q, k=10, record=False, judge=False)`，`MDCG_FRESHNESS` 开/关两情形；另 `freshness.refresh_factor` 纯函数读数。
- **observed**（代码事实 + 实测）：①主相关度打分 `_score`（`md_cg/mdcg.py:3959-4009`）**不含 importance 项**（sim+tag_bonus+语义×池降权×freshness 乘子）——实测同正文两节点同分（freshness 关时均 1.0）；②终排破序键消费：`mdcg.py:4130-4132` `sort key=(-score, -importance, id)`——实测 `F_imp09` 恒排 `F_imp05` 前（freshness 开/关均成立）；③freshness 刷新/降权乘子（`md_cg/freshness.py:197-226`）经 `mdcg.py:4003-4004` 缺省开乘进主分——实测 `F_rel_low(imp=0.1)` score=0.99 被降权档命中；纯函数 `(ac=10,la=1)`: imp=0.775→1.01 vs imp=0.5→1.0；④LIKE 全空兜底池按 importance/created_at 序（`md_cg/mdcos.py:1094-1102`）；⑤RRF 融合前排破序（`md_cg/mdcos.py:1651-1655`）；附带 maintain 分层 `_tier_of`（`forgetting.py:660-670`）亦消费。主分不消费的直接证据：`F_rel_low(importance=0.1)` 两个情形都排在 `F_irrel_high(importance=0.95)` 之前。
- **腿④注·refresh_factor 判据精确化**（v1.0-r1 增，出处 `md_cg/freshness.py:96-104, 197-226`，本报告读码；v1.0 的「rehearsal≥0.7」是缩写，判据**看 importance 不是 rehearsal**）：

  ```
  refresh_factor(access_count, last_access, importance)，符号：
    ac = access_count（访问计数）、la = last_access（最近访问时刻）、
    imp = importance（落盘重要度）、gain = 0.01（REFRESH_PARAMS["gain"]）
  刷新档：imp ≥ rehearsal_threshold(=0.7) 且 la > 0 且 ac % cycle(=10) == 0 → 1+gain
  降权档：imp < degrade_threshold(=0.2) 且 ac ≤ degrade_max_access(=2) → 1−gain
  其余 → 1.0
  ```
  即腿④的「rehearsal≥0.7→+0.01」实为「**importance 达 rehearsal 档阈值 0.7** → +0.01」——与遗忘闸门 `PROTECT_IMPORTANCE=0.7`、保护位线 `AUTO_PROTECT_IMPORTANCE=0.7` **数值相同、语义不同面**（§1.2 已指名）。三档阈值常量出处：`md_cg/freshness.py:96-104`（REFRESH_PARAMS，源自 AEIS `consolidate_cycle`）。
- **结论：落盘 importance 不是死字段**（决定并列破序、边界档位乘子与兜底池序），但排序消费的是落盘值，而启发式路径落盘恒 0.5（腿②），故裁决算出的 0.775/0.88 区分信息在落盘瞬间即丢失：破序键全并列退化到 id 序、刷新档对 0.5 永不生效、兜底池序失真——**假设链的前提（落盘携带裁决值）在改动前树上不成立，链在 `mdcos.py:3706` 落盘点断开**。
- **site**：消费面证据点 `md_cg/mdcg.py:4130-4132`（终排破序）· `md_cg/mdcg.py:4003-4004` + `md_cg/freshness.py:197-226`（乘子）· `md_cg/mdcos.py:1094-1102` 与 `1651-1655`（兜底池/RRF 破序）；链断点=`md_cg/mdcos.py:3706-3707`。

---

## 三、修法契约与落点

### 3.1 契约（使用者裁定 2026-10-02，三件套一次收口）

1. **落盘=裁决值**：`remember_gated` ACCEPT 分支无条件落 `imp["score"]`（替换「hint 非 None 才透传」口径），并按裁决来源落 `importance_source`（`"hint"|"heuristic"`）进 fm 与索引条目——免读文件可判「这条 0.8 是显式声明还是启发式分」。
2. **保护位只认显式声明**：`add` 的自动保护（importance≥0.7 → protected 位）加 source 闸——`importance_source != "heuristic"` 才打位；启发式过线**只落分、不打位**。`add` 缺省 None ⇒ 条件恒真，既有调用方保护行为逐位不变，**零回归由构造保证**（v1.0-r1 证据边界更正：v1.0 写「约 40 处既有生产调用方（逐一核对均不传该键）」——该句为实施段采集口径〔工作流采集〕，采集记录未附调用方清单与精确计数，「约 40」与「逐一核对」并存确属不自洽；本报告未复核精确数，**不作为本报告的判据**。零回归的实际机械锚是：构造性论证（None ⇒ 条件恒真）+ 守卫 E/B/C 组不变列断言 + 既有守卫回归 rc=0（§4.2），不依赖该计数）。
3. **文案分叉**：`assess` 保护分支 reason 按 `imp["from"]` 分叉——hint 维持「触发不可遗忘保护」；heuristic 改「启发式 …（未落保护——保护须显式声明）」。分支顺序/verdict/常量未动。

**改后启发式分支 reason 完整字面量**（v1.0-r1 增，回答读者「最终原文」；出处 `md_cg/forgetting.py:325-330`，本报告读码）：

- hint 分支（不变）：`f"重要度 {imp['score']:.2f}≥{PROTECT_IMPORTANCE}（触发不可遗忘保护）"`——0.9 实际输出 `重要度 0.90≥0.7（触发不可遗忘保护）`；
- heuristic 分支（本批改）：`f"启发式 {imp['score']:.2f}≥{PROTECT_IMPORTANCE}（未落保护——保护须显式声明）"`——0.775 实际输出 `启发式 0.78≥0.7（未落保护——保护须显式声明）`（`:.2f` 截两位）。

### 3.2 落点（改后行号 = 本报告读工作树所见）

| 文件:行号 | 改动 |
|---|---|
| `md_cg/mdcos.py:3725-3726` | ACCEPT 分支：`kw["importance"] = verdict["importance"]["score"]` + `kw["importance_source"] = verdict["importance"]["from"]`（注释 3715-3724；docstring 3649-3656；生效条件注释 3601 同步） |
| `md_cg/mdcg.py:2054` | `add` 新增显式参数 `importance_source: str = None`（经 `MdCGOS.add`/`MdCGSecure.add` 的 `**kw` 转发全链生效） |
| `md_cg/mdcg.py:2247-2248` | 非 None 时落 `fm["importance_source"]`（注释 2244-2246）；缺省 None 不落键，既有调用方 fm 形态逐位不变 |
| `md_cg/mdcg.py:2453-2455` | 自动保护位条件加第三判据 `and importance_source != "heuristic"`（落位 2456-2458，注释 2448-2452）；判据阈值 = `protect.AUTO_PROTECT_IMPORTANCE`（0.70，`md_cg/protect.py:46`） |
| `md_cg/mdcg.py:1881` | `_node_entry`（重建路径快照）入 `importance_source` 键（注释 1878-1880），旧库无此键 → None |
| `md_cg/mdcg.py:2494` | `_stage`（写入路径定向 upsert 快照）同口径入键（注释 2492-2493）——重建/定向 upsert 双路径同口径 |
| `md_cg/forgetting.py:325-330` | 保护分支 reason 按 `imp["from"]` 分叉（完整字面量见 §3.1；docstring 265-274、生效条件注释 239 同步） |
| `md_cg/test_i50c_meta_passthrough.py:201-213, 277-282, 295-298` | 受影响守卫正当同步：meta 白名单加第 5 条 `importance_source`（该键不是调用方透传的声明 meta，而是本闸 ACCEPT 裁决在落盘时自产 `mdcos.py:3726`——DEFER→队列 accept 路没有本闸 ACCEPT 裁决，故该路落盘无此键；v1.0-r1 消除「非调用方声明 meta」歧义句）、B2 排除该键、B5 计数 4→5 |
| `md_cg/test_i50d_importance_source.py` | **新建守卫**（524 行、32 断言、7 组），见 §4.1 |

### 3.3 契约边界补证（v1.0-r1 增，回应「显式传 importance 会不会被裁决值覆盖」）

旧口径 `if hint is not None and "importance" not in kw`（改前 `mdcos.py:3706`）带防覆盖语义；新契约「无条件落 `imp["score"]`」下调用方显式传 `importance` 的情形——**隔离库探针实测**〔本报告实跑〕（`MdCGOS` 临时根，三用例）：

| 调用 | 落盘 fm.importance | source | protected | 结论 |
|---|---|---|---|---|
| `remember_gated(…, importance=0.8)` | 0.8 | hint | True（`importance=0.80≥0.7`） | **不被覆盖丢失**：`mdcos.py:3660` `hint = kw.pop("importance_hint", kw.get("importance"))` 把显式 `importance` 当 hint 参与裁决 → 裁决值=声明值 → 落盘同值；source=hint ⇒ 保护位照打（与 `add` 直调口径一致） |
| `remember_gated(…, importance=1.5)` | **1.0** | hint | True | 越界值被裁决裁剪（`importance_score` 先 clip 到 [0,1]，`forgetting.py:228`）→ 落盘=clip 值；改前该情形落**原值 1.5**（原样透传 add，与裁决面 1.0 背离）——改后落盘与裁决一致，方向符合「落盘=裁决值」契约 |
| `remember_gated(…, importance_hint=0.9)` | 0.9 | hint | True | 守卫 B 组同款（零回归锚） |

即：显式 `importance` 调用方在改后契约下**数值不丢失**；唯一行为差异是越界值改按裁决裁剪值落盘（改前落盘与裁决背离）。

---

## 四、验证数字

### 4.1 新守卫（正向 + 定点变异自证）〔本报告实跑〕

命令 `python -X utf8 -m md_cg.test_i50d_importance_source`：

- **正向**：锚点自检 PASS（banned 缺陷形态 + required 新判据锚点，不以 git HEAD 为基线源）；**32 通过 / 0 失败 / exit 0**（与源文件 `ok(` 调用 32 处的静态计数一致）。
- **`--mutate`**：未变异基线红 0；4 处定点变异红项**全部恰好命中预期表**，exit 0：

| 变异 | 红项数 | 命中预期 | 说明 |
|---|---|---|---|
| m1 删 source 落盘 | **8** | ✓ | A4/A5/A6/A10 source 面 + A7/E1——source 缺席使 add 保护闸看不见 heuristic，启发式 0.775 也被打位（恰为缺陷形态联动复现）+ B2/C2 显式面 source 消失 |
| m2 落盘改回 hint-only 透传（缺陷形态） | **5** | ✓ | A2/A3/A4/A10 importance 面 + E2 对拍变列锚 |
| m3 启发式也打保护位（删 source 闸） | **3** | ✓ | A7/A10/E1 |
| m4 文案不分叉 | **3** | ✓ | A8/A9/A10 |

守卫自带 fail-closed：锚点缺失时打印 ANCHOR-MISS 并 exit 2〔工作流采集：内存注入假锚实测〕；独立复核另实测「删断言探针」——内存改组表删 g_a 后四变异红项 3/1/1/0 全偏离预期 → 定点变异自证 FAIL rc=1，**删组必被自证抓获**〔工作流采集〕。

### 4.2 回归面

| 检查 | 数字 | 级别 |
|---|---|---|
| 新守卫正向 | 32 通过 / 0 失败 / rc=0 | 〔本报告实跑〕 |
| 新守卫 `--mutate` | 基线红 0，红项 8/5/3/3 全命中 / rc=0 | 〔本报告实跑〕 |
| `test_i50c_meta_passthrough`（本批同步过） | 30 通过 / 0 失败 / rc=0 | 〔本报告实跑〕 |
| `test_p9_forget_protect`（保护面回归锚，含「importance_hint≥0.7→ACCEPT」既有断言） | 37 通过 / 0 失败 / rc=0 | 〔本报告实跑〕 |
| `test_p9c_dedup_hints` | 31 通过 / 0 失败 / rc=0（v1.0-r1 补齐：复跑取精确计数） | 〔本报告实跑〕 |
| `test_p2_mcp` | 64 通过 / 0 失败 / rc=0（v1.0-r1 补齐） | 〔本报告实跑〕 |
| `test_writelimit`（正向+--mutate） | **该守卫无数字计数输出**——尾行 `All writelimit tests passed.`、rc=0（正向）；`--mutate` rc=0〔采集〕。v1.0-r1 更正：v1.0 把三个用例名并一行只给两个计数（31/0、64/0），系 writelimit 守卫本身不输出 pass/fail 数字所致；现拆行、量纲如实（本报告复跑正向 rc=0 确认尾行文案） | 〔本报告实跑·正向〕+〔工作流采集·--mutate〕 |
| python 全量 `python -X utf8 scripts/run_tests.py` | **303/303 通过，5 跳过**（依赖缺失/平台不符）/ rc=0 | 〔本报告实跑〕 |
| `test_i50a_half_dup_defer` | 26/0（含 --mutate 全命中） | 〔工作流采集〕 |
| `test_i50b` | 34/0（含 --mutate 全命中） | 〔工作流采集〕 |
| 定向回归 `python -X utf8 scripts/run_tests.py md_cg` | 226/226 通过（3 skip 为依赖缺失/平台不符） | 〔工作流采集〕 |
| 容器栈一（`docker run --rm -v <repo>:/work -w /work -e CARGO_TARGET_DIR=/tmp/target rust:bookworm bash scripts/linux_verify.sh full`，README.md:585） | **127**——未执行成实测（见下） | 〔工作流采集退出码〕 |
| 容器栈二（`docker run --rm -v <repo>:/work -w /work node:22-bookworm bash -c "npm install --include=dev && npm run build && node --import tsx --test test/*.test.ts"`，README.md:588） | **127**——同上 | 〔工作流采集退出码〕 |

**容器两栈：采集 127 与本机探测如何拼接（v1.0-r1 重写，回应「127 与 docker ps rc=1 拼不上」）**：

- 采集值：两栈退出码均 **127**〔工作流采集〕。**127 产生的具体环境与步骤，采集材料未携带**（无法确证是采集机缺 docker CLI、壳层找不到命令还是其它一环），本报告不代补这条链条。
- 本报告环境探测〔本报告实跑〕：`docker --version` rc=0（Docker version 28.4.0）但 `docker ps` rc=1（daemon 未运行，`//./pipe/dockerDesktopLinuxEngine` 不存在）。
- 这两段是**不同环境的事实**，互相不能推导；唯一能共同支撑的结论是：容器两栈在采集环节与本报告环节**都未执行成实测**，127 一律不写成「测试失败」也不写成「通过」。
- 未复跑的执行性理由：栈内命令在挂载点内跑 `cargo build`/`npm install`，会向工作区写构建产物，与「只写这一个文件」硬边界冲突；且本机 daemon 未运行，不具备执行条件。
- 「既定契约」出处（v1.0-r1 增）：修复工作流实施段采集记录原文自述「**全量与容器按契约留给脚本，未跑**」——即全量与容器两栈在实施环节即声明不在实施段执行范围；本报告环节只写报告文件，同样未执行。「留给脚本」未指名具体脚本（采集原文未给），本报告不代指。

### 4.3 独立复核的对拍（两树等价性）〔工作流采集〕

复核以 `git archive HEAD md_cg` 解包出改前树（版本自洽整包，全程未动工作区，`git status` 终末与起始快照逐字一致——本报告终末亦核对一致），两树各跑 11 用例（自写 probe.py，每用例独立临时库）：

- **崩溃腿实测存在且已修**：`importance_hint='abc'` 在改前树 `ValueError: could not convert string to float: 'abc'`（旧 `remember_gated` 把原字符串透传 add）——**现行树不崩、回落启发式**（from=heuristic、落盘=裁决值 0.88、source=heuristic）。此收益修复记录原文未声明，复核补记。**语义边界（v1.0-r1 增）**：改后对非法 hint 是「不崩但**静默回落**」——回落机制在 `importance_score` 的 `except (TypeError, ValueError): pass`（`forgetting.py:230-231`），无告警无标注（`from=heuristic` 是唯一线索）。「fail-silent 是否期望语义、非法值应否显式报错」属使用者的语义裁定，本报告不代裁定，列为 §六留池观察面。
- **容错腿**：旧式节点（fm 无 `importance_source` 键）重开不崩；新树索引条目键在且为 None、旧树无键；DEFER 路两树 verdict=DEFER、proposed 非空、独立扫描确认未落盘、入队 extra 声明 meta 逐键相等。
- **可判定比较**（非『没抛异常』）：每用例「盘面独立扫描（os.walk + nodefile 逐 .md）vs API 索引投影」——节点 id 集合与 importance/importance_source/protected/layer 四键逐节点相等，**对拍合计 89 断言 0 失败**。
- **等价性**：同一探针两树实跑同一批用例，递归 diff 白名单外差异=0；hint 面（0.9/0.6）落盘值/protected/reason 逐字相等；`add` 直调既有调用方（不传 source）fm 除时间键逐键相等；assess 8 组合矩阵除预期 reason 分叉（=heuristic 且 score≥0.7 的 r1/r2/r7/r8 四组合）外逐键相等。
- **源码指纹**（`inspect.getsource` 的 sha1[:12]）：assess/remember_gated/add 两树不同（恰为本批三处）；reinforce=`141275c71f0e`、importance_score=`124645747549` 两树逐位相同。

---

## 五、独立复核判定与它列出的 uncovered

**判定：ACCEPT**〔工作流采集〕。依据（复核自述「被测物亲读」）：`git diff -- md_cg/{forgetting,mdcg,mdcos}.py` 与新守卫全文（7 组 32 处 `ok()`）；实验根全部为 `%TEMP%` 合成库；改前树为 `git archive HEAD` 解包至系统临时目录，全程未动工作区。

**复核列出的 uncovered**：

- **T1（MERGE/DROP 分支的传导效应）**：复核实测 MERGE/DROP 分支行为两树一致，**唯 T1 传导效应除外**。**为何本报告只有名目（v1.0-r1 补明）**：T1 的展开正文在采集材料（独立复核段输出）中未随传——本报告只拿到「T1 具名」这一事实；复核探针不在本报告可及范围（复核环节已结束），补采需回到复核环节重跑两树 MERGE/DROP 对拍，超出本报告「只改报告文件」的边界。照录名目、不代补内容。

**复核补充的两项修复记录未声明事项**（属复核发现，如实转录）：① `importance_hint='abc'` 崩溃腿的消除（§4.3 第一条）——修复的**顺带收益**，修复记录原文未声明；② 守卫的 fail-closed 与删断言自证均实测成立。

---

## 六、边界与未覆盖（含本轮明确不修而留池的面）

**硬边界遵守情况**：本批只动 `md_cg/{mdcos,mdcg,forgetting}.py`、`md_cg/test_i50c_meta_passthrough.py`、新增 `md_cg/test_i50d_importance_source.py`；**未** add/commit/push，未触 `data/policy.json` 与任何在役数据根。本报告撰写员只新增本文档一个文件：报告落盘前的 `git status --porcelain` 与本工作流起始快照逐字一致（4 M + `.zcode/` + `md_cg/test_i50d_importance_source.py` 共 2 ??，核实〔本报告实跑〕）；落盘后终态仅多出本文档这 1 个未跟踪文件（文末附核实）。

### 6.1 「保护须显式声明」到底在哪些路径生效、哪些不生效（v1.0-r1 增，读码核实〔本报告实跑〕）

启发式过线节点（如落盘 0.775、`importance_source="heuristic"`、**无 fm.protected 位**）在各保护面的实际行为：

| 面 | 判据读什么 | 启发式 0.775 节点的实际行为 |
|---|---|---|
| `add` 自动保护位（落盘面，本批改动点） | `importance_source != "heuristic"` 才打位（`mdcg.py:2453-2455`） | **位不打**——「保护须显式声明」只在这一个落盘点改变行为 |
| `protect.is_protected`（读时三判据：层闸 → fm.protected 位 → **importance≥0.70 按分**，`md_cg/protect.py:134` 生效条件、`:149-150` 实现） | **按落盘分** | **仍然受保护**——0.775≥0.70 命中第三判据，返回「重要性保护：importance=0.78≥0.70」；其消费方 `guard_forget`（`protect.py:262`，forget 拦截）、`guard_move`（`:274`）、`protect_stats`（`:408`）、`scrub.py:665,728`（清洗跳过）、`self_state.py:865`、`mcp_server.py:1216` 全部按受保护对待 |
| `writelimit.check` 保护豁免 | **原始 hint 形参**（`writelimit.py:143-148`；hint 的取值单点 `mdcos.py:3660`） | **不豁免**——启发式路径 hint=None，照样可被限流 DEFER/CONVERGE（限流是工程策略「先别写」，与保护正交） |
| freshness `protected_floor` 衰减下界（`freshness.py:229-251`） | **fm.protected 布尔** | 不享受下界（无位）——但落盘 0.775 本身抬高衰减/刷新档的输入（refresh 刷新档 0.775≥0.7 可拿 +0.01；改前 0.5 拿不到）——属「重要度轴带电」的行为变化面，见 §6.2.3 |

**一句话回答读者问题**：启发式 0.775 节点**不会被 forget/move/scrub 动**（读时按分仍保护），**会被写限挡**（限流豁免只认原始 hint）；「保护须显式声明」的语义只改变「落盘要不要打 fm.protected 位」这一处——fm 位是审计/统计口径（`protect_stats` 的 auto_by_importance 计数、免读判面），读时保护由 is_protected 综合兜住。§6.2.2 保留为留池面的正是这个「落分即读时保护」的联动。

### 6.2 明确不修而留池

1. **`mdcos.prefeed(write=True)` 的同族第二落点**：其 `add importance=(0.5 if hint is None else hint)` 是与本缺陷同族的「常数落盘」形态，**不在本批契约站点提示内，未改**——建议后续批次收口〔工作流采集〕。
2. **`protect.is_protected`（`md_cg/protect.py:149`）读时保护**：启发式节点落 0.7x 分后，读时「重要性保护」按分会成立——这是裁决②「只落分」的**直接后果**（§6.1 表已展开为逐面行为表）；fm 的 `protected` 位（契约判据面）确实未打。`protect.py` 不在本批站点提示内未改〔工作流采集〕。
3. **检索面零改动**：F 组只取事实（`_score` 主分不消费 importance；消费面为排序次级键三处），**未改检索面、未许诺改善**——「重要度轴带电」后的检索行为变化（破序、refresh 档、兜底池序）属后续观察面。
4. **writelimit 保护豁免**：豁免读原始 hint（`md_cg/writelimit.py:143-148` 实现，`:130` 生效条件注释；同一 `check` 函数的两面——v1.0-r1 补明两处行号是同一站点），与本缺陷无耦合，本批未触碰（核毕）〔工作流采集〕。hint 的原始值单点 = `remember_gated` 的 `mdcos.py:3660`（`kw.pop("importance_hint", kw.get("importance"))`；v1.0-r1 更正：v1.0 转录的采集行号「remember_gated:3674-3675」与当前工作树读码不符，**以本报告读码 :3660 为准**，且当时漏了文件名）。
5. **Rust 面零改动**：`rust/src/freshness.rs:94` `protected_floor` 与 `store.rs:87, 383-403` 只读 `fm.protected` 布尔，语义未动零改动（核毕）〔工作流采集〕。
6. **DEFER→队列 accept 路无 `importance_source`**：accept 落盘走 `self.add(item["id"], content, layer, tags, condition_space, **extra)`（`mdcos.py:2573-2574`），importance 来自队列记录（调用方随 `**kw` 入队的声明，缺省 0.5）。该路没有本闸 ACCEPT 裁决 ⇒ 无裁决值可落 ⇒ `importance_source` 键无从产生（None）；保护闸第三判据对 None 恒真 ⇒ **若该路落盘 importance≥0.7（只能来自调用方显式声明随 extra 入队）照样打保护位**——与「保护位只认显式声明」契约同向（v1.0-r1 补足回答，读码核实〔本报告实跑〕）。「行为边界，非缺陷」的依据即此：该路的 ≥0.7 值必为显式声明，打位正确。
7. **非法 `importance_hint` 的 fail-silent 语义**：改后不崩、静默回落启发式（§4.3）；「应否显式报错」属使用者语义裁定，留池不裁（v1.0-r1 增）。
8. **容器两栈**：退出码 127（未执行成实测，§4.2），留待容器环境可用时补跑。
9. **复核 T1**（MERGE/DROP 传导效应）：名目见 §5，补采需回复核环节（本报告边界外）。
10. **纪律 16 归档条目仍 DEFER**：实施段已按 CCG 六要素成文写入审核队列（pid `prop_72e6bc36e9a3`，一致性闸判「不适用条件否定词面与自身正文重叠」），按不重试纪律待裁决，如实记录〔工作流采集〕。

### 6.3 留池项跟进归属（v1.0-r1 增，回应「谁在什么时点收口」）

本报告无排程权，只如实写归属与触发条件，不编造时点：

| 留池项 | 归属 | 触发条件 |
|---|---|---|
| §6.2.1 prefeed 第二落点 | 后续修复批次（编排会话排程） | 编排会话纳入批次站点提示后收口 |
| §6.2.8 容器两栈补跑 | 编排会话 / 具备容器环境的执行环节 | docker daemon 可用（本机现 `docker ps` rc=1，§4.2 探测） |
| §6.2.10 `prop_72e6bc36e9a3` 裁决 | 审核队列裁决通道（写入者不得自裁；经蜂群或验证端复核后可自行执行裁决——`zcode/AGENTS.md` 裁决权规则） | 复核通道给出裁决时 |
| §6.2.7 非法 hint 语义裁定 | 使用者 | 使用者裁定「报错 or 静默回落」后转批次 |

---

## 七、v1.0-r1 修订记录（读者反馈逐条处置）

| # | 反馈（类别） | 处置 | 落点 |
|---|---|---|---|
| 1 | 「三问」无定义（unclear） | 补三问/四态定义块，标出处 | §引言「先补三问定义」（forgetting.py:21-39） |
| 2 | 「插件」指谁未交代（unclear） | 补宿主记忆插件 TS 链路（zod 缺省 0.6 → memorize → mcp_server 透传）+ 证据边界 | §2 腿③（引 issue50-a 报告 :48-49） |
| 3 | 「编排侧 0.837」零定义（unclear） | 补出处（forgetting.py:267-268 docstring、守卫 docstring:8-10）+ 与 0.775 的差异归因 | §2 腿①注末条 |
| 4 | 「硬边界②」无对应物（unclear） | 去编号、内联说明（= 本批不动 writelimit 的边界） | §2 腿② |
| 5 | 「非调用方声明 meta」残缺（unclear） | 改无歧义表述：键是本闸落盘自产，非调用方透传 | §3.2 i50c 行 |
| 6 | 两个 ≥0.7 混淆、ac/la 未定义（unclear） | refresh_factor 判据精确化（看 importance），三处 0.7 带限定词指名，符号全定义 | §1.2 末段、§2 腿④注 |
| 7 | 两常量是否同值；「0.9 档」误读（unclear） | 补「两常量同值 0.7」与第三同值阈值；0.9 改述为载荷值 | §1.2 末段、§2 腿③ |
| 8 | 「既定契约」无出处（unclear） | 补采集原文出处；「留给脚本」如实声明未指名 | §4.2 容器段末条 |
| 9 | 「约 40 处」无证据标记且自相矛盾（unsupported） | 降级为实施段采集口径并声明不作判据；补真实机械锚（构造论证 + 守卫不变列 + 回归 rc=0） | §3.1 契约 2 |
| 10 | 「载荷不同数值不同」被 t_heur 反例（unsupported） | 承认错误并更正归因：同 role+同 novelty+lf 饱和 ⇒ 同分 | §2 腿②、腿①注 |
| 11 | 0.775/0.88 无法复算（unsupported） | 补公式 + 逐项复算（0.775=0.5+0.075+0.2，0.88=0.5+0.18+0.2） | §2 腿①注 |
| 12 | 三用例两计数账面不洽（unsupported） | 拆行 + 补齐精确计数（31/0、64/0）+ writelimit 无数字计数量纲如实 | §4.2 表 |
| 13 | 容器 127 与 docker ps rc=1 拼不上（unsupported） | 重写：两段是不同环境事实、不可互推；127 产生步骤采集材料未携带、不代补 | §4.2 容器段 |
| 14 | writelimit 两处行号对不上、漏文件名（unsupported） | 补读码：:130 注释面 + :143-148 实现面 = 同一 `check` 站点；`remember_gated:3674-3675` 更正为 `md_cg/mdcos.py:3660`（采集行号与当前树不符，以读码为准） | §2 腿②、§6.2.4 |
| 15 | 启发式 0.775 会不会仍被遗忘/写限挡（question） | 补 §6.1 逐面行为表（is_protected 按分仍拦 / writelimit 不豁免 / fm 位不打） | §6.1 |
| 16 | 改后 reason 完整字面量（question） | 补两个分支的 f-string 原文与实际输出 | §3.1 末 |
| 17 | 显式 importance 会不会被覆盖（question） | 补隔离库三用例探针（0.8 不丢 / 1.5 落 clip 值 1.0 / hint 0.9 锚），含改前改后差异分析 | §3.3 |
| 18 | DEFER→accept 路 importance 来源与保护位（question） | 补读码：accept 落 add(importance 来自队列记录) + 该路 ≥0.7 必为显式声明故打位正确 | §6.2.6 |
| 19 | fail-silent 是否期望语义（question） | 如实写改后语义（静默回落、无告警），裁定权归使用者、留池 | §4.3、§6.2.7、§6.3 |
| 20 | 真实谁传 hint=0.6（question） | 同 #2：插件 zod 缺省（生产侧在役留痕 `from=hint` score=0.6），无生产代码硬编码 0.6 | §2 腿③ |
| 21 | T1 具体指什么、能否补采（question） | 如实：材料未随传、复核探针不可及、补采需回复核环节（超本报告边界）；照录名目 | §5 |
| 22 | 留池项谁在什么时点收口（question） | 补归属表（归属 + 触发条件，不编造时点） | §6.3 |

---

## 附：git 面（本报告终末核实〔本报告实跑〕）

修复批次工作树（与本工作流起始快照一致）：

```
 M md_cg/forgetting.py
 M md_cg/mdcg.py
 M md_cg/mdcos.py
 M md_cg/test_i50c_meta_passthrough.py
?? .zcode/
?? md_cg/test_i50d_importance_source.py
```

本文档落盘后终态在此之上仅多 1 个未跟踪文件：`?? docs/eval/issue50_重要度同源与保护语义_修复记录_v1.0.md`。未 add / 未 commit / 未 push。本文为唯一被修改文档；全文无明文凭据。
