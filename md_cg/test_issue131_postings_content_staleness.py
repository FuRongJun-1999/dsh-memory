# -*- coding: utf-8 -*-
"""#131 守卫：倒排发布表的新鲜度判据必须与**被判对象（节点正文）同源**。

病灶（复现于 HEAD）：
    `md_cg/postings.py` 的 `snapshot()`/`stale_reason()` 只 stat **目录** mtime，
    其 docstring 断言「节点写入走 atomic_write ⇒ 目录 mtime 必然变化」。该断言
    **只对合作写者成立**：非合作写者（就地追写 / 备份还原 / 同步盘回写 / 人手编辑）
    改的是**文件内容**，目录 mtime 逐位不变。于是：

        stale_reason('')  ← 判「新鲜」
        S7 用旧表收窄     ← 把只在新正文里出现的真命中整条剔掉（静默丢召回）

    同进程形态（= 长驻 MCP server 的真实部署形态）尤其致命：跨进程形态下
    `_index.json` mtime 会兜住（`stale_index:index_touched` → 回退全表），
    **同进程内**该兜底失效。

修法（本件）：
    `snapshot()` 增记 `node_files`：逐节点 `[mtime_ns, size, sha256[:16]]`
    （整文件字节身份，口径与 `mdcg._file_digest` / `refindex._sha256_file` 同源）；
    `stale_reason()` 在既有 stat 面之后补**内容层**：① (mtime_ns, size) 快路径
    → ② 双双相等时比整文件 sha256（**mtime 可被还原**：cp -p / rsync -t / tar x /
    备份还原 / 粗粒度文件系统下等长改写会同时满足两式）。旧快照无该层 ⇒
    `no_content_snapshot`（fail-closed：宁可慢，不可丢召回）。

断言组：
  A 缺陷面（HEAD 版应 A1/A2/A3/A7 转红）：
      A1 同进程就地追写后 stale_reason 非空
      A2 该 reason 指向内容变化（== content_changed）
      A3 S7 ON 结果 == S7 OFF 结果（新内容不被静默剔除）  ← 本笔主判据
      A4 就地追写后旧表仍缺该词（证明必须靠判据回退，而非靠表自愈）
      A5 重建后 candidates 含被改写节点（证明内容确实变了、可召回）
      A6 复现前提：目录 mtime 逐位不变（测的是内容层，不是目录层）
      A7 等长改写 + 还原 mtime（mtime 可被还原）同样判 content_changed
  B 正对照（不得误报）：
      B1 build 后 stale_reason == ''
      B2 连续两次 stale_reason 均为 ''（无自判过期）
      B3 未改动时 candidates 正常可用
      B4 未改动时 stats()['stale_reason'] == '' 且未发生重建
  C 既有 reason 字符串不回归 + fail-closed：
      C1 新增节点（经 cg.add）⇒ node_count_changed
      C2 抽样构建（limit）⇒ no_snapshot
      C3 根级节点被 utime ⇒ root_file_touched
      C4 旧快照（无 node_files 键）⇒ no_content_snapshot
  D 定点变异：抽掉内容层（退回只比 mtime）⇒ A1/A2/A3/A7/C4 必红

用法：
  python -X utf8 -m md_cg.test_issue131_postings_content_staleness
  python -X utf8 -m md_cg.test_issue131_postings_content_staleness --impl head
  python -X utf8 -m md_cg.test_issue131_postings_content_staleness --mutate
退出码：0 = 全部按预期；1 = 有断言失败 / 变异未按预期转红；2 = 变异锚点失配。
"""
import argparse
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from md_cg import postings  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMPL_REL = os.path.join("md_cg", "postings.py")
MARK = "标记词"

_N_A1 = "A1 同进程就地追写后 stale_reason 非空"
_N_A2 = "A2 reason 指向内容变化（content_changed）"
_N_A3 = "A3 S7 ON 结果 == S7 OFF 结果（新内容不被静默剔除）"
_N_A4 = "A4 就地追写后旧表仍缺该词（必须靠判据回退）"
_N_A5 = "A5 重建后 candidates 含被改写节点"
_N_A6 = "A6 复现前提：目录 mtime 逐位不变"
_N_A7 = "A7 等长改写+还原 mtime 同样判 content_changed"
_N_B1 = "B1 build 后 stale_reason == ''"
_N_B2 = "B2 连续两次 stale_reason 均为 ''"
_N_B3 = "B3 未改动时 candidates 正常可用"
_N_B4 = "B4 stats()['stale_reason'] == '' 且未发生重建"
_N_C1 = "C1 新增节点 ⇒ node_count_changed"
_N_C2 = "C2 抽样构建 ⇒ no_snapshot"
_N_C3 = "C3 根级节点被 utime ⇒ root_file_touched"
_N_C4 = "C4 旧快照（无 node_files）⇒ no_content_snapshot"

_RESULTS = []


def _check(name, ok, detail=""):
    _RESULTS.append((name, bool(ok), detail))
    print("  %s %s%s" % ("[PASS]" if ok else "[FAIL]", name,
                         ("  —— " + detail) if (not ok and detail) else ""))


def _use(path):
    """把 path 物化为 md_cg.postings 并注入（用于红基线/变异体）。

    必须**同时**改 `sys.modules` 与父包属性：生产路径 `mdcg.py` 里的
    `from . import postings as _pd` 走的是「父包属性优先」，只换 sys.modules
    不改 `md_cg.postings` 属性时，生产路径仍用原模块 ⇒ 红基线/变异体形同虚设
    （本守卫首版即踩此坑：A3 在 HEAD 版下仍绿）。
    """
    global postings
    import md_cg as _pkg
    spec = importlib.util.spec_from_file_location("md_cg.postings", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["md_cg.postings"] = mod
    spec.loader.exec_module(mod)
    _pkg.postings = mod
    postings = mod
    return mod


def _materialize_head(tmp):
    r = subprocess.run(["git", "-C", REPO, "show", "HEAD:" + IMPL_REL.replace(os.sep, "/")],
                       capture_output=True)
    if r.returncode != 0 or not (r.stdout or b"").strip():
        return None, "git show 失败 rc=%s" % r.returncode
    p = os.path.join(tmp, "postings_head.py")
    with open(p, "wb") as f:
        f.write(r.stdout)
    return p, ""


def _tmp_root(prefix):
    root = tempfile.mkdtemp(prefix=prefix)
    _rt, _tt = os.path.realpath(root), os.path.realpath(tempfile.gettempdir())
    assert _rt.startswith(_tt), "沙箱断言失败：%r 不在 tempdir 内" % _rt
    return root


def _mk_lib(root):
    """7 节点合成库：alpha（无 MARK）/ beta（含 MARK）/ 5 个无关节点。"""
    from md_cg.mdcg import MdCG
    cg = MdCG(root)
    cg.add("alpha", "阿尔法 贝塔 伽马 通用内容", "knowledge")
    cg.add("beta", MARK + " 专有名词 词条", "knowledge")
    for i in range(5):
        cg.add("f%d" % i, "无关内容 xyzzy 填充 %d" % i, "knowledge")
    cg.flush()
    return cg


def _node_file(cg, nid):
    e = cg.index["nodes"][nid]
    return os.path.join(cg.root, e["path"]), e["path"]


def _append_in_place(cg, nid, extra):
    """**就地**追写节点文件（open/append，不经 atomic_write）⇒ 目录 mtime 不变。"""
    fp, _rel = _node_file(cg, nid)
    d = os.path.dirname(fp)
    before = os.stat(d).st_mtime_ns
    with open(fp, "a", encoding="utf-8", newline="\n") as f:
        f.write(extra)
    after = os.stat(d).st_mtime_ns
    return before, after


def _equal_len_rewrite_restore_mtime(cg, nid, old, new):
    """等长改写 + 把文件 mtime 还原成原值（mtime 可被还原的场景）。"""
    assert len(old.encode("utf-8")) == len(new.encode("utf-8")), "等长前提"
    fp, _rel = _node_file(cg, nid)
    st0 = os.stat(fp)
    with open(fp, encoding="utf-8", newline="") as f:
        txt = f.read()
    assert old in txt, "锚点不在文件里：%r" % old
    with open(fp, "w", encoding="utf-8", newline="") as f:
        f.write(txt.replace(old, new, 1))
    os.utime(fp, ns=(st0.st_atime_ns, st0.st_mtime_ns))     # 还原 mtime
    st1 = os.stat(fp)
    return (st0.st_mtime_ns, st0.st_size), (st1.st_mtime_ns, st1.st_size)


def _search_ids(cg, q, s7):
    os.environ["MDCG_RETRIEVAL_PIPELINE"] = "1"
    os.environ["MDCG_GATE_S1_DOMAIN"] = "0"
    os.environ["MDCG_GATE_S1B_BUCKET"] = "0"
    os.environ["MDCG_GATE_S2_COND"] = "0"
    os.environ.pop("MDCG_S7_FRESHNESS", None)
    os.environ.pop("MDCG_SEMANTIC", None)
    if s7:
        os.environ["MDCG_GATE_S7_POSTINGS"] = "1"
    else:
        os.environ.pop("MDCG_GATE_S7_POSTINGS", None)
    r, m = cg.search(q, k=10, judge=False, record=False)
    return sorted(x[0]["id"] for x in r), m


def _case_inplace():
    """A 组：同进程就地追写（issue #131 的决定性构造）。"""
    root = _tmp_root("iss131_inplace_")
    cg = _mk_lib(root)
    postings.build(cg)
    nodes = cg.index["nodes"]
    _check(_N_B1, postings.stale_reason(root, nodes) == "",
           "reason=%r" % postings.stale_reason(root, nodes))
    _check(_N_B2, postings.stale_reason(root, nodes) == ""
           and postings.stale_reason(root, nodes) == "", "二次调用")
    _ids0, _ = postings.candidates(root, [MARK])
    _check(_N_B3, _ids0 is not None and "beta" in _ids0, "cands=%r" % (_ids0,))
    _st = postings.stats(root, nodes)
    _check(_N_B4, _st.get("stale_reason") == "", "stats=%r" % (_st.get("stale_reason"),))

    # 就地追写 alpha（**不**经 atomic_write、**不**碰 _index.json）
    before, after = _append_in_place(cg, "alpha", "\n" + MARK + " 就地追加\n")
    _check(_N_A6, before == after, "dir mtime %s -> %s" % (before, after))

    sr = postings.stale_reason(root, nodes)
    _check(_N_A1, sr != "", "reason=%r（修复前为 ''）" % (sr,))
    _check(_N_A2, sr == "content_changed", "reason=%r" % (sr,))
    ids_stale, _why = postings.candidates(root, [MARK])
    _check(_N_A4, ids_stale is not None and "alpha" not in ids_stale,
           "cands=%r" % (sorted(ids_stale or []),))

    # 端到端：新进程实例（清读缓存）下 S7 ON 与 S7 OFF 必须一致
    from md_cg.mdcg import MdCG
    cg2 = MdCG(root)
    off_ids, _m0 = _search_ids(cg2, MARK, s7=False)
    on_ids, m1 = _search_ids(cg2, MARK, s7=True)
    s7 = (m1.get("gates") or {}).get("s7") or {}
    _check(_N_A3, off_ids == on_ids and "alpha" in off_ids,
           "S7 OFF=%r S7 ON=%r gates=%r" % (off_ids, on_ids, s7))

    # 重建后新内容可被召回（证明内容确实变了、表可自愈）
    postings.build(cg2)
    ids_new, _ = postings.candidates(root, [MARK])
    _check(_N_A5, ids_new is not None and "alpha" in ids_new,
           "cands=%r" % (sorted(ids_new or []),))
    _check("B5 重建后 stale_reason 恢复 ''", postings.stale_reason(root, cg2.index["nodes"]) == "",
           "reason=%r" % postings.stale_reason(root, cg2.index["nodes"]))
    cg2.close()
    cg.close()


def _case_mtime_restored():
    """A7：等长改写 + 还原 mtime（快路径失效，只能靠内容哈希定身份）。"""
    root = _tmp_root("iss131_restore_")
    cg = _mk_lib(root)
    postings.build(cg)
    nodes = cg.index["nodes"]
    (m0, s0), (m1, s1) = _equal_len_rewrite_restore_mtime(
        cg, "alpha", "通用内容", "专用词条")
    _check(_N_A7, (m0, s0) == (m1, s1)
           and postings.stale_reason(root, nodes) == "content_changed",
           "stat 前=%r 后=%r reason=%r" % ((m0, s0), (m1, s1),
                                          postings.stale_reason(root, nodes)))
    cg.close()


def _case_existing_reasons():
    """C 组：既有 reason 字符串不回归 + 旧快照 fail-closed。"""
    root = _tmp_root("iss131_reasons_")
    cg = _mk_lib(root)
    postings.build(cg)
    cg.add("n9", "新增 节点 内容", "knowledge")
    cg.flush()
    sr = postings.stale_reason(root, cg.index["nodes"])
    _check(_N_C1, sr == "node_count_changed", "reason=%r" % (sr,))

    root2 = _tmp_root("iss131_partial_")
    cg2 = _mk_lib(root2)
    st2 = postings.build(cg2, limit=2)
    _check(_N_C2, st2.get("partial") is True and "snapshot" not in st2
           and postings.stale_reason(root2, cg2.index["nodes"]) == "no_snapshot",
           "partial=%r reason=%r" % (st2.get("partial"),
                                     postings.stale_reason(root2, cg2.index["nodes"])))

    root3 = _tmp_root("iss131_root_")
    _dst = os.path.join(root3, "r1.md")
    with open(_dst, "w", encoding="utf-8") as f:
        f.write("---\nid: r1\nlayer: knowledge\n---\n根级节点\n")
    fake = {"r1": {"path": "r1.md", "layer": "knowledge"}}
    meta3 = {"schema": postings.SCHEMA, "snapshot": postings.snapshot(root3, fake)}
    os.utime(_dst, (time.time() + 5, time.time() + 5))
    sr3 = postings.stale_reason(root3, fake, meta3)
    _check(_N_C3, sr3 == "root_file_touched", "reason=%r" % (sr3,))

    # 旧快照（无 node_files 键）⇒ fail-closed
    root4 = _tmp_root("iss131_oldsnap_")
    _dst4 = os.path.join(root4, "r1.md")
    with open(_dst4, "w", encoding="utf-8") as f:
        f.write("---\nid: r1\nlayer: knowledge\n---\n根级节点\n")
    fake4 = {"r1": {"path": "r1.md", "layer": "knowledge"}}
    snap4 = postings.snapshot(root4, fake4)
    _check("C4 前置：未改动时旧快照判新鲜",
           postings.stale_reason(root4, fake4,
                                 {"schema": postings.SCHEMA, "snapshot": snap4}) == "",
           "reason=%r" % postings.stale_reason(
               root4, fake4, {"schema": postings.SCHEMA, "snapshot": snap4}))
    meta4 = {"schema": postings.SCHEMA,
             "snapshot": {k: v for k, v in snap4.items() if k != "node_files"}}
    sr4 = postings.stale_reason(root4, fake4, meta4)
    _check(_N_C4, sr4 == "no_content_snapshot", "reason=%r" % (sr4,))
    cg.close()
    cg2.close()


_HEAD_EXPECT_RED = [_N_A1, _N_A2, _N_A3, _N_A7]


def _baseline_mode(tmp):
    """--impl head：以 HEAD 版 postings 跑 A 组，红基线必须按点转红。"""
    print("!! 红基线取证：以 HEAD 版 postings 跑 A 组——修前缺陷形态必须按点转红\n")
    head, why = _materialize_head(tmp)
    if head is None:
        _check("D 红基线自证：HEAD 版物化", False, why)
        return 1
    _use(head)
    _case_inplace()
    _case_mtime_restored()
    reds = {n for n, ok, _d in _RESULTS if not ok}
    if not reds:
        print("\nHEAD 版 A 组全绿——HEAD 已含修复（SKIP）")
        return 0
    if reds == set(_HEAD_EXPECT_RED):
        print("\n红基线成立：HEAD 版恰 %d 条点名转红（就地追写判新鲜、真命中被静默剔除）"
              % len(reds))
        return 0
    print("\n红基线不成立：多红 %r / 少红 %r"
          % (sorted(reds - set(_HEAD_EXPECT_RED)), sorted(set(_HEAD_EXPECT_RED) - reds)))
    return 1


# 定点变异：抽掉内容层（退回「只比 mtime」）——#131 的修复点。
_MUT_OLD = """    # ---- 内容层（#131）：逐节点文件身份 = (mtime_ns, size) 快路径 → sha256 定身份 ----
    want_nf = snap.get("node_files")
    if not isinstance(want_nf, dict):
        # 旧快照（本层引入前构建）无法证明「表与正文同源」——按「宁可慢，不可
        # 丢召回」的既有承诺 fail-closed：判过期、回退全量（重建一次即补上本层）。
        return "no_content_snapshot"
    paths_now = set()
    for e in index_nodes.values():
        p = (e or {}).get("path") or ""
        if p:
            paths_now.add(p)
    if set(want_nf.keys()) != paths_now:
        return "node_files_changed"
    for p, rec in want_nf.items():
        fp = os.path.join(root or "", p)
        try:
            st = os.stat(fp)
        except OSError:
            return "node_file_missing"       # 快照里有、盘上没了 ⇒ 表必过期
        if not isinstance(rec, (list, tuple)) or len(rec) < 2:
            return "no_content_snapshot"
        if (st.st_mtime_ns, st.st_size) != (rec[0], rec[1]):
            return "content_changed"         # ① 快路径：时间戳/长度任一变化即陈旧
        # ② 双双相等**不足以定身份**——mtime 可被还原（cp -p / rsync -t / 备份
        #    还原 / 粗粒度文件系统），等长改写会同时满足两式 ⇒ 比内容哈希。
        if rec[2] is None or _file_digest(fp) != rec[2]:
            return "content_changed"
    return \"\""""

_MUT_EXPECT_RED = [_N_A1, _N_A2, _N_A3, _N_A7, _N_C4]


def _read_norm(path):
    with open(path, encoding="utf-8", newline="") as f:
        return f.read().replace("\r\n", "\n")


def _write_norm(path, text):
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def _mutate_mode(tmp):
    print("!! 定点变异自证：抽掉内容层（退回只比 mtime），缺陷面必须按预期点名转红\n")
    src = _read_norm(os.path.join(REPO, IMPL_REL))
    if src.count(_MUT_OLD) != 1:
        print("  [锚点失配] 内容层锚点命中 %d 次（要求恰 1 次）" % src.count(_MUT_OLD))
        return 2
    mut = os.path.join(tmp, "mut_postings.py")
    _write_norm(mut, src.replace(_MUT_OLD, "    return \"\""))
    keep = list(_RESULTS)
    del _RESULTS[:]
    try:
        _use(mut)
        _case_inplace()
        _case_mtime_restored()
        _case_existing_reasons()
    except Exception as exc:
        _check("变异：场景异常", False, "%s: %s" % (type(exc).__name__, exc))
    reds = {n for n, ok, _d in _RESULTS if not ok}
    del _RESULTS[:]
    _RESULTS[:] = keep
    if reds == set(_MUT_EXPECT_RED):
        print("  [PASS] 变异：恰按 %d 条点名转红（A1/A2/A3/A7 主判据全红）" % len(reds))
    else:
        print("  [FAIL] 变异：多红 %r / 少红 %r"
              % (sorted(reds - set(_MUT_EXPECT_RED)),
                 sorted(set(_MUT_EXPECT_RED) - reds)))
        _check("变异按预期点名转红", False,
               "多红 %r / 少红 %r" % (sorted(reds - set(_MUT_EXPECT_RED)),
                                     sorted(set(_MUT_EXPECT_RED) - reds)))
    _use(os.path.join(REPO, IMPL_REL))
    return 0 if all(ok for _n, ok, _d in _RESULTS) else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description="#131 倒排发布表内容层新鲜度守卫")
    ap.add_argument("--impl", default="", help="指定 postings 实现副本（head = 取 HEAD blob）")
    ap.add_argument("--mutate", action="store_true", help="定点变异自证")
    a = ap.parse_args(argv)
    with tempfile.TemporaryDirectory(prefix="iss131_guard_") as tmp:
        if a.mutate:
            return _mutate_mode(tmp)
        if a.impl == "head":
            return _baseline_mode(tmp)
        if a.impl:
            _use(os.path.abspath(a.impl))
        print("== #131 倒排发布表内容层新鲜度守卫 ==\n")
        _case_inplace()
        _case_mtime_restored()
        _case_existing_reasons()
        n_red = sum(1 for _n, ok, _d in _RESULTS if not ok)
        print("\n通过 %d / 失败 %d" % (len(_RESULTS) - n_red, n_red))
        return 1 if n_red else 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
