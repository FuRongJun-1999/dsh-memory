---
name: browser-a4c793a4
description: >-
  Cookie管理 / 网络-Cookie / Cookie。用户提到这些词时使用本技能。
  场景：对照：浏览器网络——Cookie（设置/读取/删除，会话状态保持）。
  【不适用】Not for 以下场景：op 非 {delete, get, set} 时
license: MIT
compatibility: >-
  op ∈ {delete, get, set}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["Cookie管理", "网络-Cookie", "Cookie"]
    when: "op ∈ {delete, get, set}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派"
    not_applicable: ["op 非 {delete, get, set} 时"]
  calibration: "对照：浏览器网络——Cookie（设置/读取/删除，会话状态保持）"
---

# 网络-Cookie（browser-a4c793a4）

## When to use

任务「Cookie管理」；对照：浏览器网络——Cookie（设置/读取/删除，会话状态保持）。

## 克制条款（不适用条件）

op 非 {delete, get, set} 时

## How to execute

按 op 分派

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「网络-Cookie」
