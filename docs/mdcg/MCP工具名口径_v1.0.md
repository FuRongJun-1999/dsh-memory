# MCP 工具名口径 v1.0（唯一口径表）

> 目的：消除「同一工具在不同端叫不同名字」导致的**初次识别错误**。任何端、任何文档、任何注入段引用工具名时，以本表为准。
> 登记日：2026-10-19 ｜ 依据：`md_cg/mcp_server.py`（TOOLS 定义）与各端配置文件实读。

## 一、标准名（唯一）

| 层 | 标准名 | 出处（真源） |
|---|---|---|
| **MCP 服务名** | **`mdcg`** | `codebuddy/mcp.json` 的 server key 已是 `mdcg`；`md_cg/mcp_server.py` 即该服务本体 |
| 主工具（认知图） | **`cg`** | `md_cg/mcp_server.py` 的 TOOLS 定义 |
| 主工具（语义时空图） | **`stg`** | 同上 |
| 细粒度工具 | **`mdcg_*`**（`mdcg_remember` / `mdcg_recall` / `mdcg_search` / `mdcg_get` / `mdcg_reflect` / `mdcg_verify` / `mdcg_propose` / `mdcg_rejected` / `mdcg_unresolved` …） | 同上（实读命中） |

## 二、宿主前缀映射（不是别名，是宿主加的展示前缀）

| 宿主 | 展示名 | 与标准名的关系 |
|---|---|---|
| DSH | `lingshu_cg` / `lingshu_stg` / `lingshu_mdcg_*` | 宿主按插件名加前缀：**展示名 = `lingshu_` + 标准名** |
| CodeBuddy / ZCode / Codex / Claude | `cg` / `stg` / `mdcg_*` | 直接用标准名 |

**判据**：去掉 `lingshu_` 前缀后必须等于标准名；任何端不得自造第三套名字（如 `mdcg_remember` 写成 `memory_remember`、`cg` 写成 `memory`）。

## 三、现存的偏差点（本轮实读，待逐点修）

| 文件 | 现状 | 应改为 |
|---|---|---|
| `dsh/cordis.yml.example` | 出现 `lingshu_cg` / `lingshu_stg` | 保留（宿主展示名），但**旁注标准名** `cg` / `stg`；或在注释里引用本表 |
| `codex/AGENTS.md` | 同时出现 `lingshu_cg`（2 次）与 `cg`（9 次） | 统一表述：正文用标准名 `cg`/`stg`，仅在「DSH 宿主展示名」处写 `lingshu_` 前缀映射 |
| `src/index.ts` | 残留 `lingshu_remember`（1 处） | 核对是否为历史别名；若是死引用则删，若是兼容映射则补注释指向本表 |

## 四、使用规则

1. **新文档/新注入段**：一律用标准名；需要提宿主展示名时，**必须**同时给出标准名（`lingshu_cg` = 宿主前缀 + `cg`）。
2. **系统提示词/纪律注入**：涉及工具名的地方引用本表，不各写一套。
3. **门禁**：新增工具名时，`md_cg/op_table.py` 与 `md_cg/mcp_server.py` 是唯一真源；文档侧由 `cogmap_sync.py check` 守漂移。

## 五、不适用条件

- 不覆盖宿主**自有**工具（如 DSH 的 `run_code`、`agent_teams_*`、`hive_*`）——那些不属 md_cg 口径面；
- 不改变任何工具的行为或参数，仅统一**命名与引用**；
- 本文不含端内展示形态（大小写、分隔符）之外的协议改动。