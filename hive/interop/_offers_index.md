# 投放索引（机生成，勿手改）

生成时间：2026-09-18T16:42:41

认领方式：写 hive/interop/<iter>/picked.json，或向 hive/interop/_receipts_ledger.tsv 追加引用该 iter 的回执行。
状态含义：offered=已投放待认领；claimed=已认领；escalated=超窗口转内部复核；internal-verified=内部复核通过（via=internal，不当外部 PASS）；superseded=被后继版本顶替（旧结论不得再当有效）。

| iter | branch | commit | 状态 | 认领方式 | 备注 |
|---|---|---|---|---|---|
| iter-t2-disasm-truthy-r12 | task/t2-disasm-truthy-r12 | 233fd52 | internal-verified | internal:ACCEPT |  |
| iter-t3-reach-r6 | task/t3-reach-r6 | 5aa1f6b | superseded |  | r33 \u81ea\u8db3\u5f0f\u590d\u6838 REJECT\uff1aindex_unavailable \u51fa\u53e3\u7f3a\u6210\u672c\uff1b\u7531 r7 \u63a5\u66ff |
| iter-t3-reach-r8 | task/t3-reach-r8 | 959d0a3 | internal-verified | internal:ACCEPT |  |
| iter-t3-reach-r7 | task/t3-reach-r7 | 182370b | superseded |  | r34 \u81ea\u8db3\u5f0f\u590d\u6838 REJECT\uff1a\u6f0f\u8ba1\u4e0d\u53ef\u8bfb\u8bfb\u76d8 + \u6a21\u5757\u7ea7\u72b6\u6001\u4e32\u5473\uff1b\u7531 r8 \u63a5\u66ff |

待处理：0 条
