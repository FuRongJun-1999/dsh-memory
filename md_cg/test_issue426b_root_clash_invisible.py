# -*- coding: utf-8 -*-
# 功能名：root_clash 看不见调用者无权读的节点 ⇒ fail-closed 视为冲突（issue #426-B）
# 生效条件：python -X utf8 -m md_cg.test_issue426b_root_clash_invisible [--mutate]；
#           被测面＝md_cg/refindex.py::root_clash 的不可读 fallback 与 add_items 冲突跳过
# 子功能：A 组＝record(internal) 索引 B 不覆写 designer 的 restricted A 节点且回执可归因；
#         B 组＝可见节点异根冲突（既有）/同根重索引（不误判）对照；E 组＝源码钉子
# 执行：--mutate 时就地短路一条判据（撤 fallback 冲突 / 过度收紧同根 / 撤 invisible），
#       指定断言须恰好转红
# 不适用条件：不判 id 键含 root 的根治改造（issue #426-B 修复建议之外的独立立项）；
#             不判陈化豁免本身（旧根不在盘上时允许覆写，既有语义）
"""issue #426-B 守卫：#352-E 跨根冲突闸用受 clearance 过滤的 cg.get。

病象（修前）：record 令牌（internal）看不见 designer 以 restricted 索引的同 id 文档
节点 ⇒ root_clash 返回 None ⇒ 整条覆写（密级一起降 internal、原文零副本），回执
conflicts=null；之后原主重索引被闸挡回。

修复语义：冲突判定改走不过滤内部读面（索引条目 + 基类 _read）；「存在但不可读」
按 fail-closed 视为冲突，读数带 invisible=True 供回执归因。可见节点路径逐位不变。
"""
from __future__ import annotations

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

_AMARK = "AMARK 机密：生产库口令每月一号轮换。"
_BMARK = "BMARK 公开：另一个仓库的同名段落。"
_CHECKS = []
FAILS = []


def _check(name, cond, detail=""):
    if name not in _CHECKS:
        _CHECKS.append(name)
    if cond:
        print("  PASS " + name)
    else:
        print("  FAIL " + name + "  " + str(detail)[:220])
        FAILS.append(name)


class _Env:
    def __init__(self):
        self.dir = tempfile.mkdtemp(prefix="iss426b_")
        self.saved = {}
        self.own = None
        self.rec = None

    def __enter__(self):
        from md_cg import crypto
        env = {"MDCG_ROOT": self.dir + "/brain",
               "MDCG_STATE_ROOT": self.dir + "/state",
               "MDCG_AUX_ROOT": self.dir + "/auxstore",
               "MDCG_DATA_ROOT": self.dir + "/data",
               "MDCG_EXPORT_ROOT": self.dir,
               "MDCG_INGEST_ROOT": self.dir + "/src",
               "MDCG_TOKEN_FILE": self.dir + "/auxstore/tokens.json",
               "MDCG_SUSTAIN": "0", "MDCG_SLEEP": "0",
               crypto.MASTER_ENV: "ab" * 32}
        for k, v in env.items():
            self.saved[k] = os.environ.get(k)
            os.environ[k] = v
        from md_cg.mdcos import MdCGSecure
        from md_cg.security import Principal
        from md_cg.tokens import role_spec

        def P(role, clr):
            s = role_spec(role)
            return Principal(role=role, clearance=clr, can_write=s["can_write"],
                             can_admin=s["can_admin"],
                             layers_allow=s["layers_allow"],
                             ops_allow=s["ops_allow"])

        self.own = MdCGSecure(os.environ["MDCG_ROOT"],
                              principal=P("designer", "secret"), autoflush=1)
        self.rec = MdCGSecure(os.environ["MDCG_ROOT"],
                              principal=P("record", "internal"), autoflush=1)
        for d, m in (("A", _AMARK), ("B", _BMARK)):
            os.makedirs(self.dir + "/src/repo" + d, exist_ok=True)
            with io.open(self.dir + "/src/repo" + d + "/README.md", "w",
                         encoding="utf-8") as fh:
                fh.write("# 部署手册" + chr(10) + chr(10) + "## 生产库" + chr(10)
                         + chr(10) + m * 4 + chr(10))
        return self

    def __exit__(self, *exc):
        for cg in (self.own, self.rec):
            try:
                if cg is not None:
                    cg.close()
            except Exception:                           # noqa: BLE001
                pass
        for k, v in self.saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(self.dir, ignore_errors=True)
        return False

    def ing(self, cg, d, **kw):
        from md_cg import mcp_server as ms
        return ms._dispatch(cg, "cg", dict(op="ingest", action="dir",
                                           path=self.dir + "/src/repo" + d, **kw))

    def doc_chain(self, r):
        return ((r or {}).get("chains") or {}).get("doc") or {}

    def node_id(self):
        for n in list((self.own.index.get("nodes") or {})):   # H-4：先取快照再迭代（原裸迭代点，G1a 判据）
            if n.startswith("doc_"):
                return n
        return ""


def _assertions():
    print("== A 组：不可读既有节点的 fail-closed ==")
    with _Env() as e:
        e.ing(e.own, "A", sensitivity="restricted")
        nid = e.node_id()
        _check("A01 前提：designer 以 restricted 索引 A 成功",
               bool(nid) and ((e.own.get(nid) or {}).get("frontmatter") or {}).get("sensitivity") == "restricted",
               nid)
        r = e.ing(e.rec, "B")
        ch = e.doc_chain(r)
        _check("A02 ★行：record 索引 B 被冲突闸跳过（indexed=0、冲突>=1）",
               ch.get("indexed") == 0 and (ch.get("conflict_count") or 0) >= 1, ch)
        node = e.own.get(nid) or {}
        c = node.get("content") or ""
        _check("A03 ★行：A 节点原样保留（含 AMARK、仍 restricted）",
               "AMARK" in c and (node.get("frontmatter") or {}).get("sensitivity") == "restricted",
               ((node.get("frontmatter") or {}).get("sensitivity"), c[-60:]))
        cf = ch.get("conflicts") or []
        _check("A04 ★行：回执 conflicts 带 invisible 归因（调用者不可见）",
               any((x or {}).get("invisible") for x in cf), cf)
        r2 = e.ing(e.own, "A", incremental=False)
        ch2 = e.doc_chain(r2)
        _check("A05 原主可写回：designer 重索引 A indexed=1",
               ch2.get("indexed") == 1, ch2)

    print("== B 组：对照 ==")
    with _Env() as e:
        e.ing(e.own, "A")
        nid = e.node_id()
        r = e.ing(e.rec, "B")
        ch = e.doc_chain(r)
        c = ((e.own.get(nid) or {}).get("content")) or ""
        _check("B01 既有对照：可见节点异根仍跳过覆写（既有路径逐位不变）",
               ch.get("indexed") == 0 and (ch.get("conflict_count") or 0) >= 1
               and "AMARK" in c, ch)
    with _Env() as e:
        e.ing(e.own, "A", sensitivity="restricted")
        r = e.ing(e.own, "A", incremental=False)
        ch = e.doc_chain(r)
        _check("B02 同根重索引不误判（indexed=1、conflict_count=0）",
               ch.get("indexed") == 1 and (ch.get("conflict_count") or 0) == 0, ch)

    print("== E 组：钉子 ==")
    with io.open(os.path.join(_REPO, "md_cg/refindex.py"), encoding="utf-8") as fh:
        src = fh.read()
    _check("E01 ★钉子：不可读 fallback 走内部读面 cg._read(e)", "cg._read(e)" in src)
    _check("E02 ★钉子：fallback 返回 invisible 标记", '"invisible": True' in src)
    _check("E03 ★钉子：注释点名 issue #426-B", "issue #426-B" in src)


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


_RET_LIVE = ("        return {\"id\": nid, \"kind\": kind, \"existing_root\": _prev_root,"
             + chr(10) + "                \"root\": root, \"invisible\": True}" + chr(10))
_RET_CLASH = ("    if not prev_root or not root or _same_root(prev_root, root):"
              + chr(10) + "        return None" + chr(10))
_ARMS = {
    "M1": (
        "md_cg/refindex.py",
        _RET_LIVE,
        "        return None" + chr(10),
        {"A02", "A03", "A04", "A05", "E02"},
    ),
    "M2": (
        "md_cg/refindex.py",
        _RET_CLASH,
        "    if not prev_root or not root:" + chr(10) + "        return None" + chr(10),
        {"A05", "B02"},
    ),
    "M3": (
        "md_cg/refindex.py",
        "                \"root\": root, \"invisible\": True}" + chr(10),
        "                \"root\": root}" + chr(10),
        {"A04", "E02"},
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
            nl = chr(13) + chr(10) if (chr(13) + chr(10)) in text else chr(10)
            norm = text.replace(chr(13) + chr(10), chr(10))
            _cnt = norm.count(old)
            if _cnt != 1:
                print("[ANCHOR-MISS] %s：锚点命中 %d 次（期望 1）⇒ 无法变异，判据失效"
                      % (mid, _cnt))
                return 2
            with open(target, "wb") as fh:
                fh.write(norm.replace(old, new).replace(chr(10), nl).encode("utf-8"))
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
