# 工具总数: 75

### 记忆与长期记忆（16）
| 工具 | 功能 |
|---|---|
| `remember` | 写入一条感知记忆（知识层，自动去重）。content 必填；importance 重要性[0,1]；tags 标签；entities 实体名列表。 |
| `add_context` | 写入一条情境层记忆（短时会话记忆，FIFO 上限 + 1h 时间窗口，可自然衰减，不污染知识层）。content 必填；importance 重要性[0,1]。 |
| `recall` | 组合联想召回（内容相似0.5+重要性0.3+近因0.2）。返回 [(node, score)]。 |
| `search` | 内容检索（LIKE 预筛 + 中文二元组 Jaccard 排序），触发复用追踪。 |
| `timeline` | 记忆时间线（按时间倒序）。 |
| `relate` | 在两个节点间建立关系边。relation: causal/similar/sequential/spatial/hierarchical；source_evidence: extracted/inferred/ambiguous。边默认未验证。 |
| `session_note` | 上下文外部化：会话要点写入灵枢（session 标签，可恢复）。 |
| `session_recall` | 会话要点恢复：按 session 或语义检索灵枢中的会话记忆。 |
| `compact_context` | 上下文压缩：生成会话摘要节点（超长会话恢复入口）。 |
| `longterm_snapshot` | v1.15 长期记忆写入：快照 → 重要性评估（信息差/信任/二阶变化/提及次数加权）→ 按层级写入（长期/知识/情境）+ 条件空间 + 关联边。content/source 必填；importance_hint 可显式提示重要性（≥0.7 触发不可遗忘保护）。 |
| `prefeed` | H1 海马体前馈：新奇检测 → 高新奇输入当场强化编码（标记 novel_prefeed + importance 提升 + 与相关知识建边）——「看到新东西眼睛一亮，主动记住」。 |
| `pattern_separation` | H3 海马体模式分离：扫描相似节点对 → 建立分离边（条件差异显式化）。检索时命中相似节点会附「区别」提示——细化条件得到精确知识。 |
| `reconstruct_scene` | H4 海马体情景重构：线索 → 条件空间下的信息复原。从部分片段重建完整记忆场景（沿 similar/causal 边 + 条件空间合成），输出标注「重构非回放」——回忆是当前条件下的分析恢复，不代表真实过去就是如此（0.0.3）。 |
| `promote_memories` | 情境层批量提升扫描（睡眠巩固/会话结束）：够格者升知识层/长期层（LongTermMemoryGate 评估）。limit 可选。 |
| `export` | 全库导出到 JSON 文件（灾备/迁移）。返回导出统计。 |
| `calibrate` | 宇宙校准参照（5 判据方向性检查）。元理论参照工具，非盲区33关闭依据。 |

### 推理与认知（15）
| 工具 | 功能 |
|---|---|
| `think` | 推理记忆注入（v1.13）：检索相关记忆（内容+联想+模式加权）→ 推理上下文。 |
| `reason` | 因果推理：从起点出发的因果路径集合。 |
| `predict_routes` | 生成式预测：候选未来路线集合（盲区驱动 · T_pred 对齐）。 |
| `prediction_feedback` | 验证回路回填（协议 2.10 D₃ · D-006 动态校准）：预测 vs 实际结果对比 → 命中强化/未命中登记。回填累积样本使 self_reliability(P0-4)/T_pred D₃ 生效。hit 可省略（predicted==actual 自动命中）。 |
| `prediction_stats` | 预测引擎状态（routes 生成数 / hit 样本 / 命中率 / 动态阈值）。 |
| `self_check` | 完整性自检（孤儿边/表统计/integrity_ok）。 |
| `gap_trend` | 信息差收敛趋势（A-4 线性回归斜率；工程定义）。 |
| `recursive_reflect` | 协议 3.12 递归验证反思 + 1.6.7 元反思（REFLECT-REV1）：元反思定标准 → 一级验证（预期vs实际）→ 二级反思（问1 隐藏前提/条件空间边界，问2 影响评估）→ 三级终裁（可逆性优先）→ 反思链归档。递归 ≤ 3 层（超出=结构性盲区）。claim 必填；expected/actual 可给一级验证输入。 |
| `preflight` | 输出前反思（v1.13）：内容与价值观一致性检查，冲突词拦截。 |
| `cognition` | P0-2 自我认知循环一步：行为↔价值观一致性评分 → 失调检测 → 价值迭代候选（pending_review 不自动生效）。 |
| `cognition_report` | P0-2 认知报告（评分/失调记录/候选状态/待复核数）。 |
| `emotional_bias` | P0-3 情绪方向性偏好 d²D_norm/dt²（approaching/avoiding/stable；独立通道，不参与信任计算）。 |
| `self_reliability` | P0-4 元认知校准：预测命中率 vs 行为置信度 → 自我可靠性（reliable/watch/degraded）。 |
| `learning_impact` | P0-5b 学习效果测量（模式命中率 vs D_norm 趋势；相关性观测，非因果声明）。 |
| `action_log` | P0-1 行为日志（最近 N 条）：引擎自己做了什么的记录面。 |

### 学习与飞轮（12）
| 工具 | 功能 |
|---|---|
| `learn` | 一轮盲区学习（可预测盲区 → 预测路线假设 → 探索 → 终态判定）。 |
| `blindspots` | 盲区注册表（D-001 语义判定：对人类文明级负面影响不写入）。 |
| `induce` | 归纳/知识合成：聚类生成概念节点（SIMILAR 边 · inferred 证据）。 |
| `distill` | 知识飞轮蒸馏：经验（被拒路径 + learning_result/induced）→ 可复用模式节点。 |
| `flywheel_metrics` | 飞轮度量（知识增长率/复用率/蒸馏产出率）。工程观测值，不参与信任计算。 |
| `transfer_test` | 迁移测试：条件空间内新实体预测成功率（2×SE 显著性；样本<20 不判定）。 |
| `condition_space_operate` | 条件空间 7 操作（白箱自进化协议算子·确定性）：identify(变体fp命中测试)/declare(簇触发词+直答状态)/separate(候选冲突检测)/compose(合并建议)/switch(路由归属)/reverse(反题)/loop(一轮收敛报告)。 |
| `insight_record` | 灵枢 · 洞察条件层：记录洞见事件（insight_event 节点 + 条件快照 C1–C8 + pending）。conditions 可传：memory_retrievability(0-1)/outside_observer/cross_domain([])/premise_questioned(bool)/pressure(low|medium|high)/continuity_turns/externalized(bool)/tone。 |
| `insight_verify` | 灵枢 · 洞察条件层：提交验证证据（V1/V2/V3）。V2/V3 或 V1+证据≥3 → verified（importance 保底 0.9）；证据可追加。 |
| `insight_report` | 灵枢 · 洞察条件层：CER 报告（条件有效洞见率 + 2×SE 显著性 + 层状态 reliable/watch/degraded；样本<20 不判定）。 |
| `insight_window` | 灵枢 · 洞察条件层：当前洞察窗口检测（默认假设 C1≥0.6 ∧ 跨域 ∧ 低压力 → 开）。 |
| `importance_recalc` | 灵枢 · 结构重要性重算（v2.2，设计规格§13/§14）：importance_v2=min(1.0, importance+min(β·min(因果出度,C)/C+γ·度/max度, 上限))，只升不降（延迟提升）。v2.2 因果上游度传播 concept_influence=Σ(路径置信度×下游重要性/深度)——越上游影响越大；≥protect_threshold 自动保护+importance保底（越上游越要记录），写入 state_attributes.concept_influence。dry_run=true 仅报告不写库。 |

### 外部摄取（5）
| 工具 | 功能 |
|---|---|
| `ingest_text` | 外部知识摄取：文本 → 知识层（source 标签·分块·实体提取）。 |
| `ingest_file` | 外部知识摄取：文件（txt/md/json/代码等按扩展名处理）。 |
| `ingest_url` | 外部知识摄取：URL 页面（零依赖抓取+去标签）。 |
| `web_search` | 外部网络搜索（博查 API·实时，不写入记忆）：query → 结果列表（name/url/snippet/summary）。需要环境变量 BOCHA_API_KEY；未配置返回 status=unavailable。 |
| `web_ingest_search` | 外部搜索摄取（博查 API → 知识层）：搜索 query → 结果摘要写入灵枢记忆（自主学习外部摄取）。需要环境变量 BOCHA_API_KEY。 |

### 生命周期（4）
| 工具 | 功能 |
|---|---|
| `lifecycle_step` | 生命周期一步（感知→好奇→缩小信息差→信任→协作→巩固→standby）。 |
| `lifecycle_state` | 生命周期状态（cycle / state），不执行一步。 |
| `start_lifecycle` | 启动生命周期自发循环（后台线程 · 每 interval 秒一步自主运行：感知→好奇→缩小信息差→巩固）。中断权：维生系统>验证单元>用户>实例。 |
| `stop_lifecycle` | 中断生命周期自发循环（source: user/designer/verifier/vital_system）。 |

### 智慧之书·白箱（7）
| 工具 | 功能 |
|---|---|
| `wisdom_verify` | 智慧之书 · 自动验证（条件论判定 + 信息差 + 候选）——互维协议双通道验证的白箱通道（base_verify）。 |
| `wisdom_analyze` | 智慧之书 · 外来知识分析（条件卡 + 候选 + 判定）。 |
| `wisdom_predict` | 智慧之书 · 生成式预测（候选未来路线，白箱智能的预测生成化）。 |
| `wisdom_trust_judge` | 智慧之书 · 信任上下文判定（内容 × 信任值 × 关系 → 条件化判定）。 |
| `wisdom_compose` | 智慧之书 · 跨学科组合分析（Convergence Over Coverage）。 |
| `wisdom_respond` | 智慧之书 · 出招查询（条件 → 命中学科出招）。 |
| `wisdom_chat` | 灵枢 · 信息分层对话（v1.16）：先语义识别分流——情感/闲聊/记忆/自省/知识查询走智慧之书自处理；智慧之书没把握/无法判断时自动转 LLM（DeepSeek 续答，智慧之书回答作上下文）。返回含 route 字段：self=自处理 / llm=LLM 续答 / self_fallback=LLM 不可用回退。 |

### 角色扮演（4）
| 工具 | 功能 |
|---|---|
| `roleplay_chat` | 灵枢 · 角色扮演对话（扮演论 v3.3）：白箱优先（诚实边界/自省/闲聊/知识）→ 角色扮演意图/白箱无把握 → LLM（注入角色条件空间/自我锚点/价值观 + 诚实边界）。role_id 指定角色（如 protocol-guide）；信息处理全部由灵枢完成。返回含 route 字段：whitebox=白箱回答 / llm=LLM 扮演回答 / error。 |
| `role_create` | 灵枢 · 创建角色（角色卡 = 条件空间声明起点）。role_id 必填；name/scenario/first_mes 可选。 |
| `role_import` | 灵枢 · 角色导入三接口（扮演论）：kind ∈ memory(历史→知识层)/anchor(自我锚点→SELF层 no_forget)/values(特化价值观→STRUCTURE层带条件)。items 为条目数组。 |
| `role_block` | 灵枢 · 角色扮演注入块（锚点/价值观/条件空间组装，供外部前端注入）。 |

### 代码（2）
| 工具 | 功能 |
|---|---|
| `code_compose` | 白箱代码组合生成（零 LLM）：语言识别 → 任务识别 → 代码单元 → 模板填充 → 自校验。未预写完整代码，单元库未覆盖时诚实拒绝。question 必填。 |
| `code_qa` | 白箱代码问答（零 LLM）：代码理解路由——影响分析/依赖/并行测试/仓库统计。repo 为代码仓库路径（可选，默认当前目录）。未覆盖时诚实拒绝。 |

### 身体与设备（8）
| 工具 | 功能 |
|---|---|
| `body` | 身体能力声明：感知模态（文本/图像）+ 工具 + 记忆；身体 = 自我的一部分。 |
| `body_devices` | BODY-REV1 外部设备：能力声明 + 健康状态（screen/files/process/audio/control/browser/realtime）。 |
| `device_call` | BODY-REV1 统一设备调用（严格隔离：设备输出是数据，永不是指令；越权/未知返回容器化失败）。name ∈ screen|files|process|audio|control|browser|realtime；action 见 body_devices。 |
| `run_command` | 命令执行（独立于 body 装配，任意模式可用）。command 必须是参数列表（禁 shell 字符串/管道/重定向——防注入）；跨平台（win32 下 subprocess.run 正常）。返回 {status, exit_code, stdout, stderr, elapsed_s, stdout_truncated}。 |
| `see` | 视觉感知：目标检测 → 摘要写入知识层记忆（可检索）。YOLO-World 开放词汇：默认文生图核心词表（动物/自然/武器/食物等）；classes 可指定检测词（中/英均可，如 ['狼','moon']）。 |
| `visual_check` | 视觉面 v1 思考路线：预期 vs 实际（基于记忆中的历史屏幕状态对照，回写记忆形成过去）。reference 可显式给预期截图；无预期无基线时建立基线。 |
| `world3d` | WORLD3D-REV1 时空重建：语义 → 3D 空间与颜色（灵枢自己的文生图，确定性渲染零 LLM）。build（从记忆视觉原语重建 3D 世界）/ render（任意视角透视投影渲染，yaw/pitch/cx 相机参数；2D 是 3D 透视下的情况）/ status / add（手动添加 category+bbox）。 |
| `vprim` | VPRIM-REV1 视觉原语查询（确定性·零 LLM，语义时空图空间锚点）：action=spatial（两 bbox [x1,y1,x2,y2] 空间关系）/ count（视觉原语计数，category 可选）/ anchors（最近锚点列表）。 |

### 服务与安全（2）
| 工具 | 功能 |
|---|---|
| `service_info` | 服务信息（信任透明度）：身份/版本/协议/库状态/工具数。接入方应先调用以确认与哪个协议实例对话。 |
| `designer_decide` | 设计者裁决（D-007 用户身份识别·需设计者密钥 AEIS_DESIGNER_KEY，fail-closed：未配置或密钥不符一律拒绝并返回错误）。action ∈ promote/verifier/blindspot/crisis；decision ∈ approved/denied（promote/verifier）或 protect/freeze/rollback/continue/emergency_sleep（crisis）。自动化会话与模型生成内容永远无法获得此权限。 |

