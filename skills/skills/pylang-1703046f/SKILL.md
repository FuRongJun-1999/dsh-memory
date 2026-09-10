---
name: pylang-1703046f
description: >-
  复合赋值求值 / 复合赋值-执行内核 / mini_python.。用户提到这些词时使用本技能。
  场景：对照：mini_python.py aug_assign 语句内核（CPython += 真除/零除语义）。
  【不适用】Not for 以下场景：未知 op 抛 ValueError；下标/属性目标不在本单元范围
license: MIT
compatibility: >-
  op 为 '+=' '-=' '*=' '/=' 之一；rhs 与 cur 类型相容
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["复合赋值求值", "复合赋值-执行内核", "mini_python."]
    when: "op 为 '+=' '-=' '*=' '/=' 之一；rhs 与 cur 类型相容"
    sub: ["① 四值分派；② '/=' 零除报错；③ 字符串 '+=' 拼接"]
    execute: "条件分派；算术求值"
    not_applicable: ["未知 op 抛 ValueError；下标/属性目标不在本单元范围"]
  calibration: "对照：mini_python.py aug_assign 语句内核（CPython += 真除/零除语义）"
---

# 复合赋值-执行内核（pylang-1703046f）

## When to use

任务「复合赋值求值」；对照：mini_python.py aug_assign 语句内核（CPython += 真除/零除语义）。

## 克制条款（不适用条件）

未知 op 抛 ValueError；下标/属性目标不在本单元范围

## How to execute

条件分派；算术求值

## Verification

- 单元样例 5 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「复合赋值-执行内核」
