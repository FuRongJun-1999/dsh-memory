# gliding_horse 项目吸纳分析（GitHub 外部感知 2026-09）

**项目**：doiito/gliding_horse（Gliding Horse Agent OS，134★，Rust，10MB）
**定位**：工业级 AI Agent 操作系统——PDCA 7 层自适应执行 + 知识图谱 agent
（Oxigraph）+ 技能图谱（JSON-LD），企业级。v0.1.4 重构：85 文件 +6134/−4127。
**亮点**：模块化（3408 行 sa/mod.rs 拆 8 模块）、统一时间线（指数时间衰减）、
5W2H 维度审计（Pass/Warning/Fail + CausalEngine 根因链）、KG 上下文注入、
LLRU 冷归档（技能图分级存储）。

## 与白箱体系的同构

| gliding_horse | 白箱体系 | 同构点 |
|---|---|---|
| PDCA 7 层自适应执行 | 八步闭环（§18/§19） | 计划-执行-检查-行动 ≡ 感知-固化-验证-反馈 |
| SkillGraph（JSON-LD 技能图谱） | skills.json + skills_cond（§17.4） | 技能知识图谱化 |
| 5W2H 技能描述 | 适用条件/不适用条件 | when=适用时机（比我们多维度） |
| CausalEngine 根因分析 | 方向性自检 PASS/FAIL | 他们失败维度进因果链（我们缺根因链） |
| 时间衰减重排 apply_time_decay | iteration_trace 线性 | 他们指数衰减（我们缺时间权重） |
| BootstrapEngine 自举学习 | 自迭代八步闭环 | 学习来源同构（任务/错误/反馈/审查） |

## 可吸纳的独特机制（本轮决策）

### 1. SkillLink 技能关系边（6 种）——吸纳
Prerequisite / Composition / Related / Alternative / Extends / Generalization
→ 我们的 skills.json 是平的，缺技能间关系。**本轮落地**：加技能关系边
（Related 关联 / Alternative 替代 / Prerequisite 前置），条件路由可沿边
扩展（技能组合/替代路由）。

### 2. SkillEvolution Reduce（简化过复杂技能）——待实现
使用追踪 + 进化建议（Learn/Reduce）——我们只有吸收没有简化。

### 3. 时间衰减重排——待实现
记忆/轨迹召回按指数时间衰减（λ=0.5）——我们轨迹是线性。

### 4. 5W2H 技能描述——理论映射
what/why/who/when/where/how/how_much——when 对应我们的适用时机；其余
维度补全技能声明（§17.4 技能条件化扩展方向）。

## 本轮落地：技能关系边（SkillLink）

skills.json 技能节点增加 `links`（关系边）：
```json
{"skill": "...", "适用条件": [...], "不适用条件": [...],
 "links": [{"target": "不适用条件-越界：...", "type": "Related"},
           {"target": "...", "type": "Alternative"}]}
```
skills_cond 条件路由支持沿 Related 边扩展（相关技能一并提示）。
