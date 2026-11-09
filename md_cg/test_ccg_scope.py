# -*- coding: utf-8 -*-
"""test_ccg_scope —— CCG 要素口径按 kind 分层（P0/P1，2026-11-06）

判什么：
  A 组 · 口径单点（纯函数，不落盘）
    A1 policy 的 required_kinds 读得到（缺省回落 ("text",)）
    A2 text 需要六要素
    A3 work_log 不需要（流水类）
    A4 kind 缺失按 text 算（不静默豁免存量）
    A5 is_exempt 认 content_kind
    A6 completeness 带 exempt 标记
  B 组 · 写链（真落盘，临时根）
    B1 content_kind 真的落进 fm（修复前 859/859 为 null）
    B2 同一段散文，kind=work_log → ACCEPT
    B3 同一段散文，kind=text → REJECT（六要素不全）
  C 组 · backfill 口径
    C1 豁免类节点不参与回填（skip 原因是 derived，不是 backfillable）
    C2 密文节点走 cg.get 解出正文后不再判 locked（分支级判据，不起加密）

负控：
  · 把 ccg_scope.needs_marks 改成恒 True → B2 变红（流水被当语义卡卡六要素）
  · 把 backfill 的密文分支改回 `return "locked", None` → C2 变红
"""
import sys
import tempfile

from . import backfill, ccg_scope, crypto, writepipe

N = 0
BAD = []

# 流水卡按定义没有六要素：它是网关三元组/日卡落下来的原始记录，只要求非空 + 可定位来源。
PROSE = "检索 0 命中：mn_gw_0021d1d4aa9d 于 2026-11-06T03:30:00 记「检索低分的根因是语料脏，不是排序」。\n"

FULL = """# 功能名：口径分层
# 生效条件：需要判断谁该凑六要素时
# 子功能：按 kind 分流
# 执行：读 policy 的 required_kinds
# 验证方式：实测
# 不适用条件：无
正文。
"""


def ck(name, cond, detail=""):
    global N
    N += 1
    if cond:
        print("  ok   %s" % name)
    else:
        BAD.append(name)
        print("  FAIL %s  %s" % (name, detail))


def _cg(root):
    from .mdcos import MdCGSecure
    from .security import Principal
    return MdCGSecure(root, principal=Principal(
        actor="dsh-memory", role="designer", tenant="default",
        clearance="private", can_write=True, can_admin=True), autoflush=8)


def A():
    k = ccg_scope.required_kinds()
    ck("A1 required_kinds 读得到", isinstance(k, tuple) and len(k) >= 1, k)
    ck("A2 text 要六要素", ccg_scope.needs_marks("text") is True)
    ck("A3 work_log 不要", ccg_scope.needs_marks("work_log") is False)
    ck("A4 kind 缺失按 text", ccg_scope.needs_marks(None) is True)
    ck("A5 is_exempt 认 kind",
       ccg_scope.is_exempt({"content_kind": "work_log"}) is True
       and ccg_scope.is_exempt({}) is False)
    cpl = ccg_scope.completeness(PROSE, {"content_kind": "work_log"})
    ck("A6 completeness 带 exempt", cpl.get("exempt") is True and "required_kinds" in cpl, cpl)


def B():
    with tempfile.TemporaryDirectory() as td:
        cg = _cg(td)
        pipe = writepipe.default_pipeline()
        r1 = pipe.execute(cg, {"node_id": "kw_1", "content": PROSE,
                               "layer": "contextual", "content_kind": "work_log",
                               "role": "assistant"})
        g1 = cg.get("kw_1") or {}
        ck("B1 content_kind 落 fm",
           (g1.get("frontmatter") or {}).get("content_kind") == "work_log",
           [(g1.get("frontmatter") or {}).get("content_kind"),
            (r1.get("verdict") or {}).get("evidence")])
        ck("B2 流水类散文被接受", bool(r1.get("ok")) and bool(r1.get("committed")),
           (r1.get("verdict") or {}).get("evidence"))
        r2 = pipe.execute(cg, {"node_id": "kt_1", "content": PROSE + "# 尾\n",
                               "layer": "knowledge", "content_kind": "text",
                               "role": "assistant"})
        ck("B3 语义类缺要素被拒",
           (not r2.get("ok")) and (r2.get("verdict") or {}).get("state") == "REJECT",
           [r2.get("ok"), (r2.get("verdict") or {}).get("state")])
        ck("B3b 被拒的不落正式层", (cg.get("kt_1") or {}) == {})

        # B4/B5：写入口的缺省口径——流水层自动落 work_log，语义层**不猜**
        r3 = pipe.execute(cg, {"node_id": "kw_3", "content": PROSE,
                               "layer": "contextual", "role": "assistant"})
        g3 = cg.get("kw_3") or {}
        ck("B4 流水层缺省落 work_log（调用方没传 kind）",
           (g3.get("frontmatter") or {}).get("content_kind") == "work_log",
           [(g3.get("frontmatter") or {}).get("content_kind"),
            (r3.get("verdict") or {}).get("evidence")])
        r4 = pipe.execute(cg, {"node_id": "kb_1", "content": FULL,
                               "layer": "knowledge", "role": "assistant"})
        g4 = cg.get("kb_1") or {}
        ck("B5 语义层不猜 kind（fm 里没有 content_kind）",
           "content_kind" not in (g4.get("frontmatter") or {}),
           (g4.get("frontmatter") or {}).get("content_kind"))


class _Stub:
    """只实现 _classify 会碰到的那几个方法。"""

    def __init__(self):
        self.index = {"nodes": {}}
        self.asked = []

    def _readable(self, e):
        return True

    def get(self, nid, probe=False):
        self.asked.append((nid, probe))
        return {"content": FULL, "layer": "knowledge",
                "frontmatter": {"tags": [], "content_kind": "text"}}


def C():
    with tempfile.TemporaryDirectory() as td:
        cg = _cg(td)
        pipe = writepipe.default_pipeline()
        pipe.execute(cg, {"node_id": "kw_2", "content": PROSE,
                          "layer": "contextual", "content_kind": "work_log",
                          "role": "assistant"})
        e = cg.index["nodes"]["kw_2"]
        why, item = backfill._classify(cg, e, "kw_2")
        ck("C1 豁免类不回填", why == "derived" and item is None, (why, item))

    # C2：分支级——盘面读到的是完整密文信封，cg.get 能给出正文，
    # 于是必须按「present/derived」走完，不得停在 locked。
    enc = crypto.ENC_PREFIX + "QUJD" + crypto.ENC_SUFFIX
    orig = backfill.direct_read
    try:
        backfill.direct_read = lambda c, e: ({"tags": [], "content_kind": "text"}, enc)
        stub = _Stub()
        why2, _ = backfill._classify(stub, {"layer": "knowledge"}, "kp_x")
    finally:
        backfill.direct_read = orig
    ck("C2 密文节点解出后不再判 locked", why2 == "present", why2)
    ck("C2b 走的是 cg.get(probe=True)", stub.asked == [("kp_x", True)], stub.asked)


def main():
    print("=== test_ccg_scope ===")
    A()
    B()
    C()
    print("=== test_ccg_scope: PASS %d / FAIL %d ===" % (N - len(BAD), len(BAD)))
    if BAD:
        print("失败项：", "、".join(BAD))
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
