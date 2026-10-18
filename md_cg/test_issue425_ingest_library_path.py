# -*- coding: utf-8 -*-
# 功能名：摄取链不得把记忆库内部（库根/层目录/trash/保护历史）当外部文档重新索引——issue #425
# 生效条件：python -X utf8 -m md_cg.test_issue425_ingest_library_path [--mutate]；被测面＝md_cg/sources.py::library_rel/library_reserved/library_ingest_guard/library_skip_rel 与 ingest_file/ingest_dir/ingest_jsonl 的过闸点
# 子功能：A 组＝显式 path=<库根> 与 action=file 指向 trash/<id>.md 时 restricted 正文/已删除节点不被访客检索到；B 组＝白名单=库根上级目录时 dir 空 path 整枝剪掉库根；K 组＝非恒真对照（库外目录照常摄取、库根下普通子目录照常摄取、private 节点不泄露）
# 执行：--mutate 时在镜像树里回退单文件闸 / 目录闸 / 剪枝，守卫必须按指定项转红
# 验证方式：全部 PASS 即通过（退出码 0）；默认模式另做源码锚点自检（关键判据字面量缺失 ⇒ exit 2，fail-closed）；--mutate 模式红项集合须与预期逐项相符
# 不适用条件：不判真实 MCP stdio 子进程面（本守卫走 `mcp_server._dispatch`，即 tools/call 同一分派函数）；不判 `op=index_doc/index_code` 的库内重索引（那条链保留源密级与保护闸，不在本条）；不判库根下**普通子目录**里存放的库内节点副本（调用方自担）；不判存量已泄露的 doc_* 节点清理
"""issue #425 守卫：库内节点文件 / 回收站 / 保护历史**不是外部文档**。

病象（修前）：`cg(op=ingest, action=dir, path=<库根>)` 或 `action=file` 指向
`trash/<id>.md` 时，摄取链把库内 md 当外部文档重新切成 `doc_*` 节点——
restricted 正文被抄成 internal（无令牌访客可检索）、已 forget+accept 删除的
节点从 trash 复活。`MDCG_INGEST_ROOT` 设成库根上级目录时，空 path 的 dir 摄取
同样扫进整个库根。

修法（条件层）：新增库内路径闸单点 `library_ingest_guard`（库根 / 层目录 /
trash / _protected_history / hippocampus 等保留子树一律 fail-closed），
`ingest_file` / `ingest_dir` / `ingest_jsonl` 三入口过同一闸；`ingest_dir` 在
root 是库根**祖先**时把库根整枝剪进 `skip_dirs`（复用 codeindex.skip_matcher
唯一实现），并在回执里如实回报 `library_pruned`。
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

for _k in [k for k in os.environ if k.startswith("MDCG_")]:
    del os.environ[_k]

FAILS = []
_T = tempfile.mkdtemp(prefix="iss425_")
ROOT = os.path.join(_T, "brain")
EXT = os.path.join(_T, "extsrc")
OUTSIDE = os.path.join(_T, "outside_root")
os.environ.update(HOME=_T, MDCG_ROOT=ROOT,
                  MDCG_STATE_ROOT=os.path.join(_T, "stateroot"),
                  MDCG_AUX_ROOT=os.path.join(_T, "auxroot"),
                  MDCG_DATA_ROOT=os.path.join(_T, "dataroot"),
                  MDCG_EXPORT_ROOT=_T, MDCG_SUSTAIN="0", MDCG_SLEEP="0")

from md_cg.mdcos import MdCGSecure           # noqa: E402
from md_cg.security import Principal         # noqa: E402
from md_cg.tokens import role_spec           # noqa: E402
from md_cg import mcp_server as ms           # noqa: E402
from md_cg import sources                    # noqa: E402

HDR = "# 功能名：{0}\n# 生效条件：无条件\n# 执行：见下\n\n## 细节\n"
REST = HDR.format("运维处置") + "RESTMK1 跳板机 10.0.0.7，误删主库后的处置细节与回滚步骤记录如下。" * 6
FORGOT = HDR.format("前任联系方式") + "FORGOTMK 前任手机 13800001111 住址 某路 12 号，已决定忘掉这条。" * 6
PLAIN = HDR.format("外部资料") + "EXTMK 公开资料正文，可正常摄取。" * 8


def _check(name, cond, detail=""):
    if cond:
        print("  PASS " + name)
    else:
        print("  FAIL " + name + "  " + str(detail)[:220])
        FAILS.append(name)


def P(role, clr):
    s = role_spec(role)
    return Principal(role=role, clearance=clr, can_write=s["can_write"],
                     can_admin=s["can_admin"], layers_allow=s["layers_allow"],
                     ops_allow=s["ops_allow"])


def _call(cg, tool, args):
    try:
        return ms._dispatch(cg, tool, args)
    except Exception as e:                     # noqa: BLE001
        return {"_exc": type(e).__name__, "_msg": str(e)[:140]}


def _hits(cg, q, mark):
    rs = (_call(cg, "mdcg_search", {"query": q}) or {}).get("results") or []
    return [r["node"]["id"] for r in rs
            if mark in ((r.get("node") or {}).get("content") or "")]


# ---- 夹具：属主写 restricted + internal 两条，后者 forget+accept ----
os.makedirs(EXT, exist_ok=True)
os.makedirs(OUTSIDE, exist_ok=True)
own = MdCGSecure(ROOT, principal=P("designer", "secret"), autoflush=1)
rid = _call(own, "mdcg_remember", {"content": REST, "sensitivity": "restricted",
                                   "layer": "knowledge"})["id"]
fid = _call(own, "mdcg_remember", {"content": FORGOT, "layer": "contextual"})["id"]
_call(own, "mdcg_forget", {"node_id": fid, "reason": "用户要求删除"})
_pend = _call(own, "mdcg_review_list", {})
_pend = _pend.get("pending") if isinstance(_pend, dict) else _pend
for p in _pend or []:
    _call(own, "mdcg_review_decide", {"pid": p["pid"], "decision": "accept"})
_pid = _call(own, "mdcg_remember", {"content": PLAIN + "PRIVMK 私密补充。",
                                    "sensitivity": "private", "layer": "knowledge"})["id"]
own.close()
with open(os.path.join(EXT, "note.md"), "w", encoding="utf-8") as f:
    f.write(PLAIN)
os.makedirs(os.path.join(ROOT, "notes"), exist_ok=True)
with open(os.path.join(ROOT, "notes", "ext_note.md"), "w", encoding="utf-8") as f:
    f.write(PLAIN + "SUBDIRMK 库根普通子目录里的外部资料。")

print("== A 组：库根 / trash 不得被当外部文档摄取（#425 正题） ==")
rec = MdCGSecure(ROOT, principal=P("record", "internal"), autoflush=1)
print("[0] record get restricted ->", (_call(rec, "mdcg_get", {"node_id": rid}) or {}).get("error"))
_d = _call(rec, "cg", {"op": "ingest", "action": "dir", "path": ROOT})
_check("A1 显式 path=<库根> 的 dir 摄取被拒（fail-closed，error 点名 issue #425）",
       _d.get("ok") is False and "issue #425" in str(_d.get("error")), _d)
_tp = os.path.join(ROOT, "trash", fid + ".md")
_f = _call(rec, "cg", {"op": "ingest", "action": "file", "path": _tp})
_check("A2 action=file 指向 trash/<id>.md 被拒（已删除节点不复活）",
       _f.get("ok") is False and "issue #425" in str(_f.get("error")), _f)
_layer_md = os.path.join(ROOT, "knowledge", "orphan", rid + ".md")
_f2 = _call(rec, "cg", {"op": "ingest", "action": "file", "path": _layer_md})
_check("A3 action=file 指向层目录内节点文件被拒（restricted 正文不被抄成 internal）",
       _f2.get("ok") is False and "issue #425" in str(_f2.get("error")), _f2)
_j = _call(rec, "cg", {"op": "ingest", "action": "jsonl",
                       "path": os.path.join(ROOT, "hippocampus", "inbox.jsonl")})
_check("A4 action=jsonl 指向库内台账被拒（库内账本不是外部会话源）",
       _j.get("ok") is False and "issue #425" in str(_j.get("error")), _j)
rec.close()

guest = MdCGSecure(ROOT, principal=P("guest", "internal"), autoflush=1)
_g_rest = _hits(guest, "RESTMK1 跳板机", "RESTMK1")
_g_forgot = _hits(guest, "FORGOTMK 前任手机", "FORGOTMK")
_check("A5 访客检索不到 restricted 正文与已删除内容（修前：两条都命中）",
       not _g_rest and not _g_forgot, (_g_rest, _g_forgot))
_check("A6 对照：访客仍读不到 private 节点正文",
       "PRIVMK" not in json.dumps(_call(guest, "mdcg_get", {"node_id": _pid}),
                                  ensure_ascii=False))
guest.close()

print("== B 组：白名单=库根上级目录时，dir 空 path 整枝剪掉库根（C7） ==")
os.environ["MDCG_INGEST_ROOT"] = _T
rec7 = MdCGSecure(ROOT, principal=P("record", "internal"), autoflush=1)
_r7 = _call(rec7, "cg", {"op": "ingest", "action": "dir"})
_doc7 = (_r7.get("chains") or {}).get("doc") or {}
_check("B1 白名单=库根上级 + 空 path：库根被剪枝并如实回报",
       _r7.get("ok") is True and _r7.get("library_pruned") == ["brain"], _r7.get("library_pruned"))
# 库根下的节点/trash 一个都不许被索引：把每个 doc 节点的「源根 + 相对路径」
# 还原成源文件路径，判它是否落在库根内（同目录还有合法的库外兄弟目录 extsrc，
# 故不能用 indexed==0 作判据；也不能只看 doc_ref.root——祖先摄取时 root 是上级）。
_lib = os.path.normcase(os.path.realpath(ROOT))
_from_lib = []
for nid, e in list((rec7.index.get("nodes") or {}).items()):   # 快照迭代（W7 G1a）
    if not nid.startswith("doc_"):
        continue
    node = _call(rec7, "mdcg_get", {"node_id": nid}) or {}
    ref = (node.get("frontmatter") or {}).get("doc_ref") or {}
    r, rel = ref.get("root"), ref.get("path")
    if not r or not rel:
        continue
    fp = os.path.normcase(os.path.realpath(os.path.join(r, rel)))
    if fp == _lib or fp.startswith(_lib + os.sep):
        _from_lib.append(nid)
_check("B2 库根下没有任何节点被切成 doc_* 节点（trash/层目录/保护历史全部剪掉）",
       not _from_lib, _from_lib)
guest7 = MdCGSecure(ROOT, principal=P("guest", "internal"), autoflush=1)
_g7 = _hits(guest7, "RESTMK1 跳板机", "RESTMK1")
_check("B3 访客检索不到库内 restricted 正文（修前：命中）", not _g7, _g7)
guest7.close()
rec7.close()

print("== K 组：非恒真对照（只拒库内保留子树，不误伤合法摄取） ==")
rec_k = MdCGSecure(ROOT, principal=P("record", "internal"), autoflush=1)
_ke = _call(rec_k, "cg", {"op": "ingest", "action": "dir", "path": EXT})
_check("K1 库外目录照常摄取（indexed>0）",
       _ke.get("ok") is True and ((_ke.get("chains") or {}).get("doc") or {}).get("indexed", 0) > 0,
       _ke)
_ks = _call(rec_k, "cg", {"op": "ingest", "action": "dir", "path": os.path.join(ROOT, "notes")})
_check("K2 库根下**普通子目录**仍可作外部资料根（保留既有用法）",
       _ks.get("ok") is True and ((_ks.get("chains") or {}).get("doc") or {}).get("indexed", 0) > 0,
       _ks)
_kf = _call(rec_k, "cg", {"op": "ingest", "action": "file", "path": os.path.join(EXT, "note.md")})
_check("K3 库外单文件照常摄取", _kf.get("ok") is True and _kf.get("indexed", 0) > 0, _kf)
rec_k.close()
os.environ.pop("MDCG_INGEST_ROOT", None)

print("== C 组：判据单点（源码锚点） ==")
_SRC = open(os.path.join(_REPO, "md_cg", "sources.py"), encoding="utf-8").read()
_MISSING = [n for n in ("def library_ingest_guard(",
                        "def library_rel(",
                        "def library_reserved(",
                        "def library_skip_rel(",
                        "library_ingest_guard(self.cg, path, \"ingest file\")",
                        "library_ingest_guard(self.cg, root, \"ingest dir\")",
                        "library_ingest_guard(self.cg, path, \"ingest jsonl\")")
            if n not in _SRC]
_check("C01 库内路径闸是单点（一个判定函数 + 三入口都调它）", not _MISSING, _MISSING)
_check("C02 保留子树名单不复制层目录（层目录从 mdcg.LAYERS 取）",
       "from .mdcg import LAYERS" in _SRC)
_check("C03 祖先剪枝复用 codeindex.skip_matcher 唯一实现（经 refindex.index_dir 的 skip_dirs）",
       "skip_dirs=_skip" in _SRC and "def skip_matcher(" in open(
           os.path.join(_REPO, "md_cg", "codeindex.py"), encoding="utf-8").read())

if _MISSING and "--mutate" not in sys.argv:
    print("锚点自检失败：关键判据字面量缺失 %s" % _MISSING)
    shutil.rmtree(_T, ignore_errors=True)
    sys.exit(2)


def _mirror_build():
    dst = tempfile.mkdtemp(prefix="iss425_mut_")
    for name in ("md_cg", "scripts"):
        src = os.path.join(_REPO, name)
        if os.path.isdir(src):
            shutil.copytree(src, os.path.join(dst, name),
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for name in sorted(os.listdir(_REPO)):
        p = os.path.join(_REPO, name)
        if os.path.isfile(p) and (name.endswith(".py")
                                  or name in ("README.md", "pyproject.toml")):
            shutil.copy2(p, os.path.join(dst, name))
    return dst


def _run_in(tree):
    env = dict(os.environ)
    env.update({"PYTHONPATH": tree, "PYTHONUTF8": "1",
                "PYTHONDONTWRITEBYTECODE": "1"})
    for k in ("MDCG_ROOT", "MDCG_TOKEN", "MDCG_VERIFY_KEY", "MDCG_INGEST_ROOT"):
        env.pop(k, None)
    pr = subprocess.run([sys.executable, "-X", "utf8", "-m",
                         "md_cg.test_issue425_ingest_library_path"],
                        cwd=tree, env=env, capture_output=True, text=True,
                        encoding="utf-8", errors="replace", timeout=1200)
    out = (pr.stdout or "") + (pr.stderr or "")
    reds = [ln.split("FAIL ", 1)[1].strip()
            for ln in out.splitlines() if ln.strip().startswith("FAIL ")]
    return pr.returncode, reds, out


_NL = "\r\n" if b"\r\n" in open(os.path.join(_REPO, "md_cg", "sources.py"),
                                 "rb").read()[:8192] else "\n"


def _j(*lines):
    return _NL.join(lines)


# 如实登记变异下的红项集合：下游 #346 的同层覆写闸（protect.require_layer）会在
# 「库内 restricted 节点被覆写」这一步抛 AccessDenied，于是「库根被扫进来」的后果
# 可能被第二道闸挡住 ⇒ A5/B2/B3 在不同变异下红/不红取决于该下游闸是否恰好兜住。
# 判据仍直接命中缺陷点：**指定项必须红**（附加红项 = 更强判别力，不作失败）。
#   · M1 回退单文件闸 ⇒ A2/A3（库内文件被当外部文档）与 C01 必红；
#   · M2 回退目录闸   ⇒ A1（dir 摄取库根未被本闸拒绝）与 C01 必红；
#   · M3 回退剪枝     ⇒ B1（剪枝回报缺失）必红。
_MUTATIONS = (
    ("M1 回缺陷：单文件链不过库内闸", "md_cg/sources.py",
     (_j("        _g = library_ingest_guard(self.cg, path, \"ingest file\")",
         "        if _g is not None:",
         "            return _g"),
      _j("        _g = None  # 变异：单文件链不过闸")),
     ("A2", "A3", "C01")),
    ("M2 回缺陷：目录链不过库内闸", "md_cg/sources.py",
     (_j("        _g = library_ingest_guard(self.cg, root, \"ingest dir\")",
         "        if _g is not None:",
         "            return _g"),
      _j("        _g = None  # 变异：目录链不过闸")),
     ("A1", "C01")),
    ("M3 回缺陷：祖先目录不剪枝", "md_cg/sources.py",
     (_j("        _lib_rel = library_skip_rel(self.cg, root)",
         "        _skip = [_lib_rel] if _lib_rel else None"),
      _j("        _lib_rel = None  # 变异：不剪枝",
         "        _skip = None")),
     ("B1",)),
)


def _mutate():
    print("!! 定点变异：回退三处库内闸，守卫必须按指定项转红")
    tree = _mirror_build()
    bad = []
    try:
        rc, reds, out = _run_in(tree)
        print("  未变异镜像基线：rc=%d 红项=%d（必须 rc=0 且 0 红）" % (rc, len(reds)))
        if rc != 0 or reds:
            print("\n".join(out.splitlines()[-20:]))
            bad.append("镜像基线非绿")
        for desc, rel, (old, new), exp in _MUTATIONS:
            p = os.path.join(tree, rel)
            t = open(p, encoding="utf-8", newline="").read()
            if t.count(old) != 1:
                bad.append("%s 锚点命中 %d 次" % (desc, t.count(old)))
                print("  ANCHOR-MISS " + desc)
                continue
            bak = t
            open(p, "w", encoding="utf-8", newline="").write(t.replace(old, new, 1))
            for r, _dd, _ff in os.walk(tree):
                if os.path.basename(r) == "__pycache__":
                    shutil.rmtree(r, ignore_errors=True)
            rc2, reds2, _o2 = _run_in(tree)
            open(p, "w", encoding="utf-8", newline="").write(bak)
            hit = sorted({r.split(" ")[0] for r in reds2})
            # 判据：**指定项必须红**；附加红项是更强判别力（下游 #346 覆写闸
            # 是否兜住取决于变异形态），不作失败——如实打印出来。
            _extra = sorted(set(hit) - set(exp))
            if rc2 != 0 and set(exp) <= set(hit):
                print("  OK   %s  红项=%d 指定命中=%d/%d%s"
                      % (desc, len(reds2), len(set(exp)), len(exp),
                         ("  附加红项=" + str(_extra)) if _extra else ""))
            else:
                bad.append(desc)
                print("  MISMATCH %s 实际=%s 期望(必红)=%s rc=%d"
                      % (desc, hit, sorted(exp), rc2))
                for r in reds2[:8]:
                    print("        FAIL " + r)
        print("定点变异自证：%s（%d 条不合格）" % ("PASS" if not bad else "FAIL", len(bad)))
        return len(bad)
    finally:
        shutil.rmtree(tree, ignore_errors=True)


shutil.rmtree(_T, ignore_errors=True)
print("")
print("issue #425 结果：%s" % ("全部通过" if not FAILS else "%d 失败" % len(FAILS)))


def main():
    _bad = _mutate() if "--mutate" in sys.argv else 0
    return 1 if (FAILS or _bad) else 0


if __name__ == "__main__":
    sys.exit(main())
