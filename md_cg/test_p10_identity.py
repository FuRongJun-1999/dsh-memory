# -*- coding: utf-8 -*-
"""md_cg · 第 10 篇：身份特征识别（智能论 v3.4 位置效应 + 扮演论三接口）

覆盖：
  A 位置效应推断（五大单元）
      记录=全 / 反思=新 / 验证=稳 / 输出=通 / 维生=存 ·
      多证据投票 · 证据不足→unknown · 平票 tie 提示 · votes/confidence 可审计
  B 身份锚点（anchor 接口）
      self→self 层（不可遗忘） · role/user→anchor 层 · 覆盖被拒 · override 放行 ·
      扮演论边界：role 不得进 self 层
  C 条件特征（values 接口）
      structural 层 · 条件空间=触发时机 · 画像汇总
  D 位置分布 / 自描述
  E 留痕 / 写保护联动

运行：python -m md_cg.test_p10_identity
"""
from __future__ import annotations

import tempfile

from .mdcos import MdCGOS
from . import identity, protect

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


def blocked(fn):
    """执行 fn，返回是否被 ProtectionError / ValueError 拦下。"""
    try:
        fn()
        return False
    except (protect.ProtectionError, ValueError):
        return True


def main():
    root = tempfile.mkdtemp(prefix="mdcg_p10_")
    cg = MdCGOS(root)

    # ---------- A. 位置效应推断 ----------
    print("\n[A] 位置效应推断（智能论 v3.4 §十三 五大单元）")

    cg.identity_observe("agent:rec", "执行了一次抓取命令", node_id="o_rec1",
                        role="command")
    cg.identity_observe("agent:rec", "回传工具输出", node_id="o_rec2",
                        role="tool-output")
    p = cg.identity_profile("agent:rec")
    check("记录单元（全）：command/tool-output → record",
          p["position"] == "record" and p["unit"] == "记录单元",
          f'{p["position"]}/{p["position_confidence"]}')
    check("位置携带职责与效应", p["effect"] == "全" and bool(p["duty"]),
          f'{p["effect"]}/{p["duty"]}')
    check("votes / evidence_count 可审计",
          p["votes"].get("record") == 2 and p["evidence_count"] == 2, str(p["votes"]))

    cg.identity_observe("user:alice", "提出了一个需求", node_id="o_out1", role="user")
    p2 = cg.identity_profile("user:alice")
    check("输出单元（通）：user 协作表达 → output",
          p2["position"] == "output" and p2["effect"] == "通",
          f'{p2["position"]}/{p2["position_confidence"]}')

    cg.identity_observe("role:whale", "发现了遗漏条件", node_id="o_ref1",
                        tags=["reflect", "遗漏条件"])
    p3 = cg.identity_profile("role:whale")
    check("反思单元（新）：发现差异/遗漏条件 → reflect",
          p3["position"] == "reflect" and p3["effect"] == "新", p3["position"])

    cg.identity_observe("agent:ver", "判断该规则是否有效", node_id="o_ver1",
                        tags=["verify"])
    p4 = cg.identity_profile("agent:ver")
    check("验证单元（稳）：判断有效性 → verify",
          p4["position"] == "verify" and p4["effect"] == "稳", p4["position"])

    cg.identity_observe("self:lingshu", "维护存在与预算回滚", node_id="o_sus1",
                        tags=["goal", "budget"])
    p5 = cg.identity_profile("self:lingshu")
    check("维生系统（存）：维护存在/预算/回滚 → sustain",
          p5["position"] == "sustain" and p5["effect"] == "存", p5["position"])

    cg.identity_observe("user:newbie", "只有一条模糊证据", node_id="o_unk1")
    pu = cg.identity_profile("user:newbie")
    check("证据不足 → unknown（不假装确定）",
          pu["position"] == "unknown" and pu["position_confidence"] == 0.0,
          pu["position"])

    cg.identity_observe("agent:tie", "既执行又验证", node_id="o_tie1",
                        role="command", tags=["verify"])
    pt = cg.identity_profile("agent:tie")
    check("平票时置 tie 提示歧义（不假装唯一）",
          bool(pt["tie"]) and pt["position"] in ("record", "verify"),
          f'{pt["position"]}/{pt["tie"]}')

    # ---------- B. 身份锚点 ----------
    print("\n[B] 身份锚点（anchor 接口 / 扮演论边界）")
    a1 = cg.identity_anchor("self:lingshu", "我是灵枢：记忆操作系统的自我锚点")
    check("self 锚点落 self 层（智能体自身）",
          a1["layer"] == "self" and a1["protected"], str(a1)[:100])
    check("锚点不可遗忘（protect 判定）",
          protect.is_protected(cg, a1["node_id"])[0], a1["node_id"])
    check("锚点覆盖被拒（不可覆盖）",
          blocked(lambda: cg.identity_anchor("self:lingshu", "试图改写自我锚点")),
          "ProtectionError")

    a2 = cg.identity_anchor("self:lingshu", "我是灵枢：经确认修订的自我锚点",
                            override=True)
    check("override 后锚点可修订", a2["ok"])

    a3 = cg.identity_anchor("role:whale", "我是鲸鱼，负责深潜检索")
    check("role 锚点落 anchor 层（不占用 self 层）",
          a3["layer"] == "anchor", a3["layer"])
    check("扮演论边界：role 不得写入 self 层",
          blocked(lambda: cg.identity_anchor("role:whale", "伪装成灵枢自身",
                                             requested_layer="self")),
          "ValueError")

    # ---------- C. 条件特征 ----------
    print("\n[C] 条件特征（values 接口：条件空间=触发时机）")
    t1 = cg.identity_trait("self:lingshu", "遇到权限问题时先查写保护清单",
                           condition_space={"trigger": "permission_error"})
    check("特征落结构层（特化价值观）", t1["layer"] == "structural", t1["layer"])
    check("特征携带条件空间（触发时机）",
          t1["condition_space"].get("trigger") == "permission_error",
          str(t1["condition_space"]))
    prof = cg.identity_profile("self:lingshu")
    check("画像汇总特征条目", prof["traits_count"] == 1, str(prof["traits_count"]))
    check("特征保留条件空间",
          (prof["traits"][0]["condition_space"] or {}).get("trigger")
          == "permission_error", str(prof["traits"][0])[:120])

    # ---------- D. 分布 / 自描述 ----------
    print("\n[D] 位置分布 / 自描述")
    ps = cg.identity_positions()
    kinds = {s["position"] for s in ps}
    check("positions 覆盖多主体多位置",
          len(ps) >= 5 and {"record", "output", "reflect", "verify", "sustain"} <= kinds,
          str(sorted(kinds)))
    cat = identity.catalog()
    check("catalog 五单元齐备", set(cat["positions"]) == set(identity.POSITION_ORDER),
          str(list(cat["positions"])))
    check("catalog 三接口齐备（memory/anchor/values）",
          set(cat["interfaces"]) == {"memory", "anchor", "values"},
          str(list(cat["interfaces"])))

    # ---------- E. 留痕 / 写保护联动 ----------
    print("\n[E] 留痕 / 写保护联动")
    hs = cg.identity_history(limit=50)
    ops = {r.get("op") for r in hs}
    check("身份操作留痕可查", {"observe", "anchor", "trait"} <= ops, str(sorted(ops)))
    check("受保护锚点 forget 被拒",
          blocked(lambda: cg.forget(a1["node_id"], "测试删除")), "ProtectionError")

    print(f"\n==== P10 结果：{PASS} 通过 / {FAIL} 失败 ====")
    if FAILS:
        print("失败项：" + "、".join(FAILS))
    return FAIL == 0


if __name__ == "__main__":
    import sys
    sys.exit(0 if main() else 1)
