# -*- coding: utf-8 -*-
"""test_issue359_review_merge_downgrade_guard · review merge 落点双闸守卫（issue #359）

# 功能名：裁决 merge 分支的降密级单点接线 + 裁决者可见性闸守卫
# 生效条件：改动 mdcos.py review_decide 的 merge 分支（guard_write 之后的
#           两道闸）、security.merge_downgrades 单点、或 _readable 可见性
#           判据之后必跑
# 子功能：G1 private 提案 merge 进 internal 节点被拒（merge_downgrade_refused）
#           且 guest 读不到、盘上（节点面）无明文、提案留 pending
#         G2 不可见提案（orchestr 对 private）merge 返回 proposal_not_visible
#         G3 防过修：同档（internal→internal）merge 照常成功；CONVERGE /
#           reinforce / branches 三个既有降密级闸零回归
#         G4 公开提案（internal 或更低）对有权限裁决者 merge 照常成功
#         变异：V1 拆可见性闸 ⇒ G2 红；V2 拆降密级闸 ⇒ G1 红（泄漏复现）；
#           两闸各自独立承重
# 执行：python -X utf8 -m md_cg.test_issue359_review_merge_downgrade_guard
# 验证方式：末行「通过 N / 失败 M」；每条给原始读数（返回体 / 落盘正文 /
#           访客可见性 / pending 状态）
# 不适用条件：只测 review merge 落点的两道闸；inbox.jsonl 里提案正文按 propose
#           既有面留存（读面由 N201 的 _review_list_visible 把守）不在本件范围；
#           沙箱一律 tempfile，绝不触碰在役库

## 病象（issue #359 · P0 Security）
mdcos.py review_decide(decision=merge) 分支是**第四个**「把 incoming 正文并入
target、按 target 档可见」的合并落点，没接 #148 的 security.merge_downgrades
单点（该单点已接 writelimit.py / forgetting.py / branches.py 三处）。后果：
①designer 裁决者把 sensitivity=private 的提案 merge 进 internal 节点返回
ok:true，正文明文落盘、无令牌访客可读（同场景走 CONVERGE/reinforce/branch
merge 都是 merge_downgrade_refused）；
②orchestr（clearance=internal）在 review_list 看不到 private 提案（N201
过滤），但凭 pid 一样 decision=merge 进自己可写节点后 get 读回 private 明文
——MdCGSecure.review_decide 只 require_op("review")，不判裁决者能否读该提案。

## 修法与判据
merge 分支 guard_write 之后、拼接之前两道闸：
①隔离层在位时 `_readable({"sensitivity": 提案档 or "secret", "session":
  item.session})` 判裁决者可见性，不可见返回 proposal_not_visible（密级取值与
  _review_list_visible 的 N201 口径同源；纯 MdCGOS 无 _readable，本闸不设——
  其 get/search 亦不设读闸）；
②security.merge_downgrades(目标档, 提案声明档) 命中返回 merge_downgrade_refused
  （不写盘；incoming 取声明值，None 由单点内部按 DEFAULT_SENSITIVITY 处理，
  与 writelimit/forgetting/branches 三处既有调用同形）。
两闸命中均不带 record——提案留 pending（与 merge_target_not_found 同款）。
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from md_cg import branches, forgetting, security, writelimit    # noqa: E402
from md_cg.mdcos import MdCGSecure, MdCGOS                      # noqa: E402

PASS = FAIL = 0
FAILS = []

#: 各场景私文明文哨兵（节点面落盘出现即为泄漏）
MARK1 = "PRIVATE-MARK-359-A"      # G1：designer merge private→internal
MARK2 = "PRIVATE-MARK-359-B"      # G2：orchestr merge 不可见 private 提案
SAME = "INTERNAL-MARK-359-SAME"   # G3：同档合并（internal→internal，可明文）
PUB = "PUBLIC-MARK-359-PUB"       # G4：internal 档提案（低于/等于目标，照常）
BR = "PRIVATE-MARK-359-BRANCH"    # G3 回归：branches 降密级闸


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  [PASS] %s%s" % (name, ("  · " + str(detail)) if detail else ""))
    else:
        FAIL += 1
        FAILS.append(name)
        print("  [FAIL] %s  · %s" % (name, detail))


class _Box:
    """一次性沙箱：独立 root/aux，退出时清理（形态照抄 test_issue148）。"""

    def __init__(self, tag):
        self.tag = tag

    def __enter__(self):
        self.dir = tempfile.mkdtemp(prefix="iss359_%s_" % self.tag)
        os.environ["MDCG_ROOT"] = os.path.join(self.dir, "cgroot")
        os.environ["MDCG_AUX_ROOT"] = os.path.join(self.dir, "auxstore")
        os.environ.setdefault("MDCG_MASTER_KEY", "00" * 32)
        os.makedirs(os.environ["MDCG_AUX_ROOT"], exist_ok=True)
        return os.environ["MDCG_ROOT"]

    def __exit__(self, *exc):
        shutil.rmtree(self.dir, ignore_errors=True)
        return False


def _owner(root):
    return MdCGSecure(root, principal=security.Principal(
        actor="owner", clearance="private", can_write=True, can_admin=True,
        role="designer", session="s_owner"))


def _reviewer(root):
    # designer 裁决者：clearance 足够、can_admin ⇒ _readable 对 private 豁免
    # ——G1 场景里可见性闸必然放行，隔离出降密级闸独立承重。
    return MdCGSecure(root, principal=security.Principal(
        actor="reviewer", clearance="private", can_write=True, can_admin=True,
        role="designer", session="s_rev"))


def _orchestr(root):
    # 编排者：clearance=internal，可写 contextual 层（自有 internal 节点）；
    # ops_allow=None（不限）⇒ 持 review op——G2 场景里降密级闸之外的那道闸
    # 只能是可见性（private 超出 clearance）。
    return MdCGSecure(root, principal=security.Principal(
        actor="orchestr", clearance="internal", can_write=True,
        role="orchestr", session="s_orch"))


def _guest(root):
    return MdCGSecure(root, principal=security.Principal(
        actor="guest", clearance="internal", can_write=False, role="guest"))


def _node_plaintext(root, needle):
    """节点面明文扫描：全库找 needle，剔除 inbox.jsonl（提案既有面，N201 管读面）。"""
    out, n = [], needle.encode("utf-8")
    for dp, _dirs, files in os.walk(root):
        for fn in files:
            fp = os.path.join(dp, fn)
            rel = os.path.relpath(fp, root).replace(os.sep, "/")
            if rel == "hippocampus/inbox.jsonl":
                continue
            try:
                with open(fp, "rb") as fh:
                    if n in fh.read():
                        out.append(rel)
            except OSError:
                pass
    return sorted(out)


def _pending_pids(cg):
    return [r.get("pid") for r in cg.review_list()]


def _still_pending(root, pid):
    """pending 判定走**能看见该 private 提案**的裁决者（designer）实例——
    guest/orchestr 的 review_list 被 N201 可见性过滤，本就看不见 private
    提案，不能据以判 pending。"""
    rv = _reviewer(root)
    try:
        return pid in _pending_pids(rv)
    finally:
        rv.close()


def _seed_two_private_proposals(root):
    """owner 建 internal 目标节点 + 两条 private 提案（r1 场景复刻）。"""
    ow = _owner(root)
    ow.add("n1", "# 功能名：359 目标\n\n内部底稿", layer="contextual",
           sensitivity="internal")
    pid1 = ow.propose("p1", "私有提案正文 " + MARK1, sensitivity="private")
    pid2 = ow.propose("p2", "私有提案正文 " + MARK2, sensitivity="private")
    ow.close()
    return pid1, pid2


def _g1_scene(root):
    """G1：designer merge pid1(private)→n1(internal)，返回读数。"""
    pid1, _pid2 = _seed_two_private_proposals(root)
    rv = _reviewer(root)
    res = rv.review_decide(pid1, "merge", merge_into="n1")
    rv.close()
    g = _guest(root)
    gn = g.get("n1")
    out = {
        "res": res,
        "guest_sees": bool(gn) and MARK1 in (gn.get("content") or ""),
        "node_leak": _node_plaintext(root, MARK1),
        "pending": _still_pending(root, pid1),
    }
    g.close()
    return out


def _g2_scene(root):
    """G2：orchestr list 不见 pid2，凭 pid merge，返回读数。"""
    _pid1, pid2 = _seed_two_private_proposals(root)
    oc = _orchestr(root)
    listed = pid2 in _pending_pids(oc)
    oc.add("n2", "# 功能名：orchestr 自有节点\n\n编排底稿", layer="contextual",
           sensitivity="internal")
    res = oc.review_decide(pid2, "merge", merge_into="n2")
    n2 = oc.get("n2")
    out = {
        "listed": listed,
        "res": res,
        "readback": bool(n2) and MARK2 in (n2.get("content") or ""),
        "node_leak": _node_plaintext(root, MARK2),
        "pending": _still_pending(root, pid2),
    }
    oc.close()
    return out


def main():
    print("=== issue #359 review merge 落点双闸守卫 ===")

    print("\n[G1] designer merge private→internal：拒 + guest 读不到 + 节点面无明文 + 留 pending")
    with _Box("g1") as root:
        r = _g1_scene(root)
    res = r["res"]
    print("    读数：error=%s target_sensitivity=%s incoming_sensitivity=%s "
          "guest_sees=%s node_leak=%s pending=%s"
          % (res.get("error"), res.get("target_sensitivity"),
             res.get("incoming_sensitivity"), r["guest_sees"], r["node_leak"],
             r["pending"]))
    check("merge 返回 merge_downgrade_refused（fail-closed）",
          res.get("ok") is False and res.get("error") == "merge_downgrade_refused",
          res)
    check("返回体带 target_sensitivity=internal / incoming_sensitivity=private",
          res.get("target_sensitivity") == "internal"
          and res.get("incoming_sensitivity") == "private", res)
    check("无令牌访客读不到 private 明文", r["guest_sees"] is False, r["guest_sees"])
    check("节点面盘上无明文（inbox 提案既有面除外）", r["node_leak"] == [], r["node_leak"])
    check("提案留 pending（拒绝不落 accepted 裁决）", r["pending"] is True, r["pending"])

    print("\n[G2] orchestr 对不可见 private 提案：merge 返回 proposal_not_visible")
    with _Box("g2") as root:
        r = _g2_scene(root)
    res = r["res"]
    print("    读数：listed=%s error=%s readback=%s node_leak=%s pending=%s"
          % (r["listed"], res.get("error"), r["readback"], r["node_leak"],
             r["pending"]))
    check("前置：orchestr 的 review_list 看不到该 private 提案（N201 过滤在）",
          r["listed"] is False, r["listed"])
    check("凭 pid merge 返回 proposal_not_visible（不可见即不可裁决）",
          res.get("ok") is False and res.get("error") == "proposal_not_visible",
          res)
    check("orchestr 读回不到 private 明文", r["readback"] is False, r["readback"])
    check("节点面盘上无明文", r["node_leak"] == [], r["node_leak"])
    check("提案留 pending（可见性拒绝同样不落裁决）", r["pending"] is True, r["pending"])

    print("\n[G3] 防过修①：同档 merge 照常；三个既有降密级闸零回归")
    with _Box("g3a") as root:
        ow = _owner(root)
        ow.add("n3", "# 功能名：同档目标\n\n内部底稿", layer="contextual",
               sensitivity="internal")
        pid = ow.propose("p3", "同档提案正文 " + SAME, sensitivity="internal")
        ow.close()
        rv = _reviewer(root)
        res = rv.review_decide(pid, "merge", merge_into="n3")
        node = rv.get("n3")
        rv.close()
    print("    读数：%s；正文含 SAME=%s" % (
        {k: res.get(k) for k in ("ok", "error", "node_id")},
        bool(node) and SAME in (node.get("content") or "")))
    check("同档（internal→internal）merge 照常成功",
          res.get("ok") is True and res.get("node_id") == "n3", res)
    check("同档正文确实并入（判据不误伤）",
          bool(node) and SAME in (node.get("content") or ""), node)

    with _Box("g3b") as root:
        ow = _owner(root)
        ow.add("n4", "# 功能名：CONVERGE 目标\n\n内部底稿", layer="contextual",
               sensitivity="internal")
        ow.close()
        rv = _reviewer(root)
        rc = writelimit.converge_into(rv, "n4", "私有短记忆 " + MARK1,
                                      actor="reviewer", sensitivity="private")
        rf = forgetting.reinforce(rv, "n4", actor="reviewer",
                                  content="私有短记忆 " + MARK1,
                                  sensitivity="private")
        node = rv.get("n4")
        rv.close()
    print("    读数：converge=%s reinforce=%s 落盘=%s" % (
        (rc or {}).get("error"), (rf or {}).get("error"),
        MARK1 in ((node or {}).get("content") or "")))
    check("CONVERGE（writelimit.converge_into）降密级闸零回归",
          (rc or {}).get("error") == "merge_downgrade_refused"
          and MARK1 not in ((node or {}).get("content") or ""), rc)
    check("MERGE（forgetting.reinforce）降密级闸零回归",
          (rf or {}).get("error") == "merge_downgrade_refused"
          and MARK1 not in ((node or {}).get("content") or ""), rf)

    with _Box("g3c") as root:
        ow = _owner(root)
        ow.add("m_low", "低档主支正文 LOW-359", layer="knowledge",
               verification_basis="test", consistency=False)
        ow.add("m_low@bg", "升档分支正文 " + BR, layer="knowledge",
               sensitivity="private", branch_id="bg", branched_from="m_low",
               verification_basis="test", consistency=False)
        ow.close()
        rv = _reviewer(root)
        rbr = branches.merge(rv, "bg")
        main_node = rv.get("m_low")
        rv.close()
    print("    读数：merged=%s skipped=%s 主支被覆盖=%s" % (
        rbr.get("merged"), rbr.get("skipped"),
        BR in ((main_node or {}).get("content") or "")))
    check("branches merge 降密级闸零回归（分支 private>主支 internal ⇒ 跳过不写盘）",
          rbr.get("merged") == []
          and any("降密级" in str(s.get("why")) for s in (rbr.get("skipped") or []))
          and BR not in ((main_node or {}).get("content") or ""), rbr)

    print("\n[G4] 防过修②：有权限裁决者 merge 可见提案（internal / 更低档）照常")
    with _Box("g4") as root:
        ow = _owner(root)
        ow.add("n5", "# 功能名：公开档目标\n\n内部底稿", layer="contextual",
               sensitivity="internal")
        pid_i = ow.propose("p4", "内部档提案 " + PUB, sensitivity="internal")
        pid_p = ow.propose("p5", "更低档提案 " + PUB, sensitivity="public")
        ow.close()
        rv = _reviewer(root)
        ri = rv.review_decide(pid_i, "merge", merge_into="n5")
        rp = rv.review_decide(pid_p, "merge", merge_into="n5")
        node = rv.get("n5")
        rv.close()
    print("    读数：internal 档提案 merge ok=%s；public 档提案 merge ok=%s；"
          "正文并入=%s" % (ri.get("ok"), rp.get("ok"),
                          bool(node) and PUB in (node.get("content") or "")))
    check("internal 提案（同档）merge 照常成功", ri.get("ok") is True, ri)
    check("public 提案（低于目标档，非降密级）merge 照常成功",
          rp.get("ok") is True, rp)

    print("\n[V] 定点变异：两道闸各自承重（拆其一 ⇒ 对应场景红）")
    # V1 拆可见性闸：_readable 恒 True（= 修前「不判裁决者能否读提案」）。
    _saved_readable = MdCGSecure._readable
    MdCGSecure._readable = lambda self, e, session=None: True
    try:
        with _Box("v1") as root:
            r = _g2_scene(root)
    finally:
        MdCGSecure._readable = _saved_readable
    print("    V1 读数：error=%s readback=%s" % ((r["res"] or {}).get("error"),
                                                r["readback"]))
    check("V1 拆可见性闸 ⇒ G2 红（proposal_not_visible 消失；纵深由降密级闸"
          "兜住 private→internal，但「不可见即不可裁决」这一属性丢失）",
          (r["res"] or {}).get("error") != "proposal_not_visible", r["res"])

    # V2 拆降密级闸：merge_downgrades 恒 False（= 修前「第四落点不接 #148 单点」）。
    _saved_md = security.merge_downgrades
    security.merge_downgrades = lambda t, i: False
    try:
        with _Box("v2") as root:
            r = _g1_scene(root)
    finally:
        security.merge_downgrades = _saved_md
    print("    V2 读数：ok=%s guest_sees=%s node_leak=%s" % (
        (r["res"] or {}).get("ok"), r["guest_sees"], r["node_leak"]))
    check("V2 拆降密级闸 ⇒ G1 红（泄漏复现：ok:true、guest 读到明文、节点面落盘）",
          (r["res"] or {}).get("ok") is True and r["guest_sees"] is True
          and r["node_leak"] != [], r)

    # 纯 MdCGOS 面：merge 闸不设 _readable（无身份模型），降密级闸引擎级生效。
    with _Box("base") as root:
        cg = MdCGOS(root)
        cg.add("b1", "# 功能名：纯引擎目标\n\n底稿", layer="contextual",
               sensitivity="internal")
        pid = cg.propose("b2", "声明私档提案 " + MARK1,
                         **{"sensitivity": "private"})
        res = cg.review_decide(pid, "merge", merge_into="b1")
        node = cg.get("b1")
        cg.close()
    print("    读数：error=%s 落盘=%s" % (
        res.get("error"), MARK1 in ((node or {}).get("content") or "")))
    check("纯 MdCGOS：无 _readable 不设可见性闸，降密级闸照拒（引擎级单点）",
          res.get("error") == "merge_downgrade_refused"
          and MARK1 not in ((node or {}).get("content") or ""), res)

    print("\n" + "=" * 68)
    print("通过 %d / 失败 %d" % (PASS, len(FAILS)))
    if FAILS:
        print("失败项：" + "、".join(FAILS))
    print("=" * 68)
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
