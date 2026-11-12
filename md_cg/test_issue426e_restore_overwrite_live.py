# -*- coding: utf-8 -*-
# 功能名：restore(force=True) 不得静默覆写同 id 在位节点（issue #426-E）
# 生效条件：python -u -X utf8 -m md_cg.test_issue426e_restore_overwrite_live [--mutate]；被测面＝md_cg/mdcos.py 的 restore（闸 + protect.snapshot）+ MdCGSecure.restore 透传 + md_cg/mcp_server.py 两入口 + md_cg/op_table.py 的 _GENERIC_PARAMS 登记
# 子功能：A 组＝正向腿（在位节点 ⇒ live_node_exists 不覆写；显式 overwrite_live=True ⇒ 覆写且先在位版 snapshot）；K 组＝反向腿①（无在位节点时 force 恢复照常、墓碑语义逐位不变）；E 组＝源码面（三处登记的「三半」在位）；M 组＝反向腿②（--mutate，红项严格相等且不重叠）
# 执行：--mutate 时在镜像树里逐条撤闸／撤 snapshot，守卫必须按指定项转红
# 验证方式：全部 PASS 即通过（退出码 0）；--mutate 下每条变异的红项集合须与预期逐项相符，锚点未命中即 fail-closed
# 不适用条件：① 腿看不见「调用方**应该**不该恢复旧版」——只看见「覆写在位节点是否需显式确认」；② 不复用 force 属**设计裁定**（force＝忽略前置条件，不是「允许覆写同 id」；复用会让既有调用方的 force=True 静默改变行为），腿不判该裁定的对错；③ 不覆盖 `rollback._rollback_delete` 的既有漂移闸（#352-A，另一入口）；④ 不覆盖跨进程并发 restore 的竞态（本仓只有多进程共根，锁面属 U06）。
"""issue #426-E 守卫：restore 覆写同 id 在位节点需显式确认。

病象（修前）：`forget` 必写墓碑 ⇒ 恢复任何已删节点都要 `force=True`；而 `restore` 只判墓碑
与 trash，直接 `add(..., override=True)` 整份顶掉同 id 的在位节点，trash / `_protected_history`
/ 各 jsonl 都没有现行版，回执 `ok:true, forced:true` 且无任何提示。
修法：新增 `overwrite_live`（默认 False ⇒ 默认行为不变）：在位节点存在且未显式确认 ⇒
`live_node_exists` 拒绝（零副作用）；显式确认 ⇒ 先 `protect.snapshot` 留副本再覆写。
"""
from __future__ import annotations

import ast
import os
import shutil
import subprocess
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

_TMP = tempfile.mkdtemp(prefix="iss426e_")
os.environ.update({"MDCG_ROOT": _TMP + "/brain", "MDCG_STATE_ROOT": _TMP + "/state",
                   "MDCG_AUX_ROOT": _TMP + "/auxstore", "MDCG_DATA_ROOT": _TMP + "/datastore",
                   "MDCG_EXPORT_ROOT": _TMP, "MDCG_SUSTAIN": "0", "MDCG_SLEEP": "0",
                   "MDCG_AUTONOMY": "confirm"})
os.environ.pop("MDCG_READ_CACHE", None)

from md_cg import op_table as _ot                     # noqa: E402
from md_cg import tokens as _tk                       # noqa: E402
from md_cg.mdcos import MdCGSecure                    # noqa: E402
from md_cg.security import Principal                  # noqa: E402

PASSED, FAILS = [], []
V1 = "V1 住在杭州 旧版标记OLDQ7"
V3 = "V3 住在深圳 现行版标记NEWQ9"


def _check(name, cond, detail=""):
    if cond:
        print("  PASS " + name)
        PASSED.append(name)
    else:
        print("  FAIL " + name + "  " + str(detail)[:240])
        FAILS.append(name)


def _ccg(v):
    return ("# 功能名：用户画像" + chr(10) + "# 生效条件：任何会话" + chr(10)
            + "# 子功能：住址" + chr(10) + "# 执行：" + v + chr(10)
            + "# 验证方式：用户自述" + chr(10) + "# 不适用条件：无")


def _cg(root):
    sp = _tk.role_spec("designer")
    return MdCGSecure(root, principal=Principal(
        clearance="secret", can_write=sp["can_write"], can_admin=True, role="designer",
        layers_allow=sp["layers_allow"], ops_allow=sp["ops_allow"]), autoflush=1)


def _sweep(root, needle):
    hits = []
    for d, _dd, fs in os.walk(root):
        for f in fs:
            p = os.path.join(d, f)
            try:
                with open(p, "rb") as fh:
                    if needle.encode("utf-8") in fh.read():
                        hits.append(os.path.relpath(p, root))
            except OSError:
                continue
    return sorted(hits)


def _stage(root, nid, content):
    cg = _cg(root)
    cg.add(nid, _ccg(content), layer="contextual")
    cg.flush()
    return cg


def _prep(tmp, tag):
    """建「已删旧版 + 同 id 在位新版」的独立库；**每个面各自一库**（否则前一步消费掉 trash 源会让后一步走 not_in_trash，红项串味——实测 M1 曾因此多红 A3）。"""
    root = os.path.join(tmp, tag)
    cg = _stage(root, "user_profile", V1)
    cg.forget("user_profile", reason="搬家")
    cg.flush()
    cg.close()
    cg2 = _cg(root)
    cg2.add("user_profile", _ccg(V3), layer="contextual")      # 同 id 重建（在位版）
    cg2.flush()
    return root, cg2


def group_a(tmp):
    print("== A 组：正向腿——在位节点不得被静默覆写；显式确认需先留副本 ==")
    # 面 1：默认拒绝（独立库 a1）
    root1, cg1 = _prep(tmp, "a1")
    r = cg1.restore("user_profile", force=True)
    _check("A1 在位节点存在 ⇒ 默认拒绝（live_node_exists）",
           (r or {}).get("error") == "live_node_exists", "r=%r" % (r,))
    cur = (cg1.get("user_profile") or {}).get("content") or ""
    _check("A2 拒绝后现行版仍在（未被覆写）", V3 in cur and V1 not in cur, "content=%r" % cur[-40:])
    cg1.close()
    # 面 2：显式确认（独立库 a2）
    root2, cg2 = _prep(tmp, "a2")
    before = _sweep(root2, "现行版标记NEWQ9")
    r2 = cg2.restore("user_profile", force=True, overwrite_live=True)
    cur2 = (cg2.get("user_profile") or {}).get("content") or ""
    _check("A3 显式 overwrite_live=True ⇒ 覆写成功且恢复旧版",
           bool((r2 or {}).get("ok")) and V1 in cur2, "r=%r content=%r" % (r2, cur2[-40:]))
    after = _sweep(root2, "现行版标记NEWQ9")          # 覆写后现行版应另有副本
    _check("A4 覆写前已在位版本留副本（protect.snapshot）", bool(after),
           "before=%s after=%s" % (before, after))
    cg2.close()


def group_k(tmp):
    print("== K 组：反向腿①——零变更 / 既有错误语义不变 ==")
    root = os.path.join(tmp, "k")
    cg = _stage(root, "solo", V1)
    cg.forget("solo", reason="搬家")
    cg.flush()
    cg2 = _cg(root)
    r = cg2.restore("solo")
    _check("K1 未 force ⇒ 仍 tombstoned（既有语义不变）",
           (r or {}).get("error") == "tombstoned", "r=%r" % (r,))
    r2 = cg2.restore("solo", force=True)
    cur = (cg2.get("solo") or {}).get("content") or ""
    _check("K2 无在位节点 ⇒ force 恢复照常成功（零变更）",
           bool((r2 or {}).get("ok")) and V1 in cur, "r=%r" % (r2,))
    r3 = cg2.restore("solo", force=True)
    _check("K3 再次恢复（trash 源已消费）⇒ 仍走既有 not_in_trash",
           (r3 or {}).get("error") == "not_in_trash", "r=%r" % (r3,))
    cg.close()
    cg2.close()


def _src(rel):
    with open(os.path.join(_REPO, rel), encoding="utf-8") as f:
        return f.read()


def _fn(rel, cls, name):
    tree = ast.parse(_src(rel), rel)
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == cls:
            for sub in node.body:
                if isinstance(sub, ast.FunctionDef) and sub.name == name:
                    return sub
    return None


def group_e(tmp):
    print("== E 组：源码面——三处登记的「三半」在位 ==")
    sig = _fn("md_cg/mdcos.py", "MdCGOS", "restore")
    args = [a.arg for a in sig.args.args] if sig is not None else []
    _check("E1 base restore 形参含 overwrite_live（默认 False）",
           "overwrite_live" in args, "args=%s" % args)
    src_m = _src("md_cg/mdcos.py")
    _check("E2 在位节点闸在位（live_node_exists + not overwrite_live）",
           "live_node_exists" in src_m and "not overwrite_live" in src_m)
    _check("E3 覆写前 snapshot 在位（protect.snapshot）",
           "protect.snapshot(self, node_id)" in src_m)
    src_s = _src("md_cg/mcp_server.py")
    _check("E4 两个工具入口均转发 overwrite_live",
           src_s.count("overwrite_live=bool(a.get(\"overwrite_live\"))") == 2,
           "count=%d" % src_s.count("overwrite_live=bool(a.get(\"overwrite_live\"))"))
    _check("E5 schema 登记（cg 工具属性）",
           "overwrite_live=_p(" in src_s)
    _check("E6 通用参数表登记（_GENERIC_PARAMS）——三向对账的另一半",
           "overwrite_live" in _ot._GENERIC_PARAMS)


def _guard_group(tag, fn, tmp):
    try:
        fn(tmp)
    except Exception as exc:                              # noqa: BLE001
        import traceback
        _check("%s0 组内异常（fail-closed：异常即红）" % tag, False,
               "%s: %s" % (type(exc).__name__, exc))
        traceback.print_exc()


def main():
    print("== #426-E restore 覆写在位节点守卫 ==")
    _guard_group("A", group_a, _TMP)
    _guard_group("K", group_k, _TMP)
    _guard_group("E", group_e, _TMP)
    print("=" * 68)
    print("#426-E 守卫：%d 通过，%d 失败" % (len(PASSED), len(FAILS)))
    for f in FAILS:
        print("  红项：" + f)
    _bad = _mutate() if "--mutate" in sys.argv else 0
    return 1 if (FAILS or _bad) else 0


# ================================================= M 组：反向腿②（定点变异）
_MUTATIONS = (
    ("M1 撤在位节点闸（回到 #426-E 原形态：静默覆写）",
     "md_cg/mdcos.py",
     (("        if _live and not overwrite_live:" + chr(10)
       + "            return {\"ok\": False, \"error\": \"live_node_exists\", \"id\": node_id," + chr(10)
       + "                    \"hint\": \"同 id 已有在位节点；恢复会整份覆写它。确认后传 overwrite_live=true，或先 forget 在位版本。\"}",
       "        pass  # M1 撤在位节点闸"),),
     ("A1", "A2", "E2")),
    ("M2 撤 snapshot（覆写前不再为在位版本留副本）",
     "md_cg/mdcos.py",
     (("        if _live:" + chr(10)
       + "            protect.snapshot(self, node_id)      # 覆写前给在位版本留副本",
       "        pass  # M2 撤 snapshot"),),
     ("A4", "E3")),
)


def _mirror_build():
    dst = tempfile.mkdtemp(prefix="iss426e_mut_")
    for name in ("md_cg", "lib"):
        src = os.path.join(_REPO, name)
        if os.path.isdir(src):
            shutil.copytree(src, os.path.join(dst, name),
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for name in sorted(os.listdir(_REPO)):
        p = os.path.join(_REPO, name)
        if os.path.isfile(p) and name.endswith(".py"):
            shutil.copy2(p, os.path.join(dst, name))
    return dst


def _run_in(tree):
    env = dict(os.environ)
    env["PYTHONPATH"] = tree
    env["PYTHONUTF8"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    for k in ("MDCG_ROOT", "MDCG_STATE_ROOT", "MDCG_AUX_ROOT", "MDCG_DATA_ROOT",
              "MDCG_EXPORT_ROOT", "MDCG_INGEST_ROOT", "MDCG_TOKEN", "MDCG_TOKEN_FILE"):
        env.pop(k, None)
    pr = subprocess.run([sys.executable, "-u", "-X", "utf8", "-m",
                         "md_cg.test_issue426e_restore_overwrite_live"],
                        capture_output=True, text=True, encoding="utf-8",
                        errors="replace", cwd=tree, env=env, timeout=1800)
    out = (pr.stdout or "") + (pr.stderr or "")
    reds = [ln.split("FAIL ", 1)[1].strip()
            for ln in out.splitlines() if ln.strip().startswith("FAIL ")]
    return pr.returncode, reds, out


def _apply_text(text, rel, pairs):
    eol = (chr(13) + chr(10)) if (chr(13) + chr(10)) in text else chr(10)
    for old, new in pairs:
        o = old.replace(chr(10), eol)
        n = new.replace(chr(10), eol)
        if text.count(o) != 1:
            return None, "锚点在 %s 里命中 %d 次" % (rel, text.count(o))
        text = text.replace(o, n, 1)
    return text, ""


def _mutate():
    print("!! 反向腿②：撤闸／撤 snapshot，守卫必须按指定项转红")
    tree = _mirror_build()
    bad = []
    try:
        rc, reds, out = _run_in(tree)
        print("  未变异镜像基线：rc=%d 红项=%d（必须 rc=0 且 0 红）" % (rc, len(reds)))
        if rc != 0 or reds:
            bad.append("未变异镜像基线即红")
            print(chr(10).join(out.splitlines()[-20:]))
        for desc, rel, pairs, exp in _MUTATIONS:
            p = os.path.join(tree, rel)
            with open(p, encoding="utf-8", newline="") as f:
                bak = f.read()
            mut, why = _apply_text(bak, rel, pairs)
            if mut is None:
                bad.append("%s —— %s" % (desc, why))
                print("  ANCHOR-MISS " + desc + "  " + why)
                continue
            with open(p, "w", encoding="utf-8", newline="") as f:
                f.write(mut)
            for root, _dd, _ff in os.walk(tree):
                if os.path.basename(root) == "__pycache__":
                    shutil.rmtree(root, ignore_errors=True)
            rc2, reds2, out2 = _run_in(tree)
            with open(p, "w", encoding="utf-8", newline="") as f:
                f.write(bak)
            hit = sorted({r.split(" ")[0] for r in reds2})
            if rc2 != 0 and hit == sorted(exp):
                print("  OK   %s  红项=%d 指定命中=%s" % (desc, len(reds2), hit))
            else:
                bad.append(desc)
                print("  MISMATCH %s  实际红项=%s  期望=%s  rc=%d"
                      % (desc, hit, sorted(exp), rc2))
                for r in reds2[:10]:
                    print("        FAIL " + r)
        print("反向腿②：%s（%d 条不合格）" % ("PASS" if not bad else "FAIL", len(bad)))
        return len(bad)
    finally:
        shutil.rmtree(tree, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
