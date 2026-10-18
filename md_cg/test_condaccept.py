# -*- coding: utf-8 -*-
"""condaccept 自证：正负对照 + 灰度行为 + 变异自证。"""

import importlib
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from md_cg import condaccept  # noqa: E402

OK = 0
FAIL = 0


def check(name, cond):
    global OK, FAIL
    if cond:
        OK += 1
        print("  ok   %s" % name)
    else:
        FAIL += 1
        print("  FAIL %s" % name)


FULL = {"observation_position": "designer", "observation_tool": "manual",
        "time_window": "2026-10-24", "existence_constraint": "local"}
EV = "见 docs/dsh设计/灵枢记忆系统_统一架构_v1.1.md 第9.1节"
# 注意：V4 依赖 CCG 三要素，样本必须写全——否则 slot_key 返回 None，V4 按设计跳过
# （首版样本只写了功能名，导致 V4 用例假阴性：那不是判据失效，是样本没资格参与判定）。
CCG = ("# 功能名：样例\n"
       "# 生效条件：需要样例时\n"
       "# 子功能：①样例\n"
       "# 执行：略\n" + EV + "\n")
PL = {"content": CCG, "condition_space": FULL, "evidence_ref": ["docs/x.md#1"]}


class FakeCG(object):
    def __init__(self, hits=None, boom=False):
        self.hits = hits or []
        self.boom = boom

    def search(self, q, k=3):
        if self.boom:
            raise RuntimeError("boom")
        # 真实形态：(res, meta)，res 元素为 (node, score, qual)
        return [(h, 0.9, {"state": "ACCEPT"}) for h in self.hits], {}


def run(payload, ctx=None, mode_value="enforce"):
    os.environ["MDCG_WORKDONE_ACCEPT"] = mode_value
    return condaccept.verify_work_done(payload, ctx or {"nid": "me", "cg": FakeCG()})


print("[V1] 条件空间")
r = run({"content": EV})
check("无条件空间 → REJECT 打回写入方（不是入队 DEFER）",
      r["state"] == "REJECT" and "V1" in r["evidence"] and r["detail"]["return_to"] == "author")
r = run({"content": EV, "condition_space": {"observation_position": "x"}})
check("条件空间不完整 → 同样打回", r["state"] == "REJECT" and r["detail"]["return_to"] == "author")
check("打回体带补齐动作提示", r["detail"]["action"] == "resubmit_with_condition_space")

print("[V2] 证据可回溯")
r = run({"content": "无任何出处的裸断言", "condition_space": FULL})
check("无条件空间有证据也先过 V1；缺证据 → REJECT", r["state"] == "REJECT" and "V2" in r["evidence"])
r = run({"content": "裸断言", "condition_space": FULL, "evidence_ref": "node_id:mem_1"})
check("显式 evidence_ref 字符串 → 视为可回溯", r["state"] == "ACCEPT")

print("[V2 正则] 常见出处写法必须可识别（首版过窄会假拒绝）")
for probe, expect in [
    ("依据：md_cg/condgate.py 第9.1节", True),
    ("见 第 3.2.1 节 的说明", True),
    ("出处: docs/x.md", True),
    ("node_id: mem_123", True),
    ("实测读数为 68/0", True),
    ("这段话没有任何出处", False),
]:
    got = condaccept._has_evidence({"content": probe})
    check("证据识别 %-28s → %s" % (probe[:26], "有" if expect else "无"), got is expect)

print("[语义解耦] 形式层与真值层不得合并")
r_sem = run(PL, mode_value="enforce")
check("ACCEPT 恒带 acceptance=formal_pass", r_sem["detail"]["acceptance"] == "formal_pass")
check("ACCEPT 恒带 verification_state=unverified（本闸无权判真）",
      r_sem["detail"]["verification_state"] == "unverified")
check("ACCEPT 的 evidence 明写不判内容真值", "不判内容真值" in r_sem["evidence"])
r_rej = run({"content": "裸断言无出处", "condition_space": FULL}, mode_value="enforce")
check("REJECT 带 acceptance=formal_reject", r_rej["detail"]["acceptance"] == "formal_reject")
check("V2 evidence 说明只认标记存在", "只认标记存在" in r_rej["evidence"])

print("[V4] 同槽冲突")
def node(nid, content):
    return {"id": nid, "content": content}

same_slot_other = CCG + "但结论不同"
r = run(PL, {"nid": "me", "cg": FakeCG(hits=[node("other", same_slot_other)])})
check("同槽异值 → REJECT", r["state"] == "REJECT" and "V4" in r["evidence"])
r = run(PL, {"nid": "other", "cg": FakeCG(hits=[node("other", same_slot_other)])})
check("命中自身 → 排除，不判冲突（自指防护）", r["state"] == "ACCEPT")
# P0-1（外部评审 2026-10-18）：判不了 ≠ 没问题。旧断言把「检索失败」钉成 ACCEPT，
# 直接违反 I5（无证据只能 DEFER/BLINDSPOT）。现改为 BLINDSPOT，断言随之收紧。
r = run(PL, {"nid": "me", "cg": FakeCG(boom=True)})
check("检索失败 → BLINDSPOT（不得落到 ACCEPT）", r["state"] == "BLINDSPOT")
check("BLINDSPOT 带 v4_status=unknown", r["detail"]["v4_status"] == "unknown")
check("BLINDSPOT 的 acceptance 是 undetermined（既非 pass 也非 reject）",
      r["detail"]["acceptance"] == "undetermined")
r_nocg = run(PL, {"nid": "me", "cg": None})
check("无 cg 同样 BLINDSPOT", r_nocg["state"] == "BLINDSPOT")
# 不适用 ≠ 判不了：无 CCG 槽位时 V4 无从谈起，不阻断但必须标注。
r = run({"content": "只有功能名没有三要素\n" + EV, "condition_space": FULL,
         "evidence_ref": ["x"]}, {"nid": "me", "cg": FakeCG(hits=[node("o", same_slot_other)])})
check("无 CCG 三要素 → V4 不适用(na)，不阻断但显式标注",
      r["state"] == "ACCEPT" and r["detail"]["v4_status"] == "na")
check("na 与 unknown 是不同状态（不混为一谈）", r["detail"]["v4_status"] != "unknown")

print("[灰度] observe 与 enforce")
r_obs = run(PL, mode_value="observe")
check("observe 恒返回 DEFER（与未注入现状一致）", r_obs["state"] == "DEFER")
check("observe 把真实判定写进 evidence", "真实判定=ACCEPT" in r_obs["evidence"])
check("observe detail 保留真实判定", r_obs["detail"]["observe"] is True and r_obs["detail"]["real"]["state"] == "ACCEPT")
r_enf = run(PL, mode_value="enforce")
check("enforce 返回真实判定 ACCEPT", r_enf["state"] == "ACCEPT")
os.environ["MDCG_WORKDONE_ACCEPT"] = "bogus"
condaccept._WARNED_MODES.clear()
check("非法档位回落文档缺省 enforce", condaccept.mode() == "enforce")
check("非法档位必须留告警痕迹（P0-3：配置错误不静默猜）",
      "bogus" in condaccept._WARNED_MODES)
del os.environ["MDCG_WORKDONE_ACCEPT"]
check("未设档位默认 enforce（同上）", condaccept.mode() == "enforce")

print("[变异自证] 判据是否真在起作用")
importlib.reload(condaccept)
os.environ["MDCG_WORKDONE_ACCEPT"] = "enforce"
_saved = condaccept._has_evidence
condaccept._has_evidence = lambda p: True   # 变异：V2 永远通过
r_mut = condaccept.verify_work_done({"content": "裸断言", "condition_space": FULL}, {"nid": "me", "cg": FakeCG()})
check("变异（V2 恒真）后裸断言不再 REJECT → 证明 V2 承重", r_mut["state"] == "ACCEPT")
condaccept._has_evidence = _saved
r_back = condaccept.verify_work_done({"content": "裸断言", "condition_space": FULL}, {"nid": "me", "cg": FakeCG()})
check("还原后重新 REJECT → 变异自证闭合", r_back["state"] == "REJECT")

print("[注入点]")
class FakeAudit(object):
    def __init__(self):
        self.registered = {}
    def register_verifier(self, kind, fn, override=False):
        self.registered[kind] = (fn, override)

fa = FakeAudit()
condaccept.register(fa)
check("register() 覆盖注册 work_done", "work_done" in fa.registered and fa.registered["work_done"][1] is True)

print("")
print(json.dumps({"ok": OK, "fail": FAIL, "verdict": "PASS" if FAIL == 0 else "FAIL"}, ensure_ascii=False))
sys.exit(0 if FAIL == 0 else 1)
