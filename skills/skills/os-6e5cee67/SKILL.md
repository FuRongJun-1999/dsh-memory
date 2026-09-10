---
name: os-6e5cee67
description: >-
  系统调用过滤 / 安全-系统调用过滤 / OS 安 / seccomp——白。用户提到这些词时使用本技能。
  场景：对照：OS 安全——seccomp 系统调用过滤（白名单，沙箱）。
  【不适用】Not for 以下场景：op 非 {allow, check} 时
license: MIT
compatibility: >-
  op ∈ {allow, check}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["系统调用过滤", "安全-系统调用过滤", "OS 安", "seccomp——白"]
    when: "op ∈ {allow, check}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派"
    not_applicable: ["op 非 {allow, check} 时"]
  calibration: "对照：OS 安全——seccomp 系统调用过滤（白名单，沙箱）"
---

# 安全-系统调用过滤（os-6e5cee67）

## When to use

任务「系统调用过滤」；对照：OS 安全——seccomp 系统调用过滤（白名单，沙箱）。

## 克制条款（不适用条件）

op 非 {allow, check} 时

## How to execute

按 op 分派

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「安全-系统调用过滤」
