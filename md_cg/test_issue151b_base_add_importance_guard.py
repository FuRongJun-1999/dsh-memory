# -*- coding: utf-8 -*-
r"""#151② 守卫：基类 `MdCG.add` 的 importance/confidence **有限性 + 范围**守卫。

缺陷形态（复现于 HEAD d29a8436）：
  子类 `mdcos.MdCGOS.add` 早已有回落式守卫（#151a），但**基类 `MdCG.add`
  仍裸存**——直接实例化 `MdCG`（bench / 迁移 / 脚本 / 测试面大量存在）时：
    · `add(importance=inf)` ⇒ `float("inf") >= protect.AUTO_PROTECT_IMPORTANCE`
      恒真 ⇒ 节点被打上**不可遗忘保护**且永久霸榜（inf 参与任何加权仍是 inf）；
    · `add(importance=nan)` ⇒ `nan >= x` 恒假、`nan` 参与排序恒 False ⇒
      结果**不可复现**，且事后无法从读数区分。

修法（本件）：`MdCG.add` 入口（node_id 校验之后）加 finite + [0,1] 守卫，
非法即 **fail-closed 拒写**（结构化 ValueError），范式抄同仓 `reach._ttl()`
（特征串 `if not math.isfinite(v) or v <= 0:`，注释明写「非有限视同非法」）。

判据组：
  A 拒绝面（A 组在 HEAD 上应红）：
      A1 add(importance=inf) 被拒（ValueError）
      A2 add(importance=nan) 被拒
      A3 add(importance=-inf) 被拒
      A4 add(importance=2.0) 被拒（越上界）
      A5 add(importance=-1.0) 被拒（越下界）
      A6 add(confidence=inf) 被拒（同族字段一并守）
      A7 拒绝后**盘面零写入**（坏值不得半途落盘）
  B 正对照：
      B1 add(importance=0.5) 正常写入且 fm 读数 0.5
      B2 add(importance=0.0) / add(importance=1.0) 边界合法
      B3 拒绝只发生在基类入口——子类 MdCGOS 的**回落**语义一字不变
         （nan ⇒ 回落 0.5，不抛）
  C 源码级 pin（防「判据被摘掉」的静默回归）：
      C1 mdcg.py 内含 finite/范围守卫块（特征串在场）
      C2 守卫位置在 `def add(` 之后、`_maybe_reload_index` 之前（入口处）

定点变异（`--mutate=noguard`）：把 finite/范围判据恒真 ⇒ A 组必红。

用法：
  python -X utf8 -m md_cg.test_issue151b_base_add_importance_guard
  python -X utf8 -m md_cg.test_issue151b_base_add_importance_guard --mutate=noguard
退出码：0 = 全绿；1 = 有失败。
"""
from __future__ import annotations

import math
import os
import shutil
import sys
import tempfile

PASS = 0
FAIL = 0
FAILS = []

BODY = ("# 功能名：有限性守卫对照\n# 生效条件：沙箱\n# 子功能：对照\n"
        "# 执行：写\n# 验证方式：守卫\n# 不适用条件：无\n正文\n")


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


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    mut = ""
    for a in argv:
        if a.startswith("--mutate="):
            mut = a.split("=", 1)[1]

    from md_cg import mdcg as _M
    from md_cg.mdcg import MdCG
    from md_cg.mdcos import MdCGOS

    _orig_req = _M._require_unit_number
    if mut == "noguard":
        # 等价注入：把写侧数值守卫单点换成「恒不拒」（抽掉 finite + 范围两段）
        _M._require_unit_number = lambda field, value: float(value)

    sb = tempfile.mkdtemp(prefix="iss151b_")
    sb2 = tempfile.mkdtemp(prefix="iss151b_os_")
    try:
        cg = MdCG(os.path.join(sb, "lib"), autoflush=1)

        def _try(nid, **kw):
            try:
                cg.add(nid, BODY, layer="knowledge", **kw)
                return None
            except ValueError as exc:
                return str(exc)

        print("\n[A] 基类 add 的非法数值一律拒写（fail-closed）")
        cases = [
            ("A1", "inf", "importance", {"importance": float("inf")}),
            ("A2", "nan", "importance", {"importance": float("nan")}),
            ("A3", "-inf", "importance", {"importance": float("-inf")}),
            ("A4", "2.0", "importance", {"importance": 2.0}),
            ("A5", "-1.0", "importance", {"importance": -1.0}),
            ("A6", "confidence=inf", "confidence",
             {"confidence": float("inf")}),
        ]
        for tag, label, field, kw in cases:
            e = _try("bad_%s" % tag, **kw)
            ok(e is not None and field in e,
               "%s add(%s) 被拒（ValueError 点名字段）" % (tag, label), e)
        # A7：坏值不得半途落盘
        on_disk = []
        for dp, _dn, fn in os.walk(os.path.join(sb, "lib")):
            on_disk.extend(fn)
        ok(not [f for f in on_disk if f.startswith("bad_")],
           "A7 拒绝后盘面零写入（坏值不得半途落盘）", on_disk)

        print("\n[B] 正对照：合法值与子类回落语义")
        cg.add("ok_half", BODY, layer="knowledge", importance=0.5)
        f = (cg.get("ok_half") or {}).get("frontmatter") or {}
        ok(abs(float(f.get("importance")) - 0.5) < 1e-9,
           "B1 add(0.5) 正常写入且 fm 读数 0.5", f.get("importance"))
        cg.add("ok_lo", BODY, layer="knowledge", importance=0.0)
        cg.add("ok_hi", BODY, layer="knowledge", importance=1.0)
        ok((cg.get("ok_lo") or {}).get("frontmatter", {}).get("importance") == 0.0
           and (cg.get("ok_hi") or {}).get("frontmatter", {}).get("importance") == 1.0,
           "B2 边界 0.0 / 1.0 合法")
        cgos = MdCGOS(os.path.join(sb2, "lib"), autoflush=1)
        cgos.add("os_nan", BODY, layer="knowledge",
                 importance=float("nan"), confidence=float("nan"))
        _of = (cgos.get("os_nan") or {}).get("frontmatter") or {}
        _oi = _of.get("importance")
        ok(_oi is not None and math.isfinite(float(_oi))
           and abs(float(_oi) - 0.5) < 1e-9,
           "B3 子类 MdCGOS 回落语义一字不变（nan ⇒ 0.5，不抛）", _oi)

        print("\n[C] 源码级 pin")
        _src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                 "mdcg.py"), encoding="utf-8").read()
        _pin = ("if not math.isfinite(v) or not (0.0 <= v <= 1.0):" in _src
                and "def _require_unit_number(field, value) -> float:" in _src)
        if mut == "noguard":
            _pin = False
        ok(_pin, "C1 mdcg.py 内含 finite + [0,1] 守卫单点（特征串在场）")
        _i_add = _src.find("    def add(self, node_id: str, content: str,")
        _i_guard = _src.find('_require_unit_number("importance", importance)')
        _i_reload = _src.find("self._maybe_reload_index()", _i_add)
        ok(0 <= _i_add < _i_guard < _i_reload,
           "C2 守卫位于 add 入口（node_id 校验后、_maybe_reload_index 前）",
           (_i_add, _i_guard, _i_reload))
    finally:
        _M._require_unit_number = _orig_req
        for _d in (sb, sb2):
            shutil.rmtree(_d, ignore_errors=True)

    print("\n通过 %d / 失败 %d%s"
          % (PASS, FAIL, ("（变异=%s）" % mut) if mut else ""))
    for f in FAILS:
        print(" - 红：%s" % f)
    return 1 if FAIL else 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
