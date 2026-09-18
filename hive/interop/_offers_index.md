# 投放索引（机生成，勿手改）

生成时间：2026-09-18T16:54:07

认领方式：写 hive/interop/<iter>/picked.json，或向 hive/interop/_receipts_ledger.tsv 追加引用该 iter 的回执行。
状态含义：offered=已投放待认领；claimed=已认领；escalated=超窗口转内部复核；internal-verified=内部复核通过（via=internal，不当外部 PASS）；superseded=被后继版本顶替（旧结论不得再当有效）。

| iter | branch | commit | 状态 | 认领方式 | 备注 |
|---|---|---|---|---|---|
| iter-t2-disasm-truthy-r12 | task/t2-disasm-truthy-r12 | 233fd52 | internal-verified | internal:ACCEPT |  |
| iter-t3-reach-r6 | task/t3-reach-r6 | 5aa1f6b | superseded |  | r33 自足式复核 REJECT：index_unavailable 出口缺成本；由 r7 接替 |
| iter-t3-reach-r8 | task/t3-reach-r8 | 959d0a3 | internal-verified | internal:ACCEPT |  |
| iter-t3-reach-r7 | task/t3-reach-r7 | 182370b | superseded |  | r34 自足式复核 REJECT：漏计不可读读盘 + 模块级状态串味；由 r8 接替 |
| iter-027-batch-c11 | task/iter-027-batch-c11 | c6b430d | offered |  | 环二 backlog：内部复核 ACCEPT，待编外裁定 |
| iter-100-batch-c100 | task/iter-100-batch-c100 | 85c1a4b | offered |  | 环二 backlog：内部复核 ACCEPT，待编外裁定 |
| iter-104-batch-c104-fix-d1 | task/iter-104-batch-c104-fix-d1 | 7c9b579 | offered |  | 环二 backlog：内部复核 ACCEPT，待编外裁定 |
| iter-115-batch-c115-fix-d1 | task/iter-115-batch-c115-fix-d1 | 1bbc744 | offered |  | 环二 backlog：内部复核 ACCEPT，待编外裁定 |
| iter-131-batch-c131-fix-d1 | task/iter-131-batch-c131-fix-d1 | 75d78d5 | offered |  | 环二 backlog：内部复核 ACCEPT，待编外裁定 |
| iter-136-batch-c136-dual-dual | task/iter-136-batch-c136-dual-dual | f27fa65 | offered |  | 环二 backlog：内部复核 ACCEPT，待编外裁定 |
| iter-142-batch-c142-fix-d1-d2 | task/iter-142-batch-c142-fix-d1-d2 | 20298ae | offered |  | 环二 backlog：内部复核 ACCEPT，待编外裁定 |
| iter-144-batch-c144-fix | task/iter-144-batch-c144-fix | 1109c70 | offered |  | 环二 backlog：内部复核 ACCEPT，待编外裁定 |
| iter-145-batch-c145-fix-d1 | task/iter-145-batch-c145-fix-d1 | d67cbb6 | offered |  | 环二 backlog：内部复核 ACCEPT，待编外裁定 |
| iter-166-batch-c166 | task/iter-166-batch-c166 | 61879df | offered |  | 环二 backlog：内部复核 ACCEPT，待编外裁定 |
| iter-167-batch-c167-fix | task/iter-167-batch-c167-fix | 02cf208 | offered |  | 环二 backlog：内部复核 ACCEPT，待编外裁定 |
| iter-168-batch-c168-fix | task/iter-168-batch-c168-fix | a5adc11 | offered |  | 环二 backlog：内部复核 ACCEPT，待编外裁定 |
| iter-172-batch-c172-fix-d1 | task/iter-172-batch-c172-fix-d1 | 8e5df63 | offered |  | 环二 backlog：内部复核 ACCEPT，待编外裁定 |
| iter-205-batch-c205 | task/iter-205-batch-c205 | 00130c1 | offered |  | 环二 backlog：内部复核 ACCEPT，待编外裁定 |
| iter-209-batch-c209 | task/iter-209-batch-c209 | dad2188 | offered |  | 环二 backlog：内部复核 ACCEPT，待编外裁定 |
| iter-210-batch-c210-fix | task/iter-210-batch-c210-fix | c6a4399 | offered |  | 环二 backlog：内部复核 ACCEPT，待编外裁定 |
| iter-211-batch-c211 | task/iter-211-batch-c211 | 7340d7f | offered |  | 环二 backlog：内部复核 ACCEPT，待编外裁定 |
| iter-212-batch-c212 | task/iter-212-batch-c212 | e465f69 | offered |  | 环二 backlog：内部复核 ACCEPT，待编外裁定 |
| iter-213-batch-c213 | task/iter-213-batch-c213 | 4c073cb | offered |  | 环二 backlog：内部复核 ACCEPT，待编外裁定 |
| iter-214-batch-c214 | task/iter-214-batch-c214 | 3778555 | offered |  | 环二 backlog：内部复核 ACCEPT，待编外裁定 |
| iter-215-batch-c215-fix | task/iter-215-batch-c215-fix | 4006f2c | offered |  | 环二 backlog：内部复核 ACCEPT，待编外裁定 |
| iter-216-batch-c216-fix-d1 | task/iter-216-batch-c216-fix-d1 | 09459b8 | offered |  | 环二 backlog：内部复核 ACCEPT，待编外裁定 |
| iter-217-batch-c217 | task/iter-217-batch-c217 | d82b378 | offered |  | 环二 backlog：内部复核 ACCEPT，待编外裁定 |
| iter-218-batch-c218 | task/iter-218-batch-c218 | 83bb758 | offered |  | 环二 backlog：内部复核 ACCEPT，待编外裁定 |
| iter-219-batch-c219-fix | task/iter-219-batch-c219-fix | 3e94176 | offered |  | 环二 backlog：内部复核 ACCEPT，待编外裁定 |
| iter-220-batch-c220 | task/iter-220-batch-c220 | 21f6069 | offered |  | 环二 backlog：内部复核 ACCEPT，待编外裁定 |
| iter-221-batch-c221-fix | task/iter-221-batch-c221-fix | 8f17776 | offered |  | 环二 backlog：内部复核 ACCEPT，待编外裁定 |
| iter-222-batch-c222-fix | task/iter-222-batch-c222-fix | 6a9c21b | offered |  | 环二 backlog：内部复核 ACCEPT，待编外裁定 |
| iter-223-batch-c223 | task/iter-223-batch-c223 | 7a6c75a | offered |  | 环二 backlog：内部复核 ACCEPT，待编外裁定 |
| iter-224-batch-c224 | task/iter-224-batch-c224 | e602409 | offered |  | 环二 backlog：内部复核 ACCEPT，待编外裁定 |
| iter-225-batch-c225-fix | task/iter-225-batch-c225-fix | ffab717 | offered |  | 环二 backlog：内部复核 ACCEPT，待编外裁定 |
| iter-226-batch-c226-fix | task/iter-226-batch-c226-fix | 0971e64 | offered |  | 环二 backlog：内部复核 ACCEPT，待编外裁定 |
| iter-227-batch-c227 | task/iter-227-batch-c227 | b7f4bc2 | offered |  | 环二 backlog：内部复核 ACCEPT，待编外裁定 |
| iter-228-batch-c228 | task/iter-228-batch-c228 | 2fdb43e | offered |  | 环二 backlog：内部复核 ACCEPT，待编外裁定 |
| iter-230-batch-c230 | task/iter-230-batch-c230 | 28adf94 | offered |  | 环二 backlog：内部复核 ACCEPT，待编外裁定 |
| iter-231-batch-c231-fix | task/iter-231-batch-c231-fix | 087c747 | offered |  | 环二 backlog：内部复核 ACCEPT，待编外裁定 |
| iter-232-batch-c232 | task/iter-232-batch-c232 | 94513e9 | offered |  | 环二 backlog：内部复核 ACCEPT，待编外裁定 |

待处理：37 条
