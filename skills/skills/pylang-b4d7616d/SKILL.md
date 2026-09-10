---
name: pylang-b4d7616d
description: >-
  类定义 / 面向对象-类定义 / Python 类 / __init__ 构 / 构造 / 保存实例名称属性 / 发声 / 返回带名称的叫声。用户提到这些词时使用本技能。
  场景：对照：Python 类定义——__init__ 构造 + 实例方法（实例属性语义）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  d.speak 可用
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["类定义", "面向对象-类定义", "Python 类", "__init__ 构", "构造", "保存实例名称属性", "发声", "返回带名称的叫声"]
    when: "d.speak 可用"
    sub: ["① 调用 Dog"]
    execute: "顺序调用"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：Python 类定义——__init__ 构造 + 实例方法（实例属性语义）"
---

# 面向对象-类定义（pylang-b4d7616d）

## When to use

任务「类定义」；对照：Python 类定义——__init__ 构造 + 实例方法（实例属性语义）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

顺序调用

## Verification

- 单元样例 1 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「面向对象-类定义」
