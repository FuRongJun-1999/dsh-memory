---
name: compiler-0ee9b9b9
description: >-
  关键字识别 / 词法-关键字识别 / 词法——关键字表命中分类。用户提到这些词时使用本技能。
  场景：对照：词法——关键字表命中分类（KW token）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  参数 word/keywords 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["关键字识别", "词法-关键字识别", "词法——关键字表命中分类"]
    when: "参数 word/keywords 合法"
    sub: ["① 条件判定 ② 结果处理"]
    execute: "关键字识别：命中关键字表返回 (KW, 词) 否则 None（词法分类）"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：词法——关键字表命中分类（KW token）"
---

# 词法-关键字识别（compiler-0ee9b9b9）

## When to use

任务「关键字识别」；对照：词法——关键字表命中分类（KW token）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

关键字识别：命中关键字表返回 (KW, 词) 否则 None（词法分类）

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「词法-关键字识别」
