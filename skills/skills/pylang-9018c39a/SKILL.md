---
name: pylang-9018c39a
description: >-
  闭包工厂 / 闭包-工厂 / Python 闭 / 相乘 / 参数与绑定因子相乘 / 演示 / 工厂产出不同倍数的闭包。用户提到这些词时使用本技能。
  场景：对照：Python 闭包工厂——函数返回绑定参数的闭包（乘子工厂）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  参数 factor 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["闭包工厂", "闭包-工厂", "Python 闭", "相乘", "参数与绑定因子相乘", "演示", "工厂产出不同倍数的闭包"]
    when: "参数 factor 合法"
    sub: []
    execute: "闭包工厂：返回绑定了 factor 的乘法闭包；相乘：参数与绑定因子相乘；演示：工厂产出不同倍数的闭包"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：Python 闭包工厂——函数返回绑定参数的闭包（乘子工厂）"
---

# 闭包-工厂（pylang-9018c39a）

## When to use

任务「闭包工厂」；对照：Python 闭包工厂——函数返回绑定参数的闭包（乘子工厂）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

闭包工厂：返回绑定了 factor 的乘法闭包；相乘：参数与绑定因子相乘；演示：工厂产出不同倍数的闭包

## Verification

- 单元样例 1 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「闭包-工厂」
