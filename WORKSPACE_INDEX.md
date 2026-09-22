<!-- 本文件由 scripts/workspace_index.py 生成；请勿手改，改后跑 `python scripts/workspace_index.py --write` 重生成 -->

# 工作区索引（WORKSPACE_INDEX）

> **为什么有这一页**：查工作区文件前先读本页——按目录职责与关键入口定位，替代每次重复全盘浏览（**工作纪律第 18 条**）。
> **数据源**：git 追踪面（`git ls-files`，NUL 分隔取原始路径）；gitignored 的语料 / 实验产物 / 构建产物不在其内。
> **生成 / 守卫**：`python scripts/workspace_index.py --write` ｜ `--check`（CI：`.github/workflows/workspace-index-check.yml`）。
> **快照**：HEAD `4e2a9fc` · 追踪 **1822** 件 · 生成于 2026-09-22 —— 计数与 HEAD 为生成时快照，**不参与守卫校验**；守卫校验的是：①顶层目录集合 ②根级文件集合 ③职责文案与关键入口 ④正文（归一化后）逐字一致。

## 一、顶层目录

| 目录 | 职责 | 追踪件数 | 关键入口 |
|---|---|---|---|
| `md_cg/` | 灵枢大脑——记忆系统本体（纯 md 认知图 + 确定性裁决），即标准 stdio MCP server | 717 | `mcp_server.py` · `mdcg.py` · `mdcos.py` |
| `rust/` | Rust 检索引擎——只读侧检索内核（零第三方依赖，库内嵌 / --serve / 评测器三形态） | 12 | `README.md` · `Cargo.toml` · `src/lib.rs` |
| `swarm/` | 蜂群运行时——.pbc 确定性实例 + Gossip 拓扑 / 水位信箱 / WAL-HMAC / 信任聚合 | 29 | `swarm_cli.py` · `rust_swarm.py` |
| `compiler/` | 中文（术数）编译器——词法→语法→名实校验→白名单代码生成→验证终裁 + 结构性沙箱 | 22 | `api.py` · `SEMANTICS.md` |
| `hive/` | 蜂巢并发引擎——worker 池调度（原子领取/心跳/超时强杀/崩溃恢复），文件协议即接口 | 118 | `README.md` · `exec_cmd.py` · `exec.py` |
| `skills/` | 灵枢自我认知技能包（管线生成的条件单元投影，随插件分发） | 704 | `README.md` · `plugin.json` |
| `src/` | DSH 插件 TypeScript 源码（构建产物落 lib/） | 12 | `index.ts` · `tools.ts` · `bridge.ts` |
| `dsh/` | DSH profile 配置样例与插件启停脚本 | 9 | `cordis.yml.example` · `dsh-web-start.bat` |
| `codebuddy/` | CodeBuddy 端纪律注入件（full 变体）与 MCP 配置样例 | 3 | `CODEBUDDY.md` · `mcp.json` |
| `zcode/` | ZCode 端纪律注入件（full 变体） | 2 | `AGENTS.md` |
| `codex/` | Codex CLI 端纪律注入件 + 插件形态（lingshu-memory/） | 7 | `AGENTS.md` · `lingshu-memory` |
| `claude/` | Claude Code 端纪律注入件 + 插件形态（lingshu-memory/） | 7 | `CLAUDE.md` · `lingshu-memory` |
| `scripts/` | 工程管线——纪律渲染/守卫、认知图同步、发布件与常驻进程体检 | 29 | `render_discipline.py` · `verify_discipline.py` · `cogmap_sync.py` |
| `test/` | 跨包测试与独立评测脚本（宿主侧 TS 测试 + python 集成） | 23 | `mock_mcp.py` · `hive_exec_test.py` |
| `data/` | 公开评测数据与裁决留痕 | 18 | `memory-bench-1000.jsonl` · `policy.json` |
| `docs/` | 文档（按工程域分目录，索引见 docs/README.md） | 90 | `README.md` · `工作纪律_认知图条目_v1.1.json` |
| `.github/` | CI 门禁（纪律/认知图/蜂巢/conformance/安装/发布件/python 测试） | 8 | `workflows` |
| `.claude-plugin/` | Claude 插件市场清单（/plugin marketplace add 入口） | 1 | `marketplace.json` |
| `.agents/` | Codex 插件市场清单（codex plugin marketplace add 入口） | 1 | `plugins` |

## 二、根级文件

| 文件 | 内容 |
|---|---|
| `README.md` | 对外主入口（定位 / 核心亮点 / 平台全景 / 接入 / 评测 / 纪律） |
| `LICENSE` | 许可 |
| `package.json` | npm 包清单（@furongjun1999/dsh-memory，bin 入口与脚本） |
| `package-lock.json` | npm 锁文件（npm ci 可复现） |
| `tsconfig.json` | TypeScript 编译配置（src/ → lib/） |
| `memory_score.md` | AGI 七维评分说明 |
| `discussion-post.md` | 对外讨论帖留档 |
| `.gitignore` | 忽略面（本地数据面 / 实验产物 / 构建产物） |
| `.gitattributes` | 换行归一（pre-commit 钩子等须 LF 的文件） |

## 三、定位提示

- **找纪律本体** → `docs/工作纪律_认知图条目_v1.1.json`——唯一手写真源；各端产物由 `scripts/render_discipline.py` 渲染、`scripts/verify_discipline.py` 守漂移
- **找记忆能力实现** → `md_cg/mcp_server.py`（cg / stg 工具面）→ `md_cg/mdcg.py`（引擎）→ `md_cg/mdcos.py`（检索）
- **找公开评测口径** → `README.md`（对外数字）→ `data/`（数据集）→ `md_cg/bench_*.py`（复现脚本）
- **找蜂巢派发契约** → `hive/exec_cmd.py`（确定性命令）/ `hive/exec.py`（LLM 委托），spec 进 result 出
- **找本次改动该动哪** → `docs/README.md`（文档归域规则）· 本页第一节（目录职责）

---

本页由 `scripts/workspace_index.py` 从 git 追踪面机械生成，不在上表计数内。新增顶层目录或根级文件时，守卫会亮红并点名未登记项——登记到脚本的真源后重生成即恢复一致（**手工编辑本页会在下一次守卫时被判陈化**）。
