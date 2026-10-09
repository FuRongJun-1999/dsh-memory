# -*- coding: utf-8 -*-
r"""守卫 · issue #67：scrub 抽样**对照池不得被 3k 截断**（2026-10-09 DSH 端）。

缺陷（GitHub #67，本端实测坐实）：scrub._pick 无条件取池前 k*3 项再洗牌。而
_pool_candidates 只对**六个风险层**排序（stale/hot/unverified/orphan/disputed/
low_conf，见该函数末段六行 sort），pools["random"] 是**唯一不排序**的池。对它截断
等于把「随机基线」变成「索引前 3k 名」——对照面既非随机、又恒看不到后段人口，
「看起来没问题其实有问题」的记忆恰恰只能靠对照面发现（见 scrub 模块 docstring
开篇的确认偏差论述）⇒ 抽样结论无从代表全库。

修法（**只取本 issue 指明的子集**）：_pick 增 ordered 形参，仅当 ordered 为真时截断；
对照组（random 层）与 random-fill 传 ordered=False，风险层保持截断不变。

判据：
  G1 无序池不截断：长度 100 的池、k=2（窗口 6），多 seed 下必须能取到窗口外的项
  G2 有序池**行为不变**：同池同 seed，ordered=True 时取到的索引一律 < 6
  G3 池长不足窗口时两种取值**逐位相同**（截断本就无效果）
  G4 端到端：sample(strategy="random") 能取到 random 池窗口外的节点
  G5 配额未被顺手改动（_quota(n,"random") == {"random": n}）

运行：
  python -X utf8 -m md_cg.test_issue67_scrub_control_pool
  python -X utf8 -m md_cg.test_issue67_scrub_control_pool --mutate A
退出码：0 全绿 ｜ 1 断言失败 ｜ 2 锚点漂移（fail-closed）
"""
from __future__ import annotations

import contextlib
import inspect
import io
import os
import sys
import tempfile
import time

from . import scrub
from .mdcos import MdCGOS

PASS = 0
FAIL = 0
FAILS: list = []


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  [PASS] %s%s" % (name, ("  · " + detail) if detail else ""))
    else:
        FAIL += 1
        FAILS.append(name)
        print("  [FAIL] %s  · %s" % (name, detail))


def _idx_pool(n=100):
    """合成池：第 i 项的下标即 i（_pick 只按顺序切片，不关心语义）。"""
    return [("n%03d" % i, "随机基线") for i in range(n)]


def _picked_idxs(pool, k, ordered, seeds=range(30)):
    pos = {nid: i for i, (nid, _r) in enumerate(pool)}
    out = set()
    for s in seeds:
        for nid, _r in scrub._pick(pool, k, s, "random", ordered=ordered):
            out.add(pos[nid])
    return out


def _build_graph(root, n=40):
    cg = MdCGOS(root)
    for i in range(n):
        cg.add("n%03d" % i, "合成节点 %d" % i, layer="contextual",
               content_kind="code", verification_basis="test", consistency=False)
    cg.flush()
    return cg


def group_a(root=None):
    pool = _idx_pool(100)
    K = 2
    WINDOW = K * 3

    got = _picked_idxs(pool, K, ordered=False)
    outside = sorted(i for i in got if i >= WINDOW)
    check("G1 无序池（对照池）不截断：能取到窗口外的项",
          bool(outside), "取到窗口外下标 %s（窗口=%d）" % (outside[:6], WINDOW))

    kept = _picked_idxs(pool, K, ordered=True)
    check("G2 有序池（风险层）行为**不变**：取到的下标一律 < 窗口",
          kept and all(i < WINDOW for i in kept), "有序池下标集 %s" % sorted(kept)[:8])

    small = _idx_pool(5)                       # 池长 5 < 窗口 6 ⇒ 截断无效果
    a = [nid for nid, _r in scrub._pick(small, K, 7, "random", ordered=True)]
    b = [nid for nid, _r in scrub._pick(small, K, 7, "random", ordered=False)]
    check("G3 池长不足窗口时两种取值逐位相同", a == b, "%s vs %s" % (a, b))

    tmp = tempfile.mkdtemp(prefix="p67_")
    cg = _build_graph(os.path.join(tmp, "brain"), n=40)
    pools = scrub._pool_candidates(cg, now=time.time(),
                                   stale_days=scrub.STALE_DAYS,
                                   unverified_days=scrub.UNVERIFIED_DAYS)
    order = [nid for nid, _r in pools["random"]]
    pos = {nid: i for i, nid in enumerate(order)}
    N = 4
    far = set()
    for s in range(30):
        res = scrub.sample(cg, N, strategy="random", seed=s)
        for item in res.get("sample") or []:
            i = pos.get(item["node_id"])
            if i is not None and i >= N * 3:
                far.add(i)
    check("G4 端到端：sample(strategy=random) 能取到 random 池窗口外的节点",
          bool(far) and len(order) > N * 3,
          "池长=%d 窗口=%d 取到窗口外下标 %s" % (len(order), N * 3, sorted(far)[:6]))

    check("G5 配额未被顺手改动：_quota(n,random) == {random: n}",
          scrub._quota(7, "random") == {"random": 7}, str(scrub._quota(7, "random")))


_GROUPS = {"A": group_a}


# ---------------- 定点变异（内存注入；apply() 返回 restore()） ----------------

def _mut_control_truncated():
    """对照组退回截断（忽略 ordered）——复现 #67 缺陷形态。"""
    orig = scrub._pick

    def _pick(pool, k, seed, stratum, *, ordered=True):
        return orig(pool, k, seed, stratum, ordered=True)

    scrub._pick = _pick
    return lambda: setattr(scrub, "_pick", orig)


def _mut_risk_untruncated():
    """风险层也改成不截断（越过本 issue 的改动面）。"""
    orig = scrub._pick

    def _pick(pool, k, seed, stratum, *, ordered=True):
        return orig(pool, k, seed, stratum, ordered=False)

    scrub._pick = _pick
    return lambda: setattr(scrub, "_pick", orig)


#: 组 → [(变异名, 应用函数, 期望转红断言前缀集合)]
_MUTATIONS = {
    "A": [("对照组退回截断（#67 缺陷形态）", _mut_control_truncated, {"G1", "G4"}),
          ("风险层也改成不截断（越过改动面）", _mut_risk_untruncated, {"G2"})],
}

#: 源码锚点自检（命中次数必须恰为 1，否则实现已漂移、变异表失效）
_ANCHORS = [
    ("scrub._pick 的 ordered 形参在位",
     "def _pick(pool, k: int, seed, stratum: str, *, ordered: bool = True):", scrub),
    ("对照组调用点带 ordered=(s != random)", 'ordered=(s != "random")', scrub),
    ("random-fill 调用点带 ordered=False", '"random-fill", ordered=False', scrub),
]


def _anchor_preflight():
    bad = []
    for label, anchor, mod in _ANCHORS:
        n = inspect.getsource(mod).count(anchor)
        if n != 1:
            bad.append((label, n))
    if not bad:
        return 0
    for label, n in bad:
        print("  ANCHOR-MISS %s：命中 %d 次（期望 1）" % (label, n))
    print("  => 实现已漂移，变异表失效：退出码 2（fail-closed）")
    return 2


def _run_group(name, root=None):
    global PASS, FAIL
    PASS = FAIL = 0
    del FAILS[:]
    _GROUPS[name](root)
    return ({n.split(" ", 1)[0] for n in FAILS}, PASS, FAIL)


def _mutate(name):
    if name not in _MUTATIONS:
        print("未知组名 %r（可选 %s）" % (name, sorted(_MUTATIONS)))
        return 1
    rc = _anchor_preflight()
    if rc:
        return rc
    print("!! #67 定点变异自证 · 组 %s：内存注入退化，逐条要求**恰好**命中期望红项\n" % name)
    bad = []
    with contextlib.redirect_stdout(io.StringIO()):
        base_red, _, _ = _run_group(name)
    print("  未变异基线：红项 %d %s" % (len(base_red), "（应为 0）" if not base_red else sorted(base_red)))
    if base_red:
        bad.append("基线即转红：%s" % sorted(base_red))
    for mname, apply, expect in _MUTATIONS[name]:
        restore = apply()
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                red, _, _ = _run_group(name)
        except Exception as exc:                       # noqa: BLE001
            red = {"<变异体异常:%s>" % type(exc).__name__}
        finally:
            restore()
        ok = (red == expect)
        print("  [%s] %s → 红项 %s（期望 %s）" % ("OK" if ok else "BAD", mname, sorted(red), sorted(expect)))
        if not ok:
            bad.append("%s：得 %s 期望 %s" % (mname, sorted(red), sorted(expect)))
    if bad:
        print("\n变异自证失败：")
        for b in bad:
            print("  · " + b)
        return 1
    print("\n变异自证通过：%d 条退化各自**恰好**命中期望红项" % len(_MUTATIONS[name]))
    return 0


def main():
    print("[#67 scrub 对照池不截断] 正断言组 A")
    _run_group("A")
    print("\n==== #67 结果：%d 通过 / %d 失败 ====" % (PASS, FAIL))
    if FAILS:
        print("失败项：" + "、".join(FAILS))
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    if "--mutate" in sys.argv:
        i = sys.argv.index("--mutate")
        sys.exit(_mutate(sys.argv[i + 1] if i + 1 < len(sys.argv) else ""))
    sys.exit(main())
