---
name: pylang-395085ca
description: >-
  属性访问 / 工具-属性访问 / Python 动 / 构造 / 初始化内部属性字典 / 读拦截 / 未定义属性从内部字典取。用户提到这些词时使用本技能。
  场景：对照：Python 动态属性（__getattr__/__setattr__ 拦截读写）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  参数 输入 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["属性访问", "工具-属性访问", "Python 动", "构造", "初始化内部属性字典", "读拦截", "未定义属性从内部字典取"]
    when: "参数 输入 合法"
    sub: ["① 调用 User"]
    execute: "顺序调用"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：Python 动态属性（__getattr__/__setattr__ 拦截读写）"
---

# 工具-属性访问（pylang-395085ca）

## When to use

任务「属性访问」；对照：Python 动态属性（__getattr__/__setattr__ 拦截读写）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

顺序调用

## Verification

- 单元样例 1 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「工具-属性访问」
