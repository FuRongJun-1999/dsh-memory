# -*- coding: utf-8 -*-
"""test_identity_attribution · 写入归属（writer/session/harness）与会话可见性

背景：多会话共用一个 root 时，读取记忆无法区分「本会话写的」与「其他会话写的」。
修复：写入自动归属（MdCGSecure 写路径注入 writer/session/harness）+ 会话可见性
**分档判定**（issue #35 定稿：public/internal = 跨会话共享档；private/secret =
绑定档，仅归属会话可见，设计者豁免；查询侧 session 参数只作归因过滤、不构成
授权豁免）+ 审计/提案入队补 session + MDCG_SESSION env（部署侧固定会话归属）。
边界：归属是归因维度不参与授权；MCP 面不透传写入归属入参（客户端不得伪造），
库层调用方可显式覆盖（setdefault）；writer 语义=最后写入者。
"""
import glob
import json
import shutil
import sys
import tempfile
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Windows cmd 默认 GBK 代码页：带圈数字 ⑪⑫⑬ 等不在 GBK 内，打印即
# UnicodeEncodeError，且崩在断言之后、报告之前 —— 同一测试「因环境而异」。
# 测试自带 UTF-8 兜底，不依赖调用方记得加 -X utf8（可复现性纪律）。
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from md_cg.mdcg import MdCG
from md_cg.mdcos import MdCGSecure
from md_cg.security import DEFAULT_SENSITIVITY, Principal

_ok = 0
_fail = []


def check(name, cond, detail=""):
    global _ok
    if cond:
        _ok += 1
        print("[PASS] " + name)
    else:
        _fail.append(name)
        print("[FAIL] %s  · %s" % (name, str(detail)[:240]))


def _p(actor, session):
    return Principal(actor=actor, clearance=DEFAULT_SENSITIVITY,
                     can_write=True, can_admin=True, role="designer",
                     session=session, harness="test-harness")


def _last_jsonl(pattern):
    rec = None
    for path in glob.glob(pattern, recursive=True):
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                if line.strip():
                    rec = json.loads(line)
    return rec


def _row(r):
    """search 原生返回 (node, score, qual, prov) tuple；dict 则原样。"""
    return r if isinstance(r, dict) else (r[0] if r else {})


root = tempfile.mkdtemp(prefix="mdcg_attr_")
try:
    cg = MdCGSecure(root, principal=_p("alice", "sess_A"))

    # ① 写入自动归属
    nid1 = cg.add("n1", "甲会话写的知识条目", layer="knowledge")
    fm1 = cg.get(nid1)["frontmatter"]
    check("①写入自动归属 writer/session",
          fm1.get("writer") == "alice" and fm1.get("session") == "sess_A", fm1)
    check("①b harness 归属落盘", fm1.get("harness") == "test-harness", fm1)

    # ② 索引同步（_stage 透传）
    e1 = cg.index["nodes"].get(nid1) or {}
    check("②索引带归属", e1.get("session") == "sess_A", e1)

    # ③ 显式覆盖（库层调用方可传；MCP 面不透传）
    nid2 = cg.add("n2", "显式会话标签条目", layer="knowledge", session="sess_custom")
    fm2 = cg.get(nid2)["frontmatter"]
    check("③显式覆盖尊重调用方", fm2.get("session") == "sess_custom", fm2)

    # ④ 更新刷新为最后写入者（另一身份写同 id）
    cg2 = MdCGSecure(root, principal=_p("bob", "sess_B"))
    cg2.add("n1", "乙会话更新了这条", layer="knowledge")
    fm1b = cg.get("n1")["frontmatter"]
    check("④更新刷新 writer/session",
          fm1b.get("writer") == "bob" and fm1b.get("session") == "sess_B", fm1b)

    # ⑤ 检索透出归属（node.frontmatter 零改动自动生效）
    res, _meta = cg2.search("乙会话更新")
    hit = next((_row(r) for r in res if _row(r).get("id") == "n1"), None)
    check("⑤检索透出归属",
          bool(hit) and (hit.get("frontmatter") or {}).get("session") == "sess_B",
          [_row(r).get("id") for r in res])

    # ⑥⑦ 会话语义（issue #35 定稿：**分档**判定，查询参数不构成豁免）
    #   · 共享档（public/internal）跨会话可见——n1/n2 都是 internal，故传任何
    #     session（他人会话 / "*" / 缺省）都应看得见；旧断言「按 session 过滤掉」
    #     编码的是 #35 之前的契约（同口径见 test_p47_session_view 的 D1a/D2/D3）。
    #   · 绑定档（private/secret）仅归属会话——由 principal.session 判定，查询侧
    #     自报的 session 不越权；can_admin（设计者）整体判断豁免。
    res_b, _ = cg2.search("知识", session="sess_B")
    ids_b = {_row(r).get("id") for r in res_b}
    check("⑥a 共享档跨会话可见：显式 session 不缩小可见性",
          "n1" in ids_b and "n2" in ids_b, ids_b)

    # ⑥b~⑦ 绑定档对照（private 节点归 sess_B）：
    #   · 跨身份（另一 actor/会话）不可见；
    #   · **同身份换会话**：非设计者不可见（绑定档生效）；
    #   · **同身份换会话 + can_admin**：豁免可见（设计者整体判断）。
    #   注：豁免的是「会话绑定判定」，不越过加密身份——private 内容按
    #   (tenant, actor) 派生 DEK，跨 actor 即便判定可见也解不开（get 无正文），
    #   故可见性对照必须在同一 actor 内做。
    w_priv = MdCGSecure(root, principal=Principal(
        actor="bob", clearance="private", can_write=True, can_admin=False,
        role="recorder", session="sess_B"))
    try:
        w_priv.add("n_priv_b", "乙会话私有知识条目", layer="knowledge",
                   sensitivity="private")
        w_priv.flush()
    finally:
        w_priv.close()
    carol = MdCGSecure(root, principal=Principal(
        actor="carol", clearance="private", can_write=False, can_admin=False,
        role="recorder", session="sess_C"))
    try:
        res_c, _ = carol.search("私有知识", session="sess_B")   # 自报他人会话
        ids_c = {_row(r).get("id") for r in res_c}
        check("⑥b 绑定档按身份判定：自报他人会话不越权",
              "n_priv_b" not in ids_c, ids_c)
    finally:
        carol.close()
    bob_other = MdCGSecure(root, principal=Principal(
        actor="bob", clearance="private", can_write=False, can_admin=False,
        role="recorder", session="sess_OTHER"))
    try:
        res_o, _ = bob_other.search("私有知识")
        check("⑥c 同一身份换会话：非设计者仍受绑定档约束",
              "n_priv_b" not in {_row(r).get("id") for r in res_o},
              [_row(r).get("id") for r in res_o])
    finally:
        bob_other.close()
    bob_admin = MdCGSecure(root, principal=Principal(
        actor="bob", clearance="private", can_write=False, can_admin=True,
        role="designer", session="sess_OTHER"))
    try:
        res_d, _ = bob_admin.search("私有知识", session="sess_C")
        check("⑥d 同一身份 + 设计者（can_admin）：豁免绑定档",
              "n_priv_b" in {_row(r).get("id") for r in res_d},
              [_row(r).get("id") for r in res_d])

        # ⑦ recall（RRF 主链）同口径：绑定档判定不因查询 session 变化
        pack = bob_admin.recall("私有知识", session="sess_custom")
        hits = pack.get("pack") if isinstance(pack, dict) else None
        hid = {_row(h).get("id") for h in (hits or [])}
        check("⑦recall 同口径：设计者可见绑定档（查询 session 不改判定）",
              "n_priv_b" in hid,
              list(hid) or (list(pack.keys()) if isinstance(pack, dict)
                            else type(pack)))
    finally:
        bob_admin.close()

    # ⑧ 审计带 session
    last_audit = _last_jsonl(os.path.join(root, "**", "*audit*.jsonl"))
    check("⑧审计带 session",
          bool(last_audit) and last_audit.get("session") == "sess_B", last_audit)

    # ⑨ propose 入队带 session
    cg2.propose("n_prop", "提案内容", layer="knowledge")
    rec_inbox = _last_jsonl(os.path.join(root, "**", "*inbox*.jsonl"))
    check("⑨提案入队带 session",
          bool(rec_inbox) and rec_inbox.get("session") == "sess_B", rec_inbox)

    # ⑩ 旧节点兼容（基类写入、无归属字段）
    #   · 共享档：跨会话可见（#35 定稿）；
    #   · 绑定档但无归属：无法证明归属 → fail-closed，仅设计者（can_admin）可见。
    cg0 = MdCG(root)
    cg0.add("legacy", "旧库无归属节点的知识", layer="knowledge")
    cg0.add("legacy_priv", "旧库无归属的私有知识条目", layer="knowledge",
            sensitivity="private")
    cgs = MdCGSecure(root, principal=_p("carol", "sess_C"))
    res_all, _m = cgs.search("旧库无归属")
    check("⑩旧节点默认检索不受影响",
          any(_row(r).get("id") == "legacy" for r in res_all),
          [_row(r).get("id") for r in res_all])
    res_f, _ = cgs.search("旧库无归属", session="sess_C")
    check("⑩b 旧节点（无归属·共享档）跨会话可见（不炸）",
          any(_row(r).get("id") == "legacy" for r in res_f),
          [_row(r).get("id") for r in res_f])
    # ⑩c/⑩d 绑定档无归属的 fail-closed（同 clearance 的非设计者不可读 / 设计者豁免）
    peak = MdCGSecure(root, principal=Principal(
        actor="erin", clearance="private", can_write=False, can_admin=False,
        role="recorder", session="sess_E"))
    try:
        res_p, _ = peak.search("旧库无归属")
        ids_p = [_row(r).get("id") for r in res_p]
        check("⑩c 绑定档无归属 fail-closed（同 clearance 非设计者不可读）",
              "legacy_priv" not in ids_p and "legacy" in ids_p, ids_p)
    finally:
        peak.close()
    lim = MdCGSecure(root, principal=Principal(
        actor="dave2", clearance="private", can_write=True, can_admin=True,
        role="designer", session="sess_D"))
    try:
        res_l, _ = lim.search("旧库无归属")
        check("⑩d 设计者可见无归属绑定档（整体判断豁免）",
              "legacy_priv" in [_row(r).get("id") for r in res_l],
              [_row(r).get("id") for r in res_l])
    finally:
        lim.close()

    # ⑪⑫ 负记忆归属
    rn = cg2.add_rejected("假设X", "已被证伪")
    fm_r = cg2.get(rn)["frontmatter"]
    check("⑪负记忆归属", fm_r.get("writer") == "bob"
          and fm_r.get("session") == "sess_B", fm_r)
    ru = cg2.add_unresolved("问题Y", "已有线索若干")
    fm_u = cg2.get(ru)["frontmatter"]
    check("⑫未解清单归属", fm_u.get("session") == "sess_B", fm_u)

    print("\n通过 %d / 失败 %d" % (_ok, len(_fail)))
    sys.exit(1 if _fail else 0)
finally:
    shutil.rmtree(root, ignore_errors=True)
