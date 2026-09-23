#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""灵枢 · 检索 query 统一归一层（批次 15，2026-09-23 使用者口径定案）

口径：**统一翻译为中文 → 归一化到标准中文集（atoms.json）→ 检索**。
任何语言的 query 先归一为标准原子序列（空格 join）再进检索各路：
  - 英文：en_normalizer（时态还原→停用词剔除→en→zh 语素映射）→
    segment 展开为标准原子（「牛肉」→「牛 肉」，与 doc 侧 fm.semantic
    原子形态同构）；
  - 中文：segment 贪心最长匹配归一到 atoms.json 标准概念；
  - 纯中文 query **原样返回**——segment+join+bigrams(去空白) 后与原文
    等价，归一只对跨语 query 有信息增益（beef 与「牛肉」零共享字符，
    形态归一救不了跨语），纯中文零变更纪律；
  - 专名/未登录词原样保留（词表边界 unknown_keep，非错误）。

开关：MDCG_UNIFY_QUERY 默认 "1"（2026-09-23 使用者拍板口径转正）；
"=0" 显式关回退。两侧同步：rust/mcdg-eval 读同一 env + 同一份
atoms.json（scripts/rank_parity.py --dataset 对拍在两侧同开关态进行，
A/B 差异归档为转正证据）。

归一失败（semantic 模块缺失等）静默原样返回——与 en_zh_terms 同降级
风格，不阻断检索主链路。
"""
import os
import re

# 生效条件：无 required 形参，锚定环境变量名 MDCG_UNIFY_QUERY；当 os.environ.get("MDCG_UNIFY_QUERY", "1") == "1" 时返回 True，否则返回 False。
def unify_on() -> bool:
    """统一归一层开关（默认开=口径定案转正；=0 显式关回退）。"""
    return os.environ.get("MDCG_UNIFY_QUERY", "1") == "1"


# 生效条件：text 为 None/空串或开关关闭或不含 [A-Za-z] 时原样返回；否则经 canonical.query_atoms 归一为标准原子序列并以单空格 join 返回（归一产物为空或抛异常时原样返回）。
def unify_query(text):
    """检索入口统一归一：任意语言 query → 标准原子序列。"""
    t = (text or "").strip()
    if not t or not unify_on() or not re.search(r"[A-Za-z]", t):
        return text
    try:
        from .canonical import query_atoms
        atoms = query_atoms(t)
    except Exception:
        return text
    u = " ".join(a for a in atoms if a).strip()
    return u if u else text
