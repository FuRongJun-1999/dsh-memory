---
name: compiler-38378ac7
description: >-
  编译程序 / 编译-程序 / 程序语句列表 → 字节码 / 条件=跳转 / 外部校准 / 段内相对跳转目标需加全局。用户提到这些词时使用本技能。
  场景：对照：C2 顶层编译——术曰作用域/道德经指令/止停止。
  【不适用】Not for 以下场景：kind 非 {COND, INSTR, 术曰, 止} 时
license: MIT
compatibility: >-
  kind ∈ {COND, INSTR, 术曰, 止}；s.replace 可用
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["编译程序", "编译-程序", "程序语句列表 → 字节码", "条件=跳转", "外部校准", "段内相对跳转目标需加全局"]
    when: "kind ∈ {COND, INSTR, 术曰, 止}；s.replace 可用"
    sub: ["1 kind 分支处理"]
    execute: "按 op 分派；循环迭代；顺序调用"
    not_applicable: ["kind 非 {COND, INSTR, 术曰, 止} 时"]
  calibration: "对照：C2 顶层编译——术曰作用域/道德经指令/止停止"
---

# 编译-程序（compiler-38378ac7）

## When to use

任务「编译程序」；对照：C2 顶层编译——术曰作用域/道德经指令/止停止。

## 克制条款（不适用条件）

kind 非 {COND, INSTR, 术曰, 止} 时

## How to execute

按 op 分派；循环迭代；顺序调用

## Verification

- 单元样例 2 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「编译-程序」
