# DaoTi 项目吸纳分析（GitHub 外部感知 2026-09）

**项目**：zhibaiYingChuan/DaoTi（V53 道体基座，10★，Python，37MB）
**定位**：预训练神经网络语义基座——中文文本 → 结构化语义表征（编码向量/
洛书状态向量/64 维卦象原型向量）。双轨阶梯网络，消费级 CPU 训练。
**用户评价**：工程较简陋，仅供参考——但设计模式有吸纳价值。

## 三模式吸纳分析

### 1. 冻结道体 + LoRA 适配（与 §15 自举锚点同构）
**DaoTi**：核心参数预训练后冻结（"道体"），下游只训轻量适配器（LoRA）——
基于「退化基态」发现（投影层存在大量损失平坦方向 = 等价解共存）。
**映射**：我们的 BOOTSTRAP_ANCHORS（§15）就是「冻结核心」——不可再分原语
不参与路由；可路由能力（681 单元）=「适配层」。**同构确认**：
白箱的「冻结锚点 + 可路由能力」与神经网络的「冻结道体 + 适配器」是同一
范式（稳定基座 + 轻量扩展）。

### 2. coherence 一致性门槛（与 CCG 路由 ACCEPT 同构，可吸纳）
**DaoTi**（inference.py compute_coherence）：
```python
text_feat = model.encode_text(text_ids)
proto_n = normalize(model.gua_prototype.weight)   # 64 卦原型
similarity = mm(normalize(text_feat), proto_n.T)  # 输入 vs 候选卦 余弦
coherence = clamp(similarity.max(), 0, 1)          # 最高一致性
# generate_response 中 coherence_threshold=0.3 → 低于阈值不生成
```
**映射**：我们的 route ACCEPT 是硬规则（gap≥2 且命中词≥2 且有效词≥2）；
DaoTi 用**连续余弦相似度 + 阈值**决定「生成还是不生成」。
**吸纳点**：CCG 路由加 **coherence 置信度**——命中分数归一化为 [0,1]
连续置信度，上层（escalation/执行计划）可设阈值决策。

### 3. 卦象 = 结构化语义原语空间（与能力单元同构）
**DaoTi**：64 卦 × action 语义（乾-initiate/decide、离-illuminate/discriminate/
detect/track、坎-flow/grip/release…）——离散、有结构关系的语义动作通道。
**映射**：我们的 681 能力单元（六域 × 任务）就是「能力原语空间」；
CCG 的域/任务分层 = 卦象的宫/卦分层（BA_GONG 八宫 × 64 卦）。
**同构确认**：语义离散化 + 结构化组织是共同模式。

## 吸纳决策

| DaoTi 模式 | 映射 | 落地 |
|---|---|---|
| 冻结道体+适配器 | §15 锚点 + 可路由能力 | 已实现（确认同构） |
| **coherence 阈值** | **CCG 路由置信度** | **本轮落地** |
| 卦象语义原语 | 681 能力单元 | 已实现（确认同构） |

## 本轮落地：CCG 路由置信度（coherence）

route ACCEPT 增加连续置信度字段（不改变硬规则判定——兼容）：
```python
confidence = top1_score / max_score  # 归一化 [0,1] 连续置信度
```
供 escalation/执行计划按阈值决策（如 confidence < 0.4 → 即使 ACCEPT 也
标注低置信，上层可降级为 DEFER/人工确认）。
