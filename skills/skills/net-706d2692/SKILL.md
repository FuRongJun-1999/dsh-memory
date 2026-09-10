---
name: net-706d2692
description: >-
  组播 / 网络-组播 / IP 组 / 离开 / 组内广播 / join 加。用户提到这些词时使用本技能。
  场景：对照：IP 组播——组成员加入/离开/组内广播（成员管理）。
  【不适用】Not for 以下场景：op 非 {join, leave, send} 时
license: MIT
compatibility: >-
  op ∈ {join, leave, send}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["组播", "网络-组播", "IP 组", "离开", "组内广播", "join 加"]
    when: "op ∈ {join, leave, send}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派"
    not_applicable: ["op 非 {join, leave, send} 时"]
  calibration: "对照：IP 组播——组成员加入/离开/组内广播（成员管理）"
---

# 网络-组播（net-706d2692）

## When to use

任务「组播」；对照：IP 组播——组成员加入/离开/组内广播（成员管理）。

## 克制条款（不适用条件）

op 非 {join, leave, send} 时

## How to execute

按 op 分派

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「网络-组播」
