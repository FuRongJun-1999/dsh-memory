---
name: graph-8d7b569b
description: >-
  二分匹配 / 图算法-二分匹配 / 增广路查找最大匹配 / 增广 / 为左顶点寻找可占用的右顶。用户提到这些词时使用本技能。
  场景：对照：匈牙利算法——增广路求二分图最大匹配。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  参数 adj/left 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["二分匹配", "图算法-二分匹配", "增广路查找最大匹配", "增广", "为左顶点寻找可占用的右顶"]
    when: "参数 adj/left 合法"
    sub: ["① 调用 try_k；② 调用 set"]
    execute: "循环迭代；顺序调用"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：匈牙利算法——增广路求二分图最大匹配"
---

# 图算法-二分匹配（graph-8d7b569b）

## When to use

任务「二分匹配」；对照：匈牙利算法——增广路求二分图最大匹配。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

循环迭代；顺序调用

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「图算法-二分匹配」
