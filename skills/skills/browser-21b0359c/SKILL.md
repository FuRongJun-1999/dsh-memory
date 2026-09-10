---
name: browser-21b0359c
description: >-
  文本排版 / 渲染-文本排版 / 浏览器渲染——文本换行 / 按宽度贪心换行。用户提到这些词时使用本技能。
  场景：对照：浏览器渲染——文本换行（按宽度贪心断行）。
  【不适用】Not for 以下场景：text 为空/非法时（隐式盲区：返回默认值 [] = 未知行为——不适用）
license: MIT
compatibility: >-
  参数 text/width 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["文本排版", "渲染-文本排版", "浏览器渲染——文本换行", "按宽度贪心换行"]
    when: "参数 text/width 合法"
    sub: ["① 调用 len"]
    execute: "循环迭代；顺序调用"
    not_applicable: ["text 为空/非法时（隐式盲区：返回默认值 [] = 未知行为——不适用）"]
  calibration: "对照：浏览器渲染——文本换行（按宽度贪心断行）"
---

# 渲染-文本排版（browser-21b0359c）

## When to use

任务「文本排版」；对照：浏览器渲染——文本换行（按宽度贪心断行）。

## 克制条款（不适用条件）

text 为空/非法时（隐式盲区：返回默认值 [] = 未知行为——不适用）

## How to execute

循环迭代；顺序调用

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「渲染-文本排版」
