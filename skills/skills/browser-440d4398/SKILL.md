---
name: browser-440d4398
description: >-
  弹窗拦截 / 浏览器-弹窗拦截 / 无用户手势的自动弹窗拦截。用户提到这些词时使用本技能。
  场景：对照：弹窗拦截——仅用户手势触发的允许弹窗，自动弹窗拦截并记录。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  allow 为站点弹窗许可；user_gesture 为用户手势标志
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["弹窗拦截", "浏览器-弹窗拦截", "无用户手势的自动弹窗拦截"]
    when: "allow 为站点弹窗许可；user_gesture 为用户手势标志"
    sub: ["① 许可+手势放行 ② 否则拦截并记录"]
    execute: "allow ∧ user_gesture → allowed；否则 blocked_log 追加并返 blocked"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：弹窗拦截——仅用户手势触发的允许弹窗，自动弹窗拦截并记录"
---

# 浏览器-弹窗拦截（browser-440d4398）

## When to use

任务「弹窗拦截」；对照：弹窗拦截——仅用户手势触发的允许弹窗，自动弹窗拦截并记录。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

allow ∧ user_gesture → allowed；否则 blocked_log 追加并返 blocked

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「浏览器-弹窗拦截」
