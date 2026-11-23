# -*- coding: utf-8 -*-
# 功能名：结构层「外部协作确认」守卫（2026-11-22 使用者裁定：只有自我层可自签，结构层不行）
# 生效条件：python -X utf8 -m md_cg.test_issue1009_structural_external；隔离临时目录内运行，全断言通过退出 0、否则退出 1
# 子功能：①结构层 human 章由进程内默认 signer（hmac-local）签发 ⇒ 不采信、写被拒 ②结构层 human 章由部署侧工程 signer 签发 ⇒ 通过 ③自我层/锚点层 human 章由进程内默认 signer 签发 ⇒ 通过（AI 验证单元拿证据即可）④结构层缺 human ⇒ 点名缺失 ⑤档位表契约：tier2/tier3 都要求 human，差异只在签章来源
# 执行：临时库 + 临时令牌文件 + 临时 HMAC 密钥 + 进程内注册的 eng-ext 签名器，逐组断言并清理环境
# 验证方式：全部 PASS exit 0，否则 exit 1
# 不适用条件：不测跨机器托管私钥与真正的不可否认性（工程侧 signer 的真实密钥管理不在本库职责内）
"""结构层 vs 自我层的人工确认来源差异回归守卫。

裁定原话（2026-11-22）：
    「复核验证让 ai 的验证单元拿到证据做是可以。也只有自我层，结构层不行，
      这是需要外部协作确认的。」

落地公式：
  tier 3（self / anchor）  human 章：进程内 signer 可签 ⇒ AI 验证单元拿证据即可做；
  tier 2（structural）     human 章：必须由部署侧工程 signer 产出；
                           进程内默认 hmac-local 签的一律不采信（能自签=闸门可自改）。
"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from md_cg import signer as sg  # noqa: E402
from md_cg import tokens, writegate  # noqa: E402
from md_cg.mdcos import MdCGSecure, sign_review_attestation  # noqa: E402
from md_cg.security import AccessDenied  # noqa: E402

_PASS, _FAIL = [], []

_CCG_BODY = (
    "# 功能名：结构层外部确认回归样本\n"
    "# 生效条件：测试结构层签章来源守卫运行时\n"
    "# 子功能：验证结构层与自我层的 human 章来源差异\n"
    "# 执行：构造提案并经裁决路径校验\n"
    "# 验证方式：test\n"
    "# 不适用条件：非测试环境\n\n"
    "回归测试正文。"
)

_EXT_KEY = b"eng-ext-test-key-not-a-real-secret"


def ok(cond, msg, detail=""):
    (_PASS if cond else _FAIL).append(msg)
    line = ("  PASS " if cond else "  FAIL ") + msg
    if detail and not cond:
        line += "  <- " + str(detail)[:220]
    print(line)


"""同 HmacLocalSigner 的算法，名字不同 ⇒ 模拟部署侧工程 signer（密钥不在本进程默认密钥里）。"""


class _ExtSigner(sg.HmacLocalSigner):
    name = "eng-ext"


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
        MDCG_ALLOW_ROOT_ISSUE="1",   # 测试内自铸身份/复核令牌（隔离临时库）
    )
    return saved


def _restore_env(saved):
    os.environ.clear()
    os.environ.update(saved)


def main():
    tmp_dir = tempfile.mkdtemp(prefix="struct_ext_")
    saved_env = _setup_env(tmp_dir)
    if "eng-ext" not in sg.list_signers()["signers"]:
        sg.register_signer("eng-ext",
                           lambda key_file=None: _ExtSigner(key=_EXT_KEY))
    try:
        brain = os.path.join(tmp_dir, "brain")
        tok_file = os.environ["MDCG_TOKEN_FILE"]
        tok_reflect = tokens.issue(role="reflect", actor="reflect-unit",
                                   clearance="internal", path=tok_file)["token"]
        tok_verify = tokens.issue(role="verify", actor="verify-unit",
                                  clearance="internal", path=tok_file)["token"]

        print("== A 档位表契约：tier2 / tier3 都要求 human")
        ok(writegate.REQUIRED_REVIEWERS[3] == ("reflect", "verify", "human"),
           "A1 tier3（self/anchor）要求 reflect+verify+human")
        ok(writegate.REQUIRED_REVIEWERS[2] == ("reflect", "verify", "human"),
           "A2 tier2（structural）同样要求 reflect+verify+human")
        ok(writegate.tier_of("structural") == 2 and writegate.tier_of("self") == 3,
           "A3 结构层 2 档、自我层 3 档（来源差异不在档位，在签章方）")

        print("== B 结构层：进程内 hmac-local 签的 human 章不采信")
        cg_a = MdCGSecure(brain, principal=tokens.verify_token(
            tokens.issue(role="designer", actor="alice", clearance="secret",
                         path=tok_file)["token"], path=tok_file), autoflush=1)
        cg_b = MdCGSecure(brain, principal=tokens.verify_token(
            tokens.issue(role="designer", actor="bob", clearance="secret",
                         path=tok_file)["token"], path=tok_file), autoflush=1)
        pid_b = cg_a.propose("b_struct_local", _CCG_BODY + " B", layer="structural")
        human_local = sign_review_attestation(pid_b, "human", "human-op")
        blocked, err = False, ""
        try:
            cg_b.review_decide(pid_b, "accept",
                               reviewed_by=[{"token": tok_reflect},
                                            {"token": tok_verify}, human_local])
        except AccessDenied as exc:
            blocked, err = True, str(exc)
        ok(blocked and cg_b.get("b_struct_local") is None,
           "B1 结构层 human 章由进程内 hmac-local 签发 ⇒ 写被拒", err)
        ok("human" in err, "B2 拒因点名缺失单元 human（不是笼统拒绝）", err)
        ok(getattr(cg_b, "_review_grant", None) is None, "B3 拒后不残留一次性授权")

        print("== C 结构层：部署侧工程 signer 签的 human 章 ⇒ 通过（外部协作确认）")
        pid_c = cg_a.propose("c_struct_ext", _CCG_BODY + " C", layer="structural")
        # 部署侧把 MDCG_SIGNER 配成工程 signer 后，签章的产生与验签都走该 signer
        # （这正是「外部协作确认」的落地形态：密钥与模块由部署方配置，不在进程内默认面）
        prev = os.environ.get("MDCG_SIGNER")
        os.environ["MDCG_SIGNER"] = "eng-ext"
        r_c = None
        ok_c = False
        try:
            human_ext = sign_review_attestation(pid_c, "human", "eng-op")
            try:
                r_c = cg_b.review_decide(pid_c, "accept",
                                         reviewed_by=[{"token": tok_reflect},
                                                      {"token": tok_verify}, human_ext])
                ok_c = bool(r_c) and r_c.get("ok") is True
            except AccessDenied as exc:
                r_c = str(exc)
        finally:
            os.environ["MDCG_SIGNER"] = prev or "hmac-local"
        ok(ok_c and cg_b.get("c_struct_ext") is not None,
           "C1 结构层 human 章由 eng-ext 工程 signer 签发 ⇒ 裁决通过并落盘", r_c)

        print("== D 自我层/锚点层：进程内 hmac-local 签的 human 章仍可通过（裁定：只有自我层可以）")
        pid_d = cg_a.propose("d_self_local", _CCG_BODY + " D", layer="self")
        human_d = sign_review_attestation(pid_d, "human", "human-op")
        r_d = None
        try:
            r_d = cg_b.review_decide(pid_d, "accept",
                                     reviewed_by=[{"token": tok_reflect},
                                                  {"token": tok_verify}, human_d])
        except AccessDenied as exc:
            r_d = str(exc)
        ok(bool(r_d) and r_d.get("ok") is True and cg_b.get("d_self_local") is not None,
           "D1 自我层 human 章由进程内 signer 签发仍通过（AI 验证单元拿证据即可做）", r_d)

        print("== E 结构层缺 human ⇒ 点名缺失（不因令牌齐备而放行）")
        pid_e = cg_a.propose("e_struct_nohuman", _CCG_BODY + " E", layer="structural")
        blocked_e, err_e = False, ""
        try:
            cg_b.review_decide(pid_e, "accept",
                               reviewed_by=[{"token": tok_reflect}, {"token": tok_verify}])
        except AccessDenied as exc:
            blocked_e, err_e = True, str(exc)
        ok(blocked_e and cg_b.get("e_struct_nohuman") is None and "human" in err_e,
           "E1 结构层双令牌齐备但无 human 仍被拒并点名", err_e)
    finally:
        for cg in list(locals().get("_cgs", ())):
            pass
        _restore_env(saved_env)

    print()
    print("通过 %d / 失败 %d" % (len(_PASS), len(_FAIL)))
    return 0 if not _FAIL else 1


if __name__ == "__main__":
    raise SystemExit(main())
