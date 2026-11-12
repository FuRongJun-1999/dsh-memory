# -*- coding: utf-8 -*-
# 功能名：index_code/index_doc 的节点 id 不含源根 ⇒ 跨仓静默覆写（issue #352-E）
# 生效条件：python -X utf8 -m md_cg.test_issue352_refindex [--mutate]；被测面=md_cg/refindex.py 的 root_clash/add_items + md_cg/mcp_server.py 的 index_code/index_doc + md_cg/sources.py 的 ingest 链
# 子功能：A 组=两仓同名相对路径不互相覆写、先索引一侧保住、冲突在回执里点名、冲突源文件的水位被丢掉（下次增量仍报冲突）；K 组=非恒真对照（单仓照常写、同根重复索引不算冲突、同根等价写法不算冲突、不同相对路径不算冲突、无 ref.root 的节点不算冲突）；E 组=源码面单点
# 执行：两个临时源仓各放同名 src/main.py，依次经 mcp_server.call_tool(cg, "cg", {op: index_code/index_doc …}) 索引，读节点正文与 frontmatter.code_ref.root
# 验证方式：全部 PASS 即通过；--mutate 走镜像树定点变异，变异后红项必须**恰为**预期集合
# 不适用条件：①**不改 id 键**（把源根并进哈希会动存量 id 的稳定性与幂等，属仓内缺口单 §6.3 的单独立项）②不判 prune_orphans 的清退面（它按 ref.root 判同根，本就不清退别的仓）③不判 logref 日志链的独立面（共用同一 node_id_of，随 id 键改造一起走）
"""issue #352-E 守卫：跨仓同名相对路径不得静默覆写（本轮=止血，不改 id 键）。

病象（修前）：node_id = sha1(**相对源根**路径 + 符号/标题)，同一记忆库先后索引两个
源目录时同名相对路径得到同一个 id —— B 仓的节点静默覆写 A 仓的（正文与 code_ref.root
一起换成 B），回执只报 indexed；水位按绝对路径记，A 此后增量重索引判「未变」跳过，
被覆写的节点再也补不回来。

处置（**止血，不动 id 键**）：写入前比对既有节点的 ref.root（realpath + normcase），
不同根即不覆写、把该条并入返回体 conflicts 并跳过；调用方把冲突源文件的水位一并丢掉
（否则下次增量把它判成「未变」跳过，冲突从此不可见）。

**存量兼容边界（E 条特别要求）**：
  · 新库 / 单仓用户零变化（同根永远是同一个根，无冲突）；
  · 已被历史覆写的库**不会自动修复**——那需要按 id 键改造做一次重索引（单独立项）；
  · 多仓同名节点暂时只保留**先索引的一侧**，另一侧只报冲突（两仓共存要等 id 键改造）。

★**过度收紧方向**：K2（同根重复索引不算冲突）、K3（同根的等价写法：尾随 /. 与
大小写，也不许算冲突）、K4（不同相对路径不算冲突）、K5（无 ref.root 的节点不算冲突）
四条盯住「闸没把正常面一起关掉」。
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)
_TMP = tempfile.mkdtemp(prefix="iss352e_")
os.environ.update({"MDCG_ROOT": _TMP + "/brainroot",
                   "MDCG_STATE_ROOT": _TMP + "/state",
                   "MDCG_AUX_ROOT": _TMP + "/auxstore",
                   "MDCG_DATA_ROOT": _TMP + "/datastore",
                   "MDCG_EXPORT_ROOT": _TMP,
                   "MDCG_INGEST_ROOT": _TMP,
                   "MDCG_SUSTAIN": "0", "MDCG_SLEEP": "0"})

from md_cg import refindex                              # noqa: E402
from md_cg import mcp_server                            # noqa: E402
from md_cg.mdcos import MdCGOS                          # noqa: E402

FAILS = []
_RUN = [0]


def _check(name, cond, detail=""):
    if cond:
        print("  PASS " + name)
    else:
        print("  FAIL " + name + "  " + str(detail)[:400])
        FAILS.append(name)


def _lib():
    _RUN[0] += 1
    return MdCGOS(os.path.join(_TMP, "brain_%d" % _RUN[0]), autoflush=1)


def _call(cg, **a):
    r = mcp_server.call_tool(cg, "cg", a)
    if isinstance(r, dict) and "content" in r:
        return json.loads(r["content"][0]["text"])
    return r


def _mk_repo(name, doc, rel="src/main.py"):
    root = os.path.join(_TMP, name)
    d = os.path.dirname(os.path.join(root, rel))
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(root, rel), "w", encoding="utf-8") as f:
        f.write('def main():\n    """%s"""\n    return 0\n' % doc)
    return root


def _mk_docrepo(name, body):
    root = os.path.join(_TMP, name)
    os.makedirs(root, exist_ok=True)
    with open(os.path.join(root, "README.md"), "w", encoding="utf-8") as f:
        f.write("# 项目\n\n## 安装\n\n%s\n" % body)
    return root


def _main_id(cg, out):
    """从回执 ids 里取 name==main 的那个节点 id（不猜哈希）。"""
    for i in (out.get("ids") or []):
        n = cg.get(i) or {}
        if ((n.get("frontmatter") or {}).get("code_ref") or {}).get("name") == "main":
            return i
    return None


def _root_of(cg, nid):
    return (((cg.get(nid) or {}).get("frontmatter") or {}).get("code_ref")
            or {}).get("root")


_A = _mk_repo("repoA", "仓库A：连接生产库 ALPHA_DB 端口 7001")
_B = _mk_repo("repoB", "仓库B：只打印 hello")
_DOCA = _mk_docrepo("docA", "安装步骤 ALPHA_KEY：先装依赖")
_DOCB = _mk_docrepo("docB", "安装步骤：直接运行")

print("== A 组：跨仓同 id 不得静默覆写 ==")

# --- E1：index_code 两仓同名 ---
_c1 = _lib()
_ra = _call(_c1, op="index_code", path=_A)
_nid = _main_id(_c1, _ra)
_rb = _call(_c1, op="index_code", path=_B)
_c1c = (_c1.get(_nid) or {}).get("content") or ""
print("   [读数] E1 A 节点 id=%s 索B 回执 indexed=%s conflict_count=%s "
      "节点 root=%s 含 ALPHA_DB=%s"
      % (_nid, _rb.get("indexed"), _rb.get("conflict_count"),
         os.path.basename(_root_of(_c1, _nid) or "?"),
         "ALPHA_DB" in _c1c))
_check("E1 index_code：B 仓同名符号不覆写 A 仓节点（正文与 code_ref.root 仍属 A），"
       "且回执点名冲突",
       bool(_nid) and "ALPHA_DB" in _c1c
       and os.path.normcase(os.path.realpath(_root_of(_c1, _nid) or ""))
       == os.path.normcase(os.path.realpath(_A))
       and (_rb.get("conflict_count") or 0) >= 1
       and _nid in [c.get("id") for c in (_rb.get("conflicts") or [])],
       _rb)

# --- E2：冲突后对 A 增量重索引，A 的节点仍属 A ---
_ra2 = _call(_c1, op="index_code", path=_A, incremental=True)
_c1c2 = (_c1.get(_nid) or {}).get("content") or ""
print("   [读数] E2 A 增量重索引 indexed=%s skipped=%s root=%s 含 ALPHA_DB=%s"
      % (_ra2.get("indexed"), _ra2.get("skipped_unchanged"),
         os.path.basename(_root_of(_c1, _nid) or "?"), "ALPHA_DB" in _c1c2))
_check("E2 增量重索引 A：节点仍归 A（不存在「被覆写后增量补不回」）",
       "ALPHA_DB" in _c1c2
       and os.path.normcase(os.path.realpath(_root_of(_c1, _nid) or ""))
       == os.path.normcase(os.path.realpath(_A)), _ra2)

# --- E4：冲突源文件的水位被丢掉 ⇒ 再跑 B 的增量索引**仍然**报冲突 ---
_rb2 = _call(_c1, op="index_code", path=_B, incremental=True)
print("   [读数] E4 再增量索引 B：indexed=%s skipped=%s conflict_count=%s"
      % (_rb2.get("indexed"), _rb2.get("skipped_unchanged"),
         _rb2.get("conflict_count")))
_check("E4 冲突源文件的水位被丢掉：再增量索引 B 仍报冲突（没被「未变」静默跳过）",
       (_rb2.get("conflict_count") or 0) >= 1
       and (_rb2.get("skipped_unchanged") or 0) == 0, _rb2)
_c1.close()

# --- E3：index_doc 同形（README.md 的「## 安装」节）---
_c2 = _lib()
_da = _call(_c2, op="index_doc", path=_DOCA)
_ids_a = list(_da.get("ids") or [])
_db = _call(_c2, op="index_doc", path=_DOCB)
# 冲突条目**不进 B 的 ids**（不覆写即不落盘），故以 A 的 ids 复核：它们必须仍归
# docA 且正文仍是 A 的内容，同时 B 的回执点名冲突。
_doc_ok = bool(_ids_a)
for i in _ids_a:
    n = _c2.get(i) or {}
    fm = n.get("frontmatter") or {}
    r = (fm.get("doc_ref") or {}).get("root")
    if not r or os.path.normcase(os.path.realpath(r)) != os.path.normcase(
            os.path.realpath(_DOCA)):
        _doc_ok = False
    if "ALPHA_KEY" not in (n.get("content") or ""):
        _doc_ok = False
print("   [读数] E3 A 的 doc 节点数=%d 仍归 A 且含 ALPHA_KEY=%s 索B conflict_count=%s"
      % (len(_ids_a), _doc_ok, _db.get("conflict_count")))
_check("E3 index_doc 同形：README.md 的同一节不跨仓覆写（A 的节点仍归 A，冲突在回执里点名）",
       _doc_ok and (_db.get("conflict_count") or 0) >= 1,
       (_ids_a, _db.get("conflict_count")))
_c2.close()

# ========================================================= K 组：非恒真对照
print("== K 组：非恒真对照（含**过度收紧**方向）==")

# --- K1：单仓照常写入 ---
_k1 = _lib()
_r = _call(_k1, op="index_code", path=_A)
print("   [读数] K1 单仓 indexed=%s conflict_count=%s"
      % (_r.get("indexed"), _r.get("conflict_count")))
_check("K1 单仓索引照常写入、零冲突（闸没把正常路径关掉）",
       (_r.get("indexed") or 0) >= 1 and not _r.get("conflict_count"), _r)

# --- K2：同根重复索引（全量）不算冲突 ---
_r2 = _call(_k1, op="index_code", path=_A)
print("   [读数] K2 同根重复索引 indexed=%s conflict_count=%s"
      % (_r2.get("indexed"), _r2.get("conflict_count")))
_check("K2 同一源根重复索引不算冲突（幂等：同根永远是同一个根）",
       (_r2.get("indexed") or 0) >= 1 and not _r2.get("conflict_count"), _r2)

# --- K3：同根的**等价写法**也不算冲突（尾随 /. 与大小写）---
_variants = [os.path.join(_A, "."), os.path.join(_A, "..", os.path.basename(_A))]
if os.name == "nt":
    _variants.append(_A.upper())
_r3 = None
for v in _variants:
    _r3 = _call(_k1, op="index_code", path=v)
    if _r3.get("conflict_count"):
        break
print("   [读数] K3 等价写法 %s → conflict_count=%s"
      % (len(_variants), _r3.get("conflict_count")))
_check("K3 同一源根的等价写法（尾随 /. 、.. 折算、Windows 大小写）不算冲突"
       "（复用既有 _same_root：normcase + abspath 口径）",
       (_r3.get("indexed") or 0) >= 1 and not _r3.get("conflict_count"), _r3)
_k1.close()

# --- K4：不同相对路径不算冲突 ---
_k4 = _lib()
_call(_k4, op="index_code", path=_A)
_r4 = _call(_k4, op="index_code", path=_mk_repo("repoC", "仓库C：另一个文件",
                                                rel="src/other.py"))
print("   [读数] K4 不同相对路径 indexed=%s conflict_count=%s"
      % (_r4.get("indexed"), _r4.get("conflict_count")))
_check("K4 不同相对路径（id 不同）不算冲突——闸只拦「同 id 已被别的源根占用」",
       (_r4.get("indexed") or 0) >= 1 and not _r4.get("conflict_count"), _r4)
_k4.close()

# --- K5：无 ref.root 的节点不算冲突（单元面）---
_k5 = _lib()
_k5.add("manual_node", "PASSED 手工节点（无 code_ref）", layer="knowledge")
_no_prev = refindex.root_clash(_k5, "does_not_exist", "code_ref", _A)
_no_ref = refindex.root_clash(_k5, "manual_node", "code_ref", _A)
print("   [读数] K5 无节点=%s 有节点无 ref=%s" % (_no_prev, _no_ref))
_check("K5 节点不存在 / 存在但无 ref.root 时都不算冲突（不误伤手工节点与老节点）",
       _no_prev is None and _no_ref is None, (_no_prev, _no_ref))
_k5.close()

# ========================================================= E 组：源码面单点
print("== E 组：源码面单点 ==")
_src_ri = open(os.path.join(_REPO, "md_cg", "refindex.py"),
               encoding="utf-8").read()
_src_ms = open(os.path.join(_REPO, "md_cg", "mcp_server.py"),
               encoding="utf-8").read()
_src_sr = open(os.path.join(_REPO, "md_cg", "sources.py"),
               encoding="utf-8").read()
_check("E5 冲突闸单点：refindex.root_clash 定义一处，add_items 写前调用",
       _src_ri.count("def root_clash(") == 1
       and "_clash = root_clash(cg, nid, kind, root)" in _src_ri
       and _src_ri.count("def _same_root(") == 1   # 同根判据复用既有单点，不新增第二份
       and "def _norm_root(" in _src_ri)
_check("E6 add_items 接受 conflicts 出参（不覆写即记账，不静默）",
       "extra_of=None, conflicts=None):" in _src_ri
       and "conflicts.append(dict(_clash" in _src_ri)
_check("E7 mcp_server 的 index_code/index_doc 都传 conflicts 并把冲突文件水位丢掉",
       _src_ms.count("conflicts=_cf)") == 2
       and _src_ms.count('led.drop(_c.get("src")') == 2
       and _src_ms.count('out["conflict_count"] = len(_cf)') == 2)
_check("E8 水位键仍是源文件绝对路径（_src_key 未被改动——跨根同名文件不互相覆盖）",
       "os.path.abspath(fp or" in _src_ri
       and _src_ri.count("def _src_key(") == 1)
_check("E9 ingest 链同口径（sources.py 也传 conflicts 并 drop 水位）",
       "conflicts=_cf)" in _src_sr and "ledger.drop(_c.get(" in _src_sr)

shutil.rmtree(_TMP, ignore_errors=True)

print("")
if FAILS:
    print("issue #352-E 结果：%d 失败 → %s" % (len(FAILS), ", ".join(FAILS)))
else:
    print("issue #352-E 结果：全部通过")

# ------------------------------------------------------------- 定点变异（镜像树）
_MUTATIONS = (
    ("M1 摘掉冲突闸（回到「同 id 直接覆写」的修前形态）",
     (("md_cg/refindex.py",
       ["        _clash = root_clash(cg, nid, kind, root)"],
       ["        _clash = None"]),),
     # E5 也红：它断言写前调用单点那条字面（同一条锚点）。
     ("E1", "E2", "E3", "E4", "E5")),
    ("M2 摘掉冲突源文件的水位丢弃（冲突被「未变」静默吃掉）",
     (("md_cg/mcp_server.py",
       ["        for _c in _cf:",
        '            led.drop(_c.get("src") or os.path.join(root, _c.get("path") or ""))',
        "        led.save()                       # 节点已落盘 → 水位随后（两步之间被杀即安全方向）"],
       ["        for _c in _cf:",
        "            pass",
        "        led.save()                       # 节点已落盘 → 水位随后（两步之间被杀即安全方向）"]),),
     # E7 也红：它数 drop 调用点（这条变异恰好摘掉 index_code 的那一处）。
     ("E4", "E7")),
    ("M3 **过度收紧方向**：同根也判成冲突（把幂等重索引一并拦掉）",
     (("md_cg/refindex.py",
       ["    if not prev_root or not root or _same_root(prev_root, root):"],
       ["    if not prev_root or not root or False:"]),),
     ("K2", "K3")),
    ("M4 **过度收紧方向**：去掉「无 ref.root 不算冲突」的豁免（误伤手工节点/老节点）",
     (("md_cg/refindex.py",
       ["    if not prev_root or not root or _same_root(prev_root, root):",
        "        return None",
        "    if not os.path.isdir(prev_root):"],
       ["    if not root or (prev_root is not None",
        "                       and not _same_root(prev_root, root)):",
        '        return {"id": nid, "kind": kind, "existing_root": prev_root,',
        '                "root": root}',
        "    if False:"]),),
     ("K2", "K3", "K5")),
    ("M5 摘掉 index_code 的冲突回执（不覆写但不点名）",
     (("md_cg/mcp_server.py",
       ['        ids, _sens = refindex.add_items(cg, items, kind="code_ref", root=root,',
        '                                        layer=a.get("layer"), conflicts=_cf)'],
       ['        ids, _sens = refindex.add_items(cg, items, kind="code_ref", root=root,',
        '                                        layer=a.get("layer"))']),),
     # E7 也红：conflicts=_cf 的调用点由 2 处变 1 处。
     ("E1", "E4", "E7")),
)


def _mirror_build():
    dst = tempfile.mkdtemp(prefix="iss352e_mut_")
    for name in ("md_cg", "scripts"):
        src = os.path.join(_REPO, name)
        if os.path.isdir(src):
            shutil.copytree(src, os.path.join(dst, name),
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for name in sorted(os.listdir(_REPO)):
        p = os.path.join(_REPO, name)
        if os.path.isfile(p) and name.endswith(".py"):
            shutil.copy2(p, os.path.join(dst, name))
    return dst


def _nl_of(path):
    with open(path, "rb") as fh:
        raw = fh.read(8192)
    return "\r\n" if b"\r\n" in raw else "\n"


def _run_in(tree):
    env = dict(os.environ)
    env["PYTHONPATH"] = tree
    env["PYTHONUTF8"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    pr = subprocess.run([sys.executable, "-X", "utf8", "-m",
                         "md_cg.test_issue352_refindex"],
                        capture_output=True, text=True, encoding="utf-8",
                        errors="replace", cwd=tree, env=env, timeout=1800)
    out = (pr.stdout or "") + (pr.stderr or "")
    reds = [ln.split("FAIL ", 1)[1].strip()
            for ln in out.splitlines() if "FAIL " in ln]
    return pr.returncode, reds, out


def _mutate():
    print("!! 定点变异自证：把修复点改回改动前形态，守卫必须转红")
    tree = _mirror_build()
    try:
        rc, reds, out = _run_in(tree)
        print("  未变异镜像基线：rc=%d 红项=%d（必须 rc=0 且 0 红）" % (rc, len(reds)))
        if rc != 0 or reds:
            print(chr(10).join(out.splitlines()[-30:]))
        for ln in out.splitlines():
            if "[读数]" in ln:
                print("  修后读数（未变异镜像）：" + ln.strip())
        okc, bad = 0, []
        for desc, edits, exp in _MUTATIONS:
            backups, miss = [], []
            for rel, oldp, newp in edits:
                p = os.path.join(tree, rel)
                nl = _nl_of(p)
                old, new = nl.join(oldp), nl.join(newp)
                with open(p, encoding="utf-8", newline="") as fh:
                    t = fh.read()
                if t.count(old) != 1:
                    miss.append("%s —— 锚点命中 %d 次" % (rel, t.count(old)))
                    continue
                backups.append((p, t))
                with open(p, "w", encoding="utf-8", newline="") as fh:
                    fh.write(t.replace(old, new, 1))
            if miss:
                bad.append("%s —— %s" % (desc, "；".join(miss)))
                print("  ANCHOR-MISS " + desc)
                for p, t in backups:
                    with open(p, "w", encoding="utf-8", newline="") as fh:
                        fh.write(t)
                continue
            rc2, reds2, out2 = _run_in(tree)
            for p, t in backups:
                with open(p, "w", encoding="utf-8", newline="") as fh:
                    fh.write(t)
            hit = sorted({e for r in reds2 for e in exp if r.startswith(e + " ")})
            if rc2 != 0 and hit == sorted(exp) and len(reds2) == len(exp):
                okc += 1
                print("  OK   %s  红项=%d 指定命中=%d/%d"
                      % (desc, len(reds2), len(hit), len(exp)))
            else:
                bad.append(desc)
                print("  MISMATCH %s  红项=%d 指定命中=%d/%d rc=%d"
                      % (desc, len(reds2), len(hit), len(exp), rc2))
                for r in reds2[:14]:
                    print("        FAIL " + r)
        print("定点变异自证：%s（%d 条不合格）"
              % ("PASS" if not bad else "FAIL", len(bad)))
        for b in bad:
            print("  不合格：" + b)
    finally:
        shutil.rmtree(tree, ignore_errors=True)


def main():
    if "--mutate" in sys.argv:
        _mutate()
        return 1 if FAILS else 0
    return 0 if not FAILS else 1


if __name__ == "__main__":
    sys.exit(main())
