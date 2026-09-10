---
name: browser-b4c8cf65
description: >-
  事件委托 / 事件-事件委托 / 祖先单监听器按目标分派。用户提到这些词时使用本技能。
  场景：对照：事件委托——祖先单监听器按 target+type 分派子处理器（冒泡优化）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  handlers 键为 (目标, 事件类型)；event 含 target/type
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["事件委托", "事件-事件委托", "祖先单监听器按目标分派"]
    when: "handlers 键为 (目标, 事件类型)；event 含 target/type"
    sub: ["① 按 (target, type) 查处理器 ② 命中调用并返回结果"]
    execute: "dict 精确键查 + 处理器调用，未命中返回 None"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：事件委托——祖先单监听器按 target+type 分派子处理器（冒泡优化）"
---

# 事件-事件委托（browser-b4c8cf65）

## When to use

任务「事件委托」；对照：事件委托——祖先单监听器按 target+type 分派子处理器（冒泡优化）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

dict 精确键查 + 处理器调用，未命中返回 None

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「事件-事件委托」
