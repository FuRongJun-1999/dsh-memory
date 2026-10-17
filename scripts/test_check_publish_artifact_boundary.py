# -*- coding: utf-8 -*-
"""test_check_publish_artifact_boundary —— R1「TOKEN_SK 左边界」守卫（本笔修复的定点守卫）

背景（2026-10-16 实测，基线 a49fde2）：
  `scripts/check_publish_artifact.py` 的 R1 内容面 TOKEN_SK 原为 `sk-[A-Za-z0-9_\\-]{20,}`，
  **无左边界** ⇒ 任何以 `sk-` 结尾的普通标识后跟 ≥20 位字母数字即被判 **FAIL**——
  实测 `risk-` + 25 个 `a` 即误报。发版门禁的 FAIL 是"操作者必须去修"的信号，
  误报会让人去改无关代码，或让人对门禁脱敏（"它总在误报"）。
  **同仓 PII 族是正确写法**：`hive/exec.py` 的 PII-SK 用双侧 lookaround；
  本笔只把 R1 的**左边界**对齐它，右边界与长度下限的差异另立议题、不夹带。

守卫断言面（全部锚在"R1 内容面对该形态的判定"上）：
  G1 形似凭据的普通标识（`risk-` + 25 位）**不判 FAIL**（**本笔红点**）
  G2 真 `sk-` 令牌**仍判 FAIL**（回归：修法不许把真令牌放过）
  G3 占位符形态**仍降级为 NOTE、不 FAIL**（回归：既有降级面不许被改成 FAIL）
  G4 同批其它内容规则不受影响（`gh[pousr]_` 仍 FAIL）——防"改了 SK 顺带动了别的规则"
  M1 变异锚点在源码中恰好出现一次（仅 `--mutate`）
  M2 定点变异：镜像树里把左边界还原 ⇒ **恰好** G1 变红，G2/G3/G4 保持绿（仅 `--mutate`）

运行：
  python -X utf8 scripts/test_check_publish_artifact_boundary.py            # 全绿（CI 收集此行）
  python -X utf8 scripts/test_check_publish_artifact_boundary.py --mutate   # 定点变异自证
"""
import importlib.util
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TARGET = os.path.join(HERE, "scripts", "check_publish_artifact.py")

BS = chr(92)
#: 样例一律拼接构造（防本文件自身被 R1 规则命中）
FAKE_LIKE = "risk-" + "a" * 25                      # 普通标识：**不该**判 FAIL
REAL_SK = "sk-" + "a1b2c3d4e5f6g7h8i9j0k1l2m3n4"    # 真令牌形态：**该**判 FAIL
PLACEHOLDER_SK = "sk-" + "x" * 24                   # 占位符：应降级 NOTE、不 FAIL
REAL_GH = "ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"

passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print("  [PASS] " + name)
    else:
        failed += 1
        print("  [FAIL] " + name + ("  —— " + detail if detail else ""))


def load_mod(path):
    spec = importlib.util.spec_from_file_location("cpa_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def verdict(mod, text):
    """→ 'FAIL' / 'NOTE' / '—'（本模块 scan_text_hits 的语义，不改动它）"""
    hits, notes = mod.scan_text_hits(text, mod.R1_CONTENT_RULES, "probe.txt")
    if hits:
        return "FAIL"
    return "NOTE" if notes else "—"


def assert_set(mod, *, label="", record=True):
    bad_names = set()

    def guarded(name, cond, detail=""):
        full = ("[%s] " % label if label else "") + name
        if not cond:
            bad_names.add(name)
        if record:
            check(full, cond, detail)
        else:
            print("  [观测] %s %s%s" % ("红" if not cond else "绿", full,
                                       ("  —— " + detail) if (detail and not cond) else ""))

    v = verdict(mod, FAKE_LIKE)
    guarded("G1 形似凭据的普通标识不判 FAIL（本笔红点）", v != "FAIL",
            "实测判定=%s" % v)
    v = verdict(mod, REAL_SK)
    guarded("G2 真 sk- 令牌仍判 FAIL（回归）", v == "FAIL", "实测判定=%s" % v)
    v = verdict(mod, PLACEHOLDER_SK)
    guarded("G3 占位符形态仍为 NOTE、不 FAIL（回归）", v == "NOTE", "实测判定=%s" % v)
    v = verdict(mod, REAL_GH)
    guarded("G4 同批其它规则不受影响（gh_ 仍 FAIL）", v == "FAIL", "实测判定=%s" % v)
    return bad_names


def run_plain():
    assert_set(load_mod(TARGET))


def run_mutate():
    """定点变异：镜像树里把 TOKEN_SK 的左边界还原（绝不就地改源）。

    期望：**恰好** G1 变红；G2/G3/G4 保持绿（说明变异只动了这一处判据）。
    """
    src = open(TARGET, encoding="utf-8").read()
    anchor = '("TOKEN_SK", re.compile(r"(?<![0-9A-Za-z])sk-[A-Za-z0-9_' + BS + '-]{20,}")),'
    n = src.count(anchor)
    check("M1 变异锚点在源码中恰好出现一次", n == 1, "出现 %d 次" % n)
    if n != 1:
        return
    mutated = src.replace(anchor, anchor.replace("(?<![0-9A-Za-z])", ""), 1)
    check("M1b 变异体确实去掉了左边界", mutated != src)

    tmp = tempfile.mkdtemp(prefix="cpa_mutate_")
    try:
        mut_path = os.path.join(tmp, "check_publish_artifact.py")
        with open(mut_path, "w", encoding="utf-8") as f:
            f.write(mutated)
        reds = assert_set(load_mod(mut_path), label="变异体", record=False)
        expect = {"G1 形似凭据的普通标识不判 FAIL（本笔红点）"}
        check("M2 变异后**恰好** G1 变红（G2/G3/G4 保持绿）", reds == expect,
              "实得红项=%s，期望=%s" % (sorted(reds), sorted(expect)))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main(argv):
    print("=== R1 TOKEN_SK 左边界 · 守卫 ===")
    if "--mutate" in argv:
        print("[模式] 定点变异自证（镜像树，不就地改源）")
        run_mutate()
    else:
        print("[模式] 常规断言（CI 收集此行）")
        run_plain()
    print("\n%d passed, %d failed" % (passed, failed))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
