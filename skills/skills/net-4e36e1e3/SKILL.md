---
name: net-4e36e1e3
description: >-
  链路聚合 / 网络-链路聚合 / add 加。用户提到这些词时使用本技能。
  场景：对照：链路聚合 bonding——多链路负载均衡+故障切换。
  【不适用】Not for 以下场景：up 为空/非法时；op 非 {add, fail, send} 时
license: MIT
compatibility: >-
  op ∈ {add, fail, send}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["链路聚合", "网络-链路聚合", "add 加"]
    when: "op ∈ {add, fail, send}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派；循环迭代；顺序调用"
    not_applicable: ["up 为空/非法时；op 非 {add, fail, send} 时"]
  calibration: "对照：链路聚合 bonding——多链路负载均衡+故障切换"
---

# 网络-链路聚合（net-4e36e1e3）

## When to use

任务「链路聚合」；对照：链路聚合 bonding——多链路负载均衡+故障切换。

## 克制条款（不适用条件）

up 为空/非法时；op 非 {add, fail, send} 时

## How to execute

按 op 分派；循环迭代；顺序调用

## Verification

- 单元样例 5 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「网络-链路聚合」
