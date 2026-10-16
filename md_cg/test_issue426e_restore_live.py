# -*- coding: utf-8 -*-
# 功能名：restore(force) 不覆写同 id 在位节点（issue #426-E）
# 生效条件：python -X utf8 -m md_cg.test_issue426e_restore_live [--mutate]；
#           被测面＝md_cg/mdcos.py::MdCGOS.restore / MdCGSecure.restore 与
#           md_cg/mcp_server.py 两个恢复入口（cg op=forget action=restore、mdcg_restore）
# 子功能：A 组＝在位拒绝 / 显式 overwrite_live 覆写 / 无在位 KE1 恢复 / 工具面双入口；
#         K 组＝非恒真对照（无 force 仍 tombstoned、非 admin 仍 AccessDenied）；E 组＝接线钉子
# 执行：--mutate 时就地短路一条判据（撤在位闸 / force 当确认 / 撤工具面透传 / 撤 schema 登记），
#       指定断言须恰好转红
# 不适用条件：不判 trash 损坏 / 路径穿越（既有 #172/#144 面）；不判回滚执行桥（#352-A 面）
"""issue #426-E 守卫：restore(force=True) 整份覆写同 id 在位节点、现行版零副本。

病象（修前）：forget 必写墓碑 ⇒ 恢复必须 force；restore 只判墓碑与 trash，
不判同 id 是否已有在位节点，也不给现行版留副本。稳定 id 删除后重建
（user_profile/task_*/sess_*）后再恢复旧版，现行正文被整份顶掉，trash/
_protected_history/jsonl 全无副本，回执 ok:true/forced:true 无提示。

修复语义：force 只越过墓碑；同 id 在位时 restore 默认 fail-closed（live_exists +
hint），必须显式 overwrite_live=True 才整份覆写——两个确认开关分离。
无在位节点时 force 恢复行为逐位不变（KE1）。
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

V1 = "V1 住在杭州"
V3 = "V3 住在深圳 现行"
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


def _cc(v):
    return ("# 功能名：用户画像\n# 生效条件：任何会话\n# 子功能：住址\n"
            "# 执行：%s\n# 验证方式：用户自述\n# 不适用条件：无" % v)


class _Env:
    def __init__(self):
        self.dir = tempfile.mkdtemp(prefix="iss426e_")
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

    def make_live_after_delete(self, nid="user_profile"):
        self.cg.add(nid, _cc(V1), layer="contextual")
        r = self.cg.forget(nid, reason="搬家")
        assert r.get("ok"), r
        self.cg.add(nid, _cc(V3), layer="contextual")

    def content(self, nid):
        return ((self.cg.get(nid) or {}).get("content")) or ""


def _dispatch(cg, op_args):
    from md_cg import mcp_server
    return mcp_server._dispatch(cg, "cg", op_args)


def _restore_tool(cg, args):
    from md_cg import mcp_server
    return mcp_server._dispatch(cg, "mdcg_restore", args)


def _call_restore(fn, *args, **kw):
    """带 overwrite_live 的调用兼容旧签名：缺失该形参（基线）时返回结构化失败，判据按红。"""
    try:
        return fn(*args, **kw)
    except TypeError as exc:
        return {"ok": False, "error": "no_overwrite_live", "detail": str(exc)[:120]}


def _assertions():
    print("== A 组：在位节点保护 ==")
    with _Env() as e:
        e.make_live_after_delete()
        _check("A01 前提：删除后重建同 id，现行版在位",
               V3 in e.content("user_profile"), e.content("user_profile")[-80:])
        r1 = e.cg.restore("user_profile", force=True)
        _check("A02 ★行：force 不带 overwrite_live ⇒ live_exists 拒绝",
               r1.get("ok") is False and r1.get("error") == "live_exists"
               and "overwrite_live" in (r1.get("hint") or ""), r1)
        _check("A03 ★行：拒绝后现行版原样保留（零覆写）",
               V3 in e.content("user_profile") and V1 not in e.content("user_profile"))
        r2 = _call_restore(e.cg.restore, "user_profile", force=True, overwrite_live=True)
        _check("A04 ★行：显式 overwrite_live=True ⇒ 允许整份覆写（旧版恢复）",
               r2.get("ok") is True and V1 in e.content("user_profile")
               and V3 not in e.content("user_profile"), (r2, e.content("user_profile")[-80:]))
    with _Env() as e:                                        # KE1：无在位节点
        e.cg.add("solo_node", _cc(V1), layer="contextual")
        assert e.cg.forget("solo_node", reason="KE1").get("ok")
        r3 = e.cg.restore("solo_node", force=True)
        _check("A05 对照 KE1：无在位节点时 force 恢复照常成功（行为不变）",
               r3.get("ok") is True and V1 in e.content("solo_node"), r3)
    with _Env() as e:                                        # 工具面双入口
        e.make_live_after_delete()
        r4 = _restore_tool(e.cg, {"node_id": "user_profile", "force": True})
        _check("A06 ★工具面 mdcg_restore：不带 overwrite_live ⇒ live_exists",
               r4.get("ok") is False and r4.get("error") == "live_exists", r4)
        r5 = _restore_tool(e.cg, {"node_id": "user_profile", "force": True,
                                  "overwrite_live": True})
        _check("A07 ★工具面 mdcg_restore：显式 overwrite_live ⇒ 恢复成功",
               r5.get("ok") is True and V1 in e.content("user_profile"), r5)
    with _Env() as e:
        e.make_live_after_delete("task_x")
        r6 = _dispatch(e.cg, {"op": "forget", "action": "restore",
                              "node_id": "task_x", "force": True})
        _check("A08 ★工具面 cg(op=forget,action=restore)：不带 overwrite_live ⇒ live_exists",
               r6.get("ok") is False and r6.get("error") == "live_exists", r6)
        r7 = _dispatch(e.cg, {"op": "forget", "action": "restore",
                              "node_id": "task_x", "force": True,
                              "overwrite_live": True})
        _check("A09 ★工具面 cg 入口：显式 overwrite_live ⇒ 恢复成功",
               r7.get("ok") is True and V1 in e.content("task_x"), r7)

    print("== K 组：非恒真对照 ==")
    with _Env() as e:
        e.cg.add("k_node", _cc(V1), layer="contextual")
        assert e.cg.forget("k_node", reason="k").get("ok")
        rk = e.cg.restore("k_node")                          # 不带 force：墓碑检查仍在
        _check("K01 无 force ⇒ 仍 tombstoned（墓碑检查未被绕过）",
               rk.get("ok") is False and rk.get("error") == "tombstoned", rk)
    with _Env() as e:
        e.cg.add("k2_node", _cc(V1), layer="contextual")
        assert e.cg.forget("k2_node", reason="k2").get("ok")
        from md_cg.mdcos import MdCGSecure
        from md_cg.security import Principal
        cg2 = MdCGSecure(os.environ["MDCG_ROOT"],
                         principal=Principal(clearance="secret", can_admin=False),
                         autoflush=0)
        try:
            try:
                cg2.restore("k2_node", force=True)
                denied = False
            except Exception:                               # noqa: BLE001
                denied = True
        finally:
            cg2.close()
        _check("K02 非 admin ⇒ 仍 AccessDenied（管理闸未被放宽）", denied)

    print("== E 组：接线钉子 ==")

    def _read(rel):
        try:
            with io.open(os.path.join(_REPO, rel), encoding="utf-8") as fh:
                return fh.read()
        except OSError:
            return ""

    md = _read("md_cg/mdcos.py")
    srv = _read("md_cg/mcp_server.py")
    opt = _read("md_cg/op_table.py")
    tree = ast.parse(md)
    fns = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    _restore_fn = fns.get("restore")
    _check("E01 ★钉子：MdCGOS.restore 签名含 overwrite_live",
           _restore_fn is not None
           and "overwrite_live" in [a.arg for a in _restore_fn.args.args])
    _check("E02 ★钉子：两个工具入口均透传 overwrite_live",
           srv.count("overwrite_live=bool(a.get(\"overwrite_live\"))") >= 2,
           srv.count("overwrite_live=bool(a.get(\"overwrite_live\"))"))
    _check("E03 ★钉子：mdcg_restore 与 cg schema 均登记 overwrite_live",
           srv.count("overwrite_live=_p(\"boolean\"") >= 2,
           srv.count("overwrite_live=_p(\"boolean\""))
    m = re.search(r'"forget":\s*\{(.*?)\n    \},', opt, re.S)
    oseg = m.group(1) if m else ""
    _check("E04 ★钉子：op_table forget 段 params 含 overwrite_live",
           '"overwrite_live",' in oseg, oseg[:120])


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
        "md_cg/mdcos.py",
        "        if (node_id in (self.index.get(\"nodes\") or {})) and not overwrite_live:\n",
        "        if False:\n",
        {"A02", "A03", "A04", "A06", "A07", "A08", "A09"},
    ),
    "M2": (
        "md_cg/mdcos.py",
        "        if (node_id in (self.index.get(\"nodes\") or {})) and not overwrite_live:\n",
        "        if (node_id in (self.index.get(\"nodes\") or {})) and not (overwrite_live or force):\n",
        {"A02", "A03", "A04", "A06", "A07", "A08", "A09"},
    ),
    "M3": (
        "md_cg/mcp_server.py",
        "            return cg.restore(a.get(\"node_id\", \"\"), force=bool(a.get(\"force\")),\n"
        "                              overwrite_live=bool(a.get(\"overwrite_live\")))\n",
        "            return cg.restore(a.get(\"node_id\", \"\"), force=bool(a.get(\"force\")))\n",
        {"A09", "E02"},
    ),
    "M4": (
        "md_cg/mcp_server.py",
        '                          overwrite_live=_p("boolean", "显式允许整份覆写同 id 在位节点（默认拒绝；现行版无副本）")),',
        '                          ),',
        {"E03"},
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
            _cnt = norm.count(old)
            if _cnt != 1:
                print("[ANCHOR-MISS] %s：锚点命中 %d 次（期望 1）⇒ 无法变异，判据失效"
                      % (mid, _cnt))
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
