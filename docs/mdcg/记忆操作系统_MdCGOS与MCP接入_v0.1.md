# md_cg · 记忆操作系统（Memory OS）· 实现与接入

> 在 MdCG（P0/P1 已验证引擎）之上补齐「记忆操作系统」能力，并暴露为 MCP 服务。
> 2026-09-09 · 全部经 dsh 端独立实跑验证

---

## 一、本次交付

| 文件 | 职责 |
|---|---|
| `md_cg/mdcos.py` | **MdCGOS**：在 MdCG 上新增记忆 OS 能力（7 项 + 后续 P8–P11） |
| `md_cg/mcp_server.py` | **MCP server**（stdio + JSON-RPC 2.0，协议 2024-11-05，零依赖）；**默认只暴露 2 个认知基元 `cg`/`stg`**（`MDCG_MCP_SURFACE=full` 才另见 29 个细粒度工具，供兼容/调试）|
| `md_cg/consistency.py` | **节点间自动冲突检测**（三级决策：情绪 → 反思 → 递归反思）· 冲突自动触发飞轮 · **已接入 `cg(op=write)` 写入前校验** |
| `md_cg/test_p2.py` | P2 验收（7 项能力）**36/36** |
| `md_cg/test_p2_mcp.py` | MCP 协议验收 **63/63** |

回归：**P0 25 · P1 37 · P2 36 · P2-MCP 63 · P3 33 · P4 44 · P5 36 · P6 72 · P7 36 ·
P8 34 · P9 37 · P10 24 · P11 27 · P12 32 · P13 42 · P14 44 · P15 53 · P16 46 · P17 55 ·
并发锁 300/300 全绿（共 776 项）**。

> **2026-09-10 增补（md_cg 唯一真源）**：白箱 LLM provider 下线、AEIS 降为**能力库**；
> 新增 `md_cg/whitebox.py`（`cg(op=whitebox)` 显式调用白箱并验证其「编码 / 已有知识回答」能力，
> P18 **20/20**）与 `md_cg/migrate_roleplay.py`（角色/转录/互维 → 认知图，P19 **13/13**）。
> **功能 → 代码 全表见 [功能调用映射表_v0.1.md](功能调用映射表_v0.1.md)。**

---

## 二、七项能力（对标 deja-vu / dsh-noema）

| # | 能力 | 接口 | 要点 |
|---|---|---|---|
| 1 | **Fix pairs 自动挖掘** | `mine_fix_pairs(events)` | 行为日志「错误→修复」→ **knowledge/ 可路由修复知识** + **rejected/ 负记忆**（此错不必深挖根因）；幂等 |
| 2 | **role 分层索引** | `add(role=...)` · `search(roles=, include_work=)` | 工具输出/命令/编辑（`tool-output/command/edit`）**默认不参与正排**，避免稀释召回 |
| 3 | **RRF 并行多路召回** | `search_rrf(...)` | 词法 / 条件桶 / 实体 / 图扩展 四路并行 → Reciprocal Rank Fusion；结果带 **provenance**（可审计）|
| 4 | **审核队列 edit/merge** | `propose` · `review_list` · `review_decide` | 海马体式 `hippocampus/inbox.jsonl` → `decisions.jsonl`；裁决 **accept / reject / edit / merge** |
| 5 | **tombstone + 恢复检查** | `forget` · `restore` · `is_tombstoned` | 软删除入 `trash/` + `_deletions.jsonl` 删除清单；恢复时校验，须 `force` 才可强恢复 |
| 6 | **payload-free 审计** | `_audit` · `audit_records` | 每次变更只记 `{t,op,id,actor,payload_hash}`，**绝不记内容** |
| 7 | **budget-driven pack** | `recall(query, budget_tokens)` | 装到预算花完；**超大条目跳过而非停下**（继续尝试更小的）|

另：`health_os()` 在原有健康度上并入 OS 指标（role 分布 / 待审数 / 墓碑数 / 审计事件数 / 反思数）。

---

## 三、DSH 接入（MCP）

### 3.1 启动

```bash
# 在仓库根目录启动：路径全部相对当前目录，无需改任何绝对路径
MDCG_ROOT="data/mdcg" \
MDCG_ACTOR="dsh" \
PYTHONPATH="." \
python -m md_cg.mcp_server
```

### 3.2 DSH 侧配置（cordis.yml / MCP client）

```yaml
- id: mdcg
  name: mdcg-mcp            # MCP server（stdio）
  config:
    command: python
    args: ["-m", "md_cg.mcp_server"]
    env:
      MDCG_ROOT: "data/mdcg"      # 相对 DSH 进程 cwd；cwd 不稳定时改成绝对路径
      MDCG_ACTOR: "dsh"
      PYTHONPATH: "."             # 需在仓库根目录启动 DSH，python 才能 import md_cg
```

### 3.3 工具面（默认 kernel：只暴露 `cg` / `stg` 两个认知基元）

> **架构**：对外只提供**认知图**工具。`cg(op=route)` 按情境条件路由，返回知识 +
> **建议能力名（不执行）**，由调用方用本地代码执行——「认知图只给能力名，执行权归调用方」。
> 下列 29 个细粒度工具仅在 `MDCG_MCP_SURFACE=full` 时可见，供兼容/调试。

```
写：mdcg_remember（gated=true 走主动遗忘闸门；consistency=true 走冲突检测）·
    mdcg_rejected · mdcg_unresolved · mdcg_propose
读：mdcg_get · mdcg_search · mdcg_recall · mdcg_review_list · mdcg_review_records
认知：mdcg_reflect · mdcg_verify · mdcg_flywheel · mdcg_mine_fix_pairs ·
    mdcg_consistency（check/history/stats/catalog）·
    mdcg_metacognition（观测面/校准/盲区/信任/self_check）·
    mdcg_predict（routes/feedback/stats/catalog）·
    mdcg_causal（path/gate/chain/explain/catalog）
生命周期：mdcg_forget（override）· mdcg_restore · mdcg_review_decide
保护/遗忘：mdcg_protect（盘点/查询/标记/快照/历史）· mdcg_forgetting_history
身份识别：mdcg_identity（observe/anchor/trait/profile/positions/catalog）
自我状态：mdcg_self_state（snapshot/refresh/bootstrap/relate/relations/index/
    dimensions/audit/history/summary/catalog）
运维：mdcg_health · mdcg_whoami · mdcg_ingest · mdcg_watermarks · mdcg_service_info
能力库：mdcg_whitebox（ask/remember/verify_encoding/verify_existing/ping/report）
```

写保护：`self` / `anchor` 层与 `protected` 标记、`importance≥0.7` 的节点**不可遗忘**，
删除/降级需显式 `override=true`（自动快照 + `_protected_audit.jsonl` 留痕）。

**白箱能力库**（`cg(op=whitebox)`，`md_cg/whitebox.py`，2026-09-10）：
白箱 LLM provider 已下线（不再注册 `lingshu-whitebox`）；白箱能力改由 md_cg 显式调用并留痕：
`action=ask` 问答 · `remember` 编码 · `verify_encoding` 验证编码能力（口令→追问命中）·
`verify_existing` 验证已有知识回答能力（`route=self` 且非空）· `ping` · `report`。
结论写回 `self` 层（`tags` 含 `whitebox:verify`）。详见
[功能调用映射表_v0.1.md](功能调用映射表_v0.1.md) §3。

**持续性自维持**（`cg(op=sustain)`，P14 `sustain.py`）：
心跳戳（`~/.mdcg/sustain/heartbeat.<name>.stamp`，含 ts / pid / uptime / task_running）
→ 分级判定（2.5× / 3.5× 心跳间隔；**任务执行中阈值放宽**，长任务不被误判死亡）
→ 只读诊断（索引漂移 / 孤儿索引 / 陈旧临时文件 / 半截日志行 / 增量积压 / 缺密钥私有节点）
→ 自愈（只重建索引、清陈旧临时、补日志换行——**永不删节点**；缺密钥只报告不修）
→ 会话水位续接（`_sessions.json` 记 (last_t, last_seq, events)，重启不重复摄取）。
MCP 进程启动即自维持（`MDCG_SUSTAIN=0` 关闭；`MDCG_SUSTAIN_BEAT/HEAL` 调间隔）。

主动遗忘闸门（写入侧三问 → 四态）：重复？→ `redundancy`；重要？→ `importance`；
惊奇？→ 自信息代理 `-log2(dup+ε)`（结构类比量，非香农熵）。裁决
`ACCEPT / MERGE / DROP / DEFER` 全部写入 `_forgetting.jsonl`，可审计。

身份特征识别（取代单一「用户画像」）：识别每个主体（`self` / `user` / `role` / `agent`）
的**身份锚点 + 位置效应 + 条件特征**。位置效应取自智能论 v3.4 §十三 五大单元
（记录=全 / 反思=新 / 验证=稳 / 输出=通 / 维生=存），按行为证据投票推断，
返回 `confidence / votes / evidence_count`，可审计「为什么判成这个位置」。
扮演论三接口：`memory`（历史证据→知识层）/ `anchor`（身份锚点→self|anchor 层，
不可遗忘；`role` 不得进 self 层）/ `values`（条件特征→结构层，条件空间即触发时机）。
留痕 `_identity.jsonl`。

节点间自动冲突检测（信息写入前校验 · 三级决策）：`md_cg/consistency.py`。
**L0 情绪** = 信息差二阶变化 d²D/dt²（approaching / stable / avoiding；原文强制
**独立通道，不参与信任/资格计算**，只做流程调度）→ **L1 反思** = 条件论「反题」
检测（自否定 / 违反纪律 / 条件互斥）→ 四态路由 **ACCEPT / REJECT / DEFER / BLINDSPOT**
→ **L2 递归反思**（沿关系链找「区分条件」，受**深度 / 节点数 / 循环 / 信息增益门槛**
约束，智能论 :273：「若递归没有减少候选空间，就不应继续搜索」）。
冲突**自动触发知识飞轮**（误差 → 补条件 → 结构更新，:725），落 `unresolved` 条目；
留痕 `_consistency.jsonl`，可审计「为什么冲突 / 为什么放行」。
写入侧：`mdcg_remember(consistency=true)` 默认校验，`on_conflict=reject|defer|record`。
诚实边界：**条件级（结构化）冲突检测，非语义蕴含证明**；无法建立比对路径时返回
BLINDSPOT，不假装确定。

### 3.4 典型调用序列

```text
会话开始   → mdcg_recall(query=用户请求, budget_tokens=1200)
情景写入   → mdcg_remember(content, gated=true)       # 三问→四态筛选
重要判断   → mdcg_search(query, context=当前情境)     # 拿 state（四态）
踩坑/修好  → mdcg_mine_fix_pairs(events)              # 自动沉淀负记忆 + 修复知识
新知识候选 → mdcg_propose(...) → 人工/agent 审核 → mdcg_review_decide
需要清理   → mdcg_forget(id, reason) → 审计可查
保护审计   → mdcg_protect(action=stats|check) / mdcg_forgetting_history
```

---

## 四、验证命令

```bash
cd <dsh-memory 仓库根目录>
set PYTHONPATH=.
python -m md_cg.test_p0        # 25/25  引擎基线回归
python -m md_cg.test_p1        # 37/37  白箱架构回归
python -m md_cg.test_p2        # 36/36  七项 OS 能力
python -m md_cg.test_p2_mcp    # 63/63  MCP 协议端到端
python -m md_cg.test_p3        # 33/33  权限 + 设备驱动
python -m md_cg.test_p4_fuzzy  # 44/44  模糊检索
python -m md_cg.test_p5_semantic       # 36/36  语义路
python -m md_cg.test_p6_consolidate    # 72/72  固化
python -m md_cg.test_p7_goals_recent   # 36/36  目标 / 近期
python -m md_cg.test_p8_subgraph_chain # 34/34  子图 / 关系链
python -m md_cg.test_p9_forget_protect # 37/37  主动遗忘 / 写保护
python -m md_cg.test_p10_identity      # 24/24  身份特征识别
python -m md_cg.test_p11_consistency   # 27/27  节点间冲突检测（三级决策）
```

---

## 五、与竞品对照（本次补齐后）

| 维度 | deja-vu | dsh-noema | **灵枢 md_cg（本次后）** |
|---|---|---|---|
| 负记忆 | Fix pairs 自动挖掘 | rejected 候选 | **Fix pairs 自动挖掘 + rejected/unresolved** |
| 召回融合 | BM25 + 双 tier | BM25+PageIndex+图 **RRF** | **四路 RRF + 条件路由 T0–T3** |
| role 分层 | ✅ 工具输出/命令/编辑不参与 | — | **✅ 同** |
| 审核 | — | inbox→decisions（含 edit/merge）| **✅ 含 edit/merge** |
| 隐私 | 索引时 redact | 敏感度+墓碑+payload-free | **✅ tombstone + 恢复检查 + payload-free** |
| 预算控制 | budgeted digest | budget-driven pack | **✅ 跳过超大** |
| 系统调用面 | 单二进制 | MCP stdio | **✅ MCP stdio（默认 2 个认知基元 cg/stg）** |
| 独有 | — | — | **条件路由 + 资格四态 + CCG 五要素 + 信息差 D/d²D + 飞轮 + 三级冲突检测（情绪/反思/递归反思）** |

---

## 六、#2 进程/权限（公开知识 / 私有记忆隔离）

> **动机**：灵枢是开源仓库，而记忆很大一部分是私有内容。权限模型必须让
> 「公开知识」与「私有记忆」在**物理**与**逻辑**两层隔离。

`md_cg/security.py` + `MdCGSecure`（mdcos.py）：

| 机制 | 说明 |
|---|---|
| **Principal** | `tenant / actor / clearance / can_write / can_admin / session` |
| **密级链** | `public < internal < private < secret` |
| **读隔离** | `search / recall / get / search_rrf` 一致过滤：clearance 之上的节点**不可见即不存在** |
| **写隔离** | 写入敏感度 > clearance → `AccessDenied`；`secret` 对 clearance<secret **写入即拒** |
| **管理隔离** | `forget / restore / review_decide` 需 `can_admin` |
| **租户注册表** | `~/.mdcg/_tenants.json`：tenant → `{root, clearance_cap}`；**公开根在仓库内，私有根在仓库外** |
| **夹紧** | `principal_for(tenant)` 把调用方 clearance 夹到租户上限（不能越租户） |
| **审计** | 每条审计带 `tenant / session / clearance`（可追溯到哪个会话做了什么） |

**私有内容加密（`md_cg/crypto.py` + `MdCGSecure`）**：

| 机制 | 说明 |
|---|---|
| **加密范围** | 仅 `private` / `secret` 节点正文加密；`public` / `internal` 保持明文（可正常全文检索） |
| **算法** | ChaCha20-Poly1305（RFC 8439）纯标准库实现，延续「核心零外部依赖」约束 |
| **密钥层级** | KEK（`MDCG_MASTER_KEY` → `~/.mdcg/master.key`，缺失自动生成、0600、**在仓库外**）→ 包裹 → DEK（每 `tenant\|actor` 一把，存 `_keys.json`） |
| **身份一致性** | 节点 AAD = `mdcg-node\|v\|tenant\|actor\|node_id`：换身份 / 跨节点挪用 / 换 KEK 一律解密失败 |
| **密钥即访问权** | fail-closed：无密钥不降级明文——读按「不可见」处理，写 `private`/`secret` 直接拒绝 |
| **统一写盘口** | 所有节点写入经 `_write_node`（先封装再原子写），杜绝 `get()` 解密后的明文被回写降级 |
| **密文不检索** | 密文不参与全文索引，无密钥者只能走元数据；固化时密文节点跳过（不二次加密） |
| **审计** | `_crypto.jsonl` 只记事件与指纹（`kek_fp` / `id_fp`），不含载荷 |

MCP 侧通过环境变量配置：
```yaml
env:
  MDCG_ROOT: "D:/.../public-root"      # 公开租户
  MDCG_TENANT: "public"
  MDCG_CLEARANCE: "public"             # public < internal < private < secret
  MDCG_CAN_WRITE: "1"
  MDCG_CAN_ADMIN: "0"                  # 管理操作默认关闭
```

---

## 七、#3 设备驱动（会话流 → 记忆）

`md_cg/sources.py`：

| 组件 | 说明 |
|---|---|
| **Source** | 统一事件流 `{t, seq, role, text, session, cwd}` |
| **JsonlSource** | 通用 JSONL（字段映射可配）|
| **DSHSessionSource** | 读 `~/.dsh/sessions/**/session.jsonl[.zstd]`；映射 `user/message→user`、`assistant/message→assistant`（reasoning 默认丢弃）、`tool/call→command`、`tool/result→tool-output`；zstd 为**可选**依赖，缺失优雅降级 |
| **Ingestor** | 增量摄取：**watermark**（`_sources.json`）+ `(session,seq)` 去重 + 幂等 + **自动 fix-pair 挖掘** |
| **默认策略** | 会话落 `contextual` 层，**sensitivity=private**（不进公开根）|

实测：真实 DSH 会话 **3/3 可解析**；增量摄取幂等；权限不足时 `denied` 计数 + `hint` 报告（不静默）。

MCP 工具：`mdcg_ingest`（`source=auto` 自动发现本机 DSH 会话）、`mdcg_watermarks`、`mdcg_whoami`。

---

## 八、验收总表

| 套件 | 覆盖 | 结果 |
|---|---|---|
| `test_p0` | 引擎基线（分桶/回退阶梯/只读契约/并发） | **25/25** |
| `test_p1` | 白箱架构 9 维 | **37/37** |
| `test_p2` | 七项 OS 能力 | **36/36** |
| `test_p2_mcp` | MCP 协议端到端（含权限/摄取/冲突拦截） | **63/63** |
| `test_p3` | #2 权限 + #3 设备驱动 | **33/33** |
| `test_p4_fuzzy` | 模糊检索 | **44/44** |
| `test_p5_semantic` | 语义路 | **36/36** |
| `test_p6_consolidate` | 固化 | **72/72** |
| `test_p7_goals_recent` | 目标 / 近期记忆 | **36/36** |
| `test_p8_subgraph_chain` | 子图 / 关系链 | **34/34** |
| `test_p9_forget_protect` | 主动遗忘 / 写保护 | **37/37** |
| `test_p10_identity` | 身份特征识别 | **24/24** |
| `test_p11_consistency` | **节点间冲突检测（三级决策）** | **27/27** |
| `test_p12_metacognition` | 元认知 / 反思回路 | **32/32** |
| `test_p13_encryption` | 私有内容加密 / 身份一致性 | **42/42** |
| `test_p14_sustain` | **持续性自维持（心跳 / 自愈 / 会话续接）** | **44/44** |

---

## 九、下一步（OS 化剩余项）

1. **单一权威存储**：AEIS 私有记忆迁移 —— **暂缓**（开源仓库不能承载私有内容；
   须等私有租户根（仓库外）就绪后再做）。
2. ~~**常驻服务**：会话/心跳/自愈~~ —— **已完成（P14 `sustain.py`）**：
   心跳戳 + 分级判定（任务中阈值放宽）→ 只读诊断 → 自愈（索引/临时文件/日志边界，
   **永不删节点**）→ 会话水位续接 → `SustainLoop` 常驻线程 + `cg(op=sustain)`。
   MCP 进程启动即自维持（`MDCG_SUSTAIN=0` 可关）。
3. **更多驱动**：视觉/语音产出接入（`sources.py` 已是可插拔，加 Source 即可）。

