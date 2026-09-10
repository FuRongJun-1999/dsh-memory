---
name: browser-c4dd6078
description: >-
  样式计算 / 渲染-样式计算 / 浏览器渲染管线——样式计 / DOM 节。用户提到这些词时使用本技能。
  场景：对照：浏览器渲染管线——样式计算（DOM×CSS→匹配规则→级联取最高优先级样式）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  node 含 tag/classes；rules 为带特异度的样式规则列表
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["样式计算", "渲染-样式计算", "浏览器渲染管线——样式计", "DOM 节"]
    when: "node 含 tag/classes；rules 为带特异度的样式规则列表"
    sub: ["① 规则匹配过滤 ② 特异度比较 ③ 级联合并最终样式"]
    execute: "匹配规则按权重取最优逐属性合并"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：浏览器渲染管线——样式计算（DOM×CSS→匹配规则→级联取最高优先级样式）"
---

# 渲染-样式计算（browser-c4dd6078）

## When to use

任务「样式计算」；对照：浏览器渲染管线——样式计算（DOM×CSS→匹配规则→级联取最高优先级样式）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

匹配规则按权重取最优逐属性合并

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「渲染-样式计算」
