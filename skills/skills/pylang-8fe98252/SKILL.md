---
name: pylang-8fe98252
description: >-
  作用域环境 / 环境-作用域链 / 变量环境 / 局部 → 父环境 / 构造 / 创建变量表并挂接父环境 / 查询 / 本层无则沿父环境链向上查。用户提到这些词时使用本技能。
  场景：对照：mini_python.py Env（父链作用域：局部找不到向上查找）。
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
    trigger_words: ["作用域环境", "环境-作用域链", "变量环境", "局部 → 父环境", "构造", "创建变量表并挂接父环境", "查询", "本层无则沿父环境链向上查"]
    when: "参数 输入 合法"
    sub: ["① 调用 Env"]
    execute: "顺序调用"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：mini_python.py Env（父链作用域：局部找不到向上查找）"
---

# 环境-作用域链（pylang-8fe98252）

## When to use

任务「作用域环境」；对照：mini_python.py Env（父链作用域：局部找不到向上查找）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

顺序调用

## Verification

- 单元样例 1 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「环境-作用域链」
