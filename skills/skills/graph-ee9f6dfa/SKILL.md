---
name: graph-ee9f6dfa
description: >-
  顶点覆盖 / 图算法-顶点覆盖 / 贪心选边两端加入覆盖并删。用户提到这些词时使用本技能。
  场景：对照：顶点覆盖（NP 完全）——贪心 2-近似：选边两端入覆盖，删去关联边。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  参数 edges 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["顶点覆盖", "图算法-顶点覆盖", "贪心选边两端加入覆盖并删"]
    when: "参数 edges 合法"
    sub: ["① 调用 set；② 调用 sorted；③ 调用 list"]
    execute: "循环迭代；顺序调用"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：顶点覆盖（NP 完全）——贪心 2-近似：选边两端入覆盖，删去关联边"
---

# 图算法-顶点覆盖（graph-ee9f6dfa）

## When to use

任务「顶点覆盖」；对照：顶点覆盖（NP 完全）——贪心 2-近似：选边两端入覆盖，删去关联边。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

循环迭代；顺序调用

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「图算法-顶点覆盖」
