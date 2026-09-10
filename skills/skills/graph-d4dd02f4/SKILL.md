---
name: graph-d4dd02f4
description: >-
  标签约束 / 图查询-标签约束 / 图查询——边标签约束路径 / 路径边标签序列匹配。用户提到这些词时使用本技能。
  场景：对照：图查询——边标签约束路径（标签序列匹配）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  参数 adj/start/end/labels/want 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["标签约束", "图查询-标签约束", "图查询——边标签约束路径", "路径边标签序列匹配"]
    when: "参数 adj/start/end/labels/want 合法"
    sub: ["① 调用 set；② 调用 tuple"]
    execute: "循环迭代；顺序调用"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：图查询——边标签约束路径（标签序列匹配）"
---

# 图查询-标签约束（graph-d4dd02f4）

## When to use

任务「标签约束」；对照：图查询——边标签约束路径（标签序列匹配）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

循环迭代；顺序调用

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「图查询-标签约束」
