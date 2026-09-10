---
name: graph-c4a59d80
description: >-
  图权限 / 图安全-权限控制 / 节点级访问控制。用户提到这些词时使用本技能。
  场景：对照：图安全——节点级 ACL（用户/节点/动作权限）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  参数 acl/user/node/action 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["图权限", "图安全-权限控制", "节点级访问控制"]
    when: "参数 acl/user/node/action 合法"
    sub: ["① 条件判定 ② 结果处理"]
    execute: "循环迭代"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：图安全——节点级 ACL（用户/节点/动作权限）"
---

# 图安全-权限控制（graph-c4a59d80）

## When to use

任务「图权限」；对照：图安全——节点级 ACL（用户/节点/动作权限）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

循环迭代

## Verification

- 单元样例 2 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「图安全-权限控制」
