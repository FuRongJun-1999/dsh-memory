---
name: net-b873d6f7
description: >-
  ICMP探测 / 网络-ICMP探测 / ICMP Echo——p / ICMP / ping 记。用户提到这些词时使用本技能。
  场景：对照：ICMP Echo——ping 往返测量与可达性判定（RTT 阈值）。
  【不适用】Not for 以下场景：op 非 {ping, reply, stats} 时
license: MIT
compatibility: >-
  op ∈ {ping, reply, stats}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["ICMP探测", "网络-ICMP探测", "ICMP Echo——p", "ICMP", "ping 记"]
    when: "op ∈ {ping, reply, stats}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派；顺序调用"
    not_applicable: ["op 非 {ping, reply, stats} 时"]
  calibration: "对照：ICMP Echo——ping 往返测量与可达性判定（RTT 阈值）"
---

# 网络-ICMP探测（net-b873d6f7）

## When to use

任务「ICMP探测」；对照：ICMP Echo——ping 往返测量与可达性判定（RTT 阈值）。

## 克制条款（不适用条件）

op 非 {ping, reply, stats} 时

## How to execute

按 op 分派；顺序调用

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「网络-ICMP探测」
