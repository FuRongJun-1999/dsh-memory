# -*- coding: utf-8 -*-
"""跨节点证据存储端到端测试（P24 · 蜂群互联 v0.3）。

验证目标：
  ① 节点身份与名片发现（两节点 id 不同；peers 互见）
  ② 证据包导出：只含本地原始观测、签名、禁止转手
  ③ 导入 fail-closed：结构非法 / 自导入 / 篡改 / 缺签名 / 未注册签名器
  ④ 落根与留痕：`source:<node>` 标签、拒收记录
  ⑤ 幂等：重复导入不产生新节点
  ⑥ **双节点隐式学习可复现**（v0.3 验收标准）：A↔B 互相观测 →
     各自 `infer_position` 能统计到对方的跨节点证据

运行：python -m md_cg.test_p24_evidence
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile

from . import evidence, identity, signer, theory

PASS = FAIL = 0
FAILS = []


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}" + (f"  · {detail}" if detail else ""))
    else:
        FAIL += 1
        FAILS.append(name)
        print(f"  [FAIL] {name}  · {detail}")


def raises(fn, *a, **kw):
    try:
        fn(*a, **kw)
        return False, ""
    except (evidence.EvidenceError, signer.SignerError) as e:
        return True, str(e)


def main():
    tmp = tempfile.mkdtemp(prefix="mdcg_evidence_")
    root_a = os.path.join(tmp, "nodeA")
    root_b = os.path.join(tmp, "nodeB")
    os.makedirs(root_a)
    os.makedirs(root_b)
    swarm = os.path.join(tmp, "swarm")
    sf_a = os.path.join(tmp, "A_signers.json")
    sf_b = os.path.join(tmp, "B_signers.json")
    kf = os.path.join(tmp, "shared.key")
    tf = os.path.join(tmp, "theory.json")
    os.environ["MDCG_THEORY_FILE"] = tf
    os.environ["MDCG_SIGNER_KEY_FILE"] = kf
    os.environ.pop("MDCG_SIGNER", None)
    os.environ.pop("MDCG_SIGNER_MODULE", None)
    os.environ.pop("MDCG_NODE_ID", None)

    try:
        theory.declare("3.4", accepted=["3.4", "3.3"], path=tf)
        # 两节点各自声明策略：都要对 evidence 签名（D-4 的智能体自决）
        signer.set_policy("swarm", path=sf_a,
                          sign_on=["handshake", "evidence"])
        signer.set_policy("swarm", path=sf_b,
                          sign_on=["handshake", "evidence"])

        cg_a = evidence._open_cg(root_a)
        cg_b = evidence._open_cg(root_b)
        nid_a = evidence.node_id(root_a)
        nid_b = evidence.node_id(root_b)
        subj_b = "agent:" + nid_b
        subj_a = "agent:" + nid_a

        # ================= ① 身份与名片 =================
        check("两节点身份不同（根派生）", nid_a != nid_b, f"{nid_a} / {nid_b}")
        pub = evidence.publish_card(root_a, swarm=swarm)
        check("发布名片成功", os.path.exists(pub["file"]), pub["file"])
        seen = evidence.peers(swarm, root=root_b)
        check("对端能发现本节点名片",
              any(c["node_id"] == nid_a for c in seen["peers"]),
              str([c["node_id"] for c in seen["peers"]]))
        self_view = evidence.peers(swarm, root=root_a)
        check("名片发现排除自身",
              all(c["node_id"] != nid_a for c in self_view["peers"]))

        # ================= ② 导出 =================
        identity.observe(cg_a, subj_b, "B 在跨节点测试中执行了校验并给出裁决",
                         tags=["verify"], verification_basis="data")
        res = evidence.export_pack(cg_a, swarm=swarm, signers_file=sf_a)
        pack = res["pack"]
        check("导出含本地观测", res["count"] == 1, f"count={res['count']}")
        check("证据包已签名", res["signed"] is True)
        check("签名不含密钥", "key" not in (pack.get("sig") or {}))
        check("包来源为本节点", pack["from_node"] == nid_a)

        # ================= ③ fail-closed =================
        r = evidence.import_pack(cg_a, dict(pack), swarm=swarm,
                                 signers_file=sf_a)
        check("拒绝自导入（来源即本节点）",
              r["ok"] is False and r["rejected"], r.get("reason", ""))

        bad = json.loads(json.dumps(pack))
        bad["items"][0]["text"] = "被篡改的证据"
        r = evidence.import_pack(cg_b, bad, swarm=swarm, signers_file=sf_b)
        check("篡改证据 → 拒收", r["ok"] is False and r["rejected"],
              r.get("reason", ""))

        nosig = json.loads(json.dumps(pack))
        nosig["sig"]["signature"] = ""
        r = evidence.import_pack(cg_b, nosig, swarm=swarm, signers_file=sf_b)
        check("缺签名 → 拒收", r["ok"] is False, r.get("reason", ""))

        broken = json.loads(json.dumps(pack))
        broken["kind"] = "not.a.pack"
        r = evidence.import_pack(cg_b, broken, swarm=swarm, signers_file=sf_b)
        check("结构非法 → 拒收", r["ok"] is False, r.get("reason", ""))

        old = signer.set_policy("swarm", path=sf_a, signer="no-such-signer")
        dn, msg = raises(evidence.export_pack, cg_a, swarm=swarm,
                         signers_file=sf_a)
        check("未注册签名器 → 导出失败（fail-closed）", dn, msg)
        signer.set_policy("swarm", path=sf_a, signer="hmac-local")

        signer.set_policy("swarm", path=sf_a, sign_on=["handshake"])
        dn, msg = raises(evidence.export_pack, cg_a, swarm=swarm,
                         signers_file=sf_a)
        check("策略未开 evidence 签名 → 拒绝产出无签名包", dn, msg)
        signer.set_policy("swarm", path=sf_a, sign_on=["handshake", "evidence"])

        rej = os.path.join(evidence.inbox_dir(swarm), "_rejected.jsonl")
        check("拒收留痕落盘（自导入/篡改/缺签名/结构非法）",
              os.path.exists(rej) and
              len(open(rej, encoding="utf-8").read().strip().splitlines()) >= 4,
              rej)

        # ================= ④ 正常导入 =================
        # 先物化索引：模拟真实根（已有 _index.json）。否则重开时会全量重扫目录，
        # 掩盖「脏索引未落盘」的缺陷（AEIS 根实测踩坑）。
        cg_b.compact_index()
        r = evidence.import_pack(cg_b, pack, swarm=swarm, signers_file=sf_b)
        check("验签通过 → 导入成功", r["ok"] is True and r["imported"] == 1,
              f"imported={r.get('imported')}")
        got = evidence.evidence(cg_b, subject=subj_b, source=nid_a)
        check("落根本根并带 source 标签", got["count"] == 1, str(got["count"]))
        check("来源标签正确",
              got["evidence"][0]["source"] == nid_a, str(got["evidence"][0]))

        pos_b = identity.infer_position(cg_b, subj_b)
        check("跨节点证据参与位置推断（他证可见）",
              pos_b["evidence_count"] >= 1 and pos_b["position"] != "unknown",
              str(pos_b))

        # ================= ④b 跨进程持久化（重开图仍可见） =================
        cg_a.close()
        cg_b.close()
        cg_a = evidence._open_cg(root_a)
        cg_b = evidence._open_cg(root_b)
        disk = evidence.evidence(cg_b, subject=subj_b, source=nid_a)
        check("重开图后跨节点证据仍在（索引已落盘）",
              disk["count"] == 1, f"count={disk['count']}")
        pos_disk = identity.infer_position(cg_b, subj_b)
        check("重开后他证仍参与位置推断",
              pos_disk["evidence_count"] >= 1
              and pos_disk["position"] != "unknown", str(pos_disk))
        self_disk = identity.infer_position(cg_a, subj_b)
        check("A 侧自身观测亦落盘（重开可见）",
              self_disk["evidence_count"] >= 1, str(self_disk))

        # ================= ⑤ 幂等 =================
        r2 = evidence.import_pack(cg_b, pack, swarm=swarm, signers_file=sf_b)
        got2 = evidence.evidence(cg_b, subject=subj_b, source=nid_a)
        check("重复导入幂等（不新增节点）",
              r2["ok"] and got2["count"] == got["count"],
              f"{got['count']} -> {got2['count']}")

        # ================= ⑥ 禁止转手 =================
        bpack = evidence.export_pack(cg_b, swarm=swarm, signers_file=sf_b)
        check("已导入的跨节点证据不参与再次导出（防洗证据）",
              bpack["count"] == 0, f"count={bpack['count']}")

        # ================= ⑦ 双节点隐式学习可复现 =================
        identity.observe(cg_b, subj_a, "A 在跨节点测试中提供了版本声明与观测",
                         tags=["verify"], verification_basis="data")
        bpack = evidence.export_pack(cg_b, swarm=swarm, signers_file=sf_b)
        check("B 侧导出自己的观测", bpack["count"] == 1, str(bpack["count"]))
        ra = evidence.import_pack(cg_a, bpack["pack"], swarm=swarm,
                                  signers_file=sf_a)
        check("A 侧导入 B 的证据", ra["ok"] is True, ra.get("reason", ""))
        pos_a = identity.infer_position(cg_a, subj_a)
        check("双向互证：A 能看到 B 对 A 的观测",
              pos_a["evidence_count"] >= 1 and pos_a["position"] != "unknown",
              str(pos_a))
        both = (identity.infer_position(cg_a, subj_a)["evidence_count"] >= 1
                and identity.infer_position(cg_b, subj_b)["evidence_count"] >= 1)
        check("双节点隐式学习可复现（v0.3 验收）", both,
              "A 与 B 各自都能统计到对方的跨节点证据")

        # ================= ⑧ 自描述 =================
        cat = evidence.catalog()
        check("自描述声明诚实边界",
              "不是「证据为真」" in cat["honest_boundary"] and
              cat["blindspot"].startswith("§9.1"), str(cat["blindspot"]))
    finally:
        for cg in (locals().get("cg_a"), locals().get("cg_b")):
            try:
                if cg is not None:
                    cg.close()
            except Exception:  # noqa: BLE001
                pass
        shutil.rmtree(tmp, ignore_errors=True)
        for k in ("MDCG_THEORY_FILE", "MDCG_SIGNER_KEY_FILE"):
            os.environ.pop(k, None)

    print(f"\nP24 跨节点证据：{PASS} passed, {FAIL} failed")
    if FAILS:
        print("失败项：" + "；".join(FAILS))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
