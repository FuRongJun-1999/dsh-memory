---
name: net-240a14ec
description: >-
  时隙 / 网络-时隙 / assign 分。用户提到这些词时使用本技能。
  场景：对照：TDMA——时分多址时隙分配/轮转/归属。
  【不适用】Not for 以下场景：op 非 {assign, next, owner} 时
license: MIT
compatibility: >-
  op ∈ {assign, next, owner}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["时隙", "网络-时隙", "assign 分"]
    when: "op ∈ {assign, next, owner}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派；循环迭代"
    not_applicable: ["op 非 {assign, next, owner} 时"]
  calibration: "对照：TDMA——时分多址时隙分配/轮转/归属"
---

# 网络-时隙（net-240a14ec）

## When to use

任务「时隙」；对照：TDMA——时分多址时隙分配/轮转/归属。

## 克制条款（不适用条件）

op 非 {assign, next, owner} 时

## How to execute

按 op 分派；循环迭代

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「网络-时隙」
