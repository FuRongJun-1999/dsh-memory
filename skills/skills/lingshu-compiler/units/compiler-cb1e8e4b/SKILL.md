---
name: compiler-cb1e8e4b
description: >-
  变量监视 / 调试-变量监视 / C4 调 / 监视名在符号表求值——调。用户提到这些词时使用本技能。
  场景：对照：C4 调试器变量监视（watch 名 → 当前值，未知为 None）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  参数 expr/symbols 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["变量监视", "调试-变量监视", "C4 调", "监视名在符号表求值——调"]
    when: "参数 expr/symbols 合法"
    sub: []
    execute: "变量监视：监视名在符号表求值（未知名 → None）——调试器监视窗"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：C4 调试器变量监视（watch 名 → 当前值，未知为 None）"
---

# 调试-变量监视（compiler-cb1e8e4b）

## When to use

任务「变量监视」；对照：C4 调试器变量监视（watch 名 → 当前值，未知为 None）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

变量监视：监视名在符号表求值（未知名 → None）——调试器监视窗

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「调试-变量监视」
