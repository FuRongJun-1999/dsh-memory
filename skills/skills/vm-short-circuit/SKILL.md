---
name: vm-short-circuit
description: >-
  短路求值 / VM-短路求值 / 逻辑表达式 / 与=左假不求右 / 返回 。用户提到这些词时使用本技能。
  场景：对照：逻辑表达式（v0.2 短路跳转字节码）的 VM 执行端——与/或短路，右侧仅必要时求值。
  【不适用】Not for 以下场景：left 为空/非法时；op 非 {且, 或} 时
license: MIT
compatibility: >-
  op ∈ {且, 或}；left/right 为操作数值
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["短路求值", "VM-短路求值", "逻辑表达式", "与=左假不求右", "返回 "]
    when: "op ∈ {且, 或}；left/right 为操作数值"
    sub: ["① 且/或短路判定 ② 需要时求右值 ③ 返回 (结果, 右是否求值)"]
    execute: "且左假直返 False、或左真直返 True——右侧仅必要时求值"
    not_applicable: ["left 为空/非法时；op 非 {且, 或} 时"]
  calibration: "对照：逻辑表达式（v0.2 短路跳转字节码）的 VM 执行端——与/或短路，右侧仅必要时求值"
---

# VM-短路求值（vm-short-circuit）

## When to use

任务「短路求值」；对照：逻辑表达式（v0.2 短路跳转字节码）的 VM 执行端——与/或短路，右侧仅必要时求值。

## 克制条款（不适用条件）

left 为空/非法时；op 非 {且, 或} 时

## How to execute

且左假直返 False、或左真直返 True——右侧仅必要时求值

## Verification

- 单元样例 7 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「VM-短路求值」
