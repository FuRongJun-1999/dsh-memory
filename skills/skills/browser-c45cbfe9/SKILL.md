---
name: browser-c45cbfe9
description: >-
  CSS级联 / CSS-级联 / 级联应用 / 选择最高优先级规则 / CSS 级。用户提到这些词时使用本技能。
  场景：对照：浏览器 CSS——级联优先级（内联>id>class>标签）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  参数 rules 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["CSS级联", "CSS-级联", "级联应用", "选择最高优先级规则", "CSS 级"]
    when: "参数 rules 合法"
    sub: ["① 调用 max"]
    execute: "顺序调用"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：浏览器 CSS——级联优先级（内联>id>class>标签）"
---

# CSS-级联（browser-c45cbfe9）

## When to use

任务「CSS级联」；对照：浏览器 CSS——级联优先级（内联>id>class>标签）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

顺序调用

## Verification

- 单元样例 2 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「CSS-级联」
