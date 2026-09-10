---
name: browser-cf3c47f0
description: >-
  会话恢复 / 浏览器-会话恢复 / 浏览器会话恢复——标签页 / 恢复 / save 保。用户提到这些词时使用本技能。
  场景：对照：浏览器会话恢复——标签页快照保存/恢复（崩溃恢复）。
  【不适用】Not for 以下场景：op 非 {restore, save} 时
license: MIT
compatibility: >-
  op ∈ {restore, save}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["会话恢复", "浏览器-会话恢复", "浏览器会话恢复——标签页", "恢复", "save 保"]
    when: "op ∈ {restore, save}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派；顺序调用"
    not_applicable: ["op 非 {restore, save} 时"]
  calibration: "对照：浏览器会话恢复——标签页快照保存/恢复（崩溃恢复）"
---

# 浏览器-会话恢复（browser-cf3c47f0）

## When to use

任务「会话恢复」；对照：浏览器会话恢复——标签页快照保存/恢复（崩溃恢复）。

## 克制条款（不适用条件）

op 非 {restore, save} 时

## How to execute

按 op 分派；顺序调用

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「浏览器-会话恢复」
