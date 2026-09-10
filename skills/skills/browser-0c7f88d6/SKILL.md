---
name: browser-0c7f88d6
description: >-
  盒模型 / 渲染-盒模型 / 浏览器渲染——盒模型。用户提到这些词时使用本技能。
  场景：对照：浏览器渲染——盒模型（padding/border 计入元素尺寸，margin 不计）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  width/padding/border/margin 为数值（CSS 盒属性）
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["盒模型", "渲染-盒模型", "浏览器渲染——盒模型"]
    when: "width/padding/border/margin 为数值（CSS 盒属性）"
    sub: ["① 内容宽 ② 加两侧 padding ③ 加两侧 border"]
    execute: "width + 2*padding + 2*border（margin 不计入总宽）"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：浏览器渲染——盒模型（padding/border 计入元素尺寸，margin 不计）"
---

# 渲染-盒模型（browser-0c7f88d6）

## When to use

任务「盒模型」；对照：浏览器渲染——盒模型（padding/border 计入元素尺寸，margin 不计）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

width + 2*padding + 2*border（margin 不计入总宽）

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「渲染-盒模型」
