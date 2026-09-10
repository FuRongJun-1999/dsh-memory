---
name: graph-94582f69
description: >-
  图存储 / 图存储-节点边 / 条件路由图——知识=节点 / 条件链=边 / 节点 + 有向边（知识= / 构造 / 初始化节点集合与邻接表 / 加节点。用户提到这些词时使用本技能。
  场景：对照：条件路由图——知识=节点、条件链=边（气压低→沸点降→煮不熟 条件链）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  g.add_edge 可用；g.neighbors 可用
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["图存储", "图存储-节点边", "条件路由图——知识=节点", "条件链=边", "节点 + 有向边（知识=", "构造", "初始化节点集合与邻接表", "加节点"]
    when: "g.add_edge 可用；g.neighbors 可用"
    sub: ["① 调用 Graph；② 调用 sorted"]
    execute: "顺序调用"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：条件路由图——知识=节点、条件链=边（气压低→沸点降→煮不熟 条件链）"
---

# 图存储-节点边（graph-94582f69）

## When to use

任务「图存储」；对照：条件路由图——知识=节点、条件链=边（气压低→沸点降→煮不熟 条件链）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

顺序调用

## Verification

- 单元样例 1 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「图存储-节点边」
