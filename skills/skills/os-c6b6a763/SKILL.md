---
name: os-c6b6a763
description: >-
  资源限制 / 虚拟化-cgroup限制 / cgroup 资 / 内存配额 / cgroup。用户提到这些词时使用本技能。
  场景：对照：cgroup 资源限制——CPU/内存配额（使用量超限拒绝）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  参数 cg/resource/limit/usage 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["资源限制", "虚拟化-cgroup限制", "cgroup 资", "内存配额", "cgroup"]
    when: "参数 cg/resource/limit/usage 合法"
    sub: ["① 条件判定 ② 结果处理"]
    execute: "cgroup：资源配额（CPU/内存 限额，超限拒绝）"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：cgroup 资源限制——CPU/内存配额（使用量超限拒绝）"
---

# 虚拟化-cgroup限制（os-c6b6a763）

## When to use

任务「资源限制」；对照：cgroup 资源限制——CPU/内存配额（使用量超限拒绝）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

cgroup：资源配额（CPU/内存 限额，超限拒绝）

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「虚拟化-cgroup限制」
