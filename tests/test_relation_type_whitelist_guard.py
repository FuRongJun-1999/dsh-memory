# -*- coding: utf-8 -*-
"""守卫：关系类型白名单与孤例（N5-b 落地）。

# 功能名：关系类型白名单守卫
# 生效条件：每次跑测试时；改动 md_cg/relations.py 或边写入路径后
# 子功能：①白名单含全部存量类型 ②空串合法 ③笔误判 unknown ④分级不越权
#         ⑤统计函数正确 ⑥实库扫描（库存在时）：未标注率区间 + 孤例仅含已知项
# 执行：python -X utf8 -m pytest tests/test_relation_type_whitelist_guard.py -q
# 验证方式：本文件自身
# 不适用条件：不判语义正误；CI 上无实库时第 6 组自动跳过（不伪造通过）
"""
from __future__ import annotations

import os
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
from md_cg import relations as R  # noqa: E402


# ---- ① 白名单覆盖存量 ----
def test_whitelist_covers_all_stock_types():
    """实取存量 6 种必须都在白名单里（漏一个即让存量边变非法）。"""
    stock = {"generalizes", "instance_of", "reference",
             "depends_on", "derived_from", "collaborator"}
    missing = stock - set(R.RELATION_TYPES)
    assert not missing, "白名单漏了存量类型：%s" % sorted(missing)


def test_tension_is_whitelisted():
    """裁定 A：tension 允许写入（只沉淀不浮现）。"""
    assert R.reltype_verdict("tension") == (True, "labeled_ok")


# ---- ② 空串合法 ----
def test_empty_is_legal_but_counted():
    """空串 = 未标注：合法，且被计入未标注率。"""
    assert R.reltype_verdict("") == (True, "unlabeled")
    assert R.reltype_verdict(None) == (True, "unlabeled")
    assert R.reltype_verdict("   ") == (True, "unlabeled")
    d = R.distribution(["", "generalizes", ""])
    assert R.unlabeled_rate(d) == pytest.approx(2 / 3)


# ---- ③ 笔误判 unknown ----
def test_typo_is_unknown():
    """causual（少一个 l）必须判 unknown —— 这正是守卫要抓的。"""
    assert R.reltype_verdict("causual") == (False, "unknown")
    assert R.reltype_verdict("Causal") == (False, "unknown"), "大小写不等价，不得静默归一"


# ---- ④ 分级不越权 ----
def test_observe_never_blocks():
    assert R.should_block("causual", "observe") is False
    assert R.should_block("tension", "observe") is False


def test_enforce_blocks_unknown_only():
    assert R.should_block("causual", "enforce") is True
    assert R.should_block("tension", "enforce") is False
    assert R.should_block("", "enforce") is False, "未标注不得被 enforce 拦"


def test_mode_resolution_is_pure():
    """resolve_mode 是纯函数：非法/None 回落默认，合法值原样归一。"""
    assert R.resolve_mode("nonsense") == R.DEFAULT_MODE
    assert R.resolve_mode(None) == R.DEFAULT_MODE
    assert R.resolve_mode(" ENFORCE ") == "enforce"
    assert R.resolve_mode("observe") == "observe"


# ---- ⑤ 统计函数 ----
def test_singletons_and_distribution():
    d = R.distribution(["a", "a", "b", "", "c"])
    assert d == {"a": 2, "b": 1, "": 1, "c": 1}
    assert R.singletons(d) == ["b", "c"]
    assert "" not in R.singletons(d), "未标注不得进孤例"


# ---- ⑥ 实库扫描（无库即跳过，不伪造通过）----
def _find_root():
    return os.environ.get("MDCG_ROOT") or ""


def test_real_library_distribution():
    root = _find_root()
    if not root or not os.path.isdir(root):
        pytest.skip("无实库（未设 MDCG_ROOT），跳过实库断言——不伪造通过")
    from md_cg import MdCG
    cg = MdCG(root)
    try:
        nodes = (cg.index or {}).get("nodes") or {}
        edges = [ed.get("relation_type") or ed.get("relation")
                 for _n, e in nodes.items() for ed in (e.get("edges") or [])
                 if isinstance(ed, dict)]
    finally:
        try:
            cg.close()
        except Exception:
            pass
    d = R.distribution(edges)
    rate = R.unlabeled_rate(d)
    # 区间而非定值：正常使用会漂移，写死会让守卫随使用而红
    assert 0.6 <= rate <= 0.9, "未标注率越界：%.3f（实取基线 0.754）" % rate
    unknown = [k for k in d if not R.reltype_verdict(k)[0]]
    extra = [k for k in unknown if k not in R.KNOWN_SINGLETONS]
    assert not extra, "出现白名单外类型：%s（如为有效新类型，请加入 RELATION_TYPES）" % extra
