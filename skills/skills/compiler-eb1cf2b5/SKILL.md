---
name: compiler-eb1cf2b5
description: >-
  信任流分析 / 编译-信任流分析 / 德=信任累积。用户提到这些词时使用本技能。
  场景：对照：德=信任累积（v0.2 信任语义）的编译期数据流——与取min、或取max、非取补；字面量完全可信、未收录名不可信。
  【不适用】Not for 以下场景：env 中未收录的名称按不可信（0.0）处理；不修改 env 内容
license: MIT
compatibility: >-
  expr 为表达式树（tuple 操作节点/字符串名/字面量）；env 为名→信任值映射
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["信任流分析", "编译-信任流分析", "德=信任累积"]
    when: "expr 为表达式树（tuple 操作节点/字符串名/字面量）；env 为名→信任值映射"
    sub: ["① 操作节点递归传播 ② 名称查 env ③ 字面量视为完全可信"]
    execute: "AND=min / OR=max / NOT=1-t 递归归约"
    not_applicable: ["env 中未收录的名称按不可信（0.0）处理；不修改 env 内容"]
  calibration: "对照：德=信任累积（v0.2 信任语义）的编译期数据流——与取min、或取max、非取补；字面量完全可信、未收录名不可信"
---

# 编译-信任流分析（compiler-eb1cf2b5）

## When to use

任务「信任流分析」；对照：德=信任累积（v0.2 信任语义）的编译期数据流——与取min、或取max、非取补；字面量完全可信、未收录名不可信。

## 克制条款（不适用条件）

env 中未收录的名称按不可信（0.0）处理；不修改 env 内容

## How to execute

AND=min / OR=max / NOT=1-t 递归归约

## Verification

- 单元样例 7 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「编译-信任流分析」
