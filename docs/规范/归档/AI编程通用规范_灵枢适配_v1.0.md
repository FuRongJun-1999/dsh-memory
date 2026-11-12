# AI 编程通用规范 · 灵枢项目适配表 v1.0

> 作用：把通用规范里的「空位」填成本项目做法。**只填不改造**——通用条款一个字不改。

| 规范里的空位 | 本项目填什么 |
|---|---|
| 任务总线（第 6/20 条） | 蜂巢：MCP 的 hive_spawn / 命令行 hive submit --spec；宿主自带 subagent 不算等价通道，改用须声明「兜底降级」 |
| 只读直跑（第 20 条例外） | 产物落点=不改仓库/外部状态的本地只读命令（跑门禁、测试、lint 看结论），直跑须留一行「L1 直跑：<命令> — 风险/频次/可逆」 |
| 工作区目录（第 24 条） | WORKSPACE_INDEX.md（由 scripts/workspace_index.py --write 生成；--check 守漂移） |
| 记忆（第 21/25 条） | 大脑库：cg / stg 两个基元；写记忆用 cg(op=write)，读回用 cg(op=read) |
| 收尾归档四件事（第 21 条） | 按 CCG 六要素成文：功能名 / 生效条件 / 子功能 / 执行 / 验证方式 / 不适用条件 |
| 检查与门禁（第 22 条） | discipline-check、cogmap-check、workspace-index-check、publish-artifact-check、python-tests；坏样本=定点变异（--mutate） |
| 发版（第 23 条） | tag 只钉在 4/4 workflow 全绿的提交上；发布说明写清范围与「已知未收口」 |
| 提交与推送（第 19 条） | 只写明确路径；推前核 origin/main..HEAD 逐笔；共享检出里不碰别人未提交的文件 |
| 编码（第 9/12 条） | 跨进程文本一律 UTF-8（显式 encoding + PYTHONUTF8=1，不经 Windows shell）；命令用 argv 列表 |
| 工具名（第 17 条） | MCP 服务名 mdcg；工具名 cg / stg / mdcg_*；任何宿主不加前缀（口径件：docs/mdcg/MCP工具名口径_v1.0.md） |
| 图像与算法（附表 C） | 线稿=darkline.py（Sobel+mean+std*1.5）；色块=contour_semantics；算法权威件登记在 docs/mdcg/ |
| 人设与进展（第 25 条） | 读回：本端纪律注入段（人设与口径）+ 当前任务与最近决定 + 用户最近 10 轮对话 |

## 与现有《工作纪律_认知图条目_v1.1》的关系

- **不合并、不修改**：认知图条目记录「灵枢这份实现怎么做的」；本规范是「可复用的模板」。
- 映射：旧 18 条 → 新 25 条的全覆盖见《AI编程通用规范_自检清单.md》。
- 未来若要合并，只能反过来：认知图条目引用本规范的条目号，不得反向改写本规范。