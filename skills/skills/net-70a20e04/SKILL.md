---
name: net-70a20e04
description: >-
  RTT平滑 / 网络-RTT平滑 / TCP RTT——EWM / RTT 平 / sample 加。用户提到这些词时使用本技能。
  场景：对照：TCP RTT——EWMA 加权平滑估值（α=0.125）。
  【不适用】Not for 以下场景：op 非 {get, sample} 时
license: MIT
compatibility: >-
  op ∈ {get, sample}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["RTT平滑", "网络-RTT平滑", "TCP RTT——EWM", "RTT 平", "sample 加"]
    when: "op ∈ {get, sample}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派；顺序调用"
    not_applicable: ["op 非 {get, sample} 时"]
  calibration: "对照：TCP RTT——EWMA 加权平滑估值（α=0.125）"
---

# 网络-RTT平滑（net-70a20e04）

## When to use

任务「RTT平滑」；对照：TCP RTT——EWMA 加权平滑估值（α=0.125）。

## 克制条款（不适用条件）

op 非 {get, sample} 时

## How to execute

按 op 分派；顺序调用

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「网络-RTT平滑」
