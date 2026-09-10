# -*- coding: utf-8 -*-
"""连接层 + 签名接口端到端测试（P23 · 蜂群互联层1 / 裁决 D-4）。

验证目标：
  ① 签名接口契约：注册表、fail-closed、往返、篡改检测、工程侧注入
  ② 子系统策略：未声明用默认；`sign_on` 决定是否签；验签失败处置
  ③ 连接层：握手建档 / 版本对齐 → cap / 观察期
  ④ P_trust：升不超 cap（不可自放大）、降快于升、反例击穿、衰减回归
  ⑤ 状态机：promote / degrade / isolate / withdraw + 全程留痕
  ⑥ 签名与连接层联动：要求对端签而缺失 → 拒；验签失败 → 降级

运行：python -m md_cg.test_p23_links
"""
from __future__ import annotations

import os
import shutil
import tempfile
import time

from . import links, signer, theory, tokens

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
    except (links.LinkError, signer.SignerError) as e:
        return True, str(e)


def main():
    tmp = tempfile.mkdtemp(prefix="mdcg_links_")
    tf = os.path.join(tmp, "theory.json")
    lf = os.path.join(tmp, "_links.json")
    sf = os.path.join(tmp, "_signers.json")
    kf = os.path.join(tmp, "_signer.key")
    os.environ["MDCG_THEORY_FILE"] = tf
    os.environ["MDCG_LINKS_FILE"] = lf
    os.environ["MDCG_SIGNERS_FILE"] = sf
    os.environ["MDCG_SIGNER_KEY_FILE"] = kf
    os.environ.pop("MDCG_SIGNER", None)
    os.environ.pop("MDCG_SIGNER_MODULE", None)

    try:
        theory.declare("3.4", accepted=["3.4", "3.3"], path=tf)

        # ================= ① 签名接口契约 =================
        reg = signer.list_signers()
        check("注册表含内置签名器",
              "null" in reg["signers"] and "hmac-local" in reg["signers"],
              str(reg["signers"]))
        check("默认签名器为 hmac-local", reg["default"] == "hmac-local")

        dn, msg = raises(signer.get_signer, "no-such-signer")
        check("未注册签名器 → 拒绝（fail-closed，不静默降级）", dn, msg)

        s = signer.get_signer()
        payload = b"hello-swarm"
        sig = s.sign(payload, {"peer": "agent:a"})
        check("hmac-local 签名往返", s.verify(payload, sig, {"peer": "agent:a"}))
        check("篡改 payload → 验签失败",
              s.verify(b"hello-swarm!", sig, {"peer": "agent:a"}) is False)
        check("篡改 ctx → 验签失败",
              s.verify(payload, sig, {"peer": "agent:b"}) is False)
        check("签名不含密钥", "key" not in s.public(), str(s.public()))

        ns = signer.get_signer("null")
        check("null 签名器空签名通过", ns.verify(payload, "", None) is True)

        # 工程侧注入（D-4：企业 PKI / KMS 由工程项目实现）
        class CorpSigner(signer.Signer):
            name = "corp_pki"

            def sign(self, payload, ctx=None):
                return "corp." + str(len(signer.canonical(payload, ctx)))

            def verify(self, payload, signature, ctx=None):
                return signature == self.sign(payload, ctx)

        signer.register_signer("corp_pki", CorpSigner)
        check("工程侧可注册自定义签名器",
              "corp_pki" in signer.list_signers()["signers"])
        cs = signer.get_signer("corp_pki")
        check("自定义签名器往返",
              cs.verify(b"x", cs.sign(b"x", None), None) is True)
        check("内置签名器不可注销",
              raises(signer.unregister_signer, "hmac-local")[0])

        # ================= ② 子系统签名策略 =================
        pol = signer.policy_for("erp.approval", sf)
        check("未声明子系统 → 默认策略", pol["sign_on"] == ["handshake"]
              and pol["on_verify_fail"] == "degrade", str(pol))

        signer.set_policy("erp.approval", path=sf, signer="hmac-local",
                          sign_on=["handshake", "evidence"],
                          require_peer_signature=True,
                          on_verify_fail="isolate")
        pol = signer.policy_for("erp.approval", sf)
        check("set_policy 落盘生效",
              pol["signer"] == "hmac-local"
              and "evidence" in pol["sign_on"]
              and pol["require_peer_signature"] is True
              and pol["on_verify_fail"] == "isolate", str(pol))

        r = signer.sign_for("erp.approval", b"p", action="withdrawal", path=sf)
        check("策略未列 action → 不签名", r["signed"] is False, r["reason"])
        r = signer.sign_for("erp.approval", b"p", action="handshake", path=sf)
        check("策略列入 action → 签名", r["signed"] is True and bool(r["signature"]))

        v = signer.verify_for("erp.approval", b"p", "bad", action="handshake",
                              path=sf)
        check("验签失败 → 返回处置档位",
              v["ok"] is False and v["on_fail"] == "isolate", str(v))

        # ================= ③ 连接层：握手与版本对齐 =================
        h = links.handshake("node-b", peer_theory={"version": "3.4"},
                            position_map={"record": "record"}, path=lf,
                            signers_file=sf)
        lk = h["link"]
        check("握手建档 → probation", lk["status"] == "probation")
        check("初始 P_trust = 0.8", lk["p_trust"] == links.P_TRUST_INIT,
              str(lk["p_trust"]))
        check("版本对齐 → cap=0.8", lk["p_trust_cap"] == links.CAP_ALIGNED)
        check("主体 id 规范化", lk["peer_node_id"] == "agent:node-b",
              lk["peer_node_id"])
        check("握手留痕（宪章第二十八条）",
              any(a["action"] == "handshake" for a in lk["audit"]))

        h2 = links.handshake("node-c", peer_theory={"version": "9.9"},
                             position_map={"record": "record"}, path=lf,
                             signers_file=sf)
        check("版本不在认可集合 → cap=0.3",
              h2["link"]["p_trust_cap"] == links.CAP_MISALIGNED,
              str(h2["link"]["p_trust_cap"]))
        check("版本不符 → 保持观察期",
              h2["link"]["status"] == "probation")

        h3 = links.handshake("node-d", peer_theory={"version": "3.4"}, path=lf,
                             signers_file=sf)
        check("未声明单元映射 → cap≤0.6",
              h3["link"]["p_trust_cap"] == links.CAP_INCOMPLETE,
              str(h3["link"]["p_trust_cap"]))

        h4 = links.handshake("node-e", peer_theory={"version": "3.4"},
                             position_map={"record": "record"},
                             declared_charter=False, path=lf,
                             signers_file=sf)
        check("未声明宪章 → 观察期翻倍",
              h4["link"]["probation_until"] - h4["link"]["created_at"]
              == links.PROBATION_SECONDS * 2)

        dn, msg = raises(links.promote, "node-b", path=lf)
        check("观察期未满 → 拒绝转正", dn, msg)

        # ================= ④ P_trust 行为 =================
        for i in range(10):
            links.observe("node-b", evidence=f"ok-{i}", path=lf, signers_file=sf)
        lk = links.get("node-b", path=lf)
        check("正证据累积", lk["evidence_count"] == 10, str(lk["evidence_count"]))
        check("不可自放大：P_trust 不超 cap",
              lk["p_trust"] <= lk["p_trust_cap"],
              f"{lk['p_trust']} <= {lk['p_trust_cap']}")

        lk6 = links.get("node-d", path=lf)
        for i in range(10):
            links.observe("node-d", evidence=f"ok-{i}", path=lf, signers_file=sf)
        lk6 = links.get("node-d", path=lf)
        check("cap=0.6 的连接刷不过 0.6", lk6["p_trust"] <= 0.6,
              str(lk6["p_trust"]))

        before = links.get("node-b", path=lf)["p_trust"]
        links.observe("node-b", evidence="bad-1", positive=False, path=lf,
                      signers_file=sf)
        after = links.get("node-b", path=lf)["p_trust"]
        check("负证据降幅大于正证据升幅（降快于升）",
              round(before - after, 6) > links.UP_STEP,
              f"{before} -> {after}")

        links.observe("node-b", evidence="bad-2", positive=False, path=lf,
                      signers_file=sf)
        lk = links.get("node-b", path=lf)
        check("反例击穿：跌破阈值即降级",
              lk["status"] == "degraded", f"{lk['p_trust']} / {lk['status']}")
        check("降级留痕含条款",
              any("宪章第七条" in str(a.get("clause")) for a in lk["audit"]))

        # 衰减：模拟 30 天后向初值回归
        links.observe("node-c", evidence="recover", path=lf, signers_file=sf)
        future = time.time() + links.DECAY_DAYS * 86400
        d = links.decay_all(path=lf, now=future)
        check("衰减产生变更", d["count"] >= 1, str(d["count"]))
        check("衰减向初值回归（两侧都靠拢）",
              all(abs(c["to"] - links.P_TRUST_INIT)
                  < abs(c["from"] - links.P_TRUST_INIT)
                  for c in d["changed"]),
              str(d["changed"]))

        # ================= ⑤ 状态机 =================
        links.isolate("node-c", reason="持续异常", path=lf)
        lk = links.get("node-c", path=lf)
        check("isolate → P_trust 归零",
              lk["status"] == "isolated" and lk["p_trust"] == 0.0)
        check("isolate → cap 归零", lk["p_trust_cap"] == links.CAP_ISOLATED)

        links.withdraw("node-e", reason="声明退出", path=lf)
        check("withdraw → 状态迁移",
              links.get("node-e", path=lf)["status"] == "withdrawn")
        dn, msg = raises(links.observe, "node-e", evidence="x", path=lf)
        check("已退出连接不可再观测", dn, msg)

        links.degrade("node-d", reason="行为异常", path=lf)
        dn, msg = raises(links.promote, "node-d", path=lf)
        check("非 probation 不可转正", dn, msg)
        check("降级状态保持",
              links.get("node-d", path=lf)["status"] == "degraded")

        # ================= ⑥ 签名 × 连接层联动 =================
        # 策略要求对端签名（require_peer_signature=True）但未提供 → 拒绝
        dn, msg = raises(links.handshake, "node-f",
                         peer_theory={"version": "3.4"},
                         position_map={"record": "record"},
                         subsystem="erp.approval", path=lf, signers_file=sf)
        check("要求对端签名而缺失 → 握手被拒", dn, msg)

        # 提供合法签名 → 通过
        sgn = signer.get_signer("hmac-local", key_file=kf)
        pm = {"record": "record"}
        pay = links.handshake_payload("agent:node-g", {"version": "3.4"}, pm)
        good = sgn.sign(pay, {"peer": "agent:node-g", "action": "handshake"})
        h = links.handshake("node-g", peer_theory={"version": "3.4"},
                            position_map=pm, subsystem="erp.approval",
                            peer_signature=good, path=lf, signers_file=sf)
        check("提供合法对端签名 → 握手通过",
              h["ok"] and h["signature"]["ok"] is True, str(h["signature"]))
        check("连接记录留存双方签名",
              "self" in h["link"]["signatures"]
              and "peer" in h["link"]["signatures"])

        # 验签失败（on_verify_fail=isolate）→ 接入即隔离
        h = links.handshake("node-h", peer_theory={"version": "3.4"},
                            position_map=pm, subsystem="erp.approval",
                            peer_signature="hmac1.dead", path=lf,
                            signers_file=sf)
        check("验签失败 + isolate 策略 → 接入即隔离",
              h["link"]["status"] == "isolated", h["link"]["status"])

        # 宽松策略：验签失败 → degrade（不拒绝）
        signer.set_policy("crm", path=sf, sign_on=["handshake"],
                          on_verify_fail="degrade")
        h = links.handshake("node-i", peer_theory={"version": "3.4"},
                            position_map=pm, subsystem="crm",
                            peer_signature="hmac1.dead", path=lf,
                            signers_file=sf)
        check("验签失败 + degrade 策略 → 接入但降级",
              h["link"]["status"] == "degraded", h["link"]["status"])
        check("验签失败留痕",
              any("宪章第七条" in str(a.get("clause"))
                  for a in h["link"]["audit"]))

        # ================= ⑦ 自描述 =================
        cat = links.catalog()
        check("catalog 声明数值未标定",
              "未标定" in cat["p_trust"]["note"], cat["p_trust"]["note"])
        check("catalog 指向 D-4",
              "D-4" in cat["signature"]["decision"])
        check("ls 可按状态过滤",
              links.ls(path=lf, status="isolated")["count"] >= 1)

        # ================= ⑧ 权限派生（唯一核心权限不扩散） =================
        check("ALL_OPS 含 link", "link" in tokens.ALL_OPS)
        check("sustain 可执行 link（§3.3 维生职责派生）",
              "link" in tokens.role_spec("sustain")["ops_allow"])
        check("designer 覆盖 link",
              "*" in tokens.role_spec("designer")["ops_allow"])
        for role, spec in tokens.ROLE_SPECS.items():
            if role in ("designer", "sustain"):
                continue
            check(f"{role} 无 link 权限",
                  "link" not in (spec.get("ops_allow") or []),
                  str(spec.get("ops_allow")))

    finally:
        for k in ("MDCG_THEORY_FILE", "MDCG_LINKS_FILE", "MDCG_SIGNERS_FILE",
                  "MDCG_SIGNER_KEY_FILE"):
            os.environ.pop(k, None)
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"\nP23 连接层：{PASS} passed, {FAIL} failed")
    if FAILS:
        print("失败项：" + "、".join(FAILS))
    return 1 if FAIL else 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
