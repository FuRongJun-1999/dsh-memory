# -*- coding: utf-8 -*-
"""test_server_version.py · SERVER_VERSION 与包版本联动守卫（issue #42）

根因：md_cg/mcp_server.py 与 hive/hive_mcp/mcp_server.py 的 SERVER_VERSION
硬编码 "0.1.0"，从未随发版联动——MCP 握手 serverInfo.version 向客户端自报
假版本（外部用户实测：包 0.5.1 握手自报 0.1.0）。
修复：SERVER_VERSION 改为 _package_version() 动态读包根 package.json。

守卫断言：
  ① md_cg.SERVER_VERSION == package.json 的 version（动态联动）
  ② hive_mcp.SERVER_VERSION == 同一 package.json version（同族同源）
  ③ 两值 != "0.1.0"（防回退硬编码——当前发布版本必非 0.1.0）
  ④ _package_version 对坏路径回落 "0.1.0" 不抛（保底契约）
"""
import json
import os
import sys
import unittest.mock as mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PASS = 0
FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [ok] {name}")
    else:
        FAIL += 1
        print(f"  [✘] {name}  {detail}")


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
with open(os.path.join(ROOT, "package.json"), encoding="utf-8") as f:
    PKG_VERSION = json.load(f).get("version")

print(f"== 包版本基准: {PKG_VERSION} ==")

# ①② 动态联动
from md_cg import mcp_server as mdcg_server  # noqa: E402
from hive.hive_mcp import mcp_server as hive_server  # noqa: E402

check("① md_cg SERVER_VERSION == package.json version",
      mdcg_server.SERVER_VERSION == PKG_VERSION,
      f"got {mdcg_server.SERVER_VERSION!r} want {PKG_VERSION!r}")
check("② hive SERVER_VERSION == package.json version",
      hive_server.SERVER_VERSION == PKG_VERSION,
      f"got {hive_server.SERVER_VERSION!r} want {PKG_VERSION!r}")

# ③ 防硬编码回退（issue #42 的 0.1.0 即硬编码脱节形态）
check("③ 两值均非硬编码 0.1.0",
      mdcg_server.SERVER_VERSION != "0.1.0" and hive_server.SERVER_VERSION != "0.1.0",
      "出现 0.1.0 说明动态读取失效回退")

# ④ 回落保底契约：读 package.json 失败 → "0.1.0" 不抛（保底不阻塞启动）
try:
    with mock.patch("builtins.open", side_effect=OSError("deny")):
        v = mdcg_server._package_version()
    check("④ _package_version 读取失败回落 0.1.0 不抛", v == "0.1.0", f"got {v!r}")
except Exception as e:  # noqa: BLE001
    check("④ _package_version 读取失败回落 0.1.0 不抛", False, f"raised {e!r}")

print(f"== 结果: {PASS} 通过 / {FAIL} 失败 ==")
sys.exit(1 if FAIL else 0)
