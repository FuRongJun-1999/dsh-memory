# -*- coding: utf-8 -*-
# 功能名：ingest 源路径的「库内排除」闸（issue #425）——库根/trash/库内节点不是外部文档源
# 生效条件：python -X utf8 -m md_cg.test_issue425_ingest_libroot_exclusion [--mutate]；
#           被测面＝md_cg/security.py::check_ingest_source 与 md_cg/mcp_server.py::_ingest_call 接线
# 子功能：U 组＝判据单元（库内/祖先/兄弟/前缀相似）；B 组＝行为复现（C5 显式库根、C6 trash、C7 env 上级）
#         E 组＝接线钉子（白名单在先、库内排除在后、恰一次）；K 组＝正常外部源与 #351 行为不变
# 执行：--mutate 时就地短路一条判据（撤接线 / 判据短路 / 恒拒 / 只判 in_lib），指定断言须**恰好**转红
# 不适用条件：不判 mdcg_ingest 细粒度工具（会话 JSONL 源，另案）；不判 index_code/index_doc 面；不判符号链接平台差异
"""issue #425 守卫：#351 修复未闭环——库内路径仍可当外部文档摄取。

病象（修前）：#351 只堵了 dir 空 path 回落库根。显式 path=<库根>、action=file 指向
trash/<id>.md、或 MDCG_INGEST_ROOT 设为库根上级时，check_path_root 的「在根内」
判据全部放行（白名单缺省回落库根 / 上级根覆盖库根），库内 restricted 正文与
trash 中已删除节点被重新切成 internal doc_* 节点，无令牌访客可检索。

修复语义：新增单点 security.check_ingest_source(path, lib_root)——源在库内、或库根在
源路径子树内（源是库的祖先，扫描会递归进入库内）⇒ fail-closed 拒；_ingest_call 在
既有 check_path_root 之后接线。正常外部源与 #351 的空 path 行为不变。
"""
from __future__ import annotations

import ast
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SELF = os.path.abspath(__file__)
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

REST = "# 功能名：机房门禁" + chr(10) + "## 细节" + chr(10) + "门禁码 RESTMARK4321 " + "补充正文。" * 120
DEL = "# 功能名：废旧模块" + chr(10) + "## 细节" + chr(10) + "删除标记 DELMARK9988 " + "历史正文。" * 120
OUTSIDE = "# 外部文档" + chr(10) + "## 细节" + chr(10) + "外部标记 OUTSIDE425 " + "外部正文。" * 120
_CHECKS = []
FAILS = []


def _check(name, cond, detail=""):
    if name not in _CHECKS:
        _CHECKS.append(name)
    if cond:
        print("  PASS " + name)
    else:
        print("  FAIL " + name + "  " + str(detail)[:200])
        FAILS.append(name)


def _refuses(fn):
    try:
        fn()
        return None
    except PermissionError as e:
        return e
    except Exception as e:                              # noqa: BLE001
        return "OTHER:" + type(e).__name__


class _Env:
    """隔离库根 + 可控 MDCG_INGEST_ROOT。"""

    def __init__(self, clearance="secret"):
        self.dir = tempfile.mkdtemp(prefix="iss425_")
        self.saved = {}

    def __enter__(self):
        from md_cg import crypto
        env = {"MDCG_ROOT": self.dir + "/brain",
               "MDCG_STATE_ROOT": self.dir + "/state",
               "MDCG_AUX_ROOT": self.dir + "/auxstore",
               "MDCG_DATA_ROOT": self.dir + "/data",
               "MDCG_EXPORT_ROOT": self.dir,
               "MDCG_TOKEN_FILE": self.dir + "/auxstore/tokens.json",
               "MDCG_SUSTAIN": "0", "MDCG_SLEEP": "0",
               crypto.MASTER_ENV: "ab" * 32}
        for k, v in env.items():
            self.saved[k] = os.environ.get(k)
            os.environ[k] = v
        self.saved["MDCG_INGEST_ROOT"] = os.environ.get("MDCG_INGEST_ROOT")
        os.environ.pop("MDCG_INGEST_ROOT", None)
        from md_cg.mdcos import MdCGSecure
        from md_cg.security import Principal
        self.cg = MdCGSecure(os.environ["MDCG_ROOT"],
                             principal=Principal(clearance="secret",
                                                 can_admin=True), autoflush=1)
        return self

    def __exit__(self, *exc):
        try:
            self.cg.close()
        except Exception:                               # noqa: BLE001
            pass
        for k, v in self.saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(self.dir, ignore_errors=True)
        return False

    def ingest(self, args):
        from md_cg import mcp_server
        return mcp_server._ingest_call(self.cg, args)

    def doc_ids(self, mark):
        from md_cg import mcp_server
        try:
            out = mcp_server._dispatch(self.cg, "mdcg_search", {"query": mark})
        except Exception:                               # noqa: BLE001
            return []
        res = out.get("results") if isinstance(out, dict) else out
        ids = []
        for r in (res or []):
            nid = (r.get("node") or {}).get("id") or ""
            if nid.startswith("doc_"):
                ids.append(nid)
        return ids


def _assertions():
    from md_cg import security
    print("== U 组：check_ingest_source 判据单元 ==")
    base = tempfile.mkdtemp(prefix="iss425_u_")
    try:
        lib = os.path.join(base, "brain")
        inside = os.path.join(lib, "knowledge", "a.md")
        trash = os.path.join(lib, "trash", "x.md")
        outside = os.path.join(base, "outside", "b.md")
        sibling = os.path.join(base, "brain2")
        evil_prefix = lib + "_evil"
        for d in (os.path.dirname(inside), os.path.dirname(trash),
                  os.path.dirname(outside), sibling, evil_prefix):
            os.makedirs(d, exist_ok=True)
        for f in (inside, trash, outside):
            with io.open(f, "w", encoding="utf-8") as fh:
                fh.write("x")
        def _cig(path, lib_root):
            """调库内排除判据；函数不存在（基线/误删）时返回 MISSING，判据按红。"""
            fn = getattr(security, "check_ingest_source", None)
            if fn is None:
                return "MISSING"
            return _refuses(lambda: fn(path, lib_root))

        _check("U01 库根本身 ⇒ 拒", isinstance(_cig(lib, lib), PermissionError))
        _check("U02 库内层目录文件 ⇒ 拒", isinstance(_cig(inside, lib), PermissionError))
        _check("U03 trash/<id>.md ⇒ 拒", isinstance(_cig(trash, lib), PermissionError))
        _check("U04 库外文件 ⇒ 放行", _cig(outside, lib) is None)
        _check("U05 None/空串 ⇒ 放行（无源路径不判）",
               _cig(None, lib) is None and _cig("", lib) is None)
        _check("U06 前缀相似库（brain_evil）⇒ 放行（不相交不误伤）",
               _cig(evil_prefix, lib) is None)
        _check("U07 库的祖先目录 ⇒ 拒（扫描会递归进入库内）",
               isinstance(_cig(base, lib), PermissionError))
        _check("U08 库的兄弟目录 ⇒ 放行", _cig(sibling, lib) is None)
    finally:
        shutil.rmtree(base, ignore_errors=True)

    print("== B 组：行为复现（C5 显式库根 / C6 trash / C7 env 上级） ==")
    with _Env() as e:
        _check("B01 前提：restricted 节点写入成功",
               e.cg.add("rest_node", REST, layer="knowledge",
                        sensitivity="restricted") is not None)
        _check("B02 前提：internal 节点写入并 forget 进 trash",
               e.cg.add("del_node", DEL, layer="knowledge",
                        sensitivity="internal") is not None
               and bool((e.cg.forget("del_node", reason="issue425 守卫") or {}).get("ok")))
        trash = os.path.join(e.cg.root, "trash", "del_node.md")
        err1 = _refuses(lambda: e.ingest({"action": "dir", "path": e.cg.root}))
        _check("B03 ★C5：显式 path=<库根> 被库内排除闸拒",
               isinstance(err1, PermissionError) and "记忆库" in str(err1), err1)
        _check("B04 ★C5：拒绝后检索面无 internal doc_* 泄漏",
               e.doc_ids("RESTMARK4321") == [], e.doc_ids("RESTMARK4321"))
        _check("B05 前提：trash 文件在位", os.path.exists(trash), trash)
        err2 = _refuses(lambda: e.ingest({"action": "file", "path": trash}))
        _check("B06 ★C6：action=file 指向 trash/<id>.md 被拒",
               isinstance(err2, PermissionError) and "记忆库" in str(err2), err2)
        _check("B07 ★C6：已删节点未复活（get=not_found、检索面无 DELMARK doc_*）",
               e.cg.get("del_node") is None and e.doc_ids("DELMARK9988") == [],
               e.doc_ids("DELMARK9988"))
        os.environ["MDCG_INGEST_ROOT"] = os.path.dirname(e.cg.root.rstrip(os.sep))
        err3 = _refuses(lambda: e.ingest({"action": "dir"}))
        _check("B08 ★C7：env=库根上级 + 空 path 被拒（不再递归扫进库内）",
               isinstance(err3, PermissionError) and "记忆库" in str(err3), err3)
        _check("B09 ★C7：拒绝后检索面无 internal doc_* 泄漏",
               e.doc_ids("RESTMARK4321") == [], e.doc_ids("RESTMARK4321"))
        _check("B10 K：库内 restricted 节点本身未被改写、仍 restricted",
               ((e.cg.get("rest_node") or {}).get("frontmatter") or {}).get("sensitivity")
               == "restricted")
    with _Env() as e:
        outdir = os.path.join(e.dir, "outside_docs")
        os.makedirs(outdir, exist_ok=True)
        with io.open(os.path.join(outdir, "info.md"), "w", encoding="utf-8") as fh:
            fh.write(OUTSIDE)
        os.environ["MDCG_INGEST_ROOT"] = outdir
        try:
            ok_out = e.ingest({"action": "dir"})
        except Exception as exc:                        # noqa: BLE001
            ok_out = exc
        _check("B11 K：库外正常源（env=库外目录）照常摄取成功",
               isinstance(ok_out, dict) and ok_out.get("ok") is True
               and bool(e.doc_ids("OUTSIDE425")), repr(ok_out)[:160])
        os.environ.pop("MDCG_INGEST_ROOT", None)
        try:
            empty_out = e.ingest({"action": "dir"})
        except Exception as exc:                        # noqa: BLE001
            empty_out = exc
        _check("B12 K：#351 空 path 未设 env ⇒ 结构化 ok=False（行为不变）",
               isinstance(empty_out, dict) and empty_out.get("ok") is False,
               repr(empty_out)[:160])
        os.environ["MDCG_INGEST_ROOT"] = outdir
        err_wl = _refuses(lambda: e.ingest({"action": "dir", "path": e.cg.root}))
        _check("B13 K：白名单越界仍由 check_path_root 先拒（报白名单）",
               isinstance(err_wl, PermissionError) and "白名单" in str(err_wl), err_wl)

    print("== E 组：接线钉子 ==")
    with io.open(os.path.join(_REPO, "md_cg/mcp_server.py"), encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    fn = None
    for n in ast.walk(tree):
        if isinstance(n, ast.FunctionDef) and n.name == "_ingest_call":
            fn = n
    calls = {}
    for c in (ast.walk(fn) if fn else []):
        if isinstance(c, ast.Call) and isinstance(c.func, ast.Name) \
                and c.func.id in ("check_path_root", "check_ingest_source"):
            calls.setdefault(c.func.id, []).append(c.lineno)
    _check("E01 ★钉子：_ingest_call 恰调用一次 check_ingest_source",
           len(calls.get("check_ingest_source", [])) == 1,
           calls)
    _check("E02 ★钉子：白名单闸在前、库内排除闸在后",
           bool(calls.get("check_path_root")) and bool(calls.get("check_ingest_source"))
           and min(calls["check_path_root"]) < min(calls["check_ingest_source"]),
           calls)
    with io.open(os.path.join(_REPO, "md_cg/security.py"), encoding="utf-8") as fh:
        sec_src = fh.read()
    _check("E03 ★钉子：判据含相交两向（in_lib / covers_lib）",
           "in_lib = " in sec_src and "covers_lib = " in sec_src
           and "in_lib or covers_lib" in sec_src, "")


def _run_assertions():
    global FAILS
    FAILS = []
    del _CHECKS[:]
    _assertions()
    print("通过 %d / 失败 %d" % (len(_CHECKS) - len(FAILS), len(FAILS)))
    return len(FAILS)


def _subprocess_fail_names():
    r = subprocess.run([sys.executable, "-X", "utf8", _SELF, "--assert-only"],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", cwd=_REPO, timeout=600)
    names = set(re.findall(r"(?m)^\s*FAIL\s+([A-Z]\d+)", r.stdout or ""))
    return names, (r.stdout or "") + (r.stderr or "")


_ARMS = {
    "M1": (
        "md_cg/mcp_server.py",
        '    check_ingest_source(_p351, getattr(cg, "root", None), "ingest")\n',
        "    pass  # mutation M1：撤接线\n",
        {"E01", "E02", "B03", "B04", "B06", "B07", "B08", "B09"},
    ),
    "M2": (
        "md_cg/security.py",
        "    if in_lib or covers_lib:\n",
        "    if False:  # mutation M2：判据短路\n",
        {"U01", "U02", "U03", "U07", "B03", "B04", "B06", "B07", "B08", "B09", "E03"},
    ),
    "M3": (
        "md_cg/security.py",
        "    if in_lib or covers_lib:\n",
        "    if True:  # mutation M3：恒拒（过度收紧）\n",
        {"U04", "U06", "U08", "B11", "E03"},
    ),
    "M4": (
        "md_cg/security.py",
        "    if in_lib or covers_lib:\n",
        "    if in_lib:  # mutation M4：丢 covers_lib 方向\n",
        {"U07", "B08", "B09", "E03"},
    ),
}


def _mutate(argv):
    want = ""
    for a in argv:
        if a == "--mutate":
            want = want or "ALL"
        elif a.startswith("--mutate="):
            want = a.split("=", 1)[1]
    if not want:
        return 0
    ids = sorted(_ARMS) if want == "ALL" else [want]
    red = 0
    for mid in ids:
        if mid not in _ARMS:
            print("[ANCHOR-MISS] %s：未登记该变异臂" % mid)
            return 2
        rel, old, new, expect = _ARMS[mid]
        target = os.path.join(_REPO, *rel.split("/"))
        with open(target, "rb") as fh:
            orig = fh.read()
        try:
            text = orig.decode("utf-8")
            nl = "\r\n" if "\r\n" in text else "\n"
            norm = text.replace("\r\n", "\n")
            if norm.count(old) != 1:
                print("[ANCHOR-MISS] %s：锚点命中 %d 次（期望 1）⇒ 无法变异，判据失效"
                      % (mid, norm.count(old)))
                return 2
            with open(target, "wb") as fh:
                fh.write(norm.replace(old, new).replace("\n", nl).encode("utf-8"))
            actual, out = _subprocess_fail_names()
            if actual == expect:
                print("[MUTATE-OK]   %s：指定断言转红 %s" % (mid, sorted(actual)))
            else:
                print("[MUTATE-FAIL] %s：期望红 %s，实际红 %s"
                      % (mid, sorted(expect), sorted(actual)))
                for line in out.splitlines():
                    if line.strip().startswith("FAIL"):
                        print("    " + line)
                red += 1
        finally:
            with open(target, "wb") as fh:
                fh.write(orig)
    print("反证结果：%d 条变异，%s" % (len(ids), "全部恰好命中" if red == 0 else "%d 条未命中" % red))
    return 1 if red else 0


if __name__ == "__main__":
    _f = _run_assertions()
    if "--assert-only" in sys.argv:
        sys.exit(1 if _f else 0)
    _m = _mutate(sys.argv[1:])
    sys.exit(1 if (_f or _m) else 0)
