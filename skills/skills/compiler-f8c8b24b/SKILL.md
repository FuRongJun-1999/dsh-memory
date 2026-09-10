---
name: compiler-f8c8b24b
description: >-
  信息差追踪 / 分析-信息差追踪 / 智能论——信息差追踪 / record 记。用户提到这些词时使用本技能。
  场景：对照：智能论——信息差追踪（编译期信息差分析记录）。
  【不适用】Not for 以下场景：events 为空/非法时；op 非 {latest, max, record} 时
license: MIT
compatibility: >-
  op ∈ {latest, max, record}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["信息差追踪", "分析-信息差追踪", "智能论——信息差追踪", "record 记"]
    when: "op ∈ {latest, max, record}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派；顺序调用"
    not_applicable: ["events 为空/非法时；op 非 {latest, max, record} 时"]
  calibration: "对照：智能论——信息差追踪（编译期信息差分析记录）"
---

# 分析-信息差追踪（compiler-f8c8b24b）

## When to use

任务「信息差追踪」；对照：智能论——信息差追踪（编译期信息差分析记录）。

## 克制条款（不适用条件）

events 为空/非法时；op 非 {latest, max, record} 时

## How to execute

按 op 分派；顺序调用

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「分析-信息差追踪」
