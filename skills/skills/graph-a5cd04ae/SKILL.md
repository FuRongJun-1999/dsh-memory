---
name: graph-a5cd04ae
description: >-
  相似推荐 / 图学习-相似推荐 / 图学习——相似推荐 / 共同邻居最多的节点。用户提到这些词时使用本技能。
  场景：对照：图学习——相似推荐（共同邻居最多，协同过滤）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  cands.sort 可用；graph.neighbors 可用
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["相似推荐", "图学习-相似推荐", "图学习——相似推荐", "共同邻居最多的节点"]
    when: "cands.sort 可用；graph.neighbors 可用"
    sub: ["① 调用 set；② 调用 len；③ 调用 common"]
    execute: "顺序调用"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：图学习——相似推荐（共同邻居最多，协同过滤）"
---

# 图学习-相似推荐（graph-a5cd04ae）

## When to use

任务「相似推荐」；对照：图学习——相似推荐（共同邻居最多，协同过滤）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

顺序调用

## Verification

- 单元样例 1 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「图学习-相似推荐」
