---
name: browser-cc7d3d6d
description: >-
  安装事件 / PWA-安装事件 / PWA beforein / 展示 / 接受 / 拒绝 / PWA 安 / beforeinstal。用户提到这些词时使用本技能。
  场景：对照：PWA beforeinstallprompt——捕获/展示/接受/拒绝（安装事件流）。
  【不适用】Not for 以下场景：action 非 {accept, capture, dismiss, prompt} 时
license: MIT
compatibility: >-
  action ∈ {accept, capture, dismiss, prompt}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["安装事件", "PWA-安装事件", "PWA beforein", "展示", "接受", "拒绝", "PWA 安", "beforeinstal"]
    when: "action ∈ {accept, capture, dismiss, prompt}"
    sub: ["1 action 分支处理"]
    execute: "按 op 分派"
    not_applicable: ["action 非 {accept, capture, dismiss, prompt} 时"]
  calibration: "对照：PWA beforeinstallprompt——捕获/展示/接受/拒绝（安装事件流）"
---

# PWA-安装事件（browser-cc7d3d6d）

## When to use

任务「安装事件」；对照：PWA beforeinstallprompt——捕获/展示/接受/拒绝（安装事件流）。

## 克制条款（不适用条件）

action 非 {accept, capture, dismiss, prompt} 时

## How to execute

按 op 分派

## Verification

- 单元样例 5 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「PWA-安装事件」
