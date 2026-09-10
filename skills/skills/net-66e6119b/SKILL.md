---
name: net-66e6119b
description: >-
  DHCP租约 / 网络-DHCP租约 / DHCP / offer 分。用户提到这些词时使用本技能。
  场景：对照：DHCP 协议——地址租约 offer/renew/release 生命周期。
  【不适用】Not for 以下场景：op 非 {offer, release, renew} 时；state 非 {free} 时
license: MIT
compatibility: >-
  op ∈ {offer, release, renew}；state ∈ {free}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["DHCP租约", "网络-DHCP租约", "DHCP", "offer 分"]
    when: "op ∈ {offer, release, renew}；state ∈ {free}"
    sub: ["① op 分支处理；2 state 分支处理"]
    execute: "按 op 分派；循环迭代；顺序调用"
    not_applicable: ["op 非 {offer, release, renew} 时；state 非 {free} 时"]
  calibration: "对照：DHCP 协议——地址租约 offer/renew/release 生命周期"
---

# 网络-DHCP租约（net-66e6119b）

## When to use

任务「DHCP租约」；对照：DHCP 协议——地址租约 offer/renew/release 生命周期。

## 克制条款（不适用条件）

op 非 {offer, release, renew} 时；state 非 {free} 时

## How to execute

按 op 分派；循环迭代；顺序调用

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「网络-DHCP租约」
