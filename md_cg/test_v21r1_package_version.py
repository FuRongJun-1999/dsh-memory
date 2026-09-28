# -*- coding: utf-8 -*-
"""md_cg · 包版本读取 fail-closed 守卫（v21-R1：非对象 package.json 让服务起不来）

缺陷（修复前）：`md_cg/mcp_server.py:47-53` 与 `hive/hive_mcp/mcp_server.py:48-54`
的 `_package_version` 只捉 `(OSError, ValueError)`，随后**无条件** `.get("version")`：
  · `package.json` 是**合法 JSON 但顶层非对象**（`[1,2]` / `"0.1.0"` / `123` /
    `null` / `true`）→ `.get` 抛 AttributeError，**逃出 except**；
  · 而 `SERVER_VERSION = _package_version()`（md_cg:57 / hive:58）是**模块级
    立即求值**——异常发生在 import 期，`python -m md_cg.mcp_server` / `-m
    hive.hive_mcp.mcp_server` 连 initialize 都发不出就退出（服务起不来，
    与「版本号退化」完全不是一个量级）；
  · `{"version": 123}` 不抛但把 **int** 当版本号塞进 initialize 的
    serverInfo.version（协议要求字符串），调用方拿到错类型。

修复：`_package_version` 只认「读到 dict 且 "version" 为**非空字符串**」，其余
（不可读/JSON 非法/顶层非对象/version 非字符串/空串）一律回落 "0.1.0"；except
补 TypeError/AttributeError 兜底。同族既有守卫 `md_cg/test_server_version.py`
只覆盖「好文件 → 版本联动」，本守卫补**坏文件**面。

守卫（四组，全部临时包根 + 哑主密钥/哑令牌，绝不写真实 package.json、绝不触
真实 ~/.mdcg）：
  [1] 变体矩阵（16 形态 × 2 模块，真实 import + importlib.reload 重跑模块级
      `SERVER_VERSION = _package_version()`）：修前 `[1,2]` 等非对象形态报
      AttributeError、`{"version": 123}` 得 int 123；修后一律回落 "0.1.0"，
      合法形态（"9.9.9"/"0.6.0"）原样；
  [2] hive 握手端到端（真实 stdio 子进程，临时包根内 `package.json=[1,2]`）：
      修前进程 import 期即死、无任何响应；修后服务起得来且 initialize 自报
      "0.1.0"；换合法 version 时自报该值（证明该腿真有判别力，不是常量）；
  [3] md_cg 握手端到端（同上，另加临时 MDCG_ROOT + 哑令牌/哑主密钥）；
  [4] 不回归：真实仓库的 md_cg/hive 两模块 SERVER_VERSION 仍等于真实
      package.json 的 version（既有 test_server_version.py 口径）。

运行：python -m md_cg.test_v21r1_package_version
"""
from __future__ import annotations

import gc
import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

from . import crypto, tokens

PASS = FAIL = 0
FAILS = []

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DUMMY_KEK = "ab" * 32                       # 哑主密钥：子进程绝不触真实密钥库


def _clean(root):
    """尽力清理临时包根：Windows 下句柄未释放会让 rmtree 静默失败，故重试并告警。"""
    for _ in range(4):
        shutil.rmtree(root, ignore_errors=True)
        if not os.path.exists(root):
            return
        gc.collect()
        time.sleep(0.2)
    print("  [warn] 临时目录未能清理（句柄占用？）：%s" % os.path.basename(root))

# (package.json 正文（None=删文件）, 期望版本)
VARIANTS = [
    ("[1, 2]", "0.1.0"),                     # 顶层数组（AttributeError 逃逸）
    ('"0.9.9"', "0.1.0"),                    # 顶层裸字符串
    ("123", "0.1.0"),                        # 顶层数字
    ("null", "0.1.0"),                       # 顶层 null
    ("true", "0.1.0"),                       # 顶层 bool
    ('{"version": 123}', "0.1.0"),           # int 版本号曾原样进握手
    ('{"version": ["9.9.9"]}', "0.1.0"),
    ('{"version": {"a": 1}}', "0.1.0"),
    ('{"version": null}', "0.1.0"),
    ('{"version": ""}', "0.1.0"),
    ('{"version": "   "}', "0.1.0"),
    ('{"name": "x"}', "0.1.0"),              # 无 version 键
    ("{", "0.1.0"),                          # JSON 非法（ValueError 老路）
    (None, "0.1.0"),                         # 文件缺失
    ('{"version": "9.9.9"}', "9.9.9"),       # 合法
    ('{"version": "0.6.0", "extra": [1]}', "0.6.0"),   # 合法（多键）
]

DRIVER = '''# -*- coding: utf-8 -*-
"""测试驱动：逐变体写 package.json 后 reload 两个 server 模块并回报结果。

只做两件事：真实 import（触发模块级 `SERVER_VERSION = _package_version()`）
与 importlib.reload（重跑同一句）——即缺陷的**真实消费点**，不改被测代码。
"""
import importlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
MODS = ("md_cg.mcp_server", "hive.hive_mcp.mcp_server")
VARIANTS = json.load(open(os.path.join(HERE, "_variants.json"), encoding="utf-8"))


def write_pkg(body):
    p = os.path.join(HERE, "package.json")
    if body is None:
        if os.path.exists(p):
            os.remove(p)
        return
    with open(p, "w", encoding="utf-8") as f:
        f.write(body)


def probe():
    out = {}
    for name in MODS:
        try:
            m = importlib.import_module(name)          # 首次 import
        except Exception as e:                          # noqa: BLE001
            out[name] = ["IMPORT_ERR", type(e).__name__]
            continue
        try:
            m = importlib.reload(m)                     # 重跑模块级赋值
            v = m.SERVER_VERSION
            out[name] = ["OK", repr(v), type(v).__name__]
        except Exception as e:                          # noqa: BLE001
            out[name] = ["RELOAD_ERR", type(e).__name__]
    return out


results = []
write_pkg('{"version": "0.0.0"}')                       # 先保证两模块能 import
for i, body in enumerate(VARIANTS):
    write_pkg(body)
    results.append({"i": i, "r": probe()})
print(json.dumps(results))
'''


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}" + (f" · {detail}" if detail else ""))
    else:
        FAIL += 1
        FAILS.append(f"{name} · {detail}" if detail else name)
        print(f"  [FAIL] {name}" + (f" · {detail}" if detail else ""))


def _mk_pkg_root(tmp, name: str) -> str:
    """临时包根：md_cg/ 与 hive/hive_mcp/ 的真实源码副本 + 根 package.json 占位。

    副本是**当前源码**（改动即生效），根下 package.json 决定 `_package_version`
    读到的内容——真实 __file__ 推导，不 mock 任何函数。
    """
    root = os.path.join(tmp, name)
    os.makedirs(root, exist_ok=True)
    shutil.copytree(os.path.join(REPO, "md_cg"), os.path.join(root, "md_cg"),
                    ignore=shutil.ignore_patterns("__pycache__"))
    os.makedirs(os.path.join(root, "hive", "hive_mcp"), exist_ok=True)
    shutil.copy(os.path.join(REPO, "hive", "__init__.py"),
                os.path.join(root, "hive", "__init__.py"))
    for fn in glob.glob(os.path.join(REPO, "hive", "hive_mcp", "*.py")):
        shutil.copy(fn, os.path.join(root, "hive", "hive_mcp", os.path.basename(fn)))
    with open(os.path.join(root, "package.json"), "w", encoding="utf-8") as f:
        f.write('{"version": "0.0.0"}')
    return root


def _dry_run(root, variants) -> list:
    """跑驱动（真实 import/reload），返回每个变体的逐模块结果。"""
    with open(os.path.join(root, "_variants.json"), "w", encoding="utf-8") as f:
        json.dump([b for b, _e in variants], f, ensure_ascii=False)
    with open(os.path.join(root, "_drv.py"), "w", encoding="utf-8") as f:
        f.write(DRIVER)
    env = dict(os.environ)
    env["PYTHONPATH"] = REPO                       # 同级仓库根模块（aeis_core 等）
    env["PYTHONUTF8"] = "1"
    p = subprocess.run([sys.executable, "-X", "utf8", "_drv.py"], cwd=root,
                       env=env, capture_output=True, text=True,
                       encoding="utf-8", timeout=300)
    if p.returncode != 0:
        raise RuntimeError("驱动失败 rc=%s stderr=%s" % (p.returncode,
                                                        (p.stderr or "")[-400:]))
    return json.loads(p.stdout.strip().splitlines()[-1])


def _handshake(root, module: str, env: dict):
    """真实 stdio 子进程发 initialize，返回 (版本, 原始响应, stderr)。"""
    p = subprocess.Popen([sys.executable, "-X", "utf8", "-m", module],
                         stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, text=True, encoding="utf-8",
                         env=env, cwd=root)
    try:
        p.stdin.write(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                                  "params": {"protocolVersion": "2024-11-05",
                                             "capabilities": {},
                                             "clientInfo": {"name": "v21r1",
                                                            "version": "1"}}}) + "\n")
        p.stdin.flush()
        line = p.stdout.readline()                  # 进程死 → EOF，不阻塞
        if not line:
            return None, None, (p.stderr.read() or "")[-300:]
        resp = json.loads(line)
        ver = ((resp.get("result") or {}).get("serverInfo") or {}).get("version")
        return ver, resp, ""
    finally:
        try:
            p.stdin.write(json.dumps({"jsonrpc": "2.0", "id": 2,
                                      "method": "shutdown"}) + "\n")
            p.stdin.flush()
            p.wait(timeout=10)
        except Exception:                           # noqa: BLE001
            p.kill()


def main():
    print("=" * 68)
    print("包版本读取 fail-closed（v21-R1）")
    print("=" * 68)
    tmp = tempfile.mkdtemp(prefix="v21r1_pkg_")
    try:
        root = _mk_pkg_root(tmp, "pkg")
        mods = ("md_cg.mcp_server", "hive.hive_mcp.mcp_server")

        # ---------- [1] 变体矩阵（真实 import + reload） ----------
        print("\n[1] 变体矩阵（16 形态 × 2 模块，真实 import/reload）")
        res = _dry_run(root, VARIANTS)
        for rec, (body, want) in zip(res, VARIANTS):
            for m in mods:
                got = rec["r"].get(m) or ["<缺失>"]
                ok = got[0] == "OK" and got[1] == repr(want) and got[2] == "str"
                check(f"[1] {m.split('.')[0]}：{body!r} → {want!r}（必须 str）", ok,
                      f"got {got!r}")

        # ---------- [2] hive 握手端到端 ----------
        print("\n[2] hive 握手端到端（临时包根 package.json=[1, 2]）")
        bad_root = _mk_pkg_root(tmp, "pkg_bad")
        with open(os.path.join(bad_root, "package.json"), "w", encoding="utf-8") as f:
            f.write("[1, 2]")
        env = dict(os.environ)
        env["PYTHONPATH"] = REPO
        env["PYTHONUTF8"] = "1"
        ver, resp, err = _handshake(bad_root, "hive.hive_mcp.mcp_server", env)
        check("[2] 绿：服务起得来且握手自报回落版本（修前 import 期 AttributeError，无响应）",
              isinstance(ver, str) and ver == "0.1.0",
              f"ver={ver!r} stderr={err!r}")
        check("[2] 绿：serverInfo.version 为字符串（协议要求）",
              isinstance(ver, str), f"{type(ver).__name__}")
        with open(os.path.join(bad_root, "package.json"), "w", encoding="utf-8") as f:
            f.write('{"version": "9.9.9"}')
        ver2, _r2, err2 = _handshake(bad_root, "hive.hive_mcp.mcp_server", env)
        check("[2] 判别力对照：合法 version 时握手自报 9.9.9", ver2 == "9.9.9",
              f"ver={ver2!r} stderr={err2!r}")

        # ---------- [3] md_cg 握手端到端 ----------
        print("\n[3] md_cg 握手端到端（临时包根 + 临时 MDCG_ROOT + 哑令牌/哑密钥）")
        cg_root = os.path.join(tmp, "cg_lib")
        tf = os.path.join(tmp, "_tokens.json")
        tok = tokens.issue("designer", actor="v21r1", path=tf)
        aux = os.path.join(tmp, "auxdir")           # 注：不能叫 aux（Win32 保留设备名）
        os.makedirs(aux, exist_ok=True)
        env2 = dict(os.environ)
        env2.update({"PYTHONPATH": REPO, "PYTHONUTF8": "1",
                     "MDCG_ROOT": cg_root, "MDCG_TOKEN_FILE": tf,
                     "MDCG_TOKEN": tok["token"], "MDCG_MASTER_KEY": DUMMY_KEK,
                     "MDCG_AUX_ROOT": aux, "MDCG_SUSTAIN": "0",
                     "MDCG_SUSTAIN_ENABLED": "0"})
        for k in ("MDCG_LEGACY_ENV_AUTH", "MDCG_CAN_ADMIN", "MDCG_CAN_WRITE",
                  "MDCG_CLEARANCE", "MDCG_ACTOR", "MDCG_LEGACY_ENV_ADMIN"):
            env2.pop(k, None)
        check("[3] 隔离声明：临时库 + 哑令牌 + 哑主密钥",
              os.path.abspath(cg_root).startswith(os.path.abspath(tmp))
              and env2["MDCG_MASTER_KEY"] == "ab" * 32
              and env2["MDCG_TOKEN"] == tok["token"])
        root_bad = _mk_pkg_root(tmp, "pkg_bad2")
        with open(os.path.join(root_bad, "package.json"), "w", encoding="utf-8") as f:
            f.write("[1, 2]")
        ver3, _r3, err3 = _handshake(root_bad, "md_cg.mcp_server", env2)
        check("[3] 绿：md_cg 服务起得来且握手自报回落版本", ver3 == "0.1.0",
              f"ver={ver3!r} stderr={err3!r}")
        check("[3] 绿：握手可用（result 结构完整，证明不是半启动）",
              isinstance(_r3, dict) and (_r3.get("result") or {}).get("serverInfo"),
              str(_r3)[:120])

        # ---------- [4] 不回归：真实包根的版本联动 ----------
        print("\n[4] 不回归：真实 package.json 版本仍被两模块读到")
        from . import mcp_server as mdcg_server
        from hive.hive_mcp import mcp_server as hive_server
        with open(os.path.join(REPO, "package.json"), encoding="utf-8") as f:
            want = json.load(f)["version"]
        check("[4] md_cg SERVER_VERSION == 真实 package.json version",
              mdcg_server.SERVER_VERSION == want,
              f"got {mdcg_server.SERVER_VERSION!r} want {want!r}")
        check("[4] hive SERVER_VERSION == 真实 package.json version",
              hive_server.SERVER_VERSION == want,
              f"got {hive_server.SERVER_VERSION!r} want {want!r}")
        check("[4] 两者均为 str", all(isinstance(x, str) for x in
                                     (mdcg_server.SERVER_VERSION, hive_server.SERVER_VERSION)))
    finally:
        _clean(tmp)

    print("\n" + "=" * 68)
    print(f"PASS={PASS}  FAIL={FAIL}")
    if FAILS:
        print("失败项：" + "；".join(FAILS))
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
