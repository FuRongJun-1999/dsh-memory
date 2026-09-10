---
name: pylang-38e8f9ff
description: >-
  迭代协议 / 迭代器-协议 / Python 迭 / 迭代器协议 / __iter__/__n。用户提到这些词时使用本技能。
  场景：对照：Python 迭代器协议（iter/next/StopIteration 耗尽语义）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  参数 data 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["迭代协议", "迭代器-协议", "Python 迭", "迭代器协议", "__iter__/__n"]
    when: "参数 data 合法"
    sub: ["① 调用 iter；② 调用 next"]
    execute: "循环迭代；顺序调用"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：Python 迭代器协议（iter/next/StopIteration 耗尽语义）"
---

# 迭代器-协议（pylang-38e8f9ff）

## When to use

任务「迭代协议」；对照：Python 迭代器协议（iter/next/StopIteration 耗尽语义）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

循环迭代；顺序调用

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「迭代器-协议」
