# 投放索引（机生成，勿手改）

生成时间：2026-09-18T16:42:52

认领方式：写 hive/interop/<iter>/picked.json，或向 hive/interop/_receipts_ledger.tsv 追加引用该 iter 的回执行。
状态含义：offered=已投放待认领；claimed=已认领；escalated=超窗口转内部复核；internal-verified=内部复核通过（via=internal，不当外部 PASS）；superseded=被后继版本顶替（旧结论不得再当有效）。

| iter | branch | commit | 状态 | 认领方式 | 备注 |
|---|---|---|---|---|---|
| iter-t2-disasm-truthy-r12 | task/t2-disasm-truthy-r12 | 233fd52 | internal-verified | internal:ACCEPT |  |
| iter-t3-reach-r6 | task/t3-reach-r6 | 5aa1f6b | superseded |  | r33 自足式复核 REJECT：index_unavailable 出口缺成本；由 r7 接替 |
| iter-t3-reach-r8 | task/t3-reach-r8 | 959d0a3 | internal-verified | internal:ACCEPT |  |
| iter-t3-reach-r7 | task/t3-reach-r7 | 182370b | superseded |  | r34 自足式复核 REJECT：漏计不可读读盘 + 模块级状态串味；由 r8 接替 |

待处理：0 条
