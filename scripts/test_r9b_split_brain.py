# -*- coding: utf-8 -*-
# 功能名：发布闸 R9b（同一判据分叉两落点）的定点变异自证
# 生效条件：python -X utf8 scripts/test_r9b_split_brain.py；被测面＝
#   `check_publish_artifact._split_brain_split` 的三档判定
#   （无分叉 / 已登记薄壳 NOTE / 未登记判负）。
# 子功能：M1 未登记分叉必红；M2 登记后转 NOTE；M3 非薄壳同名不同物不误报；
#   M4 测试件并行套件不误报；M5 本体移入随包面后分叉消失。
# 执行：纯函数级变异（临时改内存里的登记表/包面集合），不写仓内任何文件。
# 验证方式：5/5 PASS exit 0；每节注明「怎么让它红」。
# 不适用条件：不跑真实 npm pack（那要 prepare 能构建，本机无 typescript）；
#   不覆盖 R9a 的装载关系面（见 check_publish_artifact 的 R9a 分支）。

"""为什么要有它（2026-11-02，**判据本身曾写错两次**）：

第一版 R9 只查「随包模块装载包外件」。实测它对本轮真实缺陷**恒绿**——
因为装载方 `sync_zcode_session.py` 自己也不随包，整条关系落进
「整链不发布」NOTE 档。

本轮缺陷的真形态是：`state_extract.py` 的**本体**已在 `md_cg/`（随包），
`scripts/` 下留的**薄垫片**不随包 ⇒「同一判据两个落点，一个发货一个不发」。

只查装载关系看不见这一层。故补 R9b，并必须自证它真能红。
"""

from __future__ import annotations

import importlib.util
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

_P, _F = [], []


def ok(cond, msg, detail=""):
    (_P if cond else _F).append(msg)
    print(("  PASS " if cond else "  FAIL ") + msg
          + (("  <- " + str(detail)) if detail and not cond else ""))


def _load():
    p = os.path.join(REPO, "scripts", "check_publish_artifact.py")
    spec = importlib.util.spec_from_file_location("_cpa_probe", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _shipped_files(m, prefixes):
    """按给定前缀构造「随包面」，并返回这些前缀下真实存在的仓内文件。"""
    out = []
    for root, dirs, files in os.walk(REPO):
        dirs[:] = [d for d in dirs if d not in m._R9_SKIP_DIRS]
        for fn in files:
            rel = os.path.relpath(os.path.join(root, fn), REPO).replace("\\", "/")
            if any(rel == p.rstrip("/") or rel.startswith(p.rstrip("/") + "/")
                   for p in prefixes):
                out.append(rel)
    return out


def _verdicts(m, pkg_set):
    v = m._split_brain_split(REPO, pkg_set)
    return ([e for k, e in v if k == "unregistered"],
            [e for k, e in v if k == "registered"])


def main():
    m = _load()

    # 真实包面：读 package.json 的 files（与生产同源）
    import json
    pkg = json.load(open(os.path.join(REPO, "package.json"), encoding="utf-8"))
    real_pkg = _shipped_files(m, [f for f in (pkg.get("files") or [])])

    print("== M0 基线：本轮缺陷（state_extract 分叉）当前为**已登记**（带前提）")
    bad, good = _verdicts(m, real_pkg)
    reg = [x for x in good if x.startswith("state_extract.py")]
    ok(bool(reg) and not [x for x in bad if x.startswith("state_extract.py")],
       "M0a state_extract 已登记为薄垫片（前提：装载方不随包）", bad)
    ok(any("不随包" in x for x in reg),
       "M0b 登记文本明写前提（不静默放行）", reg)

    print("== M0c 前提失效 ⇒ 登记自动作废（怎么让它红：去掉 requires_not_shipped）")
    # 模拟「sync_zcode_session.py 已进包」：装机侧会真执行该装载
    fake_dep = list(real_pkg) + ["scripts/sync_zcode_session.py"]
    bad_dep, _ = _verdicts(m, fake_dep)
    hit = [x for x in bad_dep if x.startswith("state_extract.py")]
    ok(bool(hit),
       "M0c 装载方进包后，state_extract 登记失效并重新判负", bad_dep)
    ok(any("登记已失效" in x for x in hit),
       "M0d 失效原因如实写出（不静默）", hit)

    print("== M1 登记表整体清空 ⇒ 全部转判负")
    saved = dict(m.R9B_REGISTERED_SHIMS)
    try:
        m.R9B_REGISTERED_SHIMS.clear()
        bad1, good1 = _verdicts(m, real_pkg)
        ok(len(bad1) == len(bad) + len(good),
           "M1 清空登记后，原先已登记的 %d 组全部转判负" % len(good), bad1)
    finally:
        m.R9B_REGISTERED_SHIMS.clear()
        m.R9B_REGISTERED_SHIMS.update(saved)

    print("== M2 非薄壳同名不同物不误报（怎么让它红：把薄壳识别放宽成「同名即判」）")
    # compiler/parser.py 与 md_cg/whitebox_kb/wisdom/core/parser.py 同名不同物
    names = [x.split("：")[0] for x in bad + good]
    ok("parser.py" not in names,
       "M2a 同名不同物（parser.py）未被误判为分叉", names)
    ok("mcp_server.py" not in names,
       "M2b hive/mcp_server.py 与 md_cg/mcp_server.py 未被误判", names)

    print("== M3 并行测试套件不误报（怎么让它红：去掉 test_ 前缀豁免）")
    ok(not any(n.startswith("test_") for n in names),
       "M3 md_cg/test_*.py 与 tests/test_*.py 并行套件未被判为分叉", names)

    print("== M4 本体移入随包面后分叉消失（怎么让它红：判据不看包面只看名字）")
    fake = list(real_pkg) + ["scripts/state_extract.py"]
    bad2, good2 = _verdicts(m, fake)
    ok(not [x for x in bad2 + good2 if x.startswith("state_extract.py")],
       "M4 两落点都随包 ⇒ 不再是分叉（判据确实读包面）", (bad2, good2))

    print()
    print("R9b 定点变异自证：%d 通过 / %d 失败" % (len(_P), len(_F)))
    for f in _F:
        print("  -", f)
    return 0 if not _F else 1


if __name__ == "__main__":
    raise SystemExit(main())
