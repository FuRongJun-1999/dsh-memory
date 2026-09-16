# -*- coding: utf-8 -*-
"""test_identity_attribution · 写入归属（writer/session/harness）与检索会话过滤

背景：多会话共用一个 root 时，读取记忆无法区分「本会话写的」与「其他会话写的」。
修复：写入自动归属（MdCGSecure 写路径注入 writer/session/harness）+ 检索
session= 过滤（_candidates 一处生效：search/search_rrf/recall 全链路）+
审计/提案入队补 session + MDCG_SESSION env（部署侧固定会话归属）。
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

    # ⑥ search 会话过滤
    res_b, _ = cg2.search("知识", session="sess_B")
    ids_b = {_row(r).get("id") for r in res_b}
    check("⑥search 会话过滤", "n1" in ids_b and "n2" not in ids_b, ids_b)

    # ⑦ recall 会话过滤（RRF 主链）
    pack = cg2.recall("知识", session="sess_custom")
    hits = pack.get("pack") if isinstance(pack, dict) else None
    hid = {_row(h).get("id") for h in (hits or [])}
    check("⑦recall 会话过滤", "n2" in hid and "n1" not in hid,
          list(hid) or (list(pack.keys()) if isinstance(pack, dict) else type(pack)))

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
    cg0 = MdCG(root)
    cg0.add("legacy", "旧库无归属节点的知识", layer="knowledge")
    cgs = MdCGSecure(root, principal=_p("carol", "sess_C"))
    res_all, _m = cgs.search("旧库无归属")
    check("⑩旧节点默认检索不受影响",
          any(_row(r).get("id") == "legacy" for r in res_all),
          [_row(r).get("id") for r in res_all])
    res_f, _ = cgs.search("旧库无归属", session="sess_C")
    check("⑩b 旧节点被会话过滤排除（不炸）",
          all(_row(r).get("id") != "legacy" for r in res_f),
          [_row(r).get("id") for r in res_f])

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
