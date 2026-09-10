---
name: net-d9cb43b0
description: >-
  多宿主 / 网络-多宿主 / 多宿主——多接口轮询选择 / add 添。用户提到这些词时使用本技能。
  场景：对照：多宿主——多接口轮询选择与故障切换（multihoming）。
  【不适用】Not for 以下场景：ifaces 为空/非法时；op 非 {add, failover, select} 时
license: MIT
compatibility: >-
  op ∈ {add, failover, select}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["多宿主", "网络-多宿主", "多宿主——多接口轮询选择", "add 添"]
    when: "op ∈ {add, failover, select}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派；顺序调用"
    not_applicable: ["ifaces 为空/非法时；op 非 {add, failover, select} 时"]
  calibration: "对照：多宿主——多接口轮询选择与故障切换（multihoming）"
---

# 网络-多宿主（net-d9cb43b0）

## When to use

任务「多宿主」；对照：多宿主——多接口轮询选择与故障切换（multihoming）。

## 克制条款（不适用条件）

ifaces 为空/非法时；op 非 {add, failover, select} 时

## How to execute

按 op 分派；顺序调用

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「网络-多宿主」
