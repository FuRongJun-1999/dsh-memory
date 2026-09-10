---
name: browser-c92ac01b
description: >-
  CSP报告 / 浏览器-CSP报告 / CSP 报 / record 记。用户提到这些词时使用本技能。
  场景：对照：CSP report-uri——内容安全策略违规上报。
  【不适用】Not for 以下场景：op 非 {count, filter, record} 时
license: MIT
compatibility: >-
  op ∈ {count, filter, record}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["CSP报告", "浏览器-CSP报告", "CSP 报", "record 记"]
    when: "op ∈ {count, filter, record}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派；顺序调用"
    not_applicable: ["op 非 {count, filter, record} 时"]
  calibration: "对照：CSP report-uri——内容安全策略违规上报"
---

# 浏览器-CSP报告（browser-c92ac01b）

## When to use

任务「CSP报告」；对照：CSP report-uri——内容安全策略违规上报。

## 克制条款（不适用条件）

op 非 {count, filter, record} 时

## How to execute

按 op 分派；顺序调用

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「浏览器-CSP报告」
