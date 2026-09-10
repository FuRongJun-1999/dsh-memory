---
name: os-0205cf9b
description: >-
  加密文件系统 / 安全-加密文件系统 / OS 安 / write 加。用户提到这些词时使用本技能。
  场景：对照：OS 安全——加密文件系统（透明加解密存储）。
  【不适用】Not for 以下场景：op 非 {read, write} 时
license: MIT
compatibility: >-
  op ∈ {read, write}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["加密文件系统", "安全-加密文件系统", "OS 安", "write 加"]
    when: "op ∈ {read, write}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派；顺序调用"
    not_applicable: ["op 非 {read, write} 时"]
  calibration: "对照：OS 安全——加密文件系统（透明加解密存储）"
---

# 安全-加密文件系统（os-0205cf9b）

## When to use

任务「加密文件系统」；对照：OS 安全——加密文件系统（透明加解密存储）。

## 克制条款（不适用条件）

op 非 {read, write} 时

## How to execute

按 op 分派；顺序调用

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「安全-加密文件系统」
