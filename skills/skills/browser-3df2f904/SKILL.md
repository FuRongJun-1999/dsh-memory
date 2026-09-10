---
name: browser-3df2f904
description: >-
  懒加载 / 性能-懒加载 / 浏览器性能——懒加载 / 视口内才加载。用户提到这些词时使用本技能。
  场景：对照：浏览器性能——懒加载（视口内才加载，按需优化）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  参数 loads/viewport 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["懒加载", "性能-懒加载", "浏览器性能——懒加载", "视口内才加载"]
    when: "参数 loads/viewport 合法"
    sub: []
    execute: "懒加载：视口内才加载（按需加载优化）"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：浏览器性能——懒加载（视口内才加载，按需优化）"
---

# 性能-懒加载（browser-3df2f904）

## When to use

任务「懒加载」；对照：浏览器性能——懒加载（视口内才加载，按需优化）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

懒加载：视口内才加载（按需加载优化）

## Verification

- 单元样例 2 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「性能-懒加载」
