# -*- coding: utf-8 -*-
"""守卫 · issue #78 并发面本体：默认导出路径的**原子占位**（2026-10-09 DSH 端）。

缺陷（本体，修前）：export._default_out 用 os.path.exists **先查后建**
（check-then-act）。两个线程可同时判定「目标不存在」并选中**同一路径** ⇒ 后发布者
覆盖前者，而**两次调用都返回 ok**（静默丢快照）。1ceefd3f 的碰撞自增只覆盖
**串行同秒**面，未覆盖该竞态。

修法（本笔）：把「选路径」从查询变成内核级互斥的创建——_claim_path 用
os.open(O_CREAT|O_EXCL|O_WRONLY) 原子占位，并发下至多一个调用者占到同一路径，
其余让位到 _1/_2…。_default_out 保持**纯查询**（其已声明语义，见
test_export_default_collision.py 的 G1 口径），只作**首选名（hint）**。

判据：
  G1 判据单点形态：_claim_path 在位、首选名零兼容影响、让位不覆盖既有内容
  G2 真并发占位：8 线程同时占同一首选名 ⇒ 8 个**互异**路径，盘上 8 份
  G3 端到端并发导出：两线程默认导出 ⇒ 互异 out、盘上 2 份、各自内容完整
  G4 串行三次默认导出 ⇒ 3 份互异（1ceefd3f 串行面回归）
  G5 无 .tmp 残留、无空快照残留
  G6 _default_out 仍是**纯查询**（不改其已声明语义——本笔的边界）
  G7 显式 out 不走占位（#85③ 覆盖护栏的语义面不受影响）
  G8 源码锚点计数齐备（锚点漂移 fail-closed）

运行：
  python -X utf8 -m md_cg.test_issue78_export_concurrency
  python -X utf8 -m md_cg.test_issue78_export_concurrency --mutate A
退出码：0 全绿 ｜ 1 断言失败 ｜ 2 锚点漂移（fail-closed）
"""
from __future__ import annotations

import inspect
import io
import json
import os
import sys
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import export
from .mdcos import MdCGOS

PASS = 0
FAIL = 0
FAILS: list = []

_TS = "20261008_214500"

#: 源码锚点（字面 → 期望出现次数）。实现漂移则计数变 ⇒ 变异表失效 ⇒ exit 2。
_SRC_COUNTS = [
    ("def _claim_path(preferred: str) -> str:", 1),
    # 让位循环 + 候选全满的兜底各一次
    ("os.open(cand, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)", 2),
    ("out_path = _claim_path(out_path)", 1),
    ("_claim = not out", 3),          # graph / nodes / slice 三处调用点
    ("claim=_claim", 3),
]


def _file_src():
    """读**落盘源码**（不是运行时对象）——变异自证里被 patch 的函数会让断言读到
    变异体，故源码形态断言必须读文件。"""
    with io.open(os.path.join(os.path.dirname(os.path.abspath(export.__file__)),
                              "export.py"), encoding="utf-8") as f:
        return f.read()


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  [PASS] %s%s" % (name, ("  · " + detail) if detail else ""))
    else:
        FAIL += 1
        FAILS.append(name)
        print("  [FAIL] %s  · %s" % (name, detail))


def _rm(path):
    """幂等删除（变异体下同一路径可能被删两次——清理不得中断断言组）。"""
    try:
        os.remove(path)
    except OSError:
        pass


def _cg(root):
    g = MdCGOS(root, actor="i78-guard")
    g.add("n1", "value = 1", layer="contextual", content_kind="code",
          verification_basis="test", consistency=False)
    return g


def _concurrent_claim(root, n=8):
    """n 个线程在同一个 barrier 上同时占同一首选名。"""
    preferred = os.path.join(root, "export_graph_%s.jsonl" % _TS)
    barrier = threading.Barrier(n)
    got, lock = [], threading.Lock()

    def worker():
        barrier.wait(timeout=20)
        p = export._claim_path(preferred)
        with lock:
            got.append(p)

    ts = [threading.Thread(target=worker) for _ in range(n)]
    for t in ts:
        t.start()
    for t in ts:
        t.join(timeout=30)
    return preferred, got


def group_a(root=None):
    tmp = tempfile.mkdtemp(prefix="i78_guard_")

    # G1 判据单点形态
    check("G1a 判据单点在位（可调用）", callable(export._claim_path))
    preferred = os.path.join(tmp, "export_graph_%s.jsonl" % _TS)
    first = export._claim_path(preferred)
    check("G1b 首选名零兼容影响：未被占用时原样返回首选名",
          first == preferred, os.path.basename(first))
    Path(first).write_text("SNAPSHOT-1", encoding="utf-8")
    second = export._claim_path(preferred)
    check("G1c 已占用时让位到 _1（同秒不再同名）",
          second == os.path.join(tmp, "export_graph_%s_1.jsonl" % _TS),
          os.path.basename(second))
    check("G1d 让位**不覆盖**既有内容（首份原样）",
          Path(first).read_text(encoding="utf-8") == "SNAPSHOT-1")
    for p in (first, second):
        _rm(p)

    # G2 真并发占位
    _, got = _concurrent_claim(tmp, n=8)
    check("G2a 8 线程同时占位 ⇒ 8 个互异路径", len(set(got)) == 8 and len(got) == 8,
          "互异=%d/取得=%d" % (len(set(got)), len(got)))
    on_disk = [f for f in os.listdir(tmp) if f.endswith(".jsonl")]
    check("G2b 盘上恰 8 份占位（无互相覆盖）", len(on_disk) == 8, "盘上=%d" % len(on_disk))
    for f in on_disk:
        _rm(os.path.join(tmp, f))

    # G3 端到端并发导出
    cg = _cg(tmp)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futs = [pool.submit(export.export_graph, cg) for _ in range(2)]
        res = [f.result(timeout=60) for f in futs]
    outs = [r["out"] for r in res]
    check("G3a 两线程默认导出取到互异路径", len(set(outs)) == 2,
          str([os.path.basename(o) for o in outs]))
    check("G3b 两次调用都 ok", all(r.get("ok") for r in res))
    ok_content = True
    for r in res:
        rows = [json.loads(x) for x in
                Path(r["out"]).read_text(encoding="utf-8").splitlines()]
        if len(rows) != r["written"] or Path(r["out"]).stat().st_size != r["bytes"]:
            ok_content = False
    check("G3c 两份快照各自完整（行数=written、大小=bytes）", ok_content)
    check("G3d 两份内容一致（同一库、同秒导出）",
          Path(outs[0]).read_bytes() == Path(outs[1]).read_bytes())
    for o in set(outs):
        _rm(o)

    # G4 串行三次（1ceefd3f 回归）
    ser = [export.export_graph(cg) for _ in range(3)]
    check("G4 串行三次默认导出 ⇒ 3 份互异（串行面未回退）",
          len({r["out"] for r in ser}) == 3,
          str([os.path.basename(r["out"]) for r in ser]))
    for r in ser:
        _rm(r["out"])

    # G5 残留
    leftover_tmp = [f for f in os.listdir(tmp) if f.endswith(".tmp")]
    # 只数本笔产出的快照（export_*.jsonl）——MdCGOS 自己的 _audit.jsonl 不是快照
    leftover_jsonl = [f for f in os.listdir(tmp)
                      if f.startswith("export_") and f.endswith(".jsonl")]
    check("G5 无 .tmp / 无空快照残留",
          not leftover_tmp and not leftover_jsonl,
          "tmp=%s 快照=%s" % (leftover_tmp, leftover_jsonl))

    # G6 _default_out 仍是纯查询（本笔边界）
    probe_root = tempfile.mkdtemp(prefix="i78_probe_")
    cg2 = _cg(probe_root)
    a1 = export._default_out(cg2, "graph")
    a2 = export._default_out(cg2, "graph")
    a3 = export._default_out(cg2, "graph")
    check("G6a _default_out 仍是纯查询：连问三次同一答案",
          a1 == a2 == a3, os.path.basename(a1))
    check("G6b _default_out 不创建文件（未改其已声明语义）",
          not os.path.exists(a1), "存在=%s" % os.path.exists(a1))

    # G7 显式 out 不走占位（关键：**已存在**的显式目标也不得被让位改名——
    # 覆盖与否由 mcp_server 的 #85③ 护栏把关，不由本笔的占位决定）
    explicit = os.path.join(tmp, "chosen.jsonl")
    Path(explicit).write_text("PRE-EXISTING", encoding="utf-8")
    r_ex = export.export_graph(cg, out=explicit)
    check("G7a 显式 out 不走占位：已存在的目标仍写到该路径（不让位改名）",
          r_ex["out"] == explicit, os.path.basename(r_ex["out"]))
    check("G7b 显式 out 被本次导出覆盖（#85③ 是唯一把关点）",
          Path(explicit).read_text(encoding="utf-8") != "PRE-EXISTING")
    check("G7c 未产生 _1 让位件（显式面零副作用）",
          not os.path.exists(explicit[:-6] + "_1.jsonl"))
    _rm(explicit)
    _rm(explicit[:-6] + "_1.jsonl")

    # G8 源码锚点计数
    src = _file_src()
    check("G8 源码锚点计数齐备（判据/占位/调用点）",
          all(src.count(a) == n for a, n in _SRC_COUNTS),
          "实测=%s" % {a: src.count(a) for a, _n in _SRC_COUNTS})
    cg.close()


_GROUPS = {"A": group_a}


def _anchor_preflight():
    src = _file_src()
    bad = [(a, src.count(a), n) for a, n in _SRC_COUNTS if src.count(a) != n]
    if not bad:
        return 0
    for a, got, want in bad:
        print("  ANCHOR-MISS %s：命中 %d 次（期望 %d）" % (a[:56], got, want))
    print("  => 实现已漂移，变异表失效：退出码 2（fail-closed）")
    return 2


def _mut_no_claim():
    """退化：撤掉原子占位，退回「先查后建」——复现 #78 并发面缺陷形态。"""
    orig = export._claim_path
    export._claim_path = lambda preferred: preferred
    return lambda: setattr(export, "_claim_path", orig)


def _mut_default_out_creates():
    """退化：让 _default_out 直接创建文件（破坏其「纯查询」已声明语义）。"""
    orig = export._default_out

    def _patched(cg, kind):
        p = orig(cg, kind)
        with open(p, "a", encoding="utf-8"):
            pass
        return p

    export._default_out = _patched
    return lambda: setattr(export, "_default_out", orig)


def _mut_claim_even_explicit():
    """退化：显式 out 也走占位 ⇒ 调用方指定的路径被让位改名。"""
    orig = export._write_jsonl

    def _patched(cg, out_path, entries, include_content=True, claim=False):
        return orig(cg, out_path, entries, include_content=include_content, claim=True)

    export._write_jsonl = _patched
    return lambda: setattr(export, "_write_jsonl", orig)


#: 组 → [(变异名, 应用函数, 期望转红断言前缀集合)]
_MUTATIONS = {
    "A": [
        # 期望集按**实测**填（非推测）。注意 G4（串行三次）**不红**：撤掉占位后
        # _default_out 的碰撞自增仍在 ⇒ 串行面有双保险。串行面的承载层已转移到
        # _claim_path —— 只撤 _default_out 自增打不红串行面（见移植件
        # test_export_snapshots.py 的 M1 读数），这是本笔的**增强**而非缺陷。
        ("撤掉原子占位（退回先查后建，复现 #78 缺陷形态）", _mut_no_claim,
         {"G1c", "G2a", "G2b", "G3a"}),
        ("_default_out 直接创建文件（破坏纯查询语义）", _mut_default_out_creates,
         {"G5", "G6a", "G6b"}),
        # G7b 一并转红：占位让位后 chosen.jsonl 未被覆盖，仍等于 PRE-EXISTING
        ("显式 out 也走占位（#85③ 语义面被改）", _mut_claim_even_explicit,
         {"G7a", "G7b", "G7c"}),
    ],
}


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
    print("!! #78 并发面定点变异自证 · 组 %s：内存注入退化，逐条要求**恰好**命中期望\n" % name)
    bad = []
    base_red, _, _ = _run_group(name)
    print("  未变异基线：红项 %d %s" % (len(base_red), "（应为 0）" if not base_red else sorted(base_red)))
    if base_red:
        bad.append("基线即转红：%s" % sorted(base_red))
    for mname, apply, expect in _MUTATIONS[name]:
        restore = apply()
        try:
            red, _, _ = _run_group(name)
        except Exception as exc:                       # noqa: BLE001
            red = {"<变异体异常:%s>" % type(exc).__name__}
        finally:
            restore()
        ok = (red == expect)
        print("  [%s] %s → 红项 %s（期望 %s）"
              % ("OK" if ok else "BAD", mname, sorted(red), sorted(expect)))
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
    print("[#78 并发面本体 · 原子占位] 正断言组 A")
    _run_group("A")
    print("\n==== #78 结果：%d 通过 / %d 失败 ====" % (PASS, FAIL))
    if FAILS:
        print("失败项：" + "、".join(FAILS))
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    if "--mutate" in sys.argv:
        _i = sys.argv.index("--mutate")
        sys.exit(_mutate(sys.argv[_i + 1] if _i + 1 < len(sys.argv) else ""))
    sys.exit(main())
