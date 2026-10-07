# -*- coding: utf-8 -*-
"""W5 路线B · 递归稳定性**加压对照**实证（零生产语义改动，隔离临时库）。

问题（`docs/eval/W5_标志线与融合核对_v0.1.md` §二 局限①）：
递归稳定性的首版证据证明的是「一致性可被机械校验、递归有界确定、重放幂等」，
**未证明**「在真实递归压力下决策不漂移」——缺一个**对照/扰动实验**。
本探针补这一格：对**同一批判定**跑「无压力 vs 加压力」两（三）档，产出可复跑的
**翻转率读数**，回答「递归在压力下是否漂移」。

三档压力（同一隔离库、同一批输入，只动压力旋钮）：
  A 无压力   limit=200（候选不截断）、depth=3（递归预算足）、无噪声节点；
  B 加压力   limit=3（候选超限截断）、depth=1（递归预算收紧）——判据面见
             `consistency.check` 的选面（scanned/kept/truncated）与 L2 递归（depth）；
  C 压力   limit=200/depth=3，但库内注入 40 条**无关噪声节点**（库增长压力，
             测「扰动是否漂移判定」）。

读数（每条）：verdict / conflict_strength / scanned / kept / truncated /
             recursion.stopped_by / recursion.depth。
翻转率：
  · **档内翻转率**＝同一档重复跑 R 次，逐条判定是否变化（一致性／确定性）；
  · **跨档翻转率**＝A vs B、A vs C 逐条判定是否变化（压力敏感度）；
  · **递归预算曲线**＝depth∈{0,1,2,3} 下判定与终止原因的变化（压力可调面）。

隔离声明：一切库为 `tempfile.mkdtemp` 临时根，用完即删；**只读**（check 传
log_write=False，不落台账）、**不碰活库**、不改任何生产语义。

用法：
  python -X utf8 scripts/probe_w5_recursion_pressure.py             # 正向读数
  python -X utf8 scripts/probe_w5_recursion_pressure.py --self-proof  # 自证（压力确已施加 + 基线可复跑）
  python -X utf8 scripts/probe_w5_recursion_pressure.py --json        # 机读读数
"""
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, ".")
sys.stdout.reconfigure(encoding="utf-8")

from md_cg.mdcos import MdCGOS          # noqa: E402
from md_cg import consistency as C      # noqa: E402

REPEATS = 3            # 档内重复次数（翻转率采样）
NOISE_N = 40           # C 档噪声节点数

# ---- 判定批（同一批在三档下各跑一遍；条数少但覆盖四态 + 递归）----------------
# 关键布局：k_offline / e_conf 是**相关节点**（在相关面里），必须落在过滤后索引序
# 前 limit 内（保底面），故先于填充节点写入；s_disc 是**区分节点**，故意放在别的
# 层（不在扫描面内 ⇒ 不作种子），只能经 e_conf 的因果边两跳到达——这样「递归是否
# 找到区分条件」才由**递归预算**（depth）决定，而不是由种子面决定。
BATCH = (
    dict(name="ACCEPT", layer="knowledge",
         content="# 功能：全新记录\n# 生效条件：无人占用的条件\n\n与既有结构无关。"),
    dict(name="REJECT_纪律", layer="self",
         content="删除生产数据"),
    dict(name="DEFER_条件互斥", layer="knowledge",
         content="# 功能：生产批处理\n# 生效条件：生产环境\n"),
    dict(name="DEFER_部分覆盖", layer="knowledge",
         content="# 功能：部分覆盖\n# 生效条件：生产环境 生产 车间\n"),
    dict(name="DEFER_递归", layer="knowledge",
         content="# 功能：待检\n# 生效条件：生产环境\n",
         non_applicable_conditions=["条件A"]),
    dict(name="BLINDSPOT", layer="contextual",
         content="# 功能：某情景\n# 生效条件：某个特殊条件\n\n无既有声明。"),
)


def _mkroot():
    import unicodedata
    return unicodedata.normalize("NFC", tempfile.mkdtemp(prefix="mdcg_w5rp_"))


def build_lib(root, noise=0):
    """确定性隔离库：相关节点在前（保底面），区分节点异层（只经边到达），可选噪声。"""
    cg = MdCGOS(root)
    # 相关节点（knowledge 层，索引序前段 → 保底面内）
    cg.add("k_offline",
           "# 功能：离线批处理\n# 生效条件：离线环境\n# 不适用条件：生产环境\n",
           layer="knowledge", non_applicable_conditions=["生产环境"], importance=0.4)
    cg.add("e_conf", "# 功能：冲突源\n# 生效条件：条件A\n",
           layer="knowledge", edges=[{"to": "s_disc"}], importance=0.4)
    # 区分节点：异层（structural）⇒ 不在 layer=knowledge 的扫描面内、不作种子，
    # 只能经 e_conf 的边到达 → 「递归能否找到它」由 depth 决定（纯递归预算压力）。
    cg.add("s_disc", "# 功能：区分节点\n",
           layer="structural", non_applicable_conditions=["生产环境"], importance=0.4)
    # 纪律节点（REJECT 靶）
    cg.add("discipline_prod", "# 功能：生产纪律\n# 执行：禁止删除生产数据\n",
           layer="self", tags=["discipline"],
           non_applicable_conditions=["删除生产数据"], importance=0.5)
    # 无条件节点（contextual 层）⇒ 该层可比对数=0 → BLINDSPOT 靶
    cg.add("c_plain", "情景笔记，没有任何条件声明。",
           layer="contextual", importance=0.3)
    # 填充节点（使候选超限；knowledge 层，索引序后段 → 可被截断）
    for i in range(15):
        cg.add("fill_%02d" % i,
               "# 功能：填充 %d\n# 生效条件：填充条件 %d\n" % (i, i),
               layer="knowledge", importance=0.2)
    # C 档噪声：层内无关节点（扰动压力）
    for i in range(noise):
        cg.add("noise_%03d" % i,
               "# 功能：无关噪声 %d\n# 生效条件：无关条件 %d\n" % (i, i),
               layer="knowledge", importance=0.2)
    cg.flush()
    return cg


def run(pressure):
    """在给定压力档下跑整批判定，返回 {name: 读数}。"""
    root = _mkroot()
    cg = build_lib(root, noise=pressure.get("noise", 0))
    try:
        out = {}
        for item in BATCH:
            r = cg.check_consistency(
                item["content"], layer=item["layer"],
                non_applicable_conditions=item.get("non_applicable_conditions"),
                depth=pressure["depth"], limit=pressure["limit"],
                log_write=False)
            rec = r.get("recursion") or {}
            out[item["name"]] = {
                "verdict": r["verdict"],
                "strength": round(r["conflict_strength"], 4),
                "scanned": r["scanned"], "kept": r["kept"],
                "truncated": bool(r["truncated"]),
                "stopped_by": rec.get("stopped_by"),
                "depth": rec.get("depth"),
            }
        return out
    finally:
        cg.close()
        shutil.rmtree(root, ignore_errors=True)


PRESSURES = {
    "A 无压力": dict(limit=200, depth=3, noise=0),
    "B 加压力": dict(limit=3, depth=1, noise=0),
    "C 噪声":   dict(limit=200, depth=3, noise=NOISE_N),
}


def _flip(a, b):
    """逐条比 verdict，返回翻转的条目名集合。"""
    return {k for k in a if a[k]["verdict"] != b[k]["verdict"]}


def _table(readings):
    names = [it["name"] for it in BATCH]
    hdr = ("条目", "verdict", "strength", "scanned", "kept", "trunc",
           "stopped_by", "depth")
    print("%-16s %-9s %8s %7s %5s %6s %-22s %5s" % hdr)
    for n in names:
        r = readings[n]
        print("%-16s %-9s %8.4f %7d %5d %6s %-22s %5s" % (
            n, r["verdict"], r["strength"], r["scanned"], r["kept"],
            r["truncated"], str(r["stopped_by"]), str(r["depth"])))


def collect():
    res = {}
    for tag, pr in PRESSURES.items():
        runs = [run(pr) for _ in range(REPEATS)]
        intra = set()
        base = runs[0]
        for other in runs[1:]:
            intra |= _flip(base, other)
        res[tag] = {"readings": base, "intra_flip": sorted(intra)}
    res["跨档 A→B"] = sorted(_flip(res["A 无压力"]["readings"],
                                    res["B 加压力"]["readings"]))
    res["跨档 A→C"] = sorted(_flip(res["A 无压力"]["readings"],
                                    res["C 噪声"]["readings"]))
    # 递归预算曲线（同库、同批，只动 depth）
    curve = {}
    for d in (0, 1, 2, 3):
        r = run(dict(limit=200, depth=d, noise=0))
        curve[str(d)] = {k: {"verdict": v["verdict"], "stopped_by": v["stopped_by"],
                             "depth": v["depth"]} for k, v in r.items()}
    res["预算曲线"] = curve
    return res


def _print_all(res):
    for tag in ("A 无压力", "B 加压力", "C 噪声"):
        print("\n===== %s（重复 %d 次，档内翻转：%s）====="
              % (tag, REPEATS, res[tag]["intra_flip"] or "无（0 条）"))
        _table(res[tag]["readings"])
    print("\n===== 跨档判定翻转 =====")
    print("A→B 翻转条目：", res["跨档 A→B"] or "无（0 条）")
    print("A→C 翻转条目：", res["跨档 A→C"] or "无（0 条）")
    print("\n===== 递归预算曲线（depth 0→3，同库同批）=====")
    for name in [it["name"] for it in BATCH]:
        cells = []
        for d in ("0", "1", "2", "3"):
            c = res["预算曲线"][d][name]
            cells.append("%s/%s" % (c["verdict"], c["stopped_by"] or "-"))
        print("%-16s %s" % (name, "  |  ".join(cells)))


def self_proof():
    """自证（fail-closed）：① 压力确已施加 ② 基线可复跑 ③ 无档内漂移。"""
    print("!! 自证：压力确已施加 + 同档可复跑 + 无档内漂移\n")
    bad = []
    a = run(PRESSURES["A 无压力"])
    b = run(PRESSURES["B 加压力"])
    c = run(PRESSURES["C 噪声"])

    # ① 压力确已施加：B 档确实发生候选截断（kept < scanned）
    trunc_b = [k for k, v in b.items() if v["truncated"]]
    if not trunc_b:
        bad.append("B 档未发生候选截断（压力①空转）")
    # ② 递归预算确已收紧：B 档递归深度 ≤1，A 档同一条可达更深受限更少
    deep_a = max((v["depth"] or 0) for v in a.values())
    deep_b = max((v["depth"] or 0) for v in b.values())
    if not (deep_b <= 1 or deep_a > deep_b):
        bad.append("B 档递归深度未收紧（压力②空转）：A=%s B=%s" % (deep_a, deep_b))
    # ③ C 档噪声确已注入（索引规模变大 → scanned 增大）
    if c["ACCEPT"]["scanned"] <= a["ACCEPT"]["scanned"]:
        bad.append("C 档噪声未生效（scanned 未增）")
    # ④ 基线可复跑：同档重复跑逐条同判
    for tag, pr in PRESSURES.items():
        r1, r2 = run(pr), run(pr)
        flip = _flip(r1, r2)
        if flip:
            bad.append("%s 档重复跑出现判定漂移：%s" % (tag, sorted(flip)))
    print("  B 档截断条目 %d 条（kept<scanned）：%s" % (len(trunc_b), trunc_b))
    print("  递归深度峰值：A=%s  B=%s（B 收紧生效）" % (deep_a, deep_b))
    print("  C 档 scanned：A=%s → C=%s（噪声生效）"
          % (a["ACCEPT"]["scanned"], c["ACCEPT"]["scanned"]))
    print("\n自证：%s" % ("PASS" if not bad else "FAIL —— " + "；".join(bad)))
    return 0 if not bad else 1


def main():
    if "--self-proof" in sys.argv:
        return self_proof()
    print("W5 路线B · 递归稳定性加压对照探针（隔离临时库，零生产语义改动）")
    print("=" * 78)
    res = collect()
    if "--json" in sys.argv:
        print(json.dumps(res, ensure_ascii=False, indent=2, default=str))
        return 0
    _print_all(res)
    print("\n" + "=" * 78)
    print("档内翻转率（同档重复 %d 次）：A=%s B=%s C=%s"
          % (REPEATS, res["A 无压力"]["intra_flip"] or "0",
             res["B 加压力"]["intra_flip"] or "0",
             res["C 噪声"]["intra_flip"] or "0"))
    print("跨档翻转率（A→B）：%d 条；跨档翻转率（A→C）：%d 条"
          % (len(res["跨档 A→B"]), len(res["跨档 A→C"])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
