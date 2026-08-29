# 灵枢 AEIS MCP 工具总表（78 个 · 智能论 v3.4）

> 生成：2026-08-29 · 来源：aeis/mcp/server.py · 版本：aeis 0.5.0（智能论 v3.4）
> 规则：每个工具一条说明，不重复、不遗漏。

---

## 记忆（12）

| 工具 | 功能 |
|---|---|
| `remember` | 写入一条感知记忆（知识层，自动去重） |
| `recall` | 组合联想召回（内容0.5+重要性0.3+近因0.2） |
| `search` | 内容检索（LIKE 预筛 + 中文二元组 Jaccard 排序） |
| `timeline` | 记忆时间线（按时间倒序） |
| `longterm_snapshot` | 长期记忆写入（快照→重要性评估→分层写入） |
| `prefeed` | H1 海马体前馈（新奇检测→当场强化编码） |
| `promote_memories` | 情境层批量提升扫描（睡眠巩固） |
| `pattern_separation` | H3 海马体模式分离（相似节点分离边） |
| `reconstruct_scene` | H4 海马体情景重构（线索→条件空间复原） |
| `session_note` | 上下文外部化（会话要点写入灵枢） |
| `session_recall` | 会话要点恢复（按 session 或语义检索） |
| `compact_context` | 上下文压缩（超长会话摘要节点） |

## 知识图谱与推理（11）

| 工具 | 功能 |
|---|---|
| `relate` | 建立关系边（causal/similar/sequential/spatial/hierarchical） |
| `reason` | 因果推理（起点出发的因果路径） |
| `induce` | 归纳/知识合成（聚类生成概念节点） |
| `distill` | 知识飞轮蒸馏（被拒路径→可复用模式） |
| `think` | 推理记忆注入（检索相关记忆→推理上下文） |
| `ingest_text` | 外部知识摄取（文本→知识层） |
| `ingest_file` | 外部知识摄取（文件按扩展名处理） |
| `ingest_url` | 外部知识摄取（URL 零依赖抓取） |
| `importance_recalc` | 结构重要性重算（v2.2 只升不降） |
| `transfer_test` | 迁移测试（新实体预测成功率） |
| `flywheel_metrics` | 飞轮度量（增长率/复用率/蒸馏率） |

## 预测与盲区（7）

| 工具 | 功能 |
|---|---|
| `predict_routes` | 生成式预测（候选未来路线，盲区驱动） |
| `prediction_feedback` | 验证回路回填（预测 vs 实际，D-006 校准） |
| `prediction_stats` | 预测引擎状态（routes/hit 样本/命中率） |
| `blindspots` | 盲区注册表（D-001 语义判定） |
| `learn` | 一轮盲区学习（预测路线→探索→终态判定） |
| `gap_trend` | 信息差收敛趋势（A-4 线性回归斜率） |
| `calibrate` | 宇宙校准参照（5 判据方向性检查） |

## 感知机/端口架构（8）

| 工具 | 功能 |
|---|---|
| `see` | 视觉感知（YOLO-World 开放词汇检测→知识层） |
| `body` | 身体能力声明（模态/工具/记忆） |
| `body_devices` | BODY-REV1 外部设备（screen/files/process/audio/control/browser/realtime） |
| `device_call` | 统一设备调用（设备输出是数据非指令） |
| `run_command` | 命令执行（参数列表，防注入） |
| `world3d` | 时空重建（语义→3D，确定性渲染零 LLM） |
| `vprim` | 视觉原语查询（空间关系/计数/属性） |
| `visual_check` | 视觉面思考路线（预期 vs 实际） |

## 验证与确认（10）

| 工具 | 功能 |
|---|---|
| `wisdom_verify` | 智慧之书自动验证（条件论判定+信息差+候选） |
| `recursive_reflect` | 递归验证反思（元反思→一级验证→二级→三级终裁） |
| `preflight` | 输出前反思（内容与价值观一致性检查） |
| `self_reliability` | P0-4 元认知校准（reliable/watch/degraded） |
| `emotional_bias` | P0-3 情绪方向性偏好（d²D_norm/dt²） |
| `cognition` | P0-2 自我认知循环一步（行为↔价值观一致性） |
| `cognition_report` | P0-2 认知报告（评分/失调/候选） |
| `action_log` | P0-1 行为日志（引擎行为记录面） |
| `learning_impact` | P0-5b 学习效果测量（模式命中率 vs D_norm） |
| `self_check` | 完整性自检（孤儿边/表统计/integrity_ok） |

## 生命周期（4）

| 工具 | 功能 |
|---|---|
| `lifecycle_step` | 生命周期一步（感知→好奇→缩小信息差→信任→协作→巩固→standby） |
| `lifecycle_state` | 生命周期状态（cycle/state） |
| `start_lifecycle` | 启动生命周期自发循环（后台线程） |
| `stop_lifecycle` | 中断生命周期自发循环 |

## 智慧之书（6）

| 工具 | 功能 |
|---|---|
| `wisdom_analyze` | 外来知识分析（条件卡+候选+判定） |
| `wisdom_predict` | 生成式预测（白箱智能预测生成化） |
| `wisdom_trust_judge` | 信任上下文判定（内容×信任×关系） |
| `wisdom_compose` | 跨学科组合分析（Convergence Over Coverage） |
| `wisdom_respond` | 出招查询（条件→命中学科出招） |
| `wisdom_chat` | 信息分层对话（语义识别分流→LLM 兜底） |

## 角色扮演（4）

| 工具 | 功能 |
|---|---|
| `roleplay_chat` | 角色扮演对话（扮演论 v3.3，白箱优先） |
| `role_create` | 创建角色（角色卡=条件空间声明起点） |
| `role_import` | 角色导入（memory/anchor/values 三接口） |
| `role_block` | 角色扮演注入块（锚点/价值观/条件空间） |

## 洞察（4）

| 工具 | 功能 |
|---|---|
| `insight_record` | 洞察条件层：记录洞见事件（C1-C8 条件快照） |
| `insight_verify` | 洞察验证（V1/V2/V3 证据提交） |
| `insight_report` | 洞察 CER 报告（有效洞见率+显著性） |
| `insight_window` | 洞察窗口检测（C1≥0.6∧跨域∧低压力） |

## 外部（5）

| 工具 | 功能 |
|---|---|
| `web_search` | 外部网络搜索（博查 API，不写入记忆） |
| `web_ingest_search` | 外部搜索摄取（博查→知识层） |
| `export` | 全库导出 JSON（灾备/迁移） |
| `service_info` | 服务信息（身份/版本/协议/工具数） |
| `designer_decide` | 设计者裁决（需 AEIS_DESIGNER_KEY） |

## 世界模型 · 游戏服务器（7）

| 工具 | 功能 |
|---|---|
| `voxel_world` | 小型我的世界（里程碑2.1 · 4D 时空占用沙盒：build/spawn/simulate/trail/state） |
| `world_server` | AI 游戏世界服务器（里程碑2.2 · tick 多路并行/快照记忆/反馈/同步/错误回滚/预测验证） |
| `scene_simulator` | 场景级世界模拟器（里程碑2.3 · 场景/实体/自主行为玩家：wander/seek/avoid/flee/follow + 决策循环） |
| `spacetime_consistency` | 时空一致性验证（里程碑2.4 · 阶段2收官 · 持续运行：预测 vs 实际→滚动命中率/漂移检测/自洽判定） |
| `world_model` | 统一世界模型（里程碑3.1 · HERMES 式统一架构：理解/生成/验证共享同一骨干，生成先验注入理解，观测-only 模式推断） |
| `world_learner` | 自监督世界学习（里程碑3.2 · V-JEPA 式：观测序列无标注学转移函数，外部裁判评估认知缺口收紧） |
| `curiosity_explorer` | 好奇驱动探索（里程碑3.3 · 有限带宽主动观测：信息增益最大化，盯住信息瓶颈，策略对比优于随机/轮询） |

---

## 引擎内部能力（未挂载 MCP · 8）

> 存在于引擎中，按安全边界刻意不暴露给外部 Agent 调用：

| 工具 | 功能 |
|---|---|
| `condition_space_operate` | 条件空间 7 操作（identify/declare/separate/compose/switch/reverse/loop） |
| `add_context` | 情境层记忆写入（短时会话，FIFO+1h 窗口，可衰减） |
| `code_test` | 结构化代码测试（隔离环境断言执行） |
| `compile_exec` | 中文协议编译器（认知图→代码图→编译执行） |
| `lingshu_sensor_report` | 信息差传感器（五维结构质量信号扫描） |
| `lingshu_vitality_report` | 维生状态（心跳/影响面/回滚能力/判定） |
| `lingshu_auto_snapshot` | 前置快照（sha256 指纹+修改意图） |
| `lingshu_rollback` | 一键回滚（快照指纹校验） |

---

**总计：78 个 MCP 工具 + 8 个引擎内部能力**（不重复、不遗漏）