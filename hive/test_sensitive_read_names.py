# -*- coding: utf-8 -*-
"""蜂巢执行器敏感名单守卫（N141：config.local.json / *.token 两类凭据漏检）。

背景：_sensitive_read 名单（exec.py _SENSITIVE_FILE_NAMES + V21-8 族匹配
+ 扩展名后缀族）不含 config.local.json 与 .token 后缀——而 serve 部署的
配置文件恰恰是 hive/config.local.json（serve_start.py DEFAULT_CONFIG），
令牌文件恰恰是 orch.token / designer.token（orch.py tokens 通道）。
默认部署 orch 子任务 workdir=CWD=HIVE_DIR，批次27 scope 覆盖整个 hive/，
子代理 read_file / 编排者 context_files 一句话即可把部署凭据全文读进
上下文外发 HIVE_API_BASE 外部网关，敏感名单是最后一道闸却对两者放行。

修法（最小名单增量）：_SENSITIVE_FILE_NAMES 补 "config.local.json"，
扩展名后缀族补 ".token"（不触碰批次27 scope 语义）。

本测试（哑凭据临时区，测毕清理，绝不触真实令牌库/真实 serve）：
  [A] 单元面：_sensitive_read 对两类文件名直接断言非 None（原因串）
  [B] 实弹面：read_file 通道（scope_roots=None 编排者路径）明文不回显
  [C] 实弹面：context_files 通道（_context_block）skipped 标注不漏正文
  [D] 零回归：config.json / token.txt 不误伤；id_rsa/.env 既有族仍命中
运行：python -X utf8 -m hive.test_sensitive_read_names   （退出码 0 = 全绿）
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import sys
import tempfile
from unittest import mock

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

PASS, FAIL = 0, 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [ok] {name}")
        return
    FAIL += 1
    print(f"  [FAIL] {name}  {detail}")


def _load(mod_name: str, filename: str):
    spec = importlib.util.spec_from_file_location(
        mod_name, os.path.join(_HERE, filename))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ex = _load("hive_exec_sensnames", "exec.py")

# 哑凭据临时区（随机哑密钥，非真实凭据；测毕 rmtree）
AREA = tempfile.mkdtemp(prefix="hive_sensnames_")


def _dummy(name: str, body: str) -> str:
    p = os.path.join(AREA, name)
    with open(p, "w", encoding="utf-8") as f:
        f.write(body)
    return p


CLJ = _dummy("config.local.json",
             '{"api_key": "DUMMY-KEY-not-a-real-credential-0123456789"}')
TOK = _dummy("orch.token", "DUMMY-TOKEN-not-a-real-credential-9876543210")
TOK2 = _dummy("designer.token", "DUMMY-TOKEN-2-not-real-abcdef")
NORM = _dummy("config.json", '{"model": "dummy-model", "no_secret": true}')
TOKTXT = _dummy("token.txt", "plain text named token.txt 不得误伤")

_env = dict(os.environ)
_env.pop("HIVE_READ_ROOTS", None)  # 部署级白名单不干扰本守卫
MARK = "DUMMY"

# ---------------------------------------------------------------- [A] 单元面
with mock.patch.dict(os.environ, _env):
    print("[A] _sensitive_read：两类凭据文件名直接断言命中")
    check("A1 config.local.json → 非 None",
          ex._sensitive_read(os.path.realpath(CLJ)) is not None,
          f"got {ex._sensitive_read(os.path.realpath(CLJ))!r}")
    check("A2 orch.token → 非 None",
          ex._sensitive_read(os.path.realpath(TOK)) is not None,
          f"got {ex._sensitive_read(os.path.realpath(TOK))!r}")
    check("A3 designer.token → 非 None（后缀族非单点名）",
          ex._sensitive_read(os.path.realpath(TOK2)) is not None,
          f"got {ex._sensitive_read(os.path.realpath(TOK2))!r}")
    sub = os.path.join(AREA, "sub")
    os.makedirs(sub, exist_ok=True)
    check("A4 子目录内 x.token → 非 None",
          ex._sensitive_read(os.path.realpath(
              _dummy(os.path.join("sub", "a.token"), "DUMMY-TOKEN-3")))
          is not None)

# ---------------------------------------------------------------- [B] read_file
with mock.patch.dict(os.environ, _env):
    print("[B] 实弹 read_file（scope_roots=None 编排者路径）：凭据明文不回显")
    out = ex.tool_read_file({"path": CLJ}, workdir=AREA, scope_roots=None)
    check("B1 config.local.json → ok=False",
          out.get("ok") is False,
          f"got {json.dumps(out, ensure_ascii=False)[:240]}")
    check("B2 config.local.json 明文不进结果",
          MARK not in json.dumps(out, ensure_ascii=False),
          f"got {json.dumps(out, ensure_ascii=False)[:240]}")
    out = ex.tool_read_file({"path": TOK}, workdir=AREA, scope_roots=None)
    check("B3 orch.token → ok=False 且明文不回显",
          out.get("ok") is False
          and MARK not in json.dumps(out, ensure_ascii=False),
          f"got {json.dumps(out, ensure_ascii=False)[:240]}")
    # worker 身份路径（scope 覆盖整个 AREA，模拟默认部署 workdir=CWD）
    out = ex.tool_read_file({"path": TOK}, workdir=AREA,
                            scope_roots=(os.path.realpath(AREA),))
    check("B4 worker scope 内 orch.token 仍被敏感闸拒读",
          out.get("ok") is False and "敏感" in (out.get("error") or ""),
          f"got {json.dumps(out, ensure_ascii=False)[:240]}")

# ---------------------------------------------------------------- [C] context_files
with mock.patch.dict(os.environ, _env):
    print("[C] 实弹 context_files（_context_block）：skipped 标注不漏正文")
    meta = {"notes": [], "images": 0, "image_tokens": 0, "binaries": 0}
    blk = ex._context_block("config.local.json", CLJ, "job_guard", meta)
    check("C1 config.local.json → skipped 标注块",
          'skipped="敏感凭据拒读"' in blk,
          f"got {blk[:200]!r}")
    check("C2 config.local.json 明文不进块",
          MARK not in blk, f"got {blk[:200]!r}")
    meta2 = {"notes": [], "images": 0, "image_tokens": 0, "binaries": 0}
    blk2 = ex._context_block("orch.token", TOK, "job_guard", meta2)
    check("C3 orch.token → skipped 标注块且明文不进块",
          'skipped="敏感凭据拒读"' in blk2 and MARK not in blk2,
          f"got {blk2[:200]!r}")

# ---------------------------------------------------------------- [D] 零回归
with mock.patch.dict(os.environ, _env):
    print("[D] 零回归：不误伤 + 既有族仍命中")
    out = ex.tool_read_file({"path": NORM}, workdir=AREA, scope_roots=None)
    check("D1 config.json（非 local）正常读（ok=True）",
          out.get("ok") is True, f"got {json.dumps(out, ensure_ascii=False)[:240]}")
    out = ex.tool_read_file({"path": TOKTXT}, workdir=AREA, scope_roots=None)
    check("D2 token.txt（非 .token 后缀）正常读（ok=True）",
          out.get("ok") is True, f"got {json.dumps(out, ensure_ascii=False)[:240]}")
    check("D3 id_rsa 既有族仍命中",
          ex._sensitive_read(os.path.realpath(_dummy("id_rsa", "x")))
          is not None)
    check("D4 prod.env 既有族仍命中",
          ex._sensitive_read(os.path.realpath(_dummy("prod.env", "x")))
          is not None)
    check("D5 server.pem 既有族仍命中",
          ex._sensitive_read(os.path.realpath(_dummy("server.pem", "x")))
          is not None)

shutil.rmtree(AREA, ignore_errors=True)
print(f"\n结果: {PASS} pass / {FAIL} fail")
sys.exit(0 if FAIL == 0 else 1)
