---
name: graph-97b22f09
description: >-
  介数中心性 / 图算法-介数中心性 / 介数中心性——最短路径经 / 节点出现在最短路径中的次。用户提到这些词时使用本技能。
  场景：对照：介数中心性——最短路径经过次数（桥梁节点）。
  【不适用】Not for 以下场景：n_paths 为空/非法时
license: MIT
compatibility: >-
  参数 adj 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["介数中心性", "图算法-介数中心性", "介数中心性——最短路径经", "节点出现在最短路径中的次"]
    when: "参数 adj 合法"
    sub: ["① 调用 list；② 调用 round；③ 调用 len"]
    execute: "循环迭代；顺序调用"
    not_applicable: ["n_paths 为空/非法时"]
  calibration: "对照：介数中心性——最短路径经过次数（桥梁节点）"
---

# 图算法-介数中心性（graph-97b22f09）

## When to use

任务「介数中心性」；对照：介数中心性——最短路径经过次数（桥梁节点）。

## 克制条款（不适用条件）

n_paths 为空/非法时

## How to execute

循环迭代；顺序调用

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「图算法-介数中心性」
