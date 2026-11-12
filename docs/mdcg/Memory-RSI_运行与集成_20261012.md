# Memory-RSI 本地运行与 DSH 集成准备 · 2026-10-12

> 本文记录第一轮集成准备，正式安装仍未执行。后续可选会话、新版 Reflector 与验证边界见 [三轮迭代报告](../eval/Memory-RSI_三轮迭代_20261012.md)。

本轮交付可在隔离目录运行的 Python 原型与实验程序。原 API 和正式插件默认行为没有变化；原型未注册到 MCP，也未安装到 DSH。先看[研究结论](../eval/Memory-RSI_研究报告_20261012.md)与[性能及负结果](../eval/Memory-RSI_性能与实验_20261012.md)，再决定下一轮实验。

## 1. 本机运行条件

本轮实际复用的解释器与检出目录如下。换机器时替换这两个绝对路径；不要依赖 WindowsApps 的 `python` 别名。

```powershell
$memoryRsiPython = 'E:\Codex\2026-10-08\referenced-chatgpt-conversation-this-is-an\work\venv\Scripts\python.exe'
$memoryRsiRepo = 'E:\Codex\2026-10-12\files-pasted-by-the-user-lingshu\work\dsh-memory-rsi'
$memoryRsiWork = 'E:\Codex\2026-10-12\files-pasted-by-the-user-lingshu\work'
Set-Location -LiteralPath $memoryRsiRepo
& $memoryRsiPython --version
git status --short
git rev-parse HEAD
```

源码基于 `76a1b7ba0579e8ce589e5f079b853e574735f822`。交付补丁含新增模块、测试、三份报告和文档目录登记，可在该基线先执行 `git apply --check memory-rsi.patch`，通过后应用。保留本地已有修改，不在未知版本上强行应用。

## 2. 测试与诊断命令

先让测试产生的临时、状态与身份数据全部进入新测试目录。这些环境变量只影响当前 PowerShell 及其子进程，不写系统设置。

```powershell
$memoryRsiTest = Join-Path $memoryRsiWork 'local-recheck'
New-Item -ItemType Directory -Force -Path $memoryRsiTest | Out-Null
$env:TEMP = $memoryRsiTest
$env:TMP = $memoryRsiTest
$env:MDCG_ROOT = Join-Path $memoryRsiTest 'graph'
$env:MDCG_STATE_ROOT = Join-Path $memoryRsiTest 'state'
$env:MDCG_AUX_ROOT = Join-Path $memoryRsiTest 'auxiliary'
$env:DSH_HOME = Join-Path $memoryRsiTest 'dsh'
& $memoryRsiPython -X utf8 scripts/run_tests.py --list
& $memoryRsiPython -X utf8 scripts/run_tests.py md_cg -k memory_rsi --jobs 1
& $memoryRsiPython -X utf8 -m md_cg.test_memory_rsi
```

全量回归使用 `--jobs 1`，避免性能敏感守卫因并发而被跳过。Rust 对拍需要先构建当前源码；构建缺失必须保留 FAIL，不能记 PASS。

```powershell
Push-Location rust
& 'E:\Codex\tools\rust\cargo\bin\cargo.exe' build --release
Pop-Location
& $memoryRsiPython -X utf8 scripts/run_tests.py md_cg --jobs 1
```

`test_time_core_lint` 在 Windows 上耗时较长，runner 默认单项超时 900 秒。本轮原版全量及失败重跑详情见性能报告；仍有原版 CRLF 源码形态守卫失败，不能称全量全绿。没有改 TypeScript，因此本轮没有执行 npm install/build/test，也没有声称插件端重新构建通过。

所有实验的 `--out` 必须是**尚不存在**的目录。重复执行请换名字；脚本不会清空旧结果。

```powershell
& $memoryRsiPython -X utf8 -m md_cg.probe_memory_rsi --out (Join-Path $memoryRsiWork 'audit-replay-new')
& $memoryRsiPython -X utf8 -m md_cg.bench_memory_rsi --out (Join-Path $memoryRsiWork 'experiment-replay-new') --rounds 3
& $memoryRsiPython -X utf8 -m md_cg.bench_memory_rsi_latency --experiment (Join-Path $memoryRsiWork 'experiment-replay-new') --out (Join-Path $memoryRsiWork 'latency-replay-new')
& $memoryRsiPython -X utf8 -m md_cg.probe_memory_rsi_mcp --out (Join-Path $memoryRsiWork 'mcp-replay-new')
```

公开状态链复验需要官方公开 benchmark 检出。此次读取的版本为 `f4509d7282f82982af5de9c8fe71863fc95b38cb`，目录是 `work\hive-memory-bench`。程序在运行前后校验 corpus、keys 和官方归一化脚本的哈希。

```powershell
& $memoryRsiPython -X utf8 -m md_cg.bench_memory_rsi_public --bench (Join-Path $memoryRsiWork 'hive-memory-bench') --out (Join-Path $memoryRsiWork 'public-replay-new')
```

以上只计算检索和证据代理指标。要得到官方答案分数，仍须固定 reader 并按官方答卷与判分协议执行；本轮没有这类分数。

## 3. 原型 API 与实验开关

```python
from pathlib import Path
from md_cg.memory_rsi import create_sandbox, MemoryRSILab
from md_cg.mdcos import MdCGOS

base = Path(r'E:\Codex\2026-10-12\files-pasted-by-the-user-lingshu\work\manual-lab-new')
cg = MdCGOS(str(create_sandbox(base)))
try:
    lab = MemoryRSILab(cg, base, enabled=True)
    trace_id = lab.record_experience({
        'task_id': 'isolated-config-test',
        'scope': 'Windows config loader',
        'conditions': ['working directory differs from project root'],
        'events': [
            {'id': 'e', 'kind': 'error', 'text': 'FileNotFoundError config.yaml'},
            {'id': 'a', 'kind': 'action', 'text': 'use absolute config path', 'error_id': 'e'},
            {'id': 'v', 'kind': 'check', 'text': 'config loader assertion result',
             'action_id': 'a', 'error_id': 'e', 'source': 'tool', 'passed': True}
        ]
    })
    candidates = lab.reflect(trace_id)['candidates']
    results = [lab.curate(c) for c in candidates]
    print(results)  # proposed / duplicate / deferred / rejected；不会自动接受
    for result in results:
        if result['status'] == 'proposed':
            print(lab.rollback(result['pid']))  # 原审核 API 留痕撤销，原始轨迹保留
finally:
    cg.close()
```

示例中的 `passed=True` 是演示输入，不代表已经执行了真实工具验证。系统检查回执关联和存储完整性，尚不能认证调用方自报的 `source='tool'`；因此结果始终是候选，不能据此自动信任知识。

`enabled=True` 是显式实例级实验开关，省略即拒绝构造。没有新增会被生产环境误读的全局开关，也没有自动 hook。直接使用 `MdCGOS` 仅限本机可信的离线实验；需要身份控制时传入 `MdCGSecure`，原权限与可见性检查继续有效。原型不会签发或保存凭据。

## 4. MCP 与 DSH 测试准备

准备目录为 `work\dsh-test-preparation`，其中有：

- `mcp-config.json`：绝对解释器、当前 repo cwd 和隔离根。
- `plugin-config.json`：根据本仓 `src/index.ts` 当前 schema 准备的插件配置片段。
- `profile-target.json`：明确测试 profile 名 `memory-rsi-lab-20261012`、安装源码目录与隔离 DSH_HOME；状态为 prepared，未安装。

MCP 配置中的 `MDCG_ROOT`、`MDCG_DATA_ROOT`、`MDCG_STATE_ROOT`、`MDCG_AUX_ROOT` 和租户登记路径全部落在测试准备目录。匿名 guest 用于只读检查；不要将正式根或正式身份目录填进来。该配置只准备既有 MCP 服务，不会自动暴露新 Reflector/Curator。

本轮 `probe_memory_rsi_mcp` 启动真实 `python -m md_cg.mcp_server`，验证 initialize、tools/list、cg info、cg read、匿名写入 AccessDenied 和正常退出。**DSH profile 安装、插件 UI、完整 Agent 上下文注入和带令牌写入均未测试。** 当前终端没有解析到 DSH CLI，不能确认当前安装程序的绝对入口和版本；没有为此重新安装 DSH。

后续先找到已安装的 CLI，查看其 `--help` 及 profile 目标。确认 `DSH_HOME`、profile 名、源目录与实际生成配置路径均为实验目标后，才考虑测试安装命令：

```powershell
# 准备步骤；本轮未执行以下安装命令
$env:DSH_HOME = Join-Path $memoryRsiWork 'dsh-test-preparation\dsh'
dsh plugin --profile memory-rsi-lab-20261012 add .
```

命令需在 `$memoryRsiRepo` 执行，不能把 `<测试profile>` 当字面值；也不能仅凭 profile 名就认为数据路径已经隔离。正式实例的安装、替换和更新仍需用户明确许可，本轮不执行。

如后续需要带身份的写入测试，使用项目原 `md_cg.tokens` 机制，在测试身份目录签发最小角色/操作范围令牌，并从进程环境引用 `MDCG_TOKEN`。不要将令牌放入 Git、配置示例或输出日志，不开启 legacy env 管理员来绕过权限。先测 recorder 的允许写入和禁止审核，再单独以有审核权限的身份测试原 `review_decide`。

## 5. 回滚与已知限制

原型停用方式是停止调用新模块，或不传 `enabled=True`；原检索及生产 hook 未改，不需要迁移真实库。待审候选可用原审核 reject 留痕撤回；原始 trace 继续保留。不要为“回滚”清空认知图或删审计记录。已人工接受的版本由原演化/审核流程人工处置，本轮没有实现接受后自动回退。

当前限制包括：精确槽冲突检测不是通用语义纠错；轨迹外部真实性没有认证；confidence 未校准；源字符偏移不代表完整推理证据；token 是项目估算器读数；没有测物理 RSS 或真实模型成本。公开题中元数据交付曾退化，未知信息仍可能返回非空上下文。正式接线前需要真实 tokenizer、prompt safety、会话及权限隔离、异常状态和实际 Agent 端到端验证。

下一轮优先做未使用自然任务集上的同模型、同预算 A/B/C 对照，并补原有设计文档的 reader/oracle 校准。若仍无任务收益，继续保持实验状态；不因代码能运行、测试多或改动多而认定智能提升。
