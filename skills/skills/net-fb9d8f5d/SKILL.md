---
name: net-fb9d8f5d
description: >-
  端口扫描检测 / 网络-端口扫描检测 / 入侵检测——端口扫描模式 / record 记。用户提到这些词时使用本技能。
  场景：对照：入侵检测——端口扫描模式（多端口快速尝试识别）。
  【不适用】Not for 以下场景：op 非 {check, record} 时
license: MIT
compatibility: >-
  op ∈ {check, record}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["端口扫描检测", "网络-端口扫描检测", "入侵检测——端口扫描模式", "record 记"]
    when: "op ∈ {check, record}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派；顺序调用"
    not_applicable: ["op 非 {check, record} 时"]
  calibration: "对照：入侵检测——端口扫描模式（多端口快速尝试识别）"
---

# 网络-端口扫描检测（net-fb9d8f5d）

## When to use

任务「端口扫描检测」；对照：入侵检测——端口扫描模式（多端口快速尝试识别）。

## 克制条款（不适用条件）

op 非 {check, record} 时

## How to execute

按 op 分派；顺序调用

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「网络-端口扫描检测」
