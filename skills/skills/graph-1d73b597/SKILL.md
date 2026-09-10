---
name: graph-1d73b597
description: >-
  路径查找 / 图遍历-路径 / 条件链——气压低→沸点降 / 路径存在性 / start 能。用户提到这些词时使用本技能。
  场景：对照：条件链——气压低→沸点降→煮不熟 有路径；反向无（条件链有向）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  graph 提供 neighbors 接口；start/end 为图中节点
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["路径查找", "图遍历-路径", "条件链——气压低→沸点降", "路径存在性", "start 能"]
    when: "graph 提供 neighbors 接口；start/end 为图中节点"
    sub: ["① 起终点相同直判 ② BFS 扩散 ③ 终点命中判定"]
    execute: "BFS 队列遍历，命中终点即返 True"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：条件链——气压低→沸点降→煮不熟 有路径；反向无（条件链有向）"
---

# 图遍历-路径（graph-1d73b597）

## When to use

任务「路径查找」；对照：条件链——气压低→沸点降→煮不熟 有路径；反向无（条件链有向）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

BFS 队列遍历，命中终点即返 True

## Verification

- 单元样例 2 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「图遍历-路径」
