---
name: net-686632aa
description: >-
  链路预算 / 网络-链路预算 / measure 记。用户提到这些词时使用本技能。
  场景：对照：蓝牙 RSSI——信号质量分级与距离估算（链路预算）。
  【不适用】Not for 以下场景：op 非 {distance, measure, quality} 时
license: MIT
compatibility: >-
  op ∈ {distance, measure, quality}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["链路预算", "网络-链路预算", "measure 记"]
    when: "op ∈ {distance, measure, quality}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派；顺序调用"
    not_applicable: ["op 非 {distance, measure, quality} 时"]
  calibration: "对照：蓝牙 RSSI——信号质量分级与距离估算（链路预算）"
---

# 网络-链路预算（net-686632aa）

## When to use

任务「链路预算」；对照：蓝牙 RSSI——信号质量分级与距离估算（链路预算）。

## 克制条款（不适用条件）

op 非 {distance, measure, quality} 时

## How to execute

按 op 分派；顺序调用

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「网络-链路预算」
