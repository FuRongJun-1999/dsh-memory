---
name: graph-185f2cd2
description: >-
  图同构判定 / 图算法-图同构 / 图算法——同构判定 / 图同构 / 边数+节点度序列 相同 。用户提到这些词时使用本技能。
  场景：对照：图算法——同构判定（节点数+度序列必要条件，结构等价检测）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  参数 edges_a/edges_b 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["图同构判定", "图算法-图同构", "图算法——同构判定", "图同构", "边数+节点度序列 相同 "]
    when: "参数 edges_a/edges_b 合法"
    sub: ["① 调用 set；② 调用 deg_seq；③ 调用 len"]
    execute: "循环迭代；顺序调用"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：图算法——同构判定（节点数+度序列必要条件，结构等价检测）"
---

# 图算法-图同构（graph-185f2cd2）

## When to use

任务「图同构判定」；对照：图算法——同构判定（节点数+度序列必要条件，结构等价检测）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

循环迭代；顺序调用

## Verification

- 单元样例 2 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「图算法-图同构」
