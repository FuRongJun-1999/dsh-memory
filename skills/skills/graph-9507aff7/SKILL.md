---
name: graph-9507aff7
description: >-
  欧拉路径 / 图算法-欧拉路径 / 图算法——欧拉路径 / 一笔画判定。用户提到这些词时使用本技能。
  场景：对照：图算法——欧拉路径（0/2 个奇度节点一笔画）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  参数 adj/n 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["欧拉路径", "图算法-欧拉路径", "图算法——欧拉路径", "一笔画判定"]
    when: "参数 adj/n 合法"
    sub: ["① 调用 sum；② 调用 len；③ 调用 range"]
    execute: "顺序调用"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：图算法——欧拉路径（0/2 个奇度节点一笔画）"
---

# 图算法-欧拉路径（graph-9507aff7）

## When to use

任务「欧拉路径」；对照：图算法——欧拉路径（0/2 个奇度节点一笔画）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

顺序调用

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「图算法-欧拉路径」
