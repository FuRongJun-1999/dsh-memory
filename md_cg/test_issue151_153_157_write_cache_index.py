# -*- coding: utf-8 -*-
r"""守卫 · #151 + #152 + #153（写入有限性 / 缓存面失效 / 缓存键消歧）。

判据：
  A1 #151b JSON-RPC 解析拒 NaN/Infinity：生产源码里 JSON-RPC 的 json.loads
     必须带 parse_constant（源码级 pin）+ 等价行为对照（默认接受 ⇒ 非标准值能进写入面）
  A2 #151a add() 有限性/范围守卫：NaN / ±Infinity / 越界值 ⇒ 回落文档缺省（有限）；
     正对照：合法值 0.8 原样保留
  A3 #152 lock()/unlock() 清 readcache 且失效 hotcache（调用记录判据）
  A4 #153 _canon 的 dict 分支用三元组 ⇒ 与 list-of-pairs 不再撞键；且稳定可复现
运行：
  python -X utf8 -m md_cg.test_issue151_153_157_write_cache_index
  python -X utf8 -m md_cg.test_issue151_153_157_write_cache_index --mutate=nanadd
  python -X utf8 -m md_cg.test_issue151_153_157_write_cache_index --mutate=canon
  python -X utf8 -m md_cg.test_issue151_153_157_write_cache_index --mutate=srcpin
"""
from __future__ import annotations

import json
import math
import os
import shutil
import sys
import tempfile
import types

PASS = 0
FAIL = 0
FAILS = []


def ok(cond, label, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        FAILS.append(label)
    print("  [%s] %s%s" % ("PASS" if cond else "FAIL", label,
                           ("  · " + str(detail)) if detail else ""))
    return bool(cond)


def _here():
    return os.path.dirname(os.path.abspath(__file__))


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    mut = ""
    for a in argv:
        if a.startswith("--mutate="):
            mut = a.split("=", 1)[1]
    from md_cg import mdcos, hotcache
    from md_cg.mdcos import MdCGOS

    # ---- A1 #151b：JSON-RPC 解析拒 NaN/Infinity ----
    src = open(os.path.join(_here(), "mcp_server.py"), encoding="utf-8").read()
    pin = "json.loads(line, parse_constant=_reject_const)" in src
    if mut == "srcpin":
        pin = pin and False          # 变异：把 pin 判据当「实现被摘掉」
    ok(pin, "A1a 源码级 pin：JSON-RPC 的 json.loads 带 parse_constant", pin)
    lax = json.loads('{"importance": NaN}')          # 默认（非标准扩展）
    strict_raised = False
    try:
        json.loads('{"importance": NaN}',
                   parse_constant=lambda s: (_ for _ in ()).throw(ValueError(s)))
    except ValueError:
        strict_raised = True
    ok((not math.isfinite(lax["importance"])) and strict_raised,
       "A1b 行为对照：默认接受 NaN（可污染写入面）/ parse_constant 拒收",
       (lax["importance"], strict_raised))

    # ---- A2 #151a：add() 有限性守卫 ----
    sb = tempfile.mkdtemp(prefix="iss151_")   # 系统 temp：追踪面禁写本机路径
    try:
        cg = MdCGOS(os.path.join(sb, "lib"), autoflush=1)
        if mut == "nanadd":                                   # 变异：摘掉守卫
            mdcos.math = types.SimpleNamespace(isfinite=lambda x: True)
        def imp(nid, v):
            cg.add(nid, "# 功能名：%s\n\n# 生效条件：x\n正文\n" % nid, layer="knowledge",
                   importance=v, confidence=v)
            f = (cg.get(nid) or {}).get("frontmatter") or {}
            return f.get("importance"), f.get("confidence")
        bad_vals = [float("nan"), float("inf"), float("-inf"), 2.0, -1.0]
        ok_all = True
        for i, v in enumerate(bad_vals):
            a, b = imp("nan%d" % i, v)
            good = (a is not None and math.isfinite(a) and 0.0 <= a <= 1.0
                    and b is not None and math.isfinite(b))
            ok_all = ok_all and good
        ok(ok_all, "A2 NaN/±Inf/越界 ⇒ 回落文档缺省（有限且可排序）", (a, b))
        _msrc = open(os.path.join(_here(), "mdcos.py"), encoding="utf-8").read()
        _pin2 = 'for _k, _dflt in (("importance", 0.5), ("confidence", 0.6)):' in _msrc
        if mut == "nanadd":      # 变异：把守卫块当「已被摘掉」
            _pin2 = False
        ok(_pin2, "A2c 源码级 pin：add() 内的有限性/范围守卫块在场（与运行面 A2 互为双证）")
        a8, _b8 = imp("ok_value", 0.8)
        ok(abs((a8 if a8 is not None else -1) - 0.8) < 1e-9,
           "A2b 正对照：合法值 0.8 原样保留", a8)
    finally:
        shutil.rmtree(sb, ignore_errors=True)

    # ---- A3 #152：lock/unlock 清缓存（调用记录判据） ----
    from md_cg import readcache
    calls = {"read": 0, "hot": 0}
    _rc, _hc = readcache.clear, hotcache.invalidate
    if mut != "lockcache":
        readcache.clear = lambda cg: (calls.__setitem__("read", calls["read"] + 1), 0)[1]
        hotcache.invalidate = lambda cg, node_id=None: calls.__setitem__("hot", calls["hot"] + 1)
    try:
        from md_cg.security import Principal
        from md_cg.mdcos import MdCGSecure
        sb2 = tempfile.mkdtemp(prefix="iss152_")   # 同上
        try:
            sec = MdCGSecure(sb2, principal=Principal(tenant="t", actor="a",
                             clearance="secret", can_write=True, can_admin=True),
                             master_key=os.urandom(32))
            sec.lock()
            sec.unlock(os.urandom(32))
            expect = 2 if mut != "lockcache" else 0
            ok(calls["read"] == expect and calls["hot"] == expect,
               "A3 lock()+unlock() 各清一次 readcache 与 hotcache", dict(calls))
        finally:
            shutil.rmtree(sb2, ignore_errors=True)
    finally:
        readcache.clear, hotcache.invalidate = _rc, _hc

    # ---- A4 #153：_canon dict 分支三元组 ----
    if mut == "canon":                                        # 变异：dict 分支退回二元组
        _real_canon = hotcache.HotCache._canon

        def _pre_canon(v):
            if isinstance(v, dict):
                return tuple(sorted((str(k), _real_canon(x)) for k, x in v.items()))
            return _real_canon(v)

        hotcache.HotCache._canon = staticmethod(_pre_canon)
    c_dict = hotcache.HotCache._canon({"a": 1})
    c_list = hotcache.HotCache._canon([("a", 1)])
    ok(c_dict != c_list, "A4 dict 与 list-of-pairs 的 canon 不再撞键", (c_dict, c_list))
    ok(hotcache.HotCache._canon({"a": 1}) == c_dict, "A4b canon 稳定可复现")

    print("\nissue151_153_157: %d pass / %d fail%s"
          % (PASS, FAIL, ("（变异=%s）" % mut) if mut else ""))
    for f in FAILS:
        print(" - 红：%s" % f)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())