# -*- coding: utf-8 -*-
"""test_issue346_review_overwrite_guard · 审核通道覆写目标密级闸守卫（issue #346）

# 功能名：审核通道（write / propose / accept）目标既有密级闸
# 生效条件：改动 MdCG.add 的既有节点密级闸、MdCGSecure.propose 的入队闸、
#           review_decide accept/edit 执行链之后必跑
# 子功能：G1 orchestr/record 对属主 private 节点的降密级覆写在**三个入队面**
#         （cg(op=write) 审核闸 ×orchestr、cg(op=write) 审核闸 ×record、
#         mdcg_propose）入队即 AccessDenied，节点原样、访客读不到；
#         G2 record 提交 + orchestr accept 同拒（含「存量提案 / 属主代提」的
#         accept 执行面：低 clearance 裁决者照样拒，提案保持 pending）；
#         G3 合法路径零回归（属主对自己 private 节点的审核降密流、orchestr 对
#         internal 节点的正常 accept、record 新 id 提案经 orchestr 批落盘、
#         #359 的 merge 两道闸、orchestr 直写照旧被拒）；
#         三条定点变异（两闸全回退 / 只回退 propose 闸 / 只回退 add 闸）
# 执行：python -X utf8 -m md_cg.test_issue346_review_overwrite_guard
# 验证方式：末行「通过 N / 失败 M」；每条给原始读数（返回体 / 节点盘面 / 访客可见性）
# 不适用条件：只测审核通道对**目标节点既有密级**的闸；沙箱一律 tempfile，
#             绝不触碰在役库；不测 #298 的 id 枚举残留、不测 lib.git 历史找回

## 病象（issue #346）
缺省 MDCG_AUTONOMY=confirm 下，持 orchestr 令牌（clearance 上限 internal）者对
属主 contextual 层 private 节点调 cg(op=write, sensitivity="internal")：直写面
（mdcg_remember）会 AccessDenied，但审核闸先 cg.propose 入队（BLINDSPOT 早于
autonomy 的 write_qualify），orchestr 再 mdcg_review_decide(accept) 自己批自己
——节点被整条覆写：sensitivity 降 internal、正文明文落盘、原密文无副本、
无令牌访客可读。record 令牌提交 + orchestr accept 同样成立；mdcg_propose 是
第二个入队面。修法：MdCGSecure.propose 入队前、MdCG.add 覆写落盘前，各按
**索引里的既有层与密级**过 protect.require_layer 单点（与直写面 write_qualify、
merge 支 N131 同口径）——提案者/裁决链 clearance 不足的覆写 fail-closed。
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from md_cg import protect, writepipe               # noqa: E402
from md_cg.mdcos import MdCGOS, MdCGSecure         # noqa: E402
from md_cg.security import AccessDenied, Principal  # noqa: E402

PASS = FAIL = 0
FAILS = []


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
    """一次性沙箱：独立 root/aux，退出时清理。"""

    def __init__(self, tag):
        self.tag = tag

    def __enter__(self):
        self.dir = tempfile.mkdtemp(prefix="iss346_%s_" % self.tag)
        os.environ["MDCG_ROOT"] = os.path.join(self.dir, "cgroot")
        os.environ["MDCG_AUX_ROOT"] = os.path.join(self.dir, "auxstore")
        os.environ.setdefault("MDCG_MASTER_KEY", "00" * 32)
        os.makedirs(os.environ["MDCG_AUX_ROOT"], exist_ok=True)
        return os.environ["MDCG_ROOT"]

    def __exit__(self, *exc):
        shutil.rmtree(self.dir, ignore_errors=True)
        return False


# ---------------------------------------------------------------------------
# 身份：镜像 tokens.ROLE_SPECS 的 designer / orchestr / record / guest 四档
# ---------------------------------------------------------------------------

def _owner(root):
    return MdCGSecure(root, principal=Principal(
        actor="owner", clearance="private", can_write=True, can_admin=True,
        role="designer", session="s1"))


def _orch(root):
    return MdCGSecure(root, principal=Principal(
        actor="orch", clearance="internal", can_write=True, can_admin=False,
        layers_allow=("contextual", "unresolved", "rejected"),
        ops_allow=("info", "route", "read", "write", "review", "recent",
                   "consistency"),
        role="orchestr", session="s2"))


def _rec(root):
    return MdCGSecure(root, principal=Principal(
        actor="rec", clearance="internal", can_write=True, can_admin=False,
        layers_allow=("knowledge", "contextual", "structural", "unresolved",
                      "rejected", "goals"),
        ops_allow=("info", "route", "read", "write", "goal", "task", "recent",
                   "session", "ingest", "maintain", "insight", "ccg", "status",
                   "edges"),
        role="record", session="s3"))


def _guest(root):
    return MdCGSecure(root, principal=Principal(
        actor="guest", clearance="internal", can_write=False, role="guest"))


# ---------------------------------------------------------------------------
# 读数助手
# ---------------------------------------------------------------------------

def _seed(root, nid, content, sens="private", layer="contextual"):
    o = _owner(root)
    o.add(nid, content, layer=layer, sensitivity=sens)
    o.flush()
    o.close()


def _node_reading(root, nid):
    """属主视角读回 + 盘面密文检查。"""
    o = _owner(root)
    try:
        g = o.get(nid) or {}
    finally:
        o.close()
    path = os.path.join(root, layer_file(nid))
    enc = False
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as f:
            enc = "mdcg-enc" in f.read()
    return {"sensitivity": (g.get("frontmatter") or {}).get("sensitivity"),
            "content": (g.get("content") or ""),
            "disk_encrypted": enc, "disk_exists": os.path.isfile(path)}


def layer_file(nid):
    """按 layer 目录猜路径（contextual/knowledge 一层平铺）。"""
    for layer in ("contextual", "knowledge"):
        p = os.path.join(layer, "%s.md" % nid)
        if os.path.isfile(os.path.join(os.environ["MDCG_ROOT"], p)):
            return p
    return os.path.join("contextual", "%s.md" % nid)


def _guest_sees(root, nid):
    g = _guest(root)
    try:
        n = g.get(nid)
    except Exception:                            # noqa: BLE001
        n = None
    finally:
        g.close()
    return bool(n) and bool(n.get("content"))


def _call(fn):
    """跑一次调用，返回 (异常名或 None, 结果或异常消息)。"""
    try:
        return None, fn()
    except AccessDenied as e:
        return "AccessDenied", str(e)
    except Exception as e:                        # noqa: BLE001
        return type(e).__name__, str(e)


def _pending_ids(root, nid):
    """待审队列中针对 nid 的提案 pid 列表（经 orchestr 的 review_list 读）。"""
    c = _orch(root)
    try:
        return [r.get("pid") for r in c.review_list() if r.get("id") == nid]
    finally:
        c.close()


# ---------------------------------------------------------------------------
# 攻击剧本（守卫判据 = 全部拒；变异判据 = 观察哪一环失守）
# ---------------------------------------------------------------------------

ATTACKS = {
    "f1_orch_write": ("orch", "writepipe"),
    "f2_rec_write": ("rec", "writepipe"),
    "f3_rec_propose": ("rec", "propose"),
}


def _try_enqueue(root, nid, face, marker):
    """一个入队面的一次攻击尝试：返回 (拒绝?, 读数)。"""
    who, how = ATTACKS[face]
    cg = (_orch(root) if who == "orch" else _rec(root))
    try:
        if how == "writepipe":
            err, out = _call(lambda: writepipe.default_pipeline().execute(
                cg, {"op": "write", "node_id": nid,
                     "content": "ATTACK_%s 编排通道覆写" % marker,
                     "sensitivity": "internal", "layer": "contextual"}))
        else:                                     # mdcg_propose 面（库层同点）
            err, out = _call(lambda: cg.propose(
                nid, "ATTACK_%s 提案通道覆写" % marker, layer="contextual",
                sensitivity="internal", info=True))
        moved = (out or {}).get("moved_to") if isinstance(out, dict) else None
        pid = (out or {}).get("pid") if isinstance(out, dict) else None
        return err, {"error": err, "moved_to": moved, "pid": pid,
                     "msg": out if err else out}
    finally:
        cg.close()


def _scenario_g1(root):
    """G1：三个入队面各攻一个 private 节点，收齐读数。"""
    out = {}
    for face, nid in (("f1_orch_write", "nA1"), ("f2_rec_write", "nA2"),
                      ("f3_rec_propose", "nA3")):
        _seed(root, nid, "OWNPRIV_%s 属主私有记忆" % nid)
        err, r = _try_enqueue(root, nid, face, face)
        node = _node_reading(root, nid)
        out[face] = {"enqueue": r, "node": node,
                     "guest_sees": _guest_sees(root, nid),
                     "pending": _pending_ids(root, nid)}
    return out


def _scenario_g2(root):
    """G2：record 提交被拒（队列无痕）＋属主代提的降密提案被 orchestr 批时在
    **accept 执行面**再拒一次（存量提案防线），提案保持 pending。"""
    _seed(root, "nB1", "OWNPRIV_B1 属主私有记忆")
    err, r = _try_enqueue(root, "nB1", "f2_rec_write", "g2")
    no_pid = {"enqueue": r, "pending": _pending_ids(root, "nB1"),
              "node": _node_reading(root, "nB1")}

    _seed(root, "nB2", "OWNPRIV_B2 属主私有记忆")
    o = _owner(root)
    pid = o.propose("nB2", "DOWNGRADE_B2 属主显式降密稿", layer="contextual",
                    sensitivity="internal", info=True)["pid"]
    o.close()
    c = _orch(root)
    try:
        err2, dec = _call(lambda: c.review_decide(pid, "accept"))
    finally:
        c.close()
    accept_face = {"error": err2, "dec": dec if err2 else dec,
                   "node": _node_reading(root, "nB2"),
                   "guest_sees": _guest_sees(root, "nB2"),
                   "still_pending": _pending_ids(root, "nB2")}
    return {"enqueue_face": no_pid, "accept_face": accept_face, "pid": pid}


def _scenario_g3(root):
    """G3：合法路径零回归。"""
    out = {}
    # a) 属主对自己 private 节点的审核降密流（K1：合法降密）
    _seed(root, "nC1", "OWNPRIV_C1 属主私有记忆")
    o = _owner(root)
    pid = o.propose("nC1", "DOWNGRADE_C1 属主显式降密稿", layer="contextual",
                    sensitivity="internal", info=True)["pid"]
    err, dec = _call(lambda: o.review_decide(pid, "accept"))
    o.close()
    out["owner_downgrade"] = {"error": err, "ok": (dec or {}).get("ok"),
                              "node": _node_reading(root, "nC1")}
    # b) orchestr 对 internal 节点的正常提案 + accept（K2）
    _seed(root, "nC2", "OWNINT_C2 内部记忆", sens="internal")
    c = _orch(root)
    pid = c.propose("nC2", "UPDATE_C2 编排者正常改写", layer="contextual",
                    sensitivity="internal", info=True)["pid"]
    err, dec = _call(lambda: c.review_decide(pid, "accept"))
    c.close()
    out["orch_internal_accept"] = {"error": err, "ok": (dec or {}).get("ok"),
                                   "node": _node_reading(root, "nC2")}
    # c) record 新 id 提案经 orchestr 批落盘（K3）
    r_ = _rec(root)
    pid = r_.propose("nC3", "NEW_C3 记录单元新节点", layer="contextual",
                     sensitivity="internal", info=True)["pid"]
    r_.close()
    c = _orch(root)
    err, dec = _call(lambda: c.review_decide(pid, "accept"))
    c.close()
    out["record_new_id"] = {"error": err, "ok": (dec or {}).get("ok"),
                            "node": _node_reading(root, "nC3")}
    # d) #359 的 merge 两道闸不回归：private 提案对 orchestr 不可见；
    #    属主裁决时降密级合并照旧拒
    _seed(root, "nC4", "OWNINT_C4 内部记忆", sens="internal")
    o = _owner(root)
    pid = o.propose("nC5", "SECRET_C5 私有提案正文", layer="contextual",
                    sensitivity="private", info=True)["pid"]
    o.close()
    c = _orch(root)
    err_v, dec_v = _call(lambda: c.review_decide(pid, "merge",
                                                  merge_into="nC4"))
    c.close()
    o = _owner(root)
    err_d, dec_d = _call(lambda: o.review_decide(pid, "merge",
                                                 merge_into="nC4"))
    o.close()
    out["issue359_merge"] = {"orch_error": err_v,
                             "orch_code": (dec_v or {}).get("error"),
                             "owner_code": (dec_d or {}).get("error"),
                             "node": _node_reading(root, "nC4")}
    # e) orchestr 直写 private 照旧被拒（K5；修复后库层 add 同口径）
    _seed(root, "nC6", "OWNPRIV_C6 属主私有记忆")
    c = _orch(root)
    err, _r = _call(lambda: c.add("nC6", "X", layer="contextual",
                                  sensitivity="internal"))
    c.close()
    out["orch_direct_add"] = {"error": err, "node": _node_reading(root, "nC6")}
    return out


# ---------------------------------------------------------------------------
# 定点变异（只在内存 monkeypatch，不改盘上文件）
# ---------------------------------------------------------------------------

class _MutBothOff:
    """M1：两道新闸全部回退（protect.require_layer 恒空转）。"""

    name = "M1 两闸全回退"

    def __enter__(self):
        self._orig = protect.require_layer
        protect.require_layer = (
            lambda cg, node_id, layer=None, sensitivity=None, actor=None: None)
        return self

    def __exit__(self, *exc):
        protect.require_layer = self._orig
        return False


class _MutProposeOff:
    """M2：只回退 propose 入队闸（恢复 #346 修前的 propose 主体）。"""

    name = "M2 只回退入队闸"

    def __enter__(self):
        self._orig = MdCGSecure.propose

        def _prefix_propose(self_, node_id, content, sensitivity=None, **kw):
            sens = self_._write_sensitivity(node_id, sensitivity)
            self_.principal.require_layer_write(kw.get("layer", "knowledge"),
                                                sens)
            return MdCGOS.propose(self_, node_id, content, sensitivity=sens,
                                  **kw)
        MdCGSecure.propose = _prefix_propose
        return self

    def __exit__(self, *exc):
        MdCGSecure.propose = self._orig
        return False


class _MutAddOff:
    """M3：只回退 accept 执行面的 add 闸（按调用帧名过滤，其余照旧）。"""

    name = "M3 只回退执行闸"

    def __enter__(self):
        self._orig = protect.require_layer

        def _add_only_off(cg, node_id, layer=None, sensitivity=None,
                          actor=None):
            if sys._getframe(1).f_code.co_name == "add":
                return None
            return self._orig(cg, node_id, layer=layer, sensitivity=sensitivity,
                              actor=actor)
        protect.require_layer = _add_only_off
        return self

    def __exit__(self, *exc):
        protect.require_layer = self._orig
        return False


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def main():
    print("=== issue #346 审核通道覆写目标密级闸守卫 ===")

    print("\n[G1] 三个入队面：低 clearance 对 private 既有节点的覆写入队即拒")
    with _Box("g1") as root:
        g1 = _scenario_g1(root)
    for face in ("f1_orch_write", "f2_rec_write", "f3_rec_propose"):
        r = g1[face]
        print("    %s 读数：%s" % (face, r["enqueue"]))
        label = {"f1_orch_write": "cg(op=write)×orchestr",
                 "f2_rec_write": "cg(op=write)×record",
                 "f3_rec_propose": "mdcg_propose×record"}[face]
        check("G1/%s 入队即 AccessDenied（fail-closed，不进队列）" % label,
              r["enqueue"]["error"] == "AccessDenied"
              and not r["enqueue"]["pid"]
              and "超出 clearance" in str(r["enqueue"]["msg"]), r["enqueue"])
        check("G1/%s 节点原样（仍 private 密文）" % label,
              r["node"]["sensitivity"] == "private"
              and r["node"]["disk_encrypted"] is True
              and "OWNPRIV" in r["node"]["content"]
              and "ATTACK" not in r["node"]["content"], r["node"])
        check("G1/%s 访客读不到（not_found）" % label,
              r["guest_sees"] is False, r["guest_sees"])

    print("\n[G2] record 提交 + orchestr accept 同拒（含 accept 执行面）")
    with _Box("g2") as root:
        g2 = _scenario_g2(root)
    e, a = g2["enqueue_face"], g2["accept_face"]
    print("    入队面读数：%s（队列残留 %s）" % (e["enqueue"], e["pending"]))
    print("    执行面读数：error=%s pending=%s 节点=%s 访客=%s"
          % (a["error"], a["still_pending"], a["node"]["sensitivity"],
             a["guest_sees"]))
    check("G2/a record 入队被拒且队列无痕（不占 pid）",
          e["enqueue"]["error"] == "AccessDenied" and not e["pending"],
          {"enqueue": e["enqueue"], "pending": e["pending"]})
    check("G2/b orchestr 批「属主代提的降密提案」在 accept 执行面再拒",
          a["error"] == "AccessDenied" and "超出 clearance" in str(a["dec"]),
          {"error": a["error"], "dec": str(a["dec"])[:120]})
    check("G2/c 拒后无副作用：提案保持 pending、节点原样、访客读不到",
          a["still_pending"] and a["node"]["sensitivity"] == "private"
          and a["node"]["disk_encrypted"] is True
          and "OWNPRIV" in a["node"]["content"]
          and a["guest_sees"] is False,
          {"pending": a["still_pending"], "node": a["node"],
           "guest": a["guest_sees"]})

    print("\n[G3] 合法路径零回归（防过修）")
    with _Box("g3") as root:
        g3 = _scenario_g3(root)
    o1 = g3["owner_downgrade"]
    print("    a 属主降密流读数：error=%s ok=%s sens=%s"
          % (o1["error"], o1["ok"], o1["node"]["sensitivity"]))
    check("G3/a 属主经队列显式降密自己 private 节点照旧放行（K1）",
          o1["error"] is None and o1["ok"] is True
          and o1["node"]["sensitivity"] == "internal"
          and "DOWNGRADE_C1" in o1["node"]["content"], o1)
    o2 = g3["orch_internal_accept"]
    print("    b orchestr 改 internal 读数：error=%s ok=%s 正文=%r"
          % (o2["error"], o2["ok"], o2["node"]["content"][:16]))
    check("G3/b orchestr 对 internal 节点正常提案+accept 照旧落盘（K2）",
          o2["error"] is None and o2["ok"] is True
          and "UPDATE_C2" in o2["node"]["content"]
          and o2["node"]["sensitivity"] == "internal", o2)
    o3 = g3["record_new_id"]
    print("    c record 新 id 读数：error=%s ok=%s 落盘=%s"
          % (o3["error"], o3["ok"], o3["node"]["disk_exists"]))
    check("G3/c record 新 id 提案经 orchestr 批照旧落盘（K3）",
          o3["error"] is None and o3["ok"] is True
          and o3["node"]["disk_exists"]
          and "NEW_C3" in o3["node"]["content"], o3)
    o4 = g3["issue359_merge"]
    print("    d #359 merge 闸读数：orch=%s/%s owner=%s"
          % (o4["orch_error"], o4["orch_code"], o4["owner_code"]))
    check("G3/d #359 两道 merge 闸不回归（proposal_not_visible / "
          "merge_downgrade_refused）",
          o4["orch_code"] == "proposal_not_visible"
          and o4["owner_code"] == "merge_downgrade_refused"
          and "SECRET_C5" not in o4["node"]["content"], o4)
    o5 = g3["orch_direct_add"]
    print("    e orchestr 直写读数：error=%s sens=%s"
          % (o5["error"], o5["node"]["sensitivity"]))
    check("G3/e orchestr 直写 private 照旧被拒且节点原样（K5）",
          o5["error"] == "AccessDenied"
          and o5["node"]["sensitivity"] == "private", o5)

    print("\n[变异] 三条定点变异（只在内存回退，恢复后立即复跑）")
    for mut in (_MutBothOff, _MutProposeOff, _MutAddOff):
        with mut():
            with _Box("mut") as root:
                m1 = _scenario_g1(root)
            with _Box("mut2") as root:
                m2 = _scenario_g2(root)
        faces_hit = [f for f in m1
                     if m1[f]["enqueue"]["error"] != "AccessDenied"]
        acc_hit = (m2["accept_face"]["error"] != "AccessDenied"
                   and m2["accept_face"]["node"]["sensitivity"] != "private")
        print("    %s → 入队面失守：%s；accept 面失守：%s"
              % (mut.name, faces_hit or "无", acc_hit))
        if mut is _MutBothOff:
            check("%s ⇒ G1/G2 必红（入队与执行两道都失守）" % mut.name,
                  len(faces_hit) == 3 and acc_hit,
                  {"faces": faces_hit, "accept": acc_hit})
        elif mut is _MutProposeOff:
            check("%s ⇒ G1 三面全红、G2 执行闸仍立（独立性①）" % mut.name,
                  len(faces_hit) == 3 and not acc_hit,
                  {"faces": faces_hit, "accept": acc_hit})
        else:
            check("%s ⇒ G2 accept 面红、G1 三面仍立（独立性②）" % mut.name,
                  len(faces_hit) == 0 and acc_hit,
                  {"faces": faces_hit, "accept": acc_hit})
    with _Box("restore") as root:
        g1r = _scenario_g1(root)
    check("恢复后守卫复绿（三面全部重新被拒）",
          all(g1r[f]["enqueue"]["error"] == "AccessDenied"
              for f in g1r), {f: g1r[f]["enqueue"]["error"] for f in g1r})

    print("\n" + "=" * 68)
    print("通过 %d / 失败 %d" % (PASS, len(FAILS)))
    if FAILS:
        print("失败项：" + "、".join(FAILS))
    print("=" * 68)
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
