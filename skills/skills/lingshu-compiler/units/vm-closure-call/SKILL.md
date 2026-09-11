---
name: vm-closure-call
description: >-
  闭包调用 / VM-闭包调用 / 闭包调用——词法父环境  / 捕获环境 + 参数绑定  / （词法父作用域可见 +  / 参数遮蔽捕获变量）。用户提到这些词时使用本技能。
  场景：对照：闭包调用——词法父环境 + 参数遮蔽（CPython 闭包调用语义）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  参数 closure/params/args 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["闭包调用", "VM-闭包调用", "闭包调用——词法父环境 ", "捕获环境 + 参数绑定 ", "（词法父作用域可见 + ", "参数遮蔽捕获变量）"]
    when: "参数 closure/params/args 合法"
    sub: ["① 调用 dict；② 调用 zip"]
    execute: "循环迭代；顺序调用"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：闭包调用——词法父环境 + 参数遮蔽（CPython 闭包调用语义）"
---

# VM-闭包调用（vm-closure-call）

## When to use

任务「闭包调用」；对照：闭包调用——词法父环境 + 参数遮蔽（CPython 闭包调用语义）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

循环迭代；顺序调用

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「VM-闭包调用」
