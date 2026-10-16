# -*- coding: utf-8 -*-
# 功能名：写面层闸缺 sensitivity 键的口径登记（issue #450，P3）
# 生效条件：python -X utf8 -m md_cg.test_issue450_writegate_registration [--mutate]；
#           被测面＝md_cg/protect.py::_resolve_target 的缺键回落登记与 guard_overwrite 行为对照
# 子功能：A 组＝internal 身份 × legacy 无键节点放行 / × 显式 restricted 拒绝（登记语义与实测绑定）；
#         E 组＝登记注释钉子（点名 #450/#359/#298 且位于 return 之前）
# 执行：--mutate 时就地短路一条判据（撤登记注释 / 改缺键回落行为），指定断言须恰好转红
# 不适用条件：不代维护者裁定写面是否应改 fail-closed（issue #450 明示交裁）；
#             不判 #298/#359 两面本身
"""issue #450 守卫：写面层闸缺 sensitivity 键回落 internal 且无登记。

病象（修前）：protect._resolve_target 三来源皆假值时 or DEFAULT_SENSITIVITY
（internal）——写面层闸对 legacy 无键节点 fail-open，却既无安全语义注释、也无
#359 那类「为何按缺省档」的裁定理由；与读面 #298 的 fail-closed 相反处置。

修复语义：本件只做**登记**（issue #450 的价值＝把四面口径摊开供维护者裁定，定级
P3）——在 return 前落一段点名 #450/#359/#298 的注释，明确「登记现状、不代裁」；
行为逐位不变（guard_overwrite 对 legacy 放行、对显式 restricted 拒绝）。
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

_CC = ("# 功能名：部署" + chr(10) + "# 生效条件：部署相关" + chr(10)
       + "# 子功能：端口" + chr(10) + "# 执行：%s" + chr(10)
       + "# 验证方式：用户自述" + chr(10) + "# 不适用条件：无关话题")
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
        self.dir = tempfile.mkdtemp(prefix="iss450_")
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
        return self

    def __exit__(self, *exc):
        for k, v in self.saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(self.dir, ignore_errors=True)
        return False

    def base(self):
        from md_cg.mdcg import MdCG
        return MdCG(os.environ["MDCG_ROOT"])

    def secure(self, clearance):
        from md_cg.mdcos import MdCGSecure
        from md_cg.security import Principal
        return MdCGSecure(os.environ["MDCG_ROOT"],
                          principal=Principal(clearance=clearance), autoflush=1)


def _assertions():
    print("== A 组：guard_overwrite 行为对照（登记语义与实测绑定） ==")
    with _Env() as e:
        from md_cg import protect
        base = e.base()
        base.add("legacy_n", _CC % "端口 7001", layer="contextual")
        fm = ((base.get("legacy_n") or {}).get("frontmatter") or {})
        _check("A00 前提：基类写入的 legacy 节点无 sensitivity 键",
               "sensitivity" not in fm, sorted(fm)[:24])
        cen = e.secure("internal")
        # 登记的直接单点：三来源皆假（无条目、无节点）⇒ 回落 DEFAULT_SENSITIVITY。
        lay, sens = protect._resolve_target(cen, "no_such_node_450",
                                            layer="contextual", sensitivity=None)
        _check("A01 ★行：_resolve_target 三来源皆假 ⇒ 回落 internal（登记的单点）",
               (lay, sens) == ("contextual", "internal"), (lay, sens))
        try:
            protect.require_layer(cen, "no_such_node_450", layer="contextual",
                                  sensitivity=None)
            passed = True
        except Exception:                               # noqa: BLE001
            passed = False
        _check("A02 ★行：internal 身份 × 缺省档 internal ⇒ 层闸放行（fail-open 行为面）",
               passed)
        try:
            protect.require_layer(cen, "no_such_node_451", layer="contextual",
                                  sensitivity="restricted")
            denied = False
        except Exception:                               # noqa: BLE001
            denied = True
        _check("A03 对照：显式 restricted ⇒ 拒绝（密级闸在位，变量只有密级）",
               denied)
        try:
            protect.guard_overwrite(cen, "legacy_n", layer="contextual",
                                    sensitivity=None)
            allowed = True
        except Exception:                               # noqa: BLE001
            allowed = False
        _check("A04 现场：internal 身份 × legacy 无键节点经 guard_overwrite ⇒ 放行",
               allowed)


    print("== E 组：登记注释钉子 ==")
    with io.open(os.path.join(_REPO, "md_cg/protect.py"), encoding="utf-8") as fh:
        src = fh.read()
    _check("E01 ★钉子：缺键回落处有点名 #450/#359/#298 的登记注释",
           "issue #450" in src and "#359" in src and "#298" in src)
    i = src.find("# issue #450")
    j = src.find('return _layer or "knowledge", _sens or DEFAULT_SENSITIVITY')
    _check("E02 ★钉子：登记注释位于缺键 return 之前（同一单点、不是别处散文）",
           i >= 0 and j >= 0 and i < j, (i, j))


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


_COND = 'return _layer or "knowledge", _sens or DEFAULT_SENSITIVITY'
_ARMS = {
    "M1": ("md_cg/protect.py",
           "    # issue #450（P3·口径登记，行为不改）：三来源皆假值时回落 DEFAULT_SENSITIVITY——",
           "    # 登记注释已撤（变异臂）——",
           {"E01", "E02"}),
    "M2": ("md_cg/protect.py", _COND, 'return _layer or "knowledge", _sens or "secret"',
           {"A01", "A02", "E02"}),
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
