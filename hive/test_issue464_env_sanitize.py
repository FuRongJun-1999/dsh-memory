# -*- coding: utf-8 -*-
# 功能名：hive/exec_cmd 子进程 env 凭据剥离（issue #464）
# 生效条件：python -X utf8 -m hive.test_issue464_env_sanitize [--mutate]；
#           被测面＝hive/exec_cmd.py::_sanitize_env 与 run_cmd 的 env 构造
# 子功能：U 组＝单点语义（剥离/保留/前缀相似不误伤/显式声明保留）；B 组＝真实 run_cmd 行为；
#         E 组＝接线钉子
# 执行：--mutate 时就地短路一条判据（回全量继承 / env 清空 / 正则失效），指定断言须恰好转红
# 不适用条件：不判 command 审批/可执行根闸（issue #464 的另一半，需维护者裁定审批载体，另案）
"""issue #464（env 半件）守卫：池内 spec 命令继承 serve 全量环境 ⇒ 凭据外带。

病象（修前）：run_cmd 以 env={**os.environ, **spec_env} 启动子进程，serve 进程里的
*_KEY / *_TOKEN / *_SECRET / *_PASSWORD / AEIS_DESIGNER_KEY 等固化凭据被池内
（本地可写）spec 的一条 python -c print(os.environ) 全量取走，rc=0 / ok=true 静默。

修复语义：新增 _sanitize_env(base, extra) 判据单点——base（os.environ）中命中
「独立词段」敏感模式的键不进子进程；spec.env 显式声明保留（调用方自担）；PATH/
PYTHONUTF8/proxy 等保持，既有任务零影响。本件只做 env 剥离；command 任意 argv 的
审批/根闸属另案（issue #464 的另一半）。
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

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
_SELF = os.path.abspath(__file__)
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from hive import exec_cmd as exc

_SANITIZE = getattr(exc, "_sanitize_env", None)
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


def _write_spec(job_dir, spec):
    with io.open(os.path.join(job_dir, "spec.json"), "w", encoding="utf-8") as fh:
        json.dump(spec, fh, ensure_ascii=False)


def _run_and_read(job_dir):
    rc = exc.run_cmd(job_dir)
    with io.open(os.path.join(job_dir, "result.json"), encoding="utf-8") as fh:
        res = json.load(fh)
    return rc, res


_PRINT_ENV = (
    "import os,json;print(json.dumps({k: os.environ.get(k) for k in "
    "['FAKE_SERVE_TOKEN','AEIS_DESIGNER_KEY','FAKE_PASSWORD','PATH','EXPLICIT_OK','EXPLICIT_TOKEN']}))"
)


def _assertions():
    print("== U 组：_sanitize_env 单点语义 ==")
    if _SANITIZE is None:
        for name in ("U01 敏感键全剥（KEY/TOKEN/SECRET/PASSWORD/PASSWD/CREDENTIAL/AUTH/PWD）",
                     "U02 非敏感键保留（PATH/PYTHONUTF8/proxy/LANG/FOO）",
                     "U03 前缀相似不误伤（MY_KEYSTONE/PASSWORDLESS/KEYWORDS/AUTHORS）",
                     "U04 extra 显式声明保留"):
            _check(name, False, "hive.exec_cmd._sanitize_env 不存在")
    else:
        base = {"FOO_KEY": "1", "A_TOKEN": "2", "B_SECRET": "3",
                "C_PASSWORD": "4", "D_PASSWD": "5", "E_CREDENTIAL": "6",
                "F_AUTH": "7", "G_PWD": "8", "AEIS_DESIGNER_KEY": "9",
                "HIVE_ORCH_TOKEN": "10", "PATH": "x"}
        got = _SANITIZE(base, {})
        _check("U01 敏感键全剥（KEY/TOKEN/SECRET/PASSWORD/PASSWD/CREDENTIAL/AUTH/PWD）",
               set(got) == {"PATH"}, got)
        base2 = {"PATH": "x", "PYTHONUTF8": "1", "HTTP_PROXY": "p",
                 "HTTPS_PROXY": "p", "LANG": "zh_CN", "FOO": "bar"}
        _check("U02 非敏感键保留（PATH/PYTHONUTF8/proxy/LANG/FOO）",
               _SANITIZE(base2, {}) == base2, _SANITIZE(base2, {}))
        base3 = {"MY_KEYSTONE": "1", "PASSWORDLESS": "2", "KEYWORDS": "3",
                 "AUTHORS": "4"}
        _check("U03 前缀相似不误伤（MY_KEYSTONE/PASSWORDLESS/KEYWORDS/AUTHORS）",
               _SANITIZE(base3, {}) == base3, _SANITIZE(base3, {}))
        ex = {"EXPLICIT_OK": "v", "EXPLICIT_TOKEN": "kept"}
        _check("U04 extra 显式声明保留（含敏感名，语义：调用方自担）",
               _SANITIZE({}, ex) == ex, _SANITIZE({}, ex))

    print("== B 组：真实 run_cmd 行为 ==")
    tmp = tempfile.mkdtemp(prefix="iss464_")
    try:
        os.environ["FAKE_SERVE_TOKEN"] = "abc123secret"
        os.environ["AEIS_DESIGNER_KEY"] = "designer-secret-464"
        os.environ["FAKE_PASSWORD"] = "p@ss464"
        job = os.path.join(tmp, "job")
        os.makedirs(job)
        _write_spec(job, {"model": "cmd", "user_prompt": "iss464",
                          "command": [sys.executable, "-c", _PRINT_ENV],
                          "env": {"EXPLICIT_OK": "v464"}})
        rc, res = _run_and_read(job)
        blob = json.dumps(res, ensure_ascii=False)
        stdout = (res.get("steps") or [{}])[0].get("stdout_head") or ""
        _check("B01 ★行：serve 凭据不再随继承外带（token/designer/password 均不可见）",
               "abc123secret" not in blob and "designer-secret-464" not in blob
               and "p@ss464" not in blob, stdout[:180])
        _check("B02 对照：spec.env 显式声明与非敏感 PATH 仍可见（任务可运行）",
               rc == 0 and res.get("ok") is True
               and '"EXPLICIT_OK": "v464"' in stdout and '"PATH": "' in stdout,
               (rc, stdout[:180]))
    finally:
        for k in ("FAKE_SERVE_TOKEN", "AEIS_DESIGNER_KEY", "FAKE_PASSWORD"):
            os.environ.pop(k, None)
        shutil.rmtree(tmp, ignore_errors=True)

    print("== E 组：接线钉子 ==")
    with io.open(os.path.join(_REPO, "hive/exec_cmd.py"), encoding="utf-8") as fh:
        src = fh.read()
    tree = ast.parse(src)
    fn = None
    for n in ast.walk(tree):
        if isinstance(n, ast.FunctionDef) and n.name == "run_cmd":
            fn = n
    fn_src = ast.unparse(fn) if fn else ""
    _check("E01 ★钉子：_sanitize_env 单点存在", "def _sanitize_env(" in src)
    _check("E02 ★钉子：run_cmd 经单点构造 env、不再直叠 os.environ",
           "env = _sanitize_env(os.environ, spec_env)" in fn_src
           and "{**os.environ" not in fn_src)


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
        "hive/exec_cmd.py",
        "    env = _sanitize_env(os.environ, spec_env)\n",
        "    env = {**os.environ, **spec_env}\n",
        {"B01", "E02"},
    ),
    "M2": (
        "hive/exec_cmd.py",
        "    env = _sanitize_env(os.environ, spec_env)\n",
        "    env = {}\n",
        {"B02", "E02"},
    ),
    "M3": (
        "hive/exec_cmd.py",
        '    r"(?:^|_)(?:KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL|AUTH|PWD)(?:$|_)",\n    re.IGNORECASE)',
        '    r"(?!)")',
        {"U01", "B01"},
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
