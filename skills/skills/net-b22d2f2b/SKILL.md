---
name: net-b22d2f2b
description: >-
  内容协商 / 网络-内容协商 / HTTP 内 / Accept 头。用户提到这些词时使用本技能。
  场景：对照：HTTP 内容协商——Accept 头匹配可用类型（q 剥离）。
  【不适用】Not for 以下场景：op 非 {match} 时
license: MIT
compatibility: >-
  op ∈ {match}；a.strip 可用
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["内容协商", "网络-内容协商", "HTTP 内", "Accept 头"]
    when: "op ∈ {match}；a.strip 可用"
    sub: ["① op 分支处理"]
    execute: "按 op 分派；循环迭代"
    not_applicable: ["op 非 {match} 时"]
  calibration: "对照：HTTP 内容协商——Accept 头匹配可用类型（q 剥离）"
---

# 网络-内容协商（net-b22d2f2b）

## When to use

任务「内容协商」；对照：HTTP 内容协商——Accept 头匹配可用类型（q 剥离）。

## 克制条款（不适用条件）

op 非 {match} 时

## How to execute

按 op 分派；循环迭代

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「网络-内容协商」
