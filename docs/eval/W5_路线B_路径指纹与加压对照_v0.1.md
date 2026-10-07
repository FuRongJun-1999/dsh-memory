# W5 路线B · 路径指纹与加压对照（v0.1）

> 心跳轮 2026-10-07 ｜ 块：**W5** ｜ 路线：**路线 B**（`docs/eval/设计者首批裁定_v0.1.md` 第 12 条裁定「做」）
> 依据：`docs/eval/W5_标志线与融合核对_v0.1.md`（第 1 小步核对：两标志的首版实证材料与**局限**）
> 目标：把两个判「部分（首版实证成立）」的元认知标志推向**实存（全亮档）**——①「路径感知」→ 加**路径指纹**聚合对象（改码）；②「递归稳定性」→ 做**加压前后对照**实证（实验，不改生产语义）。
> 形态对照：`docs/eval/W4_情感模拟_探针读数_v0.1.md`、`docs/eval/W2_自主目标_探针读数_v0.1.md`（探针读数 → 结论 → 边界与待核实）。

---

## 卷面（本步回答的两个局限）

W5 第 1 小步（`W5_标志线与融合核对_v0.1.md`）两条判定与局限：

- **路径感知＝成立（首版）**，局限＝「①读数**分散**在 consistency／metacognition／mdcos 各模块，**无单一『路径指纹』字段**把一次决策的路径聚合成一个可命名对象；②多数是**事后留痕**而非运行时自述」。
- **递归稳定性＝成立（首版）**，局限＝「①现有证据证明的是『一致性可被机械校验、递归有界确定、重放幂等』，**未证明**『在真实递归压力下决策不漂移』——缺一个**对照/扰动实验**；②尚无『压力档位』与『稳定性度量（翻转率）』」。

设计者裁定第 12 条：**路线 B 做**——「①路径感知→加『路径指纹』聚合对象；②递归稳定性→做『加压前后对照』实证。成本可控（小工程）」。
本步即交付这两项，并如实标注残余局限。

---

## 一、任务一：路径指纹 `path_fingerprint`（改码，最小增量）

### 1.1 落点选择（设计裁定：**检索面**，非判定面）

三段来源在系统内**分属两面**：`selection`（scanned/kept/truncated/comparable）与 L2 递归 `trace`/`stopped_by` 在**判定面**（`md_cg/consistency.py`）；命中路 `per_path`/`provenance`（每候选被哪几路捞到、排第几）**只在检索面**（`md_cg/mdcos.py` `search_rrf`）。故：

- **落检索面**（`search_rrf` → `recall` 的返回 meta，新增键 `path_fingerprint`）。理由：命中路 provenance **只在检索面存在**——若落判定面，将不得不凭空造「paths」段（无中生有，违反白箱纪律）；而检索面**自身即可自陈三段**：
  - `selection`＝本次检索的选面（scanned / 生效门控 / fused / judge_ranking / judge_filtered / early_stopped）；
  - `recursion`＝本次检索**实际发生的递归展开**（因果路多跳：命中节点数 / 最大深度 / 最大跳数，取自 `chain_prov`）；
  - `paths`＝命中路面（各路候选数 `per_path` ＋ 候选级 `provenance`，与既有 meta 的 `paths`/`provenance` 两键**同源**）。
- 判定面（`consistency.check` 的 rec）**未**加入本字段：其 `selection`/`recursion` 齐备但**无 paths 段**，加入会得到「缺一段」的残指纹——不如让「全亮档路径对象」锚在**每次读都要走的检索决策**上（可指认、可复跑、覆盖面最广）。**此项属设计裁量面，若设计者认为判定面亦须落指纹，可复议**（见「与裁定/设计不一致/需再裁」）。

### 1.2 结构（`md_cg/mdcos.py:88-121`，模块级唯一实现）

```
path_fingerprint = {
  "selection": {"scanned", "gates", "fused", "judge_ranking",
                "judge_filtered", "early_stopped"},
  "recursion": {"chain": {"enabled", "nodes", "depth_max", "hops_max"}},
  "paths":     {"per_path", "used": [...], "multi": n, "provenance": {...}},
  "hash": "<sha256(排序归一 JSON) 前 16 位>"
}
```

- 构造器单点 `build_path_fingerprint(selection, recursion, paths)`（`md_cg/mdcos.py:111`）：三段归一 + `hashlib.sha256`（**非内置 `hash()`**——后者有随机盐、跨进程不稳定），对 `json.dumps(..., sort_keys=True)` 规范串取值 → **确定性**（同输入同指纹；不含时间戳/随机/uuid/对象地址）。
- 注入点：`search_rrf` 内 `_path_fp = build_path_fingerprint(...)`（`md_cg/mdcos.py:1884`），并写入**两处** meta（热缓存写入 `:1902` 与返回体 `:1914`）——保证缓存命中面与直返面同指纹。

### 1.3 「只增不改」的证据

- 既有顶层 meta 键**一个未动**（`tier/scanned/paths/fused/judge_ranking/judge_filtered/early_stopped/expand_source/goal_used/provenance`；守卫 **P4.1** 逐键断言在场）。
- **纯聚合输出**：不改检索/判定行为——两次调用结果 id 序逐位一致、结果仍为 4 元组（守卫 **P4.2**）。
- 既有字段语义未变：`paths.per_path ≡ meta["paths"]`、`paths.provenance ≡ meta["provenance"]`（守卫 **P2.1/P2.2** 逐位相同）。

### 1.4 守卫读数（新建 `md_cg/test_w5_path_fingerprint.py`）

`python -X utf8 -m md_cg.test_w5_path_fingerprint` → **ALL OK: 15 项**（P1 在场+结构 3；P2 自洽 4；P3 确定性 3；P4 只增不改 2；P5 透传 2；P6 文档口径 1）。

| 组 | 项 | 断言 |
|---|---|---|
| P1 | 1.1 / 1.2 / 1.3 | 指纹在场；三段均 dict；hash 为 16 位十六进制 |
| P2 | 2.1 / 2.2 | `paths.per_path`≡`meta["paths"]`；`paths.provenance`≡`meta["provenance"]` |
| P2 | 2.3 / 2.4 | `selection` 与顶层 `scanned/fused/judge_filtered` 对齐；`recursion.chain` 与 provenance 里的链对齐（nodes/depth_max/hops_max） |
| P3 | 3.1 / 3.2 | 同实例重复跑同 hash；**跨实例（重开同库）**同 hash |
| P3 | 3.3 | hash 判别力：同内容异键序→同 hash、不同内容→不同 hash |
| P4 | 4.1 / 4.2 | 既有顶层键一个不动；不改检索行为 |
| P5 | 5.1 / 5.2 | `recall().meta` 透传同 hash；热缓存命中面返回同 hash |
| P6 | 6.1 | 紧邻「生效条件：」注释 + docstring 声明确定性 |

### 1.5 定点变异自证（`--self-proof`，就地变异运行中源码、复原，不读 git）

`python -X utf8 -m md_cg.test_w5_path_fingerprint --self-proof` → **PASS**（未变异基线 0 红；三处逐条**恰好**命中期望红项）：

| 变异 | 红线签名（实＝期） |
|---|---|
| ① 去掉 `paths` 段（`"paths": dict(...)` → `"paths": {}`） | `{P2.1, P2.2}` |
| ② hash 掺非确定性源（追加 `uuid.uuid4()`） | `{P3.1, P3.2, P3.3, P5.1}` |
| ③ hash 恒定（`"0"*16`，判据空转） | `{P3.3}` |

（② 期望值不含 **P5.2**——热缓存**命中**面读的是**已存**的同一 meta，故其内部两次相等、不红；这正是「命中＝读同一指纹」的正面证据，签名差异恰说明该项判据不空转。注：变异②用 `uuid` 而非 `time.time()`——后者在快/慢机上会因时间戳分辨率不同而给出**机器相关**的红项签名，uuid 令签名跨机稳定。）

---

## 二、任务二：递归稳定性加压对照实证（实验，零生产语义改动）

### 2.1 设计（隔离库 + 压力旋钮 + 翻转率）

- **隔离库**：`tempfile.mkdtemp`（`scripts/probe_w5_recursion_pressure.py`），`check` 传 `log_write=False`（不落台账）、只读、**不碰活库**。
- **同一批**判定（覆盖四态 + 递归），三档压力只动旋钮：

| 档 | limit | depth | 噪声节点 | 压力语义 |
|---|---|---|---|---|
| **A 无压力** | 200 | 3 | 0 | 候选不截断、递归预算足 |
| **B 加压力** | 3 | 1 | 0 | **候选超限截断** + **递归预算收紧** |
| **C 噪声** | 200 | 3 | 40 | **库增长/扰动**（同批、同名判定，库多 40 条无关节点） |

- **库布局关键**：相关节点（`k_offline`/`e_conf`）先写（落过滤后索引序前 limit 内＝**保底面**）；**区分节点 `s_disc` 故意异层**（不在扫描面内 ⇒ 不作种子），只能经 `e_conf` 的因果边两跳到达——使「递归能否找到区分条件」由**递归预算 depth** 决定（纯递归压力），而非由种子面决定。
- **判定批**：`ACCEPT` / `REJECT_纪律` / `DEFER_条件互斥` / `DEFER_部分覆盖`（strength 0.55）/ `DEFER_递归`（须递归）/ `BLINDSPOT`。

### 2.2 读数表（重复 3 次，逐档）

**A 无压力**（档内翻转：0 条）

| 条目 | verdict | strength | scanned | kept | trunc | stopped_by | depth |
|---|---|---|---|---|---|---|---|
| ACCEPT | ACCEPT | 0.0000 | 17 | 17 | False | — | — |
| REJECT_纪律 | REJECT | 1.0000 | 1 | 1 | False | — | — |
| DEFER_条件互斥 | DEFER | 1.0000 | 17 | 17 | False | gain_below_threshold | 1 |
| DEFER_部分覆盖 | DEFER | 0.5500 | 17 | 17 | False | gain_below_threshold | 1 |
| DEFER_递归 | DEFER | 1.0000 | 17 | 17 | False | **resolved** | **2** |
| BLINDSPOT | BLINDSPOT | 0.0000 | 1 | 1 | False | — | — |

**B 加压力**（档内翻转：0 条）

| 条目 | verdict | strength | scanned | kept | trunc | stopped_by | depth |
|---|---|---|---|---|---|---|---|
| ACCEPT | ACCEPT | 0.0000 | 17 | **3** | **True** | — | — |
| REJECT_纪律 | REJECT | 1.0000 | 1 | 1 | False | — | — |
| DEFER_条件互斥 | DEFER | 1.0000 | 17 | **3** | **True** | gain_below_threshold | 1 |
| DEFER_部分覆盖 | DEFER | 0.5500 | 17 | **3** | **True** | gain_below_threshold | 1 |
| DEFER_递归 | DEFER | 1.0000 | 17 | **3** | **True** | **depth_exceeded** | **1** |
| BLINDSPOT | BLINDSPOT | 0.0000 | 1 | 1 | False | — | — |

**C 噪声**（档内翻转：0 条）—— `scanned` 17 → **57**（噪声确已注入），判定**逐条同 A**。

### 2.3 翻转率读数（本实验核心）

| 读数 | 值 | 含义 |
|---|---|---|
| **档内翻转率**（同档重复 3 次逐条比 verdict） | **A=0 / B=0 / C=0** | 同输入、同压力 ⇒ 同判：**确定性成立**（无漂移） |
| **跨档翻转率 A→B**（候选截断+递归收紧） | **0 条** | 加重压力**不改变判定**（6 条判定逐条一致） |
| **跨档翻转率 A→C**（库噪声 ×40） | **0 条** | 库增长/扰动**不改变判定** |

### 2.4 递归预算曲线（同库同批，只动 depth 0→3）

| 条目 | depth=0 | depth=1 | depth=2 | depth=3 |
|---|---|---|---|---|
| ACCEPT | ACCEPT/— | ACCEPT/— | ACCEPT/— | ACCEPT/— |
| REJECT_纪律 | REJECT/— | REJECT/— | REJECT/— | REJECT/— |
| DEFER_条件互斥 | DEFER/— | DEFER/gain_below_threshold | DEFER/gain_below_threshold | DEFER/gain_below_threshold |
| DEFER_部分覆盖 | DEFER/— | DEFER/gain_below_threshold | DEFER/gain_below_threshold | DEFER/gain_below_threshold |
| DEFER_递归 | DEFER/— | DEFER/**depth_exceeded** | DEFER/**resolved** | DEFER/resolved |
| BLINDSPOT | BLINDSPOT/— | BLINDSPOT/— | BLINDSPOT/— | BLINDSPOT/— |

**读法**：recursion 预算收紧时，**判定（verdict）恒定不动**，变的只有**递归终止原因**（`depth_exceeded` → `resolved`）与深度——即**递归在压力下「少走几步」但不「改主意」**：压力被吸收在**递归读数**上，未外溢到**判定**。

### 2.5 自证（`--self-proof`，fail-closed）

`python -X utf8 scripts/probe_w5_recursion_pressure.py --self-proof` → **PASS**，四条前置自检全绿：

- 压力①确已施加：B 档 **4 条**发生候选截断（kept<scanned）；
- 压力②确已收紧：递归深度峰值 A=2 → B=1；
- 压力③确已注入：`scanned` A=17 → C=57；
- 基线可复跑：三档各自重复跑**逐条同判**（无档内漂移）。

### 2.6 结论（递归稳定性）

**结论：在本实验的三档压力下，递归**不漂移**——「压力-一致对照实证」成立。** 具体：

1. **确定性/一致性成立**：同输入同压力重复 3 次，判定翻转率 **0**（A/B/C 三档一致）——补上了 W5 局限①「缺对照/扰动实验」。
2. **压力不改变判定**：候选超限截断（kept 17→3）、递归预算收紧（depth 3→1）、库噪声 ×40，**跨档翻转率均为 0**——递归压力被吸收在**递归读数**（stopped_by/depth）上，判定（verdict）不随之漂移。
3. **压力可调 + 稳定性可度量**：给出「压力档位」（limit/depth/noise）与「稳定性度量（翻转率）」——补上了 W5 局限②。

**局限（如实标注）**：

- **样本小**：6 条判定、3 条压力档，属**结构性对照**而非统计显著；压力面（截断/预算/噪声）覆盖广但每条判定的压力取值单一。
- **「不漂移」有构造性前提**：候选截断按**相关性序**保留（`rel` 面）并叠加**保底面**（过滤后索引序前 limit），相关节点**结构上不会被截断**——故「截断不漂移判定」部分是**设计保证**而非纯经验观测（这也正是 `consistency` 选面纪律「修后检出 ⊇ 修前」的正面读数）。**若相关性打分本身出错**（把相关节点排在 limit 之外），压力仍可能改变判定——本实验未构造该反例。
- **未覆盖「多轮回灌」压力**：W5 所述第二类递归压力（睡眠自迭代/两段式）未纳入本探针（本探针只覆盖 L2 递归展开）；此类压力由 `sleep`/`twophase` 的**幂等/对账**机制单证（W5 §二 #6–8），**未做加压对照**——待核实。

---

## 三、与裁定/设计的一致与偏差

| 项 | 裁定/设计 | 本步 | 一致？ |
|---|---|---|---|
| 路线 B 做 | 第 12 条「做」 | 两任务均落地产出 | ✅ |
| 路径指纹＝单一可命名对象 | 三段 + 稳定 hash | `path_fingerprint`（selection/recursion/paths/hash） | ✅ |
| 指纹落点 | 「倾向检索面……若落 consistency 面说明理由」 | 落**检索面**，理由：命中路 provenance 只在检索面 | ✅（并已在 §1.1 说明） |
| 只增不改既有字段语义 | 既有返回键一个不动 | 守卫 P4.1 逐键断言 | ✅ |
| 哈希确定性 | 同输入同指纹、不含时间戳/随机 | `sha256(sort_keys JSON)`；守卫 P3.1–3.3 | ✅ |
| 不改检索/判定行为 | 纯聚合输出 | 守卫 P4.2 | ✅ |
| 守卫 + 定点变异 ≥2 处 | 结构/确定性/一致性 + 变异自证 | 15 项 + 3 处变异（恰好命中） | ✅ |
| 加压对照实验 | 无压力 vs 加压力，翻转率读数 | 三档 + 档内/跨档翻转率 + 预算曲线 | ✅ |
| 零生产语义改动（实验） | 只读 + 隔离库 | `log_write=False` + tempfile | ✅ |

**需再裁 / 需注意**：

1. **判定面是否也落指纹**：本步把指纹锚在**检索面**。若设计者要求「一次**判定**（`consistency.check`）的路径」也具备单一对象，可在判定面补 `path_fingerprint`（其 `selection`/`recursion` 齐备，`paths` 段需另议——判定面**无**检索 provenance，只能落「选面路径（scanned/kept/truncated/comparable）」为空 paths）。**建议**：不补（避免「残指纹」）；如补，须设计者裁「判定面 paths 段取何」。
2. **全亮档措辞**：本步给出**可指认、可复跑**的单一对象与**对照实证**，证据强度已达「实存（全亮档）」的**机械判据**（单一对象 + 对照读数 + 守卫/变异）；但**是否即判「全亮档」属口径归设计者**——本步只交付材料，不擅自改纲领卷面判语（对齐 W5 第 1 小步「判定是描述而非宣称」）。

---

## 四、边界与待核实

1. **本步改码仅 `md_cg/mdcos.py`（新增字段 + 单点构造器），零既有语义改动**；实验零生产改动。
2. **未碰 `docs/theory/`**；**未执行 git add/commit/push**；**未调任何 mdcg 写入 op**（隔离库构造不算写入生产）。
3. **待核实**：①「多轮回灌」类压力的加压对照（睡眠自迭代/两段式）——本实验未覆盖；②相关性打分失效下截断是否漂移（反例未构造）；③判定面指纹（见 §三.1）。
4. **相邻回归**（L1 直跑）：`md_cg.test_p45_session_identity`（42/0）、`md_cg.test_c8_search_rrf_gates`（59 OK）、`md_cg.test_p2`、`md_cg.test_p2_six_elements`（42/0）、`md_cg.test_hot_cold`（33/0）、`md_cg.test_i28_hotcache_prodpath`（8 OK）、`md_cg.test_i32_hotcache_env_key`（14/0）、`md_cg.test_retr_s1`（46/0）、`md_cg.test_retr_s3`（17/0）、`md_cg.test_p42_provenance`（52/0）、`md_cg.test_p8_subgraph_chain`（35/0）、`md_cg.test_v14_fixes`（59/0）——全绿。

---

## 五、改动清单（逐文件）

| 文件 | 增删 | 说明 |
|---|---|---|
| `md_cg/mdcos.py` | +77 / −2 | 新增模块级单点 `build_path_fingerprint` + 常量 `PATH_FINGERPRINT_KEYS`（`:88-121`）；`search_rrf` 内聚合三段并注入 meta（`:1855-1888`），写入**两处** meta（`:1902` 缓存写入 / `:1914` 返回体） |
| `md_cg/test_w5_path_fingerprint.py` | 新建 | 守卫（15 项）+ 定点变异自证（3 处，就地变异/复原） |
| `scripts/probe_w5_recursion_pressure.py` | 新建 | 加压对照探针（三档 + 翻转率 + 预算曲线 + `--self-proof`） |
| `docs/eval/W5_路线B_路径指纹与加压对照_v0.1.md` | 新建 | 本报告 |

---

> 本步结论（一句话）：**路径感知＝实存（全亮档材料）——检索返回体现在自陈单一可命名、确定性可复算的 `path_fingerprint`（selection/recursion/paths + 稳定 hash），守卫 15 项全绿且三处定点变异逐条恰好转红；递归稳定性＝实存（全亮档材料）——三档加压对照下档内/跨档翻转率均为 0，压力被吸收在递归读数（stopped_by/depth）上、不漂移判定，`--self-proof` 证压力确已施加。局限如实标注：样本小、不漂移部分有构造性前提（相关性序 + 保底面）、多轮回灌类压力未纳入。**
> 引用核对（供复核者抽查）：`md_cg/mdcos.py:111`（`build_path_fingerprint`）、`:1884`（注入）、`:1902/:1914`（两处 meta）；`md_cg/consistency.py:444/479-480`（L2 `trace`）、`:774-784`（判定返回体）、`:629-634`（选面 scanned/kept/truncated）；`md_cg/mdcos.py:1698/1709-1713/1828`（`per_path`/`provenance`）。
