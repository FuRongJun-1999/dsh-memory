---
name: browser-24163519
description: >-
  DOM解析 / HTML-DOM解析 / HTML → DOM 树 / 标签 → 直接子标签列表。用户提到这些词时使用本技能。
  场景：对照：浏览器 HTML 解析——标签嵌套 → DOM 树（父子关系）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  re.finditer 可用；m.group 可用
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["DOM解析", "HTML-DOM解析", "HTML → DOM 树", "标签 → 直接子标签列表"]
    when: "re.finditer 可用；m.group 可用"
    sub: ["① 条件判定 ② 结果处理"]
    execute: "循环迭代"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：浏览器 HTML 解析——标签嵌套 → DOM 树（父子关系）"
---

# HTML-DOM解析（browser-24163519）

## When to use

任务「DOM解析」；对照：浏览器 HTML 解析——标签嵌套 → DOM 树（父子关系）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

循环迭代

## Verification

- 单元样例 2 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「HTML-DOM解析」
