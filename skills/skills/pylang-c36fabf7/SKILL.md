---
name: pylang-c36fabf7
description: >-
  多态分发 / 面向对象-多态 / Python 多 / 多态 / 同一接口不同实现 / 演示 / 不同实现对象经同一接口调。用户提到这些词时使用本技能。
  场景：对照：Python 多态——同一接口不同实现（运行时方法分发）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  obj.speak 可用
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["多态分发", "面向对象-多态", "Python 多", "多态", "同一接口不同实现", "演示", "不同实现对象经同一接口调"]
    when: "obj.speak 可用"
    sub: []
    execute: "多态：同一接口不同实现（运行时方法分发）；演示：不同实现对象经同一接口调用（多态分发语义）"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：Python 多态——同一接口不同实现（运行时方法分发）"
---

# 面向对象-多态（pylang-c36fabf7）

## When to use

任务「多态分发」；对照：Python 多态——同一接口不同实现（运行时方法分发）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

多态：同一接口不同实现（运行时方法分发）；演示：不同实现对象经同一接口调用（多态分发语义）

## Verification

- 单元样例 1 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「面向对象-多态」
