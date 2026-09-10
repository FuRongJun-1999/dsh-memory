---
name: browser-a681d0c2
description: >-
  CSP策略 / 安全-CSP策略 / CSP / 内容安全策略。用户提到这些词时使用本技能。
  场景：对照：浏览器安全——CSP（资源类型白名单，* 通配允许）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  参数 policy/resource_type/source 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["CSP策略", "安全-CSP策略", "CSP", "内容安全策略"]
    when: "参数 policy/resource_type/source 合法"
    sub: []
    execute: "CSP：内容安全策略（资源类型 → 允许的来源白名单）"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：浏览器安全——CSP（资源类型白名单，* 通配允许）"
---

# 安全-CSP策略（browser-a681d0c2）

## When to use

任务「CSP策略」；对照：浏览器安全——CSP（资源类型白名单，* 通配允许）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

CSP：内容安全策略（资源类型 → 允许的来源白名单）

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「安全-CSP策略」
