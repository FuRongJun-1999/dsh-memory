---
name: browser-a372edeb
description: >-
  命中测试 / 渲染-命中测试 / 渲染命中测试——从顶向下 / 从顶层向下找包含  的元。用户提到这些词时使用本技能。
  场景：对照：渲染命中测试——从顶向下坐标包含判定（点击命中元素）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  参数 layers/x/y 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["命中测试", "渲染-命中测试", "渲染命中测试——从顶向下", "从顶层向下找包含  的元"]
    when: "参数 layers/x/y 合法"
    sub: ["① 条件判定 ② 结果处理"]
    execute: "循环迭代"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：渲染命中测试——从顶向下坐标包含判定（点击命中元素）"
---

# 渲染-命中测试（browser-a372edeb）

## When to use

任务「命中测试」；对照：渲染命中测试——从顶向下坐标包含判定（点击命中元素）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

循环迭代

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「渲染-命中测试」
