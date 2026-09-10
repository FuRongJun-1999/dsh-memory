---
name: browser-7f9cefec
description: >-
  虚拟键盘 / 浏览器-虚拟键盘 / show 显。用户提到这些词时使用本技能。
  场景：对照：Virtual Keyboard——虚拟键盘显隐。
  【不适用】Not for 以下场景：op 非 {hide, show, visible} 时
license: MIT
compatibility: >-
  op ∈ {hide, show, visible}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["虚拟键盘", "浏览器-虚拟键盘", "show 显"]
    when: "op ∈ {hide, show, visible}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派"
    not_applicable: ["op 非 {hide, show, visible} 时"]
  calibration: "对照：Virtual Keyboard——虚拟键盘显隐"
---

# 浏览器-虚拟键盘（browser-7f9cefec）

## When to use

任务「虚拟键盘」；对照：Virtual Keyboard——虚拟键盘显隐。

## 克制条款（不适用条件）

op 非 {hide, show, visible} 时

## How to execute

按 op 分派

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「浏览器-虚拟键盘」
