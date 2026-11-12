# -*- coding: utf-8 -*-
"""issue #544 守卫：verifier 受限沙箱的**反射逃逸链**必须被 AST 门拦下。

背景（缺陷）：`_EXEC_RUNNER_SRC` 在受限命名空间里 `exec` 被校验代码，而
builtins 白名单里 `object`/`type` 本就在（#185 的决定）⇒ 可经
`object.__subclasses__()` → `__init__.__globals__['__builtins__']`
取回**真 builtins**，再 `open()` 写任意文件；且 L1/L2/L3 三层**仍报 ok:true**
（逃逸对校验结论不可见）。实测逃逸可写出仓库外标记文件。

本守卫的判据（可机械复核）：
  ① 逃逸载荷（反射链）⇒ 被拒，且**不产生副作用文件**（核心判据）；
  ② 同载荷去掉反射链、改用字面 `open()` ⇒ 同样被拒（既有 L2/L3 行为不回退）；
  ③ 干净纯函数 ⇒ 通过（**修复不得过宽**）；
  ④ 单元表里 4 条合法单元（元编程/运算符重载/异常链）**不得**被误伤
     —— 这一条是修 #544 时最容易踩的坑：按「一切 dunder 皆拒」会额外拒掉
     19 条正在通过的单元（实测），故判据取最小充分集。

跑法（任意 cwd）：
    python -X utf8 -m md_cg.test_issue544_sandbox_reflection_gate
退出码：全部通过 0，存在失败 1。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

_PASS = 0
_FAIL = 0

#: 逃逸载荷：反射链取回真 builtins 后写文件（issue #544 的 PoC）。
_ESCAPE = '''def f(x):
    return x

_done = False
for _c in object.__subclasses__():
    try:
        _gg = getattr(_c, '__init__').__globals__
    except Exception:
        continue
    if '__builtins__' in _gg and not _done:
        _b = _gg['__builtins__']
        _open = _b['open'] if isinstance(_b, dict) else _b.open
        try:
            _open(r'{marker}', 'w').write('arbitrary code execution')
            _done = True
        except Exception:
            pass
'''

#: 字面 open（既有 L2/L3 白名单已能拦；此处作为**不回退**对照）。
_LITERAL_OPEN = '''def f(x):
    open(r'{marker}', 'w').write('x')
    return x
'''

#: 干净纯函数（不得误伤）。
_CLEAN = '''def f(x):
    """恒等。"""
    return x
'''

#: 单元表里**合法**使用反射原语的单元——按「一切 dunder 皆拒」会误伤它们。
_LEGIT_UNIT_KEYS = ("元编程-动态建类", "元编程-元编程-元类定制", "元编程-元类定制",
                    "面向对象-运算符重载", "异常-异常链")


def ok(cond, label, detail=None):
    global _PASS, _FAIL
    if cond:
        _PASS += 1
        print("  [PASS] %s" % label)
    else:
        _FAIL += 1
        print("  [FAIL] %s%s" % (label, ("  <- " + repr(detail)) if detail is not None else ""))


def _verify(code: str, cwd: str, marker: str) -> dict:
    """跑一次 verifier CLI，返回其 JSON 输出。"""
    req = {"task": "unit", "code": code.format(marker=marker),
           "unit_id": "i544", "cases": [[1, 1]]}
    rp = os.path.join(cwd, "req.json")
    with open(rp, "w", encoding="utf-8") as fh:
        json.dump(req, fh, ensure_ascii=False)
    env = dict(os.environ)
    env["PYTHONPATH"] = _REPO
    env["PYTHONUTF8"] = "1"
    p = subprocess.run(
        [sys.executable, "-X", "utf8", "-B", "-m",
         "md_cg.whitebox_kb.wisdom.verifier", "--verify", rp],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        env=env, cwd=_REPO, timeout=240)
    try:
        return json.loads(p.stdout or "{}")
    except Exception:
        return {"_raw": (p.stdout or "")[-400:]}


def _l2_l3_ok(res: dict):
    """取 L2/L3 两层的 ok 值（逃逸时三层全 True 是缺陷特征）。"""
    out = {}
    for c in (res.get("checks") or []):
        lv = c.get("level", "")
        if lv.startswith("L2"):
            out["L2"] = c.get("ok")
        if lv.startswith("L3"):
            out["L3"] = c.get("ok")
    return out


def main() -> int:
    sandbox = tempfile.mkdtemp(prefix="issue544_")
    try:
        marker = os.path.join(sandbox, "PWNED.txt")

        print("== G1 反射逃逸载荷 ⇒ 必须被拒且无副作用（核心判据）==")
        if os.path.exists(marker):
            os.remove(marker)
        r1 = _verify(_ESCAPE, sandbox, marker)
        ok(not os.path.exists(marker),
           "G1a 未产生副作用文件（逃逸被拦）", marker)
        layers = _l2_l3_ok(r1)
        ok(layers.get("L2") is False or r1.get("exec") == "error",
           "G1b L2 报失败或 exec=error（不再静默通过）", (layers, r1.get("exec")))

        print("== G2 字面 open ⇒ 仍被拒（既有行为不回退）==")
        m2 = os.path.join(sandbox, "LITERAL.txt")
        if os.path.exists(m2):
            os.remove(m2)
        _verify(_LITERAL_OPEN, sandbox, m2)
        ok(not os.path.exists(m2), "G2 字面 open 未产生文件", m2)

        print("== G3 干净纯函数 ⇒ 通过（修复不得过宽）==")
        r3 = _verify(_CLEAN, sandbox, marker)
        l3 = _l2_l3_ok(r3)
        ok(l3.get("L2") is True, "G3a L2 通过（不误伤正常代码）", l3)
        ok(l3.get("L3") is True, "G3b L3 通过", l3)

        print("== G4 单元表合法单元不得被误伤（最小充分集的判据）==")
        try:
            sys.path.insert(0, os.path.join(_REPO, "md_cg", "whitebox_kb", "wisdom"))
            import io                                       # noqa: PLC0415
            src = io.open(os.path.join(_REPO, "md_cg", "whitebox_kb",
                                       "wisdom", "verifier.py"),
                          encoding="utf-8").read()
            # 取 _ESCAPE_ATTRS 的真源，断言它**不含**会误伤合法单元的名字
            i = src.find("_ESCAPE_ATTRS = frozenset({")
            j = src.find("})", i)
            block = src[i:j]
            for bad in ("__name__", "__cause__", "__marker__"):
                ok(bad not in block,
                   "G4a _ESCAPE_ATTRS 不含 %s（否则误伤合法单元）" % bad)
            ok("__subclasses__" in block and "__globals__" in block,
               "G4b _ESCAPE_ATTRS 含逃逸链必需的两条")
        except Exception as exc:                            # noqa: BLE001
            ok(False, "G4 读取 _ESCAPE_ATTRS 真源", "%s: %s" % (type(exc).__name__, exc))

        print("=" * 64)
        print("通过 %d / 失败 %d" % (_PASS, _FAIL))
        print("=" * 64)
        return 1 if _FAIL else 0
    finally:
        shutil.rmtree(sandbox, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
