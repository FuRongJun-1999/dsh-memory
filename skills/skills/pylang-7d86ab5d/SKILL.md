---
name: pylang-7d86ab5d
description: >-
  字符串切分 / 字符串-切分 / mini_python.。用户提到这些词时使用本技能。
  场景：对照：mini_python.py str 方法白名单 split（str.split 基础版，保留空段）。
  【不适用】Not for 以下场景：多字符分隔符/正则语义/maxsplit 不在本单元范围
license: MIT
compatibility: >-
  s 为字符串；sep 为单字符分隔符
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["字符串切分", "字符串-切分", "mini_python."]
    when: "s 为字符串；sep 为单字符分隔符"
    sub: ["① 线性扫描；② 保留空段；③ 缺分隔符返回原串"]
    execute: "循环迭代；顺序追加"
    not_applicable: ["多字符分隔符/正则语义/maxsplit 不在本单元范围"]
  calibration: "对照：mini_python.py str 方法白名单 split（str.split 基础版，保留空段）"
---

# 字符串-切分（pylang-7d86ab5d）

## When to use

任务「字符串切分」；对照：mini_python.py str 方法白名单 split（str.split 基础版，保留空段）。

## 克制条款（不适用条件）

多字符分隔符/正则语义/maxsplit 不在本单元范围

## How to execute

循环迭代；顺序追加

## Verification

- 单元样例 5 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「字符串-切分」
