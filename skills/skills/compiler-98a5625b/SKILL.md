---
name: compiler-98a5625b
description: >-
  条件断点 / 调试-条件断点 / C4 调 / set 设。用户提到这些词时使用本技能。
  场景：对照：C4 调试器——条件断点（条件满足才暂停）。
  【不适用】Not for 以下场景：op 非 {hit, set} 时
license: MIT
compatibility: >-
  op ∈ {hit, set}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["条件断点", "调试-条件断点", "C4 调", "set 设"]
    when: "op ∈ {hit, set}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派；顺序调用"
    not_applicable: ["op 非 {hit, set} 时"]
  calibration: "对照：C4 调试器——条件断点（条件满足才暂停）"
---

# 调试-条件断点（compiler-98a5625b）

## When to use

任务「条件断点」；对照：C4 调试器——条件断点（条件满足才暂停）。

## 克制条款（不适用条件）

op 非 {hit, set} 时

## How to execute

按 op 分派；顺序调用

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「调试-条件断点」
