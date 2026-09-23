# -*- coding: utf-8 -*-
"""issue #27 守卫：E041 身份识别（归一化 + 令牌凭据），非裸字符串相等。

病灶（2026-09-23 外部报告，两方独立复现）：E041「LLM 不得自己验证自己」
的三处判据是裸 `==`（attest / link 准入门 / recalibrate）——`agent-A` 编译、
`agent-a` 验证即可绕过并落盘（报告实测 WRITTEN=6）。而代码声明宣称
「结构级阻断，不依赖 prompt 自觉」。

修复（分层，处置强度如实声明）：
  ①身份归一比较（_same_subject：casefold + 去空白 + 去尾部括号注记）
    ——拦截报告表格全部同源变体（对旧实现能红）；
  ②verifier_token 凭据通路（mdcg 令牌 HMAC 验签，与 narrowed_principal
    同一信任源）——根本保障；令牌身份自证同样 E041；伪造令牌 fail-closed；
  ③诚实降级标注——无令牌时 AttestResult.verifier_identity =
    "self-reported"，下游策略/审计可识别。
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from md_cg import ccgc, tokens

PASS = 0
FAIL = 0
FAILS = []


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  OK   {name}")
    else:
        FAIL += 1
        FAILS.append(name)
        print(f"  FAIL {name}  {detail}")


def main():
    # 令牌文件隔离（issue/verify 经 TOKEN_FILE_ENV 同源）
    tf = tempfile.mkdtemp(prefix="mdcg_i27_tok_")
    tokens.TOKEN_FILE_ENV and os.environ.setdefault(tokens.TOKEN_FILE_ENV
                                                    if isinstance(tokens.TOKEN_FILE_ENV, str)
                                                    else "MDCG_TOKEN_FILE",
                                                    os.path.join(tf, "tokens.json"))
    tok_env = tokens.token_file()
    os.environ[tokens.TOKEN_FILE_ENV] = tok_env

    print("== X1 归一化：报告表格全形态拦截（attest 面，能红旧实现）==")
    compiled = "agent-A"
    variants = {
        "完全相同（旧实现也拦）": "agent-A",
        "小写（报告 BYPASS 形态）": "agent-a",
        "全大写": "AGENT-A",
        "括号注记后缀": "agent-A（复核）",
        "夹空白": " agent - a ",
    }
    for label, ver in variants.items():
        r = ccgc.attest("node_x", ccgc.ACCEPT, ver, compiled, ledger=False)
        want = label != "完全相同（旧实现也拦）"
        check(f"X1 {label} → E041{'（旧实现也拦，回归对照）' if not want else '（能红旧实现）'}",
              (not r.ok) and r.error.startswith("E041"),
              f"error={r.error[:80]}")
    check("X1z 自报身份诚实标注（verifier_identity=self-reported）",
          r.verifier_identity == "self-reported")

    print("== X2 verifier_token 凭据通路（根本保障）==")
    tk = tokens.issue("verifier", actor="external-reviewer",
                      path=tok_env)["token"]
    r2 = ccgc.attest("node_x", ccgc.ACCEPT, "随便自报的字符串",
                     "agent-A", ledger=False, verifier_token=tk)
    check("X2a 令牌身份覆盖自报（verifier=令牌 actor）",
          r2.ok and r2.verifier == "external-reviewer"
          and r2.verifier_identity == "token",
          f"ok={r2.ok} verifier={r2.verifier} id={r2.verifier_identity}")
    check("X2b 不同主体凭据放行（非自证）",
          r2.ok is True)

    print("== X3 令牌身份自证仍 E041（归一化形态）==")
    tk_self = tokens.issue("verifier", actor="Agent-a",
                           path=tok_env)["token"]
    r3 = ccgc.attest("node_x", ccgc.ACCEPT, "whoever",
                     "agent-A", ledger=False, verifier_token=tk_self)
    check("X3 令牌 actor 与编译方归一同源 → E041",
          (not r3.ok) and r3.error.startswith("E041"),
          f"error={r3.error[:80]}")

    print("== X4 伪造令牌 fail-closed ==")
    r4 = ccgc.attest("node_x", ccgc.ACCEPT, "whoever",
                     "agent-A", ledger=False,
                     verifier_token="mdcg1.verifier.tk_fake.badsecretvalue")
    check("X4 令牌验签失败 → 拒绝（不回落自报）",
          (not r4.ok) and "E041" in r4.error and "令牌" in r4.error,
          f"error={r4.error[:90]}")

    print("== X5 link 准入门归一化（能红旧实现）==")
    compiled_obj = ccgc.CompileResult(node_id="node_x", actor="agent-A")
    compiled_obj.success = True
    att_ok = ccgc.attest("node_x", ccgc.ACCEPT, "agent-a",
                         "agent-A", ledger=False)
    # attest 已拦（attest.ok=False），模拟旧数据面：手构 ok 签章验证 link 门自身
    att = ccgc.AttestResult(node_id="node_x", state=ccgc.ACCEPT,
                            verifier="agent-a", compiled_by="agent-A",
                            ok=True, token="t")
    lr = ccgc.link(compiled_obj, att, apply=False, actor="agent-A")
    check("X5 link 门大小写变体 → E041",
          any(e.startswith("E041") for e in lr.errors),
          f"errors={lr.errors[:2]}")

    print("== X6 不同主体正常放行（不误杀）==")
    att_ok2 = ccgc.attest("node_x", ccgc.ACCEPT, "external-reviewer",
                          "agent-A", ledger=False)
    check("X6 真不同主体签章 ok（召回面不回归）",
          att_ok2.ok and att_ok2.verifier_identity == "self-reported")

    print()
    if FAILS:
        print(f"FAILED: {len(FAILS)} 项 → {', '.join(FAILS)}")
        return 1
    print(f"ALL OK: {PASS} 项（issue #27 E041 身份识别守卫全绿）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
