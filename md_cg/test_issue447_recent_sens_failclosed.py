# -*- coding: utf-8 -*-
# 功能名：recent_events 缺 sensitivity 键 fail-closed（issue #447）
# 生效条件：python -X utf8 -m md_cg.test_issue447_recent_sens_failclosed [--mutate]；
#           被测面＝md_cg/mdcos.py::_recent_effective_sens 与 MdCGSecure.recent_events 的密级/会话判定
# 子功能：A 组＝internal 读方对缺键/显式 public/显式 restricted 的三态 + designer 可读；
#         K 组＝新写入路径恒写 sensitivity 键（逐位不变）；E 组＝单点与接线钉子
# 执行：--mutate 时就地短路一条判据（回 internal 兜底 / 过度收紧 / 撤 admin 豁免），
#       指定断言须恰好转红
# 不适用条件：不判真实升级前旧库端到端（本件以注入缺键记录模拟旧数据形态）；
#             不判 consistency_history 面（#298 已修）
"""issue #447 守卫：缺 sensitivity 键的近期事件记录 fail-open 降 internal。

病象（修前）：recent_events 对缺键记录取 DEFAULT_SENSITIVITY（internal）⇒
① internal 读方通过密级过滤；② _rank(internal) < private ⇒ 会话绑定检查整段跳过
⇒ 明文原样返回。同库 consistency_history 对同类信号（旧记录密级不可判）走
fail-closed 去原文——同信号两读面相反处置。

修复语义：新增单点 _recent_effective_sens(m)：缺键按最保守档 secret 兜底，
密级过滤与会话绑定判定都用它（designer/admin 仍可读、非 admin 按 secret 判）。
Secure 写入面恒写 sensitivity 键，正常新数据逐位不变。
"""
from __future__ import annotations

import ast
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SELF = os.path.abspath(__file__)
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

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
        self.dir = tempfile.mkdtemp(prefix="iss447_")
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

    def inject(self, recs):
        with io.open(self.cg.recent_log, "a", encoding="utf-8") as fh:
            for r in recs:
                fh.write(json.dumps(r, ensure_ascii=False) + chr(10))

    def reader(self, clearance="internal", can_admin=False):
        from md_cg.mdcos import MdCGSecure
        from md_cg.security import Principal
        return MdCGSecure(os.environ["MDCG_ROOT"],
                          principal=Principal(clearance=clearance,
                                              can_admin=can_admin), autoflush=0)

    def texts(self, cg2):
        try:
            return [r.get("text") or "" for r in cg2.recent_events(limit=0)]
        finally:
            cg2.close()


def _recs():
    base = {"role": "user", "tags": []}
    return [
        dict(base, t=time.time(), text="MISSING-447 缺键旧记录明文",
             meta={"session": "s_other"}),
        dict(base, t=time.time() + 0.01, text="PUBLIC-447 显式公开",
             meta={"sensitivity": "public"}),
        dict(base, t=time.time() + 0.02, text="RESTRICTED-447 显式受限",
             meta={"sensitivity": "restricted"}),
    ]


def _assertions():
    print("== A 组：缺键 fail-closed 与对照 ==")
    with _Env() as e:
        e.inject(_recs())
        internal_text = chr(10).join(e.texts(e.reader("internal")))
        _check("A01 ★行：internal 读方看不到缺键记录的明文（fail-closed）",
               "MISSING-447" not in internal_text, internal_text[:160])
        _check("A02 对照：显式 public 记录对 internal 读方仍可见（未过度收紧）",
               "PUBLIC-447" in internal_text, internal_text[:160])
        _check("A03 对照：显式 restricted 记录对 internal 读方不可见（既有隔离）",
               "RESTRICTED-447" not in internal_text, internal_text[:160])
        designer_text = chr(10).join(e.texts(e.reader("secret", can_admin=True)))
        _check("A04 ★行：designer/admin 仍可读缺键记录（fail-closed ≠ 全挡）",
               "MISSING-447" in designer_text, designer_text[:160])

    print("== K 组：新写入路径逐位不变 ==")
    with _Env() as e:
        e.cg.remember_event("user", "正常-447 新事件", sensitivity="private")
        with io.open(e.cg.recent_log, encoding="utf-8") as fh:
            rec = json.loads(fh.read().strip().split(chr(10))[-1])
        _check("K01 前提：Secure 写入面恒写 meta.sensitivity 键",
               (rec.get("meta") or {}).get("sensitivity") == "private", rec.get("meta"))
        internal_text = chr(10).join(e.texts(e.reader("internal")))
        _check("K02 新写入 private 记录对 internal 读方不可见（既有隔离不变）",
               "正常-447" not in internal_text)
        designer_text = chr(10).join(e.texts(e.reader("secret", can_admin=True)))
        _check("K03 新写入 private 记录对 designer 可见（既有语义不变）",
               "正常-447" in designer_text)

    print("== E 组：单点与接线钉子 ==")

    def _read(rel):
        try:
            with io.open(os.path.join(_REPO, rel), encoding="utf-8") as fh:
                return fh.read()
        except OSError:
            return ""

    src = _read("md_cg/mdcos.py")
    _check("E01 ★钉子：单点 _recent_effective_sens 缺键兜底 secret",
           "def _recent_effective_sens(" in src
           and 'get("sensitivity") or "secret"' in src)
    tree = ast.parse(src)
    fn = None
    for n in ast.walk(tree):
        if isinstance(n, ast.FunctionDef) and n.name == "recent_events":
            fn = n
    fn_src = ast.unparse(fn) if fn else ""
    _check("E02 ★钉子：recent_events 已不再用 DEFAULT_SENSITIVITY 兜底缺键",
           "DEFAULT_SENSITIVITY" not in fn_src
           and "_recent_effective_sens" in fn_src, fn_src[:120])


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


_SENS_OK = "        return (m or {}).get(\"sensitivity\") or \"secret\"" + chr(10)
_SENS_BAD = "        return (m or {}).get(\"sensitivity\") or DEFAULT_SENSITIVITY" + chr(10)
_ARMS = {
    "M1": ("md_cg/mdcos.py", _SENS_OK, _SENS_BAD, {"A01", "E01"}),
    "M2": (
        "md_cg/mdcos.py",
        "            if not self.principal.allows(msens):" + chr(10)
        + "                continue" + chr(10),
        "            if not self.principal.can_admin:" + chr(10)
        + "                continue" + chr(10),
        {"A02"},
    ),
    "M3": (
        "md_cg/mdcos.py",
        "            if (_rank(msens) >= _rank(\"private\")" + chr(10)
        + "                    and not self.principal.can_admin" + chr(10)
        + "                    and m.get(\"session\") != self.principal.session):" + chr(10),
        "            if (_rank(msens) >= _rank(\"private\")" + chr(10)
        + "                    and True" + chr(10)
        + "                    and m.get(\"session\") != self.principal.session):" + chr(10),
        {"A04", "K03"},
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
