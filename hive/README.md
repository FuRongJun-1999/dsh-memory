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

# 配置密钥（执行器用）
set HIVE_API_KEY=你的密钥

# 起 serve——推荐正路：serve_start.py 读本地配置注入 env（key 不落命令行历史）
# 配置文件：hive/config.local.json（已 gitignore；值支持 直值 | {"env":"系统变量名"} | {"file":"key文件路径"}）
# 推荐形态：HIVE_API_KEY 引系统变量（如 DEEPSEEK_API_KEY），HIVE_WEB_SEARCH_KEY 引 key 文件
python serve_start.py            # 拉起（已在跑则拒绝）；--stop 停止；--status 查看心跳与任务统计

# 或手动起 serve（env 需自行带全：HIVE_API_KEY 必填；默认 4 worker；HIVE_WORKERS 可调）
target\release\hive.exe serve

# 提交任务（stdin JSON）——模型名须与 HIVE_API_BASE 配对（见 spec 字段表）
echo {"model":"deepseek-flash","user_prompt":"总结这份文档","context_files":["README.md"]} | target\release\hive.exe submit -

# 查状态 / 强杀 / 体检
target\release\hive.exe poll
target\release\hive.exe kill <job_id>
target\release\hive.exe doctor
```

### MCP 接入（推荐宿主直连）

`hive/hive_mcp/mcp_server.py` 提供四工具（手写 stdio JSON-RPC，形态对齐
`md_cg/mcp_server.py`）：

| 工具 | 用途 |
|---|---|
| `hive_spawn` | 提交任务（spec 结构校验 fail fast），返回 job_id |
| `hive_poll` | 无 id = 全部摘要（content 截 800 字）；带 id = 单查全文 |
| `hive_kill` | 写 kill 标志，worker ≤1s 内强杀 |
| `hive_doctor` | serve 存活 / 任务状态统计 / env 检查 |

首次 spawn 自动以 detached 方式拉起 serve（Windows
`DETACHED_PROCESS|CREATE_NO_WINDOW`）。**执行器是 serve 级配置**：
`HIVE_EXEC_PY` / `HIVE_JOBS_DIR` 在 serve 启动时读取，改动后须重启 serve 才生效。

**统一子代理默认**（缺省即注入 spec，调用方显式传值优先）：`reasoning_effort=high`、
`context_budget_tokens=200000`、`timeout_s=600`（10 分钟）；spawn 返回体 `spec_defaults`
回显实际生效值便于核对。

**serve env 的真实来源 = `config.local.json`**（`serve_start.py` 读注入）。serve 的 env
在启动时固化，子进程无法反查——故 `hive_doctor` 把 env 拆两列：`serve_env_source`
（权威，**判资格看这列**）与 `mcp_process_env`（仅诊断，用它判会得到错位结论）。
MCP 首次拉起 serve 时同样按「宿主 env + config.local.json」组装，两条拉起路径口径一致。

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
| `context_budget_tokens` | 否 | 输入 token 预算（执行器保守估算，超限 fail fast）；**MCP 面默认 200000** |
| `thinking` | 否 | 思考开关透传（如 `{"type":"enabled"}`） |
| `max_tokens` / `temperature` | 否 | 透传 API |
| `tools` | 否 | 工具白名单，子集 `["lingshu_cg","web_search"]`；非空即启用 agent loop（function calling 循环），缺省 = 单发调用（历史行为逐位不变） |
| `max_tool_rounds` | 否 | 工具轮上限，默认 5；达到后强制终答（不带 tools 再发一次） |
| `mdcg_root` | 否 | lingshu_cg 的认知图根兜底（env `MDCG_ROOT` 优先）；如任务级隔离用临时图 |
| `web_search_backend` | 否 | web_search 后端兜底（env `HIVE_WEB_SEARCH` 优先）：`zhipu` / `duckduckgo` |

确定性任务另有 `command` / `commands` 等字段，见下节。

spec 在 submit 时做存在性校验（context 文件必须已存在，fail fast 防任务白跑）。

## 任务生命周期与崩溃恢复

```text
pending → claimed → running → done | error | timeout | killed
```

- **原子领取**：worker 以 `create_new` 写 `claimed.lock`，多 serve / 多 worker 竞争
  只有一个成功，无需外层锁。
- **心跳**：worker 周期性刷新 `status.json` 的 heartbeat；serve 侧 `_serve.json`
  心跳供 doctor 判活（新鲜度 + pid 双判据）。
- **超时强杀**：超过 `timeout_s` → `child.kill()` → 终态 `timeout`。
- **kill 通道**：`kill` 标志文件，worker 1s 轮询粒度检测后强杀（诚实边界：非即时信号）。
- **崩溃恢复**：serve 重启时 `recover_orphans`——`claimed` 重新投递、`running` 标
  `error`（结果未知，绝不假装 done）。

## 文件协议（接口即目录）

```text
jobs/
  _serve.json                 # serve 心跳（pid/ts/workers）
  <job_id>/
    spec.json                 # 任务规格（submit 时写入）
    status.json               # 状态（先写 status 后写 spec = 就绪信号）
    result.json               # 结果（error 字段区分成败；终态判据）
    claimed.lock              # 原子领取锁（create_new）
    kill                      # kill 标志（存在即请求强杀）
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

| 工具 | 说明 |
|---|---|
| `lingshu_cg` | 灵枢认知图（`op=route\|read\|write` 白名单，复用 MCP 面同一 dispatch）。权限硬编码 recorder（`can_admin=false`，spec 无法提权）——写入过校验闸门：DEFER 入审核队列 / REJECT 负记忆是设计行为，裁决权留给设计者。会话隔离 `session=hive_job_<id>`。write 的 `verification_basis` 前置校验合法枚举（防自由文本卡死审核队列）。 |
| `web_search` | 网页搜索。`zhipu` 后端走 `/web_search` 端点（`HIVE_WEB_SEARCH_BASE` 缺省智谱官方，与 `HIVE_API_BASE` 解耦——后者常为 LLM 中转网关、无搜索路由；`HIVE_WEB_SEARCH_KEY` 缺省回落 `HIVE_API_KEY`）；`duckduckgo` 零 key 兜底。 |

退出码 0 成功 / 2 规格错 / 3 API 错误。rust 侧以 result.json 的 error 字段定终态
（done / error），执行器崩溃由超时兜底。env：`HIVE_API_KEY`（必填，缺失即 fail）、
`HIVE_API_BASE`（默认 `https://open.bigmodel.cn/api/paas/v4`）。

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

## 环境变量

| 变量 | 默认 | 说明 |
|---|---|---|
| `HIVE_API_KEY` | 无 | 执行器必填；缺失任务即 error |
| `HIVE_API_BASE` | GLM 开放平台 | OpenAI 兼容 base url（LLM 通道） |
| `HIVE_JOBS_DIR` | `<exe>/../../jobs` | 任务根目录 |
| `HIVE_EXEC_PY` | `<exe>/../../exec.py` | 执行器路径（serve 级）。指向 `hive/exec_cmd.py` 可让同一 serve 兼跑确定性任务 |
| `HIVE_WORKERS` | 4 | worker 池大小 |
| `HIVE_PYTHON` | `python` | 执行器解释器 |
| `MDCG_ROOT` | 无 | lingshu_cg 认知图根（serve 级；任务级可用 `spec.mdcg_root` 兜底） |
| `MDCG_HOME` | 执行器父目录 | md_cg 包所在仓根（同仓分发零配置） |
| `HIVE_WEB_SEARCH` | `zhipu` | 搜索后端：`zhipu` / `duckduckgo` |
| `HIVE_WEB_SEARCH_BASE` | 智谱官方 `/api/paas/v4` | zhipu 搜索端点 base（与 `HIVE_API_BASE` 解耦） |
| `HIVE_WEB_SEARCH_KEY` | 回落 `HIVE_API_KEY` | 搜索密钥（key 与 LLM base 不配对时独立设置） |

## 验证

- `cargo test`：13 项全绿（含 3 个真子进程端到端：done / 超时强杀 / kill 通道，
  FAKE_EXEC 假执行器注入，不依赖网络与密钥）。
- `python hive/hive_mcp/smoke_test.py`：13 项全过（MCP 协议面 / spawn 结构校验 /
  serve 自动拉起端到端 / kill 通道，全程统一 env 注入假执行器）。
- `python hive/test_exec_cmd.py`：9 例全绿（确定性执行器——argv 校验 / 多步 fail_fast /
  cwd 缺失 / expect_files / expect_stdout_contains / 单步超时强杀 / LLM 委托转发）。
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
- doctor 判活主判据 = 心跳新鲜度，pid 探测（tasklist / kill -0）是尽力而为的辅助。
- 归属是归因不参与调度：任务无身份隔离，共享 jobs 目录的调用方互见（与灵枢记忆
  「归属归因」同构的多任务版）。
