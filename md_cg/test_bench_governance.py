# -*- coding: utf-8 -*-
"""bench_governance 评估器断言测试：语料守卫/指标定义/确定性/输出结构。"""
import json
import os
import shutil
import tempfile
import time

from . import bench_governance as bg

_FAILED = []


def ok(cond, label):
    if not cond:
        print("FAIL", label)
        _FAILED.append(label)
    else:
        print("pass", label)


def main():
    # ① 语料守卫：当前语料必须合法
    try:
        bg._assert_material(time.time())
        ok(True, "① 语料守卫通过（当前语料合法）")
    except AssertionError as exc:
        ok(False, f"① 语料守卫意外失败：{exc}")

    # ② 篡改语料必须被守卫拦截（不可答题泄漏语料词面）
    saved = list(bg.UNANSWERABLE)
    try:
        bg.UNANSWERABLE.append("蜂巢心跳间隔是多少")
        try:
            bg._assert_material(time.time())
            ok(False, "② 篡改语料未被拦截")
        except AssertionError:
            ok(True, "② 篡改语料被守卫拦截")
    finally:
        bg.UNANSWERABLE[:] = saved

    # ③ 全流程跑通 + 指标定义断言
    report, root = bg.run()
    try:
        g1 = report["g1_correction_propagation"]
        ok(g1["value"] == 1.0, f"③a g1 完美传播=1.0（got {g1['value']}）")
        ok(g1["detail"]["dependents"] == 4 and g1["detail"]["updated"] == 4,
           "③b g1 依赖索引=4 且全部同步")

        g2 = report["g2_contradiction_handling"]
        ok(g2["value"] == 1.0, f"③c g2 矛盾裁决全对=1.0（got {g2['value']}，detail={g2['detail']}）")
        ok(all(j["state"] == "REJECT" for j in g2["detail"]["judged"]),
           "③d 否定节点定点裁决全 REJECT")
        ok(g2["detail"]["retrieval"]["leaked_negatives"] == [],
           "③e 检索防线 top-k 无否定节点冒充")

        g3 = report["g3_expired_recall"]
        ok(g3["value"] == 0.0, f"③f g3 validity 防线残留=0（got {g3['value']}）")
        ok(g3["detail"]["raw"]["stale_hits"], "③g 默认面确实暴露过期节点（同题竞争成立）")
        ok(not g3["detail"]["guard"]["stale_hits"], "③h guard 面 top-k 无过期节点")

        g4 = report["g4_refusal_f1"]
        d4 = g4["detail"]
        ok(d4["tp"] + d4["fn"] == len(bg.UNANSWERABLE), "③i 不可答集计数守恒")
        ok(d4["fp"] + d4["tn"] == len(bg.FACTS), "③j 可答集计数守恒")
        ok(g4["value"] is not None and 0.0 <= g4["value"] <= 1.0,
           f"③k g4 F1 在 [0,1]（got {g4['value']}）")

        ok(report["meta"]["corpus_nodes"] >= 20, "③l 语料规模守卫")
        ok(all(report[g]["value"] is not None for g in
               ("g1_correction_propagation", "g2_contradiction_handling",
                "g3_expired_recall", "g4_refusal_f1")), "③m 四指标均可计算")
    finally:
        shutil.rmtree(root, ignore_errors=True)

    # ④ 确定性：重跑逐位一致
    r1, root1 = bg.run()
    r2, root2 = bg.run()
    shutil.rmtree(root1, ignore_errors=True)
    shutil.rmtree(root2, ignore_errors=True)
    strip = lambda r: {g: r[g]["value"] for g in r if g.startswith("g")}  # noqa: E731
    ok(strip(r1) == strip(r2), "④ 两次运行四指标逐位一致")

    # ⑤ main 输出 JSON 可写且结构完整
    tmp_dir = tempfile.mkdtemp(prefix="gov_out_")
    try:
        tmp_out = os.path.join(tmp_dir, "baseline.json")
        rc = bg.main(["--out", tmp_out])
        with open(tmp_out, encoding="utf-8") as f:
            data = json.load(f)
        ok(rc == 0 and {"meta", "g1_correction_propagation", "g2_contradiction_handling",
                        "g3_expired_recall", "g4_refusal_f1",
                        "baseline_reference"} <= set(data), "⑤ 输出 JSON 结构完整且 exit 0")
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    print("\nbench_governance selftest: %d failed" % len(_FAILED))
    return 1 if _FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
