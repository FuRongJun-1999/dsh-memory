# 查询相关原文片段：从关系链召回到证据装包

2026-10-13

新增显式启用的 `excerpt_strategy="query"`：按查询选择原文片段，降低“节点找到了，预算却只留下正文开头”的信息损失。最终交付独立基于主线 `9c5d946aef17f756f07053f7f386483015f626cc`，已同步 `d6e8c8376979bbc927d89deb72ec277258e5909c`，不包含尚未合并的 PR #168 关系链改动；两项成果分别验收。

## 算法与实验设置

段落 IDF 降低通用词影响，边际词项覆盖降低重复片段收益，贪心选择最多四个窗口。长段落围绕匹配位置取窗，按原文顺序输出，返回完整正文字符位置；省略标记计入预算。生产选择过程不调用 LLM，不建立新持久索引或全局明文缓存。缺省仍为 prefix；新方式只替换原本触发预算截断的摘录。

初始实验在 PR #168 上冻结源码，功能版归档为 `6a6219f`；第一次原始 JSON 的 HEAD 不能代表当时未提交的选择器，须用所附源码 SHA256 定位。最终移植到上述最新主线，仅补精确 token 计数复用，测量版为 `ddb845f71300f49aaa79d869e35876cfc86e0845`：2500 组固定随机对照与原选择器逐字一致，两个 92 题材料及 query 的原文位置、分数、出处均一致（仅排除重新入库产生的 created_at / condition_space.time_window）。184 份真实原始答卷据此离线重算，未重新调用模型、未按测试题调参。

- 公共数据：[hive-memory-bench](https://github.com/FuRongJun-1999/hive-memory-bench)，固定快照 `f4509d7282f82982af5de9c8fe71863fc95b38cb`；23 章、主轮 92 题。
- 数据 © 2026 符荣峻，CC BY 4.0；评测代码 MIT。原语料与题目未改写，适配为原生 Markdown 章节点，并仅按章节顺序建立 sequential 边。
- 两臂相同 BM25 + chain、k=20、总预算 1200（生产 est_tokens）、截断单条 250、同一题面。候选检索规则相同，片段实际长度改变后，预算能容纳的条目数也可能变化。
- 卡片答案键只由检索结束后的评分函数读取；不进入入库、检索参数或 reader 提示。
- Reader 复用 Harness 的既有凭据，在内存中直连 DeepSeek 官方 API，模型 `deepseek-flash`；**不声称通过 Harness 宿主运行**。同一官方作答契约、temperature=0、thinking disabled、输出上限 2400；每臂 92 次成功、0 失败、0 重试、0 长度截断，共 442130 tokens。另有一次 16 tokens 的连通性探测。
- 首先各跑 8 题连通冒烟，完整运行重用相同内容指纹的 16 份缓存，没有重复支付这些答卷。完整阶段每臂并发 4；两个初始冒烟臂曾同时运行，总并发上限为 8。

## 实跑结果

| 指标 | 当前主线前缀摘录 | 新增 query 摘录 |
|---|---:|---:|
| 标注引文完整保留数（有效原文引文共 681 条） | 38 / 681 | 113 / 681 |
| 引文保留率，微平均 | 5.58% | 16.59% |
| 引文保留率，按题宏平均 | 5.17% | 17.11% |
| 真实 reader 的官方**规则层**平均覆盖率 | 20.29% | 33.22% |
| 仅覆盖轴达到该题阈值 | 2 / 92 | 6 / 92 |
| 完整规则判定 pass / review / fail | 0 / 19 / 73 | 4 / 36 / 52 |
| Reader 可定位引文 | 223 | 243 |
| Reader 不可定位引文（也计入 invalid，非两条） | 0 | 1 |
| 当前主线原生 recall p50，顺序实跑 | 15.91 ms | 38.15 ms |
| 平均装入节点数 | 4.57 | 5.60 |

初始两轮检索与主线移植后的引文保留读数一致。真实回答的规则覆盖逐题对照为 **41 胜 / 41 平 / 10 负**。92 题共享少量章节，不等于 92 个独立样本，本报告不宣称统计显著。初始查询版 p50 为 65.92 / 63.75 ms；精确计数复用后当前主线顺序复跑为 38.15 ms，前缀版为 15.91 ms。所有计时只是本机描述性读数，不能当作稳定服务 SLA。

查询片段并不保证下游模型零错误：504 份实际摘录逐一按 `cg.get(id)["content"]` 和返回区间重建，全部一致；但新 reader 的一条引文未能在原文中定位，原始答卷及判分保留。75 道适用反编造轴的题两臂均未触发其关键词规则，不代表已经完成语义层编造审查。

## 验证

| 验证 | 最终结果 |
|---|---|
| 新增运行守卫 | 提交版 12 通过 / 0 失败，含 400 组 Unicode 预算/位置检查与 Unicode 分类边界；初始版为 11 项 |
| 真实 stdio MCP | mdcg_recall 与 cg(read) 两个入口均返回相关原文及位置 |
| 定点变异 | 6 / 6 被指定断言捕获，0 异常/0 SKIP；恢复后提交版 12 项通过，源文件未变 |
| 已有前缀摘录守卫 | 6 / 6 通过 |
| 相关回归 | 冻结实验版 13 / 13 模块通过，0 SKIP；含读隔离、生命周期、RRF、读缓存与子进程编码；当前主线完整回归以 PR CI 为准 |
| 独立离线复跑包 | 原始包为 11 项守卫；提交包在新目录应用补丁后 12 项守卫通过；184 份已有答卷离线重算与原读数一致，0 API 调用 |
| 静态检查 | 文档映射、相对链接、工作区索引、显式编码、本机路径与发布件七项政策门禁通过；单列，不算运行测试 |
| 新增分支全量 CI | 以本 PR 对应 head 的 GitHub Actions 为准；PR #168 的绿灯不能替代本分支验证 |

第一次批量回归将辅助目录误命名为 Windows 保留设备名 aux，被既有生产路径守卫拒绝；改为普通目录 sidecar 后 13 项复跑通过，未放宽生产断言。初始错误日志在本地验证目录保留。

### CI 集成补证

首次主线集成的完整 CI（head `5721eeac`）实际为 **458/462 通过、4 失败、7 SKIP**，未当作全绿：新增参数漏登 `op_table` 已补齐；沙箱与审核会话两项回归采用上游 `d6e8c837` 修复；既有生态测试将 Windows 分隔符拼接改为 `os.path.join`。没有修改 CI 判据或删掉失败断言。

定点复跑：参数表对账 29/29、沙箱 9/9、审核归因 10/10，新增守卫 12/12、变异 6/6。Linux（WSL Python 3.13.12）跨域组装入口退出 0；该既有测试仍打印库存盘点 680/686 差异，未将库存盘点当作已通过指标。同步后的两臂各 92 题材料与功能包逐项一致，仅排除上述入库时间元数据，未重新调用 reader。最终全量状态以 PR 当前 head 为准；[集成记录](query_excerpt_20261013/ci-integration.json)与 ZIP 的 integration/ 保留本轮读数。

## 复跑

```bash
python -X utf8 tests/test_query_excerpt.py
python -X utf8 tests/test_query_excerpt.py --mutate
git clone https://github.com/FuRongJun-1999/hive-memory-bench.git ../hive-memory-bench
git -C ../hive-memory-bench checkout f4509d7282f82982af5de9c8fe71863fc95b38cb
git worktree add --detach ../dsh-memory-base 9c5d946aef17f756f07053f7f386483015f626cc
python -X utf8 scripts/bench_query_excerpt_hive.py retrieve --repo ../dsh-memory-base --bench ../hive-memory-bench --strategy prefix --output results/prefix.json
python -X utf8 scripts/bench_query_excerpt_hive.py retrieve --bench ../hive-memory-bench --strategy query --output results/query.json
python -X utf8 scripts/bench_query_excerpt_hive.py reader --bench ../hive-memory-bench --input results/prefix.json --output results/prefix-answers
python -X utf8 scripts/bench_query_excerpt_hive.py reader --bench ../hive-memory-bench --input results/query.json --output results/query-answers
python -X utf8 scripts/bench_query_excerpt_hive.py score --bench ../hive-memory-bench --input results/prefix.json --answers results/prefix-answers --output results/prefix-score.json
python -X utf8 scripts/bench_query_excerpt_hive.py score --bench ../hive-memory-bench --input results/query.json --answers results/query-answers --output results/query-score.json
```

检索部分仅标准库；评分与读取 Harness YAML 需 PyYAML。reader 需要已有凭据，会产生模型调用；默认仅在内存读取用户目录下的 `.dsh/.credentials.yaml` 中 DEEPSEEK_API_KEY，不打印、不记录请求头。已有答卷可直接离线重算规则分，不需要重复调用模型。重跑 retrieve 请使用新的输出文件名，防止复用旧数据目录。

## 限制

这是公开数据上的真实 reader 对照，加官方**规则层**诊断；未运行双判官锚自证、开放题语义终裁与正式成绩登记，不能称为正式榜单成绩。规则覆盖达标数与最终验收通过数是不同指标，review 也未计作 pass。

本次 1200 估算 token、无额外检索 LLM 的配置，与 #85 的 8000 字材料、问题 LLM 扩展及不同 reader 提示不构成直接胜负比较。它证明本方案相对自己的冻结基线有收益，不能据此声称超过 QMD。

尚未验证其他公开语料、百万条、并发、私域数据。IDF 和原文窗口会增加 CPU 时间，词面相关也可能漏掉反方向证据；保留显式启用，未改全项目默认设置。

原始材料：[汇总](query_excerpt_20261013/summary.json)、[运行守卫与变异日志](query_excerpt_20261013/guards-and-mutations.log)、[评测计划](query_excerpt_20261013/evaluation-plan.md)、[完整原始证据 ZIP](query_excerpt_20261013/raw-evidence.zip)。ZIP 内含两轮检索、逐题规则分、两组 184 份答卷和 SHA256 清单，已逐项校验哈希与 CRC。

主线交付补证：[两臂材料一致性](query_excerpt_20261013/main-integration.json)、[2500 组选择器对照](query_excerpt_20261013/selector-parity.json)、[当前测量版与功能输出一致性](query_excerpt_20261013/optimized-compatibility.json)。最新主线完整检索与离线重评分保存在证据 ZIP 的 integration/。
