# Memory-RSI 第二轮交付

已完成 72 次 DSH 运行：6 个真实历史缺陷 × A/B/C/D × 3 次重复。

| 组 | 配置 | 成功数 |
|---|---|---:|
| A | 原始 CSRE 检索路径 | 7/18 |
| B | 仅底层修复 | 10/18 |
| C | 修复 + 始终触发反思，最多两次 | 10/18 |
| D | 修复 + 条件触发反思，最多两次 | 11/18 |

底层正确性收益保留；始终反思没有提高成功率；条件反思只有小幅、尚不稳定的收益信号。D 比 C 总 token 少 6.65%，约 99% 的差额来自缓存；未缓存输入与输出合计只少 0.75%。反思仍默认关闭，未改生产 DSH 插件，未提交 PR。

- `第二轮实验报告.md`：完整表格、五个研究问题、验证范围和局限。
- `research-conclusions.md`：研究结论简版。
- `research-followup.md`：六篇新参考与后续单因素实验优先级。
- `trials.csv` / `analysis.json`：逐运行数据与分组、配对汇总。
- `protocol.json` / `source-freeze.json`：冻结任务、预算、源码与数据哈希。
- `runs/holdout`：全部原始 DSH 日志、工具反馈、候选代码和独立评分。
- `posthoc-acceptance-v2.json`：原“通过”凭据候选的扩展验收；其中 C 的一个候选误拒绝另一有效身份。主评分未改。
- `bottom-fix-note.md`：新增误拒绝反例、修复和回归证据。
- `MANIFEST.json` / `delivery-qa.json`：文件完整性、原始日志与密钥泄漏检查。

归档包含共用源码模板，每运行完整项目与临时状态保留在 E 盘工作目录。离线复验见 `replay_trial.py`；同机完整重跑可用 `prepare_reproduction.py --out E:\新的空目录`，保留冻结预算并重定位路径。需要现有 DSH/Python 运行时和模型凭据，步骤见实验报告。
