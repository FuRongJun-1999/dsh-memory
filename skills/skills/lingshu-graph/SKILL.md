---
name: lingshu-graph
description: >-
  灵枢白箱条件单元域入口：图算法与图数据库（117 单元 / 17 子域）。触发词：图算法、图数据库、最短路、遍历、图查询、条件路由图、图可视化。
  场景：任务命中本域任一子域主题时使用。先查下方路由表定位单元，语义模糊时经 mdcg cg op=route 路由；
  单元正文在 units/<slug>/SKILL.md 按需回读（KCCS 四要素在各单元内，不随本入口加载）。
  【不适用】Not for：任务不属于本域任何子域主题（负路由）；跨域方向判断改用 designer-perspective 元技能。
license: MIT
allowed-tools: Read Grep Glob Bash
metadata:
  version: "2.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-09-11"
  domain: graph
  unit-count: 117
  kccs:
    trigger_words: ["图算法", "图查询", "图存储", "条件路由图", "图可视化", "图遍历", "图安全", "图监控", "运维", "图嵌入", "图持久化", "图索引"]
    when: "任务命中本域单元的生效条件（子域主题见路由表；单元级条件在 units/<slug>/SKILL.md）"
    sub: ["图算法", "图查询", "图存储", "条件路由图", "图可视化", "图遍历", "图安全", "图监控", "运维", "图嵌入", "图持久化", "图索引", "图分布式", "图动态", "图学习", "图时序", "图灵枢"]
    execute: "① 定位：路由表或 mdcg cg op=route → ② 回读 units/<slug>/SKILL.md → ③ 按单元 KCCS 执行 → ④ 验证交灵枢 MCP（编译/运行/断言）"
    not_applicable: ["任务不属于本域任何子域主题（负路由）", "需要全局观测/资格裁决时改用 designer-perspective（元技能不执行操作层）"]
---

# 灵枢 图算法与图数据库域入口（lingshu-graph）

白箱条件单元域入口（v2.0 层级化重组）。本域 117 个单元收纳于 `units/`，
本文件只承载**子域路由**——description 进上下文做域级命中，单元按需回读。

## 路由表（子域 → 单元）

| 子域 | 数 | 单元（slug · 中文主题）|
|---|---|---|
| 图算法 | 36 | `graph-0de12477` · 图算法-最小生成树（graph-0de12477）、`graph-12cd830a` · 图算法-树重心（graph-12cd830a）、`graph-185f2cd2` · 图算法-图同构（graph-185f2cd2）、`graph-1b266557` · 图算法-图着色（graph-1b266557）、`graph-2465dff8` · 图算法-汉密尔顿路径（graph-2465dff8）、`graph-34a1dba7` · 图算法-最大团（graph-34a1dba7）、`graph-3755dbc9` · 图算法-最小割（graph-3755dbc9）、`graph-37a45d4b` · 图算法-最大流（graph-37a45d4b）、`graph-3aa4c941` · 图算法-拓扑排序（graph-3aa4c941）、`graph-3d34961d` · 图算法-最近公共祖先（graph-3d34961d）、`graph-44e56113` · 图算法-弦图判定（graph-44e56113）、`graph-4b363727` · 图算法-旅行商（graph-4b363727）、`graph-52e6e216` · 图算法-连通分量（graph-52e6e216）、`graph-54ac2988` · 图算法-PageRank（graph-54ac2988）、`graph-5ca34baa` · 图算法-社区发现（graph-5ca34baa）、`graph-6dc48231` · 图算法-独立集（graph-6dc48231）、`graph-7412a7cb` · 图算法-路径规划（graph-7412a7cb）、`graph-7fe49de7` · 图算法-最大割（graph-7fe49de7）、`graph-80d82194` · 图算法-二分图判定（graph-80d82194）、`graph-873fb505` · 图算法-桥检测（graph-873fb505）、`graph-8d7b569b` · 图算法-二分匹配（graph-8d7b569b）、`graph-9507aff7` · 图算法-欧拉路径（graph-9507aff7）、`graph-96b85e1f` · 图算法-强连通分量（graph-96b85e1f）、`graph-97b22f09` · 图算法-介数中心性（graph-97b22f09）、`graph-add9a63b` · 图算法-生成树计数（graph-add9a63b）、`graph-baf61b7c` · 图算法-传递闭包（graph-baf61b7c）、`graph-c407bbed` · 图算法-增量更新（graph-c407bbed）、`graph-d0677ce1` · 图算法-节点相似度（graph-d0677ce1）、`graph-d1289b39` · 图算法-度中心性（graph-d1289b39）、`graph-d15f39b1` · 图算法-支配集（graph-d15f39b1）、`graph-ddf563ff` · 图算法-三角形计数（graph-ddf563ff）、`graph-de00894f` · 图算法-聚类系数（graph-de00894f）、`graph-e2905c20` · 图算法-度序列（graph-e2905c20）、`graph-ea3150e7` · 图算法-图直径（graph-ea3150e7）、`graph-ee9f6dfa` · 图算法-顶点覆盖（graph-ee9f6dfa）、`graph-f1891287` · 图算法-割点（graph-f1891287） |
| 图查询 | 21 | `graph-04cd431b` · 图查询-时序查询（graph-04cd431b）、`graph-2508389f` · 图查询-执行计划（graph-2508389f）、`graph-276d554d` · 图查询-游标遍历（graph-276d554d）、`graph-2d455cd8` · 图查询-模式匹配（graph-2d455cd8）、`graph-3d255ed4` · 图查询-条件链（graph-3d255ed4）、`graph-40b7bf61` · 图查询-路径过滤（graph-40b7bf61）、`graph-5f894c05` · 图查询-模式路径（graph-5f894c05）、`graph-7186924a` · 图查询-标签计数（graph-7186924a）、`graph-7becedf0` · 图查询-分布式查询（graph-7becedf0）、`graph-8e920d5d` · 图查询-邻居查询（graph-8e920d5d）、`graph-8eb38e3d` · 图查询-查询缓存（graph-8eb38e3d）、`graph-95b86a8b` · 图查询-导出子图（graph-95b86a8b）、`graph-9f6665c0` · 图查询-模糊匹配（graph-9f6665c0）、`graph-a125d282` · 图查询-可达性判定（graph-a125d282）、`graph-b00e3dc7` · 图查询-子图匹配（graph-b00e3dc7）、`graph-c5815621` · 图查询-聚合（graph-c5815621）、`graph-d4dd02f4` · 图查询-标签约束（graph-d4dd02f4）、`graph-d9d3934c` · 图查询-双层邻居（graph-d9d3934c）、`graph-df1ebb63` · 图查询-物化视图（graph-df1ebb63）、`graph-e4f8cefd` · 图查询-路径计数（graph-e4f8cefd）、`graph-fd51ece9` · 图查询-正则路径（graph-fd51ece9） |
| 图存储 | 17 | `graph-19a6a301` · 图存储-快照版本（graph-19a6a301）、`graph-2041fa98` · 图存储-一致性快照（graph-2041fa98）、`graph-299f4a32` · 图存储-分区分片（graph-299f4a32）、`graph-3721be1c` · 图存储-增量备份（graph-3721be1c）、`graph-3a4a984c` · 图存储-图规范化（graph-3a4a984c）、`graph-42187d5d` · 图存储-边索引（graph-42187d5d）、`graph-4361c60e` · 图存储-一致性检查（graph-4361c60e）、`graph-656e7bd4` · 图存储-主从复制（graph-656e7bd4）、`graph-85bf101e` · 图存储-邻接表CSR（graph-85bf101e）、`graph-86583b09` · 图存储-压缩编码（graph-86583b09）、`graph-8727827c` · 图存储-备份恢复（graph-8727827c）、`graph-89b11de0` · 图存储-图差分（graph-89b11de0）、`graph-94582f69` · 图存储-节点边（graph-94582f69）、`graph-b33a7662` · 图存储-图合并（graph-b33a7662）、`graph-c1d5687b` · 图存储-属性边（graph-c1d5687b）、`graph-f1bb5aa1` · 图存储-批量操作（graph-f1bb5aa1）、`graph-fca3d129` · 图存储-事务（graph-fca3d129） |
| 条件路由图 | 9 | `graph-2461bc41` · 条件路由图-条件分解（graph-2461bc41）、`graph-2fddf701` · 条件路由图-条件合并（graph-2fddf701）、`graph-3bc2eb69` · 条件路由图-条件回溯（graph-3bc2eb69）、`graph-3f920bf3` · 条件路由图-查询（graph-3f920bf3）、`graph-580dadcd` · 条件路由图-对接（graph-580dadcd）、`graph-7c38fbf3` · 条件路由图-信任传播（graph-7c38fbf3）、`graph-d40691ca` · 条件路由图-信息差收敛（graph-d40691ca）、`graph-f56fa220` · 条件路由图-映射（graph-f56fa220）、`graph-fd6a81ab` · 条件路由图-信任聚合（graph-fd6a81ab） |
| 图可视化 | 8 | `graph-06e2b1f2` · 图可视化-节点标签（graph-06e2b1f2）、`graph-3e18a380` · 图可视化-节点大小（graph-3e18a380）、`graph-9833cfda` · 图可视化-视口变换（graph-9833cfda）、`graph-9aa8a3f4` · 图可视化-社区着色（graph-9aa8a3f4）、`graph-b77fa05a` · 图可视化-邻接矩阵（graph-b77fa05a）、`graph-f055b2ea` · 图可视化-分层布局（graph-f055b2ea）、`graph-f729034f` · 图可视化-环形布局（graph-f729034f）、`graph-f8c4a59e` · 图可视化-力导向布局（graph-f8c4a59e） |
| 图遍历 | 5 | `graph-0e564e68` · 图遍历-BFS（graph-0e564e68）、`graph-1d73b597` · 图遍历-路径（graph-1d73b597）、`graph-3b69a528` · 图遍历-路径枚举（graph-3b69a528）、`graph-53fbfef5` · 图遍历-最短路径（graph-53fbfef5）、`graph-7376a24e` · 图遍历-加权最短（graph-7376a24e） |
| 图安全 | 4 | `graph-8650548b` · 图安全-审计日志（graph-8650548b）、`graph-c4a59d80` · 图安全-权限控制（graph-c4a59d80）、`graph-ccad55f1` · 图安全-加密存储（graph-ccad55f1）、`graph-eb4ac7dd` · 图安全-租户隔离（graph-eb4ac7dd） |
| 图监控 | 3 | `graph-10d58a7b` · 图监控-健康检查（graph-10d58a7b）、`graph-33385442` · 图监控-度分布（graph-33385442）、`graph-c4676460` · 图监控-指标统计（graph-c4676460） |
| 运维 | 3 | `graph-1b707621` · 运维-在线扩容（graph-1b707621）、`graph-a49ef4f0` · 运维-慢查询定位（graph-a49ef4f0）、`graph-fd02d934` · 运维-读写分离（graph-fd02d934） |
| 图嵌入 | 2 | `graph-b76d15ee` · 图嵌入-节点特征（graph-b76d15ee）、`graph-b912fc3b` · 图嵌入-图特征（graph-b912fc3b） |
| 图持久化 | 2 | `graph-72ce5342` · 图持久化-文件（graph-72ce5342）、`graph-7dc36de7` · 图持久化-序列化（graph-7dc36de7） |
| 图索引 | 2 | `graph-d43b387a` · 图索引-布隆过滤（graph-d43b387a）、`graph-d724ea18` · 图索引-属性索引（graph-d724ea18） |
| 图分布式 | 1 | `graph-f748a63f` · 图分布式-一致性哈希（graph-f748a63f） |
| 图动态 | 1 | `graph-5cb7fbdf` · 图动态-边活跃度（graph-5cb7fbdf） |
| 图学习 | 1 | `graph-a5cd04ae` · 图学习-相似推荐（graph-a5cd04ae） |
| 图时序 | 1 | `graph-947355f7` · 图时序-时间窗口（graph-947355f7） |
| 图灵枢 | 1 | `graph-d74d36fd` · 图灵枢-导出（graph-d74d36fd） |

## 路由流程

1. **词面命中**：任务含子域/单元触发词 → 直接查上表回读对应单元
2. **语义模糊**：`mdcg cg op=route intent=<任务描述>` → 返回建议能力名与知识
3. **回读**：`units/<单元slug>/SKILL.md`（含 KCCS 四要素与验证样例）
4. **验证**：灵枢 MCP 工具物理执行（编译/运行/断言裁决），技能说"怎么验证"、MCP 负责"真去跑"

## 真源与纪律

- 知识真源：`md_cg/whitebox_kb/wisdom/graph_db_units.py`（KCCS 四要素唯一真源）
- 本包为生成投影（2026-09-11 层级化重组 v2.0）：单元内容零改动，仅目录收纳 + 域入口新增
- 触发词全量索引：`md_cg/whitebox_kb/wisdom/trigger_words_index.json`
- 变更须在真源层修改后重新导出（R6 变更验证），勿直接改本目录单元
