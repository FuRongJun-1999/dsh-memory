---
name: net-6eb37f63
description: >-
  链路利用率 / 网络-链路利用率 / 链路利用率——已用 / 容量采样 / sample 记。用户提到这些词时使用本技能。
  场景：对照：链路利用率——已用/容量采样（平均与峰值）。
  【不适用】Not for 以下场景：op 非 {peak, sample, util} 时
license: MIT
compatibility: >-
  op ∈ {peak, sample, util}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["链路利用率", "网络-链路利用率", "链路利用率——已用", "容量采样", "sample 记"]
    when: "op ∈ {peak, sample, util}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派；顺序调用"
    not_applicable: ["op 非 {peak, sample, util} 时"]
  calibration: "对照：链路利用率——已用/容量采样（平均与峰值）"
---

# 网络-链路利用率（net-6eb37f63）

## When to use

任务「链路利用率」；对照：链路利用率——已用/容量采样（平均与峰值）。

## 克制条款（不适用条件）

op 非 {peak, sample, util} 时

## How to execute

按 op 分派；顺序调用

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「网络-链路利用率」
