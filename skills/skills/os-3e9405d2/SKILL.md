---
name: os-3e9405d2
description: >-
  RAID条带 / 文件-RAID条带 / RAID 0——数 / 数据条带化。用户提到这些词时使用本技能。
  场景：对照：RAID 0——数据条带化（分块分布，并行 I/O 语义）。
  【不适用】Not for 以下场景：disks 为空/非法时（隐式盲区：返回默认值 [] = 未知行为——不适用）
license: MIT
compatibility: >-
  参数 data/disks 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["RAID条带", "文件-RAID条带", "RAID 0——数", "数据条带化"]
    when: "参数 data/disks 合法"
    sub: ["① 调用 range"]
    execute: "顺序调用"
    not_applicable: ["disks 为空/非法时（隐式盲区：返回默认值 [] = 未知行为——不适用）"]
  calibration: "对照：RAID 0——数据条带化（分块分布，并行 I/O 语义）"
---

# 文件-RAID条带（os-3e9405d2）

## When to use

任务「RAID条带」；对照：RAID 0——数据条带化（分块分布，并行 I/O 语义）。

## 克制条款（不适用条件）

disks 为空/非法时（隐式盲区：返回默认值 [] = 未知行为——不适用）

## How to execute

顺序调用

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「文件-RAID条带」
