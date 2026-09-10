---
name: os-e7612c68
description: >-
  容器生命周期 / 容器-生命周期 / start / stop / remove / 容器 / 创建/启动/停止/删除。用户提到这些词时使用本技能。
  场景：对照：容器生命周期——create/start/stop/remove（镜像→实例状态机）。
  【不适用】Not for 以下场景：op 非 {create, remove, start, stop} 时
license: MIT
compatibility: >-
  op ∈ {create, remove, start, stop}；state.clear 可用
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["容器生命周期", "容器-生命周期", "start", "stop", "remove", "容器", "创建/启动/停止/删除"]
    when: "op ∈ {create, remove, start, stop}；state.clear 可用"
    sub: ["① op 分支处理"]
    execute: "按 op 分派"
    not_applicable: ["op 非 {create, remove, start, stop} 时"]
  calibration: "对照：容器生命周期——create/start/stop/remove（镜像→实例状态机）"
---

# 容器-生命周期（os-e7612c68）

## When to use

任务「容器生命周期」；对照：容器生命周期——create/start/stop/remove（镜像→实例状态机）。

## 克制条款（不适用条件）

op 非 {create, remove, start, stop} 时

## How to execute

按 op 分派

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「容器-生命周期」
