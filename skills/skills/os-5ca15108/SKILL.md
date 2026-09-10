---
name: os-5ca15108
description: >-
  僵尸进程 / 进程-僵尸进程 / reap 回 / exit 退。用户提到这些词时使用本技能。
  场景：对照：僵尸进程——exit 未回收/reap 回收（wait 语义）。
  【不适用】Not for 以下场景：op 非 {exit, reap, zombies} 时
license: MIT
compatibility: >-
  op ∈ {exit, reap, zombies}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["僵尸进程", "进程-僵尸进程", "reap 回", "exit 退"]
    when: "op ∈ {exit, reap, zombies}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派；顺序调用"
    not_applicable: ["op 非 {exit, reap, zombies} 时"]
  calibration: "对照：僵尸进程——exit 未回收/reap 回收（wait 语义）"
---

# 进程-僵尸进程（os-5ca15108）

## When to use

任务「僵尸进程」；对照：僵尸进程——exit 未回收/reap 回收（wait 语义）。

## 克制条款（不适用条件）

op 非 {exit, reap, zombies} 时

## How to execute

按 op 分派；顺序调用

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「进程-僵尸进程」
