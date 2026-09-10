---
name: browser-37b8339e
description: >-
  关键渲染路径 / 性能-关键渲染路径 / 浏览器性能——关键渲染路 / 按依赖顺序推进。用户提到这些词时使用本技能。
  场景：对照：浏览器性能——关键渲染路径（CRP 依赖序推进，缺前置阻塞）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  order.index 可用
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["关键渲染路径", "性能-关键渲染路径", "浏览器性能——关键渲染路", "按依赖顺序推进"]
    when: "order.index 可用"
    sub: ["① 条件判定 ② 结果处理"]
    execute: "关键渲染路径：按依赖顺序推进（DOM→CSSOM→布局→绘制→合成）"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：浏览器性能——关键渲染路径（CRP 依赖序推进，缺前置阻塞）"
---

# 性能-关键渲染路径（browser-37b8339e）

## When to use

任务「关键渲染路径」；对照：浏览器性能——关键渲染路径（CRP 依赖序推进，缺前置阻塞）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

关键渲染路径：按依赖顺序推进（DOM→CSSOM→布局→绘制→合成）

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「性能-关键渲染路径」
