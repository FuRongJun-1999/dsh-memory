---
name: compiler-05eeed1e
description: >-
  名实绑定 / 编译-名实绑定 / 以名举实 / 从内层到外层查找名的绑定。用户提到这些词时使用本技能。
  场景：对照：以名举实（v0.2 名实校验）编译期绑定——作用域链逐层查找，内层遮蔽外层；未绑定→(False, None)。
  【不适用】Not for 以下场景：name 为空串时直接未绑定；本函数不修改作用域栈内容
license: MIT
compatibility: >-
  scope_stack 为作用域栈（内层在前）；name 为待查符号名
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["名实绑定", "编译-名实绑定", "以名举实", "从内层到外层查找名的绑定"]
    when: "scope_stack 为作用域栈（内层在前）；name 为待查符号名"
    sub: ["① 逆序遍历作用域 ② 命中即返回绑定 ③ 全未命中返回未绑定"]
    execute: "reversed 逐层 dict 查键，内层遮蔽外层"
    not_applicable: ["name 为空串时直接未绑定；本函数不修改作用域栈内容"]
  calibration: "对照：以名举实（v0.2 名实校验）编译期绑定——作用域链逐层查找，内层遮蔽外层；未绑定→(False, None)"
---

# 编译-名实绑定（compiler-05eeed1e）

## When to use

任务「名实绑定」；对照：以名举实（v0.2 名实校验）编译期绑定——作用域链逐层查找，内层遮蔽外层；未绑定→(False, None)。

## 克制条款（不适用条件）

name 为空串时直接未绑定；本函数不修改作用域栈内容

## How to execute

reversed 逐层 dict 查键，内层遮蔽外层

## Verification

- 单元样例 5 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「编译-名实绑定」
