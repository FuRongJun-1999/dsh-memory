---
name: graph-b76d15ee
description: >-
  节点特征 / 图嵌入-节点特征 / 图嵌入——节点特征 / 度/入度/出度。用户提到这些词时使用本技能。
  场景：对照：图嵌入——节点特征（出度/入度向量，图学习输入）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  graph.neighbors 可用
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["节点特征", "图嵌入-节点特征", "图嵌入——节点特征", "度/入度/出度"]
    when: "graph.neighbors 可用"
    sub: ["① 调用 len；② 调用 sorted"]
    execute: "循环迭代；顺序调用"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：图嵌入——节点特征（出度/入度向量，图学习输入）"
---

# 图嵌入-节点特征（graph-b76d15ee）

## When to use

任务「节点特征」；对照：图嵌入——节点特征（出度/入度向量，图学习输入）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

循环迭代；顺序调用

## Verification

- 单元样例 1 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「图嵌入-节点特征」
