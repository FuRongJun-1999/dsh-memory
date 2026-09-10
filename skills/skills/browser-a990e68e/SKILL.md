---
name: browser-a990e68e
description: >-
  翻译 / 浏览器-翻译 / translate 翻。用户提到这些词时使用本技能。
  场景：对照：Translator API——文本翻译与语言对。
  【不适用】Not for 以下场景：op 非 {available, langs, translate} 时
license: MIT
compatibility: >-
  op ∈ {available, langs, translate}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["翻译", "浏览器-翻译", "translate 翻"]
    when: "op ∈ {available, langs, translate}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派；顺序调用"
    not_applicable: ["op 非 {available, langs, translate} 时"]
  calibration: "对照：Translator API——文本翻译与语言对"
---

# 浏览器-翻译（browser-a990e68e）

## When to use

任务「翻译」；对照：Translator API——文本翻译与语言对。

## 克制条款（不适用条件）

op 非 {available, langs, translate} 时

## How to execute

按 op 分派；顺序调用

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「浏览器-翻译」
