---
name: net-b4151e9a
description: >-
  CSMA退避 / 网络-CSMA退避 / CSMA / CD——碰 / CSMA 退 / collision 碰。用户提到这些词时使用本技能。
  场景：对照：CSMA/CD——碰撞指数退避（2^n 上限 1024，重传清零）。
  【不适用】Not for 以下场景：op 非 {collision, reset, wait} 时
license: MIT
compatibility: >-
  op ∈ {collision, reset, wait}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["CSMA退避", "网络-CSMA退避", "CSMA", "CD——碰", "CSMA 退", "collision 碰"]
    when: "op ∈ {collision, reset, wait}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派；顺序调用"
    not_applicable: ["op 非 {collision, reset, wait} 时"]
  calibration: "对照：CSMA/CD——碰撞指数退避（2^n 上限 1024，重传清零）"
---

# 网络-CSMA退避（net-b4151e9a）

## When to use

任务「CSMA退避」；对照：CSMA/CD——碰撞指数退避（2^n 上限 1024，重传清零）。

## 克制条款（不适用条件）

op 非 {collision, reset, wait} 时

## How to execute

按 op 分派；顺序调用

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「网络-CSMA退避」
