---
name: os-9b6ed02c
description: >-
  字符设备 / 设备-字符设备 / OS 设 / 字符设备抽象。用户提到这些词时使用本技能。
  场景：对照：OS 设备驱动——字符设备接口（open/read/write/close，设备即文件）。
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
    trigger_words: ["字符设备", "设备-字符设备", "OS 设", "字符设备抽象"]
    when: "op ∈ {close, open, read, write}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派"
    not_applicable: ["op 非 {close, open, read, write} 时"]
  calibration: "对照：OS 设备驱动——字符设备接口（open/read/write/close，设备即文件）"
---

# 设备-字符设备（os-9b6ed02c）

## When to use

任务「字符设备」；对照：OS 设备驱动——字符设备接口（open/read/write/close，设备即文件）。

## 克制条款（不适用条件）

op 非 {close, open, read, write} 时

## How to execute

按 op 分派

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「设备-字符设备」
