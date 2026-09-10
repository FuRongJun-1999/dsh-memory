---
name: browser-5ae7623a
description: >-
  标签页管理 / 浏览器-标签页管理 / 浏览器标签页——新建 / 切换 / 关闭 / 标签页 / open 新。用户提到这些词时使用本技能。
  场景：对照：浏览器标签页——新建/切换/关闭（活动标签维护）。
  【不适用】Not for 以下场景：op 非 {close, open, switch} 时
license: MIT
compatibility: >-
  op ∈ {close, open, switch}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["标签页管理", "浏览器-标签页管理", "浏览器标签页——新建", "切换", "关闭", "标签页", "open 新"]
    when: "op ∈ {close, open, switch}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派；顺序调用"
    not_applicable: ["op 非 {close, open, switch} 时"]
  calibration: "对照：浏览器标签页——新建/切换/关闭（活动标签维护）"
---

# 浏览器-标签页管理（browser-5ae7623a）

## When to use

任务「标签页管理」；对照：浏览器标签页——新建/切换/关闭（活动标签维护）。

## 克制条款（不适用条件）

op 非 {close, open, switch} 时

## How to execute

按 op 分派；顺序调用

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「浏览器-标签页管理」
