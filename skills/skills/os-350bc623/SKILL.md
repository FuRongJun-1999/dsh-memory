---
name: os-350bc623
description: >-
  内存映射 / 文件-内存映射 / OS mmap——文 / map 映。用户提到这些词时使用本技能。
  场景：对照：OS mmap——文件映射到内存（读偏移/写回）。
  【不适用】Not for 以下场景：op 非 {map, read, write} 时
license: MIT
compatibility: >-
  op ∈ {map, read, write}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["内存映射", "文件-内存映射", "OS mmap——文", "map 映"]
    when: "op ∈ {map, read, write}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派；顺序调用"
    not_applicable: ["op 非 {map, read, write} 时"]
  calibration: "对照：OS mmap——文件映射到内存（读偏移/写回）"
---

# 文件-内存映射（os-350bc623）

## When to use

任务「内存映射」；对照：OS mmap——文件映射到内存（读偏移/写回）。

## 克制条款（不适用条件）

op 非 {map, read, write} 时

## How to execute

按 op 分派；顺序调用

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「文件-内存映射」
