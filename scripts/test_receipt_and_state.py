# -*- coding: utf-8 -*-
# 功能名：receipt 机制与会话状态文件的自检（R1/R2/R3）
# 生效条件：python -u -X utf8 scripts/test_receipt_and_state.py；夹具钉临时区，除 R1 会往 receipts/ 落一份探针收据外不改仓内状态
# 子功能：R1 收据可复现（重跑 rc 与 digest 全同）· R2 状态文件四节结构 · R3 **反例腿**（digest 篡改 ⇒ R1 判据转红；缺 `## 下一步` ⇒ R2 判据转红）
# 执行：直接跑；退出码 0=全绿、1=有红
# 验证方式：全部 PASS；R3 是「本腿能红」的证明（**不 mock、真造两份反例文件**）
# 不适用条件：不判「收据里的命令选得对不对」——选错命令的收据同样可复现（本机制不判别这一层）；不判跨机可复现（本机制只在同机同 cwd 下有定义）
"""receipt + 状态文件 自检。

★R3 的意义（本会话两次栽过「腿不判别」）：R1/R2 若只对**现在的**文件断言，就永远绿。
故 R3 **真的构造**两份反例（篡改 digest 的收据 / 缺 `## 下一步` 的状态文件），
断言 R1/R2 的**判据本体**各自转红。**不用「断言某函数被调用过」代替**（那是「只加壳不接线」）。
"""
from __future__ import annotations

import io
import json
import os
import shutil
import sys
import tempfile

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "scripts"))
import receipt as RC                                     # noqa: E402

PASS = FAIL = 0
FAILS = []


def ok(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  PASS " + name)
    else:
        FAIL += 1
        FAILS.append(name)
        print("  FAIL " + name + "  " + str(detail)[:220])


STATE = os.path.join(_REPO, "docs", "state", "会话状态.md")
SECTIONS = ("## 计划", "## 进度", "## 下一步", "## 未核清单")


# 生效条件：text 为字符串即成立；四节齐全 且 `## 下一步` 节内容非空 且 `## 未核清单` 节存在（可空）⇒ 返回 (True, "")；否则 (False, 原因)。
def state_ok(text):
    for s in SECTIONS:
        if s not in text:
            return False, "缺小节 %s" % s
    i = text.index("## 下一步")
    j = text.find("\n## ", i + 1)
    body = (text[i + len("## 下一步"):] if j < 0 else text[i + len("## 下一步"):j]).strip()
    if not body:
        return False, "`## 下一步` 为空"
    return True, ""


print("== R1 收据可复现（重跑 rc 与 digest 全同）==")
PROBE = ["python", "-u", "-X", "utf8", "-c", "print('RECEIPT-PROBE-OK')"]
w = RC.write_receipt("probe_selfcheck", PROBE)
ok("R1 前置：探针收据写入成功且未抛异常", w["exception"] is None and w["rc"] == 0, w.get("exception"))
names = sorted(f for f in os.listdir(RC.RECEIPTS) if f.endswith(".json"))
ok("R1 前置：receipts/ 至少一份收据", len(names) >= 1, names)
print("       [全量] receipts/*.json = %s" % names)
for f in names:
    good, d = RC.check_receipt(os.path.join(RC.RECEIPTS, f))
    ok("R1 %s 重跑可复现（rc 与 digest 全同）" % f, good, d)

print("")
print("== R2 状态文件结构 ==")
_st = io.open(STATE, encoding="utf-8").read()
_good, _why = state_ok(_st)
ok("R2 状态文件四节齐全 + `## 下一步` 非空 + `## 未核清单` 存在", _good, _why)
ok("R2 顶部含用法行（每轮开头读 / 结尾更新 / 完成必须附 receipts/<name>.json）",
   "每轮开头读本文件" in _st and "receipts/<name>.json" in _st)

print("")
print("== R3 反例腿：判据本体必须能红（真造反例，不 mock）==")
_sb = tempfile.mkdtemp(prefix="i_receipt_r3_")
try:
    # (i) digest 被篡改的收据 ⇒ R1 的判据本体必须转红
    _p = os.path.join(_sb, "tampered.json")
    _rec = dict(w)
    _rec["name"] = "tampered"
    _rec["digest"] = "0" * 64                      # 篡改：与重跑结果必然不同
    io.open(_p, "w", encoding="utf-8").write(json.dumps(_rec, ensure_ascii=False))
    _g1, _d1 = RC.check_receipt(_p)
    ok("R3(i) ★digest 不符 ⇒ check_receipt 判红（reason=digest 不符）",
       (_g1 is False) and _d1.get("reason") == "digest 不符（输出不可复现）", _d1)
    # (ii) rc 不符的收据 ⇒ 必须转红，且 reason 与 digest 那支**分开**
    _p2 = os.path.join(_sb, "badrc.json")
    _rec2 = dict(w)
    _rec2["name"] = "badrc"
    _rec2["rc"] = 7                                # 篡改：与真实 rc 不符
    io.open(_p2, "w", encoding="utf-8").write(json.dumps(_rec2, ensure_ascii=False))
    _g2, _d2 = RC.check_receipt(_p2)
    ok("R3(ii) rc 不符 ⇒ 判红，且 reason 与 digest 那支**分开**（一个观测一个原因）",
       (_g2 is False) and _d2.get("reason") == "rc 不符", _d2)
    # (iii) 缺 `## 下一步` 的状态文件 ⇒ R2 的判据本体必须转红
    _bad = "\n".join(l for l in _st.splitlines()
                     if l.strip() != "## 下一步" and not l.startswith("- 先落 receipt"))
    _gb, _wb = state_ok(_bad)
    ok("R3(iii) ★缺 `## 下一步`（或该节为空）⇒ state_ok 判红", _gb is False, _wb)
    _bad2 = _st.replace("- 先落 receipt 与状态文件（本件）→ 再逐条给 C1–C7 落腿 → 再回 issue 批次", "")
    _g2b, _w2b = state_ok(_bad2)
    ok("R3(iv) `## 下一步` 存在但**内容为空** ⇒ 也判红（存在≠非空）", _g2b is False, _w2b)
    # (v) 跑不起来的收据 ⇒ 与「判否」分开留痕
    _p3 = os.path.join(_sb, "boom.json")
    _rec3 = dict(w)
    _rec3["name"] = "boom"
    _rec3["cmd"] = ["definitely-not-a-real-binary-xyz"]
    io.open(_p3, "w", encoding="utf-8").write(json.dumps(_rec3, ensure_ascii=False))
    _g3, _d3 = RC.check_receipt(_p3)
    ok("R3(v) 跑不起来 ⇒ 判红但 reason 标「跑不起来（异常，与判否分开）」",
       (_g3 is False) and "跑不起来" in str(_d3.get("reason")), _d3)
finally:
    shutil.rmtree(_sb, ignore_errors=True)

print("")
print("断言总数 %d（PASS %d / FAIL %d）" % (PASS + FAIL, PASS, FAIL))
if FAILS:
    print("FAILED:")
    for f in FAILS:
        print("   - " + f)
sys.exit(1 if FAILS else 0)