---
name: graph-7c38fbf3
description: >-
  信任传播 / 条件路由图-信任传播 / 条件路由图——信任传播 / 信任沿边衰减传播。用户提到这些词时使用本技能。
  场景：对照：条件路由图——信任传播（沿边衰减，多跳信任累积）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  参数 graph/node/trust/decay 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["信任传播", "条件路由图-信任传播", "条件路由图——信任传播", "信任沿边衰减传播"]
    when: "参数 graph/node/trust/decay 合法"
    sub: ["① 调用 round"]
    execute: "循环迭代；顺序调用"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：条件路由图——信任传播（沿边衰减，多跳信任累积）"
---

# 条件路由图-信任传播（graph-7c38fbf3）

## When to use

任务「信任传播」；对照：条件路由图——信任传播（沿边衰减，多跳信任累积）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

循环迭代；顺序调用

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「条件路由图-信任传播」
