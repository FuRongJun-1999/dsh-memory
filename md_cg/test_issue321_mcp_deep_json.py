# -*- coding: utf-8 -*-
# 功能名：md_cg MCP stdio 入口对「深嵌套单行 JSON」的健壮性守卫（issue #321）
# 生效条件：python -X utf8 -m md_cg.test_issue321_mcp_deep_json [--mutate]；被测面=md_cg/mcp_server.py 的 stdin 读循环
# 子功能：A 组=子进程实跑入口（深嵌套行夹击 + 攻击行后探活 + 既有闸回归）；K 组=捕获面口径；E 组=解析点单点与通道在位
# 执行：--mutate 时逐条把判据改回改动前形态，守卫必须转红（定点变异自证）
# 验证方式：全部 PASS 即通过；--mutate 下每条变异的「指定命中」须与预期一致
# 不适用条件：不覆盖真实 MCP 宿主进程（本守卫直起 stdio 子进程）、不覆盖 POSIX 腿；不判工具层语义
"""issue #321 守卫：一行深嵌套 JSON 不得杀死 md_cg MCP server。

病象（修前）：stdin 读循环里 json.loads 外只捕 ValueError，而约 1 万层嵌套的
**合法** JSON 让 json.loads 抛 RecursionError（RuntimeError 族），逃出 main 的
try ⇒ 常驻 server rc=1 退出；解析在鉴权之前，零凭据可达，攻击行之后的请求
（含写入）全无应答。

判据取「攻击行之后的探活请求仍被应答」而非「rc==0」单点：rc 可能因其它
早退路径（root 守卫等）非 0，只有探活应答才证明读循环还在服务。
"""
import ast
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FAILS = []


def _check(name, cond, detail=""):
    if cond:
        print("  PASS " + name)
    else:
        print("  FAIL " + name + "  " + str(detail)[:200])
        FAILS.append(name)


_DEPTH = 10000


def _deep_line(depth=_DEPTH):
    return ('{"jsonrpc":"2.0","id":2,"method":"tools/call","params":'
            '{"name":"mdcg_info","arguments":{"meta":'
            + "[" * depth + "]" * depth + "}}}")


def _deep_obj_line(depth=_DEPTH):
    return ('{"jsonrpc":"2.0","id":2,"method":"tools/call","params":'
            '{"name":"mdcg_info","arguments":'
            + '{"a":' * depth + "1" + "}" * depth + "}}")


def _req(i, method="tools/list"):
    return json.dumps({"jsonrpc": "2.0", "id": i, "method": method})


def _env(tmp):
    # 目录名避开 Windows 保留设备名（aux/nul/...）：issue #57 的启动守卫会 fail-closed。
    return dict(os.environ, PYTHONUTF8="1", PYTHONPATH=_REPO,
                MDCG_ROOT=os.path.join(tmp, "brain"),
                MDCG_STATE_ROOT=os.path.join(tmp, "state"),
                MDCG_AUX_ROOT=os.path.join(tmp, "auxstore"),
                MDCG_DATA_ROOT=os.path.join(tmp, "datastore"),
                MDCG_EXPORT_ROOT=tmp,
                MDCG_TOKEN_FILE=os.path.join(tmp, "auxstore", "tokens.json"),
                MDCG_SUSTAIN="0", MDCG_SLEEP="0")


def _probe(lines):
    """起隔离 stdio 子进程，顺序喂 lines，返回 (rc, 应答 id 列表, stderr 尾)。"""
    tmp = tempfile.mkdtemp(prefix="iss321_")
    os.makedirs(os.path.join(tmp, "brain"), exist_ok=True)
    try:
        p = subprocess.Popen(
            [sys.executable, "-X", "utf8", "-m", "md_cg.mcp_server"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, env=_env(tmp), shell=False, cwd=_REPO,
            text=True, encoding="utf-8", errors="replace")
        try:
            out, err = p.communicate("\n".join(lines) + "\n", timeout=240)
        except subprocess.TimeoutExpired:
            p.kill()
            out, err = p.communicate()
            err = (err or "") + "\n[TIMEOUT]"
        ids = []
        for ln in (out or "").splitlines():
            ln = ln.strip()
            if not ln:
                continue
            try:
                ids.append(json.loads(ln).get("id"))
            except Exception:
                ids.append("unparsed")
        return p.returncode, ids, (err or "")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


print("== A 组：入口实跑（深嵌套行夹击 + 攻击行后探活）==")

rc, ids, err = _probe([_req(1), _deep_line(), _req(3)])
_check("A1 深嵌套数组行后进程仍在服务（rc==0）", rc == 0, "rc=%s" % rc)
_check("A2 攻击行之后的请求仍有应答（探活 id=3）", 3 in ids, ids)
_check("A3 深嵌套行按 Parse error 回一行（id=null 的 -32700）", None in ids, ids)

rc2, ids2, _ = _probe([_req(1), _deep_obj_line(), _req(3)])
_check("A4 深嵌套对象形态同款健壮（rc==0 且探活应答）",
       rc2 == 0 and 3 in ids2, (rc2, ids2))

rc3, ids3, _ = _probe([_req(1), _req(3)])
_check("A5 对照：无攻击行时两条请求都应答（判据非恒假）",
       rc3 == 0 and ids3 == [1, 3], ids3)

rc4, ids4, _ = _probe([_req(1), "{bad json", _req(3)])
_check("A6 对照：非法 JSON（ValueError 通道）仍回 -32700 且进程继续",
       rc4 == 0 and 3 in ids4 and None in ids4, (rc4, ids4))

_nan = ('{"jsonrpc":"2.0","id":9,"method":"tools/call","params":'
        '{"name":"mdcg_info","arguments":{"x":NaN}}}')
rc5, ids5, _ = _probe([_req(1), _nan, _req(3)])
_check("A7 回归：#151 的 NaN 字面量仍被拒（-32700）且进程继续",
       rc5 == 0 and 3 in ids5 and None in ids5, (rc5, ids5))

_SRC = io.open(os.path.join(_REPO, "md_cg", "mcp_server.py"),
               encoding="utf-8", newline="").read()
_TREE = ast.parse(_SRC)


def _handler_names(tree):
    """找「json.loads(..., parse_constant=...)」所在 try 的捕获面元素名。"""
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue
        for st in ast.walk(node):
            if (isinstance(st, ast.Call)
                    and isinstance(st.func, ast.Attribute)
                    and st.func.attr == "loads"
                    and isinstance(st.func.value, ast.Name)
                    and st.func.value.id == "json"
                    and any(k.arg == "parse_constant" for k in st.keywords)):
                names = []
                for h in node.handlers:
                    if isinstance(h.type, ast.Name):
                        names.append(h.type.id)
                    elif isinstance(h.type, ast.Tuple):
                        names.extend(e.id for e in h.type.elts
                                     if isinstance(e, ast.Name))
                return names
    return None


_NAMES = _handler_names(_TREE)
print("== K 组：捕获面口径（AST 面）==")
_check("K0 解析点定位成功（判据有效）", _NAMES is not None, _NAMES)
_check("K1 捕获面含 RecursionError（#321 收口）",
       bool(_NAMES) and "RecursionError" in _NAMES, _NAMES)
_check("K2 捕获面仍含 ValueError（#83.1 的 -32700 通道未丢）",
       bool(_NAMES) and "ValueError" in _NAMES, _NAMES)
_check("K3 捕获面收窄：不吞 Exception/BaseException（不放大既有语义）",
       bool(_NAMES) and not ({"Exception", "BaseException"} & set(_NAMES)),
       _NAMES)

_HIVE = os.path.join(_REPO, "hive", "hive_mcp", "mcp_server.py")
_HV = (io.open(_HIVE, encoding="utf-8", newline="").read()
       if os.path.exists(_HIVE) else "")
_check("K4 口径同源：hive 入口（N231）也把 RecursionError 纳入捕获面",
       "RecursionError" in _HV, "")

print("== E 组：解析点单点与通道在位 ==")
_tries = 0
for node in ast.walk(_TREE):
    if not isinstance(node, ast.Try):
        continue
    for st in ast.walk(node):
        if (isinstance(st, ast.Call) and isinstance(st.func, ast.Attribute)
                and st.func.attr == "loads"
                and isinstance(st.func.value, ast.Name)
                and st.func.value.id == "json"
                and any(k.arg == "parse_constant" for k in st.keywords)):
            _tries += 1
_check("E1 读循环解析点单点（parse_constant 形态的 loads 恰 1 处）",
       _tries == 1, _tries)
_check("E2 -32700 回写通道在位（Parse error 分支未丢）",
       "-32700" in _SRC, "")
_check("E3 深嵌套行不进入解析面：捕获后 continue/回写而非抛出",
       re.search(r"except \(?[^)]*RecursionError", _SRC) is not None, "")

print("")
if FAILS:
    print("issue #321 结果：%d 失败" % len(FAILS))
else:
    print("issue #321 结果：全部通过")


# ---------------------------------------------------------------- 定点变异

_MUTATIONS = (
    ("V1 捕获面回到修前形态（只捕 ValueError）",
     "md_cg/mcp_server.py",
     "        except (ValueError, RecursionError) as _pe:",
     "        except ValueError as _pe:",
     ("A1", "A2", "A3", "K1")),
    ("V2 捕获面收窄过头：只捕 RecursionError（丢掉 #83.1 的 ValueError 通道）",
     "md_cg/mcp_server.py",
     "        except (ValueError, RecursionError) as _pe:",
     "        except RecursionError as _pe:",
     ("A6", "K2")),
    ("V3 捕获面放大成 Exception（吞掉一切，判据不再是白名单）",
     "md_cg/mcp_server.py",
     "        except (ValueError, RecursionError) as _pe:",
     "        except (ValueError, RecursionError, Exception) as _pe:",
     ("K3",)),
)


def _mirror_build():
    dst = tempfile.mkdtemp(prefix="iss321_mut_")
    for name in ("md_cg", "scripts", "hive"):
        src = os.path.join(_REPO, name)
        if os.path.isdir(src):
            shutil.copytree(src, os.path.join(dst, name),
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc",
                                                         "target"))
    for name in sorted(os.listdir(_REPO)):
        p = os.path.join(_REPO, name)
        if os.path.isfile(p) and (name.endswith(".py")
                                  or name in ("README.md", "pyproject.toml",
                                              "package.json")):
            shutil.copy2(p, os.path.join(dst, name))
    return dst


def _run_in(tree):
    env = dict(os.environ)
    env["PYTHONPATH"] = tree
    env["PYTHONUTF8"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    pr = subprocess.run([sys.executable, "-X", "utf8", "-m",
                         "md_cg.test_issue321_mcp_deep_json"],
                        capture_output=True, text=True, encoding="utf-8",
                        errors="replace", cwd=tree, env=env, timeout=3600)
    out = (pr.stdout or "") + (pr.stderr or "")
    reds = [ln.split("FAIL ", 1)[1].strip()
            for ln in out.splitlines() if "FAIL " in ln]
    return pr.returncode, reds, out


def _mutate():
    print("!! 定点变异自证：逐条把判据改回改动前形态，守卫必须转红")
    tree = _mirror_build()
    try:
        rc, reds, out = _run_in(tree)
        print("  未变异镜像基线：rc=%d 红项=%d（必须 rc=0 且 0 红）"
              % (rc, len(reds)))
        if rc != 0 or reds:
            print(chr(10).join(out.splitlines()[-25:]))
        ok, bad = 0, []
        for desc, rel, old, new, exp in _MUTATIONS:
            p = os.path.join(tree, rel)
            t = io.open(p, encoding="utf-8", newline="").read()
            if t.count(old) != 1:
                bad.append("%s —— 锚点在 %s 里命中 %d 次"
                           % (desc, rel, t.count(old)))
                print("  ANCHOR-MISS " + desc)
                continue
            bak = t
            io.open(p, "w", encoding="utf-8", newline="").write(
                t.replace(old, new, 1))
            for root, dd, ff in os.walk(tree):
                if os.path.basename(root) == "__pycache__":
                    shutil.rmtree(root, ignore_errors=True)
            rc2, reds2, out2 = _run_in(tree)
            io.open(p, "w", encoding="utf-8", newline="").write(bak)
            hit = [r for r in reds2 if r.startswith(exp)]
            if rc2 != 0 and len(hit) == len(exp):
                ok += 1
                print("  OK   %s  红项=%d 指定命中=%d/%d"
                      % (desc, len(reds2), len(hit), len(exp)))
            else:
                bad.append(desc)
                print("  MISMATCH %s  红项=%d 指定命中=%d/%d rc=%d"
                      % (desc, len(reds2), len(hit), len(exp), rc2))
                for r in reds2[:8]:
                    print("        FAIL " + r)
        print("定点变异自证：%s（%d 条不合格）"
              % ("PASS" if not bad else "FAIL", len(bad)))
        for b in bad:
            print("  不合格：" + b)
    finally:
        shutil.rmtree(tree, ignore_errors=True)


def main():
    if "--mutate" in sys.argv:
        _mutate()
        return 0 if not FAILS else 1
    return 0 if not FAILS else 1


if __name__ == "__main__":
    sys.exit(main())