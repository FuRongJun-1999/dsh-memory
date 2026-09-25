# -*- coding: utf-8 -*-
"""蜂巢执行器 worker 读白名单守卫（_worker_scope 单串切分缺陷，2026-09-25）。

背景：_worker_scope 对 spec.read_roots 单串形态 `list(s)` 逐字符切分——
docstring 声称的「列表/单串」双形态中单串完全失效；切出的单字符 '\\'
经 realpath 归一为**当前盘根**混入 scope_roots，worker 读白名单被意外
扩到全盘（read_file 可读盘内任意文件），仅剩 _sensitive_read 凭据
形态一道防线。实测：_worker_scope(None, {read_roots:'C:\\custom\\scope'})
返回 11 个垃圾根含盘根 D:\\；以该组 roots 读仓外哑探针 → ok=True 全文回显。

修法（最小两行）：单串包一层 [s] 再进归一循环——单串入 → 单根出。

本测试：
  [A] 单元面：单串恰出一根（无盘根/无垃圾根）+ 列表/缺省/None 零回归
  [B] 实弹面：仓外哑探针（同盘、scope 外）——旧形态盘根混入可读、
      修复后拒读；scope 内正常读与空 tuple fail-closed 对照
运行：python -X utf8 -m hive.test_worker_scope   （退出码 0 = 全绿）
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


ex = _load("hive_exec_scopeguard", "exec.py")

SCOPE_DIR = tempfile.mkdtemp(prefix="hive_scope_dir_")          # 白名单定制目录
PROBE_AREA = tempfile.mkdtemp(prefix="hive_scope_probe_",
                               dir=os.path.dirname(_REPO))       # 仓外、同盘
PROBE = os.path.join(PROBE_AREA, "probe.txt")
with open(PROBE, "w", encoding="utf-8") as f:
    f.write("SCOPE_PROBE_MARKER_XY 不含凭据形态的哑标记正文\n")

DRIVE_ROOT = os.path.realpath("/")  # 当前盘根（win: D:\；posix: /）

# ---------------------------------------------------------------- [A] 单元面
print("[A] _worker_scope：单串恰出一根（无盘根/无垃圾根）")
r = ex._worker_scope(None, {"read_roots": SCOPE_DIR})
check("A1 单串入 → 恰出一根（== realpath(该串)）",
      r == (os.path.realpath(SCOPE_DIR),),
      f"got {len(r)} 根: {r}")
check("A2 返回不含当前盘根（旧缺陷：单字符 '\\' 归一混入）",
      DRIVE_ROOT not in r, f"盘根 {DRIVE_ROOT} in {r}")
inner = os.path.join(SCOPE_DIR, "sub")
os.makedirs(inner, exist_ok=True)
r = ex._worker_scope(None, {"read_roots": [SCOPE_DIR, inner]})
check("A3 列表形态零回归（两根去重归一）",
      r == (os.path.realpath(SCOPE_DIR), os.path.realpath(inner)),
      f"got {r}")
r = ex._worker_scope("/tmp/jobx", {"workdir": SCOPE_DIR})
check("A4 缺省 read_roots 零回归（job_dir+workdir）",
      r == (os.path.realpath("/tmp/jobx"), os.path.realpath(SCOPE_DIR)),
      f"got {r}")
r = ex._worker_scope(None, {"read_roots": ["", "   ", None]})
check("A5 空串/空白/None 项被过滤（空 tuple）", r == (), f"got {r}")

# ---------------------------------------------------------------- [B] 实弹面
print("[B] 实弹：仓外哑探针（同盘、scope 外）——盘根不得混入放行")
_env = dict(os.environ)
_env.pop("HIVE_READ_ROOTS", None)  # 部署级白名单不干扰本守卫
with mock.patch.dict(os.environ, _env):
    roots = ex._worker_scope(None, {"read_roots": SCOPE_DIR})
    out = ex.tool_read_file({"path": PROBE}, workdir=None,
                            scope_roots=roots)
    check("B1 探针在 scope 外（单串形态）→ 拒读（旧缺陷 ok=True 回显）",
          out.get("ok") is False
          and "SCOPE_PROBE_MARKER_XY" not in json.dumps(out, ensure_ascii=False),
          f"roots={roots} got {json.dumps(out, ensure_ascii=False)[:240]}")
    inside = os.path.join(SCOPE_DIR, "inside.txt")
    with open(inside, "w", encoding="utf-8") as f:
        f.write("SCOPE_INSIDE_OK_XY 白名单内正常读\n")
    out = ex.tool_read_file({"path": inside}, workdir=None,
                            scope_roots=roots)
    check("B2 白名单内正常读零回归（ok=True）",
          out.get("ok") is True and "SCOPE_INSIDE_OK_XY" in (out.get("content") or ""),
          f"got {json.dumps(out, ensure_ascii=False)[:240]}")
    out = ex.tool_read_file({"path": PROBE}, workdir=None, scope_roots=())
    check("B3 空 tuple fail-closed 对照（既有行为零回归）",
          out.get("ok") is False, f"got {json.dumps(out, ensure_ascii=False)[:240]}")
    roots_list = ex._worker_scope(None, {"read_roots": [SCOPE_DIR]})
    out = ex.tool_read_file({"path": PROBE}, workdir=None,
                            scope_roots=roots_list)
    check("B4 列表形态探针拒读零回归",
          out.get("ok") is False, f"roots={roots_list}")

shutil.rmtree(SCOPE_DIR, ignore_errors=True)
shutil.rmtree(PROBE_AREA, ignore_errors=True)
print(f"\n结果: {PASS} pass / {FAIL} fail")
sys.exit(0 if FAIL == 0 else 1)
