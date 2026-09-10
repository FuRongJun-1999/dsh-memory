---
name: browser-97a14ca3
description: >-
  事件监听 / 事件-事件监听 / 浏览器事件——监听器注册 / 触发 / 事件监听器。用户提到这些词时使用本技能。
  场景：对照：浏览器事件——监听器注册/触发（addEventListener/dispatchEvent 语义）。
  【不适用】Not for 以下场景：event 非 {add, trigger} 时（隐式盲区：返回默认值 0 = 未知行为——不适用）
license: MIT
compatibility: >-
  event ∈ {add, trigger}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["事件监听", "事件-事件监听", "浏览器事件——监听器注册", "触发", "事件监听器"]
    when: "event ∈ {add, trigger}"
    sub: ["1 event 分支处理"]
    execute: "按 op 分派；顺序调用"
    not_applicable: ["event 非 {add, trigger} 时（隐式盲区：返回默认值 0 = 未知行为——不适用）"]
  calibration: "对照：浏览器事件——监听器注册/触发（addEventListener/dispatchEvent 语义）"
---

# 事件-事件监听（browser-97a14ca3）

## When to use

任务「事件监听」；对照：浏览器事件——监听器注册/触发（addEventListener/dispatchEvent 语义）。

## 克制条款（不适用条件）

event 非 {add, trigger} 时（隐式盲区：返回默认值 0 = 未知行为——不适用）

## How to execute

按 op 分派；顺序调用

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「事件-事件监听」
