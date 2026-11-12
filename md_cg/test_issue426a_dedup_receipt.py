# -*- coding: utf-8 -*-
# 功能名：gated 入队回执透出 dedup 归因（issue #426-A 建议 3）
# 生效条件：python -X utf8 -m md_cg.test_issue426a_dedup_receipt [--mutate]；
#           被测面＝autonomy_modes.apply_dedup 单点与五处 gated 入队回执接线
#           （forget/merge/write_gated/remember 直写/写链覆写）
# 子功能：A 组＝forget 同键两次：第二次回执带 dedup/dup_of/dup_status 与「并入已有单」说明；
#         B 组＝mdcg_remember 直写同键两次；E 组＝单点与五处接线钉子
# 执行：--mutate 时就地短路一条判据（撤判定 / 撤 forget 接线 / 撤直写接线 / 过度收紧），
#       指定断言须恰好转红
# 不适用条件：不改并单语义本身（#426-A 建议 1/2 需维护者拍板，本件只做建议 3）；
#             不含 goal_gen._enqueue（未传 info=True，边界外）
"""issue #426-A（建议 3）守卫：gated 面入队回执只回 pid，不透出 dedup 归因。

病象（修前）：propose(info=True) 命中同键去重时返回 dedup/dup_of/dup_status，
但 gated 面（forget/merge/write_gated/remember 直写/写链覆写）只取 pr["pid"]，
agent 收到「已入审核队列」却不知道本次其实并入了一张既有单（可能是已裁决旧单）。

修复语义：新增单点 autonomy_modes.apply_dedup(out, pr)，命中 dedup 时只增
三键并在 hint 尾部追加「同键提案已存在…本次并入已有单、未新入队」；五处接线；
不改并单语义、不改 pid 与 hint 前段。
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

_CHECKS = []
FAILS = []
_CC = ("# 功能名：部署" + chr(10) + "# 生效条件：部署相关" + chr(10)
       + "# 子功能：端口" + chr(10) + "# 执行：%s" + chr(10)
       + "# 验证方式：用户自述" + chr(10) + "# 不适用条件：无关话题")


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
        self.dir = tempfile.mkdtemp(prefix="iss426a_")
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
        env.pop("MDCG_AUTONOMY", None)
        self.saved["MDCG_AUTONOMY"] = os.environ.pop("MDCG_AUTONOMY", None)
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


def _dispatch(cg, name, args):
    from md_cg import mcp_server
    return mcp_server._dispatch(cg, name, dict(args))


def _assertions():
    print("== A 组：forget 同键两次 ==")
    with _Env() as e:
        e.cg.add("n_forget", _CC % "端口 7001", layer="contextual")
        r1 = e.cg.forget_gated("n_forget", reason="测试 426-A")
        r2 = e.cg.forget_gated("n_forget", reason="测试 426-A")
        _check("A01 前提：两次 forget 均出单（CONFIRM 档）",
               bool(r1.get("pid")) and bool(r2.get("pid")), (r1, r2))
        _check("A02 ★行：第二次回执带 dedup/dup_of/dup_status",
               r2.get("dedup") is True and r2.get("dup_of") == r1.get("pid")
               and r2.get("dup_status") == "pending", r2)
        _check("A03 ★行：hint 明说「并入已有单、未新入队」",
               "并入已有单" in (r2.get("hint") or ""), r2.get("hint"))
        _check("A04 对照：第一次回执不带 dedup 归因",
               r1.get("dedup") is not True
               and "并入已有单" not in (r1.get("hint") or ""), r1)

    print("== B 组：mdcg_remember 直写同键两次 ==")
    with _Env() as e:
        e.cg.add("n_direct", _CC % "端口 7101", layer="contextual")
        b1 = _dispatch(e.cg, "mdcg_remember",
                       {"node_id": "n_direct", "content": _CC % "端口 7102",
                        "layer": "contextual"})
        b2 = _dispatch(e.cg, "mdcg_remember",
                       {"node_id": "n_direct", "content": _CC % "端口 7102",
                        "layer": "contextual"})
        _check("B01 ★行：直写第二次回执带 dedup 归因",
               b2.get("dedup") is True and b2.get("dup_of") == b1.get("pid")
               and "并入已有单" in (b2.get("hint") or ""), (b1, b2))
        _check("B02 对照：直写第一次不带 dedup 归因",
               b1.get("dedup") is not True, b1)

    print("== E 组：单点与五处接线钉子 ==")

    def _read(rel):
        try:
            with io.open(os.path.join(_REPO, rel), encoding="utf-8") as fh:
                return fh.read()
        except OSError:
            return ""

    am = _read("md_cg/autonomy_modes.py")
    md = _read("md_cg/mdcos.py")
    wp = _read("md_cg/writepipe.py")
    ms = _read("md_cg/mcp_server.py")
    _check("E01 ★钉子：单点 apply_dedup 含 dedup 判定与说明文案",
           "def apply_dedup(" in am and 'pr.get("dedup")' in am
           and "并入已有单" in am)
    _check("E02 ★钉子：五处 gated 回执均接线 apply_dedup",
           md.count("apply_dedup(") >= 3 and wp.count("apply_dedup(") >= 1
           and ms.count("apply_dedup(") >= 1,
           (md.count("apply_dedup("), wp.count("apply_dedup("),
            ms.count("apply_dedup(")))


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


_COND = '    if isinstance(pr, dict) and pr.get("dedup"):' + chr(10)
_ARMS = {
    "M1": ("md_cg/autonomy_modes.py", _COND, "    if False:" + chr(10),
           {"A02", "A03", "B01"}),
    "M2": ("md_cg/mdcos.py",
           "        return autonomy_modes.apply_dedup(" + chr(10),
           "        return (lambda _x, _p: _x)(" + chr(10),
           {"A02", "A03", "E02"}),
    "M3": ("md_cg/mcp_server.py",
           "            return _am.apply_dedup(" + chr(10),
           "            return (lambda _x, _p: _x)(" + chr(10),
           {"B01", "E02"}),
    "M4": ("md_cg/autonomy_modes.py", _COND,
           "    if isinstance(pr, dict):" + chr(10),
           {"A04", "B02"}),
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
