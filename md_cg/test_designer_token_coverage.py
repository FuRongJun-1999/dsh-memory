# -*- coding: utf-8 -*-
# 功能名：设计者令牌覆盖面判据（DESIGNER_COVERAGE_OPS / coverage_gap）与签发告警守卫
# 生效条件：python -X utf8 -m md_cg.test_designer_token_coverage；被测面＝md_cg/tokens.py 的角色默认、issue() 告警、verify 体检输出
# 子功能：①designer 角色默认必须是全集 ["*"]（防默认被改窄）②不传 ops 签发 ⇒ 全集且 gap 为空 ③显式收窄到历史那 10 个 op ⇒ gap 恰 9 项（UI 撞墙面）④显式全集 ⇒ gap 为空 ⑤CLI 收窄签发在 stderr 告警、不传 ops 不告警 ⑥verify 对窄令牌输出 designer_coverage_gap、对宽令牌为空
# 执行：临时令牌库（空库首启自举）→ issue/CLI 两条路径 → 断言 gap 与告警 → verify 体检
# 验证方式：全部 PASS 即 exit 0；任一条失败 exit 1
# 不适用条件：不判「故意最小权限的窄令牌是否该存在」（合法用法，判据只做告警不阻断）；不判密钥材料本身
"""设计者令牌覆盖面守卫（2026-10-27）。

病象：线上 designer 令牌被收窄成 10 个 op，DSH 端 UI「自我认知」「审核与维护」
多项 AccessDenied；报错自述「角色 designer 本身含该 op，是签发时被收窄」——
**用了设计者令牌却看不了、裁不了**。

本守卫钉三件事：角色默认不得被改窄、收窄必须留下可观测告警、体检输出必须能看见缺口。
"""
import json
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from md_cg import tokens

_PASS, _FAIL = [], []


def ok(cond, msg, detail=""):
    (_PASS if cond else _FAIL).append(msg)
    print(("  PASS " if cond else "  FAIL ") + msg + (("  <- " + str(detail)) if detail and not cond else ""))


#: 线上那枚窄令牌的 ops（2026-09-26 签发，tk_ad734b789205）
_NARROW = ["info", "route", "read", "write", "recent", "goal", "identity",
           "whitebox", "verify", "task"]
#: 该窄集相对「读面+裁决面」的缺口（本常量即用户现场撞墙的面）
_EXPECT_GAP = ["help", "status", "edges", "self_state", "metacognition", "review",
               "protect", "evolution", "sustain"]
#: 界面/自动化应持的**只读面**（2026-10-27 使用者裁定：设计者只读、写需谨慎、
#: 裁决须反思+验证单元复核）—— 17 项，无 write/verify/破坏性 op。
_READONLY = ["info", "help", "status", "edges", "read", "route", "recent", "identity",
             "self_state", "metacognition", "review", "protect", "evolution",
             "sustain", "goal", "task", "whitebox"]


def _tmp_store():
    d = tempfile.mkdtemp(prefix="designer_cov_")
    return os.path.join(d, "_tokens.json")


def main():
    print("== A 角色默认必须是全集（防默认被改窄）")
    spec = tokens.role_spec("designer")
    ok(spec["ops_allow"] == ["*"], "A1 designer 角色默认 ops_allow == [\"*\"]", spec["ops_allow"])
    ok(spec["can_admin"] is True and spec["delegable"] is True,
       "A2 designer 仍可管理且可派生（角色语义未变）")

    print("== B 不传 ops 签发 ⇒ 全集，gap 为空")
    p1 = _tmp_store()
    r1 = tokens.issue("designer", actor="t-wide", path=p1)
    ok(r1["ops_allow"] == ["*"], "B1 签发记录 ops_allow == [\"*\"]", r1["ops_allow"])
    ok(tokens.coverage_gap(r1["ops_allow"]) == [], "B2 宽令牌 gap 为空")

    print("== C 显式收窄到线上那 10 个 op ⇒ gap 恰为 9 项")
    p2 = _tmp_store()
    r2 = tokens.issue("designer", actor="t-narrow", path=p2, ops_allow=list(_NARROW))
    gap = tokens.coverage_gap(r2["ops_allow"])
    ok(gap == _EXPECT_GAP, "C1 gap 恰为现场撞墙的 9 个 op", gap)
    ok("self_state" in gap and "review" in gap and "protect" in gap,
       "C2 缺口覆盖「自我认知/审核与维护」两类")

    print("== D 显式全集 ⇒ gap 为空")
    p3 = _tmp_store()
    r3 = tokens.issue("designer", actor="t-full", path=p3,
                      ops_allow=list(tokens.DESIGNER_COVERAGE_OPS))
    ok(tokens.coverage_gap(r3["ops_allow"]) == [], "D1 覆盖完整时无缺口")

    print("== E/G 非 designer 角色不受本判据影响")
    p4 = _tmp_store()
    r4 = tokens.issue("record", actor="t-rec", path=p4)
    ok(r4["ops_allow"] != ["*"], "E1 record 角色仍是自己的窄清单（不因本判据放开）", r4["ops_allow"])

    print("== F CLI：收窄签发必须在 stderr 告警；不传 ops 不告警")
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8",
           "MDCG_ALLOW_ROOT_ISSUE": "1"}
    def cli(store, *argv):
        """--token-file 是**全局**参数（须在子命令前），据此拼命令行。"""
        return [sys.executable, "-X", "utf8", "-m", "md_cg.tokens",
                "--token-file", store] + list(argv)

    base = None
    p5 = _tmp_store()
    c1 = subprocess.run(cli(p5, "issue", "--role", "designer", "--actor", "t-cli-narrow",
                            "--ops-allow", ",".join(_NARROW)),
                         cwd=repo, capture_output=True, text=True,
                         encoding="utf-8", errors="replace", env=env, timeout=180)
    ok(c1.returncode == 0, "F1 收窄签发本身成功（告警不阻断）", (c1.returncode, c1.stderr[-200:]))
    ok("收窄" in (c1.stderr or "") and "缺少" in (c1.stderr or ""),
       "F2 收窄签发在 stderr 告警（含「收窄/缺少」）", (c1.stderr or "")[-200:])
    ok("self_state" in (c1.stderr or "") or "review" in (c1.stderr or ""),
       "F3 告警点名缺失的读面/裁决面 op", (c1.stderr or "")[-200:])
    p6 = _tmp_store()
    c2 = subprocess.run(cli(p6, "issue", "--role", "designer", "--actor", "t-cli-wide"),
                        cwd=repo, capture_output=True, text=True,
                        encoding="utf-8", errors="replace", env=env, timeout=180)
    ok(c2.returncode == 0 and "收窄" not in (c2.stderr or ""),
       "F4 不传 ops 签发不产生告警", (c2.returncode, (c2.stderr or "")[-160:]))

    print("== G verify 体检：窄令牌报缺口、宽令牌为空")
    p7 = _tmp_store()
    r7 = tokens.issue("designer", actor="t-v-narrow", path=p7, ops_allow=list(_NARROW))
    v1 = subprocess.run(cli(p7, "verify", "--token", r7["token"]),
                        cwd=repo, capture_output=True, text=True,
                        encoding="utf-8", errors="replace", env=env, timeout=180)
    try:
        d1 = json.loads(v1.stdout or "{}")
    except Exception:
        d1 = {}
    ok(d1.get("designer_coverage_gap") == _EXPECT_GAP,
       "G1 verify 对窄令牌输出 designer_coverage_gap（9 项）",
       d1.get("designer_coverage_gap"))
    p8 = _tmp_store()
    r8 = tokens.issue("designer", actor="t-v-wide", path=p8)
    v2 = subprocess.run(cli(p8, "verify", "--token", r8["token"]),
                        cwd=repo, capture_output=True, text=True,
                        encoding="utf-8", errors="replace", env=env, timeout=180)
    try:
        d2 = json.loads(v2.stdout or "{}")
    except Exception:
        d2 = {}
    ok(d2.get("designer_coverage_gap") == [],
       "G2 verify 对宽令牌输出空缺口", d2.get("designer_coverage_gap"))

    print("== H 高风险面告警（全权限在不可靠的情况下就是灾难）")
    ok(tokens.high_risk_granted(["*"]) == ["*"], "H1 全权签发被识别")
    ok(tokens.high_risk_granted(_READONLY) == [],
       "H2 只读面令牌不含任何高风险 op（可安全给界面/自动化）",
       tokens.high_risk_granted(_READONLY))
    ok(set(tokens.high_risk_granted(["read", "write", "forget"])) == {"write", "forget"},
       "H3 写入/删除面被逐个点名")
    ok("verify" not in tokens.DESIGNER_COVERAGE_OPS,
       "H4 设计者应有面**不含** verify（裁决属验证单元复核通道，非设计者本职）")
    ok(tokens.coverage_gap(_READONLY) == [],
       "H5 只读 17 面即视为覆盖完整（去 verify 后无缺口）",
       tokens.coverage_gap(_READONLY))
    p9 = _tmp_store()
    c3 = subprocess.run(cli(p9, "issue", "--role", "designer", "--actor", "t-full-warn"),
                        cwd=repo, capture_output=True, text=True,
                        encoding="utf-8", errors="replace", env=env, timeout=180)
    ok("全权" in (c3.stderr or "") and "灾难" in (c3.stderr or ""),
       "H6 全权签发时 stderr 明确警告「全权限在不可靠的情况下就是灾难」",
       (c3.stderr or "")[-200:])

    print()
    print("设计者令牌覆盖面守卫：%d 通过 / %d 失败" % (len(_PASS), len(_FAIL)))
    if _FAIL:
        for f in _FAIL:
            print("  -", f)
    return 0 if not _FAIL else 1


if __name__ == "__main__":
    raise SystemExit(main())