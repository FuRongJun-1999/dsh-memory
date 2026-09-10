---
name: browser-a2d9b0b0
description: >-
  游戏手柄 / 浏览器-游戏手柄 / connect 连。用户提到这些词时使用本技能。
  场景：对照：Gamepad——手柄连接/按键/摇杆。
  【不适用】Not for 以下场景：op 非 {axis, button, connect} 时
license: MIT
compatibility: >-
  op ∈ {axis, button, connect}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["游戏手柄", "浏览器-游戏手柄", "connect 连"]
    when: "op ∈ {axis, button, connect}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派"
    not_applicable: ["op 非 {axis, button, connect} 时"]
  calibration: "对照：Gamepad——手柄连接/按键/摇杆"
---

# 浏览器-游戏手柄（browser-a2d9b0b0）

## When to use

任务「游戏手柄」；对照：Gamepad——手柄连接/按键/摇杆。

## 克制条款（不适用条件）

op 非 {axis, button, connect} 时

## How to execute

按 op 分派

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「浏览器-游戏手柄」
