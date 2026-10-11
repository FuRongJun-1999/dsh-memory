# 中文召回词覆盖实验

`cn_recall_grams` 现有默认取前 16 个去重中文 2-gram。长问题前半段就能用完
额度，后半段的实体可能不进入 LIKE 候选。相关现象见 [Issue #108](https://github.com/FuRongJun-1999/dsh-memory/issues/108)。

本实验在相同额度内改变取词位置，缺省关闭。它是确定性的词面候选策略，不调用
LLM、不增加依赖、不改 Markdown 真源、评分公式、权限过滤或 RRF 融合公式。

## 开启和回退

在启动 MCP server 或 Python 进程前设置：

```powershell
$env:MDCG_CN_GRAMS_COVERAGE = '1'
python -X utf8 -m md_cg.mcp_server
```

Linux/macOS 可用 `MDCG_CN_GRAMS_COVERAGE=1 python3 -X utf8 -m md_cg.mcp_server`。
保留现有 `MDCG_ROOT` 与身份配置；这个开关没有修改库或配置文件的副作用。
取消该变量或设为 `0` 即回退。仅字符串 `1` 开启；`true`、空值及未设都关闭。
`MDCG_CN_GRAMS=0` 优先于本实验，关闭全部中文扩展。

开关登记在配置 registry，并进入热查询缓存键；同实例翻转时不会沿用另一种策略的
缓存。Rust 检索器读取同名开关。两侧共享 `md_cg/query_coverage_cases.tsv` 的期望词序。

## 选择规则

1. 沿用 CJK 基本区、连续串长度至少 4、停用 gram 表。全局去重，重复词归首次出现的段。
2. 不超过额度时，输出与现实现一致。超过额度时，轮流向非空段分配一个名额；短段用完后
   把剩余额度继续分配给其他段。
3. 段内按整数等距位置取词；名额至少两个时包含首尾，只有一个时取中间位置。
   非空段数超过额度时，对段位置也作同样取样，因此不能承诺每段都覆盖。
4. 按原文先后顺序输出选中的词，保持确定性。总数不超过额度，默认仍为 16。

Python 保留 `min_run`、`cap` 入参；`cap<=0` 仍按历史行为返回首个有效词，
**不是不限**。Rust 公共入口与原来相同，固定 `min_run=4/cap=16`。
完整扫描与临时内存为 O(查询长度)，比早停多做预处理；不承诺降低查询延迟。

## 验收

从仓库根运行（安装态可以运行两个测试模块，源码树额外支持 Rust 验收）：

```text
python -X utf8 -m md_cg.test_query_coverage
python -X utf8 -m md_cg.test_query_coverage_mutations
cargo test --manifest-path rust/Cargo.toml --lib
python -X utf8 -m md_cg.bench_query_coverage --fillers 701 --rounds 5 --output coverage.json
```

测试包含基类与生产 `search`、RRF 倒排候选开关、会话过滤、缓存翻转以及真实 MCP stdio
子进程。故障注入只改子进程内存，不改工作区，逐项确认断言能发现对应故障。

合成基准把线索分别放在头部、尾部和短问题中，同库配对运行两种策略；另保留强前缀
干扰对照，展示取词覆盖不能替代相关度排序。原始读数和限制见
[本轮实验记录](../eval/query_coverage_20261011.md)。

## 尚未证明的范围

- 16 个词不能保留所有词；选词集合改变可能让原有前缀关键词落选。
- 首层候选改善不保证最终 top-k、条件门控、图扩散或 QA 答案改善。
- 未取得 #108 的私有 86 题数据库，未复算其公开读数，也未跑真实长对话的 QA 对照。
- 未改变 `GLOBAL_CAP`；强前缀干扰下尾部目标仍可能被相关度截断。
- 尚无标定集证明新策略应默认开启，故 registry 状态保留 `uncalibrated`。
