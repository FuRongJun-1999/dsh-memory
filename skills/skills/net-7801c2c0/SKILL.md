---
name: net-7801c2c0
description: >-
  选择性确认 / 网络-选择性确认 / TCP SACK——块。用户提到这些词时使用本技能。
  场景：对照：TCP SACK——块确认只重传缺失段（高效丢包恢复）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  参数 received/expected 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["选择性确认", "网络-选择性确认", "TCP SACK——块"]
    when: "参数 received/expected 合法"
    sub: ["① 调用 range"]
    execute: "顺序调用"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：TCP SACK——块确认只重传缺失段（高效丢包恢复）"
---

# 网络-选择性确认（net-7801c2c0）

## When to use

任务「选择性确认」；对照：TCP SACK——块确认只重传缺失段（高效丢包恢复）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

顺序调用

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「网络-选择性确认」
