# -*- coding: utf-8 -*-
# 功能名：Issue #1009 Item #5（SEC-07）统一三源复核证据闸与 Tier-3 人工签章回归守卫
# 生效条件：python -X utf8 -m md_cg.test_issue1009_dual_review_auth；隔离临时目录内运行，全断言通过退出 0、否则退出 1
# 子功能：①decided_by 自证覆盖拦截（含大小写/空白/括号注记/空身份）②MCP 与直调裸 reviewed_by 拦截（双审闸 + Tier-1/2/3 写门控 + edit 升层 + propose extra 夹带 + direct/token 直调 add）③伪造/越权/同主体/自签/跨单与跨节点重放/NullSigner/吊销与过期令牌拦截与明文脱敏 ④统一三源并集（proof ∪ ledger ∪ grant）及 Tier-3 self/anchor 人工签章救回正对照
# 执行：临时库 + 临时令牌文件 + 临时 HMAC 密钥，逐组断言并清理环境
# 验证方式：全部 PASS exit 0，否则 exit 1
# 不适用条件：不测试宿主层（DSH UI）交互弹窗；仅验证大脑库、review_evidence 与 MCP 分发面安全不变量
"""Issue #1009 Item #5 (SEC-07) unified 3-way review gate regression guard:
  accepted_units = proof ∪ ledger ∪ grant   (all 3 require actor != writer)

  - `decided_by` is audit metadata only and MUST NOT override authenticated `self.actor`.
  - Bare `reviewed_by` strings/unsigned dicts MUST NOT bypass writegate on either MCP
    or direct Python calls when no cryptographic proof / ledger evidence / code grant exists.
  - `sign_review_attestation` (non-NullSigner) supplies cryptographic `proof=` for `human`,
    rescuing Tier-3 (`self`/`anchor`) into a verifiable human-attestation path.
"""
import json
import os
import shutil
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from md_cg import mcp_server, review_evidence, tokens  # noqa: E402
from md_cg.mdcos import MdCGOS, MdCGSecure, sign_review_attestation  # noqa: E402
from md_cg.security import AccessDenied, Principal  # noqa: E402

_PASS, _FAIL = [], []

_CCG_BODY = (
    "# 功能名：双审鉴权回归样本\n"
    "# 生效条件：测试复核鉴权守卫运行时\n"
    "# 子功能：验证自证拦截与分层写门控\n"
    "# 执行：构造提案并经裁决路径校验\n"
    "# 验证方式：test\n"
    "# 不适用条件：非测试环境\n\n"
    "回归测试正文。"
)


def ok(cond, msg, detail=""):
    (_PASS if cond else _FAIL).append(msg)
    line = ("  PASS " if cond else "  FAIL ") + msg
    if detail and not cond:
        line += "  <- " + str(detail)[:220]
    print(line)


def _setup_env(tmp_dir):
    saved = dict(os.environ)
    for k in list(os.environ):
        if k.startswith("MDCG_"):
            del os.environ[k]
    os.environ.update(
        MDCG_ROOT=os.path.join(tmp_dir, "brain"),
        MDCG_STATE_ROOT=os.path.join(tmp_dir, "state"),
        MDCG_AUX_ROOT=os.path.join(tmp_dir, "aux_sidecar"),
        MDCG_DATA_ROOT=os.path.join(tmp_dir, "data"),
        MDCG_EXPORT_ROOT=tmp_dir,
        MDCG_TOKEN_FILE=os.path.join(tmp_dir, "aux_sidecar", "_tokens.json"),
        MDCG_SIGNER="hmac-local",
        MDCG_SIGNER_KEY_FILE=os.path.join(tmp_dir, "aux_sidecar", "_signer.key"),
        MDCG_SUSTAIN="0",
        MDCG_SLEEP="0",
        MDCG_WRITE_GATE="enforce",
        MDCG_REVIEW_CHANNELS="subagent,hive",
        MDCG_REVIEW_DUAL_CHECK="1",
    )
    return saved


def _restore_env(saved):
    os.environ.clear()
    os.environ.update(saved)


def _principal(actor, role="designer", clearance="secret", auth_mode="direct"):
    spec = tokens.role_spec(role)
    return Principal(
        actor=actor, role=role, clearance=clearance,
        can_write=spec["can_write"], can_admin=spec["can_admin"],
        layers_allow=spec["layers_allow"], ops_allow=spec["ops_allow"],
        auth_mode=auth_mode,
    )


def main():
    tmp_dir = tempfile.mkdtemp(prefix="sec07_guard_")
    saved_env = _setup_env(tmp_dir)
    cgs = []
    try:
        brain = os.path.join(tmp_dir, "brain")
        tok_file = os.environ["MDCG_TOKEN_FILE"]

        # Issue real distinct tokens in isolated token file
        tok_alice = tokens.issue(role="designer", actor="alice",
                                 clearance="secret", path=tok_file)["token"]
        p_alice_tok = tokens.verify_token(tok_alice, path=tok_file)
        tok_bob = tokens.issue(role="designer", actor="bob",
                               clearance="secret", path=tok_file,
                               _authorized_by=p_alice_tok)["token"]
        tok_reflect_ok = tokens.issue(role="reflect", actor="reflect-unit",
                                      clearance="internal", path=tok_file)["token"]
        tok_verify_ok = tokens.issue(role="verify", actor="verify-unit",
                                     clearance="internal", path=tok_file)["token"]
        tok_reflect_alice = tokens.issue(role="reflect", actor="alice",
                                         clearance="internal", path=tok_file)["token"]
        tok_reflect_twin = tokens.issue(role="reflect", actor="twin-bot",
                                        clearance="internal", path=tok_file)["token"]
        tok_verify_twin = tokens.issue(role="verify", actor="twin-bot",
                                       clearance="internal", path=tok_file)["token"]
        rev_rec = tokens.issue(role="reflect", actor="reflect-revoked",
                               clearance="internal", path=tok_file)
        tok_reflect_revoked = rev_rec["token"]
        tokens.revoke(rev_rec["token_id"], path=tok_file)
        tok_verify_expired = tokens.issue(role="verify", actor="verify-expired",
                                          clearance="internal", ttl=-10,
                                          path=tok_file)["token"]

        p_bob_tok = tokens.verify_token(tok_bob, path=tok_file)
        p_bob_direct = _principal("bob", "designer", "secret", auth_mode="direct")
        p_alice_direct = _principal("alice", "designer", "secret", auth_mode="direct")

        cg_alice_tok = MdCGSecure(brain, principal=p_alice_tok, autoflush=1)
        cg_bob_tok = MdCGSecure(brain, principal=p_bob_tok, autoflush=1)
        cg_bob_direct = MdCGSecure(brain, principal=p_bob_direct, autoflush=1)
        cg_alice_direct = MdCGSecure(brain, principal=p_alice_direct, autoflush=1)
        cgs.extend([cg_alice_tok, cg_bob_tok, cg_bob_direct, cg_alice_direct])

        # ==============================================================
        print("== A: decided_by 自证覆盖拦截（self_review_forbidden）")
        # ==============================================================
        bare = MdCGOS.__new__(MdCGOS)
        bare.actor = "alice"
        r_a1 = bare._dual_review_verdict(
            {"pid": "p_a1", "actor": "alice"}, "accept",
            decided_by="bob", reviewed_by=["reflect", "verify"],
        )
        ok(r_a1.get("ok") is False and r_a1.get("error") == "self_review_forbidden"
           and r_a1.get("decided_by") == "alice"
           and r_a1.get("decided_by_claimed") == "bob",
           "A1 伪造 decided_by=bob 无法绕过 self.actor=alice 自证检查", r_a1)

        bare2 = MdCGOS.__new__(MdCGOS)
        bare2.actor = "alice(复核)"
        r_a2 = bare2._dual_review_verdict(
            {"pid": "p_a2", "actor": "  ALICE  "}, "accept",
            decided_by="carol", reviewed_by=["reflect", "verify"],
        )
        ok(r_a2.get("ok") is False and r_a2.get("error") == "self_review_forbidden",
           "A2 大小写/空白/括号注记变体自证同样被拒", r_a2)

        bare_empty = MdCGOS.__new__(MdCGOS)
        bare_empty.actor = ""
        r_a3 = bare_empty._dual_review_verdict(
            {"pid": "p_a3", "actor": "alice"}, "accept",
            decided_by="bob", reviewed_by=["reflect", "verify"],
        )
        ok(r_a3.get("ok") is False and r_a3.get("error") == "self_review_forbidden"
           and r_a3.get("decided_by") == "",
           "A3 空 self.actor（无鉴权身份）fail-closed 拒绝，不回落入参 decided_by", r_a3)

        bare3 = MdCGOS.__new__(MdCGOS)
        bare3.actor = "alice"
        r_a4 = bare3._dual_review_verdict(
            {"pid": "p_a4", "actor": "alice", "proposer": "other"}, "accept",
            decided_by="other", reviewed_by=["reflect", "verify"],
        )
        ok(r_a4.get("ok") is False and r_a4.get("error") == "self_review_forbidden",
           "A4 item 同时含 actor=alice 与 proposer=other 时仍拦截 alice 自证", r_a4)

        pid_a5 = cg_alice_direct.propose("a5_own_k", _CCG_BODY + " A5", layer="knowledge")
        r_a5_py = cg_alice_direct.review_decide(
            pid_a5, "accept", decided_by="bob", reviewed_by=["reflect", "verify"])
        r_a5_mcp = mcp_server.call_tool(cg_alice_tok, "mdcg_review_decide", {
            "pid": pid_a5, "decision": "accept",
            "decided_by": "bob", "reviewed_by": ["reflect", "verify"],
        })
        ok(r_a5_py.get("error") == "self_review_forbidden"
           and r_a5_mcp.get("error") == "self_review_forbidden"
           and cg_alice_tok.get("a5_own_k") is None,
           "A5 端到端直调与 MCP 伪造 decided_by 均被拒且未落盘", (r_a5_py, r_a5_mcp))

        # ==============================================================
        print("== B: MCP 与直调未签名 reviewed_by 拦截（无证据一律拒）")
        # ==============================================================
        pid_b1 = cg_alice_tok.propose("b1_self", _CCG_BODY + " B1", layer="self")
        r_b1 = mcp_server.call_tool(cg_bob_tok, "mdcg_review_decide", {
            "pid": pid_b1, "decision": "accept",
            "reviewed_by": ["reflect", "verify", "human"],
        })
        ok(r_b1.get("ok") is False and r_b1.get("error") == "dual_check_required"
           and r_b1.get("missing") == ["reflect", "verify"]
           and bool(r_b1.get("unverified_reviewed_by"))
           and cg_bob_tok.get("b1_self") is None,
           "B1 MCP mdcg_review_decide 裸数组 ['reflect','verify','human'] 被双审闸拒绝", r_b1)

        pid_b2 = cg_alice_tok.propose("b2_anchor", _CCG_BODY + " B2", layer="anchor")
        r_b2 = mcp_server.call_tool(cg_bob_tok, "cg", {
            "op": "review", "action": "decide",
            "pid": pid_b2, "decision": "accept",
            "reviewed_by": [{"unit": "reflect"}, {"unit": "verify"}, {"unit": "human"}],
        })
        ok(r_b2.get("ok") is False and r_b2.get("error") == "dual_check_required"
           and cg_bob_tok.get("b2_anchor") is None,
           "B2 MCP cg(op=review) 未签名字典被拒且 anchor 节点未落盘", r_b2)

        # B3: Dual check OFF, only writegate enforce -> raw MCP reviewed_by still blocked
        # (including Tier-2 structural: MCP bare strings NEVER get code_grant!)
        pid_b3_struct = cg_alice_tok.propose("b3_struct", _CCG_BODY + " B3s", layer="structural")
        os.environ["MDCG_REVIEW_DUAL_CHECK"] = "0"
        try:
            for label, tool, payload, nid_x, cg_call in (
                ("B3a mdcg_review_decide self (auth_mode=direct)", "mdcg_review_decide",
                 {"pid": pid_b1, "decision": "accept",
                  "reviewed_by": ["reflect", "verify", "human"]},
                 "b1_self", cg_bob_direct),
                ("B3b cg(op=review) anchor (auth_mode=token)", "cg",
                 {"op": "review", "action": "decide", "pid": pid_b2, "decision": "accept",
                  "reviewed_by": ["reflect", "verify", "human"]},
                 "b2_anchor", cg_bob_tok),
                ("B3c mdcg_review_decide structural (MCP 不发裸 grant)", "mdcg_review_decide",
                 {"pid": pid_b3_struct, "decision": "accept",
                  "reviewed_by": ["reflect", "verify"]},
                 "b3_struct", cg_bob_tok),
            ):
                blocked = False
                err_msg = ""
                try:
                    out_b3 = mcp_server.call_tool(cg_call, tool, payload)
                    err_msg = str(out_b3)
                except AccessDenied as exc:
                    blocked = "分层复核闸" in str(exc)
                    err_msg = str(exc)
                ok(blocked and cg_bob_tok.get(nid_x) is None,
                   f"{label} 关双审时仍被写门控拒绝且未落盘", err_msg)

            # B4: edit escalation contextual -> self over MCP
            pid_b4 = cg_alice_tok.propose("b4_esc", _CCG_BODY + " B4", layer="contextual")
            b4_blocked = False
            try:
                mcp_server.call_tool(cg_bob_tok, "mdcg_review_decide", {
                    "pid": pid_b4, "decision": "edit",
                    "edits": {"layer": "self"},
                    "reviewed_by": ["reflect", "verify", "human"],
                })
            except AccessDenied as exc:
                b4_blocked = "分层复核闸" in str(exc)
            ok(b4_blocked and cg_bob_tok.get("b4_esc") is None,
               "B4 MCP edit 升层到 self + 伪造 reviewed_by 被 Tier-3 写门控拒绝")

            # B5: Direct MdCGSecure.add under BOTH token AND direct cannot self-attest bare strings
            b5_self_blocked = False
            b5_anchor_blocked = False
            b5_direct_k_blocked = False
            try:
                cg_bob_tok.add("b5_self_add", _CCG_BODY + " B5s", layer="self",
                               reviewed_by=["reflect", "verify", "human"])
            except AccessDenied as exc:
                b5_self_blocked = "分层复核闸" in str(exc)
            try:
                cg_bob_tok.add("b5_anchor_add", _CCG_BODY + " B5a", layer="anchor",
                               reviewed_by=["reflect", "verify", "human"])
            except AccessDenied as exc:
                b5_anchor_blocked = "分层复核闸" in str(exc)
            try:
                cg_bob_direct.add("b5_direct_k", _CCG_BODY + " B5k", layer="knowledge",
                                  reviewed_by=["reflect"])
            except AccessDenied as exc:
                b5_direct_k_blocked = "分层复核闸" in str(exc)
            ok(b5_self_blocked and b5_anchor_blocked and b5_direct_k_blocked
               and cg_bob_tok.get("b5_self_add") is None
               and cg_bob_tok.get("b5_anchor_add") is None
               and cg_bob_direct.get("b5_direct_k") is None,
               "B5 token 与受信任 direct 直调 add 无证据传裸 reviewed_by 均被拒")

            # B6: Smuggling reviewed_by via propose(**kw) -> item["extra"]
            pid_b6 = cg_alice_tok.propose(
                "b6_smuggle", _CCG_BODY + " B6", layer="self",
                reviewed_by=["reflect", "verify", "human"],
            )
            b6_blocked = False
            try:
                mcp_server.call_tool(cg_bob_tok, "mdcg_review_decide", {
                    "pid": pid_b6, "decision": "accept",
                })
            except AccessDenied as exc:
                b6_blocked = "分层复核闸" in str(exc)
            ok(b6_blocked and cg_bob_tok.get("b6_smuggle") is None,
               "B6 经 propose extra 夹带 reviewed_by 被剥离且被写门控拒绝")

            # B7: Server MDCG_REVIEWERS=reflect + MCP forged human -> cannot escalate
            os.environ["MDCG_REVIEWERS"] = "reflect"
            try:
                b7_blocked = False
                try:
                    mcp_server.call_tool(cg_bob_tok, "mdcg_review_decide", {
                        "pid": pid_b1, "decision": "accept",
                        "reviewed_by": ["reflect", "verify", "human"],
                    })
                except AccessDenied as exc:
                    b7_blocked = "分层复核闸" in str(exc)
                ok(b7_blocked and cg_bob_tok.get("b1_self") is None,
                   "B7 服务端仅配 MDCG_REVIEWERS=reflect 时 MCP 伪造 human 无法提权写 self")
            finally:
                os.environ.pop("MDCG_REVIEWERS", None)

            # B8: Direct review_decide with bare ['reflect','verify','human'] on Tier-3 self
            # MUST still fail closed because grant never authorizes human without signed proof!
            b8_blocked = False
            try:
                cg_bob_direct.review_decide(
                    pid_b1, "accept", reviewed_by=["reflect", "verify", "human"])
            except AccessDenied as exc:
                b8_blocked = "human" in str(exc) or "分层复核闸" in str(exc)
            ok(b8_blocked and cg_bob_direct.get("b1_self") is None
               and getattr(cg_bob_direct, "_review_grant", None) is None,
               "B8 直调 review_decide 裸传 human 无签章仍被 Tier-3 拒且不残留 _review_grant")
        finally:
            os.environ["MDCG_REVIEW_DUAL_CHECK"] = "1"

        # ==============================================================
        print("== C: 凭据与签章防伪（伪造/越权/自证/同主体/重放/NullSigner/吊销过期）")
        # ==============================================================
        fake_secret = "mdcg1.reflect.tk_fake.dummysecretvalue999"
        r_c1 = mcp_server.call_tool(cg_bob_tok, "mdcg_review_decide", {
            "pid": pid_b1, "decision": "accept",
            "reviewed_by": [{"unit": "reflect", "token": fake_secret},
                            {"token": tok_verify_ok}],
        })
        ok(r_c1.get("error") == "dual_check_required"
           and "reflect" in (r_c1.get("missing") or [])
           and fake_secret not in json.dumps(r_c1, ensure_ascii=False),
           "C1 伪造令牌被拒且返回体不回显令牌明文", r_c1)

        r_c2 = mcp_server.call_tool(cg_bob_tok, "mdcg_review_decide", {
            "pid": pid_b1, "decision": "accept",
            "reviewed_by": [{"unit": "verify", "token": tok_reflect_ok},
                            {"unit": "human", "token": tok_bob}],
        })
        ok(r_c2.get("error") == "dual_check_required"
           and set(r_c2.get("missing") or []) == {"reflect", "verify"},
           "C2 reflect 令牌冒充 verify / designer 令牌冒充 human 均被拒", r_c2)

        r_c3 = mcp_server.call_tool(cg_bob_tok, "mdcg_review_decide", {
            "pid": pid_b1, "decision": "accept",
            "reviewed_by": [{"token": tok_reflect_alice},
                            {"token": tok_verify_ok}],
        })
        # Also test writer self-signing human attestation on direct add()
        c3_self_sig_blocked = False
        try:
            cg_bob_tok.add(
                "c3_self_sig", _CCG_BODY + " C3", layer="self",
                reviewed_by=[
                    {"token": tok_reflect_ok},
                    {"token": tok_verify_ok},
                    sign_review_attestation("", "human", "BOB (复核)", node_id="c3_self_sig"),
                ],
            )
        except AccessDenied as exc:
            c3_self_sig_blocked = "human" in str(exc) or "分层复核闸" in str(exc)
        ok(r_c3.get("error") == "dual_check_required"
           and r_c3.get("missing") == ["reflect"]
           and c3_self_sig_blocked and cg_bob_tok.get("c3_self_sig") is None,
           "C3 提案者自证 reflect 令牌与写入者自签 human（含大小写括号变体）均被拒", r_c3)

        r_c4 = mcp_server.call_tool(cg_bob_tok, "mdcg_review_decide", {
            "pid": pid_b1, "decision": "accept",
            "reviewed_by": [{"token": tok_reflect_twin},
                            {"token": tok_verify_twin}],
        })
        ok(r_c4.get("error") == "dual_check_required"
           and r_c4.get("missing") == ["verify"],
           "C4 同一主体 twin-bot 同时持 reflect/verify 双令牌被拒（防同侧互证）", r_c4)

        # C5: Cross-proposal AND cross-node replay of valid human signature
        sig_for_b1 = sign_review_attestation(pid_b1, "human", "human-op")
        sig_stripped = {k: v for k, v in sig_for_b1.items() if k != "pid"}
        sig_for_node_a = sign_review_attestation("", "human", "human-op", node_id="c5_node_a")
        c5_replay1 = c5_replay2 = c5_node_replay = False
        try:
            mcp_server.call_tool(cg_bob_tok, "mdcg_review_decide", {
                "pid": pid_b2, "decision": "accept",
                "reviewed_by": [{"token": tok_reflect_ok},
                                {"token": tok_verify_ok},
                                sig_for_b1],
            })
        except AccessDenied as exc:
            c5_replay1 = "human" in str(exc) or "分层复核闸" in str(exc)
        try:
            mcp_server.call_tool(cg_bob_tok, "mdcg_review_decide", {
                "pid": pid_b2, "decision": "accept",
                "reviewed_by": [{"token": tok_reflect_ok},
                                {"token": tok_verify_ok},
                                sig_stripped],
            })
        except AccessDenied as exc:
            c5_replay2 = "human" in str(exc) or "分层复核闸" in str(exc)
        try:
            cg_bob_tok.add(
                "c5_node_b", _CCG_BODY + " C5n", layer="self",
                reviewed_by=[{"token": tok_reflect_ok},
                             {"token": tok_verify_ok},
                             sig_for_node_a],
            )
        except AccessDenied as exc:
            c5_node_replay = "human" in str(exc) or "分层复核闸" in str(exc)
        ok(c5_replay1 and c5_replay2 and c5_node_replay
           and cg_bob_tok.get("b2_anchor") is None
           and cg_bob_tok.get("c5_node_b") is None,
           "C5 跨提案与跨节点重放 human 签章（带 pid / 剥离 pid / 错 node_id）均被拒")

        # C6: NullSigner disallowed
        os.environ["MDCG_SIGNER"] = "null"
        try:
            c6_sign_blocked = False
            try:
                sign_review_attestation(pid_b1, "human", "human-op")
            except ValueError:
                c6_sign_blocked = True
            c6_verify_blocked = False
            try:
                mcp_server.call_tool(cg_bob_tok, "mdcg_review_decide", {
                    "pid": pid_b1, "decision": "accept",
                    "reviewed_by": [{"token": tok_reflect_ok},
                                    {"token": tok_verify_ok},
                                    {"unit": "human", "actor": "human-op", "sig": "null-fake"}],
                })
            except AccessDenied:
                c6_verify_blocked = True
            ok(c6_sign_blocked and c6_verify_blocked,
               "C6 NullSigner 无法签发或通过复核签章验签（fail-closed）")
        finally:
            os.environ["MDCG_SIGNER"] = "hmac-local"

        # C7: Revoked & expired reviewer tokens rejected
        r_c7 = mcp_server.call_tool(cg_bob_tok, "mdcg_review_decide", {
            "pid": pid_b1, "decision": "accept",
            "reviewed_by": [{"token": tok_reflect_revoked},
                            {"token": tok_verify_expired}],
        })
        ok(r_c7.get("error") == "dual_check_required"
           and set(r_c7.get("missing") or []) == {"reflect", "verify"}
           and tok_reflect_revoked not in json.dumps(r_c7, ensure_ascii=False)
           and tok_verify_expired not in json.dumps(r_c7, ensure_ascii=False),
           "C7 已吊销与已过期复核令牌均被拒且不回显明文", r_c7)

        # ==============================================================
        print("== D: 正对照（统一三源 proof ∪ ledger ∪ grant 与 Tier-3 人工签章救回）")
        # ==============================================================
        # D1: Tier-2 structural with distinct reflect + verify tokens over MCP (proof)
        pid_d1 = cg_alice_tok.propose("d1_struct", _CCG_BODY + " D1", layer="structural")
        r_d1 = mcp_server.call_tool(cg_bob_tok, "mdcg_review_decide", {
            "pid": pid_d1, "decision": "accept",
            "decided_by": "audit-alias",
            "reviewed_by": [{"token": tok_reflect_ok}, {"token": tok_verify_ok}],
        })
        dec_text = open(cg_bob_tok.decisions_log, encoding="utf-8").read()
        d1_recs = [r for r in cg_bob_tok.decisions() if r.get("pid") == pid_d1]
        d1_node = cg_bob_tok.get("d1_struct")
        ok(r_d1.get("ok") is True and r_d1.get("node_id") == "d1_struct"
           and d1_node is not None
           and bool(d1_recs) and d1_recs[-1].get("actor") == "bob"
           and d1_recs[-1].get("decided_by_claimed") == "audit-alias"
           and len(d1_recs[-1].get("verified_reviewers") or []) == 2
           and tok_reflect_ok not in dec_text and tok_verify_ok not in dec_text
           and "reviewed_by" not in (d1_node.get("frontmatter") or {}),
           "D1 合法独立 reflect+verify 令牌通过结构层裁决，actor=bob、令牌不落盘", r_d1)

        # D2: Tier-3 self with valid reflect+verify tokens + raw unsigned 'human' -> still denied!
        d2_blocked = False
        try:
            mcp_server.call_tool(cg_bob_tok, "mdcg_review_decide", {
                "pid": pid_b1, "decision": "accept",
                "reviewed_by": [{"token": tok_reflect_ok},
                                {"token": tok_verify_ok},
                                "human"],
            })
        except AccessDenied as exc:
            d2_blocked = "human" in str(exc) or "分层复核闸" in str(exc)
        ok(d2_blocked and cg_bob_tok.get("b1_self") is None,
           "D2 合法 reflect+verify 令牌配裸字符串 'human' 仍被 Tier-3 self 写门控拒绝")

        # D3: Tier-3 self + anchor with valid reflect+verify tokens + signed human attestation (proof)
        r_d3_self = mcp_server.call_tool(cg_bob_tok, "cg", {
            "op": "review", "action": "decide",
            "pid": pid_b1, "decision": "accept",
            "reviewed_by": [
                {"token": tok_reflect_ok},
                {"token": tok_verify_ok},
                sign_review_attestation(pid_b1, "human", "human-op"),
            ],
        })
        ver_self = (cg_bob_tok.verify_review_record(r_d3_self.get("record_node_id", ""))
                    if r_d3_self.get("record_node_id") else {})
        r_d3_anchor = mcp_server.call_tool(cg_bob_tok, "mdcg_review_decide", {
            "pid": pid_b2, "decision": "accept",
            "reviewed_by": [
                {"token": tok_reflect_ok},
                {"token": tok_verify_ok},
                sign_review_attestation(pid_b2, "human", "human-op"),
            ],
        })
        ok(r_d3_self.get("ok") is True and cg_bob_tok.get("b1_self") is not None
           and ver_self.get("ok") is True
           and r_d3_anchor.get("ok") is True and cg_bob_tok.get("b2_anchor") is not None,
           "D3 合法独立令牌 + 有效人工签章通过 Tier-3 self/anchor 裁决且审计指纹一致",
           (r_d3_self, ver_self, r_d3_anchor))

        # D4: Direct trusted Python review_decide: grant for knowledge, grant ∪ proof for Tier-3 self
        pid_d4_k = cg_alice_direct.propose("d4_direct_k", _CCG_BODY + " D4k", layer="knowledge")
        r_d4_k = cg_bob_direct.review_decide(
            pid_d4_k, "accept", reviewed_by=["reflect", "verify"])
        pid_d4_s = cg_alice_direct.propose("d4_direct_self", _CCG_BODY + " D4s", layer="self")
        r_d4_s = cg_bob_direct.review_decide(
            pid_d4_s, "accept",
            reviewed_by=["reflect", "verify",
                         sign_review_attestation(pid_d4_s, "human", "human-op")])
        ok(r_d4_k.get("ok") is True and cg_bob_direct.get("d4_direct_k") is not None
           and r_d4_s.get("ok") is True and cg_bob_direct.get("d4_direct_self") is not None,
           "D4 直调 review_decide：knowledge 走 code_grant、Tier-3 self 走 code_grant ∪ proof(human)",
           (r_d4_k, r_d4_s))

        # D5: Direct add() for Tier-3 self via pure cryptographic proof (node_id-bound human sig)
        nid_d5 = cg_bob_tok.add(
            "d5_direct_self", _CCG_BODY + " D5", layer="self",
            reviewed_by=[
                {"token": tok_reflect_ok},
                {"token": tok_verify_ok},
                sign_review_attestation("", "human", "human-op", node_id="d5_direct_self"),
            ],
        )
        ok(bool(nid_d5) and cg_bob_tok.get("d5_direct_self") is not None,
           "D5 token 直调 add(self) 经纯 proof（双令牌 + node_id 绑定人工签章）救回 Tier-3", nid_d5)

        # D6: Unified ledger ∪ proof(human) + verify_claims(proof=...) actor normalization
        now = time.time()
        v_proof_ok = review_evidence.verify_claims(
            ["human"], actor="bob",
            proof={"human": {"actor": "human-op", "via": "sig", "signer": "hmac-local"}},
            now=now)
        v_proof_self = review_evidence.verify_claims(
            ["human"], actor="bob",
            proof={"human": {"actor": "BOB（复核）", "via": "sig", "signer": "hmac-local"}},
            now=now)
        # Write a normalized self-actor ledger entry + distinct codebuddy ledger entry
        with open(cg_bob_direct.decisions_log, "a", encoding="utf-8") as _f:
            _f.write(json.dumps({
                "t": now, "pid": "p_self_norm", "decision": "accept",
                "status": "accepted", "actor": "BOB (复核)", "issues": [],
                "redteam_verdict": "pass", "verify_hash": "vh_self",
                "record_hash": "rh_self",
            }, ensure_ascii=False) + "\n")
        v_ledger_self = review_evidence.verify_claims(
            ["reflect", "verify"], ledger_path=cg_bob_direct.decisions_log,
            actor="bob", now=now)
        with open(cg_bob_direct.decisions_log, "a", encoding="utf-8") as _f:
            _f.write(json.dumps({
                "t": now, "pid": "p_peer_ev", "decision": "accept",
                "status": "accepted", "actor": "codebuddy", "issues": [],
                "redteam_verdict": "pass", "verify_hash": "vh_peer",
                "record_hash": "rh_peer", "record_node_id": "rev_peer_r1",
            }, ensure_ascii=False) + "\n")
        nid_d6 = cg_bob_direct.add(
            "d6_ledger_proof_self", _CCG_BODY + " D6", layer="self",
            reviewed_by=[
                "reflect", "verify",
                sign_review_attestation("", "human", "human-op",
                                        node_id="d6_ledger_proof_self"),
            ],
        )
        ok(v_proof_ok["accepted"] == ["human"]
           and v_proof_ok["evidence"]["human"]["source"] == "proof"
           and v_proof_self["accepted"] == []
           and v_ledger_self["accepted"] == []
           and bool(nid_d6) and cg_bob_direct.get("d6_ledger_proof_self") is not None,
           "D6 verify_claims(proof=) 与 ledger ∪ proof(human) 联合过 Tier-3，且大小写/括号自证均拒",
           (v_proof_ok, v_proof_self, v_ledger_self, nid_d6))
    finally:
        for cg in cgs:
            try:
                cg.close()
            except Exception:
                pass
        _restore_env(saved_env)
        shutil.rmtree(tmp_dir, ignore_errors=True)

    print()
    print("issue #1009 SEC-07 双审鉴权守卫：%d 通过 / %d 失败" % (len(_PASS), len(_FAIL)))
    if _FAIL:
        for f in _FAIL:
            print("  -", f)
    return 0 if not _FAIL else 1


if __name__ == "__main__":
    raise SystemExit(main())
