---
name: pylang-cd4234a5
description: >-
  二叉树 / 数据结构-二叉树 / 二叉搜索树——插入构建  / build 有 / 插入 / 按序递归定位并建节点 / 中序 / 左根右遍历。用户提到这些词时使用本技能。
  场景：对照：二叉搜索树——插入构建 + 中序遍历（升序输出）。
  【不适用】Not for 以下场景：op 非 {build, inorder} 时
license: MIT
compatibility: >-
  op ∈ {build, inorder}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["二叉树", "数据结构-二叉树", "二叉搜索树——插入构建 ", "build 有", "插入", "按序递归定位并建节点", "中序", "左根右遍历"]
    when: "op ∈ {build, inorder}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派；循环迭代；顺序调用"
    not_applicable: ["op 非 {build, inorder} 时"]
  calibration: "对照：二叉搜索树——插入构建 + 中序遍历（升序输出）"
---

# 数据结构-二叉树（pylang-cd4234a5）

## When to use

任务「二叉树」；对照：二叉搜索树——插入构建 + 中序遍历（升序输出）。

## 克制条款（不适用条件）

op 非 {build, inorder} 时

## How to execute

按 op 分派；循环迭代；顺序调用

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「数据结构-二叉树」
