---
name: os-f9bf8dd4
description: >-
  写时复制 / 内存-写时复制 / OS 内 / 写共享页 → 复制新页再。用户提到这些词时使用本技能。
  场景：对照：OS 内存——写时复制（fork 共享页写时复制，节省物理内存）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  shared_set.discard 可用
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["写时复制", "内存-写时复制", "OS 内", "写共享页 → 复制新页再"]
    when: "shared_set.discard 可用"
    sub: ["① 条件判定 ② 结果处理"]
    execute: "写时复制：写共享页 → 复制新页再写（原页保留，fork COW 语义）"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：OS 内存——写时复制（fork 共享页写时复制，节省物理内存）"
---

# 内存-写时复制（os-f9bf8dd4）

## When to use

任务「写时复制」；对照：OS 内存——写时复制（fork 共享页写时复制，节省物理内存）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

写时复制：写共享页 → 复制新页再写（原页保留，fork COW 语义）

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「内存-写时复制」
