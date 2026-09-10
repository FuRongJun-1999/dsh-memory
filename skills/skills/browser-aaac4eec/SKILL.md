---
name: browser-aaac4eec
description: >-
  布局树 / 渲染-布局树 / 浏览器渲染管线——布局树 / 块级节点→  坐标。用户提到这些词时使用本技能。
  场景：对照：浏览器渲染管线——布局树（块级纵向堆叠，默认宽=容器/高=1）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  参数 nodes/container_w 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["布局树", "渲染-布局树", "浏览器渲染管线——布局树", "块级节点→  坐标"]
    when: "参数 nodes/container_w 合法"
    sub: []
    execute: "循环迭代"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：浏览器渲染管线——布局树（块级纵向堆叠，默认宽=容器/高=1）"
---

# 渲染-布局树（browser-aaac4eec）

## When to use

任务「布局树」；对照：浏览器渲染管线——布局树（块级纵向堆叠，默认宽=容器/高=1）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

循环迭代

## Verification

- 单元样例 2 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「渲染-布局树」
