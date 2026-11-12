# -*- coding: utf-8 -*-
# 功能名：审核裁决记录密级固定 internal，外部可复核（issue #522）
# 生效条件：python -X utf8 -m md_cg.test_issue522_review_record_sensitivity [--mutate]；
#           被测面＝md_cg/mdcos.py::MdCGOS._write_review_record 的审计件密级来源
# 子功能：A 组＝private 裁决者：审计件 internal / 外部 internal 可读 / verify_review_record ok；
#         B 组＝internal 裁决者对照；C 组＝private 目标正文不进审计件；E 组＝源码钉子
# 执行：--mutate 时就地短路一条判据（回 principal.clearance / 固定 secret / 固定 public），
#       指定断言须恰好转红
# 不适用条件：不迁移存量 private 审计件（issue #522 的「本地处置」是手工重写，另案）；
#             不修附带发现 created_at 被 add 刷新的问题（独立第二条，另案）
"""issue #522 守卫：裁决记录密级取 principal.clearance ⇒ 外部复核面失效。

病象（修前）：_write_review_record 对 MdCGSecure 写 sensitivity=principal.clearance；
裁决者是 private/secret 时审计件落成密文 + 会话绑定，非裁决者读面为空——
verify_review_record 对非裁决者返回 node_not_found，与 docstring「外部来源可读、
可复核」直接冲突。

修复语义：审计件保护级由件类型固定为 DEFAULT_SENSITIVITY(internal)，不随写入者
权限漂移；显式声明仍照走「声明↔落盘」闸。private 目标正文不进审计件（只含
target_id），故 internal 化不扩大正文暴露面。
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

_CHECKS = []
FAILS = []
_PRIVATE_BODY = "PRIVATE-CONTENT-522 目标正文不得进审计件"


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
        self.dir = tempfile.mkdtemp(prefix="iss522_")
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


def _secure(clearance, can_admin=True):
    from md_cg.mdcos import MdCGSecure
    from md_cg.security import Principal
    return MdCGSecure(os.environ["MDCG_ROOT"],
                      principal=Principal(clearance=clearance,
                                          can_write=True, can_admin=can_admin),
                      autoflush=1)


def _make_decision(clearance, target_private=False):
    dec = _secure(clearance)
    if target_private:
        dec.add("target_522", "# 功能名：目标" + chr(10) + chr(10) + _PRIVATE_BODY,
                layer="knowledge", sensitivity="private")
    pid = dec.propose("target_522", "# 功能名：提案" + chr(10) + chr(10) + "提案正文",
                      layer="knowledge")
    res = dec.review_decide(pid, "reject", reason="issue #522 测试")
    nid = res.get("record_node_id") or ""
    return dec, res, nid


def _assertions():
    print("== A 组：private 裁决者 ==")
    with _Env() as e:
        dec, res, nid = _make_decision("private")
        _check("A01 前提：裁决成功且产出审计节点",
               bool(nid) and bool(res.get("record_hash")),
               (res.get("record_error"), nid))
        own = dec.get(nid) or {}
        sens = (own.get("frontmatter") or {}).get("sensitivity")
        _check("A02 ★行：审计件密级固定 internal（不随裁决者 private）",
               sens == "internal", sens)
        dec.close()
        aud = _secure("internal", can_admin=False)
        try:
            got = aud.get(nid)
            ver = aud.verify_review_record(nid)
        finally:
            aud.close()
        _check("A03 ★行：外部 internal 身份可读审计件", got is not None)
        _check("A04 ★行：外部 verify_review_record ok=True/status=rejected",
               ver.get("ok") is True and ver.get("status") == "rejected", ver)

    print("== B 组：internal 裁决者对照 ==")
    with _Env() as e:
        dec, res, nid = _make_decision("internal")
        own = dec.get(nid) or {}
        sens = (own.get("frontmatter") or {}).get("sensitivity")
        _check("B01 对照：internal 裁决者审计件仍 internal", sens == "internal", sens)
        dec.close()
        aud = _secure("internal", can_admin=False)
        try:
            ver = aud.verify_review_record(nid)
        finally:
            aud.close()
        _check("B02 对照：外部复核 ok=True（既有语义不变）", ver.get("ok") is True, ver)

    print("== C 组：private 目标正文不进审计件 ==")
    with _Env() as e:
        dec, res, nid = _make_decision("private", target_private=True)
        own = dec.get(nid) or {}
        body = own.get("content") or ""
        _check("C01 private 目标正文不进审计件（只含 target_id）",
               _PRIVATE_BODY not in body and "target_522" in body, body[:120])
        dec.close()

    print("== E 组：源码钉子 ==")

    def _read(rel):
        try:
            with io.open(os.path.join(_REPO, rel), encoding="utf-8") as fh:
                return fh.read()
        except OSError:
            return ""

    src = _read("md_cg/mdcos.py")
    tree = ast.parse(src)
    fn = next((n for n in ast.walk(tree)
               if isinstance(n, ast.FunctionDef) and n.name == "_write_review_record"), None)
    fs = (ast.unparse(fn) if fn else "").replace('"', "'")
    _check("E01 ★钉子：审计件显式 sensitivity=DEFAULT_SENSITIVITY",
           "extra = {'sensitivity': DEFAULT_SENSITIVITY}" in fs, fs[:120])
    _check("E02 ★钉子：方法体不再取 principal.clearance",
           "getattr(self.principal, 'clearance'" not in fs)


def _run_assertions():
    global FAILS
    FAILS = []
    del _CHECKS[:]
    _assertions()
    print("通过 %d / 失败 %d" % (len(_CHECKS) - len(FAILS), len(FAILS)))
    return len(FAILS)


def _subprocess_fail_names():
    import glob
    for _pyc in glob.glob(os.path.join(_REPO, "md_cg", "__pycache__", "mdcos.*.pyc")):
        try:
            os.remove(_pyc)
        except OSError:
            pass
    r = subprocess.run([sys.executable, "-X", "utf8", _SELF, "--assert-only"],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", cwd=_REPO, timeout=600)
    names = set(re.findall(r"(?m)^\s*FAIL\s+([A-Z]\d+)", r.stdout or ""))
    return names, (r.stdout or "") + (r.stderr or "")


_ARMS = {
    "M1": (
        "md_cg/mdcos.py",
        '        extra = {"sensitivity": DEFAULT_SENSITIVITY}' + chr(10),
        "        extra = {}" + chr(10)
        + "        if hasattr(self, \"principal\"):" + chr(10)
        + "            extra[\"sensitivity\"] = getattr(self.principal, \"clearance\", None)" + chr(10),
        {"A02", "A03", "A04", "E01", "E02"},
    ),
    "M2": (
        "md_cg/mdcos.py",
        '        extra = {"sensitivity": DEFAULT_SENSITIVITY}' + chr(10),
        '        extra = {"sensitivity": "secret"}' + chr(10),
        {"A01", "A02", "A03", "A04", "B01", "B02", "C01", "E01"},
    ),
    "M3": (
        "md_cg/mdcos.py",
        '        extra = {"sensitivity": DEFAULT_SENSITIVITY}' + chr(10),
        '        extra = {"sensitivity": "public"}' + chr(10),
        {"A02", "B01", "E01"},
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
                print("[ANCHOR-MISS] %s：锚点命中 %d 次（期望 1）⇒ 无法变异" % (mid, _cnt))
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
