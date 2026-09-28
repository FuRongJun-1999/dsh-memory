# -*- coding: utf-8 -*-
"""令牌形态「只认小写」的守卫（批次79，2026-09-28 使用者裁定）。

运行：python -X utf8 -m md_cg.test_token_lowercase_form              # 正常跑
      python -X utf8 -m md_cg.test_token_lowercase_form --head-baseline  # 判别力自证

裁定原文：「不认大写。统一只认小写。」落点＝**受理面单点** `tokens.parse_token`
（`verify_token` 的唯一入口）。改动前该函数返回 `role.lower()`、且对 token_id 不做
任何形态检查——即受理面比识别面**更宽**：`md_cg` 自己的检测表
（`data/policy.json` forbidden #9 `\\btk_[0-9a-f]{8,}\\b`、`src/hooks.ts`
SENSITIVE_PATTERNS 的同形规则）**有意**不含 `A-F`，而受理面却会接受一个含大写的
token_id——检测面漏过的形态照样能通过校验，两面的松紧就倒挂了。

本套断言分七组：
  G1 放行面（真令牌通过；secret 含大写仍通过——base64url 必含大写，不得误伤）
  G2 token_id 含大写 → 拒（`TK_` 前缀、全大写 hex、混合大小写 id 三种）
  G3 role 含大写 → 拒（改动前 role.lower() 会**静默接受**）
  G4 前缀含大写 → 拒（既有判据，钉住它别被后续重构放松）
  G5 端到端（真临时令牌库：合法令牌过闸；同 secret 的大写变形令牌抛 TokenError，
     而不是落到「令牌不存在」这类下游软失败上——形态问题必须在形态层拒掉）
  G6 生成面自证（**推论前提**：`issue` 只产小写 role/token_id ⇒ 大写形态没有合法来源）
  G7 口径面（识别面**仍然**宽：禁表两条原样存在、hooks.ts 的 role 段仍 `[A-Za-z]+`；
     受理面已窄。二者关系＝「识别面宽、受理面窄」，不是「两面都收紧」）

**红基线自证（--head-baseline）**：把 `parse_token` 临时换回改动前的实现
（`return role.lower(), token_id, secret`），G2/G3/G5 必须转红。若红基线不红，
说明这几条断言没有判别力（删掉新分支也照样全绿）。
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import re
import secrets
import shutil
import sys
import tempfile

from . import tokens
from .tokens import ROLE_SPECS, TokenError

_PASS = []
_FAIL = []


def ok(cond, msg, extra=""):
    (_PASS if cond else _FAIL).append(msg)
    print(("  PASS " if cond else "  FAIL ") + msg + (("  ← " + str(extra)) if (extra and not cond) else ""))


def _rejects(token: str, want: str = "") -> tuple:
    """调 parse_token 判拒：返回 (是否被拒, 错误文本)。"""
    try:
        tokens.parse_token(token)
        return False, ""
    except TokenError as e:
        t = str(e)
        return (want in t), t
    except Exception as e:                                    # noqa: BLE001
        return False, "%s: %s" % (type(e).__name__, e)


# ---------------------------------------------------------------- 旧实现（红基线用）
def _old_parse_token(token: str):
    """改动前的实现原文——仅用于 --head-baseline 的判别力自证，不参与生产。"""
    parts = (token or "").strip().split(".")
    if len(parts) != 4 or parts[0] != tokens.PREFIX:
        raise TokenError("令牌格式非法（应为 mdcg1.<role>.<token_id>.<secret>）")
    _, role, token_id, secret = parts
    if not role or not token_id or not secret:
        raise TokenError("令牌字段缺失")
    return role.lower(), token_id, secret


# 合成件：secret 刻意含大写（与 token_urlsafe 的真实产物同分布），用来把「只认小写」
# 的适用面钉在 role/token_id 两段上，而不是顺手把 secret 也收紧。值里带 `dummy`/`fake`
# 标记是**发版门禁的既有约定**（scripts/check_publish_artifact.py::FAKE_TOKEN_MARKERS）：
# 测试里的合成凭据必须一眼可辨为假值，否则 R1 凭据面会把本文件判成真实泄露（本批次首跑
# 实测命中 APIKEY_LITERAL + TOKEN_MDCG 两条，即按该约定改正而成现在这样）。
DUMMY_SECRET_UC = "Fake-Dummy-aB3xY9zQ7wV1uT5sR2pN8mL4kJ6"
HEX_ID = "9f3a2b8c7d4e"                                        # token_hex(6) 形态


def _tok(role: str, tid: str, secret: str = None) -> str:
    """拼一条令牌：经 make_token 而非字面量——测试源码里不留「像真凭据」的整串。"""
    return tokens.make_token(role, tid, secret or DUMMY_SECRET_UC)


def g1_allow():
    print("\n[G1] 放行面：合法令牌与含大写 secret 的令牌都通过")
    good = _tok("designer", "tk_" + HEX_ID)
    role, token_id, secret = tokens.parse_token(good)
    ok(role == "designer" and token_id == "tk_" + HEX_ID and secret == DUMMY_SECRET_UC,
       "G1a 合法令牌原样通过（role/token_id/secret 都不改写）")
    ok(secret == DUMMY_SECRET_UC and any(c.isupper() for c in secret),
       "G1b secret 含大写仍然通过（base64url 必含大写，不得误伤）",
       "样例 secret 大写字母数=%d" % sum(1 for c in secret if c.isupper()))
    ok(tokens.parse_token(_tok("guest", "tk_" + "0123456789ab"))[0] == "guest",
       "G1c 另一角色同样通过（避免只对 designer 生效的伪断言）")


def g2_id_uppercase():
    print("\n[G2] token_id 含大写 → 拒（受理面比识别面宽的那个洞）")
    for label, tid in (("TK_ 前缀大写", "TK_" + HEX_ID),
                       ("全大写 hex", "tk_" + HEX_ID.upper()),
                       ("混合大小写", "tk_9f3a2B8c7d4e")):
        hit, err = _rejects(_tok("designer", tid), want="小写")
        ok(hit, "G2 token_id %s → 拒且文案点明「小写」" % label, err)
    ok(tokens.parse_token(_tok("designer", "tk_" + HEX_ID))[1] == "tk_" + HEX_ID,
       "G2 正对照：同一形态换成小写即通过（拒的是大小写，不是 tk_ 前缀）")


def g3_role_uppercase():
    print("\n[G3] role 含大写 → 拒（改动前 role.lower() 静默接受）")
    for label, role in (("全大写", "DESIGNER"), ("首字母大写", "Designer"),
                        ("别名大写", "VERIFIER")):
        hit, err = _rejects(_tok(role, "tk_" + HEX_ID), want="小写")
        ok(hit, "G3 role %s → 拒且文案点明「小写」" % label, err)
    ok(tokens.parse_token(_tok("designer", "tk_" + HEX_ID))[0] == "designer",
       "G3 正对照：全小写 role 通过且不被改写")


def g4_prefix():
    print("\n[G4] 前缀含大写 → 拒（既有判据，钉住别被后续重构放松）")
    hit, err = _rejects(_tok("designer", "tk_" + HEX_ID).replace("mdcg1", "MDCG1", 1), want="格式非法")
    ok(hit, "G4a 前缀 MDCG1 → 拒", err)
    hit2, err2 = _rejects(_tok("designer", "tk_" + HEX_ID).replace("mdcg1", "Mdcg1", 1), want="格式非法")
    ok(hit2, "G4b 前缀 Mdcg1 → 拒", err2)
    ok(tokens.PREFIX == tokens.PREFIX.lower() and tokens.PREFIX == "mdcg1",
       "G4c PREFIX 常量本身即小写（前缀大小写敏感的前提）", tokens.PREFIX)


def g5_end_to_end():
    print("\n[G5] 端到端：真令牌库上，合法令牌过闸、大写变形令牌在形态层即拒")
    root = tempfile.mkdtemp(prefix="mdcg_toklower_")
    tf = os.path.join(root, "_tokens.json")
    try:
        rec = tokens.issue("designer", path=tf)
        tok = rec["token"]
        p = tokens.verify_token(tok, path=tf)
        ok(p.role == "designer", "G5a 合法令牌 verify_token 通过（role=%s）" % p.role)
        role, tid, sec = tokens.parse_token(tok)
        up_id = tokens.make_token(role, tid.upper(), sec)
        try:
            tokens.verify_token(up_id, path=tf)
            ok(False, "G5b 大写 token_id 的变形令牌必须被拒", "竟然通过了")
        except TokenError as e:
            ok("小写" in str(e), "G5b 大写 token_id 变形 → TokenError 且文案指向形态（非下游软失败）", str(e))
        up_role = tokens.make_token(role.upper(), tid, sec)
        try:
            tokens.verify_token(up_role, path=tf)
            ok(False, "G5c 大写 role 的变形令牌必须被拒", "竟然通过了")
        except TokenError as e:
            ok("小写" in str(e), "G5c 大写 role 变形 → TokenError 同上", str(e))
        msg = _reject_text(up_id)
        ok("小写" in msg and "不存在" not in msg and "不匹配" not in msg,
           "G5d 拒因是形态层（不含「令牌不存在/密钥不匹配」这类下游软失败文案）", msg)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _reject_text(token: str) -> str:
    """取原始错误文本（不做 must-contain 判据），供 G5d 反向核对。"""
    try:
        tokens.parse_token(token)
        return "(未被拒)"
    except TokenError as e:
        return str(e)


def g6_issuer():
    print("\n[G6] 生成面自证：大写形态没有合法来源（推论的**前提**）")
    hexes = [secrets.token_hex(6) for _ in range(64)]
    ok(all(re.fullmatch(r"[0-9a-f]{12}", h) for h in hexes),
       "G6a secrets.token_hex(6) 只产小写 hex（64 次采样零违例）",
       [h for h in hexes if not re.fullmatch(r"[0-9a-f]{12}", h)][:3])
    ok(all(k == k.lower() for k in ROLE_SPECS),
       "G6b ROLE_SPECS 全部键为小写（签发面 role 取值域即小写）", sorted(ROLE_SPECS))
    # 签发面另有一层归一：issue 经 normalize_role 把小写化做在「我方自己发」这一侧。
    # 这不算「认大写」——产出物恒为小写；受理面收的是外部来的串，没有这层信任。
    # 结构断言（不写整串字面量：测试源码里不留「像真凭据」的串，见 DUMMY_SECRET_UC 处注释）
    ok(tokens.make_token("designer", "tk_" + HEX_ID, DUMMY_SECRET_UC).split(".") ==
       [tokens.PREFIX, "designer", "tk_" + HEX_ID, DUMMY_SECRET_UC],
       "G6c make_token 是纯拼接（四段原样，不在拼接层做大小写变换）")
    root = tempfile.mkdtemp(prefix="mdcg_toklower_iss_")
    try:
        tok = tokens.issue("DESIGNER", path=os.path.join(root, "_tokens.json"))["token"]
        ok(tok.startswith("mdcg1.designer."),
           "G6d 即便调用方传大写 role，issue 产出仍是小写（签发面归一生效处）", tok[:24])
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _hooks_rules() -> list:
    """从 src/hooks.ts 源码里取出现行的 `/…/g` 字面（JS 与 Python 在这些构造上同义）。"""
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = io.open(os.path.join(repo, "src", "hooks.ts"), encoding="utf-8").read().splitlines()
    out = []
    for i, line in enumerate(src, 1):
        m = re.search(r"re:\s*/(.+)/[a-z]*\s*,", line)
        if m:
            out.append((i, m.group(1), line))
    return out


def g7_detection_face():
    print("\n[G7] 口径面：识别面**仍然**宽、受理面已窄（不是两面都收紧）")
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    pol = json.loads(io.open(os.path.join(repo, "data", "policy.json"), encoding="utf-8").read())
    forb = pol["forbidden"]
    vals = list(forb.values()) if isinstance(forb, dict) else list(forb)
    ok(any(v.strip() == r"\btk_[0-9a-f]{8,}\b" for v in vals),
       "G7a 禁表 id 规则原样保留（未顺手加 A-F / re.I——那会把「只认小写」变成误报源）")
    ok(any("mdcg1" in v for v in vals),
       "G7b 禁表全形态令牌规则原样保留")
    ok(all("(?i)" not in v for v in vals if "tk_" in v),
       "G7c 令牌相关禁用规则不带 (?i)（大小写敏感是刻意的）")
    rules = _hooks_rules()
    full = [(ln, p) for ln, p, _ in rules if "mdcg1" in p]
    bare = [(ln, p) for ln, p, _ in rules if "tk_" in p and "mdcg1" not in p]
    ok(len(full) == 1 and len(bare) == 1,
       "G7d hooks.ts 恰好各有一条全形态/裸 id 令牌规则（行号=%s）"
       % ([ln for ln, _ in full] + [ln for ln, _ in bare]))
    if not full or not bare:
        return
    up_tok = _tok("DESIGNER", ("tk_" + HEX_ID).upper(), DUMMY_SECRET_UC.upper())
    lo_tok = _tok("designer", "tk_" + HEX_ID)
    ok(re.search(full[0][1], up_tok) is not None and re.search(full[0][1], lo_tok) is not None,
       "G7e 插件全形态规则**行为上宽**：含大写的令牌也整条命中（拦得住）",
       full[0][1])
    ok(re.search(bare[0][1], "tk_" + HEX_ID) is not None,
       "G7f 插件裸 id 规则匹配小写 hex id", bare[0][1])
    ok(re.search(bare[0][1], "tk_" + HEX_ID.upper()) is None,
       "G7g 插件裸 id 规则**有意**不匹配大写 hex id（识别面固有缺口＝本批次修的另一半）",
       bare[0][1])
    # 缺口闭合：识别面漏掉的大写形态，受理面必须拒 ⇒ 两面组合后无缝隙。
    # 反过来说，若受理面像改动前那样认大写，G7g 的形态就是一条真的凭据通道。
    hit, _ = _rejects(_tok("designer", "tk_" + HEX_ID.upper()))
    ok(hit, "G7h 识别面漏（大写 hex）⇔ 受理面拒：不存在「检测漏 + 受理收」的缝隙")


def _run_groups() -> int:
    _PASS.clear(); _FAIL.clear()
    for g in (g1_allow, g2_id_uppercase, g3_role_uppercase, g4_prefix, g5_end_to_end,
              g6_issuer, g7_detection_face):
        g()
    return len(_FAIL)


def main() -> int:
    if sys.stdout.encoding and sys.stdout.encoding.lower().startswith("cp"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    base = "--head-baseline" in sys.argv
    if base:
        print("!! 红基线模式：parse_token 临时替换回改动前实现（role.lower()、不查 token_id 形态）")
        print("   期望 G2/G3/G5 转红\n")
        tokens.parse_token = _old_parse_token
        globals()["tokens"] = tokens
    groups = (g1_allow, g2_id_uppercase, g3_role_uppercase, g4_prefix, g5_end_to_end,
              g6_issuer, g7_detection_face)
    for g in groups:
        g()
    if base:
        print("\n== 红基线判定：应有失败 ==")
        print("红基线失败数 = %d（>0 才算断言有判别力）" % len(_FAIL))
        for f in _FAIL:
            print("   红:", f)
        return 0 if _FAIL else 1
    print("\n令牌形态（只认小写）守卫：%d 通过，%d 失败" % (len(_PASS), len(_FAIL)))
    return 0 if not _FAIL else 1


if __name__ == "__main__":
    with contextlib.redirect_stdout(sys.stdout):
        sys.exit(main())
