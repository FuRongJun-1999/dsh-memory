# -*- coding: utf-8 -*-
"""issue #677 守卫：内容指纹幂等闸（opt-in），且必须登记在写入链**链首**。"""
from __future__ import annotations

import tempfile

from . import writepipe
from .mdcos import MdCGOS

BODY = "# 功能名：幂等闸测试\n# 执行：同内容两次写入\n"
OTHER = "# 功能名：另一段内容\n# 执行：不同文本\n"


def main():
    ok = bad = 0

    def chk(cond, label, extra=""):
        nonlocal ok, bad
        if cond:
            ok += 1
            print("  PASS", label)
        else:
            bad += 1
            print("  FAIL", label, extra)

    # ① 链序：dedupe 必须是 before 链的第一位（未落盘就不该解析引用/建边）
    pipe = writepipe.default_pipeline()
    order = pipe.names()["before"]
    chk(order and order[0] == "dedupe", "#677 幂等闸登记在写入链链首", str(order[:3]))

    cg = MdCGOS(tempfile.mkdtemp(prefix="f677_"))
    cg.add("existing", BODY, layer="knowledge", importance=0.6, verification_basis="test")
    cg.flush()

    def gate(a, c=cg):
        return writepipe._gate_dedupe({"a": a, "cg": c})

    # ② 命中：同层同内容 + dedupe=true → 短路返回既有 id
    out = gate({"content": BODY, "layer": "knowledge", "dedupe": True})
    chk(isinstance(out, dict) and out.get("deduped") is True, "#677 命中时返回 deduped=True", str(out)[:120])
    chk(isinstance(out, dict) and out.get("id") == "existing", "#677 返回**既有**节点 id（不是新 id）")
    chk(isinstance(out, dict) and out.get("committed") is False, "#677 短路不落盘（committed=False）")
    chk(isinstance(out, dict) and out.get("content_sha"), "#677 返回 content_sha（可用于事后核对）")

    # ③ 缺省关：不带 dedupe → 放行（返回 None），既有行为一字不变
    chk(gate({"content": BODY, "layer": "knowledge"}) is None, "#677 缺省（不带 dedupe）放行，不影响既有写入")

    # ④ 内容不同 → 放行
    chk(gate({"content": OTHER, "layer": "knowledge", "dedupe": True}) is None, "#677 内容不同不短路")

    # ⑤ 同内容但**不同层** → 放行（跨层同文本是不同语义，不能并）
    cg.add("ctx_one", BODY, layer="contextual", importance=0.4, verification_basis="test")
    cg.flush()
    out_layer = gate({"content": BODY, "layer": "structural", "dedupe": True})
    chk(out_layer is None, "#677 同内容不同层不短路（判别力自证）", str(out_layer)[:100])

    # ⑥ 字符串 "false" 不得反向开启（同 _as_flag 口径）
    chk(gate({"content": BODY, "layer": "knowledge", "dedupe": "false"}) is None,
        "#677 dedupe=\"false\" 判假（不反向开启）")
    chk(isinstance(gate({"content": BODY, "layer": "knowledge", "dedupe": "true"}), dict),
        "#677 dedupe=\"true\" 判真")

    return 0 if bad == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
