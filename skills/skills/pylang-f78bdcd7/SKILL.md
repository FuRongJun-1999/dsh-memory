---
name: pylang-f78bdcd7
description: >-
  函数机制 / 函数-定义调用 / mini_python. / 函数对象 / 调用。用户提到这些词时使用本技能。
  场景：对照：mini_python.py 函数对象（参数+body+定义环境）与 call 调用（局部环境+参数绑定）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  参数 params/body/def_env 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["函数机制", "函数-定义调用", "mini_python.", "函数对象", "调用"]
    when: "参数 params/body/def_env 合法"
    sub: []
    execute: "函数对象：参数 + body + 定义环境（闭包基础）；调用：局部环境（父=定义环境）+ 参数绑定 + 执行 body（return 值）"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：mini_python.py 函数对象（参数+body+定义环境）与 call 调用（局部环境+参数绑定）"
---

# 函数-定义调用（pylang-f78bdcd7）

## When to use

任务「函数机制」；对照：mini_python.py 函数对象（参数+body+定义环境）与 call 调用（局部环境+参数绑定）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

函数对象：参数 + body + 定义环境（闭包基础）；调用：局部环境（父=定义环境）+ 参数绑定 + 执行 body（return 值）

## Verification

- 单元样例 1 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「函数-定义调用」
