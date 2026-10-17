# -*- coding: utf-8 -*-
# 功能名：ingest 显式 path 落在记忆库根内/库根祖先不得绕过读隔离与删除（issue #425）
# 生效条件：python -X utf8 -m md_cg.test_issue425_ingest_libroot_bypass [--mutate]；被测面=md_cg/sources.py 的 run 入口闸（security.check_ingest_source）与 md_cg/refindex.py 的 index_dir 剪枝（_lib_subtree_rule）
# 子功能：A 组=C5 显式 path=<库根> 拒 + 访客检索不到 restricted/已删除正文；B 组=C6 action=file 指向 trash/<id>.md 拒；C 组=C7 白名单/显式 path=库根上级时库根子树剪枝（回执点名、不静默）+ 库外文档不误伤 + session 腿库内 jsonl 剔除；K 组=#351 空 path 语义 / 越白名单拒 / record 读不到 restricted / jsonl 腿同闸 / stat 不受影响
# 执行：--mutate 时 V1 把 run 入口闸改成恒假（C5/C6 复活）、V2 把 index_dir 剪枝改成恒假（C7 复活），守卫必须转红
# 验证方式：全部 PASS 即通过；--mutate 下变异的「指定命中」须与预期一致
# 不适用条件：不覆盖 op=index_code/index_doc 显式传库根/祖先根（designer 面，另立）；不测 private 正文（密文，#425 明示不在面内）；不测 mdcg_ingest 工具面（会话源，无 file/dir 腿）；不覆盖 POSIX 腿
"""issue #425 守卫：ingest 的显式 path= 库根 / 库内 / 库根祖先三面不得把库内节点当外部文档。

病象（修前，HEAD dd8a9640 实测 4/4 命中）：#351 的修复只堵了 dir 的**空 path**；
持 record 令牌（clearance=internal）时——
  · C5 显式 path=<库根>：restricted 正文被抄进 internal 的 doc_* 节点（无令牌
    访客 mdcg_search 可检索）；
  · C6 action=file 指向 trash/<id>.md：已 forget 并 accept 删除的节点复活；
  · C7 MDCG_INGEST_ROOT=库根上级：空 path 经 env 解析 / 显式 path=上级目录，
    walk 钻进库根整棵重切（同 C5 后果）。
根因：白名单未配置时回落记忆库根本身（#85 选 A），check_path_root 只判
「在根内」，库根与库内路径全放行。

修复（两道，单点判据）：① sources.run 入口对 file/dir/jsonl 统一过
security.check_ingest_source——realpath 等于库根或落在库根内即拒
（normcase(realpath)，与 check_export_target 同平台口径）；② refindex.index_dir
在给了 ledger（ledger.root 即记忆库根）时，扫描根是库根祖先则把库根子树
整枝剪掉（并入 skip_dirs，stats["skipped_dirs"] 如实回报），sources.ingest_dir
的 session 腿同步剔除库内 .jsonl 并计数（skipped_in_lib）。
"""
import os
import shutil
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)
_TMP = tempfile.mkdtemp(prefix="iss425_")
os.environ.update({"MDCG_ROOT": _TMP + "/brainroot", "MDCG_STATE_ROOT": _TMP + "/state",
                   "MDCG_AUX_ROOT": _TMP + "/auxstore",
                   "MDCG_DATA_ROOT": _TMP + "/datastore", "MDCG_EXPORT_ROOT": _TMP,
                   "MDCG_SUSTAIN": "0", "MDCG_SLEEP": "0"})
os.environ.pop("MDCG_INGEST_ROOT", None)
from md_cg.mdcos import MdCGSecure  # noqa: E402
from md_cg.security import Principal  # noqa: E402
from md_cg import mcp_server as _ms  # noqa: E402

FAILS = []
ROOT = os.environ["MDCG_ROOT"]

HDR = "# 功能名：{0}\n# 生效条件：无条件\n# 执行：见下\n\n## 细节\n"
REST = HDR.format("运维处置") + ("RESTMK1 跳板机 10.0.0.7，误删主库后的处置细节与回滚步骤记录如下。" * 6)
SHORT = HDR.format("机房门禁") + "SHORTMK 门禁码 4321，短正文也不得被抄出。"
FORGOT = HDR.format("前任联系方式") + ("FORGOTMK 前任手机 13800001111 住址 某路 12 号，已决定忘掉这条。" * 6)


def _check(name, cond, detail=""):
    if cond:
        print("  PASS " + name)
    else:
        print("  FAIL " + name + "  " + str(detail)[:200])
        FAILS.append(name)


def _mk(role, clearance, write=True, admin=None):
    p = Principal(role=role, clearance=clearance, can_write=write,
                  can_admin=admin if admin is not None else (role == "designer"))
    return MdCGSecure(ROOT, principal=p, autoflush=1)


def _T(cg, name, args):
    try:
        return _ms.call_tool(cg, name, args)
    except Exception as e:                      # noqa: BLE001
        return {"_exc": type(e).__name__ + ":" + str(e)[:600]}


def _ingest(cg, args):
    return _T(cg, "cg", dict({"op": "ingest"}, **args))


def _hits(cg, mark):
    rs = (_T(cg, "mdcg_search", {"query": mark}) or {}).get("results") or []
    return [x["node"]["id"] for x in rs if mark in (x["node"].get("content") or "")]


def _seed():
    """属主视角造库：restricted 长文（RESTMK）+ restricted 短文（SHORTMK，C8 形状）
    + 一条已 forget 并 accept 删除的节点（FORGOTMK）。返回 (rid, fid)。"""
    own = _mk("designer", "secret")
    rid = (_T(own, "mdcg_remember", {"content": REST, "sensitivity": "restricted",
                                     "layer": "knowledge"}) or {}).get("id")
    _T(own, "mdcg_remember", {"content": SHORT, "sensitivity": "restricted",
                              "layer": "knowledge"})
    fid = (_T(own, "mdcg_remember", {"content": FORGOT, "layer": "contextual"})
           or {}).get("id")
    _T(own, "mdcg_forget", {"node_id": fid, "reason": "用户要求删除"})
    pend = _T(own, "mdcg_review_list", {})
    pend = pend.get("pending") if isinstance(pend, dict) else pend
    for p in pend or []:
        _T(own, "mdcg_review_decide", {"pid": p["pid"], "decision": "accept"})
    own.close()
    return rid, fid


def _fresh():
    for k in ("brainroot", "state", "auxstore", "datastore"):
        shutil.rmtree(os.path.join(_TMP, k), ignore_errors=True)
        os.makedirs(os.path.join(_TMP, k), exist_ok=True)


def _guest_hits(*marks):
    g = _mk("guest", "internal", write=False, admin=False)
    out = {m: _hits(g, m) for m in marks}
    g.close()
    return out


print("== A 组：C5 显式 path=<库根>（未设 MDCG_INGEST_ROOT，白名单回落库根） ==")
_seed()
rec = _mk("record", "internal")
_a1 = _ingest(rec, {"action": "dir", "path": ROOT})
_check("A1 显式 path=<库根> dir → PermissionError 点名 issue #425 与「记忆库根内」",
       "PermissionError" in str(_a1) and "issue #425" in str(_a1)
       and "记忆库根" in str(_a1), str(_a1)[:160])
rec.close()
_gh = _guest_hits("RESTMK1", "SHORTMK", "FORGOTMK")
_check("A2 A1 后无令牌访客检索不到 restricted 正文（长文 RESTMK / 短文 SHORTMK）",
       not _gh["RESTMK1"] and not _gh["SHORTMK"], _gh)
_check("A3 A1 后已 forget+accept 的内容不复活（FORGOTMK 无命中）",
       not _gh["FORGOTMK"], _gh)

print("== B 组：C6 action=file 指向 trash/<id>.md ==")
_fresh()
_, fid_b = _seed()
rec = _mk("record", "internal")
_tp = os.path.join(ROOT, "trash", fid_b + ".md")
_b1 = _ingest(rec, {"action": "file", "path": _tp})
rec.close()
_check("B1 file 指向 trash/<id>.md → PermissionError 点名 issue #425",
       "PermissionError" in str(_b1) and "issue #425" in str(_b1), str(_b1)[:160])
_check("B2 B1 后已删除内容不被访客检索到（FORGOTMK 无命中）",
       not _guest_hits("FORGOTMK")["FORGOTMK"], "")

print("== C 组：C7 白名单/显式 path=库根上级目录（剪枝，不静默） ==")
_fresh()
_rid_c, _ = _seed()
_ext = os.path.join(_TMP, "ws", "extdocs")            # _TMP/ws 是库根（_TMP/brainroot
os.makedirs(_ext, exist_ok=True)                      # 之外另一棵子树）的兄弟目录，
with open(os.path.join(_ext, "note.md"), "w", encoding="utf-8") as f:  # 同受 ws 摄取
    f.write("# 功能名：外部资料\n# 生效条件：a\n# 执行：b\n# 验证方式：c\n"
            "# 不适用条件：d\n\n## 细节\n" + "EXTMK 外部资料正文段落，应照常索引。" * 8)
with open(os.path.join(_ext, "session.jsonl"), "w", encoding="utf-8") as f:
    f.write('{"type": "user/message", "text": "EXTSESS 外部会话一行"}\n')
_WS = os.path.join(_TMP, "ws")
os.makedirs(_WS, exist_ok=True)
os.environ["MDCG_INGEST_ROOT"] = _TMP                 # _TMP = 库根与 ws 的上级
rec = _mk("record", "internal")
_c1 = _ingest(rec, {"action": "dir"})                # 空 path → env 解析成 _TMP
_doc_c1 = ((_c1.get("chains") or {}).get("doc")) or {}
rec.close()
_check("C1 白名单=库根上级时空 path（env 解析）不扫库内节点（doc 链 files 只数库外 .md）",
       _c1.get("ok") is True and _doc_c1.get("files") == 1, _doc_c1)
_gh2 = _guest_hits("RESTMK1", "FORGOTMK")
_check("C2 剪枝后访客检索不到库内 restricted/已删除正文",
       not _gh2["RESTMK1"] and not _gh2["FORGOTMK"], _gh2)
_sd = list(_doc_c1.get("skipped_dirs") or [])
_check("C3 剪枝不静默：doc 链回执 skipped_dirs 点名库根子树",
       any("brainroot" in s for s in _sd), _sd)
rec = _mk("record", "internal")
_c4 = _ingest(rec, {"action": "dir", "path": _TMP})  # 显式 path=上级目录
rec.close()
_doc_c4 = ((_c4.get("chains") or {}).get("doc")) or {}
_check("C4 显式 path=<库根上级> 同剪枝判据（files 只数库外 .md）",
       _c4.get("ok") is True and _doc_c4.get("files") == 1, _doc_c4)
_g3 = _guest_hits("EXTMK")
_check("C5 库外文档照常索引（不误伤合法摄取面：EXTMK 有命中）",
       bool(_g3["EXTMK"]), _g3)
_ses = ((_c4.get("chains") or {}).get("session")) or {}
_check("C6 session 腿剔除库内 .jsonl 并计数（库内有 _audit/_deletions 等派生物）",
       _ses.get("files") == 1 and (_ses.get("skipped_in_lib") or 0) >= 1, _ses)
os.environ.pop("MDCG_INGEST_ROOT", None)

print("== K 组：既有语义不回归 ==")
rec = _mk("record", "internal")
_k1 = _ingest(rec, {"action": "dir"})
_check("K1 未设 env、dir 空 path → 仍按 #351 拒（fail-closed 保持）",
       _k1.get("ok") is False and "issue #351" in str(_k1.get("error")), str(_k1)[:150])
os.environ["MDCG_INGEST_ROOT"] = _WS
_k2 = _ingest(rec, {"action": "dir", "path": _TMP})
_check("K2 越白名单路径仍被 check_path_root 拒（白名单闸保持）",
       "PermissionError" in str(_k2) and "白名单" in str(_k2), str(_k2)[:150])
os.environ.pop("MDCG_INGEST_ROOT", None)
_k3 = _T(rec, "mdcg_get", {"node_id": _rid_c})
_check("K3 record 直接 get restricted 节点 not_found（越权读前提仍在，不在本修面）",
       "not_found" in str(_k3.get("error", _k3)), str(_k3)[:120])
_k4 = _ingest(rec, {"action": "jsonl", "path": os.path.join(ROOT, "_audit.jsonl")})
_check("K4 jsonl 腿同闸：库内 _audit.jsonl → PermissionError 点名 issue #425",
       "PermissionError" in str(_k4) and "issue #425" in str(_k4), str(_k4)[:150])
_k5 = _ingest(rec, {"action": "stat"})
_check("K5 stat（无 path）不受影响",
       _k5.get("ok") is True, str(_k5)[:120])
rec.close()

shutil.rmtree(_TMP, ignore_errors=True)

print("")
if FAILS:
    print("issue #425 结果：%d 失败" % len(FAILS))
else:
    print("issue #425 结果：全部通过")

# ------------------------------------------------------------------ 定点变异
# 锚点取「注释行 + 判据行」唯一片段（按目标文件实际 NL 折算，同 #351 守卫）。
_MUTATIONS = (
    ("V1 run 入口闸恒假（即 #425 修前：显式 path/file 指库内不再拒）",
     "md_cg/sources.py",
     "    if act in (\"file\", \"dir\", \"jsonl\"):" + chr(10)
     + "        from .security import check_ingest_source",
     "    if act in (\"file\", \"dir\", \"jsonl\") and False:" + chr(10)
     + "        from .security import check_ingest_source",
     ("A1", "A2", "A3", "B1", "B2", "K4")),
    ("V2 index_dir 剪枝恒假（即 #425 修前：白名单=库根上级时照扫库内）",
     "md_cg/refindex.py",
     "    _lib_rule = _lib_subtree_rule(ledger.root, root) if ledger is not None else None" + chr(10)
     + "    if _lib_rule:",
     "    _lib_rule = _lib_subtree_rule(ledger.root, root) if ledger is not None else None" + chr(10)
     + "    if _lib_rule and False:",
     ("C1", "C2", "C3", "C4")),
)


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
                                  or name in ("README.md", "pyproject.toml", "package.json")):
            shutil.copy2(p, os.path.join(dst, name))
    return dst


def _run_in(tree):
    import subprocess
    env = dict(os.environ)
    env["PYTHONPATH"] = tree
    env["PYTHONUTF8"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env.pop("MDCG_INGEST_ROOT", None)
    pr = subprocess.run([sys.executable, "-X", "utf8", "-m",
                         "md_cg.test_issue425_ingest_libroot_bypass"],
                        capture_output=True, text=True, encoding="utf-8",
                        errors="replace", cwd=tree, env=env, timeout=1200)
    out = (pr.stdout or "") + (pr.stderr or "")
    reds = [ln.split("FAIL ", 1)[1].strip()
            for ln in out.splitlines() if "FAIL " in ln]
    return pr.returncode, reds, out


def _mutate():
    print("!! 定点变异自证：把判据改回改动前形态，守卫必须转红")
    tree = _mirror_build()
    try:
        rc, reds, out = _run_in(tree)
        print("  未变异镜像基线：rc=%d 红项=%d（必须 rc=0 且 0 红）" % (rc, len(reds)))
        if rc != 0 or reds:
            print(chr(10).join(out.splitlines()[-25:]))
        ok, bad = 0, []
        for desc, rel, old, new, exp in _MUTATIONS:
            p = os.path.join(tree, rel)
            raw = open(p, "rb").read()
            # 锚点按 \n 构造，目标文件可能是 CRLF——按文件实际行尾折算后再比对。
            _nl = "\r\n" if b"\r\n" in raw[:8192] else "\n"
            t = raw.decode("utf-8")
            old = old.replace("\n", _nl)
            new = new.replace("\n", _nl)
            if t.count(old) != 1:
                bad.append("%s —— 锚点命中 %d 次" % (desc, t.count(old)))
                print("  ANCHOR-MISS " + desc)
                continue
            bak = t
            open(p, "w", encoding="utf-8", newline="").write(t.replace(old, new, 1))
            rc2, reds2, out2 = _run_in(tree)
            open(p, "w", encoding="utf-8", newline="").write(bak)
            hit = [r for r in reds2 if r.startswith(exp)]
            if rc2 != 0 and len(hit) == len(exp):
                ok += 1
                print("  OK   %s  红项=%d 指定命中=%d/%d"
                      % (desc, len(reds2), len(hit), len(exp)))
            else:
                bad.append(desc)
                print("  MISMATCH %s  红项=%d 指定命中=%d/%d rc=%d"
                      % (desc, len(reds2), len(hit), len(exp), rc2))
                for r in reds2[:8]:
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
    return 0 if not FAILS else 1


if __name__ == "__main__":
    sys.exit(main())
