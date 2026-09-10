---
name: net-0e7f91e4
description: >-
  CRC校验 / 网络-CRC校验 / CRC-16 校。用户提到这些词时使用本技能。
  场景：对照：CRC-16 校验——多项式除法余数（传输完整性检测）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  参数 data 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["CRC校验", "网络-CRC校验", "CRC-16 校"]
    when: "参数 data 合法"
    sub: ["① 调用 range"]
    execute: "循环迭代；顺序调用"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：CRC-16 校验——多项式除法余数（传输完整性检测）"
---

# 网络-CRC校验（net-0e7f91e4）

## When to use

任务「CRC校验」；对照：CRC-16 校验——多项式除法余数（传输完整性检测）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

循环迭代；顺序调用

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「网络-CRC校验」
