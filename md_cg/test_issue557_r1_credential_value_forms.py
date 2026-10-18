# -*- coding: utf-8 -*-
# 功能名：凭据禁表的值形态覆盖（issue #82/#90 追评 R1）：引号包值、含符号密码、「是：」组合分隔
# 生效条件：python -u -X utf8 -m md_cg.test_issue557_r1_credential_value_forms；被测面＝md_cg/audit.audit
# 子功能：A 组＝六种写法必须全部 REJECT（修前 5 种 ACCEPT）；K 组＝反向腿（无凭据语义的普通文本不得被拒）
# 执行：直接调 audit.audit('text', {'content': ...}, {})，判返回值真值
# 验证方式：全部 PASS 即通过（退出码 0）；BYPASS 数必须为 0
# 不适用条件：不判「规则集是否穷尽所有凭据形态」（只钉本件报的六种）；不判写入闸之后的落盘面
"""R1 守卫：凭据禁表的**值**形态覆盖（#557 R1）。

病象（修前）：value 字符类是 [A-Za-z0-9_\-]，于是
  DB_PASSWORD = "Abc123456"    值以双引号开头 ⇒ ACCEPT
  password: 'Abc123456'        值以单引号开头 ⇒ ACCEPT
  数据库密码：“Abc123456”       值以中文引号开头 ⇒ ACCEPT
  数据库密码：P@ssw0rd!2024    值含 @ ! ⇒ ACCEPT
  我的数据库密码是：Abc123456   「是」与「：」并用 ⇒ ACCEPT
六种写法里 5 种放行，而写入闸调的是同一个函数。
"""
import sys

from . import audit

PASS = 0
FAIL = 0
FAILS = []


def ok(cond, title, detail=None):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  PASS %s" % title)
    else:
        FAIL += 1
        FAILS.append(title)
        print("  FAIL %s  <- %r" % (title, detail))


# 值形态矩阵：每一行都必须 REJECT
FORBIDDEN = [
    ("A1 对照（已修形态）", "R1 数据库密码：Abc123456"),
    ("A2 下划线键 + 双引号值", 'R1 DB_PASSWORD = "Abc123456"'),
    ("A3 单引号值", "R1 password: 'Abc123456'"),
    ("A4 中文引号值", "R1 数据库密码：“Abc123456”"),
    ("A5 含符号密码", "R1 数据库密码：P@ssw0rd!2024"),
    ("A6 「是：」组合分隔", "R1 我的数据库密码是：Abc123456"),
]


# 判据：`audit.audit` **恒返回 dict**（含 state=ACCEPT/REJECT），不是 None/真值 ——
# 所以 `bool(hit)` 恒真。本守卫首版即因此假绿（A 组 6 条全「PASS」而其实无一被拦）。
# 正确判据是 state 字段。
print("== A 组：六种值形态必须全部 REJECT ==")
for title, text in FORBIDDEN:
    hit = audit.audit("text", {"content": text}, {})
    ok((hit or {}).get("state") == "REJECT", title, hit)

print("== K 组：反向腿（普通文本不得被误拒）==")
# K 组的文本必须是**形状合格的 CCG 六要素**，否则会先被「缺少必需要素」拦下，
# 就测不到凭据规则本身（本守卫首版即栽在这里：三条 K 全红，而原因与密码无关）。
_CCG = ("# 功能名：反向腿\n# 生效条件：测试\n# 子功能：无\n"
        "# 执行：%s\n# 验证方式：test\n# 不适用条件：无")
CLEAN = [
    ("K1 无凭据语义（密码学）", _CCG % "今天把密码学那章读完了"),
    ("K2 只有词没有值", _CCG % "记得改 password 字段"),
    ("K3 值太短", _CCG % "password: abc"),
]
for title, text in CLEAN:
    hit = audit.audit("text", {"content": text}, {})
    ok((hit or {}).get("state") == "ACCEPT", title, hit)

print("")
print("=" * 56)
print("通过 %d / 失败 %d" % (PASS, FAIL))
for f in FAILS:
    print("  - %s" % f)
sys.exit(0 if FAIL == 0 else 1)