#!/usr/bin/env python
# -*- coding: utf-8 -*-
r"""配置面反向对账守卫的**判别力自证**（issue #120）。

# 功能名：test_check_config_env_registry —— 反向对账守卫的自证件
# 生效条件：与 scripts/check_config_env_registry.py 同目录（直接 import 该模块的判据单点）
# 子功能：
#   [1] 合成语料：三形态读取被认、写入形态不被认、别名面按 _ENV 约定收窄、名字面按前缀收窄；
#   [2] compare() 三条判据（C1 新缺口 / C2 基线已登记 / C3 基线已不读）逐个打桩；
#   [3] 定点变异：run(..., mutate=True) 必须 exit 1（在 mdcg.py 注入未登记 env 读取）；
#   [4] 真实仓：run(REPO) 必须 exit 0（把「基线态绿」钉成回归）。
# 执行：python -X utf8 scripts/test_check_config_env_registry.py [--mutate]
# 验证方式：末行「通过 N / 失败 M」；退出码 0=全绿，1=有失败
# 不适用条件：不判 registry 条目语义（另见 issue #138）；不判缺省值合理性（见 config_registry_guard G2）
"""
from __future__ import annotations

import argparse
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import check_config_env_registry as G                     # noqa: E402

PASS = FAIL = 0
FAILS = []


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  [PASS] %s%s" % (name, ("  · " + str(detail)) if detail else ""))
    else:
        FAIL += 1
        FAILS.append(name)
        print("  [FAIL] %s  · %s" % (name, detail))
    return bool(cond)


CORPUS = {
    "md_cg/a.py": (
        "import os\n"
        "X_ENV = \"MDCG_ALIASED\"\n"
        "STATE = \"ACCEPT\"\n"
        "def f():\n"
        "    return (os.environ.get(\"MDCG_GET\"), os.environ[\"MDCG_SUB\"],\n"
        "            os.getenv(\"MDCG_GETENV\"), os.environ.get(X_ENV),\n"
        "            os.environ.get(\"DEEPSEEK_API_KEY\"), STATE)\n"
    ),
    "md_cg/b.py": (
        "import os\n"
        "def w():\n"
        "    os.environ[\"MDCG_WRITTEN\"] = \"1\"\n"
        "    os.environ.update(MDCG_UPDATED=\"1\")\n"
    ),
}


def group_scan():
    print("\n[1] 合成语料：读取面识别与收窄")
    reads = G.collect_env_reads(CORPUS)
    for n in ("MDCG_GET", "MDCG_SUB", "MDCG_GETENV", "MDCG_ALIASED"):
        check("认读取 %s" % n, n in reads, reads.get(n))
    check("写形态 environ[X]= 不被认", "MDCG_WRITTEN" not in reads)
    check("写形态 environ.update(X=) 不被认", "MDCG_UPDATED" not in reads)
    check("非 _ENV 后缀常量不算别名（ACCEPT）", "ACCEPT" not in reads, sorted(reads))
    check("非本仓前缀不入判据面（DEEPSEEK_API_KEY）", "DEEPSEEK_API_KEY" not in reads, sorted(reads))


def group_compare():
    print("\n[2] compare()：C1/C2/C3 判据")
    reads = {"MDCG_A": ["x:1"], "MDCG_B": ["x:2"], "MDCG_C": ["x:3"]}
    new, sr, sg = G.compare(reads, {"MDCG_A"}, {"MDCG_B": {}, "MDCG_GONE": {}})
    check("C1 新缺口 = MDCG_C", new == ["MDCG_C"], new)
    check("C2 无已登记项", sr == [], sr)
    check("C3 已不读项 = MDCG_GONE", sg == ["MDCG_GONE"], sg)
    new2, sr2, _ = G.compare({"MDCG_A": ["x:1"]}, {"MDCG_A"}, {"MDCG_A": {}})
    check("C2 捕「基线条目已进登记面」", sr2 == ["MDCG_A"], sr2)
    check("C1 无缺口（已登记）", new2 == [], new2)


class _FakeCV:
    """C5 打桩用的假校验器（只带判据要用的三样）。"""

    def __init__(self, rules, true_vocab):
        self.RULES = rules
        self._TRUE = true_vocab


def group_c5():
    print("\n[5] C5：校验器口径 ↔ 源码真值")
    src = {"md_cg/x.py": 'v = os.environ.get("MDCG_STRICT") == "1"\n'
                         'w = os.environ.get("MDCG_INVERT") == "0"\n'
                         'e = os.environ.get("MDCG_ENUMISH") == "raw"\n'
                         'u = os.environ.update(MDCG_WRITEONLY="1")\n'}
    cv = _FakeCV({"MDCG_STRICT": {"type": "bool", "bool_like": True},
                  "MDCG_INVERT": {"type": "bool", "bool_like": True},
                  "MDCG_ENUMISH": {"type": "bool", "bool_like": True},
                  "MDCG_WRITEONLY": {"type": "bool", "bool_like": True}},
                 ("1", "true", "yes"))
    mis, unknown, wide = G.validator_mismatches(src, cv)
    check("C5 捕「== 1」宽词表失配", "MDCG_STRICT" in mis, mis)
    check("C5 捕「枚举值被当布尔」失配", "MDCG_ENUMISH" in mis, mis)
    check("C5 反相形态 == 0 不误伤（非 0 即真）", "MDCG_INVERT" not in mis, mis)
    check("C5 只认读取行（update 不产生字面量）", "MDCG_WRITEONLY" in unknown, unknown)
    cv2 = _FakeCV({"MDCG_STRICT": {"type": "bool", "bool_like": True}}, ("1",))
    mis2, _u, _w = G.validator_mismatches(src, cv2)
    check("C5 词表收窄到源码同口径 ⇒ 不报", "MDCG_STRICT" not in mis2, mis2)
    # 定点变异：账本被清空 ⇒ 守卫必红（证明账本是承重的，不是装饰）
    saved = G.VALIDATOR_LEDGER
    try:
        G.VALIDATOR_LEDGER = {"MDCG_ZZZ_STALE_LEDGER_PROBE": "陈旧条探针"}
        rc = G.run(_REPO, G.BASELINE)
    finally:
        G.VALIDATOR_LEDGER = saved
    check("变异（注入陈旧账本条）⇒ exit=1", rc == 1, "exit=%s" % rc)


def group_mutation():
    print("\n[3] 定点变异：注入未登记 env 读取 ⇒ 必红")
    rc = G.run(_REPO, G.BASELINE, as_json=False, mutate=True)
    check("变异后 exit=1", rc == 1, "exit=%s" % rc)


def group_repo():
    print("\n[4] 真实仓：基线态必须绿")
    rc = G.run(_REPO, G.BASELINE, as_json=False)
    check("本仓 exit=0（基线不陈旧、无新缺口）", rc == 0, "exit=%s" % rc)


def main(argv):
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("--mutate", action="store_true")
    a = ap.parse_args(argv)
    group_scan()
    group_compare()
    group_c5()
    if a.mutate:
        group_mutation()
    group_repo()
    print("\n通过 %d / 失败 %d" % (PASS, FAIL))
    if FAIL:
        print("FAILS: " + ", ".join(FAILS))
    return 0 if not FAIL else 1


def test_check_config_env_registry():
    """pytest 入口：合成语料 + 判据 + 真实仓基线态（不含变异，变异由 --mutate 显式触发）。"""
    assert main([]) == 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
