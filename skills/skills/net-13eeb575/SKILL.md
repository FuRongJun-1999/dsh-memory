---
name: net-13eeb575
description: >-
  前向纠错 / 网络-前向纠错 / parity 异 / blocks 含。用户提到这些词时使用本技能。
  场景：对照：FEC 异或奇偶——校验块生成与缺块恢复。
  【不适用】Not for 以下场景：op 非 {parity, recover} 时
license: MIT
compatibility: >-
  op ∈ {parity, recover}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["前向纠错", "网络-前向纠错", "parity 异", "blocks 含"]
    when: "op ∈ {parity, recover}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派；循环迭代；顺序调用"
    not_applicable: ["op 非 {parity, recover} 时"]
  calibration: "对照：FEC 异或奇偶——校验块生成与缺块恢复"
---

# 网络-前向纠错（net-13eeb575）

## When to use

任务「前向纠错」；对照：FEC 异或奇偶——校验块生成与缺块恢复。

## 克制条款（不适用条件）

op 非 {parity, recover} 时

## How to execute

按 op 分派；循环迭代；顺序调用

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「网络-前向纠错」
