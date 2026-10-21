# 归档 · 2026-10-21 · 未接线的回答规范锚点

## 为什么在这里

`answer_spec_anchor.py`（88 行）在 2026-10-21 的可达性普查里是**唯一一个「谁都不达」的生产模块**：

- 全仓 import 0 处（`grep -rn "answer_spec_anchor" lingshu-src/ --include=*.py` 只命中它自己）
- 没有任何测试引用它（`grep -rn answer_spec_anchor lingshu-src --include=test_*.py` 空）
- 全文只是一个常量 `ANSWER_SPEC_LLM_BLOCK` + `build_answer_spec_block()`，没有任何调用方

它的设计意图（v1.30「规范即机制」：把回答规范作为 self/anchor 层注入 LLM 系统提示词）在
`设计\源码对标-结论.md` 里作为「未接线设计」登记过；到 2026-10-21 为止仍没有接入口。

## 为什么是归档而不是删除

按用户 2026-10-21 的「三级评估（真跑 / 接溯源发售 / 删）」：它既不在跑，也没有可发售的
对外形态。但它是**设计产物**而非死代码垃圾，直接删会让「这套回答规范到底写没写过」变成
不可考。归档保留了正文，同时把它从生产代码统计与「在链上」分母里移出去。

## 怎么恢复

```powershell
Move-Item D:\wook\lingshu-src\_archive\20261021-未接线\answer_spec_anchor.py `
          D:\wook\lingshu-src\md_cg\whitebox_kb\wisdom\answer_spec_anchor.py
```

恢复后它仍然是「谁都不达」，除非同时补一个真正的注入点（MCP `context` op 或
`mdcg` 的 system-prompt 组装处），并在 `orchestrator/reachability-dispositions.json` 里
把 disposition 改成 `wire` 且写明调用方——门 `gate-reachability-budget.mjs` 会核对那条调用方
是否真的 import 它。
