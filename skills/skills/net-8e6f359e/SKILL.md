---
name: net-8e6f359e
description: >-
  包过滤 / 网络-包过滤 / ACL——按 / rules 规。用户提到这些词时使用本技能。
  场景：对照：ACL——按五元组规则过滤（允许/拒绝）。
  【不适用】Not for 以下场景：op 非 {filter, rules, stats} 时
license: MIT
compatibility: >-
  op ∈ {filter, rules, stats}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["包过滤", "网络-包过滤", "ACL——按", "rules 规"]
    when: "op ∈ {filter, rules, stats}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派；循环迭代；顺序调用"
    not_applicable: ["op 非 {filter, rules, stats} 时"]
  calibration: "对照：ACL——按五元组规则过滤（允许/拒绝）"
---

# 网络-包过滤（net-8e6f359e）

## When to use

任务「包过滤」；对照：ACL——按五元组规则过滤（允许/拒绝）。

## 克制条款（不适用条件）

op 非 {filter, rules, stats} 时

## How to execute

按 op 分派；循环迭代；顺序调用

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「网络-包过滤」
