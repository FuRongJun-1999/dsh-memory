# -*- coding: utf-8 -*-
"""issue #157 余项守卫：hyperedge 幂等键位宽 / stgidx 桶内下标表 + swap-pop / refindex 水位 sha256 列。

真源：外部审计 ybyz2 #157（三项：hyperedge 幂等键 40bit、stgidx 用 list.remove O(N^2)、
refindex.Ledger.is_fresh 只用 (size, mtime) 漏哈希）。

本件三处改动的**独立反面证明**（反退化探针）：
  H hyperedge.node_id_for 幂等键由 sha1[:10]（40 bit）改 sha1[:12]（48 bit），
    与同仓 codeindex/docindex 的同类键对齐（改前实测 146 万行内即撞出一条同 id
    ⇒ 同 id 幂等 upsert 会静默覆盖 = 回执丢失）。
  S stgidx.StgIndex 的四个桶各配一张**下标表**，摘除由 list.remove(O(桶长)) 换
    swap-pop(O(1))；桶内顺序因此不再保证物理序，由 subset 出口统一回排保住契约。
  R refindex.Ledger 的水位条目补 sha256 列，is_fresh 在 (size, mtime) 双等后再比
    整文件哈希，堵住「等长改写 + mtime 被还原」沿用旧水位静默跳过已改源。

运行：
  python -X utf8 -m md_cg.test_issue157b_index_remainder
  python -X utf8 -m md_cg.test_issue157b_index_remainder --mutate A

退出码（fail-closed）：
  0 = 全绿 / 变异逐条**恰好**命中期望红项；1 = 有断言失败或变异未按预期转红；
  2 = ANCHOR-MISS（变异锚点在盘上源码里命中次数 != 1，实现漂移必须硬失败）。

环境：全程 tempfile 沙箱（不碰在役库）；源码形态断言读**盘上文件**（io.open），
不用 inspect.getsource——变异会把实现 exec 到内存，getsource 会读到变异体。
"""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from md_cg import hyperedge as H  # noqa: E402
from md_cg import refindex as RF  # noqa: E402
from md_cg import stgidx as S     # noqa: E402

_PASS, _FAIL = [], []
_HYPER = os.path.join(_HERE, "hyperedge.py")
_STG = os.path.join(_HERE, "stgidx.py")
_REF = os.path.join(_HERE, "refindex.py")


def ok(cond, msg, extra=""):
    (_PASS if cond else _FAIL).append(msg)
    print(("  PASS " if cond else "  FAIL ") + msg + (("  <- " + str(extra)) if (extra and not cond) else ""))


def _src(path):
    return io.open(path, encoding="utf-8", newline="").read()


# ------------------------------------------------------------------ H hyperedge
def h1():
    print("== H1-H3 hyperedge 幂等键位宽 ==")
    row = {c: "v" + str(i) for i, c in enumerate(H.LEDGER_COLUMNS)}
    nid = H.node_id_for(row)
    ok(len(nid) == 15 and nid.startswith("he_") and len(nid) - 3 == 12,
       "H1 幂等键 = he_ + 12 位十六进制（48 bit，id 长 15）", nid)
    import hashlib
    canon = "".join("%d:%s" % (len(row[c]), row[c]) for c in H.LEDGER_COLUMNS)
    ok(nid == "he_" + hashlib.sha1(canon.encode("utf-8")).hexdigest()[:12],
       "H1b 与 sha1(canon)[:12] 逐位一致（不是写死常量）", nid)
    same = H.node_id_for(dict(row))
    alt = H.node_id_for({**row, H.LEDGER_COLUMNS[0]: "别的内容"})
    ok(same == nid and alt != nid, "H2 同行恒同 id、异行不同 id（幂等 + 区分）", (same, alt))
    seen, dup = set(), 0
    for i in range(200000):
        r = {"x%d_%d" % (i, j): None for j in ()}
        r = {c: "s%d_%d" % (i, j) for j, c in enumerate(H.LEDGER_COLUMNS)}
        k = H.node_id_for(r)
        if k in seen:
            dup += 1
        else:
            seen.add(k)
    ok(dup == 0, "H2b 20 万抽样零碰撞（40 bit 下期望碰撞数约 0.018，非判别主项）", dup)
    src = _src(_HYPER)
    code = [l for l in src.splitlines() if "hexdigest()" in l and "def " not in l]
    ok(any("[:12]" in l for l in code) and not any("[:10]" in l for l in code),
       "H3 实现行用 [:12]（读盘上文件）", code[:2])
    ok(src.count("he_<sha1(六列值 join)[:12]>") == 1
       and src.count("len:val\u300d拼接)[:12]>") == 1,
       "H3b 模块文档串与 node_id_for 生效条件串同步为 [:12]（doc 与实现不漂移）")


# ------------------------------------------------------------------ S stgidx
def _mk_nodes(n):
    out = {}
    for i in range(n):
        out["n%06d" % i] = {"session": "s%d" % (i % 16), "layer": "knowledge",
                            "temporal": 1000.0 + (i % 997)}
    return out


def s1():
    print("== S1-S3 stgidx 下标表 + swap-pop ==")
    nodes = _mk_nodes(4000)
    ix = S.build({"nodes": nodes})
    for k in list(nodes)[:1000]:
        ix.remove(k)
    rest = {k: v for k, v in nodes.items() if k in ix.pos}
    probs = S.verify(ix, rest)
    ok(not probs, "S1 删 1000 条后 verify 无不一致（含下标表逆映射不变量）", probs[:3])
    # 下标表确实与桶列表互逆（独立于 verify 再核一次）
    bad = 0
    for sid, lst in ix.by_session.items():
        im = ix.ix_session.get(sid) or {}
        bad += sum(1 for i, x in enumerate(lst) if im.get(x) != i)
    ok(bad == 0, "S1b 下标表逐位互逆（抽样核 by_session 各桶）", bad)
    # swap-pop 真的换过位：桶内顺序已非物理序，而 subset 出口仍回排成物理序
    n2 = {"a": {"session": "s1", "layer": "k", "temporal": 1.0},
          "b": {"session": "s1", "layer": "k", "temporal": 2.0},
          "c": {"session": "s1", "layer": "k", "temporal": 3.0},
          "d": {"session": "s1", "layer": "k", "temporal": 4.0}}
    ix2 = S.build({"nodes": n2})
    ix2.remove("b")
    raw = list(ix2.by_session["s1"])
    got = ix2.subset(session="s1")[0]
    ok(raw != ["a", "c", "d"], "S2 桶内已被 swap-pop 换位（等于物理序则说明未生效）", raw)
    ok(got == ["a", "c", "d"], "S2b subset 出口仍回**物理序**（契约保住）", got)
    ok(not S.verify(ix2, {k: v for k, v in n2.items() if k != "b"}),
       "S2c 换位后不变量仍成立", S.verify(ix2, {k: v for k, v in n2.items() if k != "b"}))
    ix3 = S.build({"nodes": _mk_nodes(20000)})
    keys = list(ix3.pos)
    t = time.perf_counter()
    for k in keys:
        ix3.remove(k)
    ms = (time.perf_counter() - t) * 1000.0
    ok(ms < 200.0, "S3 批量删 untimed 脱离 O(N^2)：N=20000 全清 < 200ms（改前实测 553ms）",
       round(ms, 2))


# ------------------------------------------------------------------ R refindex
def r1():
    print("== R1-R3 refindex 水位 sha256 列 ==")
    tmp = tempfile.mkdtemp(prefix="i157b_guard_")
    p = os.path.join(tmp, "src_sample.py")
    A = "VALUE_AAAA = 1\n" * 40
    B = "VALUE_BBBB = 1\n" * 40          # 与 A 等长
    with io.open(p, "w", encoding="utf-8", newline="") as f:
        f.write(A)
    led = RF.Ledger(tmp)
    led.record("src_sample.py", p, "code_ref", [{"id": "x", "lineno": 1, "end": 2, "hash": "h"}])
    led.save()
    e = led.load()["files"][RF._src_key(p)]
    ok(isinstance(e.get("sha256"), str) and len(e["sha256"]) == 64,
       "R1 水位条目含 64 位 sha256 列", sorted(e.keys()))
    st0 = os.stat(p)
    ok(led.is_fresh("src_sample.py", p) is True, "R1b 未改动 → fresh（不误伤快路径）")
    with io.open(p, "w", encoding="utf-8", newline="") as f:
        f.write(B)
    os.utime(p, ns=(st0.st_atime_ns, st0.st_mtime_ns))
    st1 = os.stat(p)
    ok(st0.st_size == st1.st_size and st0.st_mtime_ns == st1.st_mtime_ns,
       "R2 前置：等长改写且 mtime 逐位还原（size/mtime 双判据在此必失效）",
       (st0.st_size, st1.st_size))
    ok(led.is_fresh("src_sample.py", p) is False,
       "R2 等长改写 + mtime 还原 → is_fresh 为 False（#157 漏判闭合）")
    led2 = RF.Ledger(tmp)
    d = led2.load()
    d["files"][RF._src_key(p)].pop("sha256", None)
    led2._d = d
    ok(led2.is_fresh("src_sample.py", p) is False,
       "R3 旧版条目（无 sha256 列）→ False（触发就地重切补列，优雅迁移）")
    import shutil
    shutil.rmtree(tmp, ignore_errors=True)


_ITEMS = [h1, s1, r1]


# ------------------------------------------------------------------ 变异
def _mut_hyper_10():
    """变异①：幂等键截断回退 [:12] -> [:10]（= 改动前形态）。"""
    live = H.node_id_for
    src = _src(_HYPER)
    ns = {}
    exec(compile(src.replace("hexdigest()[:12]", "hexdigest()[:10]"), "hyper_mut.py", "exec"), ns)
    H.node_id_for = ns["node_id_for"]
    globals()["H"].node_id_for = ns["node_id_for"]
    import md_cg.hyperedge as _h
    _h.node_id_for = ns["node_id_for"]

    def restore():
        _h.node_id_for = live
    return restore


def _old_unclassify(self, nid):
    """改动前实现原文（list.remove 版）——仅用于变异自证。"""
    import bisect as _b
    sid, layer, bucket, t = self.cls.pop(nid)
    lst = self.by_session[sid]
    lst.remove(nid)
    if not lst:
        self.by_session.pop(sid, None)
    lst = self.by_layer[layer]
    lst.remove(nid)
    if not lst:
        self.by_layer.pop(layer, None)
    if bucket == 0:
        i = _b.bisect_left(self.by_time, (t, nid))
        if i >= len(self.by_time) or self.by_time[i] != (t, nid):
            raise KeyError(nid)
        del self.by_time[i]
    elif bucket == 1:
        self.nonfinite.remove(nid)
    else:
        self.untimed.remove(nid)


def _mut_old_unclassify():
    """变异②：swap-pop + 下标表回退为 list.remove（= 改动前形态）⇒ 不变量/序/性能断言转红。"""
    live = S.StgIndex._unclassify
    S.StgIndex._unclassify = _old_unclassify

    def restore():
        S.StgIndex._unclassify = live
    return restore


def _mut_no_sha_compare():
    """变异③：is_fresh 去掉哈希比对（= 只看 size/mtime 的改动前形态）。"""
    live = RF.Ledger.is_fresh
    src = _src(_REF)
    # exec 整个模块源码：须带 __package__（相对导入 from .fsutil import ...）
    ns = {"__name__": "md_cg._ref_mut", "__package__": "md_cg", "__file__": _REF}
    new_src = src.replace("        want = e.get(\"sha256\")\n"
                          "        if not want:\n"
                          "            return False                # 旧版水位无哈希列 ⇒ 判不新鲜、重切补列\n"
                          "        return _sha256_file(fp) == want",
                          "        return True")
    if new_src == src:
        return None                       # 锚点漂移 ⇒ 交给 ANCHOR-MISS 前置拦
    exec(compile(new_src, "ref_mut.py", "exec"), ns)
    RF.Ledger.is_fresh = ns["Ledger"].is_fresh

    def restore():
        RF.Ledger.is_fresh = live
    return restore


#: 组 -> [(变异名, 应用函数, 期望转红断言前缀集合)]——期望集合按**实测**填
_MUTATIONS = {
    "A": [("幂等键截断回退 [:10]（40bit）", _mut_hyper_10, {"H1", "H1b"}),
          ("swap-pop 回退 list.remove", _mut_old_unclassify,
           {"S1", "S1b", "S2", "S2c", "S3"}),
          ("is_fresh 去掉哈希比对", _mut_no_sha_compare, {"R2", "R3"})],
}


def _anchor_preflight():
    """变异锚点自检：读**盘上文件**（不用 inspect.getsource）。"""
    bad = []
    n = _src(_HYPER).count("hexdigest()[:12]")
    if n != 1:
        bad.append(("hyperedge hexdigest()[:12]", n))
    txt = _src(_REF)
    if txt.count("        return _sha256_file(fp) == want") != 1:
        bad.append(("refindex sha256 比对行", txt.count("return _sha256_file(fp) == want")))
    if "def _unclassify(self, nid):" not in _src(_STG):
        bad.append(("stgidx _unclassify", 0))
    if not bad:
        return 0
    for label, n in bad:
        print("  ANCHOR-MISS " + label + "：命中 " + str(n) + " 次（期望 1）")
    print("  => 实现已漂移，变异表失效：退出码 2（fail-closed）")
    return 2


def _run():
    _PASS.clear(); _FAIL.clear()
    for fn in _ITEMS:
        fn()
    return {n.split(" ", 1)[0] for n in _FAIL}, len(_PASS), len(_FAIL)


def _mutate(name):
    if name not in _MUTATIONS:
        print("未知组名 " + repr(name) + "（可选 " + str(sorted(_MUTATIONS)) + "）")
        return 1
    rc = _anchor_preflight()
    if rc:
        return rc
    print("!! #157b 定点变异自证：内存注入退化，逐条要求**恰好**命中期望红项\n")
    red, _, _ = _run()
    print("  未变异基线：红项 " + str(len(red)) + ("（应为 0）" if not red else " " + str(sorted(red))))
    bad = []
    if red:
        bad.append("基线即转红：" + str(sorted(red)))
    for i, (mname, apply, expect) in enumerate(_MUTATIONS[name]):
        try:
            restore = apply()
        except Exception as exc:                       # noqa: BLE001
            bad.append("变异" + str(i + 1) + " " + mname + "：施加即抛 "
                       + type(exc).__name__ + ": " + str(exc)[:120])
            print("  变异" + str(i + 1) + " " + mname + "  施加即抛 "
                  + type(exc).__name__ + ": " + str(exc)[:120])
            continue
        if restore is None:
            bad.append("变异" + str(i + 1) + " " + mname + "：锚点漂移，未施加")
            print("  变异" + str(i + 1) + " " + mname + "  锚点漂移")
            continue
        try:
            got, _, _ = _run()
        except Exception as exc:                       # noqa: BLE001
            got = {"<变异体异常:" + type(exc).__name__ + ">"}
        finally:
            restore()
        hit = got == expect
        if not hit:
            bad.append("变异" + str(i + 1) + " " + mname + "：红项 " + str(sorted(got))
                       + " != 期望 " + str(sorted(expect)))
        print("  变异" + str(i + 1) + " " + mname + "  红项 " + str(len(got))
              + "（期望 " + str(len(expect)) + "）"
              + ("PASS" if hit else "**FAIL** 实=" + str(sorted(got)) + " 期=" + str(sorted(expect))))
    print("\n变异自证：" + ("PASS（逐条恰好命中期望红项）" if not bad else "FAIL —— " + "；".join(bad)))
    return 0 if not bad else 1


def main():
    if "--mutate" in sys.argv:
        i = sys.argv.index("--mutate")
        return _mutate(sys.argv[i + 1] if i + 1 < len(sys.argv) else "")
    print("#157 余项守卫 · hyperedge 幂等键位宽 / stgidx 下标表+swap-pop / refindex 水位 sha256")
    print("=" * 74)
    red, npass, nfail = _run()
    print("=" * 74)
    print("通过 " + str(npass) + " / 失败 " + str(nfail))
    if _FAIL:
        print("失败项：" + "，".join(_FAIL))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
