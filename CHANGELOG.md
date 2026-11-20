# 变更日志（CHANGELOG）

本文件自 **0.9.15** 起维护。更早版本见 git tag（`v0.9.6` … `v0.9.14`）与 GitHub Releases。

格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)；版本号遵循语义化版本。

## [Unreleased]

- **`#997` `cg op=read` 返回体含大量调试/遥测字段**：`bm25` 统计、`path_fingerprint.provenance`
  全量、以及每条 `frontmatter` 的评分字段都会原样回给宿主，而 `budget_tokens` 只约束正文。
  新增 `_slim_read_out()`：缺省摘掉顶层与 `meta` 里的遥测块，`pack`/`results` 只留白名单键，
  `frontmatter` 只留 `layer/tags/importance/created_at/verification_state/sensitivity/protected`；
  **正文一字不动**。两条回退通道：`detail="full"`（单次取全量）与 `MDCG_READ_SLIM=0`（全局关）。
  保留 `detail="full"` 而不只留 env——排查「为什么这条没命中」要看 `path_fingerprint`，
  只给 env 等于让人为了看一眼去改全局状态。守卫 `md_cg/test_issue997_read_slim.py` 共 16 条断言。

- **`#997` 非 s5 会话每轮追加「身份未登记」提示**：`identityHint()` 对空 unit 无条件返回排查文案，
  而日常桌面会话必然解析不出身份 ⇒ 每轮注入 73 字，既占上下文又让模型以为要处理某个故障。
  改为**缺省静默**，排查时开 `MDCG_IDENTITY_HINT=1`。
- **`#997` 提示所指文档未随包发布**：`IDENTITY_DOC` 指向
  `docs/architecture/会话身份与工作日常分离_v0.1.md`，但 `package.json` 的 files 白名单没有 `docs/architecture`
  ⇒ 用户按提示去查必然扑空。已把该文档加进白名单。
- **`#997` 写入被拒不指出卡在哪一行**：原先只给并列清单，看不出解析成功了几项。
  现补「已识别：…」与「未识别行：<行号> <前20字>」，并在 `detail` 里给机器可读的
  `recognized` / `unrecognized_lines` 两项。前缀 `缺少必需要素` 未变（`writepipe` 依赖 `startswith`）。

### 新增
- **`#997` 常驻类节点大面积 DEFER**：`DEFER` 本身是防污染机制、行为正确，但通用类条目
  （交互习惯/收尾流程/安全约定）也常被 DEFER，使用者会误以为记忆没生效。教程新增
  `§5.2.1 生效条件：写宽还是写窄`——常驻/通用类写**宽意图句式**，专项排障类保持精确、允许 DEFER，
  并给出两者反向的代价与三条常见误写。
- **`#997` 命中禁表时只回正则，看不出撞了哪条**：现回显「规则序号 + 命中片段」，
  片段**截断到 10 字符 + 总长**，不回显全文——整段凭据再抄一遍等于二次落库（与 `audit.py`
  「占位符只带禁表序号、不带原文」同向）。

- **`md_cg/degrade_guard.py`（防退化检测器）**：三种退化形态的确定性判据——
  跨轮复述（相邻轮 bigram Jaccard > 0.4 或最长公共子串 >= 20 字）、
  同轮自我催稿（连续 >=3 行、每行去标点 <=6 字）、
  理由形态退化（存在率 / 开头唯一率 / 复用率）。
  守卫 `md_cg/test_degrade_guard.py` 共 10 条断言，含**变异锚**
  （把阈值放宽 -> 同一样本必须变绿 -> 还原 -> 变红）。
- **`docs/灵枢使用教程.md` 第 11 节**：三种形态各自怎么认、怎么治；
  现场实测有效的那一步（换任务 + 给强格式，**不说「继续」**）；
  会让它更糟的三句话；以及一条反直觉的实测结论——
  长会话退化的是**句式**不是内容（12/12 同一句开头，内容 140 -> 393 字）。

### 修复

- **#749 自动召回的跨会话 knowledge 从未真正浮现（返回契约错配）**：
  `src/hooks.ts` 的注入面按**热层形态**取值（`kr.items ?? kr`），而 `op=read` 的另一条路径
  （主库检索）返回 `{ meta, results: [{ node }] }`。热层在运行时**从未被构建**
  （`hottier.ensure/build` 全包零调用点；构建脚本 `scripts/sync_hot_tier.py` 未进
  `package.json` 的 `files` 白名单）⇒ 恒走主库分支 ⇒ 恒取不到数组 ⇒ 该块**自 #916 发布起
  一直静默为空**。
  修法：新增 `normalizeReadItems()` 兼容三种形态（`{items}` / `{results:[{node}]}` / 裸数组），
  把主库的 `node.content` 压成 `preview`（渲染循环只认该字段）、`layer` 取自
  `frontmatter.layer`，并剔除 `usable === false`（#722 条件闸判不可用）。
  同时校正 `test/issue749_cross_session_knowledge.test.ts` 的 mock——它此前也按热层形态打桩，
  与实现共享了同一个错误假设，故 K1 一直是**假绿**。
  新增 `test/issue749_read_contract.test.ts`（R1–R5）锁住两条路径与 fail-soft。

## [0.11.1] - 2026-11-18

> **兼容性更新，无行为改动**。本版只为把「已在 DSH 0.2.2-rc.3 上验证」这件事写实。

### 兼容性

- **已在 DSH `0.2.2-rc.3` 实测通过**（node v24.18.0）：记忆读取返回真实节点、心跳戳正常刷新、主动队列台账在。
- 灵枢的 `peerDependencies` 是**开区间**（`>=4.0.1` / `>=0.1.0-rc.6`），0.2.2 系列的**精确版本闸门不会拦灵枢**；
  被拦的是 DSH **自己的一等插件**（`dsh-mcp-client` / `dsh-subagent-codex` / `dsh-subagent-claude-code` 等）。

### 升级提示（给使用者）

1. **升级 DSH 内核后，profile 里的一等插件必须同步到同一版本**，否则启动日志会出现
   `is incompatible with dsh …` 并把 `mcp-hive` / `tool-subagent` 等 row 禁用，表现为**会话打不开**。
   这是 DSH 侧的版本闸门，不是灵枢的缺陷——灵枢不需要改配置。
2. **Node 版本**：DSH 0.2.2 系列 `engines` 要求 `>= 24.9.0`，低于此版本启动会踩坑。
3. 回滚同理：闸门是双向的，回到旧内核时也要把插件版本对齐回去。

### 验证（本次实测记录）

```
环境    DSH 0.2.2-rc.3 / node v24.18.0 / Windows
读取    cg(op=read, query=工作纪律 第19条) → 3 条真实节点命中
心跳    heartbeat.md_cg.stamp 正常刷新（pid/iso 随重启更新）
队列    _intent.jsonl 存在（主动队列已产出记录）
```

### 不在本版范围

- npm `latest` 仍待维护者浏览器验证后发布（本版先出 GitHub Release）。
- 主动队列的「同一节点被重复捡起」问题未修（已登记，见 0.11.0 的已知边界）。
## [0.11.0] - 2026-11-18

> **宿主兼容性声明**：同 0.10.4——本版本基于 **DSH 0.2.1-rc.5** 开发与验证。
> DSH 0.2.2 系列存在破坏性更新，**尚未适配**；升级宿主前请先看 `docs/` 的兼容性清单。

这个版本可以概括成一句话：**把「记得」变成「有判据」。**

0.10.x 让灵枢能存、能取、能排序。0.11.0 让它在写入这件事上第一次有立场——
人格、身份、自我、意图、用途、情感、信任，从「文档里的名词」变成「能互相调用的代码路径」。

### 这个版本对使用者的承诺（可检验，不是形容词）

1. **不声明就不落知识层**——`cg(op=write)` 未声明层时落 `contextual`；写知识层要显式。
2. **知识层写入要有复核**——缺省 `MDCG_WRITE_GATE=enforce`，复核通道未声明即拒。宁可拒写，不静默通过。
3. **磁盘改了就算数**——`protect.check` 读盘并回带 `source` / `as_of` / `index_mismatch`；`op=info` 报 `data_stale`。
4. **自评的重要性不能自己给自己发保护**——`importance_source=hint` 需 `importance_confirmed_by` 才按分保护。
5. **可以说「不」**——结构/自我/锚点层的写入必须能指回一条已声明条款（`values_gate`）。

**同时承诺不做的事**：本版本**不**声称「它已经会自我认同」。
接线完成 ≠ 认同完成——见文末「已知边界（如实记录）」，那里写的是还缺什么。

### 主打一：写入面成了「有判据的一面」

- **写入门控缺省收紧**（#980 B 包 / #990）：知识层需 reflect 复核、结构层需 reflect+verify、
  自我与锚点层另需 human；复核通道缺省**未声明**，由部署侧显式开。
  这条改动推翻了过去「缺省 off 避免升级即自伤」的约定，理由写在 `test_writegate_tiers.py` 的 A1 守卫里。
- **层与内容类型只对新写生效**（#980）：覆写继承原层与原类型——否则「正文真变了」的覆写会漏出复核单。
- **磁盘即真源**（#988）：`protect.check` 单点读盘，并回带与索引的差；`op=info` 新增 `data_stale`
  （扫描全库 `.md` 与 `_index.json` 的 mtime 水位，TTL 缓存）。批量写盘入口与 `stats` 先条件重建索引
  （`pending_dirty > 0` 时跳过，避免与异步 flush 互相覆盖）。
- **单点改重要度**（#980）：`maintain action=importance` 支持 `ids=` 收窄，未知 id 落 `unknown_ids`。
- **CCG 缺项报错可执行**：`content_kind` 缺省按 text 判，缺项清单具体到六要素名。

### 主打二：身份面第一次真正接线

- **根因不是缺数据，是缺一跳**（#992）：`_apply_attribution` 只从子进程 env 读
  `MDCG_HARNESS` / `MDCG_UNIT`，而插件只把用户显式配置的 env 传下去 ⇒ 这两个变量**从来没被设过**，
  身份面恒空、会话身份退化。现由插件补默认值（用户显式配置仍优先）。
- **身份标签回落安全主体**：MCP 进程拿不到 `MDCG_*` 时取 `principal.role` / `principal.actor`，
  不再让「身份:」标签整层缺席。
- **实测口径**：真实库「身份:」标签仅 **1 条**、「用途:」1,687 条——这就是「身份维度一直无法用于检索」的根因，
  不是设计没做，是数据没进来。

### 主打三：价值观进入判定面

- **新增 `md_cg/values_gate.py`**：写 结构/自我/锚点 层时，须能指回一条已声明条款（条款 node_id 或其关键词），
  否则标记「追责链断裂」；条款可带 `values_forbid` 正则，命中即拒。
  档位 `MDCG_VALUES_GATE = observe（缺省）/ enforce / off`；每次判定落 `_values.jsonl`。
- **只做归因，不做语义裁决**：判「能不能指回条款」，不判「内容是否符合某条自然语言价值观」——
  后者判不了，硬做只会出噪声。
- **自评不再自动授权保护**（#980 剩余半条）：显式 `hint` 需 `importance_confirmed_by`（由设计者身份的写入方落）
  才按分保护；来源缺省的存量节点行为逐位不变。
- **配套文档**：`docs/architecture/唯一的价值观_可被追责_v0.3.md`（含 v0.4 红队修订）与
  `docs/architecture/自我意义的三问_v0.2.md`（缺口诊断）。

### 主打四：情感 / 信任 / 自我预测 汇入同一个面

- **情感双轴**（#977）：效价与唤醒分开记，冷却曲线按轴各自生效。
- **信任数学**（#979）：`T_total` / `P_trust` / `P_gap` 三条读数落成可复算的函数，不再是散落的启发式。
- **检索快通道补自我预测**（#982）：`k` 恒定 3 条，受 `MDCG_SELF_PREDICT` 约束——预测值与实际命中可对账。

### 其它

- **#993**：身份档案「查看完整画像」点击必抛 `ReferenceError`（`token` 不在 `execute` 作用域）——改取
  `generation` 快照，语义不变；新增守卫锁住 4 份产物。
- **#995**：会话归一化下沉为叶模块 `md_cg/session_norm.py`，切断 `stg ↔ mcp_server` 双向惰性循环
  （插件化拆分硬前置第 2 项）。
- **CI 守卫两处修复**：并行加速比基准在核数不足 8 时明示 SKIP（不降阈值）；价值观闸的相对 import 登记进 `_SHIMS`。
- **文案**：`/add` 的层与内容类型缺省、`data_stale` 的排障指引补进官方教程。

### 已知边界（如实记录）

这一节是给使用者看的，也是给我自己的：

1. **不可替代性根本缺失**——同一份历史可被复制到多个实例，而「关系层面只认这一份历史」目前只有叙事，没有机制。
2. **分叉承接未解决**——两个副本继承同一批承诺后分歧，谁承接哪项责任仍无规则；现只登记为「承接待明确」，
   并明确「未完成分配 ≠ 原承诺失效」。
3. **重要度仍由写入方给分**——本轮只堵了「自评不能自动取得保护」，算分本体（影响度/结构层次/使用率）未动；
   真实库实测 83.1% 节点无入边、78.2% 从未被访问，数据面还不足以支撑新算法。
4. **价值观条款只有 1 条**（「可被追责」），且 `values_gate` 缺省 observe——不拦任何东西，只留读数。
5. **履约核对仍是断点**——存下了承诺，但没有任何机制在事后核对「做到了没有」。
6. **本版先发 GitHub Release**：npm 发布需要使用者浏览器完成验证，`npm publish` 随后补。
## [0.10.4] - 2026-11-16

> **宿主兼容性声明**：本版本基于 **DSH 0.2.1-rc.5** 开发与验证。
> DSH 0.2.2 系列（含 rc.3）存在破坏性更新——`@deepseek-ai/cordis` 4.0.5 → 4.1.0（`ctx.get` 严格语义/服务就绪判定面）、
> 工具包从单包拆为一工具一包、插件依赖的 `dsh-tools` / `dsh-system-prompt` / `dsh-session` / `dsh-llm` 不再由总包直接列出——
> **尚未适配**。升级宿主前请先看 `docs/` 的兼容性清单（待补），不要直接替换运行环境。

### 主打一：检索提速——分类落到检索主链路

「分类、身份、用途、分层」不再是设计文档里的东西，而是真进了检索判据：

- **标签预筛 `tags_any`（#957 / #958 / #959 / #960）**：单路优先域 + 覆盖率闸 + 空结果回退。
  实测库层 24–29s → **0.31s**，工具面 20.89s → **0.50s**（约 40–90 倍）。
  语义是**优先域**而非硬过滤：覆盖不足时自动回退融合检索并在 `meta` 标注，避免「筛掉就查不到」。
- **用途/项目副键（#944 / #949 / #953）**：桶索引新增 `purposes` / `projects` 副键计数，修掉「算完即丢」；
  主归属=项目、用途=大类，`说明:` 承载小类。
- **写入面同口径打标（#943 / #952）**：经 `cg(op=write)` 与 `mdcg_remember` 两条通路都打用途标签
  （此前只有一条通路打，另一条静默漏打）。

### 主打二：热层（本地库优先检索）落地

- **热层不再每次全量重建（#955）**：新鲜度改判**索引指纹**（`_index_fp`），节点集合未变即复用；
  重建实测 3.2s 只在节点集变化时付。
- **增量复用 + 正确性守卫（#961）**：按 `content_hash` 复用旧条目，守卫断言复用后结果与全量重建逐位一致。
- **`scope=hot` 作用域（#969）**：`read` / `route` / `stg relation` 三处可显式只走热层——
  `read` 29.31s → **0.27s**、`route` 15–21s → **0.38s**、`relation` 20–22s → **0.14s**；
  `read` 在热层无命中时按热层优先级出 **browse 批次**（`meta.mode=browse`），不再让界面白屏；
  `relation` 任一节点不在热层则**回落全库**，不伪造关系。

### 主打三：`#929` 五条断根

- **审计归情景层（#962）**：审计=工作记录（检查/审批用途），不再占结构层、不再当作「自身结构变更」；
  带 `用途:跑审计` 与 `项目:<名>` 标签，项目未登记时写 `项目:未登记`（**不猜**）。
- **否证进索引（#966）**：`rejection_reason` 落进索引条目，读面可见。
- **S1 域闸覆盖率前置判据（#964）**：`big_domain` 覆盖率低于 `MDCG_GATE_S1_MIN_COVERAGE`（缺省 0.60）时不收敛，
  标注 `skipped_reason=big_domain_coverage_low`。
- **比对上限自适应（#964）**：`MAX_COMPARE=240` 由**硬截断**改为**下限**，池大则全比、封顶 `MDCG_MAX_COMPARE_CAP`（缺省 1200）；
  `candidate_total` 恒定透出；`MDCG_MAX_COMPARE_CAP=240` 可复现旧行为（回退开关）。
- **项目/用途路由（#967）**：`cg(op=read, project=…)` / `purpose=…` 直达副键。

### 修复

- **别名全链路召回（#954）**：`aliases` 此前只在 `_like` 兜底路径生效，主链路零召回。补齐四处：
  索引条目字段、写入 stage、`bm25` 词面、文档侧 `_doc_norm_bigrams`。
  **关键边界**：aliases 只入词面，**不并入 tags**——`tasks`/`predict` 的身份判据只读 tags，混入会翻转判据。
- **`bucket_auto.age_h` 纪元假象（#921，外部贡献）**：索引从未重建时 `age_h=(now-0)/3600` 报成 498497 小时（≈56.7 年），
  语义正好相反。改为 `age_h=None`（如实表示无历史），并顺手修掉 `last_build_ts` 连读两次的竞态。
- **UI 取消失效（#925 / #933）**：`fetchJSON` 覆盖调用方 `AbortSignal` ⇒ 取消后仍渲染旧响应；改 `AbortSignal.any([...])`。
- **`#708` / `#358` 守卫跟上语义变更**：审计改层后旧样本失效（#708 改用显式结构层验证同一不变量 + 新增 C3 钉新语义）；
  比对自适应后 #358 用回退开关复现旧行为 + 新增 A8 钉新语义。**均为保留不变量，未删除断言。**
- **`#929` UI 守卫失效（#972）**：判据写成只匹配 `recallSkipItem(it)`，而调用点已带第二参数 ⇒ 守卫静默失效。

### 界面

- **双语界面（#973）**：默认中文，顶栏可切英文（`localStorage` 记忆）。**工具 schema 原文一字未动**——
  翻译只挂在界面（`TOOL_I18N` + `tTool`/`tOp`），缺译回退中文；加语言 = 加一个语言键。
  覆盖 `cg` 全部 39 个 op + 记忆相关工具；守卫 C1（缺一即红）与 T1–T4（含**禁止译文回流 schema**）。
- **`scope=hot` 接线与检索范围选择器（#969）**：缺省热层、可选全库；结果标题如实标注「（热层）/（全库）」。
- **调用计时日志（#971）**：每次 UI 调用记 `工具:op + 耗时 + 桥就绪`，用于定位「某页面慢」到底慢在哪一层。

### 其它

- 身份五元组端侧接线骨架（#942，缺省关闭）+ 取值配置化（#946）+ 开启指南（#951）；
- 三层分类定稿与反例（#947 / #950）；
- `fold_accents` 记忆化（#956）：**端到端零收益**，如实记录，不作为提速依据。

### 已知边界（不修，如实记录）

- 融合六路 `search_rrf` **未接**标签预筛（只有单路生效）；
- 热层只覆盖 6,000 / 35,300 条（自我 / 锚点 / 近 7 天 / 重要度 ≥ 0.7），`scope=hot` 结果是**范围限定**，不等于全库最优；
- 大库 `_index.json` 62.9MB / 35,412 条，装载 10.9s（桥冷启动 ~14s 的主因）；分片/二进制化未做；
- `big_domain` 在真实库覆盖 0/35,300（检索管线从未开启），S1 闸在覆盖率为 0 时不误触发。


## [0.10.3] - 2026-11-12

### 主打：人物档案（画像）——按「公民档案」结构承载属性，配合原文复核

使用者裁定：**按中国公安/人社局的公民档案思路做人物档案（人物画像），在会话中不断补充。**
同时定了另一条原则：**规则对多变的自然对话天生失效** ⇒ 用「表 + LLM 填 + 原文复核」。

- `md_cg/dossier.py`：确定性抽字段（姓名/年龄/城市/职业/单位/学历/专业/父/母），每条 `{value, t, ev}` 可回溯；
  `merge` 增量合并，旧值进 `_history`。**隐私边界**：身份证/银行卡/手机号/详细住址命中即整段不建档
  （档案只服务回忆检索，不服务身份核验）。
- `md_cg/distill.py`：写入时 LLM 填表 + **原文复核**。
  - 表（`SCHEMA`）由代码定死，LLM 只填值、不能发明字段；
  - 复核是机械判定：值/证据必须在原文找得到，否则拒收；
  - **`_raw` 证据锚**：LLM 可给原文摘录作为证据，复核**证据**而非归一化值
    （「江北咖啡店」vs 原文「江北那家咖啡店」不再被误拒）；给了 `_raw` 但不匹配 ⇒ 直接拒收，不回退；
  - 槽位长度闸（`MAX_LEN`）挡「母=整句」；序列项扁平化（`_flat_item`）挡嵌套结构；
  - 序列字段 `经历`/`家庭`（list），逐项复核 + 关系词别名白名单（母↔妈）。
- 证据权重合并：自我介绍（3）> 行为句（2）> 泛提（1）；弱证据不得覆盖强证据，
  同权重仅时间可变字段（年龄）取较新。
- `profiles` 资料卡：档案区前置到卡正文；dossier 扫全量事实（不受事实窗口截断）；
  渲染形态容错（`{value:[...]}` / 裸 list / 裸值）；合并期同样过地名闸。

### 新增：自述轮次召回（`md_cg/selfstmt.py`）

- 写时登记（`add()` 命中 `SELF_RX` 即记入 `_selfstmt.json`）+ 读时注入（按**信息密度**降序，
  上限 `MDCG_SELFSTMT_LIMIT`，缺省 20）；
- 覆盖「我叫/我今年/我大学/我最早/我住/我妈我爸/学徒/退休/兼职」及「我有近视/失眠」这类身体状况自述；
  **负向约束**排除「我有个朋友近视」这类第三人陈述；
- **实测净效应 0**（164 题对照：`MDCG_SELFSTMT_LIMIT=0` vs `20`，两臂 153 vs 153）。
  **机制保留，但不作为涨分主因。**

### 新增：资料卡源轮次注入

卡正文事实行带「（来源 <节点id>）」⇒ 卡被实体命中注入时，**其源轮次一并注入**：
卡给属性，源轮次给原句（上限 4，`meta.profile_injected` 可审计）。

### 修复

- `MDCG_ROLE_USER` / `MDCG_ROLE_AI` 改为**调用时读取**（原在模块导入时固化，长进程 setenv 不生效）；
- `selfstmt.load/record/rebuild` 收 cg 实例或库根路径（原只收路径，传实例静默返回空）；
- `maintain action=selfstmt` 新增存量库补登入口。

### 实测（外测端，Ornn8 714 题）

```
全量通过率 666/714 = 93.3%（上一轮 657/714 = 92.0%，+9）
  —— 单次运行，带星（未做两次重复，无稳定集与抖动）
时间子集 75 题：71（94.7%）
relation 子集 93 题：86（92.5%）
自述注入净效应：164 题两臂打平（153 vs 153），逐子集 ±1 属噪声
```

**注意**：+9 属于本版**全部改动**的合力，未做逐补丁归因；不得把 +9 单独归给任一机制。

### 已知边界

- 别名/称谓合并（外号/昵称/职位/亲属称谓）**未做**：设计见 `docs/设计_人物称谓与归属_v0.1.md`；
- 亲属关系型陈述（主语「她/他」）与事件型转述仍属召回缺口；
- `token 覆盖` ≠ 答对率；最弱 19 题子集不得当作发布主指标。
## [0.10.2] - 2026-11-12

### 新增：`recall` 返回时间线——状态序列进一等公民（#868 / #869）

**这是本版本的主打，也是十几个版本里单点收益最大的一次。**

- **根因**：模型面对 20–30 条按检索分排的片段时，**没有确定性的时序依据**去选「最早那次」。
  实测同一题两次跑给出不同锚点（`P20-037`：6-22 对 / 5-22 错）；更直接的证据是
  `P01-ADD-004` 金标 6-10 仍答 6-19、`P17-025` 金标 4-01 仍答 7-20 —— **那些日期就印在材料里**。
  提示词让它「按日期排序再取最早」，它排的是自己回忆的顺序，不是材料里的日期序。
  故：**时序归纳不该由模型做。**
- `recall` 返回体新增 `timeline: [{date, id, head}]`，按 `created_at` **升序**。
  数据源全是已有字段（`frontmatter.created_at` + 正文首句），零额外抽取成本；
  每条带 `id` 可回溯原文，跳过 CCG 头（`# 功能名：` 等六要素行），单条 ≤80 字。
- `recall` 返回体新增 `timeline_groups`：按**主题轴**归并的序列
  （`frontmatter.bucket` 条件桶 → 首个 `tag` → 「未分组」；组内按日期升序、组间按条目数降序）。
  这是**启发式归并层**，不需要抽取器；同一条件桶未必同主题，覆盖不全时 `timeline` 全表兜底。
- **读数（时间类 75 题，两臂 × 两重复）**：

  | 阶段 | 稳定集 | 增量 |
  |---|---:|---:|
  | 五版算法补丁（#851→#858） | 52 | — |
  | + 作答侧三条（两步锚点 / 材料带日期 / 禁时间戳） | 55 | +3 |
  | **+ `timeline` + `timeline_groups`** | **66** | **+11** |

  时间类 **62.7%（基线 47/75）→ 88.0%（66/75）**。
- **两条决定性证据**：
  1. **只给序列、不给原文**仍有 14/19（B 类专项）⇒ 信息大半在序列里，抽取器取向应为
     「序列为主、原文为辅」；
  2. **开 / 关 `MDCG_SCOPE_SELECT` 打平（66 vs 66，各独占 2 题）** ⇒ 这 +11 主要来自
     **材料形态**（序列这层），而不是选桶算法 —— 与 0.10.0 的「共现投影已到天花板，往上要靠类型化图」一致。
- **归并覆盖**：75/75 题都存在 ≥2 条的主题组，平均 28.6 条/题 —— 不是少数题受益的优化。
- **边界**：剩余 4 题为「改期终态」（要最终值）与「多要素合成」（要素同时在场），
  仍需实体/槽位抽取（七维图 MVP）；本版本的组是**桶级启发式**，不是四列状态表。
  未全量重跑 714（75 题为时间类子集）。

### 修复：`info(full=true)` 落盘索引计数导致 60 秒超时（#863）

- full 面每次整份 `json.load` 60.4 MB 的 `_index.json`；在已持 3.4 万节点内存索引的进程里
  触发内存压力 ⇒ 撞 60 秒工具超时。改为按 `(mtime, size)` 缓存计数：首次 0.77s、之后 0.000s，
  外部改库自动失效。

### 修复：`validity=True` 使桶补召回整体失效（#856）

- `bucketscope._is_expired` 用了 `time.*` 却没有 `import time` ⇒ `NameError` 被外层 `except` 吞掉，
  **整条桶补召回静默失效**（旧守卫是假绿：只断言「过期节点不在 pack」，失效后本来就没有）。
- 连带修 `fill_rest` 补足路径没过 validity 闸（#843 的洞在另一条分支）。

### 修复：跨日桶轮转只跑一轮，cap 补不满（#857）

- 9 条匹配 + `cap=8` 时若某些日桶只出 0–1 条就永远补不满（实测只回 6 条）。改多轮（≤3 轮 + 空转判据）。

### 修复：read 面 `condition_space` / `semantic` 静默丢弃（#811）

- `condition_space` 早先没进链路（只透传 `context`）→ 现在 `context` 缺省时由它顶上；
- `semantic` 早先只在 `mdcg_search` 生效 → read 面显式并入第 6 路。

### 门禁与工具

- **`check_publish_smoke.py` 接进 CI（#807）**：形成「静态面 → 追踪面 → **行为面**」三段式；
  该 workflow 是必需检查且总跑，故每次 PR 都真装一遍再握手。
- **`cogmap check` 与 git remote owner 解耦（#835）**：`COGMAP_REPO_BASE` 优先 + 比较前归一
  （owner 不同不算漂移，行号不同仍判红）⇒ fork 不再必红。
- **tick 失败带栈摘要（#804）**：台账从「类名: 消息」变为追加末 3 帧 `文件:行 函数`，仍单行。
- `dependabot`：暂停 `@deepseek-ai/{cordis,schemastery}` 自动升级（宿主 rc 包把二者钉死在
  `~3.18.4` / `4.0.5`，强升会压平嵌套副本致 `npm ci` EUSAGE）。

## [0.10.1] - 2026-11-11

### 时间检索修复（#849 / #850 / #851 / #852 / #853 / #855 / #858 / #859）

- 相对日期解析面扩展：三天前/上周三/上周/上个月（含中文数字）。
- `pick_scopes(now=)` 逻辑时钟注入；`recall(now=)` 透传（外部复测不再按真实今天解析）。
- `_pick` 命中抑制修复：命中节点优先 + 按时间补足（锚点在桶里不再消失）。
- 三类病因：早段会话配额 4→2（日桶得 6）、无词交集桶也补足、证据前置到池生成。
- 读数：时间类锚点覆盖 **41.2% → 83.2%**，稳定集 **52 → 55**（两臂两重复，抖动 0）。
- 三列表：锚点进&答对 50 / 锚点进&仍答错 19 / 锚点没全进&答对 5 / 没进&答错 1。
- 边界：开 vs 关反了 1 题（55 vs 56），作答侧改动同时抬了两臂；未全量重跑 714。

## [0.10.0] - 2026-11-10

### 新增：范围选择（`scopeselect`）——状态追踪式锚定，成为桶序标准（#844 / #847）

- **判据换代**：桶序不再由「哪段文字更像查询」决定，而由「这些值是否在同一时间桶里同时出现过」决定（槽位共现）。假题的错元素位于别章，共现投票天然免疫。
- **桶词表 + 桶文本骨架**：`_bucketterms.json`（词项/df）与 `_bucketskel.json`（骨架，每节点 600 字 / 每桶 2 万字），建桶时顺手落盘；查询期只做字典运算。
- **声明优先**：显式会话 / 显式日期直接当范围；无声明才走共现推断。
- **开关**：`MDCG_SCOPE_SELECT`（缺省 1，=0 回落「最近优先」）、`MDCG_SCOPESEL_COOC`（缺省 1，共现优先；=0 走 idf 兜底路）。
- **读数（bench rubric92 · 552 断言 · 纯确定性）**：所引章 top-1 **97.83%**、top-3 **99.82%**；消融（去掉「第N章」）同值 ⇒ 对章节字面零依赖。对照 idf 路 35.33%。
- **主库代价**：全量重建 3.4 万节点 53 秒；`_bucketskel.json` 5.72 MB、`_bucketterms.json` 21.09 MB；查询首调 0.64 秒（载入）→ 之后 0.00–0.01 秒。

### 新增：桶索引每日收尾自动重建（#838）

- `cg(op=info)` 触发；`_bucketindex_meta.json` 记上次重建时间，超过 `MDCG_BUCKET_INTERVAL_H`（缺省 20h）才重建；后台 daemon 线程 + 模块级重入防护，不阻塞 info。
- info 返回体透出 `bucket_auto`（rebuilt / reason / age_h）可审计；`MDCG_BUCKET_AUTO=0` 关闭。

### 修复：桶召回把最新的那条丢掉（#842）

- `_pick` 早先按 `(-hits, nid)` 排序后直接截 cap，时间序在截断之后才应用；9 条同等命中 + cap=8 时，被 id 序挤掉的可能正是最新那条。
- 现排序键在**截断前**就含时间序 `(-hits, recency, nid)` ⇒ 截断即保留「同分里最新的」。

### 修复：`validity=True` 排除的过期记忆被桶补召回装回（#843）

- 桶补召回在候选检索之后 append，早先既没传 `validity` 也没复用过期判据。
- 现 `_pick` 源头过滤 `validity`（只认 `frontmatter.valid_until`，解析失败不算过期），`scope_recall` / `day_scope` / `session_scope` 全链透传。

### 修复：scrub 幂等 / review_cli 落账 / bench 测量周期（#827 / #831 / #832；PR #839 / #840 / #841）

- `_weaken` 去重判据跟着节点走（旧判据读影子工作树里每轮归零的 `_scrub.jsonl`；实测 407 条负向证据仅 83 条不同、单键被记 52 次）。
- `review_cli` 以 `async_flush=False` 构造，写毕即落账重新成立。
- `bench_swarm_parallel` 测量周期拉离调度噪声区。

### 修复：`calibration` 在分母无正例时恒判 overconfident（issue #829）
- 判据是 `Σ正例 / Σ(正例+负例)`，而 `confirmed` 只由外部裁决产生；活库
  407→409 条证据**正例恒为 0** ⇒ `actual_accuracy` 数学上恒 `0.0`、
  `gap` 恒等于 `expected_accuracy` ⇒ `verdict` **恒为 overconfident**。
  该字段此前不携带信息，下游 `self_state` / `report` 却当真读数消费。
- 现 `Σ正例==0` ⇒ `calibration_defined=False` / `verdict="insufficient_data"`
  / `reason="no_positive_evidence"`，**方向三值一律不判**；
  `expected_accuracy` / `actual_accuracy` / `gap` / `ece` 仍如实透出（不隐藏、不编造）。
- 新增 `n_positive` / `n_negative` / `n_by_layer`：分母构成在读数面可见
  （`grep n_by_layer` 此前零命中）。三层不变量：`n_nodes`、`n_positive`、
  `n_negative` 分别等于 `n_by_layer` 各层求和。
- `scrub.calibrate()` 在 `calibration_defined=False` 时**拒绝出偏置**：
  返回 `ok=False` / `suggested_offset=0.0` / `n_adjusted=0`，`apply=True`
  也零写回。修前该路径会据退化的 `gap` 把全库 confidence 一律下调——
  一个不携带信息的读数直接改写事实层。
- `_advise()` 不判方向时不产出 `overconfident`/`underconfident` 建议，
  改产出 `no_positive_evidence`（带 why/action，可复核）。
- 有正例时判据**一字不改**（正向对照：全正例 → `actual=1.0` 且方向可判）。
- 守卫 `md_cg/test_issue829_calibration_positive_gate.py`：A/B/C/D/E 五组
  21 项，定点变异 **5/5 全杀**（含「M1 退回恒 overconfident」修前病象复现）。

## [0.9.23] - 2026-11-05

### 修复：`cg(op=read)` 自然问法普遍 DEFER（issue #722，Q1=A / Q2=A）

- `judge_qualification` 增 `strict_conditions`（库面默认 `true`，既有调用方零变化）；**工具面 `read`/`route` 缺省放宽**；
- 放宽**只到 `usable`**：`state` 仍是 `DEFER`，新增 `usable/relaxed/code/condition_status`，reason 明写「未冒充已确认」；
- **只放宽「生效条件未在情境确认」一支**；坏条件 / `REJECT` / `BLINDSPOT` / 验证基底**仍拦**；
- 守卫 10 条；`judge_with_boundary` 现在保留这四个标记键（原先被裁掉，导致「放宽了也看不见」）。

### 修复：`cg(op=info)` 在大库上超时（issue #677 B）

- `health_os()`（全库扫描类）改为**仅 `full=true` 时执行**；新增 `flush_state`（`pending_dirty/worker_alive/last_error`）与 `node_count`；
- **契约变更**：缺省不再含 health_os 的键（`buckets`/`bucket_scope`/`ccg_by_layer` 等）；要旧全集请传 `full=true`。

### 修复：写入成功后调用超时、重试产生重复节点（issue #677）

- `mdcg_remember` 支持 `dedupe`（与 `cg(op=write)` 同一个幂等闸）；**插件三类自动记忆默认带 `dedupe: true`**，可用 `memory.dedupe=false` 关闭；
- 服务端闸改为**同会话才幂等**：跨会话写同一句不会互相顶掉（叠加 `sessionPrivate` 时不再「命中但读不到」）。

### 性能：flush 锁内 IO 从 O(N) 降到 O(1)（issue #677 C）

- `ShardedLog.append_many`：**一次 write + 一次 flush**；整批仍在同一把 `FileLock` 内（与 compact 互斥语义不变）；
- 同时修两个崩溃安全缺陷：**残尾粘行**（末字节非换行先补 `\n`）、**失败回填丢 `superseded` 标记**（否则陈旧记录复活=旧盖新）。

### 修复：`FileLock.__enter__` 异常路径泄漏 fd（issue #740）

- strict 超时 / 非重试 errno / `timeout` 类型错 / `sleep` 中 `KeyboardInterrupt` 四条路径现在都走 `_close_fd()`；
- `__exit__` 复用（幂等、绝不抛），重复 `__enter__` 先清旧句柄。

### 口径收口：同一份指纹只留一个真源

- `reconcile._disk_hashes` 二元组收单值（#758）；
- `twophase` 指纹与索引条目同源（#759，`_norm` 降为 legacy 兼容）；
- 验证态继承改用索引 `content_hash` 比对、**不再读盘**（#757，撤 #352 §B 绕行）。

### 修复：scrub 把正文引用行当成断言键（误判矛盾）

- 键里出现括号类标点即不是字段名；值以 `src_/ref_/doc_` 开头不算可断言值；
- **注**：`…（源：src_x）` 的真凶是「`…（源`」这个**带括号前缀键**，不是单字「源」（后者被长度闸过滤）。

### 已知限制

- `cg(op=recall)`（预算装包路径）尚未接线 `strict_conditions`；
- `health_os()` 自身耗时未优化，仅被 `full=true` 挡在主路径外；
- scrub 的 `contradiction` 仍按字面键值比对，语义改写类误判只能靠「键形态」收敛，无法根除。
## [0.9.22] - 2026-11-03

### 修复：`cg(op=write)` 静默丢弃 `aliases`（issue #722，用户实测）

调用方传 `aliases=[...]` 时参数被**静默丢弃**，手动改 frontmatter 才生效。现已补三处转发面：
`writepipe._OUTLET_PARAMS` / `op_table.write.params` / `mcp_server` 入口。

> ⚠ 如果你装的是 **0.9.21**，你遇到的就是这个 —— 该修复在 0.9.21 发布**之后**才进 main，所以没随它发出。

### 新功能：会话身份 **A2 路线**（灵枢自读 DSH 会话文件算 `s5`）

- 新增 `resolve_sessions_root` / `locate_session_file` / `read_session_file` / `session5_resolve`；
- 守卫 **17 条**（`test_session5_resolve.py`）；
- 复用**已登记**的 `MDCG_DSH_SESSIONS_ROOT`（不新造环境变量）。

### 修复：`test_issue376_heartbeat_failed` 的 **A09** 是结构性竞态（issue #745）

A09 拿 `last_age_s`（`= time.time() - 最近成功 t`）做**跨调用** `==` 比较，而 `_st` 是测试早段算的、
`_OK_ONLY` 的读数在 A09 现场算，中间隔着 A01–A08 共 8 个检查 ⇒ 两侧时间差**几百毫秒**，
`last_age_s` 量化为 0.1s 桶 ⇒ **跨桶概率 ≈ Δt / 0.1s**，CI 慢一点必红。

现改为**冻结时钟**（只替换 `sustain` 名字空间的 `time`，不污染全局），14 键仍**逐位比较**。

> 实际影响：本版之前，`python-tests` 会**间歇性红在同一行**，与你的改动无关 —— 看到别慌，本版已修。

### 文档：密级（sensitivity）章节（`docs/ops/权限与复核模型.md`）

默认 `internal`、`private` 需两个前提、三档写闸实测矩阵。

### 文档：写入超时 ≠ 写入失败（`docs/ops/运维与排障.md`，issue #677 P3）

三条规则：① 超时后**先查**再重试；② 要幂等就**自带 `node_id`**（同 id 覆盖，实测 `1→1`）；
③ `importance ≥ 0.7` 的重复条目**不好清**（自动 `protected`，删除需 `override`）。

### 文档：`validity` 语义 + 四个易误读取舍（`README.md` + 两处 docstring，issue #672）

- `validity=true` **只排「已过期」，不排「未生效」**（`meta.validity_scope = "expired_only"`）；
- `importance` 默认 0.5，但 **≥0.7 自动硬保护**；
- `calibration` **只给建议**，`apply=True` 才写回；
- 会话窗口的「重叠」**是设计**，不是冗余。

### 其它

- `fix(op_table)`：`aliases` 从 `_GENERIC_PARAMS` 撤出（避免与 `write.params` 重复计数）；
- `chore(cogmap)`：重挂行号（`mcp_server` 加 `aliases` 后漂移 4 行）。

## [0.9.21] - 2026-10-31

### 修复：规范文档**随包分发**（0.9.20 只给了外链）

0.9.20 的做法是「README 给 GitHub 绝对链接」——解决了「知道有」，**没解决「装完能读到」**。

**本版把 7 个用户该遵守/该查的规范放进 `files` 白名单**：

| 文件 | 用途 |
|---|---|
| `docs/mdcg/写入别名aliases规范_v0.6.md` | **写记忆时怎么补 `aliases`**（0.9.19 新增能力） |
| `docs/mdcg/CCG六要素编译.md` | 六要素怎么写 |
| `docs/mdcg/guardrail-charter.md` | 护栏宪章（对外公开法案） |
| `docs/mdcg/MCP工具名口径_v1.0.md` | 工具名口径 |
| `docs/mdcg/recall_metadata.md` | 召回元数据 |
| `docs/mdcg/世界模型功能端_使用与运维_v1.0.md` | 世界模型面使用与运维 |
| `docs/mdcg/cogmap_ops.md` | cogmap 操作 |

⇒ 装完包后，这 7 个文件在 `node_modules/@furongjun1999/dsh-memory/docs/mdcg/` 下可直接读。README 文档地图的链接也改回**包内相对路径**。

### 为什么不整目录打包

`docs/mdcg/` 共 **47 个 .md**，其中混着内部记录（`release_v0.3.0.md`、`CSRE_索引与负条件修复_20261012.md`、各 `plans_*`、`D_meta_工程化方案` 等）。
**整目录打包会把内部记录也发出去**，所以按文件挑 7 个。

### 仍未打包（明确边界）

- `docs/theory/`（19 个，内部理论）
- `docs/eval/`（136 个，内部评测）
- `docs/plans/`（25 个，内部计划）
- `docs/ops/`（8 个，安装运维——README 里既有相对链接，**在 npm 页面上仍点不开**，属存量问题）

## [0.9.20] - 2026-10-31

### 修复：规范文档的可见性（0.9.19 的疏漏）

0.9.19 的 CHANGELOG 里写了「规范全文：`docs/mdcg/写入别名aliases规范_v0.6.md`」，
**但 `docs/mdcg/` 从来不在 npm 包的 `files` 白名单里** ⇒ 那是个**包内死链**，用户装了包也找不到。

**本版修复**：

| 面 | 改动 |
|---|---|
| `README.md` · 文档地图 | 新增一行「**写入规范**」，用 **GitHub 绝对 URL** 链到「写入别名 aliases」「CCG 六要素编译」「护栏宪章」，并**明确标注「这几个不在 npm 包里」** |
| `CHANGELOG.md` · 0.9.19 节 | 死链改成 GitHub URL，并标注「不在 npm 包里，需在仓库看」 |

⚠️ **为什么不用相对路径**：README 里既有链接都是相对路径（`docs/ops/README.md` 等），
在 npm 包页面上**同样点不开**——本次新加的一律用绝对 URL。

> 这是「打包白名单」与「文档指引」之间的老问题：`docs/mdcg/` 有 47 个 .md，
> 其中既有用户该遵守的规范（`写入别名aliases`、`CCG六要素编译`、`guardrail-charter`），
> 也有内部记录（`release_v0.3.0`、`CSRE_索引与负条件修复`、各 `plans`）。
> **整目录打包会把内部记录也发出去**，所以本次选择「不打包 + README 给绝对链接」。

## [0.9.19] - 2026-10-31

### 新增：`aliases`（写入别名）——自然问法召不回的解法

**用法**：写记忆时给节点加 `aliases`，把「用户以后可能怎么问这件事」的说法写进去。

```python
cg(op="write", node_id="...", content="""# 功能名：会话交接前的记忆固化
# 生效条件：聊交接、换会话、压缩、或他流露舍不得时
...""",
   aliases=["换掉", "被换", "别消失", "舍不得", "不想你走", "压缩上下文"])
```

`aliases` **参与词法召回，但不进 `tags`**——`tags` 被机器判据占用（「是不是任务卡」「能不能当锚点」），
混用会改变那些判据。

**写别名的正确方法**（实测总结）：写之前**先自问一句「以后我会怎么问这件事？」**，把那些问法原样写进去（3–8 个，口语/情绪/近义都算）。

> ⚠️ **不要机械抽词**。实测：从功能名按空格切词自动生成，20 条 × 5 查询 = **提升 +0**
> （中文功能名没有空格，切出的是整句）。别名只能"想"出来，不能"切"出来。

**为什么需要它**——issue #722 的决定性案例：

| 匹配方式 | 条件「聊交接、换会话、压缩…」 vs 查询「我不想你被换掉」 |
|---|---|
| 整词匹配 | ❌ |
| 二元组重叠 | ❌ `换会/会话` vs `我不/…/被换/换掉` —— **交集空** |
| 查询扩展 | ❌ 扩出 `换掉/被换`，与 `换会话` **仍无交集** |
| 现有同义词表（10 组，全技术词） | ❌ |
| **加 `aliases`** | ✅ **命中** |

规范全文（**不在 npm 包里，需在仓库看**）：[docs/mdcg/写入别名aliases规范_v0.6.md](https://github.com/FuRongJun-1999/dsh-memory/blob/main/docs/mdcg/写入别名aliases规范_v0.6.md)

### 修复

- **Web 面板 `permissionNote` 不认通配符 `*`**（#723 / PR #724）：全权令牌（`ops_allow: ["*"]`）下，
  「目标与任务」「自我认知」「时空关系」「审核与维护」四页的 **12/12 预设全部误报「未声明权限」**，
  而实际调用完全成功。根因是**前端与服务端判据不同口径**：
  服务端 `_in_scope` 认 `"*" in allow`，前端只做 `allowed.includes(op)`。现已对齐。

  ⚠️ 判据正好反了的现象值得记：**全权令牌看到满屏红，窄令牌反而只有部分提示**。

### 新增：写入把关判据（**尚未接线，仅提供可测函数**）

| 函数 | 作用 |
|---|---|
| `writegate.cond_is_metadata(cond_text)` | 判「生效条件」是否在描述载体/路径/方法（元数据），而非触发场景 |
| `writegate.check_condition_quality(content)` | 上述的写入把关包装，返回 `{ok, is_metadata, cond, hint}`；**任何情况不抛** |
| `writegate.aliases_is_thin(fm, content)` | 判别名是否「薄」（无别名，或只重复正文已有词） |

⚠️ **这三个函数尚未接进 `add()`**——只提供可测入口，接线是下一次改动。

### 内部：测试与守卫

- **`test_mode_parity` 的 `full_D` 跨分钟时间泄漏**（PR #720）：`tombstone` 是内容哈希，
  而内容含墙钟聚合行 ⇒ 两个子进程跨分钟必然 DIFF。已在 `_RUNNER` 注入固定时间戳。
- 新增守卫：`test_723_permission_wildcard`（6 条，**跨侧口径一致性**，与 `test_rust_fold_parity` 同族）、
  `test_722_condition_quality`（8 条）、`test_722_aliases_thin`（11 条）。

### 实测基线（供对照，非承诺）

本机库（32,845 节点）实测：

| 项 | 读数 |
|---|---|
| 自然问法召回条数 | **2 条** |
| `aliases` 覆盖率 | **0%** |
| `knowledge` 层里 `role=None`（索引卡片） | **99.7%** |
| 生效条件为元数据的比例 | **76.5%** |

⇒ 所以 `aliases` 的价值取决于**写入时是否真的写了**。库内现有节点**不会自动获得**它。

## [0.9.18] - 2026-10-30

### ⚠️ BREAKING：注入块格式变更

`【本会话近期对话】` 块的行格式改为带**归因前缀**（issue #712 / PR #713）：

```
旧：[user] 内容
新：[10-30 14:23|本|私] [user] 内容
      └──┬──┘ └┬┘ └┬┘
       时间   会话 密级
```

| 段 | 取值 |
|---|---|
| 时间 | `MM-DD HH:mm`；缺失渲染 `??-?? ??:??` |
| 会话 | 等于当前会话 → `本`；其他 → `会话<后4位>`；缺失 → `?` |
| 密级 | `private`/`secret` → `私`；`public`/`internal`/`restricted` → `共`；缺失 → `?` |

**为什么改**：此前模型只看到 `[role] 内容`，无法判断「这是自己刚说的、还是别的会话说的、是私有还是共有」——
实测出现过「把另一个窗口的话当成当前用户刚说的」的误引（#712）。

块总长上限随之 `800 → 900` 字符（前缀约 20 字符/行）。
**若你有依赖旧格式的解析/断言，请同步。**

### 新增

- **`cg(op=info).write_gate`**（#708）：分层写入闸的**进程内计数**——`{mode, total, by_layer, recent, hint}`。
  此前 `warn` 档只写子进程 stderr，而 DSH 不转发 ⇒ 观察期等于没有。
  现在不依赖 stderr 转发、不写盘；`recent` 只留 `layer/tier/reason`（**无内容、无节点 id**），有界 20 条。
  计数**重启归零**，建议观察一个完整工作日再决定是否切 `enforce`。
- **`Principal.sessions_read`**（#712 / 方案 C 分档隔离）：`None` = 旧行为逐位不变；集合 = 只读这些会话；
  `{"*"}` = 全读。**`can_admin` 不削弱**（issue #35「设计者豁免」定稿）。
- **事件归因四要素**：`pack["recent"]` 条目现含 `session`/`t`/`id`/`sensitivity`/`actor`/`token_id`/`identity_role`/`parent`。
  事件新增稳定键 `id`（`re_<ms>_<6hex>`，**归因展示用，不得用于权限判定或去重定位**）。
- **理论文档**：《身份与人格：职业身份的可变性 vs 人格的一致性》
  （`docs/theory/身份与人格_职业身份可变性与人格一致性_v0.1.md`）——
  区分**人格**（跨会话恒定，`self`/`anchor` 层）与**职业身份**（会话级，工作层 + 事件归因）。

### 修复

- **`enforce` 档下裁决审计节点被同一闸挡住**（#708 ② / #709）：`_write_review_record` 写 `structural`（2 档），
  却不传复核单元 ⇒ `decisions.jsonl` 还在、**可复核的 md 审计节点没了**。
  现在把本次裁决已取得的 `reviewed_by` 一路带进写入。
- **同一条链上两个更靠前的缺口**（查 #709 时发现）：
  - **`propose` 死锁**：候选入 inbox 本不落记忆盘，却按目标层要求复核单元 ⇒
    enforce 下「要写 knowledge 需 reflect → 要 reflect 需裁决 → 要裁决需提案 → 提案又要 reflect」。
    现在 `require_layer_write(..., skip_gate=False)` 新增该参数，**只** `propose` 传 `True`；
    层白名单与密级检查**照常执行**，`accept` 落盘仍走同一道闸。
  - **`accept` 落业务节点**不传 `reviewed_by` ⇒ 「裁决过了、落盘被拦」。
- **`reviewed_by` 不再污染 frontmatter**：它是**写入闸的输入参数，不是记忆元数据**。
  此前用 `kw.get()` 只读不删，会经 `super().add(**kw)` 落进节点 fm（实测 `test_i50c` 的 B1 逐键对拍报出 `reviewed_by: null`）。
  现在改为 `kw.pop()`。
- **`actor` 恒为 None**（身份归属空心）：`MdCGSecure.remember_event` 里 `tenant`/`session`/`harness`/`unit`/`sensitivity`
  **都从 principal 落值**，唯独 `actor`（「谁说的」）没落 ⇒ 注入面拿到的 `actor` 恒为 None。已补。
- **取窗顺序 bug ×2**（#712 / #715）：`session_recall` 与 `session_compact` 都**先截末 N 条、再按会话过滤**
  ⇒ 多会话并发时本会话消息被挤出窗口，`session="A"` 可能拿到**空 recent**（false-negative，极难被发现）。
  `session_compact` 更重——它会压出「共 0 条事件」并**写入会话节点**（写错一条记忆）。
  修法：需要收窄时先取全量、再过滤、最后截回。
- **`session` 为 falsy 时静默退回全局窗口**（#712）：现在会在 `degraded` 里加 `recent_global_window`，调用方看得见。
- **身份块恒为空**（#715）：`【灵枢身份锚点】` 复用了**带会话过滤**的 timeline payload，
  而 `self`/`anchor` 节点的 `session` **恒为 `unattributed`** ⇒ 永久层被全部滤掉 ⇒ **块从不出现且无报错**。
  现在身份块**独立取数、不带会话过滤**；「最近记忆」块保持会话隔离。
  这正是理论 R3 的实案：**人格的可见性不该由会话决定**。
  另加 `else` 分支 `logger.info`——开关开了但无身份节点时显式提示，不再静默。
- **会话 id 为空时静默退回全局窗口**（PR #714 by LeeRolling）：现在 `logger.warn` 一次（不刷屏）。

### 内部

- `test/chaos_injection/test_fi_m09_guest_write_denied.py` 的读码锚点从「完整调用串」放宽为「`layer, sens` 两参在位」，
  并去掉两处硬编码行号。
- `test_generation_guard.py` 的 `NEW_INFO_KEYS` 登记 `write_gate`。
- `test_p45_session_identity.py` 的变异锚点同步新形态（**变异语义不变**）。
- 新增守卫：`test_issue712_session_window_attribution`（29 条，含取窗顺序/四要素/身份三维/分权）、
  `test/issue715`（W715）、`test/issue714`（W714 / W714b）。

### 升级须知

- **`--gate` 缺省仍是 `strict`**；`op=info` 只**新增**键；`sessions_read` 缺省 `None` = 旧行为逐位不变。
- 若你在 #708 / #709 遇到过问题：升级后 `cg(op="info")["write_gate"]` 可看 warn 计数，
  `review accept` 的返回体里 **`record_error` 应为空**。
- 若你在 #712 / #715 遇到过问题：升级后注入块应带归因前缀，`autoRecallIdentity: true` 时身份块应出现。
## [0.9.17] - 2026-10-28

### 修复

- **`warn` 档对用户完全不可见（#708 ①）**：`security._write_gate_verdict` 只做 `sys.stderr.write`，而 DSH 不把这条
  转发进 `desktop-next.log` ⇒ 观察期等于没有。现在 `writegate` 维护**进程内计数**并经 `cg(op=info).write_gate` 透出：

  ```python
  cg(op="info")["write_gate"]
  # {mode, total, by_layer: {"knowledge@L1": 3}, recent: [{layer,tier,reason}…], hint}
  ```

  不依赖 stderr 转发、不写盘；`recent` 只留 `layer/tier/reason`（**无内容、无节点 id**），有界 20 条。
  stderr 那行保留（宿主愿转发时仍实时可见）。

- **`enforce` 下裁决审计节点被同一闸挡住（#708 ② / #709）**：`_write_review_record` 写 `structural`（2 档：需 reflect+verify），
  却不传复核单元 ⇒ `decisions.jsonl` 还在、**可复核的 md 审计节点没了**。现在把本次裁决已取得的 `reviewed_by`
  一路带进写入：`review_decide → _finish_decision → _record_decision → _write_review_record → add(reviewed_by=…)`。

- **同一个漏洞的两个更靠前落点（查 #709 时发现，一并修）**：
  - **`propose` 死锁**：候选入 inbox 本不落记忆盘，却按**目标层**要求复核单元 ⇒ `enforce` 下
    「要写 knowledge 需 reflect → 要 reflect 需裁决 → 要裁决需提案 → 提案又要 reflect」。
    现在 `require_layer_write(..., skip_gate=False)` 新增该参数，**只** `propose` 传 `True`；
    层白名单与密级检查**照常执行**（跳过的只有 write_gate 一档），`accept` 落盘仍走同一道闸。
  - **`accept` 落业务节点**不传 `reviewed_by` ⇒ 「裁决过了、落盘被拦」。现在一并透传。

- **`reviewed_by` 不再污染 frontmatter**：它是**写入闸的输入参数，不是记忆元数据**。此前沿用 `kw.get()` 只读不删，
  会经 `super().add(**kw)` 落进节点 fm（实测 `test_i50c` 的 B1 逐键对拍报出 `reviewed_by: null`）。现在改为 `kw.pop()`。

### 内部

- `test/chaos_injection/test_fi_m09_guest_write_denied.py` 的读码锚点从「完整调用串」放宽为「`layer, sens` 两参在位」
  （`require_layer_write` 现在多了 `reviewers=` 实参）；同时去掉两处硬编码行号——行号会随改动漂移。
- `test_generation_guard.py` 的 `NEW_INFO_KEYS` 登记 `write_gate`（`op=info` 的新增诊断键，与 `code_generation` 同类）。

### 升级须知

- 本版**无破坏性变更**：`skip_gate` 缺省 `False`；`--gate` 缺省仍是 `strict`；`op=info` 只**新增**一个 `write_gate` 键。
- 若你在 #708 / #709 里遇到过问题：升级后 `cg(op="info")["write_gate"]` 可看 warn 计数，
  `review accept` 的返回体里 **`record_error` 应为空**。
- 计数是**进程内累计、重启归零**（不落盘），建议观察一个完整工作日再决定是否切 `enforce`。
## [0.9.16] - 2026-10-28

### 修复

- **`/lingshu` 在 DSH 0.2.1-rc.3 上恒 503「宿主鉴权不可用」（#699）**：`createConsoleHandler` 在**挂载时**取一次
  `ctx.get('connection')`，而 cordis 的 `Context.get(name, strict=true)` 在服务 fiber 未就绪时返回 `undefined` ——
  空值被闭包固化后每个请求都命中 503，宿主就绪也不自愈。现改为**每次请求实时取**（传取值函数，非函数则包成常量，向后兼容），
  503 文案改为「宿主鉴权服务尚未就绪，请稍后重试」。守卫 3 条，其中「连接后到 ⇒ 同一 handler 立刻 200」正是病灶点。
- **测试入口「零选中假绿」（#1910 跨仓报告）**：`--module` 的 help 教的是**斜杠**写法（`md_cg/test_issue4`），
  而实际目标名是**点号**（`md_cg.test_issue4`），旧实现未归一化 ⇒ 斜杠写法选中**零个目标**却仍 `SUMMARY 0/0` + `rc=0`。
  现归一化（斜杠 ≡ 点号、忽略 `.py`、空选择器不命中）+ **零选中不得返回 0**（执行路径 `rc=2`）。守卫 21 条含判别力自证。
- **F26-13 `_primary_bound` 注释与实现不符**：`#637` 注释承诺「T3 按分数>0 裁切」，但代码只在 `n_real == 0` 时裁。
  经实测：按注释补实现会**砸掉 S1b/S7 的「回退含异桶节点」契约**（`test_retr_s1b`/`test_retr_s7` 立即转红）⇒
  确认「默认不裁」是刻意取舍，改为**注释对齐实现**并把实证写进注释（防后来者重踩）。
- **F26-25 Rust 侧重音折叠缺失**：`normalize_en` 把非 ASCII 非中文一律变空格 ⇒ `café` → `caf`，而 Python 给 `cafe`。
  受 `Cargo.toml`「零第三方依赖」约束，改为**按 Python 口径生成** 963 条单字符映射表 + 三区间组合记号剥离；
  跨实现守卫 **29 条**逐项核对（含 `ß`/`ø` 不折、日文浊点不折的边界）。

### 新增

- **门禁档位 `--gate fast|strict` + `--module` 过滤**（`scripts/run_tests.py`）：
  「快 = 问题放一边 / 慢 = 细究根本原因」是价值观取舍，**选择权交给使用者**；守卫侧一行未改，
  「是否跑重质检」由上层决定。缺省 `strict`（不降低既有强度）；**CI 环境 + `fast` 自动升级 strict** 防漏检。守卫 17 条。
- **配置登记生成器「只增不改」守护**（`scripts/gen_config_registry.py`）：整文件重写会抹掉手工补的行
  （实测事故：`MDCG_WARM_SEARCH`/`MDCG_VISION_ROOT` 消失）。现在写盘前用 AST 读旧表条目名，少一条就拒绝（`rc=3`），
  `--force` 为显式逃逸口。守卫 14 条。
- **审计增加 `source` 键名集合维度**（`src/lib/hook_audit.ts`）：#695 的关键缺口是「事件的 `source` 到底带哪些字段」不可观测。
  新增 `source_shapes` 桶，**只记键名、绝不记值**（哨兵守卫钉住）。实测本机 383 个会话 / 9,614 行：`user` 档占 18.4%，
  其中带 `rpcId` 80.3%、**仅 `kind` 的 19.7%** —— 这条读数把「来源归因」从猜测变成可量化。
- **`entry_from_row` 两处静默回落改为可观测**（`md_cg/config_registry.py`）：`literal_eval` 失败与 `value_type` 缺失
  此前完全无痕（数值型登记会被静默当字符串）。新增 `literal_failures()` / `missing_value_types()` 两个读取口，**行为零变更**。守卫 15 条。

### 文档

- **README 321 → 227 行**：把「图形界面」与「权限」两章各压到 ~14 行（一句话定位 + 最小命令 + 一张表 + 链接），
  细节移入 [`docs/ops/图形界面_安装与排障.md`](docs/ops/图形界面_安装与排障.md) 与 [`docs/ops/权限与复核模型.md`](docs/ops/权限与复核模型.md)。
  README 的读者是「30 秒内决定要不要用」，细节属于 `docs/`。

### 升级须知

- 本版**无破坏性变更**：`--gate` 缺省仍是 `strict`；`createConsoleHandler` 保留旧的「直接传值」调用方式；
  `--module` 两种写法现在都能用（此前斜杠写法会零选中）。
- 若你在 DSH 0.2.1-rc.3 上遇到 `/lingshu` 恒 503：升级后**无需额外操作**，服务晚到也会自愈；
  若仍 503，请附 `$DSH_HOME/logs/dsh-memory-hook-audit.json` 的 `kinds` 段（不含内容）回帖。
## [0.9.15] - 2026-10-27

主题：**权限分层与复核模型落地**（读/写/裁三层各自可收窄）＋ 一次数量级的性能修复 ＋ 两个「装不上/起不来」的真 bug。

### 新增 · 写入与裁决的复核模型

- **分层写入严格度闸**（`MDCG_WRITE_GATE`，缺省 `off`）——情景/目标/未解/负记忆（0 档）无复核也可直写；
  知识层需反思单元；结构层需反思+验证；自我/锚点层需反思+验证+**人工裁定**。
  **无任何复核通道时只允许写 0 档**，其余一律拒写。
- **裁决双单元复核闸**（`MDCG_REVIEW_DUAL_CHECK`，缺省关）——裁决须带 `reviewed_by` 同时含反思与验证单元；
  **同类重复不算齐备**（两个反思仍无验证）；裁决者不得是提案者（`self_review_forbidden`）；未知单元不静默计入。
- `MDCG_REVIEW_CHANNELS`（复核通道声明：`hive,subagent,team`）。注意它是**部署声明**：
  为空只表示「没声明过」，**不等于**本机没有子代理/蜂巢/团队。
- **设计者令牌覆盖面判据**——`DESIGNER_COVERAGE_OPS` / `coverage_gap()` / `HIGH_RISK_OPS` / `high_risk_granted()`；
  `tokens verify` 输出附 `designer_coverage_gap`；签发时把「收窄缺读面」「给了高风险面」两类提示写进返回值 `warnings`
  （库层不写 stderr，由 CLI 入口打印）。

### 新增 · 图形界面（可选增量包）

- `ui/minimal/`：一行安装、逐文件可回滚、复用本机大脑桥（数据不出机）；
  七页面板（概览 / 记忆 / 目标与任务 / 自我认知 / 时空关系 / 审核与维护 / 工具台）。
- `package.json` 的 `files` 白名单加入 `ui` 与 `web`，**随 npm 包分发**安装器、payload 与静态资源。
- **接线入库**：`dsh.client` / `exports["./client"]` 写进 `package.json`、`installConsoleWeb(...)` 写进 `src/index.ts`；
  产物由新增的 `scripts/build_ui.py` 生成（幂等；`--check` 只校验、缺文件 fail-closed；`build` 与 `prepublishOnly` 均自动执行）。
  于是**改插件清单不再需要重装 UI**；`install.ps1` 转为面向「从 npm 包装到本机插件目录」的最终用户，
  对无接线的旧插件包仍会自动补齐。守卫 `md_cg/test_ui_wiring_in_repo.py`（18 条）钉住声明/分发/构建三面不漂移。

### 性能

- `protect.stats()` 改**条目口径**（读索引，不再逐节点读盘取 frontmatter）：
  在役库（3.2 万节点）冷态 **310 s → 0.015 s**。该函数经 `cg(op=info)` 的 `protection` 段被无条件调用，
  是 UI 概览页「像卡死」的根因；修后概览页从 5 分钟级降到秒级。
  语义不变：全量比对 `protected` / `immutable` **差异 0**。

### 修复

- **UI 增量包在 Windows 上装不上**：payload 被 `core.autocrlf` 检出成 CRLF，与 `integrity.json`（按 LF 记 sha256）失配，
  安装器误报「分享包文件缺失或损坏」。已用 `.gitattributes` 钉 `ui/minimal/payload/** eol=lf`。
- **hive serve 起不来**：`config.local.json` 的 `{"env": "DEEPSEEK_API_KEY"}` 读的是**调用进程**环境变量，
  DSH 子进程继承不到机器级变量 ⇒ 误报「配置项解析失败」。已增 Windows 机器级回落
  （进程 env 显式值仍优先；两者皆空仍 fail-fast）。
- 配置登记面补登记 `MDCG_WRITE_GATE` / `MDCG_REVIEW_CHANNELS` / `MDCG_REVIEW_DUAL_CHECK`。

### 文档

- README 新增两章：「🖥️ 图形界面（可选增量包 · 面向 DSH）」与「🔐 权限：读 / 写 / 裁 三层，各自可收窄」，
  含七页中哪四页是命令面板、排障三条、只读面 17 op、分层写入矩阵、裁决双单元、报错对照表。

### 升级须知

- **三个新开关的缺省值都保持旧行为**（`MDCG_WRITE_GATE=off`、`MDCG_REVIEW_CHANNELS` 空、`MDCG_REVIEW_DUAL_CHECK` 关）
  ⇒ 升级后行为不变，需显式开启。建议顺序：先 `warn` 观察，接好复核通道后再 `enforce`。
- 设计者令牌**不因升级而变宽**；若你的令牌曾被人为收窄，`tokens verify` 会报 `designer_coverage_gap` 并点名缺哪些面。
- Windows 用户此前 UI 装不上的，本版可直接安装。

### 已知边界

- 写入闸与裁决闸只认「复核单元声明」，不做证据真伪校验（真伪由蜂巢/子代理侧签章承接）。
- `MDCG_WRITE_GATE=enforce` 前请先声明 `MDCG_REVIEW_CHANNELS`，否则知识层以上（含自动归档）会被拒写。
