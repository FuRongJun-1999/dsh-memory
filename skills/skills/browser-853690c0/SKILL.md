---
name: browser-853690c0
description: >-
  内置聊天 / 浏览器-内置聊天 / send 发。用户提到这些词时使用本技能。
  场景：对照：AI Chat——内置对话发送/回复/历史。
  【不适用】Not for 以下场景：op 非 {history, reply, send} 时
license: MIT
compatibility: >-
  op ∈ {history, reply, send}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["内置聊天", "浏览器-内置聊天", "send 发"]
    when: "op ∈ {history, reply, send}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派；顺序调用"
    not_applicable: ["op 非 {history, reply, send} 时"]
  calibration: "对照：AI Chat——内置对话发送/回复/历史"
---

# 浏览器-内置聊天（browser-853690c0）

## When to use

任务「内置聊天」；对照：AI Chat——内置对话发送/回复/历史。

## 克制条款（不适用条件）

op 非 {history, reply, send} 时

## How to execute

按 op 分派；顺序调用

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「浏览器-内置聊天」
