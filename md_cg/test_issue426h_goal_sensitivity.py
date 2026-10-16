# -*- coding: utf-8 -*-
# 功能名：goal op 分派层 sensitivity 透传（issue #426-H）
# 生效条件：python -X utf8 -m md_cg.test_issue426h_goal_sensitivity [--mutate]；
#           被测面＝md_cg/mcp_server.py 的 cg op=goal add 分支、cg 工具 schema、md_cg/op_table.py goal params
# 子功能：A 组＝工具面 private goal 落盘且访客读不到；K 组＝非恒真对照（缺省 internal、库层直调通路、非法密级 fail-closed）；
#         E 组＝源码/AST 钉子
# 执行：--mutate 时就地短路一条判据（撤工具面透传 / 缺省强推 private / 撤 schema 描述 / 撤 op_table 登记），
#       指定断言须恰好转红
# 不适用条件：不判 goal 的其它 action（list/status/generate）密级面；不判 #439 三入口继承（PR #461 另一面）
"""issue #426-H 守卫：goal op 的 sensitivity 被分派层丢弃。

病象（修前）：库层 MdCGSecure.add_goal 已支持 sensitivity（#439/#461 所修），但
cg(op=goal, action=add) 分派层不转发该参数 ⇒ designer 声明 private 的目标静默落
internal、回执 ok:true 不提示，无令牌访客经 mdcg_get 读到目标正文。

修复语义：add 分支透传 sensitivity=a.get("sensitivity")；cg 工具 schema 的
sensitivity 字段描述补 goal 语义；op_table goal params 登记 sensitivity。
缺省不声明仍落 internal（既有语义逐位不变）；非法密级由库层 _rank fail-closed。
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

SECRET_TEXT = "GOAL-SECRET-426H：私密目标正文"
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


class _Env:
    def __init__(self):
        self.dir = tempfile.mkdtemp(prefix="iss426h_")
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

    def guest_read(self, gid):
        from md_cg.mdcos import MdCGSecure
        from md_cg.security import Principal
        cg2 = MdCGSecure(os.environ["MDCG_ROOT"],
                         principal=Principal(clearance="internal"), autoflush=0)
        try:
            return ((cg2.get(gid) or {}).get("content")) or ""
        finally:
            cg2.close()

    def fm(self, gid):
        return ((self.cg.get(gid) or {}).get("frontmatter") or {})


def _dispatch(cg, args):
    from md_cg import mcp_server
    return mcp_server._dispatch(cg, "cg", dict(args, op="goal"))


def _assertions():
    print("== A 组：工具面 goal add 的 sensitivity 透传 ==")
    with _Env() as e:
        r0 = _dispatch(e.cg, {"action": "add", "goal": "基线目标-缺省密级"})
        _check("A01 前提：缺省不声明 ⇒ internal（既有语义）",
               bool(r0.get("id")) and e.fm(r0["id"]).get("sensitivity") == "internal",
               e.fm((r0 or {}).get("id") or "").get("sensitivity"))
        r1 = _dispatch(e.cg, {"action": "add", "goal": SECRET_TEXT,
                              "sensitivity": "private"})
        gid = r1.get("id") or ""
        _check("A02 ★行：工具面 sensitivity=private ⇒ 落盘 private",
               bool(gid) and e.fm(gid).get("sensitivity") == "private",
               e.fm(gid).get("sensitivity"))
        _check("A03 ★行：internal 档访客读不到 private 目标正文",
               SECRET_TEXT not in e.guest_read(gid), e.guest_read(gid)[:80])
        _check("A04 designer 自己仍能读回（private 对属主可见）",
               SECRET_TEXT in (((e.cg.get(gid) or {}).get("content")) or ""))

    print("== K 组：非恒真对照 ==")
    with _Env() as e:
        gid2 = e.cg.add_goal("库层直调目标", sensitivity="private")
        _check("K01 库层直调 cg.add_goal(sensitivity=private) 仍 private（非恒降级）",
               e.fm(gid2).get("sensitivity") == "private", e.fm(gid2).get("sensitivity"))
        try:
            e.cg.add_goal("非法密级目标", sensitivity="topsecret-426h")
            bad = False
        except Exception:                               # noqa: BLE001
            bad = True
        _check("K02 非法密级 fail-closed（不静默降级落盘）", bad)

    print("== E 组：源码钉子 ==")

    def _read(rel):
        try:
            with io.open(os.path.join(_REPO, rel), encoding="utf-8") as fh:
                return fh.read()
        except OSError:
            return ""

    srv = _read("md_cg/mcp_server.py")
    opt = _read("md_cg/op_table.py")
    gi = srv.find("gid = cg.add_goal(")
    gseg = srv[gi:gi + 700] if gi >= 0 else ""
    _check("E01 ★钉子：goal add 分支透传 sensitivity=a.get(...)",
           'sensitivity=a.get("sensitivity"),' in gseg, gseg[:160])
    _check("E02 ★钉子：cg schema 的 sensitivity 描述含 goal op=add 语义",
           "goal op=add 透传 cg.add_goal" in srv)
    m = re.search(r'"goal":\s*\{(.*?)\n    \},', opt, re.S)
    oseg = m.group(1) if m else ""
    _check("E03 ★钉子：op_table goal params 含 sensitivity",
           '"sensitivity",' in oseg, oseg[:160])


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
        '                              # issue #426-H：分派层透传 sensitivity（此前被丢 ⇒\n'
        '                              # private 目标静默落 internal，访客可读）。\n'
        '                              sensitivity=a.get("sensitivity"),\n',
        "",
        {"A02", "A03", "E01"},
    ),
    "M2": (
        "md_cg/mcp_server.py",
        '                              sensitivity=a.get("sensitivity"),\n'
        '                              priority=float(a.get("priority", 0.5)),',
        '                              sensitivity=a.get("sensitivity") or "private",\n'
        '                              priority=float(a.get("priority", 0.5)),',
        {"A01", "E01"},
    ),
    "M3": (
        "md_cg/mcp_server.py",
        '保守降为 private）；goal op=add 透传 cg.add_goal（缺省 internal，'
        '"\n                                     "private/secret 仅 designer）"),',
        '保守降为 private）"),',
        {"E02"},
    ),
    "M4": (
        "md_cg/op_table.py",
        '            "sensitivity",\n            "deadline",',
        '            "deadline",',
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
