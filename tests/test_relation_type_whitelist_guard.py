# -*- coding: utf-8 -*-
"""守卫：关系类型白名单与孤例（N5-b 落地）。

# 功能名：关系类型白名单守卫
# 生效条件：每次跑测试时；改动 md_cg/relations.py 或边写入路径后
# 子功能：①白名单含全部存量类型 ②空串合法 ③笔误判 unknown ④分级不越权
#         ⑤统计函数正确 ⑥实库扫描（库存在时）：未标注率区间 + 孤例仅含已知项
# 执行：python -X utf8 tests/test_relation_type_whitelist_guard.py   （script-style 直跑）
#       亦可 python -X utf8 -m pytest tests/test_relation_type_whitelist_guard.py -q
# 验证方式：本文件自身
# 不适用条件：不判语义正误；CI 上无实库时第 6 组自动跳过（不伪造通过）
"""
from __future__ import annotations

import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
from md_cg import relations as R  # noqa: E402


# `pytest` 由**可选**导入承担：本件必须能直跑（CI 门禁 scripts/run_tests.py 对
# 根 tests/ 具名清单只发 `python <file>`，见 ROOT_TESTS 注释），故不得在模块顶层
# 硬依赖 pytest —— 否则无 pytest 的环境连 import 都过不去，收集面直接 ImportError。
# 保留软引用仅为了让 `-m pytest` 路径下的 skip 标记依然可被 pytest 识别。
try:
    import pytest  # noqa: F401 —— 可选：有则让 -m pytest 路径沿用原生 skip
except Exception:                                   # noqa: BLE001
    pytest = None


def approx(a, b, rel=1e-6):
    """`pytest.approx` 的等价最小实现（仅本文件用到的标量相对/绝对容差语义）。

    生效条件：浮点比较需容忍舍入误差时。不判复数/序列嵌套容差。
    """
    return abs(a - b) <= max(rel * max(abs(a), abs(b)), 1e-12)


def _skip(msg):
    """直跑与 pytest 路径统一的跳过出口。

    有 pytest 时抛 pytest.skip 的原生异常 —— `-m pytest` 下正确记为 **skipped**
    （否则本件在 pytest 路径会变成 failed，与改造前的 8 passed 1 skipped 不等价）；
    无 pytest 时抛本地 SkipCase，由 main() 打印 SKIP 且不计入通过也不计入失败。
    """
    if pytest is not None:
        pytest.skip(msg)
    raise SkipCase(msg)


class SkipCase(Exception):
    """用例主动跳过（不伪造通过）。"""


#: 直跑时也要把「pytest 原生 Skipped」当作跳过捕获：本机可能装了 pytest，
#: _skip() 会优先抛 pytest 原生异常；若 main() 只捕获 SkipCase，直跑会把它
#: 当失败（RC=1），与 -m pytest 路径的 8 passed 1 skipped 不等价
#: （2026-11-08 实测踩到）。故把原生 Skipped 一并纳入捕获元组。
_SKIP_TYPES = (SkipCase,)
if pytest is not None:
    try:
        from _pytest.outcomes import Skipped as _PytestSkipped
        _SKIP_TYPES = (SkipCase, _PytestSkipped)
    except Exception:                               # noqa: BLE001
        pass                                        # 私有模块改名也不致命：退化为 SkipCase


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
    assert approx(R.unlabeled_rate(d), 2 / 3)


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
        _skip("无实库（未设 MDCG_ROOT），跳过实库断言——不伪造通过")
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


# ---- script-style 入口（门禁直跑面）----
# 为什么必须补（2026-11-08，与 md_cg/test_issue192_move_layer_indices_guard.py 同族）：
# 本件原为纯 pytest-style（只有 `def test_*`、无 `__main__`），而 CI 门禁对根
# `tests/` 具名清单只发 `python <file>` —— 对 pytest-style 件该命令只做 define、
# 跑**零个**用例、RC 恒 0。实测（2026-11-07 留档于 run_tests.py ROOT_TESTS 注释）：
# 把区间断言改成恒假后直跑仍 RC=0，而 `-m pytest` 下 8 passed 1 skipped。
# ⇒ 收它进门禁必须先让它直跑真的执行断言。此处用两条**等价替换**而非给 CI 装 pytest：
#   · pytest.approx      → 本文件顶部 approx()（标量容差）
#   · pytest.skip        → _skip()/SkipCase（直跑打印 SKIP，不伪造通过）
# 这样既满足门禁「直跑执行断言」的硬要求，又不新增任何 CI 依赖面。
_ENTRY_CASES = (
    ("① 白名单覆盖存量 6 类", test_whitelist_covers_all_stock_types),
    ("① tension 在白名单", test_tension_is_whitelisted),
    ("② 空串合法且计入未标注率", test_empty_is_legal_but_counted),
    ("③ 笔误判 unknown", test_typo_is_unknown),
    ("④ observe 从不拦截", test_observe_never_blocks),
    ("④ enforce 只拦 unknown", test_enforce_blocks_unknown_only),
    ("④ resolve_mode 纯函数", test_mode_resolution_is_pure),
    ("⑤ 孤例与分布统计", test_singletons_and_distribution),
    ("⑥ 实库扫描（无库则 SKIP）", test_real_library_distribution),
)


def main():
    import traceback

    failed = []
    skipped = []
    for name, fn in _ENTRY_CASES:
        try:
            fn()
            print("  PASS %s" % name)
        except _SKIP_TYPES as exc:
            skipped.append(name)
            print("  SKIP %s: %s" % (name, exc))
        except Exception as exc:            # noqa: BLE001 —— 直跑要报全，不吞
            failed.append(name)
            print("  FAIL %s: %s: %s" % (name, type(exc).__name__, exc))
            traceback.print_exc()
    total = len(_ENTRY_CASES)
    passed = total - len(failed) - len(skipped)
    print("")
    print("===== SUMMARY %d passed, %d skipped, %d failed (共 %d) ====="
          % (passed, len(skipped), len(failed), total))
    print("VERDICT=%s" % ("PASS" if not failed else "FAIL"))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
