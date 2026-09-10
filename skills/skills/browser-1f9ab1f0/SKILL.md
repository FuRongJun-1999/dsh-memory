---
name: browser-1f9ab1f0
description: >-
  边框圆角 / 渲染-边框圆角 / border-radiu / 点是否在圆角矩形内。用户提到这些词时使用本技能。
  场景：对照：border-radius——圆角矩形内点判定（命中测试）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  参数 box/radius/point 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["边框圆角", "渲染-边框圆角", "border-radiu", "点是否在圆角矩形内"]
    when: "参数 box/radius/point 合法"
    sub: ["① 调用 min；② 调用 max"]
    execute: "顺序调用"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：border-radius——圆角矩形内点判定（命中测试）"
---

# 渲染-边框圆角（browser-1f9ab1f0）

## When to use

任务「边框圆角」；对照：border-radius——圆角矩形内点判定（命中测试）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

顺序调用

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「渲染-边框圆角」
