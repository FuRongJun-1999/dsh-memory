# -*- coding: utf-8 -*-
"""位置权重矩阵端到端测试（P25 · 不同身份，参数偏好不同）。

验证目标：
  ① 两类位置：认知视角（3 项都涉及、不设零）vs 功能单元（身份即排除）
  ② 三条结构不变量：排除唯一（参与度 5/6）、排除项只属功能单元且各一次、
     视角主导 ↔ 功能单元排除一一配对
  ③ 序标定方向：不猜/不记/不对外 三个「排除」可推导且严格最低
  ④ 设计者定位：不参与日常评估（元参照系）
  ⑤ 合成占位：主导分量对结果影响最大（方向性，数值未标定）
  ⑥ 连接层非破坏性接线：position_preference 可用且不改动既有 cap

运行：python -m md_cg.test_p25_weights
"""
from __future__ import annotations

import os
import shutil
import tempfile

from . import links, theory, weights

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


def main():
    # ================= ① 两类位置 =================
    for p in ("designer", "reflect", "verify"):
        check(f"{p} 是认知视角（3 项都涉及，不设零）",
              weights.is_viewpoint(p) and weights.excluded(p) is None,
              f"class/excluded={weights.excluded(p)}")
    for p in ("record", "output", "sustain"):
        check(f"{p} 是功能单元（身份即排除）",
              weights.is_functional(p) and weights.excluded(p) is not None,
              f"excluded={weights.excluded(p)}")

    # ================= ② 三条不变量 =================
    inv = weights.invariants()
    for k, v in inv["checks"].items():
        check(f"不变量：{k}", v["ok"], str(v["detail"]))
    check("全部不变量通过", inv["ok"] is True)

    # 参与度具体值：每分量恰被 1 个位置排除 ⇒ 参与 5/6
    for c in weights.COMPONENTS:
        n_exc = sum(1 for p in weights.POSITION_ORDER
                    if weights.rank(p, c) == 0)
        cnt = sum(1 for p in weights.POSITION_ORDER if weights.rank(p, c) > 0)
        check(f"分量 {c} 恰被 1 处排除、参与 5/6",
              n_exc == 1 and cnt == 5, f"exc={n_exc} part={cnt}")

    # 视角主导 ↔ 功能单元排除配对
    pair = {"designer": "sustain", "reflect": "record", "verify": "output"}
    for vp, fn in pair.items():
        check(f"配对：{vp} 主导 == {fn} 排除",
              weights.dominant(vp) == weights.excluded(fn),
              f"{weights.dominant(vp)} vs {weights.excluded(fn)}")

    # ================= ③ 序标定方向（可推导的排除） =================
    check("记录不猜 → 排除 位置可预测性",
          weights.excluded("record") == "predictability")
    check("输出不记 → 排除 一致性",
          weights.excluded("output") == "consistency")
    check("维生不对外 → 排除 版本对齐度",
          weights.excluded("sustain") == "version_alignment")

    # 功能单元的序：主导 > 次主导 > 排除
    check("记录：一致性 > 版本对齐度 > 可预测性(≈0)",
          weights.prefers("record", "consistency", "version_alignment") is True
          and weights.prefers("record", "version_alignment", "predictability") is True)
    check("输出：可预测性 > 版本对齐度 > 一致性(≈0)",
          weights.prefers("output", "predictability", "version_alignment") is True
          and weights.prefers("output", "version_alignment", "consistency") is True)
    check("维生：一致性 > 可预测性 > 版本对齐度(≈0)",
          weights.prefers("sustain", "consistency", "predictability") is True
          and weights.prefers("sustain", "predictability", "version_alignment") is True)

    # 视角：只标主导，另两项并列（无严格序）
    check("反思：主导=可预测性，另两项并列",
          weights.dominant("reflect") == "predictability"
          and weights.prefers("reflect", "version_alignment", "consistency") is None)
    check("验证：主导=一致性，另两项并列",
          weights.dominant("verify") == "consistency"
          and weights.prefers("verify", "version_alignment", "predictability") is None)

    # ================= ④ 设计者定位 =================
    check("设计者不参与日常评估（元参照系）",
          weights.in_daily_eval("designer") is False)
    check("其余五位置参与日常评估",
          all(weights.in_daily_eval(p) for p in weights.DAILY))
    check("日常评估集合恰 5 项", len(weights.DAILY) == 5)

    # ================= ⑤ 合成（占位：方向性） =================
    # 记录：只抬高其主导分量（一致性）应比抬高等量可预测性更有效
    base = {"version_alignment": 0.5, "predictability": 0.5, "consistency": 0.5}
    hi_c = dict(base, consistency=1.0)
    hi_p = dict(base, predictability=1.0)
    sc, sp = weights.blend("record", hi_c)["score"], weights.blend("record", hi_p)["score"]
    check("记录：抬高主导分量(一致性)增益 > 抬高被排除分量",
          sc > sp, f"{sc} > {sp}")
    check("blend 标注权重未标定",
          "未标定" in weights.blend("record", base)["note"])
    check("权重和 = 1（归一化）",
          abs(sum(weights.weights("record").values()) - 1.0) < 1e-6)

    # ================= ⑥ 连接层非破坏性接线 =================
    tmp = tempfile.mkdtemp(prefix="mdcg_weights_")
    tf = os.path.join(tmp, "theory.json")
    lf = os.path.join(tmp, "_links.json")
    os.environ["MDCG_THEORY_FILE"] = tf
    os.environ["MDCG_LINKS_FILE"] = lf
    try:
        theory.declare("3.4", accepted=["3.4"], path=tf)
        pp = links.position_preference("record")
        check("links.position_preference 暴露偏好序",
              pp["dominant"] == "consistency"
              and pp["excluded"] == "predictability"
              and pp["class"] == links.FUNCTIONAL,
              str(pp["order"]))
        check("catalog 声明位置权重模块",
              links.catalog().get("position_weights", {}).get("module")
              == "md_cg.weights")
        # 既有 cap 默认行为不变（非破坏性）
        h = links.handshake("node-x", peer_theory={"version": "3.4"},
                            position_map={"record": "record"}, path=lf)
        check("既有 cap 行为不变（对齐+有映射 → 0.8）",
              h["link"]["p_trust_cap"] == links.CAP_ALIGNED)
        h2 = links.handshake("node-y", peer_theory={"version": "9.9"},
                             position_map={"record": "record"}, path=lf)
        check("既有 cap 行为不变（版本不符 → 0.3）",
              h2["link"]["p_trust_cap"] == links.CAP_MISALIGNED)
    finally:
        os.environ.pop("MDCG_THEORY_FILE", None)
        os.environ.pop("MDCG_LINKS_FILE", None)
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"\nP25 位置权重：{PASS} passed, {FAIL} failed")
    if FAILS:
        print("失败项：" + "、".join(FAILS))
    return 1 if FAIL else 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
