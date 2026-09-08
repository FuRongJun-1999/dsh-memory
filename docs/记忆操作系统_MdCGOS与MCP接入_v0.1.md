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
PYTHONPATH="D:/Program Files/2_ai/dsh-memory/llm-adapter-poc" \
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
      PYTHONPATH: "D:/Program Files/2_ai/dsh-memory/llm-adapter-poc"
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
cd "D:/Program Files/2_ai/dsh-memory/llm-adapter-poc"
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

## 六、下一步（OS 化剩余项）

1. **单一权威存储**：AEIS 现有记忆（`aeis_memory.db`）迁移到 md_cg（全量字段等价校验）。
2. **进程/权限**：常驻服务 + 会话/租户 + 访问控制（noema 的 tenant.lock / sensitivity cap）。
3. **设备驱动**：接入 DSH 会话流 / 视觉语音产出（自动 `mine_fix_pairs` 需要事件源）。
