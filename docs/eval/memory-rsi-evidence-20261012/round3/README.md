# Memory-RSI 第三轮交付索引

先读 `研究结论.md` 和 `第三轮实验报告.md`。完整可分析主样本为 `normalized-results.json`：`controlled-v2` 原始120份记录中两份因HTTP 402中断，原件保留，以 `service-replacements` 的两份同配置运行替代。合计122次主实验尝试。根目录 `runs` 是因CRLF编辑器错误被整批排除的初始批次，不参与排名，日志与成本保留。

## 文件与代码改动

| 内容 | 入口 |
|---|---|
| 第二轮18配对案例、61反思事件 | 第二轮逐案例分析.md、round2-case-audit.json、round2-rendered-novelty.json |
| 身份误拒根因与最小修复 | 身份误拒根因与修复.md、identity-minimal-fix.patch、identity-sources.json |
| 完整身份字段正反回归 | identity-results-v2.json、identity-tests-v2/、identity-path-boundaries/ |
| 真实 DSH/stdin MCP 证据 | identity-mcp/dsh.stdout.jsonl、identity-mcp/audit.json |
| 新测试与固定条件 | 独立测试集与实验协议.md、controlled-v2/protocol.json、controlled-v2/source-freeze.json |
| 五组结果/成本/配对 | analysis.json、trials.csv、第三轮逐案例分析.md |
| 服务中断与补跑映射 | service-interruption-policy.json、normalized-results.json、service-replacements/replacement-plan.json |
| 身份扩展验收 | expanded-identity.json、expanded-identity/ |
| 同轨迹触发重放 | trigger-trajectory-replay.json |
| 经验重复、触发选择性与来源容量 | evidence-diagnostics.json、diagnose_evidence.py |
| 公开动态史证据诊断 | public-temporal/、public-benchmark-input/ |
| 默认关闭与证据边界 | evidence-boundary/result.json |
| 文献与后续门槛 | 研究参考与下一阶段门槛.md |
| 完整第二轮原件 | round2-full-evidence.zip，SHA256见artifact-layout.json |

身份代码只改隔离生成候选的 `source-fixed/md_cg/mcp_server.py`，补丁针对指定SHA256；当前主线已经采用正确缓存机制，未重复修改主线。E只改评测插件中的一个触发gate。`controlled-v2/text-edit.mjs` 修正工具的LF/CRLF匹配，已做7项行为回归；该修正对所有组一致，与算法或评分改动无关。

其余代码是夹具、外部评分、运行、归因及封存脚本。候选模块在各trial的 `project/<target>`，属于模型生成研究样本，未作为产品改动应用。

## 环境与实际执行的主要命令

Windows PowerShell；Python 3.12.10，既有venv；Node 24.16.0；DSH正常命名profile。DSH提交与CLI哈希见冻结清单。既有API凭据由DSH凭据引用读取，不出现在命令或交付文件中。

```powershell
$round3Python = 'E:\Codex\2026-10-08\referenced-chatgpt-conversation-this-is-an\work\venv\Scripts\python.exe'
$round3Work = 'E:\lingshu\work\memory-rsi-round3-20261012'
& $round3Python -X utf8 (Join-Path $round3Work 'run_identity_v2.py')
& $round3Python -X utf8 (Join-Path $round3Work 'finish_p0.py')
node (Join-Path $round3Work 'test_editor.mjs')
node (Join-Path $round3Work 'controlled-v2\run.mjs') freeze
node (Join-Path $round3Work 'controlled-v2\run.mjs') holdout
& $round3Python -X utf8 (Join-Path $round3Work 'prepare_service_replacements.py')
node (Join-Path $round3Work 'service-replacements\run.mjs') holdout
& $round3Python -X utf8 (Join-Path $round3Work 'normalize_service_results.py')
& $round3Python -X utf8 (Join-Path $round3Work 'public_temporal_diagnostic.py')
& $round3Python -X utf8 (Join-Path $round3Work 'evidence_boundary_probe.py')
& $round3Python -X utf8 (Join-Path $round3Work 'posthoc_identity.py')
& $round3Python -X utf8 (Join-Path $round3Work 'replay_trigger_trajectories.py')
& $round3Python -X utf8 (Join-Path $round3Work 'analyze_round3.py')
& $round3Python -X utf8 (Join-Path $round3Work 'diagnose_evidence.py')
& $round3Python -X utf8 (Join-Path $round3Work 'report_round3.py')
```

上面是原始执行记录，部分脚本要求新输出目录，不应直接覆盖重跑；复现用下面的独立新目录入口。服务替代脚本只适用于本轮已固定的两次QUOTA事件，不是通用重试或选择成功候选的工具。保存的 `finish_p0` 会读取已完成回归结果，需新运行时改用新的输出目录。各预检、身份路径边界与MCP启动的原脚本亦在包内。

## 零API候选复现

解包到E盘新目录，把 `$round3Work` 改成解包根。包中重复的基线模块被压缩：每次模型运行保留其真实修改模块，其余从 `controlled-v2/source-main` 重建；原始DSH、检查和错误日志全部保留。合成令牌、临时图与密钥状态由夹具再生成，不需要真实记忆。

```powershell
& $round3Python -X utf8 (Join-Path $round3Work 'restore_identity_sources.py')
& $round3Python -X utf8 (Join-Path $round3Work 'replay_candidate.py') --task same-stat-new-fact --arm D --rep 1 --out 'E:\lingshu\replays\round3-d-r1-new'
& $round3Python -X utf8 (Join-Path $round3Work 'identity_matrix.py') --source (Join-Path $round3Work 'source-fixed') --out 'E:\lingshu\replays\round3-identity-new'
```

复现输出必须是尚不存在的E盘目录。源码只有本地审计边界，非面向恶意代码的认证操作系统沙箱；脚本禁止评分代码网络/子进程访问及越界写入。结果只证明列出的行为断言。

## 重新运行模型对照

此入口只准备新目录；第二条命令才会调用API，最多120次任务。使用同一现有DSH/Python路径与凭据，模型响应存在随机性，不保证输出字节相同。

```powershell
& $round3Python -X utf8 (Join-Path $round3Work 'reproduce_campaign.py') --out 'E:\lingshu\replays\round3-model-new'
node 'E:\lingshu\replays\round3-model-new\run.mjs' holdout
```

换机器时需调整脚本中的Python/DSH路径并重新冻结；不能把不同模型/运行时的结果混入本轮。公开数据来自固定版本hive-memory-bench，署名与许可随包保留。

## 封存与验收

`export_evidence.py` 导出原始轨迹、评分器、冻结模板、候选目标模块及完整第二轮ZIP；`verify_export.py` 在交付目录重新检查冻结哈希、正反候选评分、完整身份矩阵和新模型批次准备，均不调用API。`scan_evidence.mjs` 对交付文件及嵌套ZIP检查当前API凭据的精确字节，凭据不打印或保存。`seal_evidence.py` 生成SHA256清单、ZIP并逐文件复核。

封存验证见 `export-acceptance.json`、`credential-scan.json` 和压缩包旁的 `memory-rsi-round3-20261012-verification.json`。此为本机复现验收；未声称在没有既有Python/DSH依赖的其他电脑上完成安装测试。完整旧实验在 `round2-full-evidence.zip`；重算旧分析需将它解包到common.py声明的第二轮目录或调整该路径，不覆盖已有数据。

## 回滚与状态

停止加载评测patch即可退出实验机制，选择B即完全关闭实验反思，E可切回D。MemoryRSILab普通构造默认关闭，需要显式offline sandbox；探针已验证。生成的知识仅提案，不能自批上线。

当前生产插件、正式记忆库、系统文件和GitHub PR均未修改。身份修复只在隔离候选中；正确主线保留，错误候选仅用于复现，不建议作为业务回滚版本。所有原始实验记录保留，没有删除系统文件。
