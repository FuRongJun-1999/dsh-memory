---
name: browser-0f598430
description: >-
  页面可见性 / 浏览器-页面可见性 / document.vis / set 切。用户提到这些词时使用本技能。
  场景：对照：document.visibilityState——页面可见性（visible/hidden 切换）。
  【不适用】Not for 以下场景：op 非 {events, get, set} 时
license: MIT
compatibility: >-
  op ∈ {events, get, set}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["页面可见性", "浏览器-页面可见性", "document.vis", "set 切"]
    when: "op ∈ {events, get, set}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派；顺序调用"
    not_applicable: ["op 非 {events, get, set} 时"]
  calibration: "对照：document.visibilityState——页面可见性（visible/hidden 切换）"
---

# 浏览器-页面可见性（browser-0f598430）

## When to use

任务「页面可见性」；对照：document.visibilityState——页面可见性（visible/hidden 切换）。

## 克制条款（不适用条件）

op 非 {events, get, set} 时

## How to execute

按 op 分派；顺序调用

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「浏览器-页面可见性」
