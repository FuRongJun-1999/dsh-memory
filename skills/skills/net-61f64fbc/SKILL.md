---
name: net-61f64fbc
description: >-
  令牌桶 / 网络-令牌桶限速 / 网络限速——令牌桶 / 令牌桶限速 / 按速率补令牌——流量整形。用户提到这些词时使用本技能。
  场景：对照：网络限速——令牌桶（速率补令牌，容量封顶）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  参数 tokens/capacity/rate/elapsed 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["令牌桶", "网络-令牌桶限速", "网络限速——令牌桶", "令牌桶限速", "按速率补令牌——流量整形"]
    when: "参数 tokens/capacity/rate/elapsed 合法"
    sub: ["① 调用 min"]
    execute: "顺序调用"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：网络限速——令牌桶（速率补令牌，容量封顶）"
---

# 网络-令牌桶限速（net-61f64fbc）

## When to use

任务「令牌桶」；对照：网络限速——令牌桶（速率补令牌，容量封顶）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

顺序调用

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「网络-令牌桶限速」
