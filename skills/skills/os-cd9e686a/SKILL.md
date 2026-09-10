---
name: os-cd9e686a
description: >-
  中断向量 / 中断-向量表 / OS 中 / 中断向量表 / IRQ 号。用户提到这些词时使用本技能。
  场景：对照：OS 中断——向量表（IRQ→handler 查表分派，未注册返回 None）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  参数 table/irq 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["中断向量", "中断-向量表", "OS 中", "中断向量表", "IRQ 号"]
    when: "参数 table/irq 合法"
    sub: []
    execute: "中断向量表：IRQ 号 → 处理函数（未注册 → None）"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：OS 中断——向量表（IRQ→handler 查表分派，未注册返回 None）"
---

# 中断-向量表（os-cd9e686a）

## When to use

任务「中断向量」；对照：OS 中断——向量表（IRQ→handler 查表分派，未注册返回 None）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

中断向量表：IRQ 号 → 处理函数（未注册 → None）

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「中断-向量表」
