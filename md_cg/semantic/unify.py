#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""灵枢 · 检索 query 统一归一层（批次 15 立；2026-09-30 使用者裁定收窄作用域）

口径：**只对英文内容做翻译归一，中文内容原样不动**。
query 先按「中文段 / 非中文段」切开，只有**非中文段里的英文**进归一链路：
  - 非中文段（含 ASCII 字母）：en_normalizer（时态还原→停用词剔除→en→zh 语素
    映射）→ segment 展开为标准原子（「牛肉」→「牛 肉」，与 doc 侧
    fm.semantic 原子形态同构）；
  - 中文段（CJK 统一表意文字基本区 U+4E00–U+9FFF，判据单点 =
    `canonical.is_zh_char`）：**逐字保留、绝不切分、绝不送 segment**；
  - 非英文段（数字/标点等，段内无 ASCII 字母）：原样保留（不是英文即不翻译）；
  - 两段按原顺序以单空格 join，空白（段内/段间）一律折叠为单空格；
  - 专名/未登录词原样保留（词表边界 unknown_keep，非错误）。

为什么收窄（2026-09-30 定因，实测于 locomo-zh-500 公开题池 500 题 / 567 池、
eval_common jaccard + GLOBAL_CAP 解除、k=5）：旧口径「query 含任一 ASCII 字母
即整条归一」会把**中夹英** query 的中文部分逐字切开（「自我接纳」→
「自 我 接 纳」、「慈善跑」→「慈 善 跑」）；500 题里含 ASCII 字母的 145 条
**全部**也含中文（无纯英文 query）。单点实测：整条归一 lexical hit@1 = 94.4% /
lexical,fuzzy = 87.2%；只译英文片段 lexical = 95.8% / lexical,fuzzy = 96.6%；
归一层全关 lexical = 96.4% / lexical,fuzzy = 97.2%。

开关：MDCG_UNIFY_QUERY 默认 "1"（2026-09-23 使用者拍板口径转正）；
"=0" 显式关回退。两侧同步：rust/mcdg-eval 读同一 env + 同一份
en_zh_map.json（scripts/rank_parity.py --dataset 对拍在两侧同开关态进行）。

归一失败（semantic 模块缺失等）静默原样返回——与 en_zh_terms 同降级
风格，不阻断检索主链路。

两侧同构：rust/src/atoms.rs::Atoms::unify 同语义、同中文判据；逐位对拍 fixture
= `md_cg/semantic/unify_fixture.json`（本侧守卫 md_cg/test_unify_scope.py 与
Rust 单测 unify_mixed_fixture_matches_python 钉同一份期望值）。
"""
import os
import re

from .canonical import is_zh_char

# 生效条件：无 required 形参，锚定环境变量名 MDCG_UNIFY_QUERY；当 os.environ.get("MDCG_UNIFY_QUERY", "1") == "1" 时返回 True，否则返回 False。
def unify_on() -> bool:
    """统一归一层开关（默认开=口径定案转正；=0 显式关回退）。"""
    return os.environ.get("MDCG_UNIFY_QUERY", "1") == "1"


# 生效条件：单参 text 为任意字符串（空串返回空列表），按 canonical.is_zh_char 逐字符判中文段，相邻同判据字符归并为一个连续段，返回 [(是否中文段, 段文本), ...] 的保序列表。
def _runs(text):
    """按中文判据切连续段：[(True, "中文段"), (False, "非中文段"), ...]。"""
    out = []
    cur = None
    buf = []
    for ch in text:
        k = is_zh_char(ch)
        if buf and k != cur:
            out.append((cur, "".join(buf)))
            buf = []
        cur = k
        buf.append(ch)
    if buf:
        out.append((cur, "".join(buf)))
    return out


# 生效条件：text 为 None/空串、或开关 MDCG_UNIFY_QUERY 取值不为 "1"、或 strip 后不含 [A-Za-z] 时，原样返回 text（未 strip 的入参）；否则按中文段（canonical.is_zh_char）切分——中文段与不含 ASCII 字母的非中文段逐字保留、含 ASCII 字母的非中文段经 canonical.query_atoms 归一——各段折空白后按原顺序单空格 join；归一产物为空（trim 后）或抛异常时原样返回 text。
def unify_query(text):
    """检索入口统一归一：只译英文内容，中文段逐字原样。"""
    t = (text or "").strip()
    if not t or not unify_on() or not re.search(r"[A-Za-z]", t):
        return text
    try:
        from .canonical import query_atoms
        parts = []
        for is_zh, run in _runs(t):
            if is_zh or not re.search(r"[A-Za-z]", run):
                seg = run                       # 中文段 / 非英文段：逐字保留
            else:
                atoms = query_atoms(run)        # 非中文段里的英文：既有链路
                seg = " ".join(a for a in atoms if a)
            seg = " ".join(seg.split())         # 段内空白折叠为单空格
            if seg:
                parts.append(seg)
    except Exception:
        return text
    u = " ".join(parts)
    return u if u else text
