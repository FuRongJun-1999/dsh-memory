# 落地记录：S4 五层激活优先级（anchor/self 先激活）

- 候选分支：`task/iter-retr-s4`（tip `729e846`，1 个提交）
- 落地方式：**fast-forward 推送**（base == origin/main；+1 提交，**0 删除**）
- 落地后 origin/main：`729e846`；里程碑标签：`core-retr-s4`
- 落地判据：内部独立复核 **首轮 ACCEPT** ∧ 零删除 ∧ 干净树回归绿（`md_cg` 组 92/92，3 跳过）

## 1. 做了什么（契约 §3 S4）

五层（anchor/structural/knowledge/contextual/self）此前只是 `layer` 字段的等值过滤（审计偏差 3：
「层级从认知优先级退化成分类标签」）。本阶段把它变成**激活优先级加成**：

- 加成表默认：`anchor 0.20 / self 0.20 / structural 0.15 / knowledge 0.10 / contextual 0.05`；
- 位置：`_score()` **评分末端**加上加成并夹 `1.0`（加性，不改乘性分池权重）；
- 语义：**只改初始激活值/排序，不改变任何门控**——被 S1/S2 剔除的节点不会因加成回归（有专门断言）；
- 可配置：`MDCG_LAYER_BOOST="anchor=0.3,knowledge=0.05"`（部分覆盖，未提及的层取默认；非法项忽略、负值夹 0）；
- 审计：`meta.gates.s4 = {boosts: <表>, layers: {层: 候选数}}`。

## 2. 开关（显式启用）

| 开关 | 默认 | 说明 |
| --- | --- | --- |
| `MDCG_RETRIEVAL_PIPELINE` | 0 | 总开关 |
| `MDCG_GATE_S4_LAYER` | **0** | 必须显式 =1（新增加成会改变排序，属显式启用项） |
| `MDCG_LAYER_BOOST` | 见上 | 层级加成表（部分覆盖） |

## 3. 测试证据

- `python -X utf8 -m md_cg.test_retr_s4` → **13 断言全通过**：解析器（默认副本/部分覆盖/非法项/负值夹 0）、
  默认关无 `gates` 键、子开关未设不生效、同内容各层分数相同（默认关）、层级次序
  `anchor/self > structural > knowledge > contextual`、加成上限 ≤1.0、自定义表改变次序、
  **S2 拦掉的节点不因 S4 回归**、重复检索与索引重建幂等、关→开→关 等价。
- `python -X utf8 scripts/run_tests.py md_cg --jobs 4` → **92/92 通过**（3 跳过）。

## 4. 回退

关掉 `MDCG_GATE_S4_LAYER`（或总开关）即回原行为；或 `git revert 729e846`。

## 5. 进度（契约 §2）

S1 大域收敛 ✅（`core-retr-s1`）→ S2 条件前置门控 ✅（同批）→ S3 图扩散激活 ✅（`core-retr-s3`）
→ **S4 五层激活优先级 ✅（本记录 `core-retr-s4`）** → 待做：S5 负记忆抑制信号、S6 一致性交叉验证。
