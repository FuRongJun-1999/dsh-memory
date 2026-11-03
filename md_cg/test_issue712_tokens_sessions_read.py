# -*- coding: utf-8 -*-
"""issue #712 签发侧接线守卫：sessions_read 的 issue/derive/verify/CLI/narrowed 全链路。

背景（2026-11-01）：0.9.18 起 `Principal.sessions_read` 的**读侧执行**已落地
（`mdcos` 读路径按它收窄，见 test_issue712_session_window_attribution），但**签发侧**
没有接线——`issue()`/`derive()` 签名不带它，落盘 rec 不存它，CLI 没有 `--sessions-read`，
`verify_token` 重建 Principal 时也不传它。⇒ 这把锁有锁体、有锁舌，没有锁眼。
本套断言钉住接线后的六段语义（与 security.Principal 文档口径逐字对齐）：

  G1 签发回环：issue(sessions_read=[s1,s2]) → 落盘 → verify → tuple(s1,s2)
  G2 缺省零变：不带该参数 = None = 不限读面（旧行为，同 layers 兼容口径）
  G3 特殊值：'*' 原样保留（读面语义见 session_recall 的 recent 段）
  G4 存量兼容：rec **没有**这个键（0.9.18~0.9.21 签发的真实令牌库）→ verify 不炸、None
  G5 派生只能收窄（与 N123 过期夹紧同构）：
     a 未指定=继承父界  b 交集非空取交集并记 clamped  c 交集空=TokenError（fail-closed）
     d 子请求'*'而父有界=夹紧为父界  e 父'*'=视同无界，子自设界生效  f 父 None 同 e
  G6 narrowed_principal 传导（附带 bug fix 回归钉）：owner 带读面限制时，
     as_unit 请求级收窄后的身份**必须仍带**同一限制——修复前此处漏传，静默放宽为不限。
  G7 CLI 面：issue/derive --sessions-read 逗号解析（复用 _csv_list），list 可见读面，
     verify 的 as_dict 输出含 sessions_read。

红基线：对未打补丁的 0.9.21 HEAD 运行本文件，G1 起即 `TypeError: unexpected keyword
argument 'sessions_read'` 成片转红（G4 会红在 verify 输出无读面键）——接线前这些
语义**没有合法来源**，断言不可能空转全绿。

运行：python -X utf8 -m md_cg.test_issue712_tokens_sessions_read
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import tempfile

from . import tokens
from .tokens import TokenError, issue, verify_token, derive, narrowed_principal, main

_PASS = []
_FAIL = []


def ok(cond, msg, extra=""):
    (_PASS if cond else _FAIL).append(msg)
    print(("  PASS " if cond else "  FAIL ") + msg + (("  ← " + str(extra)) if (extra and not cond) else ""))


def _tmp_tokfile(name="t"):
    d = tempfile.mkdtemp(prefix=f"mdcg-712-{name}-")
    return os.path.join(d, "_tokens.json")


def g1_roundtrip():
    print("\n== G1 签发回环 ==")
    tf = _tmp_tokfile("g1")
    r = issue("designer", sessions_read=["s1", "s2"], path=tf)
    ok(r.get("sessions_read") == ["s1", "s2"], "G1a issue 返回值携带读面（list 形态）", r.get("sessions_read"))
    p = verify_token(r["token"], path=tf)
    ok(p.sessions_read == ("s1", "s2"), "G1b verify → Principal.sessions_read tuple 化", p.sessions_read)


def g2_default_zero():
    print("\n== G2 缺省零变（旧行为） ==")
    tf = _tmp_tokfile("g2")
    r = issue("recorder", path=tf)
    ok(r.get("sessions_read") is None, "G2a issue 不带参数 → None", r.get("sessions_read"))
    p = verify_token(r["token"], path=tf)
    ok(p.sessions_read is None, "G2b verify → Principal 不限读面", p.sessions_read)


def g3_star():
    print("\n== G3 特殊值 '*' ==")
    tf = _tmp_tokfile("g3")
    r = issue("recorder", sessions_read=["*"], path=tf)
    p = verify_token(r["token"], path=tf)
    ok(p.sessions_read == ("*",), "G3 '*' 原样保留（全部读面语义在执行侧解释）", p.sessions_read)


def g4_legacy_record():
    print("\n== G4 存量兼容（rec 无此键） ==")
    tf = _tmp_tokfile("g4")
    r = issue("recorder", path=tf)
    with open(tf, encoding="utf-8") as f:
        data = json.load(f)
    data["tokens"][r["token_id"]].pop("sessions_read")          # 模拟 0.9.21 存量库
    with open(tf, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    try:
        p = verify_token(r["token"], path=tf)
        ok(p.sessions_read is None, "G4 缺键记录 verify 不炸且=不限（零闸变）", p.sessions_read)
    except TokenError as e:
        ok(False, "G4 缺键记录 verify 不炸且=不限（零闸变）", e)


def g5_derive():
    print("\n== G5 派生只能收窄 ==")
    tf = _tmp_tokfile("g5")
    par = issue("designer", sessions_read=["s1", "s2"], path=tf)
    # a 未指定 → 继承父界
    a = derive(par["token"], "recorder", path=tf)
    pa = verify_token(a["token"], path=tf)
    ok(pa.sessions_read == ("s1", "s2"), "G5a 子未指定=继承父界", pa.sessions_read)
    # b 交集
    b = derive(par["token"], "recorder", sessions_read=["s2", "s3"], path=tf)
    pb = verify_token(b["token"], path=tf)
    ok(pb.sessions_read == ("s2",), "G5b 交集非空取交集", pb.sessions_read)
    ok("sessions_read" in b.get("clamped", []), "G5b' 夹紧记录进 clamped", b.get("clamped"))
    # c 交集空 → 拒签（fail-closed）
    try:
        derive(par["token"], "recorder", sessions_read=["s9"], path=tf)
        ok(False, "G5c 交集空=TokenError（宁可拒签）")
    except TokenError:
        ok(True, "G5c 交集空=TokenError（宁可拒签）")
    # d 子请求 '*' 而父有界 → 夹紧回父界
    d = derive(par["token"], "recorder", sessions_read=["*"], path=tf)
    pd = verify_token(d["token"], path=tf)
    ok(pd.sessions_read == ("s1", "s2"), "G5d 子'*'遇父有界=夹紧为父界", pd.sessions_read)
    ok("sessions_read" in d.get("clamped", []), "G5d' 夹紧记录进 clamped", d.get("clamped"))
    # e 父 '*' → 视同无界，子自设界生效（#543 授权闸：非空库再签 designer 会被拒，
    # 每个父令牌用独立空库首启自举——这本身也是新库既有的正确姿势）
    tf_e = _tmp_tokfile("g5e")
    pstar = issue("designer", sessions_read=["*"], path=tf_e)
    e = derive(pstar["token"], "recorder", sessions_read=["s1"], path=tf_e)
    pe = verify_token(e["token"], path=tf_e)
    ok(pe.sessions_read == ("s1",), "G5e 父'*'=子可自设任意界", pe.sessions_read)
    # f 父 None 同 e
    tf_f = _tmp_tokfile("g5f")
    pnone = issue("designer", path=tf_f)
    f = derive(pnone["token"], "recorder", sessions_read=["s7"], path=tf_f)
    pf = verify_token(f["token"], path=tf_f)
    ok(pf.sessions_read == ("s7",), "G5f 父无界=子可自设任意界", pf.sessions_read)


def g6_narrowed():
    print("\n== G6 narrowed_principal 传导（bug fix 回归钉） ==")
    tf = _tmp_tokfile("g6")
    r = issue("designer", sessions_read=["s1", "s2"], path=tf)
    p = verify_token(r["token"], path=tf)
    q = narrowed_principal(p, "record")
    ok(q.sessions_read == ("s1", "s2"),
       "G6a owner 带限制 → as_unit 收窄身份仍带（修复前此处静默变 None=fail-open）",
       q.sessions_read)
    tf_b = _tmp_tokfile("g6b")
    r2 = issue("designer", path=tf_b)
    p2 = verify_token(r2["token"], path=tf_b)
    q2 = narrowed_principal(p2, "record")
    ok(q2.sessions_read is None, "G6b owner 无限制 → 收窄后仍无限制（不误伤）", q2.sessions_read)


def g7_cli():
    print("\n== G7 CLI 面 ==")
    tf = _tmp_tokfile("g7")
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = main(["--token-file", tf, "issue", "--role", "designer",
                   "--sessions-read", "a,b"])
    ok(rc == 0, "G7a issue --sessions-read rc=0", rc)
    try:
        j = json.loads(buf.getvalue())
    except Exception as e:                                       # noqa: BLE001
        ok(False, "G7a issue 输出纯 JSON", e)
        j = {}
    ok(j.get("sessions_read") == ["a", "b"], "G7b issue JSON 含读面", j.get("sessions_read"))
    buf2 = io.StringIO()
    with contextlib.redirect_stdout(buf2):
        rc2 = main(["--token-file", tf, "derive", "--token", j.get("token", ""),
                    "--role", "recorder", "--sessions-read", "b,c"])
    ok(rc2 == 0, "G7c derive --sessions-read rc=0", rc2)
    j2 = json.loads(buf2.getvalue()) if rc2 == 0 else {}
    ok(j2.get("sessions_read") == ["b"], "G7d derive 交集语义经 CLI 生效", j2.get("sessions_read"))
    ok("sessions_read" in (j2.get("clamped") or []), "G7e clamped 经 CLI 可见", j2.get("clamped"))
    buf3 = io.StringIO()
    with contextlib.redirect_stdout(buf3):
        rc3 = main(["--token-file", tf, "list"])
    j3 = json.loads(buf3.getvalue()) if rc3 == 0 else {}
    rows = j3.get("tokens") or []
    ok(rc3 == 0 and all("sessions_read" in x for x in rows),
       "G7f list 展示读面（运维体检可见）", [list(x.keys()) and ("sessions_read" in x) for x in rows][:1])
    buf4 = io.StringIO()
    with contextlib.redirect_stdout(buf4):
        rc4 = main(["--token-file", tf, "verify", "--token", j.get("token", "")])
    j4 = json.loads(buf4.getvalue()) if rc4 == 0 else {}
    ok(j4.get("principal", {}).get("sessions_read") == ["a", "b"],
       "G7g verify 输出读面（as_dict 接线）", j4.get("principal", {}).get("sessions_read"))


def main_():
    if sys.stdout.encoding and sys.stdout.encoding.lower().startswith("cp"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    for g in (g1_roundtrip, g2_default_zero, g3_star, g4_legacy_record,
              g5_derive, g6_narrowed, g7_cli):
        g()
    print("\nissue #712 签发侧接线守卫：%d 通过，%d 失败" % (len(_PASS), len(_FAIL)))
    return 0 if not _FAIL else 1


if __name__ == "__main__":
    sys.exit(main_())
