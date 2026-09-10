---
name: browser-87b0ce80
description: >-
  在线状态 / 浏览器-在线状态 / offline 事 / set 设。用户提到这些词时使用本技能。
  场景：对照：navigator.onLine + online/offline 事件（网络状态监测）。
  【不适用】Not for 以下场景：op 非 {events, get, set} 时
license: MIT
compatibility: >-
  op ∈ {events, get, set}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["在线状态", "浏览器-在线状态", "offline 事", "set 设"]
    when: "op ∈ {events, get, set}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派；顺序调用"
    not_applicable: ["op 非 {events, get, set} 时"]
  calibration: "对照：navigator.onLine + online/offline 事件（网络状态监测）"
---

# 浏览器-在线状态（browser-87b0ce80）

## When to use

任务「在线状态」；对照：navigator.onLine + online/offline 事件（网络状态监测）。

## 克制条款（不适用条件）

op 非 {events, get, set} 时

## How to execute

按 op 分派；顺序调用

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「浏览器-在线状态」
