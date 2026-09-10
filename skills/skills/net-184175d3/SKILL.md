---
name: net-184175d3
description: >-
  边缘计算 / 网络-边缘计算 / 边缘计算——任务就近处理 / 任务分发到就近节点处理。用户提到这些词时使用本技能。
  场景：对照：边缘计算——任务就近处理（边缘节点/云端回退）。
  【不适用】Not for 以下场景：nodes 为空/非法时（隐式盲区：返回默认值 ('cloud', 0) = 未知行为——不适用）
license: MIT
compatibility: >-
  参数 nodes/task/data 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["边缘计算", "网络-边缘计算", "边缘计算——任务就近处理", "任务分发到就近节点处理"]
    when: "参数 nodes/task/data 合法"
    sub: ["① 调用 min"]
    execute: "顺序调用"
    not_applicable: ["nodes 为空/非法时（隐式盲区：返回默认值 ('cloud', 0) = 未知行为——不适用）"]
  calibration: "对照：边缘计算——任务就近处理（边缘节点/云端回退）"
---

# 网络-边缘计算（net-184175d3）

## When to use

任务「边缘计算」；对照：边缘计算——任务就近处理（边缘节点/云端回退）。

## 克制条款（不适用条件）

nodes 为空/非法时（隐式盲区：返回默认值 ('cloud', 0) = 未知行为——不适用）

## How to execute

顺序调用

## Verification

- 单元样例 2 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「网络-边缘计算」
