# -*- coding: utf-8 -*-
# 功能名：门禁档位（--gate fast|strict）与模块过滤（--module）的守卫
# 生效条件：python -X utf8 scripts/test_run_tests_gate.py；被测面＝scripts/run_tests.py 的 _heavy_reason / --gate / --module / CI 自动升级
# 子功能：①重质检判据归一（点号与斜杠都命中）②fast 跳过并留痕 ③strict 全跑 ④CI+fast 自动升级 ⑤--module 前缀过滤 ⑥缺省仍是 strict
# 执行：subprocess 跑 run_tests.py 断言输出行；判据归一用 import 直测
# 验证方式：全部 PASS exit 0，否则 exit 1
# 不适用条件：不判守卫内部是否跑变异（各守卫自己的 --mutate 面）；不判真实 CI 环境（只判 CI 变量存在时的升级）
"""门禁档位守卫（2026-10-27 使用者裁定：快/慢是价值观取舍，选择权交给使用者；
模块化只做自己那一个功能，是否开启重质检交给上层）。"""
import importlib.util
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "scripts", "run_tests.py")

_PASS, _FAIL = [], []


def ok(cond, msg, detail=""):
    (_PASS if cond else _FAIL).append(msg)
    print(("  PASS " if cond else "  FAIL ") + msg + (("  <- " + str(detail)) if detail and not cond else ""))


def _load():
    spec = importlib.util.spec_from_file_location("_rt_gate", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run(*argv, env_extra=None):
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
    env.pop("CI", None)
    if env_extra:
        env.update(env_extra)
    r = subprocess.run([sys.executable, "-X", "utf8", SCRIPT, *argv],
                       cwd=ROOT, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", env=env, timeout=900)
    return (r.stdout or "") + (r.stderr or ""), r.returncode


def main():
    print("== A 重质检判据（归一：点号 / 斜杠）")
    mod = _load()
    ok(mod._heavy_reason("md_cg.test_issue452_ingest_root_sensitivity") != "",
       "A1 点号形态命中重质检")
    ok(mod._heavy_reason("md_cg/test_issue452_ingest_root_sensitivity") != "",
       "A2 斜杠形态命中重质检")
    ok(mod._heavy_reason("md_cg.test_issue452_ingest_root_hint") == "",
       "A3 轻量同族守卫不被误判")
    ok(mod._heavy_reason("md_cg.test_issue93_remember_redaction") != "",
       "A4 复用 MUTATE_GUARDS 登记（不另立清单）")

    print("== B fast 档：跳过并留痕")
    out, rc = _run("md_cg", "-k", "issue452", "--gate", "fast")
    ok("SKIP  md_cg.test_issue452_ingest_root_sensitivity" in out and "gate=fast" in out,
       "B1 fast 档明确 SKIP 并给原因与升级提示", out[-300:])
    ok("跳过 1 条重质检" in out, "B2 fast 档给出跳过计数（可核验）", out[-300:])
    ok("PASS  md_cg.test_issue452_ingest_root_hint" in out,
       "B3 轻量守卫照常执行", out[-300:])
    ok(rc == 0, "B4 fast 档退出码 0", rc)

    print("== C strict 档：全跑")
    out2, rc2 = _run("md_cg", "-k", "issue452", "--gate", "strict")
    ok("SKIP  md_cg.test_issue452_ingest_root_sensitivity" not in out2,
       "C1 strict 档不跳过", out2[-300:])
    ok("PASS  md_cg.test_issue452_ingest_root_sensitivity" in out2,
       "C2 strict 档真跑了重质检守卫", out2[-300:])
    ok(rc2 == 0, "C3 strict 档退出码 0", rc2)

    print("== D CI + fast ⇒ 自动升级（防漏检）")
    out3, _rc3 = _run("md_cg", "-k", "issue452", "--gate", "fast", env_extra={"CI": "true"})
    ok("自动升级为 strict" in out3, "D1 明确告警自动升级", out3[-300:])
    ok("SKIP  md_cg.test_issue452_ingest_root_sensitivity" not in out3,
       "D2 升级后不跳过（CI 不会因 fast 漏检）", out3[-300:])

    print("== E --module 前缀过滤")
    out4, _rc4 = _run("md_cg", "--module", "test_issue452", "--list")
    ok("md_cg    md_cg.test_issue452_ingest_root_hint" in out4
       and "md_cg    md_cg.test_issue452_ingest_root_sensitivity" in out4,
       "E1 --module 只列匹配模块", out4[:300])
    ok("共 2 个" in out4, "E2 过滤后计数正确", out4[:300])

    print("== F 缺省仍是 strict（不改变既有门禁强度）")
    src = open(SCRIPT, encoding="utf-8").read()
    ok("default=\"strict\"" in src, "F1 缺省档位 strict 在位")
    ok("--gate" in src and "--module" in src, "F2 两个新参数都在位")

    print()
    print("门禁档位守卫：%d 通过 / %d 失败" % (len(_PASS), len(_FAIL)))
    if _FAIL:
        for f in _FAIL:
            print("  -", f)
    return 0 if not _FAIL else 1


if __name__ == "__main__":
    raise SystemExit(main())