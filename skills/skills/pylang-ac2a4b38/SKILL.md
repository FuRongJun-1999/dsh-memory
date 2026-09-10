---
name: pylang-ac2a4b38
description: >-
  异常传播 / 异常-传播 / Python 异 / 内层函数抛错 → 中间不 / 内层 / 主动抛出指定异常 / 中层 / 不捕获。用户提到这些词时使用本技能。
  场景：对照：Python 异常传播（内层 raise → 中间不处理 → 外层捕获）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  参数 call_chain/etype/msg 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["异常传播", "异常-传播", "Python 异", "内层函数抛错 → 中间不", "内层", "主动抛出指定异常", "中层", "不捕获"]
    when: "参数 call_chain/etype/msg 合法"
    sub: ["① 调用 etype；② 调用 inner；③ 调用 mid"]
    execute: "顺序调用"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：Python 异常传播（内层 raise → 中间不处理 → 外层捕获）"
---

# 异常-传播（pylang-ac2a4b38）

## When to use

任务「异常传播」；对照：Python 异常传播（内层 raise → 中间不处理 → 外层捕获）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

顺序调用

## Verification

- 单元样例 1 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「异常-传播」
