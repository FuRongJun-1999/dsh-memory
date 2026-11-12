# -*- coding: utf-8 -*-
"""#152① 守卫：密封（加密）库不得被 postings.build 写出明文 bigram。

缺陷形态（复现于 HEAD）：
    md_cg/postings.py 的 build() 经 cg.get() 取**解密后**的 content，把明文 bigram
    写进 <root>/_postings.json。节点正文已加密，而词项索引仍是明文 ⇒ 持该文件者
    可读出内容主题（与全仓「原文明文不出库」立场冲突）。

修法（本件）：
    build() 开头做**密封面探测**——索引中存在加密级节点（entry.sensitivity 属
    crypto.ENCRYPTED_LEVELS），或本实例挂密钥面且当前可解密（dek 为真）时，
    **不写任何文件**直接拒绝，返回 refused / sealed_nodes / reason 供调用方判因。

断言组：
  A 缺陷面（HEAD 版应 5 条全红）：
      A1 密封库 build 后 _postings.json 不存在
      A2 返回 rebuilt is False 且 refused == "sealed_nodes"
      A3 产物全文无任何明文关键词 bigram
      A4 返回 sealed_nodes == 1（拒因可定位到节点数）
      A5 _postings_meta.json 同样未写出（拒绝=整体不落盘，不是写一半）
  B 不误伤：
      B1 非密封库（MdCG + internal 节点）照常 build（rebuilt=True 且文件写出）
      B2 密封库但**全 internal 且已 lock**（无加密节点、不可解密）⇒ 放行
      B3 抽样构建（limit）在密封库上同样被拒且不写文件
  C 判据未放宽：
      C1 _encrypted_levels() 与 crypto.ENCRYPTED_LEVELS 一致（小写集合）
      C2 internal 节点的 _sealed_node_ids 为空
      C3 拒绝路径不产出 partial 快照
  D 红基线自证：以 HEAD 版 postings 跑 A 组，应恰 5 条全红；HEAD 已含修复则 SKIP

用法：
  python -X utf8 -m md_cg.test_issue152_sealed_postings
  python -X utf8 -m md_cg.test_issue152_sealed_postings --impl head
  python -X utf8 -m md_cg.test_issue152_sealed_postings --mutate
退出码：0 = 全部按预期；1 = 有断言失败 / 变异未按预期转红；2 = 变异锚点失配。
"""
import argparse
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import md_cg  # noqa: E402
from md_cg import postings  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMPL_REL = os.path.join("md_cg", "postings.py")
SECRET = "绝密项目代号"

_N_A1 = "A1 密封库：build 后 _postings.json 不存在"
_N_A2 = "A2 密封库：rebuilt is False 且 refused == sealed_nodes"
_N_A3 = "A3 密封库：产物全文无明文关键词 bigram"
_N_A4 = "A4 密封库：sealed_nodes == 1"
_N_A5 = "A5 密封库：_postings_meta.json 同样未写出"
_N_B1 = "B1 非密封库：照常 build（rebuilt=True 且文件写出）"
_N_B2 = "B2 密封库+全 internal+locked：放行（不误伤）"
_N_B3 = "B3 密封库+limit 抽样：同样被拒且不写文件"
_N_C1 = "C1 加密级集合 == crypto.ENCRYPTED_LEVELS"
_N_C2 = "C2 internal 节点的 _sealed_node_ids 为空"
_N_C3 = "C3 拒绝路径不产出 partial 快照"

_RESULTS = []


def _check(name, ok, detail=""):
    _RESULTS.append((name, bool(ok), detail))
    print("  %s %s%s" % ("[PASS]" if ok else "[FAIL]", name,
                         ("  —— " + detail) if (not ok and detail) else ""))


def _use(path):
    """把 path 物化为 md_cg.postings 并注入（用于红基线/变异体）。"""
    global postings
    spec = importlib.util.spec_from_file_location("md_cg.postings", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["md_cg.postings"] = mod
    spec.loader.exec_module(mod)
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


def _mk_sealed(root, body=None, sensitivity="secret", lock=False):
    from md_cg import mdcos
    from md_cg.security import Principal
    owner = Principal(tenant="t1", actor="alice", clearance="secret")
    cg = mdcos.MdCGSecure(root, principal=owner, master_key=os.urandom(32))
    cg.add("s1", body or (SECRET + " 行动方案"), sensitivity=sensitivity)
    cg.flush()
    if lock:
        cg.lock()
    return cg


def _mk_open(root):
    from md_cg import mdcos
    cg = mdcos.MdCG(root)
    cg.add("n1", "阿尔法 贝塔 伽马", "knowledge")
    cg.flush()
    return cg


def _leaked_terms(root):
    """产物里含 SECRET 任一字符的 bigram（文件不存在 ⇒ 空集，即无泄漏）。"""
    p = postings.postings_path(root)
    if not os.path.exists(p):
        return []
    try:
        with io.open(p, encoding="utf-8") as f:
            table = json.load(f)
    except Exception:
        return ["<unreadable>"]
    return sorted({g for g in table if any(c in g for c in SECRET)})


def _case_sealed():
    root = _tmp_root("iss152_sealed_")
    cg = _mk_sealed(root)
    st = postings.build(cg)
    _check(_N_A1, not os.path.exists(postings.postings_path(root)),
           "exists=%s" % os.path.exists(postings.postings_path(root)))
    _check(_N_A2, st.get("rebuilt") is False and st.get("refused") == "sealed_nodes",
           "rebuilt=%r refused=%r" % (st.get("rebuilt"), st.get("refused")))
    leak = _leaked_terms(root)
    _check(_N_A3, not leak, "leak=%r" % (leak[:8],))
    _check(_N_A4, st.get("sealed_nodes") == 1, "sealed_nodes=%r" % (st.get("sealed_nodes"),))
    _check(_N_A5, not os.path.exists(postings.meta_path(root)),
           "meta_exists=%s" % os.path.exists(postings.meta_path(root)))
    cg.close()


def _case_no_false_positive():
    root = _tmp_root("iss152_open_")
    cg = _mk_open(root)
    st = postings.build(cg)
    _check(_N_B1, st.get("rebuilt") is True and st.get("nodes", 0) > 0
           and os.path.exists(postings.postings_path(root)),
           "rebuilt=%r nodes=%r exists=%s" % (st.get("rebuilt"), st.get("nodes"),
                                              os.path.exists(postings.postings_path(root))))
    cg.close()
    root2 = _tmp_root("iss152_internal_")
    cg2 = _mk_sealed(root2, body="阿尔法 贝塔", sensitivity="internal", lock=True)
    st2 = postings.build(cg2)
    _check(_N_B2, st2.get("rebuilt") is True and st2.get("refused") is None,
           "rebuilt=%r refused=%r" % (st2.get("rebuilt"), st2.get("refused")))
    cg2.close()
    root3 = _tmp_root("iss152_partial_")
    cg3 = _mk_sealed(root3)
    st3 = postings.build(cg3, limit=1)
    _check(_N_B3, st3.get("rebuilt") is False
           and not os.path.exists(postings.postings_path(root3)),
           "rebuilt=%r exists=%s" % (st3.get("rebuilt"),
                                     os.path.exists(postings.postings_path(root3))))
    _check(_N_C3, "partial" not in st3, "keys=%r" % (sorted(st3),))
    cg3.close()


def _case_criteria():
    from md_cg import crypto
    want = {str(x).strip().lower() for x in crypto.ENCRYPTED_LEVELS}
    _check(_N_C1, postings._encrypted_levels() == want,
           "got=%r want=%r" % (sorted(postings._encrypted_levels()), sorted(want)))
    _check(_N_C2, postings._sealed_node_ids({"n1": {"sensitivity": "internal"}}) == [],
           "got=%r" % (postings._sealed_node_ids({"n1": {"sensitivity": "internal"}}),))


_HEAD_EXPECT_RED = [_N_A1, _N_A2, _N_A3, _N_A4, _N_A5]


def _baseline_mode(tmp):
    """--impl head：以 HEAD 版 postings 跑 A 组，红基线必须 5 条全红。"""
    print("!! 红基线取证：以 HEAD 版 postings 跑 A 组——修前缺陷形态必须按点转红\n")
    head, why = _materialize_head(tmp)
    if head is None:
        _check("D 红基线自证：HEAD 版物化", False, why)
        return 1
    _use(head)
    _case_sealed()
    reds = {n for n, ok, _d in _RESULTS if not ok}
    greens = [n for n, ok, _d in _RESULTS if ok]
    if not reds:
        print("\nHEAD 版 A 组全绿——HEAD 已含修复，红基线只在本改动提交前可复现（SKIP）")
        return 0
    if reds == set(_HEAD_EXPECT_RED):
        print("\n红基线成立：HEAD 版恰 5 条点名转红（明文 bigram 落盘可复现）")
        return 0
    print("\n红基线不成立：多红 %r / 少红 %r"
          % (sorted(reds - set(_HEAD_EXPECT_RED)), sorted(set(_HEAD_EXPECT_RED) - reds)))
    return 1


_MUTATIONS = [
    ("M1 删除密封面早退块（完全放行）",
     "    sealed_ids = _sealed_node_ids(nodes)\n"
     "    if sealed_ids:\n"
     "        return {\"schema\": SCHEMA, \"nodes\": 0, \"terms\": 0, \"postings\": 0,\n"
     "                \"rebuilt\": False, \"refused\": \"sealed_nodes\",\n"
     "                \"sealed_nodes\": len(sealed_ids),\n"
     "                \"reason\": \"密封面 fail-closed（#152①）：密文节点的明文 bigram 不得落进 _postings.json\"}\n"
     "    if _is_sealed_instance(cg) and getattr(cg, \"dek\", None):\n"
     "        return {\"schema\": SCHEMA, \"nodes\": 0, \"terms\": 0, \"postings\": 0,\n"
     "                \"rebuilt\": False, \"refused\": \"sealed_instance_unlocked\", \"sealed_nodes\": 0,\n"
     "                \"reason\": \"密封面 fail-closed（#152①）：实例持密钥可解密，明文 bigram 不得落进 _postings.json\"}\n",
     "",
     [_N_A1, _N_A2, _N_A3, _N_A4, _N_A5]),
    ("M2 节点面判据失效（if sealed_ids → if False）",
     "    if sealed_ids:",
     "    if False:",
     [_N_A2, _N_A4]),
    ("M3 探测函数恒空（_sealed_node_ids 恒返回 []）",
     "    return [nid for nid, e in (nodes or {}).items()\n"
     "            if str(((e or {}).get(\"sensitivity\")) or \"\").strip().lower() in lv]",
     "    return []",
     [_N_A2, _N_A4]),
]


def _read_norm(path):
    with open(path, encoding="utf-8", newline="") as f:
        return f.read().replace("\r\n", "\n")


def _write_norm(path, text):
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def _mutate_mode(tmp):
    print("!! 定点变异自证：逐条把修复点改回退化形态，A 组必须按预期点名转红\n")
    src = _read_norm(os.path.join(REPO, IMPL_REL))
    anchor_bad = 0
    for idx, (label, old, new, expect) in enumerate(_MUTATIONS):
        hits = src.count(old)
        if hits != 1:
            print("  [锚点失配] %s：锚点命中 %d 次（要求恰 1 次）" % (label, hits))
            anchor_bad = 2
            continue
        mut = os.path.join(tmp, "mut_%d_postings.py" % idx)
        _write_norm(mut, src.replace(old, new))
        keep = list(_RESULTS)
        del _RESULTS[:]
        try:
            _use(mut)
            _case_sealed()
        except Exception as exc:
            _check("变异 %s：场景异常" % label, False, "%s: %s" % (type(exc).__name__, exc))
        reds = {n for n, ok, _d in _RESULTS if not ok}
        del _RESULTS[:]
        _RESULTS[:] = keep
        if reds == set(expect):
            print("  [PASS] %s —— 恰按 %d 条点名转红" % (label, len(reds)))
        else:
            print("  [FAIL] %s —— 多红 %r / 少红 %r"
                  % (label, sorted(reds - set(expect)), sorted(set(expect) - reds)))
            _check("变异 %s 按预期点名转红" % label, False,
                   "多红 %r / 少红 %r" % (sorted(reds - set(expect)), sorted(set(expect) - reds)))
    _use(os.path.join(REPO, IMPL_REL))
    if anchor_bad:
        return anchor_bad
    return 0 if all(ok for _n, ok, _d in _RESULTS) else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description="#152① 密封库 build fail-closed 守卫")
    ap.add_argument("--impl", default="", help="指定 postings 实现副本（head = 取 HEAD blob）")
    ap.add_argument("--mutate", action="store_true", help="定点变异自证")
    a = ap.parse_args(argv)
    with tempfile.TemporaryDirectory(prefix="iss152_guard_") as tmp:
        if a.mutate:
            return _mutate_mode(tmp)
        if a.impl == "head":
            return _baseline_mode(tmp)
        if a.impl:
            _use(os.path.abspath(a.impl))
        print("== #152① 密封库 postings.build fail-closed 守卫 ==\n")
        _case_sealed()
        _case_no_false_positive()
        _case_criteria()
        n_red = sum(1 for _n, ok, _d in _RESULTS if not ok)
        print("\n通过 %d / 失败 %d" % (len(_RESULTS) - n_red, n_red))
        return 1 if n_red else 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
