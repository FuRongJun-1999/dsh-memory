---
name: os-462f3ed4
description: >-
  优先级继承 / 进程-优先级继承 / 优先级继承——持锁者继承 / wait 等。用户提到这些词时使用本技能。
  场景：对照：优先级继承——持锁者继承等待者高优先（防反转）。
  【不适用】Not for 以下场景：op 非 {inherit, restore, wait} 时
license: MIT
compatibility: >-
  op ∈ {inherit, restore, wait}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["优先级继承", "进程-优先级继承", "优先级继承——持锁者继承", "wait 等"]
    when: "op ∈ {inherit, restore, wait}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派；顺序调用"
    not_applicable: ["op 非 {inherit, restore, wait} 时"]
  calibration: "对照：优先级继承——持锁者继承等待者高优先（防反转）"
---

# 进程-优先级继承（os-462f3ed4）

## When to use

任务「优先级继承」；对照：优先级继承——持锁者继承等待者高优先（防反转）。

## 克制条款（不适用条件）

op 非 {inherit, restore, wait} 时

## How to execute

按 op 分派；顺序调用

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「进程-优先级继承」
