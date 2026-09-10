---
name: compiler-aabbd099
description: >-
  死代码消除 / 编译-死代码消除 / 编译优化——死代码消除 / 不可达指令删除。用户提到这些词时使用本技能。
  场景：对照：编译优化——死代码消除（JUMP 后不可达指令删除）。
  【不适用】Not for 以下场景：op 非 {JUMP} 时
license: MIT
compatibility: >-
  op ∈ {JUMP}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["死代码消除", "编译-死代码消除", "编译优化——死代码消除", "不可达指令删除"]
    when: "op ∈ {JUMP}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派；循环迭代"
    not_applicable: ["op 非 {JUMP} 时"]
  calibration: "对照：编译优化——死代码消除（JUMP 后不可达指令删除）"
---

# 编译-死代码消除（compiler-aabbd099）

## When to use

任务「死代码消除」；对照：编译优化——死代码消除（JUMP 后不可达指令删除）。

## 克制条款（不适用条件）

op 非 {JUMP} 时

## How to execute

按 op 分派；循环迭代

## Verification

- 单元样例 2 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「编译-死代码消除」
