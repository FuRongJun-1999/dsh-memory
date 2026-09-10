---
name: graph-72ce5342
description: >-
  图文件 / 图持久化-文件 / .cgdb 文 / 组装 / Graph + save。用户提到这些词时使用本技能。
  场景：对照：条件图数据库——.cgdb 文件持久化（存储层升级：JSON→文件）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  json.dump 可用
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["图文件", "图持久化-文件", ".cgdb 文", "组装", "Graph + save"]
    when: "json.dump 可用"
    sub: ["① 调用 open；② 调用 sorted"]
    execute: "顺序调用"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：条件图数据库——.cgdb 文件持久化（存储层升级：JSON→文件）"
---

# 图持久化-文件（graph-72ce5342）

## When to use

任务「图文件」；对照：条件图数据库——.cgdb 文件持久化（存储层升级：JSON→文件）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

顺序调用

## Verification

- 单元样例 1 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「图持久化-文件」
