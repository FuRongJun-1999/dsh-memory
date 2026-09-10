---
name: net-14102d54
description: >-
  广播风暴 / 网络-广播风暴 / 广播风暴抑制——计数 / 速率 / 超阈阻塞 / count 计。用户提到这些词时使用本技能。
  场景：对照：广播风暴抑制——计数/速率/超阈阻塞（环路风暴防护）。
  【不适用】Not for 以下场景：op 非 {block, count, rate} 时
license: MIT
compatibility: >-
  op ∈ {block, count, rate}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["广播风暴", "网络-广播风暴", "广播风暴抑制——计数", "速率", "超阈阻塞", "count 计"]
    when: "op ∈ {block, count, rate}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派"
    not_applicable: ["op 非 {block, count, rate} 时"]
  calibration: "对照：广播风暴抑制——计数/速率/超阈阻塞（环路风暴防护）"
---

# 网络-广播风暴（net-14102d54）

## When to use

任务「广播风暴」；对照：广播风暴抑制——计数/速率/超阈阻塞（环路风暴防护）。

## 克制条款（不适用条件）

op 非 {block, count, rate} 时

## How to execute

按 op 分派

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「网络-广播风暴」
