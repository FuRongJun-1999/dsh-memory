#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""#109 守卫：写入工具的**返回语义**——ok 与 committed 同真值，「已受理待审」由 status 显式标注。

缺陷（作者 #109）：同一 node_id 二次写入不同正文时判 C 类（改写），缺省自治级别下服务端返回
`{"ok": true, "committed": false, "moved_to": "review_queue", "pid": "prop_…"}`：**正文未落盘**
（盘面仍是先到者，新正文入 `hippocampus/inbox.jsonl`），但 `ok=True` ⇒ 只判 ok 的调用方把
「转投待审」计成「已入库」（作者实测 8,146 轮里命中 40 次：`_audit.jsonl` `op=add 8113` / `op=propose 40`）。

契约（本批统一，跨 tier 收口）：
  · 已落盘      ok=True,  committed=True
  · 已受理待审  ok=False, committed=False, status="pending_review"（moved_to 说明去向）
  · 被拒/未受理 ok=False, committed=False, moved_to="rejected"/"autonomy_forbidden"/…
仓内先例：冲突闸 `writepipe._gate_consistency` 早已是 ok=False + moved_to="review_queue"，本条是把
其余同形返回体对齐到该先例（按不变量收口，不新增语义）。对应的已知有意变更声明见
`md_cg/test_mode_parity.py` 的 `_KNOWN_QUEUE_CONTRACT`，其「在场断言」与本件互为守卫。

用法：
  python -X utf8 -m md_cg.test_i109_ok_contract
  python -X utf8 -m md_cg.test_i109_ok_contract --mutate   # 定点变异：把直写分支改回旧契约，期望本守卫转红
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True

from . import mcp_server                                   # noqa: E402
from . import autonomy_modes as _am                        # noqa: E402
from .mdcos import MdCGOS                                  # noqa: E402

PLAIN = ("# 功能名：返回契约探针\n# 生效条件：全时窗\n# 子功能：无\n"
         "# 执行：%s\n# 验证方式：test\n# 不适用条件：无\n")
R = []


def check(name, cond, got=""):
    R.append(bool(cond))
    print("%s  %s%s" % ("PASS" if cond else "FAIL", name,
                        ("  ← " + str(got)[:150]) if got != "" else ""))


#: 档位 env 名的**单一真源**（仓内 G 组纪律：带引号的字面量只许出现在 autonomy_modes.py）
_ENV_MODE = _am.AUTONOMY_ENV_KEYS["mode"]


class _Mode:
    """临时设档位（与既有 test_autonomy_modes 同口径：经单一真源取名），退出即还原。"""

    def __init__(self, mode):
        self.mode = mode

    def __enter__(self):
        self.old = os.environ.get(_ENV_MODE)
        os.environ[_ENV_MODE] = self.mode
        return self

    def __exit__(self, *exc):
        if self.old is None:
            os.environ.pop(_ENV_MODE, None)
        else:
            os.environ[_ENV_MODE] = self.old
        return False


def _lib(tag):
    root = tempfile.mkdtemp(prefix="i109_%s_" % tag)
    assert os.path.realpath(root).startswith(os.path.realpath(tempfile.gettempdir())), root
    return MdCGOS(root)


def _direct(mode, tag, first, second):
    """直写面（mdcg_remember 非 gated）两写：先 A 新增，再同 id 改写。"""
    with _Mode(mode):
        cg = _lib(tag)
        o1 = mcp_server._dispatch(cg, "mdcg_remember",
                                  {"content": PLAIN % first, "node_id": "ud_c",
                                   "layer": "knowledge"})
        cg.flush()
        o2 = mcp_server._dispatch(cg, "mdcg_remember",
                                  {"content": PLAIN % second, "node_id": "ud_c",
                                   "layer": "knowledge"})
        body = (cg.get("ud_c") or {}).get("content") or ""
        orders = cg.review_list()
        cg.close()
        return o1, o2, body, orders


def main():
    print("== #109 返回契约守卫（ok 与 committed 同真值；入队须有 status）==")

    # ---- G1/G2/G3：作者 #109 的原复现路径（缺省自治=confirm）----
    o1, o2, body, orders = _direct(None if False else "confirm", "confirm", "初版", "改写版")
    check("G1 A 新增真落盘：ok=True 且 committed=True",
          o1.get("ok") is True and o1.get("committed") is True,
          {k: o1.get(k) for k in ("ok", "committed", "moved_to")})
    check("G2 C 改写（confirm 档）返回已受理待审：ok=False + committed=False + "
          "moved_to=review_queue + status=pending_review + pid",
          o2.get("ok") is False and o2.get("committed") is False
          and o2.get("moved_to") == "review_queue"
          and o2.get("status") == "pending_review" and bool(o2.get("pid")),
          {k: o2.get(k) for k in ("ok", "committed", "moved_to", "status", "pid")})
    check("G3 未提交为实：盘面仍是先到者正文（改写版未落盘）+ 队列恰 1 张",
          "改写版" not in body and "初版" in body and len(orders) == 1,
          {"body_head": body[:28], "orders": len(orders)})

    # ---- G4 不变量：三档直写面的入队返回体口径一致 ----
    bad = []
    for mode in ("plan", "confirm"):
        _, o, _b, _ = _direct(mode, "inv_%s" % mode, "初版", "改写版")
        mv = o.get("moved_to")
        rec = {k: o.get(k) for k in ("ok", "committed", "status", "moved_to")}
        if mv == "review_queue":
            # 入队面：ok 与 committed 同真值，且 status 显式标注去向
            if not (o.get("ok") is False and o.get("committed") is False
                    and o.get("status") == "pending_review"):
                bad.append((mode, rec))
        else:
            # 非入队面（plan 档的 C 是 fail-closed 的 FORBID）：ok=False 且不得带 pending 状态
            if not (o.get("ok") is False and o.get("committed") is False
                    and not o.get("status")):
                bad.append((mode, rec))
    check("G4 不变量：入队面一律 ok=False + status=pending_review；非入队面 ok=False 且无 "
          "pending 状态（plan 档 C 为 fail-closed，moved_to=autonomy_forbidden）",
          not bad, bad)

    # ---- G5 对照：full 档真落盘，不得误伤放行面 ----
    o1f, o2f, bodyf, _ = _direct("full", "full", "初版", "改写版")
    check("G5 对照 full 档 C 改写真落盘：ok=True 且 committed=True 且 moved_to 为空、盘面已改写",
          o2f.get("ok") is True and o2f.get("committed") is True
          and not o2f.get("moved_to") and "改写版" in bodyf,
          {k: o2f.get(k) for k in ("ok", "committed", "moved_to")})

    # ---- G6 枚举自证：仓内不再存在「committed=False 却 ok=True」的入队返回体 ----
    import io
    import re
    here = os.path.dirname(os.path.abspath(__file__))
    offenders = []
    for fn in ("writepipe.py", "mdcos.py", "mcp_server.py", "goal_gen.py"):
        src = io.open(os.path.join(here, fn), encoding="utf-8").read()
        for m in re.finditer(r'\{"ok": True[^}]*?moved_to": "review_queue"', src, re.S):
            offenders.append("%s:%d" % (fn, src[:m.start()].count("\n") + 1))
    check("G6 枚举自证：全包无「ok=True + moved_to=review_queue」返回体（五处已收口）",
          not offenders, offenders)

    print("\n#109 返回契约守卫：%d 通过，%d 失败" % (sum(R), len(R) - sum(R)))
    return 0 if all(R) else 1


# --- 定点变异：把**作者报的那条路径**（mcp_server 直写分支）改回旧契约，期望本守卫转红 ---
_MUT_OLD = ('            return {"ok": False, "id": nid, "committed": False,\n'
            '                    "moved_to": "review_queue", "status": "pending_review",\n')
_MUT_NEW = ('            return {"ok": True, "id": nid, "committed": False,\n'
            '                    "moved_to": "review_queue",\n')


def mutate():
    pkg = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # 仓库根
    tmp = tempfile.mkdtemp(prefix="i109_mut_")
    dst = os.path.join(tmp, "pkg")
    shutil.copytree(os.path.join(pkg, "md_cg"), os.path.join(dst, "md_cg"),
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    # 顶层 *.py 必须一并带上（md_cg 依赖仓库根的 utf8_boot 等），否则副本 import 失败
    # 会被误判成「守卫转红」——那是装置缺陷，不是变异成立。
    for fn in os.listdir(pkg):
        if fn.endswith(".py"):
            shutil.copy2(os.path.join(pkg, fn), os.path.join(dst, fn))
    tgt = os.path.join(dst, "md_cg", "mcp_server.py")
    t = open(tgt, encoding="utf-8").read()
    if t.count(_MUT_OLD) != 1:
        print("MUTATE-SKIP：锚点未命中（源码结构与预期不同，勿盲改）")
        return 2
    open(tgt, "w", encoding="utf-8", newline="").write(t.replace(_MUT_OLD, _MUT_NEW, 1))
    p = subprocess.run([sys.executable, "-X", "utf8", "-B", "-m",
                        "md_cg.test_i109_ok_contract"],
                       cwd=dst, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=600)
    red = [l for l in (p.stdout or "").splitlines() if l.startswith("FAIL")]
    tail = [l for l in (p.stdout or "").splitlines() if "失败" in l or "通过" in l]
    print("\n--- 定点变异（直写分支改回旧契约后重跑本守卫）---")
    print("退出码 =", p.returncode, "| FAIL 行数 =", len(red), "| 汇总行 =", tail[-1:])
    for l in red[:6]:
        print("   " + l[:150])
    if not red and (p.stderr or "").strip():
        print("   [stderr] " + (p.stderr or "").strip()[-400:])
    print("变异判定：", "PASS（注入必失败 ⇒ 守卫转红并点名）"
          if (p.returncode != 0 and red) else "FAIL（守卫对契约回退不敏感）")
    shutil.rmtree(tmp, ignore_errors=True)
    return 0 if (p.returncode != 0 and red) else 1


if __name__ == "__main__":
    raise SystemExit(mutate() if "--mutate" in sys.argv else main())
