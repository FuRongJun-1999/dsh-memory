# BM25 稀疏同步复跑说明

日期：2026-10-12。

生产代码、测试、数据生成器及逐条结果都在同一个 PR 中。性能基线为 `dcb8fbf4148f727a5b4de1bd0737e14000935857`，已包含上一轮块维护优化。本轮比较写后候选资格重判与统计同步，不重复计入上一轮收益。

## 使用 Git 检出

先检出 PR #160，再在其仓库根准备冻结基线和新输出目录：

```powershell
gh pr checkout 160 --repo FuRongJun-1999/dsh-memory
git worktree add --detach ../bm25-frozen dcb8fbf4148f727a5b4de1bd0737e14000935857
python -X utf8 -m md_cg.test_bm25
python -X utf8 -m md_cg.test_bm25_incremental
python -X utf8 -m md_cg.test_bm25_sparse_sync
python -X utf8 -m md_cg.test_bm25_sparse_mutations --output ../sparse-mutations.json
python -X utf8 -m md_cg.bench_bm25_sparse_sync --baseline ../bm25-frozen --workspace ../sparse-1000 --count 1000 --rounds 12 --output ../sparse-1000.json
```

上述检出步骤需要网络与 GitHub 访问；检出完成后，核心配对 benchmark 可离线运行。`workspace`、变异输出和结果路径每次使用新名称。完整万条/十万条命令、BEIR 命令与原始结果索引见 [优化报告](bm25_sparse_sync_20261012.md)。

## 使用离线源码 ZIP

准备当前源码与冻结基线两个 Git archive ZIP，分别解压为相邻的 `current/`、`frozen/`。先按随包 `SHA256SUMS.txt` 校验 ZIP，并记录 ZIP comment 中的原始提交 SHA。完整 Python 与 Git 需预先安装；源码包不携带解释器。

benchmark 会记录 `git rev-parse HEAD`。没有 `.git` 的归档可分别建立本地快照，无需账户、远端或网络。在包含两个目录的父目录执行：

```powershell
git -C current init -q
git -C current add .
git -C current -c user.name=OfflineVerifier -c user.email=offline@example.invalid commit -q -m "Offline snapshot"
git -C frozen init -q
git -C frozen add .
git -C frozen -c user.name=OfflineVerifier -c user.email=offline@example.invalid commit -q -m "Offline snapshot"
python -m venv verifier --without-pip
Set-Location current
../verifier/Scripts/python.exe -X utf8 -m md_cg.bench_bm25_sparse_sync --baseline ../frozen --workspace ../verify-1000 --count 1000 --rounds 12 --output ../verify-1000.json
```

这两个本地提交只是运行时的快照身份，**不是原 PR / 基线提交**；原始提交由归档 comment、ZIP SHA256 和结果内四个生产文件的 SHA256 共同核对。在 Windows/Python 3.12 实际解包，使用无 pip、无 numpy/yaml/requests 的环境运行核心 benchmark：61 组查询配对，0 结果差异、0 错误；两个工作进程均安装 socket 拒绝钩子，记录的网络尝试为空。

## 数据与验收边界

- 核心 benchmark 自带确定性合成 Markdown 生成器，输出初始语料清单和 SHA256；随后在两份独立副本上执行同一查询及写入序列。随包 110,000 个 Markdown 是十万均匀与一万变长/变词频的**初始**合成真源，不含私有记忆、运行时密钥或派生索引。
- 预期结果：`status == "passed"`、`paired_queries == 61`、`mismatches == []`、`errors == []`。核对完整融合卡片、原始 BM25 top-50 分数及 matched；退出码 0 以外也须核对这些字段。
- 无第三方依赖只指核心配对 benchmark。CSRE 路径验证需 numpy；BEIR 需预先备齐官方评分器与 SciFact/NFCorpus 数据。源码 ZIP 不打包 BEIR 原始数据或 Python 环境。
- 正式数据是本地回归，未提交官方排行榜。百万条、并发吞吐、共享实例读写及真实私有语料验收未完成；这份离线 smoke 也不代表生产延迟 SLO。
