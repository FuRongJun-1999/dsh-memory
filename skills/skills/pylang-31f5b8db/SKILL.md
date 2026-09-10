---
name: pylang-31f5b8db
description: >-
  协议接口 / 类型-协议接口 / Python 协 / 协议 / 结构约定。用户提到这些词时使用本技能。
  场景：对照：Python 协议——结构约定（具 __len__ 即序列协议，鸭子类型）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  参数 obj/methods 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["协议接口", "类型-协议接口", "Python 协", "协议", "结构约定"]
    when: "参数 obj/methods 合法"
    sub: ["① 调用 all；② 调用 hasattr"]
    execute: "顺序调用"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：Python 协议——结构约定（具 __len__ 即序列协议，鸭子类型）"
---

# 类型-协议接口（pylang-31f5b8db）

## When to use

任务「协议接口」；对照：Python 协议——结构约定（具 __len__ 即序列协议，鸭子类型）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

顺序调用

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「类型-协议接口」
