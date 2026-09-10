---
name: net-3bdf9d9d
description: >-
  多径传输 / 网络-多径传输 / MPTCP 多。用户提到这些词时使用本技能。
  场景：对照：MPTCP 多径传输——多子流并行，选最少发送。
  【不适用】Not for 以下场景：paths 为空/非法时；op 非 {add, send, stats} 时
license: MIT
compatibility: >-
  op ∈ {add, send, stats}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["多径传输", "网络-多径传输", "MPTCP 多"]
    when: "op ∈ {add, send, stats}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派；顺序调用"
    not_applicable: ["paths 为空/非法时；op 非 {add, send, stats} 时"]
  calibration: "对照：MPTCP 多径传输——多子流并行，选最少发送"
---

# 网络-多径传输（net-3bdf9d9d）

## When to use

任务「多径传输」；对照：MPTCP 多径传输——多子流并行，选最少发送。

## 克制条款（不适用条件）

paths 为空/非法时；op 非 {add, send, stats} 时

## How to execute

按 op 分派；顺序调用

## Verification

- 单元样例 5 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「网络-多径传输」
