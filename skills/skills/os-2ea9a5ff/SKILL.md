---
name: os-2ea9a5ff
description: >-
  资源限额 / 系统-资源限额 / OS ulimit——进 / ulimit / 进程资源限制。用户提到这些词时使用本技能。
  场景：对照：OS ulimit——进程资源限制（软限制设置/查询）。
  【不适用】Not for 以下场景：op 非 {check, get, set} 时
license: MIT
compatibility: >-
  op ∈ {check, get, set}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["资源限额", "系统-资源限额", "OS ulimit——进", "ulimit", "进程资源限制"]
    when: "op ∈ {check, get, set}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派；顺序调用"
    not_applicable: ["op 非 {check, get, set} 时"]
  calibration: "对照：OS ulimit——进程资源限制（软限制设置/查询）"
---

# 系统-资源限额（os-2ea9a5ff）

## When to use

任务「资源限额」；对照：OS ulimit——进程资源限制（软限制设置/查询）。

## 克制条款（不适用条件）

op 非 {check, get, set} 时

## How to execute

按 op 分派；顺序调用

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「系统-资源限额」
