---
name: os-0f8ed882
description: >-
  命名空间 / 虚拟化-命名空间 / 命名空间隔离 / PID/网。用户提到这些词时使用本技能。
  场景：对照：容器命名空间——PID 视图映射（进程在命名空间内重编号，隔离语义）。
  【不适用】Not for 以下场景：op 非 {lookup, register} 时
license: MIT
compatibility: >-
  op ∈ {lookup, register}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["命名空间", "虚拟化-命名空间", "命名空间隔离", "PID/网"]
    when: "op ∈ {lookup, register}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派"
    not_applicable: ["op 非 {lookup, register} 时"]
  calibration: "对照：容器命名空间——PID 视图映射（进程在命名空间内重编号，隔离语义）"
---

# 虚拟化-命名空间（os-0f8ed882）

## When to use

任务「命名空间」；对照：容器命名空间——PID 视图映射（进程在命名空间内重编号，隔离语义）。

## 克制条款（不适用条件）

op 非 {lookup, register} 时

## How to execute

按 op 分派

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「虚拟化-命名空间」
