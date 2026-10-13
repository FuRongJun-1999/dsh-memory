# -*- coding: utf-8 -*-
"""证据包密级继承守卫（issue #248）。

验证目标：
  ① 导出：包条目带 sensitivity（取 subgraph.node_sensitivity，与 #164 派生节点同源）
  ② 导入：按条目声明档位落盘 ⇒ private 观测在对端仍是 private，且**盘上无明文**
  ③ 阴性对照：internal 观测不被过度提级、也不被误拒（明文照旧在盘）
  ④ fail-closed：缺 sensitivity 字段（旧格式包）/ 非法档位 ⇒ 不写盘、计入 skipped
  ⑤ 导入方密级不足（AccessDenied）⇒ 跳过而不降级落盘、不抛异常
  ⑥ 归档闸：**整包**含 private/secret 或判不了档位的条目 ⇒ 不写收件箱（归档是整包明文 JSON）
     —— 判据扫整包全部条目，含缺档/非法档/被跳过者与切片外尾部条目（#258 复核补）
  ⑦ 判据单点自证（含「委托 subgraph 单点」的跟随自证）+ 3 条定点变异

运行：python -m md_cg.test_evidence_pack_sensitivity
      python -m md_cg.test_evidence_pack_sensitivity --mutate=drop_sensitivity|trust_item|allow_archive
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile

from . import evidence, identity, signer, theory

PASS = FAIL = 0
FAILS = []
CANARY = "CANARY-EVPACK-PRIVATE-9c41d7"


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}" + (f"  · {detail}" if detail else ""))
    else:
        FAIL += 1
        FAILS.append(name)
        print(f"  [FAIL] {name}  · {detail}")


def scan_plaintext(root, needle):
    """全库扫明文（os.walk + 字节匹配），返回命中文件相对路径清单。"""
    hits = []
    for dp, _dn, fn in os.walk(root):
        for f in fn:
            p = os.path.join(dp, f)
            try:
                with open(p, "rb") as fh:
                    if needle.encode("utf-8") in fh.read():
                        hits.append(os.path.relpath(p, root))
            except OSError:
                pass
    return sorted(hits)


def _open_low_clearance(root):
    """导入方密级不足的夹具：clearance=internal 的可写 principal。"""
    from .mdcos import MdCGSecure
    from .security import Principal
    from .tokens import role_spec
    spec = role_spec("sustain")
    p = Principal(tenant="default", actor="low-clearance", clearance="internal",
                  can_write=True, can_admin=False, role="sustain",
                  layers_allow=spec["layers_allow"], ops_allow=spec["ops_allow"],
                  auth_mode="legacy_env")
    return MdCGSecure(root, principal=p)


def main(mutate: str = ""):
    tmp = tempfile.mkdtemp(prefix="mdcg_evpack_sens_")
    root_a = os.path.join(tmp, "A")
    root_b = os.path.join(tmp, "B")
    root_c = os.path.join(tmp, "C")
    for r in (root_a, root_b, root_c):
        os.makedirs(r)
    swarm = os.path.join(tmp, "swarm")
    os.makedirs(swarm)
    sf_a = os.path.join(tmp, "A_signers.json")
    sf_b = os.path.join(tmp, "B_signers.json")
    kf = os.path.join(tmp, "shared.key")
    tf = os.path.join(tmp, "theory.json")
    os.environ["MDCG_THEORY_FILE"] = tf
    os.environ["MDCG_SIGNER_KEY_FILE"] = kf
    for k in ("MDCG_SIGNER", "MDCG_SIGNER_MODULE", "MDCG_NODE_ID", "MDCG_ROOT"):
        os.environ.pop(k, None)

    saved = None
    try:
        theory.declare("3.4", accepted=["3.4", "3.3"], path=tf)
        signer.set_policy("swarm", path=sf_a, sign_on=["handshake", "evidence"])
        signer.set_policy("swarm", path=sf_b, sign_on=["handshake", "evidence"])
        cg_a = evidence._open_cg(root_a)
        cg_b = evidence._open_cg(root_b)
        cg_c = _open_low_clearance(root_c)
        nid_a = evidence.node_id(root_a)
        nid_b = evidence.node_id(root_b)
        subj_b = "agent:" + nid_b
        subj_c = "agent:" + evidence.node_id(root_c)

        # ---- 变异：注入历史缺陷（单点级） ----
        # drop_sensitivity：单点恒返 None（复刻「导出不带档位」这一半）；
        # 注意其端态是**导入侧 fail-closed 跳过**（不是改前的 internal+明文），
        # 「盘上无明文」那条断言由 trust_item 变异覆盖。
        if mutate == "drop_sensitivity":
            saved = evidence._node_sensitivity
            evidence._node_sensitivity = lambda cg, nid: None
        elif mutate == "trust_item":
            saved = evidence._item_sensitivity
            evidence._item_sensitivity = lambda it: "internal"
        elif mutate == "allow_archive":
            saved = evidence._pack_has_unarchivable
            evidence._pack_has_unarchivable = lambda pack: False
        elif mutate:
            print(f"未知变异：{mutate}")
            return 2

        # ================= ① 判据单点自证 =================
        check("_item_sensitivity 认合法档位",
              evidence._item_sensitivity({"sensitivity": "private"}) == "private")
        check("_item_sensitivity 未知档 ⇒ None",
              evidence._item_sensitivity({"sensitivity": "topsecret"}) is None)
        check("_item_sensitivity 缺字段 ⇒ None",
              evidence._item_sensitivity({}) is None)
        check("_item_sensitivity 非字符串 ⇒ None",
              evidence._item_sensitivity({"sensitivity": 7}) is None)

        # 单点委托自证：把 subgraph.node_sensitivity 换成哨兵，evidence 必须跟随
        # （否则另写一份阶梯也能通过「同源」断言）
        from . import subgraph as _subgraph_mod
        _saved_ns = _subgraph_mod.node_sensitivity
        _subgraph_mod.node_sensitivity = lambda cg, nid: "restricted"
        try:
            check("_node_sensitivity 委托 subgraph.node_sensitivity（跟随单点，非自建阶梯）",
                  evidence._node_sensitivity(None, "any") == "restricted",
                  str(evidence._node_sensitivity(None, "any")))
        finally:
            _subgraph_mod.node_sensitivity = _saved_ns

        # 归档闸判据扫**整包**（#258 复核：只看已写盘条目会漏掉缺档/非法档/尾部条目）
        check("归档判据：private 条目 ⇒ 不归档",
              evidence._pack_has_unarchivable({"items": [{"sensitivity": "private"}]}) is True)
        check("归档判据：缺档 / 非法档 ⇒ 不归档",
              evidence._pack_has_unarchivable({"items": [{}]}) is True
              and evidence._pack_has_unarchivable({"items": [{"sensitivity": "topsecret"}]}) is True)
        check("归档判据：切片外尾部条目也计（不受 items[:MAX_ITEMS] 影响）",
              evidence._pack_has_unarchivable(
                  {"items": [{"sensitivity": "internal"}] * 3 + [{"sensitivity": "secret"}]}) is True)
        check("归档判据：非 dict 条目 ⇒ 不归档（fail-closed）",
              evidence._pack_has_unarchivable({"items": ["x"]}) is True)
        check("归档判据：全 internal ⇒ 可归档",
              evidence._pack_has_unarchivable({"items": [{"sensitivity": "internal"}]}) is False)

        # ================= ② private 观测：导出带档位、导入仍 private =================
        cg_a.add("obs_priv", CANARY + " A 侧私有观测正文", layer="knowledge",
                 tags=[identity.TAG_OBS, "subject:" + subj_b],
                 sensitivity="private", verification_basis="data")
        check("夹具：A 侧节点索引档位为 private",
              (cg_a.index["nodes"]["obs_priv"] or {}).get("sensitivity") == "private",
              str((cg_a.index["nodes"]["obs_priv"] or {}).get("sensitivity")))
        check("夹具：A 侧盘上无明文（private 已加密）",
              scan_plaintext(root_a, CANARY) == [], scan_plaintext(root_a, CANARY))
        check("_node_sensitivity 与 subgraph 单点同源（private）",
              evidence._node_sensitivity(cg_a, "obs_priv") == "private",
              str(evidence._node_sensitivity(cg_a, "obs_priv")))

        res = evidence.export_pack(cg_a, swarm=swarm, signers_file=sf_a)
        pack = res["pack"]
        item = pack["items"][0]
        check("导出条目带 sensitivity=private",
              item.get("sensitivity") == "private", str(item.get("sensitivity")))

        r = evidence.import_pack(cg_b, dict(pack), swarm=swarm, signers_file=sf_b)
        check("导入成功 1 条", r.get("ok") is True and r.get("imported") == 1, str(r.get("imported")))
        xnid = (r.get("node_ids") or [""])[0]
        e_b = cg_b.index["nodes"].get(xnid) or {}
        fm_b = (cg_b.get(xnid) or {}).get("frontmatter") or {}
        check("导入后对端索引档位仍 private", e_b.get("sensitivity") == "private",
              str(e_b.get("sensitivity")))
        check("导入后对端 frontmatter 仍 private", fm_b.get("sensitivity") == "private",
              str(fm_b.get("sensitivity")))
        check("导入后对端盘上无 private 明文",
              scan_plaintext(root_b, CANARY) == [], scan_plaintext(root_b, CANARY))
        check("包内含 private ⇒ 不写收件箱（archive_skipped 非空）",
              not r.get("archived") and bool(r.get("archive_skipped")),
              f"archived={r.get('archived')!r} reason={r.get('archive_skipped')!r}")
        check("收件箱内无 private 明文",
              scan_plaintext(swarm, CANARY) == [], scan_plaintext(swarm, CANARY))

        # ================= ③ 阴性对照：internal 不提级、不误拒 =================
        cg_a.add("obs_int", "INTERNAL-CONTROL-3b7f 普通观测", layer="knowledge",
                 tags=[identity.TAG_OBS, "subject:" + subj_c],
                 verification_basis="data")
        res2 = evidence.export_pack(cg_a, subjects=[subj_c], swarm=swarm, signers_file=sf_a)
        items2 = {i["node_id"]: i for i in res2["pack"]["items"]}
        check("对照：internal 条目带 sensitivity=internal",
              items2["obs_int"].get("sensitivity") == "internal",
              str(items2["obs_int"].get("sensitivity")))
        r2 = evidence.import_pack(cg_b, dict(res2["pack"]), swarm=swarm, signers_file=sf_b)
        check("对照：internal 条目被正常接收（不误拒）",
              r2.get("imported") == 1, str(r2.get("imported")))
        xn2 = (r2.get("node_ids") or [""])[0]
        check("对照：internal 未被过度提级",
              ((cg_b.index["nodes"].get(xn2) or {}).get("sensitivity")) == "internal",
              str((cg_b.index["nodes"].get(xn2) or {}).get("sensitivity")))
        check("对照：internal 明文照旧在盘（证明判据不靠禁写实现）",
              scan_plaintext(root_b, "INTERNAL-CONTROL-3b7f") != [],
              scan_plaintext(root_b, "INTERNAL-CONTROL-3b7f"))
        check("对照：不含加密档位时归档正常",
              bool(r2.get("archived")) and not r2.get("archive_skipped"),
              f"archived={r2.get('archived')!r}")

        # ================= ④ fail-closed：旧格式包 / 非法档位 =================
        def resign(pk):
            sig = signer.sign_for("swarm", evidence._pack_payload(pk),
                                  action=evidence.SIGN_ACTION, path=sf_a)
            pk["sig"] = {"signer": sig.get("signer"),
                         "signature": sig.get("signature") or "",
                         "signed": bool(sig.get("signed"))}
            return pk

        old = json.loads(json.dumps(res["pack"]))
        old["items"][0].pop("sensitivity", None)
        old["pack_id"] = "pack-oldfmt000001"
        resign(old)
        r3 = evidence.import_pack(cg_b, old, swarm=swarm, signers_file=sf_b)
        check("旧格式包（缺 sensitivity）⇒ fail-closed 不写盘",
              r3.get("ok") is True and r3.get("imported") == 0 and r3.get("skipped") >= 1,
              f"imported={r3.get('imported')} skipped={r3.get('skipped')}")
        check("旧格式包导入后对端盘上无 private 明文",
              scan_plaintext(root_b, CANARY) == [], scan_plaintext(root_b, CANARY))
        check("旧格式包（缺档）⇒ 整包不归档（archive_skipped 非空）",
              not r3.get("archived") and bool(r3.get("archive_skipped")),
              f"archived={r3.get('archived')!r} reason={r3.get('archive_skipped')!r}")
        check("旧格式包（缺档）⇒ 收件箱无 private 明文",
              scan_plaintext(swarm, CANARY) == [], scan_plaintext(swarm, CANARY))

        bad = json.loads(json.dumps(res["pack"]))
        bad["items"][0]["sensitivity"] = "topsecret"
        bad["pack_id"] = "pack-badtier00001"
        resign(bad)
        r4 = evidence.import_pack(cg_b, bad, swarm=swarm, signers_file=sf_b)
        check("非法档位 ⇒ fail-closed 不写盘",
              r4.get("imported") == 0 and r4.get("skipped") >= 1,
              f"imported={r4.get('imported')} skipped={r4.get('skipped')}")
        check("非法档位 ⇒ 整包不归档（archive_skipped 非空）",
              not r4.get("archived") and bool(r4.get("archive_skipped")),
              f"archived={r4.get('archived')!r} reason={r4.get('archive_skipped')!r}")
        check("非法档位 ⇒ 收件箱无 private 明文",
              scan_plaintext(swarm, CANARY) == [], scan_plaintext(swarm, CANARY))

        # ================= ⑤ 导入方密级不足 =================
        low = json.loads(json.dumps(res["pack"]))
        low["items"][0]["subject"] = subj_c
        low["pack_id"] = "pack-lowclear0001"
        resign(low)
        r5 = evidence.import_pack(cg_c, low, swarm=swarm, signers_file=sf_b)
        check("导入方密级不足 ⇒ 跳过而不抛异常",
              r5.get("ok") is True and r5.get("imported") == 0 and r5.get("skipped") >= 1,
              f"imported={r5.get('imported')} skipped={r5.get('skipped')}")
        check("导入方密级不足 ⇒ 不降级落明文",
              scan_plaintext(root_c, CANARY) == [], scan_plaintext(root_c, CANARY))
        check("导入方密级不足 ⇒ 整包不归档、收件箱无 private 明文",
              not r5.get("archived") and bool(r5.get("archive_skipped"))
              and scan_plaintext(swarm, CANARY) == [],
              f"archived={r5.get('archived')!r} hits={scan_plaintext(swarm, CANARY)}")
    finally:
        if saved is not None:
            if mutate == "drop_sensitivity":
                evidence._node_sensitivity = saved
            elif mutate == "trust_item":
                evidence._item_sensitivity = saved
            elif mutate == "allow_archive":
                evidence._pack_has_unarchivable = saved
        for cg in (locals().get("cg_a"), locals().get("cg_b"), locals().get("cg_c")):
            try:
                if cg is not None:
                    cg.close()
            except Exception:  # noqa: BLE001
                pass
        shutil.rmtree(tmp, ignore_errors=True)
        for k in ("MDCG_THEORY_FILE", "MDCG_SIGNER_KEY_FILE"):
            os.environ.pop(k, None)

    tag = f"（变异 {mutate}）" if mutate else ""
    print(f"\n证据包密级守卫{tag}：{PASS} pass / {FAIL} fail")
    if FAILS:
        print("失败项：" + "；".join(FAILS))
        return 1
    return 0


if __name__ == "__main__":
    m = ""
    for a in sys.argv[1:]:
        if a.startswith("--mutate="):
            m = a.split("=", 1)[1]
    raise SystemExit(main(m))
