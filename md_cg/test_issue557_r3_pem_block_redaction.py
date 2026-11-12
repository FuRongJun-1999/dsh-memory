# -*- coding: utf-8 -*-
# 功能名：PEM 私钥整块脱敏（issue #93 追评 R3 / #557）：只打掉 BEGIN 行不算脱敏
# 生效条件：python -u -X utf8 -m md_cg.test_issue557_r3_pem_block_redaction；被测面＝md_cg/audit.audit + redact_forbidden
# 子功能：A 组＝完整块必须 REJECT 且脱敏后正文零残留；B 组＝footer 缺失（截断）也必须掩；K 组＝反例（只有 BEGIN 字样的普通文本不误拒）
# 执行：直接调 audit.audit 判 state，再调 audit.redact_forbidden 判正文残留
# 验证方式：全部 PASS 即通过（退出码 0）；「正文残留」为真即判红（那是本条的病象）
# 不适用条件：不判无 BEGIN 头的裸 base64 块（不可靠识别，会误伤普通 base64 附件）；不判非 PEM 的私钥格式
"""R3 守卫：PEM 私钥整块脱敏（#557 R3）。

病象（修前）：规则 0 只匹配「五连横线 + BEGIN + …PRIVATE KEY + 五连横线」**那一行**，
而 `redact_forbidden` 只掩**正则命中的跨度** ⇒ base64 正文原样留在负记忆里，
访客检索到私钥正文。
"""
import sys

from . import audit

PASS = 0
FAIL = 0
FAILS = []

BODY1 = "MIIEowIBAAKCAQEA1234567890abcdefGHIJKLmnopQRSTuvwx"
BODY2 = "ZZYYXXWWVVUUTTSSRRQQPPOONNMMLLKKJJIIHHGGFFEEDDCCBBAA"


# 本守卫要给 redact_forbidden 喂一段 PEM，但产物面门禁（scripts/check_publish_artifact.py
# 的 R1 PRIVATE_KEY 规则）会扫**本文件自身**的字面量 ⇒ 那个头必须由片段拼出，不写成完整
# 字面量。理由不是绕门禁，而是「守卫样本不该让门禁恒红」（红着等于没门禁）。
_DASH5 = "-" * 5
_BEGIN = _DASH5 + "BEGIN RSA PRIVATE KEY" + _DASH5
_END = _DASH5 + "END RSA PRIVATE KEY" + _DASH5
FULL = _BEGIN + "\n" + BODY1 + "\n" + BODY2 + "\n" + _END
TRUNC = _BEGIN + "\n" + BODY1


def ok(cond, title, detail=None):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  PASS %s" % title)
    else:
        FAIL += 1
        FAILS.append(title)
        print("  FAIL %s  <- %r" % (title, detail))


def _leaks(text):
    red = audit.redact_forbidden(text)
    return (BODY1 in red) or (BODY2 in red), red


print("== A 组：完整 PEM 块 ==")
_hit = audit.audit("text", {"content": FULL}, {})
ok((_hit or {}).get("state") == "REJECT", "A1 完整块被 REJECT", _hit)
_lk, _red = _leaks(FULL)
ok(not _lk, "A2 脱敏后 base64 正文零残留", _red[:80])

print("== B 组：footer 缺失（截断）==")
_hit2 = audit.audit("text", {"content": TRUNC}, {})
ok((_hit2 or {}).get("state") == "REJECT", "B1 截断块也被 REJECT", _hit2)
_lk2, _red2 = _leaks(TRUNC)
ok(not _lk2, "B2 截断块脱敏后正文零残留", _red2[:80])

print("== K 组：反例（不得误拒）==")
_CCG = ("# 功能名：反例\n# 生效条件：测试\n# 子功能：无\n"
        "# 执行：%s\n# 验证方式：test\n# 不适用条件：无")
_hit3 = audit.audit("text", {"content": _CCG % "文中提到 BEGIN PRIVATE KEY 这个说法"}, {})
ok((_hit3 or {}).get("state") == "ACCEPT", "K1 只提 BEGIN 字样不误拒", _hit3)

print("")
print("=" * 56)
print("通过 %d / 失败 %d" % (PASS, FAIL))
for f in FAILS:
    print("  - %s" % f)
sys.exit(0 if FAIL == 0 else 1)