---
name: pylang-f2f40090
description: >-
  文件读取 / 工具-文件读取 / Python 文 / 按行 / read 读。用户提到这些词时使用本技能。
  场景：对照：Python 文件读取——读全部/按行（splitlines）。
  【不适用】Not for 以下场景：op 非 {lines, read} 时
license: MIT
compatibility: >-
  op ∈ {lines, read}；content.splitlines 可用
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["文件读取", "工具-文件读取", "Python 文", "按行", "read 读"]
    when: "op ∈ {lines, read}；content.splitlines 可用"
    sub: ["① op 分支处理"]
    execute: "按 op 分派"
    not_applicable: ["op 非 {lines, read} 时"]
  calibration: "对照：Python 文件读取——读全部/按行（splitlines）"
---

# 工具-文件读取（pylang-f2f40090）

## When to use

任务「文件读取」；对照：Python 文件读取——读全部/按行（splitlines）。

## 克制条款（不适用条件）

op 非 {lines, read} 时

## How to execute

按 op 分派

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「工具-文件读取」
