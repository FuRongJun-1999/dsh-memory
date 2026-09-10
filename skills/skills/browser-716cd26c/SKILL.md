---
name: browser-716cd26c
description: >-
  动画帧 / 渲染-动画帧 / 浏览器渲染——动画帧循环 / 动画帧循环。用户提到这些词时使用本技能。
  场景：对照：浏览器渲染——动画帧循环（rAF 逐帧更新状态）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  参数 state/step_fn/frames 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["动画帧", "渲染-动画帧", "浏览器渲染——动画帧循环", "动画帧循环"]
    when: "参数 state/step_fn/frames 合法"
    sub: ["① 调用 range；② 调用 step_fn"]
    execute: "循环迭代；顺序调用"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：浏览器渲染——动画帧循环（rAF 逐帧更新状态）"
---

# 渲染-动画帧（browser-716cd26c）

## When to use

任务「动画帧」；对照：浏览器渲染——动画帧循环（rAF 逐帧更新状态）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

循环迭代；顺序调用

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「渲染-动画帧」
