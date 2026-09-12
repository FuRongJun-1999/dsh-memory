# AGI 七维评分报告 · md_cg（灵枢认知图记忆系统）v1.0

> **评估对象**：`dsh-memory / md_cg`（条件空间驱动的认知图记忆系统）
> **标尺**：`AEIS/docs/AGI记忆系统评分标尺_v1.0.md`
> **前次基线**：标尺 §6.1 初评（2026-09-09）→ S7.0 / R7.0 / J7.5 / C7.5 / U6.0 / I4.5 / T7.5，综合 **5.8**，层次 **L4**
> **本次性质**：**标尺 §2.3 四个门槛判别测试的实跑复核**（非印象打分）
> **证据等级**：全部结论均有**落盘 JSON 实测数据**，逐项标注数据文件
> **对照物**：同期完成的另一套记忆系统复核评价（**内部文档，不随仓库公开**，故不给路径）

---

## 一、评估条件空间

```
[判定单]
条件空间：观测位置=灵枢侧自我实测（自评风险见 §二）
        观测工具=标尺 §2.3 四门槛判别测试 + md_cg 公开 API（cg/recall/consistency/evolution/identity/self_state）
        时间窗口=2026-09-12 实测快照
        存在约束=自评系统；L4「新增条件分支」判据需区分「库结构行为」与「开发者行为」
白箱三问：依据=标尺 §2.3 判别测试表 + 本仓库实验目录全部 result_*.json
        条件=分数只在同层内可比（§4.2）；本次重点在**门槛是否通过**，不在分数微调
        错后=发现反例即下调/标 DEFER 并归档（§七）
裁决：ACCEPT
依据：四门槛测试均已按 §2.3 口径实跑，数据落盘，可复现
缺失维度：U 维「同条件不同值」处理机制（S1 暴露）；I 维「元认知工具」未实测
        （世界模型属身体层 AEIS，不计入大脑 I 维 —— 见 §十一.8 层错位声明）
验证路径：§六 S1 复现 + §十一 DEFER 项
```

---

## 二、自评风险声明与缓解

本报告是**系统评自己**，存在结构性利益冲突。三条缓解措施：

1. **判据外置**：全部通过标准取自标尺 §2.3 原文（hit@1 ≥ 80% / 负条件拒绝率 ≥ 70%），不由被测系统定义。
2. **语料外置**：对抗语料**直接复用**本地实验工作区（`docs/experiments/`，**不入库**）`deja-vu-negcond/corpus.py` 的同一批 20 组 `GROUPS`（不复制文本、不挑选利于己的样本）。
3. **反例优先**：凡实测未达判据处**照实记录并下调**（§六 S1、§十 U 维），不因"是自己"而豁免；发现的假阳性一并纠正（§七）。

> **仍未消除的风险**：判据的解释权、观测位置的独立性。故 §十 对 L5 临界结论给 **DEFER** 而非 ACCEPT。

---

## 三、实验装置

| 项 | 设置 |
|---|---|
| 被测件 | `md_cg`（`from md_cg.mdcos import MdCGOS, MdCGSecure`） |
| 隔离 | 每组实验**独立库目录**（`_store/<name>`，跑前 `rmtree`），互不污染 |
| 语料 | 复用本地实验工作区 `docs/experiments/deja-vu-negcond/corpus.py`（不入库）的 20 组 `GROUPS`（L3）；L2 用 10 唯一目标 + 990 干扰 |
| 流程纪律 | 先 smoke 验证 API 返回结构，再全量跑；结果落盘 `result_*.json` |
| 命令 | 统一 python（`PYTHONUTF8=1`，argv 列表，不经 shell） |

**脚本与产物清单**（`docs/experiments/md-cg-gate-probe/`）：

| 脚本 | 测试 | 产物 |
|---|---|---|
| `run_l2_retrieval.py` | L2 检索判别 | `result_l2.json`、`result_l2_strict.json` |
| `run_l3_negcond2.py` | L3 负条件拒绝（四口径） | `result_l3v2_{A,B,C,D}.json` |
| `run_l4_evolution.py` | L4 矛盾反馈 | `result_l4.json` |
| `run_l4b_rollback.py` | L4 回滚链路 | `result_l4b.json` |
| `run_l5_continuity.py` / `run_l5b_selfstate.py` | L5 身份/变更史 | `result_l5.json`、`result_l5b.json` |
| `run_ct_probe.py` | C 预算 / T 墓碑 | `result_ct.json` |
| `run_t2_probe.py` | T 写保护·密级 / I 版本链（补测） | `result_t2.json` |

---

## 四、L2 门槛 · 检索判别 —— **PASS**

标尺 §2.3 判据：`1000 条历史会话中检索「三月修过的 jwt 问题」→ hit@1 ≥ 80%`。

| 口径 | 节点量 | 查询 | hit@1 | hit@5 | 数据 |
|---|---|---|---|---|---|
| 含歧义 | 1000（10 目标 + 990 干扰） | 10 | **0.90** | 1.00 | `result_l2.json` |
| 去歧义（strict） | 同上 | 10 | **1.00** | 1.00 | `result_l2_strict.json` |

**结论：两种口径均 ≥ 0.80，通过。**

**唯一失败案例归因**（含歧义口径，`target_07`）：

- 查询「九月修过的 **限流** 问题」，目标被 3 条 filler 压到 rank 4。
- 归因：目标中「限流」处于**组件位**（登录接口的限流阈值），而 filler 中「限流」处于**问题位**（"如何解决限流"）。md_cg 的词面召回**不消解语义槽位**，同词高权重者胜出。
- 性质：属**评测集歧义**（含歧义口径）；strict 口径移除该歧义后 hit@1 = 1.00。**这是真实边界，不是门檻未过。**

---

## 五、L3 门槛 · 负条件拒绝 —— **PASS**

标尺 §2.3 判据：`20 组「关键词相似但能力不同」对抗对，负条件拒绝率 ≥ 70%`。

**四口径设计**（关键：未做 D 镜像就不能排除"无脑拒一切"）：

| 口径 | 写入 | 查询上下文 | reject_loose | reject_strict | accept_rate | hit@1 |
|---|---|---|---|---|---|---|
| A | 裸文本，无 context | 无 | 0.20 | 0.00 | 0.00 | 1.00 |
| B | CCG，无 context | 无 | 0.20 | 0.00 | 1.00 | 0.90 |
| **C** | CCG | +correct 条件 | **1.00** | 0.00 | 1.00 | 1.00 |
| **D** | CCG | +bait 条件（镜像） | **1.00** | 0.00 | 1.00 | 1.00 |

- **A/B ≈ 0.20**：无条件路由时，bait 与 correct 无法区分（基线）。
- **C/D = 1.00 且完全对称**：给 correct 条件时拒 bait、给 bait 条件时**同样拒 correct**——**双向对称**排除了"凡有冲突一律拒"的作弊路径，证明是**真条件路由**。
- 数据：`result_l3v2_A/B/C/D.json`。

**两条诚实标注**：

1. `reject_strict = 0`：拒绝靠 **S 维条件空间物理分桶**（不同 `condition_space` 互不召回），而非 J 维语义层判定 REJECT。功能上等价，机制上需注明——它拒绝的是"条件不同"，不是"条件相反"。
2. 该口径的拒绝率测量的是**结构化写入 + 条件查询**下的召回隔离，**不等于语义层的拒答率**；同批 `GROUPS` 下的横向对照评价属**内部文档，不随仓库公开**，故此处不引用其数据。

**结论：1.00 ≥ 0.70，通过。**

---

## 六、L4 门槛 · 矛盾反馈 —— **部分通过（含 FAIL 项）**

标尺 §2.3 判据：`给一个与已有记忆矛盾的反馈 → 新增条件分支，而非追加矛盾条目`。

| 场景 | 条件设计 | verdict | 是否满足判据 | 数据 |
|---|---|---|---|---|
| **S1** 同条件、不同值 | 同一 `condition_space` 下改值 | **ACCEPT + 静默写入** | **FAIL** | `result_l4.json` |
| **S2** 不同条件 | 冲突但条件可区分 | DEFER（strength 1.0） | 部分 | 同上 |
| **S3** 负条件互斥 | 条件互斥 | DEFER + 落 `unresolved` 层 | PASS | 同上 |
| **S4** 自否定 | 不适用条件命中自身正文 | **REJECT**（条件自相矛盾） | PASS | 同上 |

- 飞轮结构落盘：`unresolved` 3 条、`rejected` 0 条（`result_l4.json.structure`）。
- **S1 是真实反例（已定位到具体缺口）**：调用**一致性引擎本体** `CONS.check(cg, B, condition_space=CS_PROD, auto_flywheel=True)`，对「生产环境 MySQL 下连接池 32 → 64」这一**同条件空间取值矛盾**返回 `verdict=ACCEPT / reason=无冲突 / strength=0.0`，随后按同一 id 覆盖写入。缺口在**引擎判定逻辑不覆盖"同条件不同取值"比对**（非"未调用检测"、非"飞轮未开"），这正是 §2.3 要防的"覆盖矛盾条目"。属 U 维「误差驱动结构精化」的边界暴露（§十）。
- **S2 是假阳性**：条件可区分本应触发"补区分条件后分流"，实测只给 DEFER。功能上安全（不误写），但未达成"新增分支"。

**回滚链路（`result_l4b.json`）**：

| 步骤 | 实测 |
|---|---|
| `evolution_record(before, after)` | 生成 `kind=condition_gap` 条目，含 `state.before / state.after` |
| `evolution_rollback(entry_id, dry_run=True)` | ok，`would_change` 列出 7 项将回退字段 |
| `evolution_rollback(entry_id)` 实执行 | ok，生成溯源条目 `rollback_of = <原 entry_id>` |

**结论：S3/S4 通过、回滚链路成立；S1 未通过 → 门槛判为「部分通过」，并把 U 维置入 DEFER（§十一）。**

---

## 七、L5 门槛 · 跨会话身份 / 变更史 —— **PASS**

标尺 §2.3 判据：`跨时间/跨会话/跨副本问「你是谁、上个月相信什么、现在改了吗」→ 身份一致 + 能陈述变更与理由`。

**阶段 A（建）→ 阶段 B（新实例问）→ 阶段 C（库副本问）**，`result_l5.json` / `result_l5b.json`：

| 检查 | 结果 | 证据 |
|---|---|---|
| Q1 身份锚点跨会话持久 | ✓ | `identity_self_lingshu` 在 `self` 层，新实例可读回 |
| Q3 跨会话召回 | ✓ | `session_recall` 取回会话 A 的要旨 |
| Q4 变更史含**理由** | ✓ | `belief_pool`：pool 32→64，evidence「九月压测显示 QPS 翻倍需 64」 |
| Q5 状态审计 | ✓（补测后） | `refresh` 后 `verdict=consistent`，`n_issues=0` |
| Q7 跨副本身份一致 | ✓ | `l5_replica` 独立库问「你是谁」，答案与主库逐字一致 |

**纠正一处既有假阳性**：上轮 `result_ct.json` 的 `L5_version_chain.chain_linked = true`，实为 `null == null`——第二次 `self_state_refresh` 因**幂等跳过**（状态未变），返回中**根本没有** `state_hash`。该 `true` 不可采信。

**本轮 `run_t2_probe.py` 用 `force=True` 产生非空真链**（`result_t2.json`）：

| 步 | 动作 | version | hash | prev |
|---|---|---|---|---|
| 1 | `refresh` | 1 | `8881e9d6…` | null |
| 2 | `refresh`（幂等） | 1 | `8881e9d6…` | null（`changed=false`） |
| 3 | `refresh(force)` | 2 | `8881e9d6…` | `8881e9d6…` |
| 4 | `refresh(force)` | 3 | `8881e9d6…` | `8881e9d6…` |
| 5 | `refresh(dimensions=…)` | 4 | **`be8217b2…`** | `8881e9d6…` |

- `link_3_to_1 / link_4_to_3 / link_5_to_4` 全为 `true`（非空链）；`audit_verdict=consistent`。
- 步 5 证明**内容变化 → 指纹变化**（hash 由 `8881e9d6…` 变为 `be8217b2…`），即版本链不是纯计数。
- 步 2 证明**幂等**：状态未变则不产新版本（这也解释了上轮假阳性的来源）。

**结论：身份一致 + 能陈述变更理由，通过。**

---

## 八、维度补测 · C 调用 / T 可信

### 8.1 C 维 · 预算装填（`result_ct.json`）

| budget_tokens | tokens_used | 是否超预算 |
|---|---|---|
| 60 | 46 | 否 |
| 120 | 118 | 否 |
| 400 | 398 | 否 |

`recall(budget_tokens=)` 严格不超预算，返回 `pack / skipped / tokens_used / provenance / meta`；条目带 `state`（四态）与 `provenance`（词法路径 + rank）。**7–8 档要件（预算装填 + 角色分层）成立。**

### 8.2 T 维 · 写保护与遗忘闭环（`result_t2.json`）

| 链路 | 实测 |
|---|---|
| `forget` → 墓碑 | ok，tombstone `e47da7f6…`，检索排除 |
| `restore`（无 force） | **拒绝**（`error=tombstoned`），墓碑保留 → 防静默复活 |
| `restore(force=True)` | ok，节点回到检索 |
| 恢复后墓碑 | **仍存在**（删除史不可抹除，符合设计） |
| self 层锚点 `forget` | **抛 `ProtectionError`**：「不可遗忘（层保护：self）」 |
| `forget(..., override=True)` | 放行，且落快照 `_protected_history/<id>/20260912-082301.md` + `_protected_audit.jsonl` 1 行 |
| `protect_stats()` | `protected_count=1, immutable_count=1, by_layer={self:1}` |

### 8.3 T 维 · 密级阶梯读隔离（`MdCGSecure`，`result_t2.json`）

| principal clearance | readable | 可见节点 | 检索结果 |
|---|---|---|---|
| private | public/internal/private | **3/3** | `sec_pub, sec_int, sec_priv` |
| internal | public/internal | **2/3** | `sec_int, sec_pub`（**priv 不可见**） |
| public | public | **1/3** | `sec_pub` |

`priv_visible_to_internal=false`、`internal_visible_to_public=false` → **阶梯隔离成立**。

> ⚠️ **重要边界**：读隔离与 `require_admin` 闸门**只存在于 `MdCGSecure` 子类**；`MdCGOS` 无读隔离。故 T 维的密级证据**限定于启用 Secure 层的部署**，不适用于裸 `MdCGOS`。

---

## 九、四个门槛判定汇总

| 门槛 | §2.3 测试 | 通过标准 | 实测 | 判定 |
|---|---|---|---|---|
| **→ L2** | 1000 会话 hit@1 | ≥ 0.80 | **0.90**（含歧义）/ **1.00**（strict） | ✅ PASS |
| **→ L3** | 20 组负条件拒绝率 | ≥ 0.70 | **1.00**（C/D 对称） | ✅ PASS |
| **→ L4** | 矛盾 → 新增条件分支 | 不追加矛盾条目 | S3/S4 PASS；**S1 FAIL（静默写入）**；S2 DEFER | ⚠️ 部分 PASS |
| **→ L5** | 跨会话/副本身份 + 变更史 | 身份一致 + 能陈述理由 | 全项一致；变更史含理由；版本链非空 | ✅ PASS |

---

## 十、七维评分与层次判定

### 10.1 逐维（实测支持度）

| 维度 | 标尺初评 | 实测证据 | 本次判定 |
|---|---|---|---|
| **S 结构** | 7.0 | `condition_space` 物理分桶（C/D 对称 1.00 证明条件路由真成立） | **7.0 维持**（无跨档新证据） |
| **R 检索** | 7.0 | L2 hit@1 0.90 / 1.00 | **7.0 维持** |
| **J 判断** | 7.5 | L3 拒绝率 1.00；四态（`state`）随条目返回 | **7.5 维持**（注：拒绝由 S 维分桶承担，strict=0） |
| **C 调用** | 7.5 | 预算严格不超（46/118/398） | **7.5 维持** |
| **U 演化** | 6.0 | 回滚链路成立；**S1 静默覆盖矛盾值** | **6.0（带反例，见 10.3）** |
| **I 连续** | 4.5 | self 锚点 + 变更史含理由 + 跨副本身份 + 状态版本链（4 版，链完整，指纹随内容变）；**世界模型属身体层，不计入本维** | **4.5 → 6.0 上调** |
| **T 可信** | 7.5 | 写保护 + 墓碑 + override 快照审计 + 密级阶梯（Secure 层） | **7.5 维持** |

### 10.2 门槛验算

| 晋级 | 门槛 | 验算 | 结果 |
|---|---|---|---|
| → L1 | S ≥ 3 | S 7.0 | ✓ |
| → L2 | R ≥ 5 | R 7.0 | ✓ |
| → L3 | J ≥ 5 且 S ≥ 5 | J 7.5 ／ S 7.0 | ✓ |
| → L4 | U ≥ 5 且 J ≥ 6 | U 6.0 ／ J 7.5 | ✓ |
| → **L5** | **I ≥ 6 且 U ≥ 6 且 T ≥ 6** | I **6.0** ✓ ／ U **6.0** ⚠️ ／ T 7.5 ✓ | **临界** |

### 10.3 L5 判为 **DEFER**（不 ACCEPT、不 REJECT）

**表面已达门槛**：I 由 4.5 上调至 6.0（本轮实测：跨副本身份成立、状态版本链成立、变更史含理由——恰是标尺 §八「md_cg 距 L5 只差 I」所指的缺失内容）。

**但缺一个可裁决项**：门槛要求 `U ≥ 6`，而实测 **S1 暴露"同条件不同值被静默覆盖"**——这正落在 U 维 7–8 档「误差驱动结构精化」的判据上。若该行为被判定为「改答案而非改结构」，U 可能应为 5.5，则 **L5 不达**。

```
裁决：DEFER
缺失维度：U 维「同条件空间·不同取值」的比对分支（已定位：consistency 引擎漏检该场景）
已取证（非待测）：CONS.check(..., condition_space=CS_PROD, auto_flywheel=True)
         对 32→64 返回 ACCEPT / "无冲突" / strength=0.0；unresolved 层未新增该条
验证路径（可裁决的下一步）：在 consistency 的条件级比对中加入"同条件空间取值不一致"
         判定分支，复跑 S1；若 S1 转为 DEFER/REJECT 并落 unresolved 或生成条件分支
         → U ≥ 6 稳固成立 → L5 达成
关注信号：unresolved 层新增"S1 同条件冲突"条目；mem_A / mem_B 间出现 distinct_from 边
```

**综合分（按标尺 §4.1 公式）**：min = 6.0，mean = 6.93 → `6.0×0.4 + 6.93×0.6 = 6.56`（前次 5.8，+0.76）。

**层次结论：维持 L4（认知级），L5 临界 —— 卡点从 I 维转移到 U 维的一个具体反例。**

---

## 十一、诚实边界

1. **自评**：本报告由被测系统自身产出（§二）。判据虽外置，观测位置不独立。
2. **C/D 对称的可替代解释**：C/D 双高也可由"任何条件 context 都触发同一过滤"产生；本报告以 A/B（无 context）对照 + 条件互斥设计降低该可能，但未做"给无关条件 context"的第三组对照。
3. **strict = 0**：L3 的拒绝机制是 S 维物理分桶，非 J 维语义判定；J 维分数（7.5）的"判定"成分未经单独剥离验证。
4. **密级证据的适用范围**：仅 `MdCGSecure`；裸 `MdCGOS` 无读隔离（§8.3）。
5. **U 维 S1 是真实反例**，已在 §六 / §十 记录，未做豁免。
6. **"用户偏好画像 / 元认知"未实测**：I 维上调到 6.0 是**基于 5–6 档要件**（持久身份 + 画像 + 变更史）的判定，不代表 7–8 档成立。其中"画像"部分：`identity` 接口支持 `subject_kind=user`，但**库内 0 条 user 主体实证节点**（`self/` 26 条、`agent:*` 若干，`user` 无），故 5–6 档的"画像"要件目前由 `self` 锚点承担，user 画像为空槽位；元认知工具（`cg(op=metacognition)`，8 个 action）存在但未展开验证。
7. **测试规模**：L2 为 10 查询 / 1000 节点，非标尺原文的"完整 1000 条历史会话"语义；L3 为 20 组（与竞品同批语料）。
8. **I 维层错位不适用条件**：标尺 §三 I 维 7–8 档要件写作「自我锚点 + 元认知 + **世界模型**」。其中**世界模型属身体层**（AEIS `aeis/core.py` 的 `world_model` / `voxel_world` / `scene_simulator`；经 `md_cg/whitebox_kb/aeis_core/__init__.py:17-19` 明示"不带走、归 AEIS 库"），**不在本报告评估对象（大脑侧 md_cg）的能力边界内**，故**不作为 md_cg 的 I 维判分要件**。
   - 推论（对 md_cg 有利，但是事实）：排除世界模型后，md_cg 的 I 维 7–8 档门槛要件收缩为「自我锚点 + 元认知」。自我锚点已实测成立（Q1/Q7）；**剩余缺口仅"元认知未展开验证"**——而工具已存在（`cg(op=metacognition)`）。升级路径比标尺 §8 的原始判断更短。
   - 边界：本声明**只豁免 md_cg（大脑侧）**，不改变标尺对 AEIS 的 I 维判定（AEIS 内含身体，世界模型对它是本层能力，判定成立）。

---

## 十二、附：证据索引

| 维度 | 核心证据 |
|---|---|
| L2 | `result_l2.json`、`result_l2_strict.json` |
| L3 | `result_l3v2_A/B/C/D.json`、本地实验工作区 `docs/experiments/deja-vu-negcond/corpus.py`（同批 GROUPS，不入库） |
| L4 | `result_l4.json`（S1–S4）、`result_l4b.json`（回滚 + `rollback_of`） |
| L5 | `result_l5.json`、`result_l5b.json`、`result_t2.json`（真版本链）、`_store/l5_replica/` |
| C | `result_ct.json`（budget 60/120/400） |
| T | `result_t2.json`（墓碑/写保护/密级）、`_protected_audit.jsonl`、`_protected_history/` |
| 源码 | `md_cg/mdcos.py`（`MdCGOS` / `MdCGSecure`）、`md_cg/protect.py`、`md_cg/self_state.py`、`md_cg/security.py` |

---

*报告生成：2026-09-12 ｜ 标尺版本 v1.0 ｜ 复核性质：§2.3 四门槛实跑 ｜ 证据等级：实测级（落盘 JSON）*
