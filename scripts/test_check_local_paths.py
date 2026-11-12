# -*- coding: utf-8 -*-
"""test_check_local_paths —— B6「用户实名目录」8.3 短名守卫（本笔修复的定点守卫）

背景（2026-10-16 实测，基线 a49fde2）：
  `scripts/check_local_paths.py` 的 `_build_rules()` 第 ⑥ 族把 8.3 短名拼成
  `"FU" + " RONG~1"`（**多一个空格**）⇒ 生效形态 `FU RONG~1` ⇒ 真实存在的 8.3 短名写法
  **整类漏抓**；而该脚本的 `selftest()` 正样例只喂长名 ⇒ **判据与自证同时漏**
  （修前 `--selftest` 一直是 PASS）。同仓姊妹件 `check_publish_artifact.py` 的 R3-b
  拼的是无空格形态 ⇒ 同一形态在两个守卫之间口径分叉。

守卫断言面（全部锚在「这一族正则的生效形态」上）：
  G1 模块自带 `hit_samples()` 无问题（自证通过）
  G2 长名命中（**回归**：防修坏既有面）
  G3 短名的三种写法（`\\`、`/`、`\\\\` 转义）**全部**命中（**本笔红点**）
  G4 全部负样例零命中（**反面对照**：修法不许把合成夹具/别的用户一并变成红）
  G5 模块自身源码零命中（本仓体例：规则字面量与样例一律拼接构造）
  M1 变异锚点在源码中恰好出现一次（仅 `--mutate`）
  M2 定点变异：把 ⑥ 族还原成带空格形态 ⇒ **恰好**锚在那一处的两条断言变红；G2/G4/G5 保持绿

运行：
  python -X utf8 scripts/test_check_local_paths.py            # 全绿（CI 收集此行）
  python -X utf8 scripts/test_check_local_paths.py --mutate   # 定点变异自证：恰好红 G3
"""
import importlib.util
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TARGET = os.path.join(HERE, "scripts", "check_local_paths.py")

BS = chr(92)
SL = "/"
LONG_NAME = "Fu" + "RongJun"
SHORT_NAME = "FU" + "RONG~1"

#: 短名的三种写法（一律拼接构造，防本文件自身被规则命中）
SHORT_SAMPLES = [
    ("反斜杠", "C:" + BS + "Users" + BS + SHORT_NAME + BS + "x"),
    ("正斜杠", "C:" + SL + "Users" + SL + SHORT_NAME + SL + "x"),
    ("双反斜杠（转义）", "C:" + BS + BS + "Users" + BS + BS + SHORT_NAME + BS + BS + "x"),
]
LONG_SAMPLE = "C:" + BS + "Users" + BS + LONG_NAME + BS + "x"

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
    spec = importlib.util.spec_from_file_location("clp_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def family_hits(mod, sample):
    return [lab for lab, rx in mod.RULES if rx.search(sample)]


def assert_set(mod, *, label="", record=True):
    """对给定模块跑 G1–G5。

    `record=True` ⇒ 计入全局通过/失败（本体模式）；
    `record=False` ⇒ **只观测**：变异体的红项是**期望内**的事实，不能计成本守卫的失败
    （否则「变异恰好点红」这个自证会被自己的记账方式判成不通过）。
    返回失败项名集合。
    """
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

    guarded("G1 模块自带自证无问题", mod.hit_samples() == [],
            "hit_samples=%s" % (mod.hit_samples(),))
    guarded("G2 长名命中（回归）", family_hits(mod, LONG_SAMPLE) != [],
            "长名未命中：%s" % LONG_SAMPLE)
    miss = [w for w, s in SHORT_SAMPLES if not family_hits(mod, s)]
    guarded("G3 短名三种写法全部命中（本笔红点）", not miss,
            "漏抓写法：%s" % "、".join(miss))
    fp = []
    for s in mod.NEGATIVE_SAMPLES:
        for lab, rx in mod.RULES:
            if rx.search(s):
                fp.append("%s <- %s" % (lab, s))
    guarded("G4 负样例零命中（反面对照）", not fp, "；".join(fp[:3]))
    own = mod.own_source_clean(os.path.abspath(mod.__file__))
    guarded("G5 模块自身源码零命中", not own, "自身命中：%s" % "、".join(own))
    return bad_names


def run_plain():
    mod = load_mod(TARGET)
    assert_set(mod)


def run_mutate():
    """定点变异：**镜像树里**把 ⑥ 族还原成带空格形态（绝不就地改源）。

    期望：**恰好** G3 变红 —— G2（长名）与 G4（负样例）必须保持绿，
    否则说明这次变异同时动了别的判据（多红 = 语义纠缠）。
    """
    src = open(TARGET, encoding="utf-8").read()
    old = '"RongJun|FU" + "' + 'RONG~1)"'
    new = '"RongJun|FU" + "' + ' RONG~1)"'
    n = src.count(old)
    check("M1 变异锚点在源码中恰好出现一次", n == 1, "出现 %d 次" % n)
    if n != 1:
        return

    tmp = tempfile.mkdtemp(prefix="clp_mutate_")
    try:
        mut_path = os.path.join(tmp, "check_local_paths.py")
        with open(mut_path, "w", encoding="utf-8") as f:
            f.write(src.replace(old, new, 1))
        mut = load_mod(mut_path)
        reds = assert_set(mut, label="变异体", record=False)
        # ★ 期望红项是**锚在本次修复那一处**的两条断言，且只有它们：
        #   G1 = 模块自带自证（本笔已把短名补进它的正样例）—— 模块自己的尺子；
        #   G3 = 本守卫的独立检查 —— 第二把尺子（独立见证者）。
        #   两条量的是**同一个点**（⑥ 族短名分支），属**刻意的双尺冗余**，
        #   不是语义纠缠：证据是 G2（长名回归）与 G4（负样例反面对照）在变异下**保持绿**
        #   ⇒ 变异是局部的、没有牵连别的判据。
        expect = {"G1 模块自带自证无问题",
                  "G3 短名三种写法全部命中（本笔红点）"}
        check("M2 变异后红项恰好等于『锚在本次修复那一处』的两条（G2/G4/G5 保持绿）",
              reds == expect,
              "实得红项=%s，期望=%s" % (sorted(reds), sorted(expect)))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main(argv):
    print("=== B6 用户实名目录 · 8.3 短名守卫 ===")
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
