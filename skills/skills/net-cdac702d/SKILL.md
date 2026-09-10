---
name: net-cdac702d
description: >-
  校验和 / 网络-校验和 / UDP 校 / 16 位和进位折叠 → 。用户提到这些词时使用本技能。
  场景：对照：网络 UDP——校验和（和取反，接收端校验出错）。
  【不适用】Not for 以下场景：total 越界（Gt）时
license: MIT
compatibility: >-
  参数 data 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["校验和", "网络-校验和", "UDP 校", "16 位和进位折叠 → "]
    when: "参数 data 合法"
    sub: ["① 条件判定 ② 结果处理"]
    execute: "循环迭代"
    not_applicable: ["total 越界（Gt）时"]
  calibration: "对照：网络 UDP——校验和（和取反，接收端校验出错）"
---

# 网络-校验和（net-cdac702d）

## When to use

任务「校验和」；对照：网络 UDP——校验和（和取反，接收端校验出错）。

## 克制条款（不适用条件）

total 越界（Gt）时

## How to execute

循环迭代

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「网络-校验和」
