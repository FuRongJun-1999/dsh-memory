---
name: net-3434e92f
description: >-
  数据包采样 / 网络-数据包采样 / NetFlow——按 / sample 按。用户提到这些词时使用本技能。
  场景：对照：NetFlow——按采样率抽取数据包（sFlow/NetFlow）。
  【不适用】Not for 以下场景：op 非 {count, rate, sample} 时
license: MIT
compatibility: >-
  op ∈ {count, rate, sample}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["数据包采样", "网络-数据包采样", "NetFlow——按", "sample 按"]
    when: "op ∈ {count, rate, sample}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派"
    not_applicable: ["op 非 {count, rate, sample} 时"]
  calibration: "对照：NetFlow——按采样率抽取数据包（sFlow/NetFlow）"
---

# 网络-数据包采样（net-3434e92f）

## When to use

任务「数据包采样」；对照：NetFlow——按采样率抽取数据包（sFlow/NetFlow）。

## 克制条款（不适用条件）

op 非 {count, rate, sample} 时

## How to execute

按 op 分派

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「网络-数据包采样」
