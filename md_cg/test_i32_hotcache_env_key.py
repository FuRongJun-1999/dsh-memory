# -*- coding: utf-8 -*-
"""issue #32 守卫：query 缓存的**口径键**必须覆盖进程级开关（env）。

病灶（2026-09-24 审查复现）：v14 缺陷 C 修的是**参数面**（include_work /
roles / paths / fusion / judge_ranking / …），但还有一类口径来自**环境变量**
——MDCG_SEMANTIC / MDCG_EN_ATOMS / MDCG_UNIFY_QUERY。它们不入键时，同一 query
在切换开关后会命中**另一口径**的缓存（cached=True + 陈旧结果），表现为静默
错答：先按 MDCG_SEMANTIC=1 查一次写缓存，再关掉语义路重查，拿到的仍是
「语义路开启时」的排序。

修法（本件守门）：`hotcache._KEYED_EXTRA` 增列 `env_switch`，
调用方 `mdcos.search_rrf` 以 `hotcache.env_switch_key()` 填该键——开关一变
键就变，缓存自然不命中；同一口径内缓存收益不变。

断言（含能红旧实现的两条）：
  K1 _KEYED_EXTRA 登记 env_switch（清单真源，防漏登）
  K2 env_switch_key() 随开关取值变化（未设 = None 也进键）
  K3 semantic=1 首查：gold 经语义资格路命中（非缓存）
  K4 切到 semantic=0 后同 query **不命中**旧口径缓存（旧实现这里 cached=True）
  K5 切开关后的结果 == 关缓存重算的结果（无跨口径串味）
  K6 同口径重复查仍命中缓存（修完不许把缓存打废）

运行：python -m md_cg.test_i32_hotcache_env_key
"""
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from md_cg import eval_common as ec                              # noqa: E402
from md_cg import hotcache, mdcos                                # noqa: E402

PASS = FAIL = 0
FAILS = []


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  OK   {name}")
    else:
        FAIL += 1
        FAILS.append(name)
        print(f"  FAIL {name}  {detail}")


def _mk(root):
    from md_cg.mdcos import MdCGOS
    return MdCGOS(root, autoflush=500)


def _query(cg, q="horse meat"):
    res, meta = cg.search_rrf(q, k=5, paths=("lexical",), judge=False,
                              record=False)
    return [r[0]["id"] for r in res], res, meta


def main():
    ec.unlock_global_cap()
    ec.use_jaccard()

    print("== K1/K2 清单真源与键值 ==")
    check("K1 _KEYED_EXTRA 登记 env_switch",
          "env_switch" in hotcache._KEYED_EXTRA, str(hotcache._KEYED_EXTRA))
    os.environ.pop("MDCG_SEMANTIC", None)
    before = hotcache.env_switch_key()
    os.environ["MDCG_SEMANTIC"] = "1"
    after = hotcache.env_switch_key()
    os.environ.pop("MDCG_SEMANTIC", None)
    check("K2 env_switch_key() 随开关变化（未设=None 也进键）",
          before != after and any(v is None for _k, v in before),
          f"{before} vs {after}")

    tmp = tempfile.mkdtemp(prefix="mdcg_i32_")
    try:
        rooth = os.path.join(tmp, "hot")
        rootn = os.path.join(tmp, "nocache")
        for root in (rooth, rootn):
            cg = _mk(root)
            # gold 只有 fm.semantic（「马 肉」）能对上英文 query；正文是中文，
            # 归一路关闭时词法零交集 → 语义路开关是唯二变量（另一个是归一层）。
            cg.add("gold", "今天午饭吃了马肉，味道不错，下次还做。",
                   layer="knowledge", semantic="马 肉", verification_basis="data")
            cg.add("d1", "下午去市场买了马，价格比昨天便宜一些。",
                   layer="knowledge", verification_basis="data")
            cg.flush()
            cg.close()

        print("== K3~K6 跨口径缓存（MDCG_HOTCACHE=1，归一层关闭以隔离变量）==")
        os.environ["MDCG_HOTCACHE"] = "1"
        os.environ["MDCG_UNIFY_QUERY"] = "0"
        cg = _mk(rooth)
        try:
            os.environ["MDCG_SEMANTIC"] = "1"
            ids_sem, _r, m_sem = _query(cg)
            check("K3 semantic=1 首查：gold 命中且非缓存",
                  bool(ids_sem) and ids_sem[0] == "gold"
                  and m_sem.get("cached") is not True,
                  f"{ids_sem} cached={m_sem.get('cached')}")

            os.environ.pop("MDCG_SEMANTIC", None)
            ids_off, _r2, m_off = _query(cg)
            check("K4 切开关后不命中旧口径缓存（旧实现 cached=True）",
                  m_off.get("cached") is not True,
                  f"cached={m_off.get('cached')} ids={ids_off}")
            check("K5 切开关后结果与 semantic=1 不同（无跨口径串味）",
                  ids_off != ids_sem,
                  f"sem={ids_sem} / off={ids_off}")

            _ids3, _r3, m3 = _query(cg)
            check("K6 同口径重复查仍命中缓存（缓存未被打废）",
                  m3.get("cached") is True, json.dumps(m3, default=str)[:160])
        finally:
            cg.close()
            os.environ.pop("MDCG_SEMANTIC", None)

        # 旁路对照：不挂热缓存重算 semantic=0 的结果必须与 K5 一致
        os.environ.pop("MDCG_HOTCACHE", None)
        cg2 = _mk(rootn)
        try:
            ids_plain, _r4, _m4 = _query(cg2)
        finally:
            cg2.close()
            os.environ.pop("MDCG_UNIFY_QUERY", None)
        check("K5b 与旁路（无缓存）重算结果一致",
              ids_plain == ids_off, f"cached={ids_off} plain={ids_plain}")
    finally:
        for k in ("MDCG_HOTCACHE", "MDCG_SEMANTIC", "MDCG_UNIFY_QUERY"):
            os.environ.pop(k, None)
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n" + "=" * 64)
    print(f"PASS={PASS}  FAIL={FAIL}")
    if FAILS:
        print("失败项：" + "；".join(FAILS))
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
