# md_cg · AGI 七维评分报告 v1.0

> 评分对象：**dsh-memory / md_cg（认知图 + 记忆 OS）** 当前实现（2026-09-10）
> 评分标尺：`AEIS/docs/AGI记忆系统评分标尺_v1.0.md`（七维 · 层次优先 · 门槛晋级）
> 综合公式：`综合 = min × 0.4 + mean × 0.6`
> 取证：源码级（`md_cg/*.py` 逐模块核对）+ 测试级（P0–P19 共 21 套 **809 项** + 并发锁 **300 项** 全绿）
> 立场：不虚高、不虚低。每分给依据；无法验证的项单列、不计分。

---

## 一、结论

| 维度 | 得分 | 档位 | 一句话依据 |
|---|---|---|---|
| **S 结构** | **8.5** | 认知图（四要素 3.5/4） | 条件空间 + **嵌套子图递归** + 负条件 + execution；conditions/execution 未完全强制 |
| **R 检索** | **8.5** | 因果路由 ✓ / 意图理解 △ | 多路 RRF + 条件级负路由 + `chain.py` 13 类边 + `predict` 沿因果链生成未预写路径；意图理解仍是规则层 |
| **J 判断** | **9.0** | 独立元认知 + 主动遗忘 | 四态判定 + 验证基底 + 负记忆 + 主动遗忘闸门 + 冲突检测 + 独立元认知（四观测面） |
| **C 调用** | **8.5** | 精准注入（非零污染） | 预算装填 + role 分层 + 记忆自净 `scrub.py`；抽样式去污染、无 SNR 仪表盘 |
| **U 演化** | **7.5** | 误差驱动结构精化 | 飞轮自动触发 + `consolidate.py` 提炼条件维度；提炼器未接 MCP、回滚靠 git/快照 |
| **I 连续** | **8.0** | 自我锚点 + 元认知 + 世界模型 | self/anchor 层 + `identity.py` + `self_state.py` + `stg.py` 时空 + 跨副本身份指纹 |
| **T 可信** | **8.5** | 加密 + 全链路审计 + 信任可度量 | ChaCha20-Poly1305（KEK/DEK + AAD 身份绑定 + fail-closed）+ payload-free 审计 + P_trust；零信任未落地 |

```
min  = 7.5   (U)
mean = 8.357 (S8.5 R8.5 J9.0 C8.5 U7.5 I8.0 T8.5)
综合 = 7.5 × 0.4 + 8.357 × 0.6 = 8.0
```

### 层次判定：**L5（AGI 级记忆）· 入门**

| 晋级 | 门槛 | 实测 | 结论 |
|---|---|---|---|
| → L3 | J ≥ 5 且 S ≥ 5 | 9.0 / 8.5 | ✅ |
| → L4 | U ≥ 5 且 J ≥ 6 | 7.5 / 9.0 | ✅ |
| → **L5** | **I ≥ 6 且 U ≥ 6 且 T ≥ 6** | **8.0 / 7.5 / 8.5** | ✅ |

**五问定层法复核**（标尺 §2.2）：

```
Q1 能存吗？              ✅ 五层 + 负记忆 + 目标槽 + 子图
Q2 能从一堆里找对那条？   ✅ 四路 RRF + 条件路由 + 因果链
Q3 能说「这条不该用」吗？ ✅ 四态判定 / 条件级负路由 / 负记忆
Q4 说错后改结构还是改答案？✅ 改结构（consolidate 提炼条件维度 + verify 降级 + 冲突→飞轮）
Q5 一个月后还是同一个「我」吗？✅ self/anchor 层不可覆盖 + identity 锚点 + self_state 变更史
```

> 判为 **L5 入门**（标尺 §4.3：L5 区间 7.5–10，入门段）。距「长期压力验证的 L5」仍有距离，见 §五。

---

## 二、逐维依据

### S · 结构 · 8.5

**加分**：`condition_space` 写入强制补 `time_window`、条件分桶物理落盘（`routing.route_key`）；`non_applicable_conditions` + `has_non_applicable()`（`mdcg.py:348/465`）；`subgraph.py` 全套嵌套递归（`declared/children/parents/expand/flatten/roots/validate`，带 `max_depth/max_nodes` 与缓存，L29–L215）；execution 经 CCG 行映射（`consolidate.py:84`）；`_move_layer` 层间降级（`mdcg.py:1038`）；一等字段 `modality`（L439）；`scrub` 按陈旧度 weaken/demote（可逆）。

**扣分**：① conditions 理论四维只有 `time_window` 强制；② execution 非一等 frontmatter（无 schema 校验）；③ 衰减走抽样判陈旧，非连续时间因子。

> 7–8 档「图结构 + 条件绑定」完全达标，`subgraph`/`modality` 属 9 档构成项 → **8.5**。

### R · 检索 · 8.5

**加分**：`search_rrf` 四路融合且 `per_path` 可审计（`mdcos.py:642`）；条件级负路由 `_neg_hit`（L162）+ 条件槽重叠 `_slot_overlap`（L193）；`chain.py` 13 类边 + `walk/explain/expand_from_seeds`（边权 × `decay^跳`）；**`predict.routes` 沿因果链生成未预写路径**（L446）+ `causal_path` BFS（L644）+ 伪因果过滤门（L152）；`_path_goal/_path_fuzzy/_path_semantic`；tier（怎么找到）与 state（该不该用）正交。

**扣分**：意图理解仍是确定性规则（归一化 + 目标定向 + `route()` 建议能力名），非开放域 LLM 理解；有意剔除神经嵌入（取向而非短板）。

> 9–10 档要求「因果路由 + 意图理解」齐备——因果已达标，意图仅规则层 → **8.5**。

### J · 判断 · 9.0

**加分**：四态 ACCEPT/REJECT/DEFER/BLINDSPOT（`mdcg.py:713–724`）；`verification_basis` 白名单 + 反例非对称权重（confirmed +0.05 / weakened −0.15，跌破即降级，L1025–1050）；负记忆 `rejected/` + `unresolved/`；**主动遗忘闸门** `forgetting.assess` 三问→四态、全量留痕（L182）+ `remember_gated` 写入前置裁决（`mdcos.py:1306`）；`consistency.py` 三级决策（L0 情绪→L1 反思→L2 递归反思）且冲突**自动投递飞轮**；**独立元认知** `metacognition.py` 四观测面（`trace` L123 / `calibration`+ECE L167 / `blindspots` L248 / `trust` L301）+ 闸门 `self_check`（L427），独立性三重约束（不参与裁决 / 独立 jsonl / 独立入口）；`predict.feedback` 命中校准（L583）。

**扣分**：① 主判定路径 REJECT 仍简化版（`mdcg.py:713` 自注关键词命中），与 `consistency.py` 条件级判定未统一；② 元认知只建议不执行；③ D-006 预测反馈需显式调用、未联动。

> 9–10 档门槛项「独立元认知 + 主动遗忘」齐备且有测试 → **9.0**（三条扣分使其停在 9.0）。

### C · 调用 · 8.5

**加分**：`recall(query, budget_tokens)` 预算装填、超大条目跳过而非停下（`mdcos.py:759`）；role 分层索引（工具输出/命令/编辑不进正排，砍掉最大噪声源）；重要性 + 置信度双参数排序，负记忆不污染正排；写入侧 DROP/MERGE；`scrub.py` 分层抽样 + 5 类污染判据 → 可逆去污染 + 幂等留痕，受保护节点跳过、永不删除（L479/L572/L685/L733）。

**扣分**：① 无 SNR 量化仪表盘；② 去污染是 12/轮抽样 + 确定性判据，非穷尽语义蕴含 → 未达「零污染」；③ `_contradiction` 为词级比对，跨表述矛盾不可识别。

> 7–8 档「重要性评分 + 精准注入」扎实达标 → **8.5**。

### U · 演化 · 7.5

**加分**：`flywheel_step` + `mine_fix_pairs`（错误→修复对→knowledge/rejected）；**冲突自动投递飞轮**（`cg(op=write)` 内置 `auto_flywheel=True`，`mcp_server.py:1129`）；**`consolidate.py` 误差驱动结构精化**——LLM 从正文提炼 CCG 条件维度，经 `grounding_filter`（词根落地）+ `replay_check`（重放校验）后 `_apply_node` 回写条件结构（L387/L406/L475/L506）；md 单一真相源 + git 可 diff/回滚，`protect.snapshot` 存受保护节点历史（L146）。

**扣分**：① `consolidate` 仅 CLI 入口，`cg(op=...)` 无对应 op → 不在 agent 主循环，「自主演化」需人工/定时触发；② 无通用结构变更版本表/一键回滚（`protect` 只覆盖受保护节点）；③ 预测校准需人工喂反馈。

> 7–8 档核心「误差驱动结构精化」已实现（P6 72 项）→ **7.5**；9–10 档「飞轮自运转 + 结构版本可回滚」仅半程。

### I · 连续 · 8.0

**加分**：`self`/`anchor` 层不可遗忘、普通写入不能覆盖；`identity.py` — `set_anchor`/`add_trait`/`infer_position`（五单元位置效应投票）/`profile`/`history`（L155–L370）；`self_state.py` — `snapshot/refresh/relate/relations/index/dimensions/audit/history/bootstrap` + 状态指纹 `_fingerprint` + `trust_band`（L179/L379/L600/L785）；`metacognition.py` 四观测面；**世界模型** `stg.py` 时空关系/时间线/锚点/一致性（L55–L194）+ `condition_space` + `subgraph`；**跨副本身份** `crypto.identity_fingerprint(tenant, actor)` 绑进密钥 AAD（L219/225），跨身份读取即失败；角色一致性由 `roleplay_web` + `migrate_roleplay` 承载。

**扣分**：① `self_state.history` 是留痕/审计，非跨会话自我变更叙事；② 跨副本状态收敛/冲突合并无实测（指纹只解决「读不到」）；③ 元认知不写事实（设计如此）。

> 7–8 档三要素「自我锚点 + 元认知 + 世界模型」齐备且经 `cg(op=identity/self_state/metacognition)` 暴露 → **8.0**；9–10 档属未验证项。

### T · 可信 · 8.5

**加分**：四级密级 × clearance 三隔离（不可见即不存在 / secret 写入即拒 / 管理需 `can_admin`）；租户物理隔离（私有根落仓库外 + `_tenants.json` + `principal_for()` 夹上限）；**加密** `crypto.py` 纯标准库 ChaCha20-Poly1305（L51/L149）+ scrypt KEK + **KEK/DEK 分层**（L264/L291）+ **身份绑定 AAD**（L225/L229）+ **fail-closed**（无密钥抛 `LockedError`，不降级明文）+ 主密钥落仓库外；payload-free 审计（只记 `{t,op,id,actor,payload_hash}`）+ `_crypto.jsonl` + `_protected_audit.jsonl`；`scrub` 去污染 + `replay_check` 防重放注入；**信任可度量** `metacognition.trust` → `P_trust/P_gap` + 情感 `d²T/dt²`（L301）；tombstone + 恢复校验。

**扣分**：① 零信任未落地（主密钥仍在服务端进程可及，无远程身份校验/客户端持钥）；② 加密非严格 E2E（服务端可解密；密文不参与全文索引的工程折衷）；③ 威胁模型自认未覆盖本地内存取证/侧信道。

> 7–8 档「隐私树 + 全链路审计 + 记忆防污染」完全达标，加密 + P_trust 属 9 档构成项 → **8.5**，零信任缺位封顶。

---

## 三、与标尺 v1.0 原表对比（2026-09-09 → 2026-09-10）

| 维度 | 原表 | 本报告 | 变化来源 |
|---|---|---|---|
| S 结构 | 7.0 | **8.5** | `subgraph.py` 嵌套递归 · execution CCG 字段 · `modality` |
| R 检索 | 7.0 | **8.5** | `chain.py` 13 类边 · `predict.causal_path` · 条件级负路由 |
| J 判断 | 7.5 | **9.0** | `forgetting.py` · `consistency.py` · `metacognition.py` |
| C 调用 | 7.5 | **8.5** | `scrub.py` 记忆自净 · role 分层 · budget pack |
| **U 演化** | 6.0 | **7.5** | `consolidate.py` 条件维度提炼 · `predict.feedback` · `protect` 快照 |
| **I 连续** | 4.5 | **8.0** | `identity.py` · `self_state.py` · `metacognition.py` · `stg.py` · 跨副本身份指纹 |
| **T 可信** | 7.5 | **8.5** | `crypto.py` 加密栈 · P_trust |
| min / mean | 4.5 / 6.71 | **7.5 / 8.357** | |
| **综合** | **5.8** | **8.0** | |
| **层次** | L4 认知级 | **L5 入门** | I 越过 6 门槛，L5 三门槛（I/U/T）全达标 |

> 原表指出的 I 维短板「无元认知工具、无世界模型、无跨副本身份」，已分别由 `metacognition.py` / `stg.py` / `crypto.identity_fingerprint` 补齐。

---

## 四、测试取证

21 套功能测试 **809 项全绿** + 并发锁 **300 项全绿**：

```
P0 25 · P1 37 · P2 36 · P2-MCP 63 · P3 33 · P4 44 · P5 36 · P6 72 · P7 36
P8 34 · P9 37 · P10 24 · P11 27 · P12 32 · P13 42 · P14 44 · P15 53 · P16 46
P17 55 · P18 20 · P19 13      → 合计 809
test_lock 300/300
```

本报告引用的维度均有对应用例：J←P9/P11/P12，I←P10/P12/P14，T←P13，U←P6/P8/P17，S←P2/P4，R←P2/P8。

---

## 五、短板与到下一档的差距

| 维度 | 当前 | 到 9.5+ 需补 |
|---|---|---|
| U 演化 | 7.5 | `consolidate` 接入 `cg(op=...)` 进主循环；通用结构变更版本表 + 一键回滚；预测反馈自动联动 |
| I 连续 | 8.0 | 跨会话生命史叙述合成；跨副本状态收敛实测 |
| C 调用 | 8.5 | SNR 仪表盘；去污染从抽样→穷尽 + 语义蕴含级 |
| T 可信 | 8.5 | 零信任（远程身份校验 + 客户端持钥）；密文可检索方案 |
| R 检索 | 8.5 | 开放域意图理解（非规则） |
| S 结构 | 8.5 | conditions 四维强制 + execution 一等 schema |
| J 判断 | 9.0 | 主判定路径 REJECT 与 `consistency` 条件级判定统一 |

**最高优先级**：U（唯一的 7.5，拉低 min）。把 `consolidate` 包成 `cg(op=consolidate)` 即可同时抬升 U 的「自主演化」与 J 的结构闭环。

---

## 六、诚实边界声明

1. **U / I 无公开基准**：标尺自述「U / I 无公开基准，只能行为观察」。本报告的 8.0 / 7.5 属**代码能力判定**，非长周期实证；长期压力验证需真实运行数月。
2. **打分含主观性**：0.5 分粒度由评估者按判据落位，不同评估者可能 ±0.5。
3. **「能实现」≠「已验证」**：本报告区分二者，未验证项（跨副本收敛、长周期自我连续性）已单列在 §五，不计入分数。
4. **可证伪**：任一维度若发现反例（如某功能代码存在但不可调用、或测试造假），对应分数应下调。

---

*报告生成：2026-09-10 · 标尺：AGI记忆系统评分标尺_v1.0 · 取证脚本已清理*
