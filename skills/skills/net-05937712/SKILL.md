---
name: net-05937712
description: >-
  NTP同步 / 网络-NTP同步 / NTP——时 / NTP 同 / offset 时。用户提到这些词时使用本技能。
  场景：对照：NTP——时间偏移与往返时延计算（时间同步）。
  【不适用】Not for 以下场景：op 非 {offset, roundtrip} 时
license: MIT
compatibility: >-
  op ∈ {offset, roundtrip}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["NTP同步", "网络-NTP同步", "NTP——时", "NTP 同", "offset 时"]
    when: "op ∈ {offset, roundtrip}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派；顺序调用"
    not_applicable: ["op 非 {offset, roundtrip} 时"]
  calibration: "对照：NTP——时间偏移与往返时延计算（时间同步）"
---

# 网络-NTP同步（net-05937712）

## When to use

任务「NTP同步」；对照：NTP——时间偏移与往返时延计算（时间同步）。

## 克制条款（不适用条件）

op 非 {offset, roundtrip} 时

## How to execute

按 op 分派；顺序调用

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「网络-NTP同步」
