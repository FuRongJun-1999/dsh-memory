---
name: pylang-482be62b
description: >-
  捕获异常 / 异常-捕获 / except / 异常捕获。用户提到这些词时使用本技能。
  场景：对照：Python try/except（异常匹配 etype → 处理器；无异常 → ok）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  risky 为可调用；etype 为异常类型；handler 为异常处理器
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["捕获异常", "异常-捕获", "except", "异常捕获"]
    when: "risky 为可调用；etype 为异常类型；handler 为异常处理器"
    sub: ["① 尝试执行 ② 捕获指定异常 ③ 转交处理器"]
    execute: "try risky() → except etype → handler(err)"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：Python try/except（异常匹配 etype → 处理器；无异常 → ok）"
---

# 异常-捕获（pylang-482be62b）

## When to use

任务「捕获异常」；对照：Python try/except（异常匹配 etype → 处理器；无异常 → ok）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

try risky() → except etype → handler(err)

## Verification

- 单元样例 1 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「异常-捕获」
