---
name: net-88ad93a6
description: >-
  网络切片 / 网络-网络切片 / 5G 网 / create 创。用户提到这些词时使用本技能。
  场景：对照：5G 网络切片——按服务隔离带宽资源（准入控制）。
  【不适用】Not for 以下场景：op 非 {admit, create} 时
license: MIT
compatibility: >-
  op ∈ {admit, create}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["网络切片", "网络-网络切片", "5G 网", "create 创"]
    when: "op ∈ {admit, create}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派"
    not_applicable: ["op 非 {admit, create} 时"]
  calibration: "对照：5G 网络切片——按服务隔离带宽资源（准入控制）"
---

# 网络-网络切片（net-88ad93a6）

## When to use

任务「网络切片」；对照：5G 网络切片——按服务隔离带宽资源（准入控制）。

## 克制条款（不适用条件）

op 非 {admit, create} 时

## How to execute

按 op 分派

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「网络-网络切片」
