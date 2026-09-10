---
name: graph-06e2b1f2
description: >-
  节点标签 / 图可视化-节点标签 / 图可视化——节点标签标注 / 为节点附标签（可视化标注。用户提到这些词时使用本技能。
  场景：对照：图可视化——节点标签标注（缺省占位）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  参数 positions/labels 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["节点标签", "图可视化-节点标签", "图可视化——节点标签标注", "为节点附标签（可视化标注"]
    when: "参数 positions/labels 合法"
    sub: []
    execute: "节点标签：为节点附标签（可视化标注，缺省 ?）"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：图可视化——节点标签标注（缺省占位）"
---

# 图可视化-节点标签（graph-06e2b1f2）

## When to use

任务「节点标签」；对照：图可视化——节点标签标注（缺省占位）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

节点标签：为节点附标签（可视化标注，缺省 ?）

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「图可视化-节点标签」
