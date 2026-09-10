---
name: pylang-a02eac31
description: >-
  装饰器 / 装饰器-定义使用 / Python 装 / 包装函数 / 包装 / 记录调用并转发原函数 / 演示 / @timer 装。用户提到这些词时使用本技能。
  场景：对照：Python 装饰器（@timer 包装增强，不改原函数逻辑）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  参数 fn 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["装饰器", "装饰器-定义使用", "Python 装", "包装函数", "包装", "记录调用并转发原函数", "演示", "@timer 装"]
    when: "参数 fn 合法"
    sub: ["① 调用 fn"]
    execute: "顺序调用"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：Python 装饰器（@timer 包装增强，不改原函数逻辑）"
---

# 装饰器-定义使用（pylang-a02eac31）

## When to use

任务「装饰器」；对照：Python 装饰器（@timer 包装增强，不改原函数逻辑）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

顺序调用

## Verification

- 单元样例 1 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「装饰器-定义使用」
