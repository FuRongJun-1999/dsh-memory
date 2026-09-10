---
name: browser-faac8812
description: >-
  XSS防护 / 安全-XSS防护 / XSS 防 / HTML 转。用户提到这些词时使用本技能。
  场景：对照：浏览器安全——XSS 防护（HTML 实体转义，防脚本注入）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  text.replace 可用
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["XSS防护", "安全-XSS防护", "XSS 防", "HTML 转"]
    when: "text.replace 可用"
    sub: []
    execute: "XSS 防护：HTML 转义（< > & \" ' → 实体，防脚本注入）"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：浏览器安全——XSS 防护（HTML 实体转义，防脚本注入）"
---

# 安全-XSS防护（browser-faac8812）

## When to use

任务「XSS防护」；对照：浏览器安全——XSS 防护（HTML 实体转义，防脚本注入）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

XSS 防护：HTML 转义（< > & " ' → 实体，防脚本注入）

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「安全-XSS防护」
