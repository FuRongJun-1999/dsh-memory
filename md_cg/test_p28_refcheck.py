# -*- coding: utf-8 -*-
"""ref 增量索引 + 漂移/悬空巡检（P28 · R3 改造验收）。

对照 `docs/认知图_索引与工程规范化_计划_v0.1.md` 的 R3：

  ① 统一 ref 协议 + 提取器注册表：调用方只说 `kind`，`refindex` 决定用哪个
     提取器；无提取器后缀显式报错。
  ② `_refindex.json` 增量（修 F）：`incremental=True` 时未变文件**不再读盘重切**
     （`skipped_unchanged`），节点仍在（幂等）；默认全量，保证「不漏召回」。
  ③ `op=ref action=check` 漂移/悬空巡检（修 D）：改源一行 → 报 `stale`；删除源
     文件 → 报 `dangling`；**只读、不抛、不改源文件**。
  ④ `op=ref action=stat`：看水位，最近一次索引是否被截断（`truncated` 不再静默）。
  ⑤ 接入 `sustain.diagnose`：`ref_stale` / `ref_dangling` 进入体检；`heal` 的
     `rebuild_refs` 重建派生物后漂移消除（源文件不动）。
  ⑥ 检索结果带 `ref` / `ref_kind`（读侧只加字段，不改召回逻辑）。
  ⑦ 派生物不膨胀：`_refindex.json` 体积有界、重跑不涨。

运行：python -m md_cg.test_p28_refcheck
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile

from . import corpus, refindex, tokens
from .mdcg import MdCG
from .mcp_server import call_tool

PASS = FAIL = 0
FAILS = []

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.join(_BASE, "_md_cg_p28")


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}" + (f"  · {detail}" if detail else ""))
    else:
        FAIL += 1
        FAILS.append(name)
        print(f"  [FAIL] {name}  · {detail}")


ALPHA = ('"""能量计算模块。"""\n'
         'import math\n'
         '\n'
         '\n'
         'def compute_energy(mass, speed):\n'
         '    """计算动能。"""\n'
         '    return mass * speed * speed\n'
         '\n'
         '\n'
         'class Reactor:\n'
         '    """反应堆模型。"""\n'
         '\n'
         '    def ignite(self):\n'
         '        """点火。"""\n'
         '        self.state = "on"\n')

# 同函数同区间，只改一行实现 → 行数不变，只有区间哈希变（最强的漂移信号）
ALPHA_DRIFT = ALPHA.replace("return mass * speed * speed",
                            "return 0.5 * mass * speed * speed")
# 第二个漂移变体：段⑤ 已把源改成 ALPHA_DRIFT 并重建索引，段⑧ 要再制造一次真实漂移，
# 必须写出**与当前索引内容不同**的正文；否则只是 mtime 变了、内容没变，报 ok 才对。
ALPHA_DRIFT2 = ALPHA.replace("return mass * speed * speed",
                             "return mass * speed * speed / 2.0")
ALPHA_MARK2 = "speed * speed / 2.0"

BETA = ('"""辅助模块。"""\n'
        '\n'
        '\n'
        'def helper_scale(x):\n'
        '    """缩放。"""\n'
        '    return x * 2\n')


def rd(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def wr(path, text, bump=0.0):
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    if bump:
        # 显式推后 mtime：粗粒度文件系统上保证「变了」能被水位看见
        t = os.path.getmtime(path) + bump
        os.utime(path, (t, t))


def index_read(cg, code_dir, **extra):
    a = {"op": "index_code", "path": code_dir}
    a.update(extra)
    return call_tool(cg, "cg", a)


def ref_read(cg, **args):
    a = {"op": "ref"}
    a.update(args)
    return call_tool(cg, "cg", a)


def main():
    print("=" * 68)
    print("md 认知图 P28 验收 · ref 增量索引 + 漂移/悬空巡检（R3）")
    print("=" * 68)

    tmp = tempfile.mkdtemp(prefix="mdcg_refcheck_")
    src = os.path.join(tmp, "pkg")
    os.makedirs(src)
    alpha = os.path.join(src, "alpha.py")
    beta = os.path.join(src, "beta.py")
    wr(alpha, ALPHA)
    wr(beta, BETA)

    corpus.reset_root(ROOT)
    cg = MdCG(ROOT)

    try:
        # ============================================ ① 统一 ref 协议 + 注册表
        print("\n【1】统一 ref 协议与提取器注册表")
        check("tokens.ALL_OPS 仍收录 ref / index_code",
              "ref" in tokens.ALL_OPS and "index_code" in tokens.ALL_OPS)
        check("REF_KEYS = (code_ref, doc_ref)",
              refindex.REF_KEYS == ("code_ref", "doc_ref"), str(refindex.REF_KEYS))
        reg = refindex.registry()
        check("注册表覆盖 code_ref / doc_ref",
              "code_ref" in reg and "doc_ref" in reg, str(sorted(reg)))
        check("kind_of_path 按后缀判 kind",
              refindex.kind_of_path("a.py") == "code_ref"
              and refindex.kind_of_path("a.md") == "doc_ref"
              and refindex.kind_of_path("a.txt") == "",
              f"py={refindex.kind_of_path('a.py')} md={refindex.kind_of_path('a.md')}")
        try:
            refindex.extract("x = 1", "foo.xyz")
            raised = False
        except ValueError as exc:
            raised = "无提取器" in str(exc) or "无索引提取器" in str(exc)
        check("无提取器后缀显式报错（不静默）", raised)

        # ============================================ ② 全量索引 + 水位
        print("\n【2】index_code 全量 + _refindex.json 水位")
        out1 = index_read(cg, src)
        check("op=index_code ok", out1.get("ok"), str(out1)[:120])
        check("files == 2（命中后缀）", out1.get("files") == 2, str(out1.get("files")))
        check("indexed > 0 且 error_count == 0",
              out1.get("indexed", 0) > 0 and out1.get("error_count") == 0)
        cg.flush()
        led = refindex.Ledger(ROOT)
        summ = led.summary()
        check("_refindex.json 落盘", summ["exists"], summ["path"])
        check("水位 files == 2", summ["files"] == 2, str(summ["files"]))
        check("水位 nodes == 本轮 indexed",
              summ["nodes"] == out1.get("indexed"), f"{summ['nodes']} == {out1.get('indexed')}")
        n_before = len((cg.index.get("nodes") or {}))
        ids1 = set(out1.get("ids") or [])

        # ============================================ ③ 增量：未变则跳过
        print("\n【3】增量索引：未变文件不重切（修 F）")
        out2 = index_read(cg, src, incremental=True)
        check("incremental 跳过未变文件",
              out2.get("skipped_unchanged") == 2, str(out2.get("skipped_unchanged")))
        check("incremental 下 indexed == 0（没有重复条目）",
              out2.get("indexed") == 0, str(out2.get("indexed")))
        cg.flush()
        check("增量后节点数不变（幂等）",
              len((cg.index.get("nodes") or {})) == n_before,
              f"{len((cg.index.get('nodes') or {}))} == {n_before}")
        out3 = index_read(cg, src)
        check("默认（不传 incremental）仍是全量：不跳过",
              out3.get("skipped_unchanged") == 0, str(out3.get("skipped_unchanged")))
        check("重跑 id 集合稳定", set(out3.get("ids") or []) == ids1,
              f"{len(set(out3.get('ids') or []))} vs {len(ids1)}")

        # ============================================ ④ 回读 + 检索带 ref
        print("\n【4】op=ref 回读 + 检索结果带 ref / ref_kind")
        rr = ref_read(cg, node_id=(out1.get("ids") or [""])[0])
        check("op=ref read ok", rr.get("ok") is True, str(rr)[:120])
        check("ref_kind == code_ref", rr.get("ref_kind") == "code_ref",
              str(rr.get("ref_kind")))
        check("回读带 hash_match（源未动 → True）",
              rr.get("hash_match") is True, str(rr.get("hash_match")))
        read = call_tool(cg, "cg", {"op": "read", "query": "compute_energy", "k": 10})
        hits = [r for r in read.get("results", []) if r.get("ref_kind") == "code_ref"]
        check("检索结果带 ref / ref_kind 字段", bool(hits), f"hits={len(hits)}")
        check("检索的 ref 指回源文件",
              bool(hits) and isinstance(hits[0].get("ref"), dict)
              and hits[0]["ref"].get("path") == "alpha.py",
              str(hits[0].get("ref") if hits else None))

        # ============================================ ⑤ 漂移：stale
        print("\n【5】漂移检测：改源一行 → stale（只读、不抛）")
        wr(alpha, ALPHA_DRIFT, bump=5.0)
        mt_before = {p: os.path.getmtime(p) for p in (alpha, beta)}
        chk = ref_read(cg, action="check")
        mt_after = {p: os.path.getmtime(p) for p in (alpha, beta)}
        check("action=check 返回 ok", isinstance(chk, dict), str(type(chk)))
        check("check 判定 ok=False（有漂移）", chk.get("ok") is False, str(chk.get("ok")))
        check("报出 stale 且指向 alpha.py",
              any((r.get("path") or "").endswith("alpha.py") for r in chk.get("stale", [])),
              str([r.get("path") for r in chk.get("stale", [])]))
        check("巡检只读：源文件 mtime 不变", mt_before == mt_after)
        stale_rr = ref_read(cg, ref={"path": "alpha.py", "lineno": 5, "end": 7,
                                     "hash": "deadbeef", "root": src, "precise": True})
        check("回读陈旧 ref → hash_match=False / stale=True",
              stale_rr.get("hash_match") is False and stale_rr.get("stale") is True,
              str(stale_rr.get("hash_match")))
        index_read(cg, src)                       # 重建：漂移消除
        chk2 = ref_read(cg, action="check")
        check("重跑 index_code 后 stale 消除", chk2.get("ok") is True,
              str([r.get("path") for r in chk2.get("stale", [])]))

        # ============================================ ⑥ 悬空：dangling
        print("\n【6】悬空检测：删源文件 → dangling")
        os.remove(beta)
        chk3 = ref_read(cg, action="check")
        check("报出 dangling 且指向 beta.py",
              any((r.get("path") or "").endswith("beta.py")
                  for r in chk3.get("dangling", [])),
              str([r.get("path") for r in chk3.get("dangling", [])]))
        check("dangling 时 ok=False", chk3.get("ok") is False)
        wr(beta, BETA)                            # 恢复源 + 重建
        index_read(cg, src)
        chk4 = ref_read(cg, action="check")
        check("恢复源并重建后 dangling 消除",
              chk4.get("ok") is True and not chk4.get("dangling"),
              str([r.get("path") for r in chk4.get("dangling", [])]))

        # ============================================ ⑦ 截断不静默 + 水位留痕
        print("\n【7】截断显式上报 + 写进水位")
        tr = index_read(cg, src, max_files=1)
        check("max_files=1 → truncated=True", tr.get("truncated") is True)
        check("truncated_reason 指出 max_files",
              "max_files" in (tr.get("truncated_reason") or ""),
              str(tr.get("truncated_reason")))
        stt = ref_read(cg, action="stat")
        check("action=stat 返回水位与 last_index",
              isinstance(stt.get("ledger"), dict)
              and "last_index" in stt["ledger"], str(stt.get("ledger"))[:120])
        check("水位记下 last_index.truncated=True",
              (stt["ledger"].get("last_index") or {}).get("truncated") is True)
        index_read(cg, src)
        check("重跑全量后 last_index.truncated 回 False",
              (ref_read(cg, action="stat")["ledger"].get("last_index") or {})
              .get("truncated") is False)

        # ============================================ ⑧ 接入 sustain.diagnose / heal
        print("\n【8】接入 sustain：diagnose 报 ref_stale，heal 的 rebuild_refs 修复")
        wr(alpha, ALPHA_DRIFT2, bump=5.0)
        diag = call_tool(cg, "cg", {"op": "sustain", "action": "diagnose"})
        codes = {i["code"] for i in diag.get("issues", [])}
        check("diagnose issues 含 ref_stale", "ref_stale" in codes, str(sorted(codes)))
        check("diagnose stats 报 ref_stale / ref_checked",
              diag.get("stats", {}).get("ref_stale", 0) >= 1
              and "ref_checked" in diag.get("stats", {}),
              str(diag.get("stats", {}).get("ref_stale")))
        check("巡检不改源文件（改动仍在）", ALPHA_MARK2 in rd(alpha))
        heal = call_tool(cg, "cg", {"op": "sustain", "action": "heal"})
        check("heal 动作含 rebuild_refs",
              any(a.get("code") == "rebuild_refs" for a in heal.get("actions", [])),
              str([a.get("code") for a in heal.get("actions", [])]))
        diag2 = call_tool(cg, "cg", {"op": "sustain", "action": "diagnose"})
        codes2 = {i["code"] for i in diag2.get("issues", [])}
        check("heal 后 ref_stale 消除", "ref_stale" not in codes2, str(sorted(codes2)))
        check("heal 不修改源文件", ALPHA_MARK2 in rd(alpha))

        # ============================================ ⑨ 派生物不膨胀 + 未知 action
        print("\n【9】_refindex.json 不膨胀 / 未知 action 不静默")
        led2 = refindex.Ledger(ROOT)
        p = led2.path
        size1 = os.path.getsize(p)
        for _ in range(3):
            index_read(cg, src)
        size2 = os.path.getsize(p)
        check("_refindex.json 体积有界（< 20KB）", size2 < 20000, f"{size2}B")
        check("重跑 3 次不膨胀", size2 == size1, f"{size1} -> {size2}")
        check("水位 files 仍 == 2（无幽灵条目）", led2.summary()["files"] == 2,
              str(led2.summary()["files"]))
        try:
            r = ref_read(cg, action="nope")
            silent = (isinstance(r, dict) and r.get("ok") is True)
        except Exception:                          # noqa: BLE001
            silent = False
        check("未知 action 不静默成功", silent is False)

    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n" + "=" * 68)
    print(f"通过 {PASS} / 失败 {FAIL}")
    if FAILS:
        print("失败项：\n  - " + "\n  - ".join(FAILS))
    print("=" * 68)
    return 1 if FAIL else 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
