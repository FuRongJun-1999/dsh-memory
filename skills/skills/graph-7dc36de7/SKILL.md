---
name: graph-7dc36de7
description: >-
  图序列化 / 图持久化-序列化 / 条件图数据库——图序列化 / JSON → 图。用户提到这些词时使用本技能。
  场景：对照：条件图数据库——图序列化持久化（JSON 存储层）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  graph 含 nodes/edges 接口（节点集 + 邻接表）
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["图序列化", "图持久化-序列化", "条件图数据库——图序列化", "JSON → 图"]
    when: "graph 含 nodes/edges 接口（节点集 + 邻接表）"
    sub: ["① 节点排序收集 ② 边表排序 ③ JSON 编码"]
    execute: "json.dumps({'nodes':…, 'edges':…})"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：条件图数据库——图序列化持久化（JSON 存储层）"
---

# 图持久化-序列化（graph-7dc36de7）

## When to use

任务「图序列化」；对照：条件图数据库——图序列化持久化（JSON 存储层）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

json.dumps({'nodes':…, 'edges':…})

## Verification

- 单元样例 1 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「图持久化-序列化」
