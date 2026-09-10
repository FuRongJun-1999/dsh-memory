---
name: graph-fd51ece9
description: >-
  正则路径 / 图查询-正则路径 / 图查询——正则路径 / 正则路径查询 / 按标签序列沿边匹配。用户提到这些词时使用本技能。
  场景：对照：图查询——正则路径（标签序列沿边匹配，属性图路径语义）。
  【不适用】Not for 以下场景：frontier 为空/非法时
license: MIT
compatibility: >-
  参数 adj/start/labels 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["正则路径", "图查询-正则路径", "图查询——正则路径", "正则路径查询", "按标签序列沿边匹配"]
    when: "参数 adj/start/labels 合法"
    sub: ["① 调用 sorted；② 调用 set"]
    execute: "循环迭代；顺序调用"
    not_applicable: ["frontier 为空/非法时"]
  calibration: "对照：图查询——正则路径（标签序列沿边匹配，属性图路径语义）"
---

# 图查询-正则路径（graph-fd51ece9）

## When to use

任务「正则路径」；对照：图查询——正则路径（标签序列沿边匹配，属性图路径语义）。

## 克制条款（不适用条件）

frontier 为空/非法时

## How to execute

循环迭代；顺序调用

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「图查询-正则路径」
