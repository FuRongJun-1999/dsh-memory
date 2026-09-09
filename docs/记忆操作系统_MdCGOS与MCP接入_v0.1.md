# md_cg · 记忆操作系统（Memory OS）· 实现与接入

> 在 MdCG（P0/P1 已验证引擎）之上补齐「记忆操作系统」能力，并暴露为 MCP 服务。
> 2026-09-08 · 全部经 dsh 端独立实跑验证

---

## 一、本次交付

| 文件 | 职责 |
|---|---|
| `md_cg/mdcos.py` | **MdCGOS**：在 MdCG 上新增 7 项记忆 OS 能力 |
| `md_cg/mcp_server.py` | **MCP server**（stdio + JSON-RPC 2.0，协议 2024-11-05，17 工具，零依赖）|
| `md_cg/test_p2.py` | P2 验收（7 项能力）**31/31** |
| `md_cg/test_p2_mcp.py` | MCP 协议验收 **23/23** |

回归：**P0 25/25 · P1 37/37 仍全绿**（未修改 MdCG 既有语义）。

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
MDCG_ROOT="D:/Program Files/2_ai/AEIS/data/mdcg" \
MDCG_ACTOR="dsh" \
PYTHONPATH="D:/Program Files/2_ai/dsh-memory" \
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
      MDCG_ROOT: "D:/Program Files/2_ai/AEIS/data/mdcg"
      MDCG_ACTOR: "dsh"
      PYTHONPATH: "D:/Program Files/2_ai/dsh-memory"
```

### 3.3 工具面（17）

```
写：mdcg_remember · mdcg_rejected · mdcg_unresolved · mdcg_propose
读：mdcg_get · mdcg_search · mdcg_recall · mdcg_review_list
认知：mdcg_reflect · mdcg_verify · mdcg_flywheel · mdcg_mine_fix_pairs
生命周期：mdcg_forget · mdcg_restore · mdcg_review_decide
运维：mdcg_health · mdcg_service_info
```

### 3.4 典型调用序列

```text
会话开始   → mdcg_recall(query=用户请求, budget_tokens=1200)
重要判断   → mdcg_search(query, context=当前情境)     # 拿 state（四态）
踩坑/修好  → mdcg_mine_fix_pairs(events)              # 自动沉淀负记忆 + 修复知识
新知识候选 → mdcg_propose(...) → 人工/agent 审核 → mdcg_review_decide
需要清理   → mdcg_forget(id, reason) → 审计可查
```

---

## 四、验证命令

```bash
cd "D:/Program Files/2_ai/dsh-memory"
set PYTHONPATH=.
python -m md_cg.test_p2        # 31/31  七项能力
python -m md_cg.test_p2_mcp    # 23/23  MCP 协议
python -m md_cg.test_p0        # 25/25  回归
python -m md_cg.test_p1        # 37/37  回归
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
| 系统调用面 | 单二进制 | MCP stdio | **✅ MCP stdio（17 工具）** |
| 独有 | — | — | **条件路由 + 资格四态 + CCG 五要素 + 信息差 D/d²D + 飞轮** |

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
| `test_p2` | 七项 OS 能力 | **31/31** |
| `test_p3` | #2 权限 + #3 设备驱动 | **33/33** |
| `test_p2_mcp` | MCP 协议端到端（含权限/摄取） | **29/29** |

---

## 九、下一步（OS 化剩余项）

1. **单一权威存储**：AEIS 私有记忆迁移 —— **暂缓**（开源仓库不能承载私有内容；
   须等私有租户根（仓库外）就绪后再做）。
2. **常驻服务**：会话/心跳/自愈（当前 MCP 进程已常驻，缺心跳与重启策略）。
3. **更多驱动**：视觉/语音产出接入（`sources.py` 已是可插拔，加 Source 即可）。

