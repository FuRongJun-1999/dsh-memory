# 多 harness 接入（五端差异）

> 本页由原 `README.md` 拆分而来（源：原 README「多 harness 接入」一节（L522–L561））。


## 主推路径与五端对照

### 多 harness 接入（按端分目录）

> **主推路径：MCP 直挂**——各端接入的**共性是挂载同一个 stdio MCP server**（`python -m md_cg.mcp_server`）：任何支持 MCP 的宿主直接挂上即可，**不依赖任何插件系统**。

共享层（`md_cg/` 大脑 · `data/` · `docs/` · `scripts/`）在仓库根；**harness 专属配置按端归置**，下表列的只是各端**纪律注入方式**的差异（纪律如何进入上下文），大脑与记忆真源零改动：

> ⚠ **出货面与源码树的分界**：npm 包的 `files` 只含 `lib/ src/ md_cg/ skills/ README.md dsh/ codebuddy/ zcode/ docs/`
> —— `scripts/`、`hive/`、`swarm/`、`compiler/`、`rust/` 属**源码树**（发布门禁、蜂巢运行时、Rust 评测器），
> 装出来的插件里**不存在**。因此运行期依赖一律不得指向它们：
> 判据面清单走包内 `md_cg/judgment_manifest.py`（`md_cg/interop.py` 进程内调用）、
> 裁决 CLI 走包内 `python -m md_cg.review_cli`、全量测试走包内 `python -m md_cg.run_tests`；
> 依赖 `scripts/`/`hive/` 的**测试**在缺件时按实跑形态处置（不虚报通过）：**安装态**（`scripts/`/`hive/`/`swarm/`/`compiler/` 不存在）下套件按存在性发现、自然没有这些组的目标；**源码树**里需要 Rust 编译产物的套件（如 `md_cg.test_rank_parity_score_mode`）未构建时 **fail-closed FAIL**（打印 `cd rust && cargo build --release` 重编指引）；如实 SKIP 只用于三类——依赖 hive 二进制未构建的守卫成功趟（`scripts/test_utf8_boot_guard.py` 等，逐条理由、不计入通过数）、依赖 gitignored 本地数据缺件（p44 等）、平台不符（非 Windows 上的 Windows 专用件）。

## 五端纪律同源

> 五端纪律**同源**（`docs/工作纪律_认知图条目_v1.1.json`），由 `scripts/render_discipline.py` 渲染、
> `scripts/verify_discipline.py` 守卫漂移；矩阵见 `docs/discipline/harnesses.yaml`。

## 可选补充：插件形态安装

<details>
<summary><b>可选补充：插件形态安装（仅 Claude Code / Codex CLI · 省手工复制，非主推路径）</b></summary>

> 等价于按上表手工配置，只是把纪律 skill 与配置样例随插件一起拿到；**不装插件不影响任何能力**。

| 宿主 | 安装 | 插件位置 | 装后一步 |
|---|---|---|---|
| Claude Code | `/plugin marketplace add FuRongJun-1999/dsh-memory` → `/plugin install lingshu-memory@lingshu` | `claude/lingshu-memory/`（纪律以 skill 分发，`/lingshu-memory:linglu-discipline` 可显式调用） | 复制插件内 `mcp.json.example` 为项目根 `.mcp.json`，填 `PYTHONPATH` |
| Codex CLI | `codex plugin marketplace add <本仓路径>` → `codex plugin add lingshu-memory@lingshu` | `codex/lingshu-memory/`（skill 三级渐进加载；`.codex-plugin/plugin.json` 清单） | 把插件内 `config.toml.example` 两段合并进 `~/.codex/config.toml`，填 `PYTHONPATH` |

> marketplace 清单：Claude 端在仓根 `.claude-plugin/marketplace.json`，Codex 端在仓根
> `.agents/plugins/marketplace.json`。插件不含大脑本体（`md_cg/` 不随插件分发）——MCP 装好后
> 大脑仍是你本机的 dsh-memory 仓库；插件形态的纪律 skill 同样由真源渲染（`skill` 变体，
> 矩阵槽位 `claude-code-plugin-skill` / `codex-plugin-skill`），漂移由同一 `verify_discipline.py` 守卫。

</details>
