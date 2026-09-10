---
name: pylang-dcde3040
description: >-
  参数默认值绑定 / 参数-默认值与关键字绑定。用户提到这些词时使用本技能。
  场景：对照：mini_python.py bind_params（V-P4 第三批 d2f796a，AST/VM 共用绑定，默认值在定义环境求值）。
  【不适用】Not for 以下场景：*args/**kwargs 收集形态与重复绑定冲突检测不在本单元范围
license: MIT
compatibility: >-
  params 为 (名字, 默认值) 列表；args 为位置实参序列；kw 为关键字实参 dict
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["参数默认值绑定", "参数-默认值与关键字绑定"]
    when: "params 为 (名字, 默认值) 列表；args 为位置实参序列；kw 为关键字实参 dict"
    sub: ["① 位置实参按序绑定；② 关键字实参按名绑定；③ 缺省填充默认值"]
    execute: "顺序绑定；条件分派"
    not_applicable: ["*args/**kwargs 收集形态与重复绑定冲突检测不在本单元范围"]
  calibration: "对照：mini_python.py bind_params（V-P4 第三批 d2f796a，AST/VM 共用绑定，默认值在定义环境求值）"
---

# 参数-默认值与关键字绑定（pylang-dcde3040）

## When to use

任务「参数默认值绑定」；对照：mini_python.py bind_params（V-P4 第三批 d2f796a，AST/VM 共用绑定，默认值在定义环境求值）。

## 克制条款（不适用条件）

*args/**kwargs 收集形态与重复绑定冲突检测不在本单元范围

## How to execute

顺序绑定；条件分派

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「参数-默认值与关键字绑定」
