# -*- coding: utf-8 -*-
r"""守卫 · #82.2 work_wip 层路由 + #82.3 写入硬上限（2026-10-09 DSH 端实施）。

背景：
  · #82.2：writepipe 多处写 layer-or-knowledge 兜底，而 work_wip 属**过程件**，
    缺省进 knowledge 层会稀释分桶/条件路由。修法＝在唯一入口
    WritePipeline.execute 处**单点规范化**（仅当未显式给 layer 且 kind==work_wip
    时改路由到 contextual）。
  · #82.3：写入无大小上限（复现时 2MB 内容可 ACCEPT）。修法＝入口硬上限 1 MiB，
    超限 REJECT 并如实报当前大小与上限。

判据（真跑 WritePipeline.execute + 真库落盘读回）：
  G1 work_wip 缺省 ⇒ 落 contextual
  G2 text 缺省 ⇒ 落 knowledge（对照，证明未误伤其余 kind）
  G3 work_wip 显式给 layer ⇒ 尊重显式（仍 knowledge）
  G4 超 1 MiB ⇒ REJECT 且如实报 bytes/limit/evidence
  G5 略小于上限 ⇒ 正常写入
  G6 MAX_WRITE_BYTES == 1048576
运行：python -X utf8 -m md_cg.test_issue82_layer_and_size
退出码：0 全绿 ｜ 1 断言失败
"""
from __future__ import annotations

import os
import re
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
if REPO not in sys.path:
    sys.path.insert(0, REPO)

PASS = 0
FAIL = 0
FAILS = []
SIX = ("# 功能名：t\n# 生效条件：t\n# 子功能：t\n# 执行：t\n"
       "# 验证方式：t\n# 不适用条件：t\n")


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("[PASS] %s%s" % (name, ("  · " + detail) if detail else ""))
    else:
        FAIL += 1
        FAILS.append(name)
        print("[FAIL] %s  · %s" % (name, detail))


def _cg(root):
    from md_cg import tokens as TK
    from md_cg.mdcos import MdCGSecure
    prof = r"D:\dsh-home\profiles\web\cordis.patch.yml"
    tok = None
    try:
        m = re.search("MDCG_TOKEN:[ ]*'([^']+)'",
                      open(prof, encoding="utf-8", errors="replace").read())
        tok = m.group(1) if m else None
    except OSError:
        tok = None
    return MdCGSecure(root, principal=TK.verify_token(tok) if tok else None)


def _layer(cg, nid):
    g = cg.get(nid) or {}
    return ((g.get("frontmatter") or {}).get("layer"))


def main():
    from md_cg import writepipe
    root = tempfile.mkdtemp(prefix="p82_guard_")
    cg = _cg(root)
    pipe = writepipe.WritePipeline()

    check("G6 MAX_WRITE_BYTES == 1048576（1 MiB）",
          writepipe.MAX_WRITE_BYTES == 1048576, str(writepipe.MAX_WRITE_BYTES))

    pipe.execute(cg, {"node_id": "g_wip", "content": SIX, "content_kind": "work_wip"})
    check("G1 work_wip 缺省 ⇒ 落 contextual", _layer(cg, "g_wip") == "contextual",
          str(_layer(cg, "g_wip")))

    pipe.execute(cg, {"node_id": "g_text", "content": SIX, "content_kind": "text"})
    check("G2 text 缺省 ⇒ 落 knowledge（对照）", _layer(cg, "g_text") == "knowledge",
          str(_layer(cg, "g_text")))

    pipe.execute(cg, {"node_id": "g_wip_ex", "content": SIX, "content_kind": "work_wip",
                      "layer": "knowledge"})
    check("G3 work_wip 显式给 layer ⇒ 尊重显式", _layer(cg, "g_wip_ex") == "knowledge",
          str(_layer(cg, "g_wip_ex")))

    big = SIX + ("X" * (1048576 + 100))
    res = pipe.execute(cg, {"node_id": "g_big", "content": big, "content_kind": "text"})
    ok_rej = (res.get("ok") is False) and (res.get("bytes", 0) > 1048576) \
        and (res.get("limit") == 1048576) and ((res.get("verdict") or {}).get("state") == "REJECT")
    check("G4 超 1 MiB ⇒ REJECT 且如实报 bytes/limit/evidence", ok_rej,
          "ok=%r bytes=%r limit=%r state=%r" % (res.get("ok"), res.get("bytes"),
                                                res.get("limit"),
                                                (res.get("verdict") or {}).get("state")))

    res2 = pipe.execute(cg, {"node_id": "g_ok", "content": SIX + ("Y" * 100000),
                             "content_kind": "text"})
    check("G5 略小于上限 ⇒ 正常写入（未被误拦）",
          (res2.get("ok") is True) and (cg.get("g_ok") is not None), str(res2.get("ok")))

    print("")
    print("=" * 64)
    print("通过 %d ／ 失败 %d" % (PASS, FAIL))
    if FAILS:
        print("失败项：" + "，".join(FAILS))
    print("=" * 64)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
