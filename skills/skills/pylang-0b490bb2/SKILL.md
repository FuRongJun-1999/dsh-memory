---
name: pylang-0b490bb2
description: >-
  链表 / 数据结构-链表 / 单链表——节点链构建 / 遍历 / 查找 / 链表操作 / build 值。用户提到这些词时使用本技能。
  场景：对照：单链表——节点链构建/遍历/查找（Python 链表机制）。
  【不适用】Not for 以下场景：op 非 {build, contains, traverse} 时
license: MIT
compatibility: >-
  op ∈ {build, traverse, contains}；value 为查找目标（contains 时）
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["链表", "数据结构-链表", "单链表——节点链构建", "遍历", "查找", "链表操作", "build 值"]
    when: "op ∈ {build, traverse, contains}；value 为查找目标（contains 时）"
    sub: ["① build 逆序建链 ② traverse 顺序取值 ③ contains 遍历查找"]
    execute: "节点 dict {value, next} 链式构造与遍历"
    not_applicable: ["op 非 {build, contains, traverse} 时"]
  calibration: "对照：单链表——节点链构建/遍历/查找（Python 链表机制）"
---

# 数据结构-链表（pylang-0b490bb2）

## When to use

任务「链表」；对照：单链表——节点链构建/遍历/查找（Python 链表机制）。

## 克制条款（不适用条件）

op 非 {build, contains, traverse} 时

## How to execute

节点 dict {value, next} 链式构造与遍历

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「数据结构-链表」
