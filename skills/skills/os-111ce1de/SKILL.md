---
name: os-111ce1de
description: >-
  信号量 / 并发-信号量 / OS 并 / P 减。用户提到这些词时使用本技能。
  场景：对照：OS 并发——信号量 P/V（计数同步，资源耗尽 P 阻塞）。
  【不适用】Not for 以下场景：op 非 {P, V} 时
license: MIT
compatibility: >-
  op ∈ {P, V}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["信号量", "并发-信号量", "OS 并", "P 减"]
    when: "op ∈ {P, V}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派"
    not_applicable: ["op 非 {P, V} 时"]
  calibration: "对照：OS 并发——信号量 P/V（计数同步，资源耗尽 P 阻塞）"
---

# 并发-信号量（os-111ce1de）

## When to use

任务「信号量」；对照：OS 并发——信号量 P/V（计数同步，资源耗尽 P 阻塞）。

## 克制条款（不适用条件）

op 非 {P, V} 时

## How to execute

按 op 分派

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「并发-信号量」
