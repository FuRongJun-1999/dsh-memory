# ⬢ hive · 灵枢蜂巢（多智能体并发引擎）

> 蜂群多智能体的 **Rust 并发调度面**：大脑出题（spec），蜂巢并发执行（worker 池），
> 文件协议交付（result.json）。纯 std 零第三方依赖（D-005），调度生命周期全在 rust——
> worker 池、心跳、超时强杀、kill 通道、崩溃恢复；HTTPS/LLM 调用委托零依赖 Python
> 执行器子进程（urllib 走系统证书）。

## 状态：逐步稳定中（欢迎反馈）

蜂巢是灵枢五件套里**最新的一层**。调度生命周期已闭环——worker 池、`claimed.lock` 原子领取、
心跳、超时强杀、kill 通道、崩溃恢复（`claimed` 重投 / `running` 诚实标 error）——并有回归验证
（`cargo test` + MCP 冒烟）覆盖。但**并发、超时、崩溃恢复这类路径，只有在真实任务与真实机器上
跑得足够多才会真正稳定**：本层会持续迭代，接口（文件协议 + spec 字段）保持稳定，内部行为按
真实反馈打磨。

因此**特别欢迎下载试用后反馈**——拉起失败、任务卡住、心跳异常、平台差异、kill 不生效、
超时判定偏差等**失败路径**，比「我这边跑通了」有价值得多。请开
[Issue](https://github.com/FuRongJun-1999/dsh-memory/issues) 并附 `hive doctor` 输出
（serve 存活 / 任务状态统计 / env 检查），能显著缩短定位时间。

## 迭代状态：**实测迭代期**（2026-09-22 起）

蜂巢于 2026-09-22 曾转「迭代中的产品」暂停常规派发；同日使用者裁定**进入实测迭代**：
蜂巢不稳定，边实测边修——主代理（编排/裁决）+ 蜂巢 worker（子代理）协作迭代。
**迭代纪律**：每批修改 = 一个 git 提交点，验证（测试/门禁/探针）绿才推进、红即 revert；
每批留反思（偏差归因）与验证结论。工程真源：`D:\2_ai\蜂巢记忆架构设计.md`（M1–M7，
P0 可开工）+ `docs/hive/蜂巢设计_理论对齐_v0.1.md`（理论锚点与裁决）。

**迭代批次记录（2026-09-23）**：批次 4-7 = M6 事件源/暴露口/事件级密级 + mine_fix_pairs
系统纪律化 + rerun_on_recover 逃生门 + 工具层回读拦截 + M6 真实库实跑（98 事件落盘）；
批次 8a = **经验回路全链首次真实升层**（fix_25734ee75277，阶段 1 首证达成）+ 两摄取缺陷
修复；批次 8b = **判据面重定义**（三承重测试迁 `hive/tests/judgment_surface.rs`，
判据面/候选面物理分离成立 + `scripts/judgment_manifest.py` 清单 hash 工具——互验
本体 A3 的前置缺口收口）；批次 9 = **flush×compact/rebuild 临界区互斥**（9·12 多写者
病灶防治，能红双态实证）；批次 10-11 = **互验本体切片①②**（§7.1-7.3 身份心跳/
A1A2A3/verdict 脱敏门禁 + §7.4 派发/执行/入库原语，`hive/verify_runner.py`）；
批次 12 = **CCG 六要素注释补齐**（rust 侧非测试 fn 66/66 接口层全覆盖 + orch/
verify_runner 差额——注释真源=批次 4-11 认知图机制记忆，递归自我改进实测：知识→
代码文档化路径）。

**三条流程纪律（可核断言，2026-09-23 从 issue #24 复盘蒸馏）**：

1. **先查后写**：任何单元施工前，工作记录必须列出「已查文档清单」——该单元的
   理论条款（智能论 3.x 带行号）+ 单元设计文档 + 仓内既有实测记录。无清单不开工。
   *教训*：`consolidate.py` 用 `max_tokens=1200` 硬编码时，仓内已有实测记录
   （`bench_lme_zh.py:113`，2026-09-11：「deepseek-flash 与 deepseek-v4-pro 都是
   推理模型」）未被查找接入——知识在仓内，开发流程没强制接。
2. **独立复审**：交付前必须有一次独立于作者的复审（另一实例或专门 review pass），
   提交信息记录复审要点。*教训*：issue #24 三连缺陷（硬编码默认值 / 无 CLI+env
   口子 / 不检查 `finish_reason=="length"`）全是复审面一眼可抓项，却由外部
   使用者首发——发布链路只有测试没有复审。
3. **误差归因闭环**：同一错误信号（DEFER / parse_failed / rejected…）**累计 ≥2 次
   即触发理论归因**（回智能论/设计文档找条件层误差，写归因记录），不允许停留为
   reasons 统计噪音。*教训*：`parse_failed` 在认知图固化轮次早已多次出现，
   无人归因，直到外部 issue #24 才钉死根因——观测面有数据，闭环缺一环。

### 迭代项 1（已修）：执行任务时弹终端

- **现象**：每经蜂巢跑一个任务就弹出一个终端窗口，打断使用者正在做的事。
- **根因**：`serve` 由 `serve_start.py` 以 `DETACHED_PROCESS` 拉起（**自身无控制台**），
  而它 spawn 的 `python.exe` / `tasklist.exe` 都是 console 子系统程序；Windows 在
  「父进程无控制台 **且** 子进程未声明 `CREATE_NO_WINDOW` / `DETACHED_PROCESS`」时
  会为子进程**新建一个可见的控制台窗口**。全仓仅两处裸 spawn
  （`src/exec.rs::spawn_executor`、`src/main.rs::tasklist_row`），两处都缺该 flag。
- **修复**：`src/exec.rs` 新增 `hide_window(&mut Command)`（Windows 设
  `CREATE_NO_WINDOW = 0x0800_0000`，其余平台 no-op），两处 spawn 统一走它。
- **验证**：`cargo test` 22/22（lib 17 + main 5）零回归；端到端探针跑在真实执行器链内，
  报告 `HWND=0 VISIBLE=False`（探针：`test_console_window.py`，含复验命令）。
- **诚实边界**：未做「修复前主动复现」（避免再次弹窗打扰使用者）；根因依据 = 使用者现场报告
  + 源码取证（全仓仅此两处 spawn，均缺 flag）+ Windows 文档语义。

## 架构

```text
调用方（agent / MCP 宿主）
   │  hive_spawn / hive submit（spec.json）
   ▼
hive serve（rust 纯 std，常驻）
   │  主循环扫描 jobs/ → claimed.lock 原子领取 → mpsc worker 池并发
   │  1s 轮询：退出 / kill 标志 / 超时 → child.kill()
   ▼
执行器（可替换子进程，serve 级配置 HIVE_EXEC_PY）
   │  确定性任务 → exec_cmd.py：跑 command（零 LLM / 不涉网络）
   │  LLM 任务   → exec.py：调 OpenAI 兼容 chat/completions（GLM 同形）
   │  编排任务   → orch.py：spec.orchestrate 真值 → 拆子任务 / 卡片收口（见「任务编排」）
   │  统一契约：读 spec.json → 写 result.json
   ▼
result.json（error 字段区分成败，幂等终态）
```

分工原则：**rust 管并发与生命周期，python 管协议与 LLM**。TLS 无第三方库在纯 std
rust 不可行，故 HTTPS 放执行器；执行器是可替换子进程——换 curl / 其它 SDK 宿主时，
保持「读 spec.json、写 result.json」契约即可。

## 快速开始

```bash
# 构建（零第三方依赖，无 cargo install 之外的任何安装）
cd hive && cargo build --release

# ⚠ cargo 不在 PATH 时（Windows 常见：rustup 装完未重启终端 / 未加 PATH）用绝对路径：
#   "%USERPROFILE%\.cargo\bin\cargo.exe" build --release --manifest-path hive/Cargo.toml
#   CreateProcess 不自动补 .exe 后缀，故须写全 cargo.exe（只写 cargo 会 WinError 2）。
#   本机实证：shutil.which('cargo') 为 None，但 ~/.cargo/bin 工具链完整（cargo/rustc/rustup 齐备）。

# 配置密钥（执行器用）
set HIVE_API_KEY=你的密钥

# 起 serve——**唯一推荐正路**：serve_start.py 读本地配置注入 env（key 不落命令行历史）
# 配置文件：hive/config.local.json（已 gitignore；值支持 直值 | {"env":"系统变量名"} | {"file":"key文件路径"}）
#   首次使用请复制入库模板 hive/config.local.example.json 改名后改值（模板本身不入 gitignore，随仓分发）
# 推荐形态：HIVE_API_KEY 引系统变量（如 DEEPSEEK_API_KEY），HIVE_WEB_SEARCH_KEY 引 key 文件
python serve_start.py            # 拉起（已在跑则拒绝）；--stop 停止；--restart 重启；--rebuild 重编译并重启；--status 查看心跳与任务统计
# ⚠ 重启/重编译（含 --restart/--rebuild）必须由 **serve 进程树外**执行：主代理 CLI 直跑，
#   或 MCP `hive_restart` 工具（MCP 进程是宿主拉起的，独立于 serve 树，重启 serve 不会自杀）。
#   经蜂巢任务派发跑 restart 仍会自毁：worker 属 serve 进程树，stop 杀 serve 即杀自己
#   → 任务中断、新 serve 未必起、无 result 留痕。（本机实证 2026-09-22：pid 8596→24288）
# ⚠ rust 改动后用 --rebuild（stop→cargo build→start 原子序）：serve 在跑时 hive.exe 被
#   Windows 锁定，直接 build 报 os error 5——--restart 中间插不进 build，会「重启了旧二进制」。
#   --rebuild 在 build 失败时保持停止态（fail-closed：宁可停着，不让旧二进制假活）。
#   cargo 定位顺序：HIVE_CARGO env > ~/.cargo/bin > PATH（PATH 常缺 cargo）。

# 手动起 serve（**不读 config.local.json**，env 需自行带全；同一 jobs 目录至多一个 serve）
# ⚠ 直起 hive.exe serve 而未显式设 HIVE_EXEC_PY 时，执行器回退 exec.py（llm_only）——
#   spec 的 command / commands / orchestrate 会失败（确定性执行需 exec_cmd.py）。
#   确需手动起：先 set HIVE_EXEC_PY=<仓>/hive/exec_cmd.py，或直接用上一行的 serve_start.py。
target\release\hive.exe serve   # 已有 serve 在跑会被拒绝；--force 可强起（迁机 / 心跳残留时用）

# 提交任务（stdin JSON）——模型名须与 HIVE_API_BASE 配对（见 spec 字段表）
echo {"model":"deepseek-flash","user_prompt":"总结这份文档","context_files":["README.md"]} | target\release\hive.exe submit -

# 查状态 / 强杀 / 体检
target\release\hive.exe poll
target\release\hive.exe kill <job_id>
target\release\hive.exe doctor
```

### MCP 接入（推荐宿主直连）

`hive/hive_mcp/mcp_server.py` 提供五工具（手写 stdio JSON-RPC，形态对齐
`md_cg/mcp_server.py`）：

| 工具 | 用途 |
|---|---|
| `hive_spawn` | 提交 LLM 任务（**入参白名单** + spec 结构校验 fail fast），返回 job_id；确定性/编排任务走 CLI（见「确定性执行」「任务编排」） |
| `hive_poll` | 无 id = 全部摘要（content 截 800 字）；带 id = 单查全文；`handoff_ready=true` = 子代理满上下文交回，待主代理裁决续跑 |
| `hive_kill` | 写 kill 标志，worker ≤1s 内强杀 |
| `hive_restart` | 重启 serve（stop→start 原子序，复用 `serve_start.restart`）：改 serve 级配置或 rust 重新 build 后使改动生效；stop 失败绝不 start（防双实例）。重启中断 claimed/running 任务，重启后由 recover_orphans 收尸 |
| `hive_doctor` | serve 存活 / 任务状态统计 / env 检查 |

首次 spawn 自动以 detached 方式拉起 serve（Windows
`DETACHED_PROCESS|CREATE_NO_WINDOW`）。**执行器是 serve 级配置**：
`HIVE_EXEC_PY` / `HIVE_JOBS_DIR` 在 serve 启动时读取，改动后须重启 serve 才生效。

**统一子代理默认**（缺省即注入 spec，调用方显式传值优先）：`reasoning_effort=high`、
`context_budget_tokens=200000`、`timeout_s=600`（10 分钟）；spawn 返回体 `spec_defaults`
回显实际生效值便于核对。

**serve env 的真实来源 = `config.local.json`**（**仅当经 `serve_start.py` 拉起时**）。serve 的
env 在启动时固化，子进程无法反查——故 `hive_doctor` 从**serve 自报的心跳**读执行器资格
（`exec_py` / `exec_mode` / `exec_source`，**权威**），另有 `serve_env_source`（config 期望值）
与 `mcp_process_env`（仅诊断，用它判必得错位结论）两组参考值。

**两条拉起路径的 env 口径并不相同**（此为实测缺陷，勿混同）：

- `python hive/serve_start.py` / MCP 首次 spawn → 读 `config.local.json` 注入 ⇒ 与配置一致；
- 裸 `hive.exe serve` → **不读任何配置**，只认进程 env ⇒ `HIVE_EXEC_PY` 等常缺失，
  执行器回退 `exec.py`（llm_only），确定性执行不可用（serve 启动时 stderr 会告警；
  `HIVE_API_KEY` 同样拿不到，LLM 任务报「HIVE_API_KEY 未设置」）。

判定「当前 serve 能不能跑确定性任务」的唯一可靠办法：看 doctor 的 `exec_mode`
（`exec_source=serve_heartbeat` 时即 serve 自报值），或直接提交一个带 `command` 的探针任务。

### 各 harness 注册（通用接入）

蜂巢对宿主是**标准 MCP server（stdio）**，各端只需在自己的 MCP 客户端配置里加一条 server
条目——**不需要改 hive 代码**：

```json
{
  "mcpServers": {
    "hive": {
      "command": "python",
      "args": ["-m", "hive.hive_mcp.mcp_server"],
      "env": { "PYTHONPATH": "<本机 dsh-memory 仓库绝对路径>" }
    }
  }
}
```

TOML 形态（Codex CLI）：

```toml
[mcp_servers.hive]
command = "python"
args = ["-m", "hive.hive_mcp.mcp_server"]
startup_timeout_sec = 120

[mcp_servers.hive.env]
PYTHONPATH = "<本机 dsh-memory 仓库绝对路径>"
```

**只需 `PYTHONPATH`**：jobs 目录、`config.local.json`、`hive.exe` 一律由该路径下的 `hive/`
推导（`HIVE_JOBS_DIR` / `HIVE_EXE` / `HIVE_CONFIG` 可覆盖）。`config.local.json` **不入库**
（含密钥），首次使用请复制同目录的入库模板 `config.local.example.json` 改名后改值。
注意：这段 env 只作用于
**MCP 进程自身**（用于定位路径）；**serve 的运行 env 由 `config.local.json` 决定**，
与客户端配置里写了什么无关——两者不是一回事，不要互相推断。

仓内已含该条目的模板（照抄即可）：

| harness | 模板 | 客户端配置落点 |
|---|---|---|
| CodeBuddy / ZCode | [`../codebuddy/mcp.json`](../codebuddy/mcp.json) | CodeBuddy 用户级 `mcp.json`（ZCode 同构，仅 `MDCG_ACTOR` 不同） |
| Claude Code | [`../claude/mcp.json.example`](../claude/mcp.json.example) | 项目级 `.mcp.json`（或 `claude mcp add`） |
| Codex CLI | [`../codex/config.toml.example`](../codex/config.toml.example) | `~/.codex/config.toml` |
| Claude / Codex 插件 | 插件内 `mcp.json.example` / `config.toml.example` | 同上（随插件分发） |
| DSH | —— | **形态不同**：本端是插件内建桥（TS 侧 spawn + 工具注册），非原生 MCP 客户端；当前兜底 = CLI `hive submit` |

**「通用并发」的落地语义**：池与 serve 由 `PYTHONPATH` 推导 ⇒ **多个 harness 指向同一仓库
即共享同一并发池与同一个 serve 进程**（谁派的任务都进同一队列、由同一 worker 池消费）。
要让某端用独立池（高优 / 隔离实验），给它加 `HIVE_JOBS_DIR`（+ 独立 `HIVE_CONFIG`）——
不同 jobs 目录 = 不同 serve 实例，互不干扰。

**两条必读边界**：

1. **`workdir` 取 MCP 进程 cwd**（MCP 面不接受 `workdir` 入参）⇒ 各端启动 MCP 进程的工作
   目录即 `context_files` 相对路径的基准；喂上下文请用**绝对路径**，或确认该端 cwd。
2. **确定性执行与编排不在 MCP 面**（`command` / `commands` / `orchestrate` / `workdir` 四键
   只走 CLI）⇒ 跑测试 / 脚本 / 批量命令请用 `hive.exe submit --spec <spec.json>`（执行器
   `exec_cmd.py`，零 LLM）；MCP 面传入会被 fail fast 拒绝（不静默丢弃）。
   ⚠ **submit 只认 `--spec <file>` 或 stdin 的 `-`**：位置参数会被忽略并转而读**空 stdin**，
   表现为 exitCode 1 且**无任何输出**（易误判成 serve 故障，实为参数形态问题）。
   ⚠ **未传 `workdir` 时，命令的 cwd 是 worker 侧的 job 目录**（`hive/jobs/<job_id>/`），**不是** submit 时的 shell cwd；`workdir` 既作 `context_files` 相对基准，也作命令执行 cwd。⇒ 命令里的脚本/数据一律用**绝对路径**，或显式传 `workdir`。（实测：用相对路径脚本会 `can't open file` → exit=2；命令回显的 `cwd` 字段可直接核对。）

### 任务上下文管理（谁负责哪一段）

蜂巢把「任务上下文」拆成四段，各有明确归属——主代理据此裁决，而不是把上下文一股脑塞进一次调用：

| 段 | 承载 | 说明 |
|---|---|---|
| 注入 | `hive_spawn` 的 `context_files`（+ `system_prompt` / `user_prompt`） | 逐个读入为 `<context path="...">` 块拼在 prompt 前；读取失败写错误块不中断 |
| 预算 | `context_budget_tokens`（MCP 面默认 200000）+ `context_strict` | 达预算**默认交回续跑**（写进展卡 + `need_continue`）；`context_strict=true` 才恢复「超预算即 error」 |
| 交接 | `hive_poll` 的 `handoff_ready` + 进展卡 `progress.jsonl` | `handoff_ready=true` = 子代理满上下文交回；主代理读卡后裁决**续跑**（新 spawn 带卡）或**收口** |
| 观察 | `hive_poll`（无 id = 全部摘要 / 带 id = 单查全文） | 主代理只做编排：派发 → 观察 → 裁决，不把子任务上下文搬进自己的窗口 |

## spec 字段

| 字段 | 必填 | 说明 |
|---|---|---|
| `model` | 是 | 模型名，缺失即拒。**须与 `HIVE_API_BASE` 配对**：deepseek base（`api.deepseek.com`）→ `deepseek-flash` / `deepseek-v4-pro`；智谱 base → `glm-5.3-flash`。错配在 API 侧 400（实测：deepseek base 传 `glm-5.3-flash` → `supported API model names are deepseek-flash, deepseek-v4-pro`） |
| `user_prompt` | 是 | 非空（trim 后），内容保留原样不 trim |
| `system_prompt` | 否 | system 消息 |
| `context_files` | 否 | 文件列表，逐个读入以 `<context path="...">` 块拼在 prompt 前；读取失败写错误块不中断 |
| `workdir` | 否 | context 相对路径基准（默认进程 cwd） |
| `timeout_s` | 否 | 5..=3600，rust 侧默认 300，**MCP 面注入默认 600**（10min）；超时 rust 侧强杀并标 `timeout` |
| `reasoning_effort` | 否 | 思考强度 `low`\|`medium`\|`high`（rust 侧白名单校验）；**MCP 面默认 `high`** |
| `context_budget_tokens` | 否 | 输入 token 预算（执行器保守估算）；达预算默认**交回续跑**（写进展卡 + `need_continue`，见下节）；**MCP 面默认 200000** |
| `context_strict` | 否 | `true` 恢复旧行为（超预算即 `error` 终止，不交回）；缺省 = 交回续跑 |
| `thinking` | 否 | 思考开关透传（如 `{"type":"enabled"}`） |
| `max_tokens` / `temperature` | 否 | 透传 API |
| `tools` | 否 | 工具白名单，子集 `["lingshu_cg","web_search","read_file"]`；非空即启用 agent loop（function calling 循环），缺省 = 单发调用（历史行为逐位不变） |
| `max_tool_rounds` | 否 | 工具轮上限，默认 5；达到后强制终答（不带 tools 再发一次） |
| `mdcg_root` | 否 | lingshu_cg 的认知图根兜底（env `MDCG_ROOT` 优先）；如任务级隔离用临时图 |
| `web_search_backend` | 否 | web_search 后端兜底（env `HIVE_WEB_SEARCH` 优先）：`zhipu` / `duckduckgo` |
| `orchestrate` | 否 | 编排形态：真值（`true` 或 `{"max_subtasks": N}`）→ 由 `orch.py` 接管（见「任务编排」）。多态转发须 `HIVE_EXEC_PY` 指向 `exec_cmd.py`；子任务上限默认 8 |

**面差异（先看清再传参）**：上表是 **spec.json 字段表**（CLI `hive submit` 的全集）。
MCP 面的 `hive_spawn` **只接受其中 15 键**——除 `workdir`（本面强制取 MCP 进程 cwd）与
`orchestrate` 外的全部，`command` / `commands` 亦不在其列。这四个键**只走 CLI**（见下节）；
MCP 面传入会被**显式拒绝**（fail fast 并指路 CLI），不再静默丢弃——静默丢弃的后果是
「以为在跑确定性任务、实际走了 LLM 路径烧 token」。白名单与 `hive_spawn` 的 schema
同集，由 `hive/hive_mcp/smoke_test.py` 断言守卫。

spec 在 submit 时做存在性校验（context 文件必须已存在，fail fast 防任务白跑）。

## 任务生命周期与崩溃恢复

```text
pending → claimed → running → done | error | timeout | killed
```

- **原子领取**：worker 以 `create_new` 写 `claimed.lock`，多 serve / 多 worker 竞争
  只有一个成功，无需外层锁。
- **心跳**：worker 周期性刷新 `status.json` 的 heartbeat；serve 侧 `_serve.json`
  心跳供 doctor 判活——**三层判据缺一不可**：心跳新鲜（`FRESH_MS`）**且** pid 存活
  **且** 该 pid 确实是本程序（同映像名）。第三层是 2026-09-17 补的：pid 号会被无关
  进程复用，只判「号是否存在」会让一个残留 pid 冒充 serve 而误挡启动（且文案会把
  运维引向一个并不存在的 serve）。
- **超时强杀**：超过 `timeout_s` → `child.kill()` → 终态 `timeout`。
- **kill 通道**：`kill` 标志文件，worker 1s 轮询粒度检测后强杀（诚实边界：非即时信号）。
- **崩溃恢复**：serve 重启时 `recover_orphans`——`claimed` 重新投递、`running` 标
  `error`（结果未知，绝不假装 done）。

## 文件协议（接口即目录）

```text
jobs/
  _serve.json                 # serve 心跳（pid/ts/workers/exec_py/exec_mode）
  <job_id>/
    spec.json                 # 任务规格（submit 时写入）
    status.json               # 状态（先写 status 后写 spec = 就绪信号）
    result.json               # 结果（error 字段区分成败；终态判据）
    claimed.lock              # 原子领取锁（create_new）
    kill                      # kill 标志（存在即请求强杀）
    progress.jsonl            # 进展卡（工具轮/终答/交回逐条留痕，见下节）
    claimed/ log.txt          # 运行态
```

任何语言都能按此协议提交与消费——文件协议即接口，不绑定 MCP 或 CLI。

## 执行器契约

`exec.py`（零第三方依赖）：`argv[1] = job 目录`，读 `spec.json` 写 `result.json`：

```json
{"ok": true,  "content": "...", "usage": {...}, "model": "...",
 "tool_trace": [...], "tool_rounds": 2, "duration_s": ...}
{"ok": false, "error": "...", "tool_trace": [...], ...}
```

`tool_trace` 每轮记录 `{round, tool, args, ok, brief, result}`（审计可回放）；
API 错误收敛为 `ok:false` 但已发生的 trace 保留。

### 工具面（agent loop）

`spec.tools` 白名单启用后按 OpenAI function calling 循环：模型回 tool_calls →
执行器执行 → tool 消息回喂 → 循环至终答；轮次耗尽强制终答（`forced_final: true`）。
工具结果回喂前截断（4000 字符）防上下文爆炸；上下文预算逐轮校验，超限诚实终止。

**读写不对称（2026-09-19 裁定）**：**读放开、写严格**——`read_file` 只读、默认全路径
开放（部署可用 `HIVE_READ_ROOTS` 收窄）；执行器的**唯一写路径**是 `lingshu_cg op=write`
（recorder 令牌 + 校验闸门 DEFER/REJECT）。`read_file` 的 schema 内**没有任何写参数**，
结构上不可能落盘改状态。

| 工具 | 说明 |
|---|---|
| `lingshu_cg` | 灵枢认知图（`op=route\|read\|write` 白名单，复用 MCP 面同一 dispatch）。权限硬编码 recorder（`can_admin=false`，spec 无法提权）——写入过校验闸门：DEFER 入审核队列 / REJECT 负记忆是设计行为，裁决权留给设计者。会话隔离 `session=hive_job_<id>`。write 的 `verification_basis` 前置校验合法枚举（防自由文本卡死审核队列）。 |
| `web_search` | 网页搜索。`zhipu` 后端走 `/web_search` 端点（`HIVE_WEB_SEARCH_BASE` 缺省智谱官方，与 `HIVE_API_BASE` 解耦——后者常为 LLM 中转网关、无搜索路由；`HIVE_WEB_SEARCH_KEY` 缺省回落 `HIVE_API_KEY`）；`duckduckgo` 零 key 兜底。 |
| `read_file` | 读本地文件/目录（**只读**：不落盘、不改状态）。目录给清单（子目录优先，超 `READ_DIR_MAX=300` 截断）；文本给行窗分页（`offset`/`limit`/`max_chars`，默认 2000 行 / 60000 字符，窗口满标 `truncated`，大文件行总数记 `null` 不假装精确）；图像只给类型+尺寸、二进制只给类型+字节数（`content=null`，不猜内容）；非 UTF-8 按替换处计数并在 `note` 标存疑。相对路径基准 = `workdir`（缺省进程 cwd）；`HIVE_READ_ROOTS` 非空时越界即拒读（错误里带回 `roots`）。 |

退出码 0 成功 / 2 规格错 / 3 API 错误。rust 侧以 result.json 的 error 字段定终态
（done / error），执行器崩溃由超时兜底。env：`HIVE_API_KEY`（必填，缺失即 fail）、
`HIVE_API_BASE`（默认 `https://open.bigmodel.cn/api/paas/v4`）。

## 满上下文换人续跑（handoff）

**问题**：长任务跑着跑着把 200k 预算吃满——旧行为是整个任务判失败，已完成的几十轮
工具调用随实例一起丢。**机制**：达预算时执行器**不失败**，而是写进展卡 + 交回：

```json
{"ok": true, "content": "【交回续跑】…", "completed": false,
 "need_continue": true, "tool_rounds": 12,
 "handoff": {"reason": "context_budget", "est_tokens": 210000,
             "budget_tokens": 200000, "rounds_done": 12,
             "progress_file": "progress.jsonl", "auto_continue": false}}
```

`ok:true` + `completed:false` 并存，是为了诚实区分「本次执行正常收口」与「任务已完成」——
交回不是错误，实例退休而状态留在盘上（状态在库里，不在实例里）。

| 观测面 | 交接信号 |
|---|---|
| `hive poll`（rust） | `completed` / `need_continue` / `handoff_ready`（派生，一眼判）/ `handoff` / `tool_rounds`；旧 result 缺失字段透传 Null，不伪造 false |
| `hive_poll`（MCP） | result.json 原样透传 + 同口径 `handoff_ready` |
| 进展卡 | `jobs/<id>/progress.jsonl`：`start` / `tool` / `final` / `handoff` / `error` 逐条（含 `ts`、`round`、证据） |

读进展卡（主代理侧，`hive/wm.py`）：

```cmd
python hive\wm.py progress --job hive\jobs\<id>              :: 运行中/未快照
python hive\wm.py progress --wm <WM> --job-id <id>           :: 已快照（两级查找：工作区 → task/<id> 分支）
```

**已快照来源走两级查找**：`snapshot` 提交后 HEAD 归还 `main`，产物只存在于
`task/<job_id>` 分支——直读工作区必然落空，故先看工作区，落空再
`git show task/<ID>:jobs/<ID>/progress.jsonl`（返回体 `source`/`ref` 标明读取出处）。

**续跑编排（主代理裁决，执行器不自动续跑——`auto_continue` 恒 false）**：

1. `poll` 见 `handoff_ready=true` → 读 `handoff` 卡与进展卡；
2. 决定续跑 → 以「同 `system_prompt` + 进展摘要最小充分注入 + 剩余目标」`hive_spawn`
   新 job（同 `session` 读回记忆面）；
3. 不续跑 → 收尾：清理工作记忆临时进展态 + 结果蒸馏归档（`hive/wm.py snapshot`
   入库产物；结论写灵枢记忆）。

**边界（诚实）**：预算是**保守估算**（文本 4:1 字符折算，图像按 1200 tokens/张计入），
估算偏高会提前交回——收窄任务或调大 `context_budget_tokens`。`context_strict=true`
恢复旧 fail fast（超预算即 `error`）。进展卡是观测/交接通道：写失败只记 `log.txt`，
不终杀任务。

## 确定性执行（exec_cmd.py · 零 LLM）

**第 17 条「确定性执行 = 自定义 worker」的落地形态**：`hive/exec_cmd.py` 与 `exec.py`
契约完全一致（`argv[1] = job 目录`，读 `spec.json` 写 `result.json`），但不调 LLM——
把 spec 里的命令当任务跑。`HIVE_EXEC_PY` 指向它时，**一个 serve 同时承载两类任务**：
spec 带 `command` / `commands` → 跑命令；不带 → 转发给同目录 `exec.py`（LLM 委托，
行为逐位不变）。不指向它时全链路零变动。

| 字段 | 说明 |
|---|---|
| `command` | 单条命令，**只收 argv 数组**（如 `["python","-m","pytest","-q"]`）；字符串形态一律拒（不经 shell，规避转义 / GBK 陷阱） |
| `commands` | 多步串行：`[{"command":[...],"cwd":...,"label":...}, ...]` |
| `cwd` | 工作目录（缺省 spec.workdir → job 目录） |
| `env` | 附加环境变量（覆盖继承值）；执行器强制补 `PYTHONUTF8=1` |
| `fail_fast` | 默认 true：任一步非 0 即停，不再跑后续步 |
| `timeout_step_s` | 单步超时（缺省 spec.timeout_s → 600）；rust 侧另有硬超时兜底 |
| `expect_files` | 执行后断言存在（相对 cwd），缺失即 error |
| `expect_stdout_contains` | 各步 stdout 合并文本须含**全部**给定子串，缺一即 error |

订阅约定：`model` 写 `"cmd"`、`user_prompt` 写任务标签——仅为过 rust 侧必填校验，
本执行器不发任何网络请求。单步完整输出落 `step_<i>_stdout/stderr.txt`，`result.json`
只留 head（4000 字符）防爆炸。退出码 0 成功 / 2 规格错 / 3 执行错。

```json
{"model":"cmd","user_prompt":"回归套件","cwd":"<仓根>","env":{"PYTHONPATH":"<仓根>"},
 "commands":[{"command":["python","-m","md_cg.test_cond_match"],"label":"cond_match"}],
 "expect_stdout_contains":["0 failed"]}
```

> 实测边界：包内测试脚本含相对导入（`from .mdcg import …`），直跑
> `python md_cg/test_cond_match.py` 会报 `attempted relative import with no known
> parent package`——须以 `-m md_cg.test_xxx` 形式运行，且 cwd / PYTHONPATH 指向仓根。

## 任务编排（orch.py · 主代理只做编排）

**问题**：单代理跑大任务时，主实例把上下文全花在「自己干活」上——拆解、执行、收口混在
一个预算窗口里，边做边忘。**机制**：`orch.py` 让主实例只当**编排者**——拆子任务派出去、
看卡片、收口结论；子任务在蜂巢 worker 池并发跑，各自独立上下文。

与既有件的分工（避免重复建设）：

| 件 | 管什么 | 与本层关系 |
|---|---|---|
| `exec.py` | 单代理执行器（LLM 委托 + 工具循环） | **复用**：同一 agent loop、同一 spec / result 契约 |
| `exec_cmd.py` | 多态转发层 | `spec.orchestrate` 真值 → 转发本层（否则 `exec.py`） |
| `md_cg/units.py` | ccgc 复核通道（reflect / verify 专用 role 面） | 不复用——编排面是任意子任务 |
| `test/orchestrator_memory.py` | **记忆层**并发（卡片提交 / 收口 / 裁决） | 正交：它管「记忆节点并发写不打架」，本层管「任务怎么拆」 |

### 编排三工具（不外传子代理）

| 工具 | 说明 |
|---|---|
| `spawn_subtask` | 派发子任务（**毫秒即返，不阻塞**）。子任务 prompt 必须自足——子代理看不到编排者上下文，也不能再派发 |
| `poll_subtasks` | 看进度与卡片；不传 `job_ids` = 本编排者派发的全部 |
| `read_full` | 按需拉取**本编排者派发的**子任务的 `result.json` 全文（默认上限 20000 字符，超出给头 + 指针） |

**卡片回流（省编排者上下文）**：`poll_subtasks` 默认只给 `content_head` 200 字 +
`tool_trace` 尾部 6 条（`tool_calls` 全量仍可审计）+ `result_path` + `hint` 指路
`read_full`；`full=true` 或 `read_full(job_id)` 才拿全文。

### 权限（收窄派生令牌，真源 = `md_cg/tokens.py` 的 `ORCH_*`）

| 能 / 不能 | 说明 |
|---|---|
| **能** 裁决子代理冲突 | `op=review` 在清单内（库层走 `require_admin`，故派生令牌 `can_admin=True`——能力所求，非越权） |
| **不能** 动地基 | 层白名单不含核心层 `anchor` / `self` |
| **不能** 删除 / 提权 | `forget` / `identity` / `protect` / `delegate` / `maintain` / `consolidate` 均不在清单 |
| **不能** 自验派生 | 派生令牌结构上 `delegable=False`（二次 `derive` 被库层拒） |
| 派生**只收窄** | `derive` 与父令牌 ops / layers 求交，不放大 |

**fail-closed（硬纪律，不降级）**：令牌缺失 / 无效 → 立即写 `result.json`
（`error_code=orch_token_unavailable`）并退出，**绝不**降级为默认 recorder 身份继续跑。
理由（第 4 条）：静默降级 = 权限意图落空且不可见——模型每轮裁决都失败，但 job 仍以
`done` 结束，使用者看到一次「成功」的编排，实际从未裁决过任何冲突。

### 结构性护栏（不靠约定）

- **防无限递归**：子 spec 由**白名单键**构造，`orchestrate` 不可能出现；子代理 `tools`
  只能是 `lingshu_cg` / `web_search` / `read_file` 的子集（编排三工具不外传）——两条独立防线。
- **越权读拒绝**：`read_full` 只允许读本编排者派发的子任务。
- **上限诚实**：子任务数达 `max_subtasks`（默认 8）即报错，不静默丢弃、不静默排队。
- **换人续跑不重复派发（能力边界如实标注）**：子任务清单落编排者自己的 job 目录
  （`_children.json`），**同机**接管者读回清单即不重复派发。
  边界：该文件**不在** `wm.py` 快照白名单内（白名单 = `spec.json` / `result.json` /
  `log.txt` / `progress.jsonl` / `--artifacts`）——跨 worktree / 跨机经工作记忆接管时
  清单**不回传**，接管者只能从 `progress.jsonl` 的 `spawn_subtask` 条目得知**派发过几个**、
  拿不到完整清单，此时会重复派发。跨机续跑须显式 `wm.py snapshot --artifacts _children.json`
  纳入（落 `artifacts/_children.json`，非 job 根）。

### 启用

```cmd
:: ① 签发编排器令牌（父令牌须为 designer 且可派生）
python -m md_cg.tokens issue --role designer          :: 若无 designer 令牌
python -m md_cg.tokens orch --token-file-in <designer.token> --out <orch.token>

:: ② 注入 serve 环境（serve 级，改后须重启 serve）
set HIVE_ORCH_TOKEN_FILE=<orch.token>
set HIVE_EXEC_PY=<仓>\hive\exec_cmd.py               :: 多态转发：按 spec.orchestrate 分流
```

```json
{"model":"deepseek-flash","user_prompt":"查清这仓测试失败原因并给修复方案",
 "orchestrate":{"max_subtasks":4}}
```

子任务跑在同一个 serve 的 worker 池里——编排者只负责派发与收口，不参与执行。

## 环境变量

| 变量 | 默认 | 说明 |
|---|---|---|
| `HIVE_API_KEY` | 无 | 执行器必填；缺失任务即 error |
| `HIVE_API_BASE` | GLM 开放平台 | OpenAI 兼容 base url（LLM 通道） |
| `HIVE_JOBS_DIR` | `<exe>/../../jobs` | 任务根目录（**同一 jobs 目录至多一个 serve**：CLI 与 MCP 均有单实例守卫，判活为三层——心跳新鲜 + pid 存活 + pid 身份；守卫认为在跑时会拦启动，确认无 serve 在跑（如心跳残留）请加 `--force`） |
| `HIVE_EXEC_PY` | `<exe>/../../exec.py` | 执行器路径（serve 级，**启动时固化并写入心跳**）。指向 `hive/exec_cmd.py` 可让同一 serve 兼跑确定性任务与编排任务（多态转发）；**未设时回退默认 `exec.py`（llm_only）——确定性执行不可用**：serve 启动时 stderr 告警、doctor 的 `exec_mode` 显示 `llm_only` |
| `HIVE_ORCH_TOKEN` | 无 | 编排器派生令牌明文（`python -m md_cg.tokens orch` 签发）；与下行二选一，**缺失即 fail-closed 拒绝启动**（不降级为默认身份） |
| `HIVE_ORCH_TOKEN_FILE` | 无 | 同上，令牌文件路径（避免明文进环境变量 / 命令行历史） |
| `HIVE_WORKERS` | 4 | worker 池大小 |
| `HIVE_PYTHON` | `python` | 执行器解释器 |
| `MDCG_ROOT` | 无 | lingshu_cg 认知图根（serve 级；任务级可用 `spec.mdcg_root` 兜底） |
| `MDCG_HOME` | 执行器父目录 | md_cg 包所在仓根（同仓分发零配置） |
| `HIVE_WEB_SEARCH` | `zhipu` | 搜索后端：`zhipu` / `duckduckgo` |
| `HIVE_WEB_SEARCH_BASE` | 智谱官方 `/api/paas/v4` | zhipu 搜索端点 base（与 `HIVE_API_BASE` 解耦） |
| `HIVE_WEB_SEARCH_KEY` | 回落 `HIVE_API_KEY` | 搜索密钥（key 与 LLM base 不配对时独立设置） |
| `HIVE_READ_ROOTS` | 无（= 读放开） | `read_file` 可读根白名单（`os.pathsep` 切分，支持多根，逐项 `expanduser+realpath`）。**未设置或全空 = 读放开**（缺省全路径开放）；设为至少一个真实目录即收窄，越界即拒读；只影响 `read_file`，不影响 `lingshu_cg`（认知图用自己的 root） |

## 验证

- `cargo test`：22 项全绿（lib 17 + main 5；lib 含 3 个真子进程端到端：done / 超时强杀 /
  kill 通道，FAKE_EXEC 假执行器注入，不依赖网络与密钥；main 含 4 项 `result_summary`
  交接字段单测与 1 项存活判据身份层单测——无关进程不得被判成 serve）。
- `python hive/test_serve_entry.py`：38 项全绿（serve 入口口径守卫——存活窗口单一常量源、
  单实例守卫三层判据、执行器资格由 serve 自报心跳承载、推荐入口唯一、假存活端到端复现
  四种心跳形态）。**干净克隆可直接跑**（配置载体 local 优先、缺失退回入库模板
  `config.local.example.json`）。
- `python hive/hive_mcp/smoke_test.py`：13 项全过（MCP 协议面 / spawn 结构校验 /
  serve 自动拉起端到端 / kill 通道，全程统一 env 注入假执行器）。
- `python hive/test_exec_tools.py`：62 项全绿（工具注册表 / lingshu_cg 真库层 /
  web_search 假 urlopen / **read_file 只读面**（读写不对称 / 白名单收窄 / 行窗分页 /
  非文本诚实面）/ agent loop / 预算交回 / 图像护栏 / 提示词真源重建）。
- `python hive/test_exec_cmd.py`：9 例全绿（确定性执行器——argv 校验 / 多步 fail_fast /
  cwd 缺失 / expect_files / expect_stdout_contains / 单步超时强杀 / LLM 委托转发）。
- `python hive/test_wm_progress.py`：44 项全绿（工作记忆进展面——跨面契约 / 快照白名单 /
  job 与已快照两源读取 / 分支态两级查找 / CLI 单行 JSON / 坏行诚实降级）。
- `python hive/test_orch.py`：74 项全绿（编排器——权限收窄面 / 三工具护栏与结构性防递归 /
  卡片截断与按需拉取 / `exec.py` 两个扩展口默认零变更 / `exec_cmd.py` 转发档 /
  `main()` 装配与令牌缺失 fail-closed）。
- `python scripts/run_tests.py hive`：蜂巢组整体回归入口。
- 端到端四路径实测（2026-09-16，真 serve）：确定性成功 → `done`；命令 exit≠0 → `error`
  （error=失败步标签）；断言未命中 → `error`（error=`输出未命中预期子串：…`）；
  LLM 委托 → `done`（`deepseek-flash` / effort=high / 200k / 600s，content=`HIVE_UNIFIED_OK`）。
- `cargo build --release`：0 warning。
- 数据文件（status.json / result.json / _serve.json）经 tmp+fsync+rename
  原子替换落盘：并发读者不会读到截断空窗口（避免「空输入」parse 失败）。

## 设计边界（诚实）

- TLS 不进 rust：纯 std 无第三方库不可行，HTTPS 全在执行器（D-005 的结构性取舍，
  不是遗留缺陷）。
- kill 与超时的检测粒度 = 1s 轮询，非信号级即时。
- doctor 判活 = 三层（心跳新鲜 + pid 存活 + **pid 身份**：Windows tasklist 映像名列 /
  unix `/proc/<pid>/cmdline`）。身份层在零依赖边界下可能取不到映像名——此时**保守判假**
  （宁可放行一次启动，也不误报「已有 serve 在跑」把运维引向不存在的进程）。
- 单实例守卫的「在跑」判定**不构成授权**：`--force` 是显式豁免出口，用于确认无 serve
  在跑（如心跳残留）的情形。
- 归属是归因不参与调度：任务无身份隔离，共享 jobs 目录的调用方互见（与灵枢记忆
  「归属归因」同构的多任务版）。
