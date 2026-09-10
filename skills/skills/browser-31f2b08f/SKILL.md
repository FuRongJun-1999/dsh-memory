---
name: browser-31f2b08f
description: >-
  形状检测 / 浏览器-形状检测 / detect 检。用户提到这些词时使用本技能。
  场景：对照：Shape Detection——人脸/条码形状检测。
  【不适用】Not for 以下场景：op 非 {count, detect, last} 时
license: MIT
compatibility: >-
  op ∈ {count, detect, last}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["形状检测", "浏览器-形状检测", "detect 检"]
    when: "op ∈ {count, detect, last}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派"
    not_applicable: ["op 非 {count, detect, last} 时"]
  calibration: "对照：Shape Detection——人脸/条码形状检测"
---

# 浏览器-形状检测（browser-31f2b08f）

## When to use

任务「形状检测」；对照：Shape Detection——人脸/条码形状检测。

## 克制条款（不适用条件）

op 非 {count, detect, last} 时

## How to execute

按 op 分派

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「浏览器-形状检测」
