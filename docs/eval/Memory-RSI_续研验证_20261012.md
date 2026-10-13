# Memory-RSI 续研验证 · 2026-10-12

本轮完成 CSRE 负条件与索引一致性修复，并补充实际本地工具链的验证证据。Memory-RSI 继续默认关闭，没有自动接受知识，没有接入正式 DSH。未开展 LLM reader / Agent 的任务成功率实验。

CSRE 的行为、兼容影响、20 项回归与成本对照见 [索引与负条件修复](../mdcg/CSRE_索引与负条件修复_20261012.md)。第一轮的研究报告与公开语料负结果继续有效；本轮没有用新工具夹具覆盖这些负结果。

## 实际工具检查

`md_cg.bench_memory_rsi_tools` 创建三类新文件项目：相对路径配置读取、UTF-8 BOM JSON 读取、UTF-8 BOM CSV 字段读取。每类先实际运行失败的 Python 程序，再分别测试正确修复、重复错误操作、返回占位值。共 9 条轨迹、18 次训练工具调用。

检查标准在运行前冻结：**退出码为 0，且 stdout 解析后的 JSON 与独立预期结果完全一致**。返回占位值的程序虽然退出码为 0，但结果错误，仍判失败。每次 subprocess 的 argv、cwd、返回码、完整 stdout/stderr、程序哈希和预期结果保存为 JSON，轨迹引用这些记录的哈希。

原型原样使用 `record_experience → reflect → verify → curate`；没有改 Reflector 判据，也没有放宽证据范围。

| 指标 | 实测 |
|---|---:|
| 成功观察 | 3 |
| 失败观察 | 6 |
| 退出码 0 但结果检查失败 | 3 |
| 失败观察生成的候选 | 0 |
| 成功观察进入原待审队列 | 3 |
| 自动写入 knowledge 的节点 | 0 |
| 在新文件实例重放固定修复方案 | 3/3 通过 |
| 重放阶段图文件哈希变化 | 无 |
| 待审回滚 | 1 条成功；队列 3 → 2 |
| 总工具调用 | 21，未超过冻结上限 |

新实例的文件内容与训练实例不同，程序和修复方案固定，重放阶段不重新学习。每个方案只在与预定义白名单动作完全相等时执行，输入候选不能变成任意代码或 shell 命令。超时 5 秒，无网络、安装命令或外部应用操作。

这比填入一个 `passed=True` 多了真实进程和独立结果校验，证据可按原始记录复核。但夹具、控制器和三个修复方案都是预先构造的，候选也没有经默认召回交付给 LLM。因此 **3/3 是固定方案的实例复验，不是 Agent 迁移成功率，不是记忆学习收益**。没有无记忆/相同门控/反思三臂的自然任务对照，不给出模型能力提升数字。

工具记录由此本地运行器产生，可核对文件哈希；原型仍不具备外部工具身份签名或硬件可信证明，`external_authenticity` 仍为 `not_authenticated`。候选精确匹配与固定 0.5 可信度的局限没有改变。

## 复现与结果路径

全部命令从 dsh-memory 工作区运行，先设置新的 TEMP、MDCG_ROOT、MDCG_DATA_ROOT、MDCG_STATE_ROOT、MDCG_AUX_ROOT、DSH_HOME，清除继承的身份/密钥与 WB 配置；只为实验设置需要的开关。完整测试不统一关闭待测功能。

```powershell
& $python -X utf8 -m md_cg.test_csre_correctness
& $python -X utf8 -m md_cg.bench_csre_correctness --out E:/lab/new-csre-result
& $python -X utf8 -m md_cg.bench_memory_rsi_tools --out E:/lab/new-tool-result
& $python -X utf8 -m scripts.run_tests md_cg --jobs 1 --timeout 300
```

实验脚本拒绝复用既有输出根，需每次使用新目录。交付包中含可配置隔离运行器、修复前源码、源码补丁、清单哈希和以下原始证据：

- `evidence/csre-before/` 与 `csre-after/`：协议、同数据 fixture、逐查询结果、原始计时和源哈希。
- `evidence/tool-loop/`：冻结协议、程序、原始工具记录、构造文件、原图中的轨迹和原 inbox 待审/回滚留痕。测试身份密钥不交付。
- `evidence/audit-after/`：旧探针修复后的结果，含明确的 stale / source_mismatch 状态。
- `evidence/validation/`：红测、20 项绿测、原守卫、完整 Memory 组、补丁和文档索引校验。包括错误配置导致的首轮失败与中止记录。

完整 Memory 组：本次完整组 308/309 个可运行模块通过，1 项失败；3 项私有语料 SKIP，共 312 个发现模块。唯一失败是新增工具基准的裸索引迭代；改成快照后，原 H4 完整守卫独立复跑通过，工具链也复跑通过。未再重跑整个组，不将两次运行拼称一次全绿。逐模块完整日志齐备，18 个冻结 Python 文件未变，1 个脚本的修复另留版本。3 项依赖 gitignored 私有语料的 SKIP 单独列出，不当作通过。

## 研发决定

可以为确定的基础修复准备独立 PR，迁移说明必须包含旧索引显式重建和完整指纹的额外成本。Memory-RSI 原型的 PR 保持实验定位、默认关闭和原 inbox 审核门槛。

下一步验证 LLM Agent 收益时，需要冻结模型、reader、预算、重试、任务与裁判，比较无记忆、相同审核门控、反思候选三个条件，并让任务集含失败修复和条件不匹配反例。本轮没有默认调用未配置的模型，也没有把固定工具程序包装为该实验。
