# -*- coding: utf-8 -*-
"""灵枢语义层（semantic IR）· 原子级中英归一管线。

模块：
  - atoms.json        语义原子（815）
  - zh_en_atoms.py    中文文本 → 标准英文原子序列
  - en_normalizer.py  英文 query → 中文语素序列（检索归一）
  - build_en_index.py 英文词 → 中文原子倒排索引构建
  - SCHEMA.md         IR schema v0.1
"""
