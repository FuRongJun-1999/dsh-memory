# -*- coding: utf-8 -*-
"""test_check_publish_artifact_scan —— 发版门禁 scan_text_hits 全量命中守卫（N167）

背景（2026-09-27 缺陷 N167，severity=high）：scripts/check_publish_artifact.py
的 scan_text_hits 对每文件每规则只取首个 rx.search 命中，且 TOKEN_* 命中若
形似占位符（_looks_placeholder）即降级 NOTE 并 continue——continue 跳过的是
该规则在整篇文本上的余下扫描。同文件「占位符令牌在前、真实凭据在后」时，
真令牌整条逃逸 R1 内容面（FAIL 命中=0、NOTE=1、exit 0）——local/registry
两模式同源调用（local_mode/registry_mode 均走 scan_text_hits），发版门禁
系统性静默漏报。前提坐实（2026-09-27 实测）：package.json files 含 'docs'；
docs/hive/令牌与角色权职分离_v0.1.md 为追踪件且 TOKEN_MDCG 首配片段
=mdcg1.designer.tk_xxxxxxxxxxxx.xxxxxxxx、_looks_placeholder=True——
该文件内占位符之后再出现真令牌即可直达公开 registry。

守卫断言面（核心断言全哑数据，与仓库状态解耦；N8 为真实追踪件前提软复核）：
  N1（红点）占位符在前+真令牌在后（同文件同规则）→ FAIL 命中=1
  N2     真令牌在前+占位符在后 → FAIL=1（真命中坐实即判，护栏）
  N3     仅占位符 → FAIL=0 NOTE=1（占位符降级语义保持，selftest 原契约）
  N4     仅真令牌 → FAIL=1 NOTE=0
  N5     多规则同文件（TOKEN_SK 占位符在前真在后 + APIKEY_LITERAL 真命中）
         → 两条规则各计一条 FAIL（规则间不串扰）
  N6     非 TOKEN_* 规则（PRIVATE_KEY）不受占位符降级影响，命中即 FAIL
  N7     脚本自带 selftest() 全绿（含既有断言与新增断言的回归）
  N8     前提复核（软）：目标追踪件存在时 TOKEN_MDCG 首配为占位符形态
         （文件缺失 → SKIP，不计失败）

运行：python -X utf8 scripts/test_check_publish_artifact_scan.py
"""
import contextlib
import importlib.util
import io
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print("  [PASS] " + name)
    else:
        failed += 1
        print("  [FAIL] " + name + "  " + str(detail)[:300])


def _load_mod():
    p = os.path.join(HERE, "scripts", "check_publish_artifact.py")
    spec = importlib.util.spec_from_file_location("cpa_guard", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main():
    global passed, failed
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    mod = _load_mod()
    r1 = mod.R1_CONTENT_RULES

    # 真形态样串取自脚本 selftest（哑数据，非真实凭据）
    real_mdcg = ("mdcg1.designer.tk_9f3aK2mQ8vLpR4sT1uWz7yB6nH0cX5dE"
                 ".a1B2c3D4e5F6h7J8k9")
    fake_mdcg = "mdcg1.designer.tk_" + "x" * 12 + ".xxxxxxxx"
    real_sk = "sk-9f3aK2mQ8vLpR4sT1uWz7yB6nH0cX5dE"
    fake_sk = "sk-" + "x" * 32

    def rule_hits(text):
        """→ {label: (fail数, note数)}——按规则标签拆账。"""
        out = {}
        for label, rx in r1:
            h, n = mod.scan_text_hits(text, [(label, rx)], "x.md")
            out[label] = (len(h), len(n))
        return out

    # N1 红点：占位符在前、真令牌在后（同文件同规则）
    # 修后口径：真命中 FAIL=1（核心——修前为 (0,1) 真令牌整条逃逸）；
    # 途中占位符命中仍显式 NOTE=1（不静默丢弃契约）
    acc = rule_hits(fake_mdcg + "\n\n后续正文，其后真实凭据：" + real_mdcg + "\n")
    check("N1 占位符在前+真在后 → TOKEN_MDCG FAIL命中=1",
          acc["TOKEN_MDCG"] == (1, 1), acc)

    # N2 护栏：真在前（真命中坐实即判）
    acc = rule_hits(real_mdcg + "\n占位符示例：" + fake_mdcg + "\n")
    check("N2 真在前+占位符在后 → TOKEN_MDCG FAIL命中=1",
          acc["TOKEN_MDCG"] == (1, 0), acc)

    # N3 降级语义保持：仅占位符
    acc = rule_hits("示例令牌 " + fake_mdcg + "\n")
    check("N3 仅占位符 → FAIL=0 NOTE=1", acc["TOKEN_MDCG"] == (0, 1), acc)

    # N4 仅真
    acc = rule_hits("值=" + real_mdcg + "\n")
    check("N4 仅真 → FAIL=1 NOTE=0", acc["TOKEN_MDCG"] == (1, 0), acc)

    # N5 多规则不串扰：TOKEN_SK 占位符在前真在后 + APIKEY_LITERAL 真命中
    text5 = (fake_sk + "\n"
             "真 sk：" + real_sk + "\n"
             "api_key = \"1234567890123456\"\n")
    acc = rule_hits(text5)
    check("N5 TOKEN_SK 占位符在前真在后 → FAIL=1",
          acc["TOKEN_SK"] == (1, 1), acc)
    check("N5 APIKEY_LITERAL 真命中 → FAIL=1",
          acc["APIKEY_LITERAL"] == (1, 0), acc)

    # N6 非 TOKEN_* 规则不受降级影响（PRIVATE_KEY 在占位符令牌之后）
    text6 = (fake_mdcg + "\n"
             "-----BEGIN RSA PRIVATE KEY-----\n")
    acc = rule_hits(text6)
    check("N6 PRIVATE_KEY 命中即 FAIL（占位符令牌在前不影响）",
          acc["PRIVATE_KEY"] == (1, 0), acc)

    # N7 脚本自带 selftest 全绿（含既有断言回归）
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        st_ok = mod.selftest()
    check("N7 selftest() 全绿", st_ok is True,
          [ln for ln in buf.getvalue().splitlines() if "FAIL" in ln][:5])

    # N8 前提软复核：真实追踪件首配占位符（文件缺失 → SKIP 不计失败）
    target = os.path.join(HERE, "docs", "hive",
                          "令牌与角色权职分离_v0.1.md")
    if os.path.isfile(target):
        text8 = open(target, encoding="utf-8").read()
        m0 = r1[3][1].search(text8)          # TOKEN_MDCG
        check("N8 前提：目标追踪件 TOKEN_MDCG 首配为占位符形态",
              m0 is not None and mod._looks_placeholder(m0.group(0)),
              m0.group(0)[:50] if m0 else "无命中")
    else:
        print("  [SKIP] N8：目标追踪件不存在（docs/hive/令牌与角色权职分离"
              "_v0.1.md），前提复核跳过")

    print("\n%d passed, %d failed" % (passed, failed))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
