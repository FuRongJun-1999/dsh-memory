---
name: os-41d14544
description: >-
  孤儿进程 / 进程-孤儿进程 / adopt 收。用户提到这些词时使用本技能。
  场景：对照：孤儿进程——父亡子被 init（PID 1）收养。
  【不适用】Not for 以下场景：op 非 {adopt, orphaned, parent} 时
license: MIT
compatibility: >-
  op ∈ {adopt, orphaned, parent}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["孤儿进程", "进程-孤儿进程", "adopt 收"]
    when: "op ∈ {adopt, orphaned, parent}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派；顺序调用"
    not_applicable: ["op 非 {adopt, orphaned, parent} 时"]
  calibration: "对照：孤儿进程——父亡子被 init（PID 1）收养"
---

# 进程-孤儿进程（os-41d14544）

## When to use

任务「孤儿进程」；对照：孤儿进程——父亡子被 init（PID 1）收养。

## 克制条款（不适用条件）

op 非 {adopt, orphaned, parent} 时

## How to execute

按 op 分派；顺序调用

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「进程-孤儿进程」
