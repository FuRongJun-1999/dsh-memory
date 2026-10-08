# -*- coding: utf-8 -*-
"""守卫 · export 默认路径同秒碰撞（#78，2026-10-09 DSH 端修复随附）。

缺陷（修前）：_default_out 用秒级时间戳命名，同秒两次导出得同一路径；且
_write_jsonl 的 tmp = out_path + '.tmp' 也同名 ⇒ 第二次 publish 直接覆盖
第一份快照，而**两个调用都返回 ok**（静默丢数据）。

修法：碰撞自增（首份保持原格式，仅目标已存在时追加 _1/_2…），并给 tmp 加
uuid 段防并发互踩。

判据（真跑为主）：
  G1 _default_out 连续三次（同秒内）返回三个互异路径
  G2 首个路径仍为 export_<kind>_<ts>.jsonl 旧格式（零兼容性影响）
  G3 真跑 export_graph ×3 → 目录内落三个 .jsonl（修前=1，两份被覆盖）
  G4 导出后无 .tmp 残留
运行：python -m md_cg.test_export_default_collision
      python -m md_cg.test_export_default_collision --self-proof   # 变异自证
退出码：0 全绿 ｜ 1 断言失败
"""
from __future__ import annotations

import os
import re
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
if REPO not in sys.path:
    sys.path.insert(0, REPO)

PASS = 0
FAIL = 0
FAILS = []
LEGACY_RE = re.compile(r"^export_graph_\d{8}_\d{6}\.jsonl$")


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("[PASS] %s%s" % (name, ("  · " + detail) if detail else ""))
    else:
        FAIL += 1
        FAILS.append(name)
        print("[FAIL] %s  · %s" % (name, detail))


def _cg(root):
    from md_cg import tokens as TK
    from md_cg.mdcos import MdCGSecure
    # 本机跑可设 MDCG_DSH_PROFILE 指向 DSH profile（内含 MDCG_TOKEN）；未设/读不到回落 guest 身份
    prof = os.environ.get("MDCG_DSH_PROFILE")
    tok = None
    if prof:
        try:
            m = re.search("MDCG_TOKEN:[ ]*'([^']+)'", open(prof, encoding="utf-8",
                                                             errors="replace").read())
            tok = m.group(1) if m else None
        except OSError:
            tok = None
    pr = TK.verify_token(tok) if tok else None
    return MdCGSecure(root, principal=pr)


def run():
    from md_cg import export

    root = tempfile.mkdtemp(prefix="cg78_guard_")
    cg = _cg(root)

    # G1 / G2
    # 注意：_default_out 是**纯查询**（只探存在性、不创建文件），故须"先占用再问"
    # 才观察得到让位行为；连问三次而其间不落盘，本就应返回同一路径。
    first = export._default_out(cg, "graph")
    open(first, "a", encoding="utf-8").close()          # 占用首份
    second = export._default_out(cg, "graph")
    open(second, "a", encoding="utf-8").close()         # 占用第二份
    third = export._default_out(cg, "graph")
    outs = [first, second, third]
    check("G1 目标被占用后 _default_out 让位（同秒不再同名覆盖）", len(set(outs)) == 3,
          str([os.path.basename(o) for o in outs]))
    check("G2 首份保持旧格式 export_<kind>_<ts>.jsonl",
          bool(LEGACY_RE.match(os.path.basename(outs[0]))),
          os.path.basename(outs[0]))

    # G3 / G4（真跑）
    for o in outs:
        if os.path.exists(o):
            os.remove(o)
    results = [export.export_graph(cg) for _ in range(3)]
    files = sorted(f for f in os.listdir(root) if f.endswith(".jsonl"))
    check("G3 真跑三次 → 落三个快照（修前=1，两份被静默覆盖）", len(files) == 3,
          "files=%d, ok=%s" % (len(files), all(r.get("ok") for r in results)))
    check("G4 无 .tmp 残留",
          not [f for f in os.listdir(root) if f.endswith(".tmp")], "")

    print("")
    print("=" * 64)
    print("通过 %d ／ 失败 %d" % (PASS, FAIL))
    if FAILS:
        print("失败项：" + "，".join(FAILS))
    print("=" * 64)
    return 1 if FAIL else 0


def self_proof():
    """变异自证：把 _default_out 还原为『无自增』版本 → G1/G3 必红；随后复原。"""
    target = os.path.join(HERE, "export.py")
    original = open(target, encoding="utf-8").read()
    NL = chr(10)
    mutated = original.replace(
        "    base = os.path.join(cg.root, f\"export_{kind}_{ts}\")" + NL +
        "    out = base + \".jsonl\"" + NL +
        "    if not os.path.exists(out):" + NL +
        "        return out",
        "    base = os.path.join(cg.root, f\"export_{kind}_{ts}\")" + NL +
        "    out = base + \".jsonl\"" + NL +
        "    if True:" + NL +
        "        return out", 1)
    if mutated == original:
        print("[FAIL] 自证：变异未生效（找不到锚点）")
        return 1
    try:
        open(target, "w", encoding="utf-8").write(mutated)
        print("== 变异已注入（撤掉碰撞自增）——期望 G1/G3 变红 ==")
        rc = run()
    finally:
        open(target, "w", encoding="utf-8").write(original)
    print("== 已复原 ==")
    print("[%s] 自证：变异后守卫变红并点名（rc=%d）" % ("PASS" if rc != 0 else "FAIL", rc))
    return 0 if rc != 0 else 1


if __name__ == "__main__":
    if "--self-proof" in sys.argv:
        sys.exit(self_proof())
    sys.exit(run())
