---
name: graph-e2905c20
description: >-
  度序列 / 图算法-度序列 / Havel-Hakimi。用户提到这些词时使用本技能。
  场景：对照：Havel-Hakimi——度序列可图化判定。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  d.sort 可用
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["度序列", "图算法-度序列", "Havel-Hakimi"]
    when: "d.sort 可用"
    sub: ["① 调用 sorted；② 调用 range；③ 调用 len"]
    execute: "循环迭代；顺序调用"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：Havel-Hakimi——度序列可图化判定"
---

# 图算法-度序列（graph-e2905c20）

## When to use

任务「度序列」；对照：Havel-Hakimi——度序列可图化判定。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

循环迭代；顺序调用

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「图算法-度序列」
