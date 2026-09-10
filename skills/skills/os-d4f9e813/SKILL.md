---
name: os-d4f9e813
description: >-
  设备树 / 设备-设备树 / 设备树——硬件拓扑节点 / 硬件拓扑节点查找。用户提到这些词时使用本技能。
  场景：对照：设备树——硬件拓扑节点（compatible 属性）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  参数 tree/node 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["设备树", "设备-设备树", "设备树——硬件拓扑节点", "硬件拓扑节点查找"]
    when: "参数 tree/node 合法"
    sub: []
    execute: "设备树：硬件拓扑节点查找（属性查询）"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：设备树——硬件拓扑节点（compatible 属性）"
---

# 设备-设备树（os-d4f9e813）

## When to use

任务「设备树」；对照：设备树——硬件拓扑节点（compatible 属性）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

设备树：硬件拓扑节点查找（属性查询）

## Verification

- 单元样例 2 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「设备-设备树」
