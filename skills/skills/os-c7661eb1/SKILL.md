---
name: os-c7661eb1
description: >-
  文件系统调用 / 系统调用-文件分派 / OS 系 / read / write / close 文 / 系统调用 / open/read/wr。用户提到这些词时使用本技能。
  场景：对照：OS 系统调用——open/read/write/close 文件操作（fd 表分派）。
  【不适用】Not for 以下场景：op 非 {close, open, read, write} 时
license: MIT
compatibility: >-
  op ∈ {close, open, read, write}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["文件系统调用", "系统调用-文件分派", "OS 系", "read", "write", "close 文", "系统调用", "open/read/wr"]
    when: "op ∈ {close, open, read, write}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派；顺序调用"
    not_applicable: ["op 非 {close, open, read, write} 时"]
  calibration: "对照：OS 系统调用——open/read/write/close 文件操作（fd 表分派）"
---

# 系统调用-文件分派（os-c7661eb1）

## When to use

任务「文件系统调用」；对照：OS 系统调用——open/read/write/close 文件操作（fd 表分派）。

## 克制条款（不适用条件）

op 非 {close, open, read, write} 时

## How to execute

按 op 分派；顺序调用

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「系统调用-文件分派」
