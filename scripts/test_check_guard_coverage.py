# -*- coding: utf-8 -*-
"""scripts/check_guard_coverage.py 的配对测试（issue #129 元守卫自证）。

跑法：
  python -X utf8 scripts/test_check_guard_coverage.py
  python -X utf8 scripts/test_check_guard_coverage.py --mutate=covered|no_registry|glob|surface_keys

变异自证（注入必失败 ⇒ 断言必红并点名）：
  --mutate=surface_keys 把反向判据换回 #179 落地时的**缺陷版**（扫 package.json 的
  全部 scripts 键），于是「非执行面脚本文案里的路径不进反向判据面」这条断言必红。
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PASS = []
FAIL = []


def ok(name: str, cond: bool, detail: str = "") -> None:
    (PASS if cond else FAIL).append(name + ("  · " + detail if detail else ""))


def load_guard():
    p = os.path.join(REPO, "scripts", "check_guard_coverage.py")
    spec = importlib.util.spec_from_file_location("guardcov", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def synth(tmp: str, gate: str = "python scripts/check_alpha.py",
          prepare: str = "") -> str:
    """合成小仓：alpha 被 gate 点名；beta 被 CI 点名；gamma 有配对测试；delta 孤儿。

    `prepare` 用来注入**非执行面**脚本的文案（#179 判据面越权的实况形态）。
    """
    os.makedirs(os.path.join(tmp, "scripts"))
    os.makedirs(os.path.join(tmp, ".github", "workflows"))
    scripts = {"gate": gate}
    if prepare:
        scripts["prepare"] = prepare
    with open(os.path.join(tmp, "package.json"), "w", encoding="utf-8") as fh:
        json.dump({"scripts": scripts}, fh)
    with open(os.path.join(tmp, ".github", "workflows", "w.yml"), "w", encoding="utf-8") as fh:
        fh.write("run: python scripts/check_beta.py\n")
    for n in ("check_alpha.py", "check_beta.py", "check_gamma.py", "check_delta.py"):
        with open(os.path.join(tmp, "scripts", n), "w", encoding="utf-8") as fh:
            fh.write("# x\n")
    with open(os.path.join(tmp, "scripts", "test_check_gamma.py"), "w", encoding="utf-8") as fh:
        fh.write("# x\n")
    return tmp


def states(mod, root: str) -> dict:
    info = mod.build(root)
    return {os.path.basename(r["guard"]): r["state"] for r in info["guards"]}


def legacy_missing_named_paths(mod, repo_root: str) -> list:
    """#179 落地时的**缺陷版**反向判据：扫 package.json 的**全部** scripts 键。

    只用于 --mutate=surface_keys 的定点变异自证（注入历史缺陷 ⇒ 守卫断言必红并点名）。
    """
    pj_path = os.path.join(repo_root, "package.json")
    if not os.path.isfile(pj_path):
        raise OSError("package.json 不存在：" + pj_path)
    with open(pj_path, "r", encoding="utf-8") as fh:
        scripts = json.load(fh).get("scripts") or {}
    named = set()
    for k in sorted(scripts):
        named |= mod.named_paths_in(str(scripts[k]))
    named |= mod.named_paths_in(mod._workflow_run_text(repo_root))
    return [r for r in sorted(named)
            if not os.path.exists(os.path.join(repo_root, r.replace("/", os.sep)))]


def run(mutate: str) -> int:
    """三条变异 + 一套**恒定的核心断言**。

    设计要旨（吸取既往教训）：变异必须**破坏守卫的判据**，然后由**同一套断言**把它逮住
    ——而不是单独为变异写一条「变异生效了」的断言（那是空跑，永远绿）。
    """
    mod = load_guard()
    tmp = tempfile.mkdtemp(prefix="guardcov_test_")
    # #161 实况：prepare（**非执行面**）的错误文案里提到 lib/index.js（构建产物，
    # 干净克隆上必然不存在）。它不得进反向判据面——否则元守卫在干净克隆上恒退 4。
    synth(tmp, prepare="node -e \"if(!require('fs').existsSync('lib/index.js'))process.exitCode=1\"")

    if mutate == "covered":
        # 判据被破坏：分类恒返回「已覆盖」⇒ 孤儿再也识别不出来
        mod.classify = lambda g, sf: ("covered_direct", "mutated")
    if mutate == "no_registry":
        # 判据被破坏：登记表被清空 ⇒ 真仓的已登记例外重新变成孤儿
        mod.EXCEPTIONS.clear()
    if mutate == "glob":
        # 判据被破坏：配对测试收集面被清空 ⇒ 有配对测试的守卫被误判为孤儿
        mod.COLLECT_GLOBS = ()
    if mutate == "surface_keys":
        # 判据被破坏：反向判据换回 #179 落地时的缺陷版（扫 package.json 全部 scripts 键）
        mod.missing_named_paths = lambda root: legacy_missing_named_paths(mod, root)

    st = states(mod, tmp)

    # ---- 核心断言（与变异无关，恒定执行）----
    ok("alpha 被 gate 点名 ⇒ covered_direct", st.get("check_alpha.py") == "covered_direct",
       str(st.get("check_alpha.py")))
    ok("beta 被 CI 点名 ⇒ covered_direct", st.get("check_beta.py") == "covered_direct",
       str(st.get("check_beta.py")))
    ok("gamma 有配对测试 ⇒ covered_test", st.get("check_gamma.py") == "covered_test",
       str(st.get("check_gamma.py")))
    ok("delta 无执行面 ⇒ orphan（与 gamma 同仓对照）", st.get("check_delta.py") == "orphan",
       str(st.get("check_delta.py")))

    # ---- 反向判据面（#179）：判据面 = 执行面，非执行面文案不得成为判据对象 ----
    synth_missing = mod.missing_named_paths(tmp)
    ok("非执行面脚本（prepare）文案里的路径不进反向判据面（#179 判据面越权）",
       synth_missing == [], str(synth_missing))

    real = mod.build(REPO)
    ok("真仓无未登记孤儿（退出码 0）", mod.exit_code(real) == 0,
       "orphans=" + str(real["orphans"]) + " bad=" + str(real.get("bad_registry")))
    ok("真仓反向判据面无假阳性（点名缺失 0）", real["missing_named"] == [],
       str(real["missing_named"]))

    # ---- 「正反两向同源」这条不变量本身必须有守护（否则两侧将来再分叉也不会变红）----
    # ① workflow run: 抽取：正向（gather_surfaces.ci_text）与反向（_workflow_run_text）
    #    必须是同一套规则，否则「正向看得见、反向看不见」会开出假阴性通道。
    _sf_real = mod.gather_surfaces(REPO)
    _fwd = mod.named_paths_in(_sf_real["ci_text"])
    _rev = mod.named_paths_in(mod._workflow_run_text(REPO))
    ok("正反两向的 workflow run: 抽取同源（点名路径集合逐字相同）", _fwd == _rev,
       "forward=%d reverse=%d 差集=%s" % (len(_fwd), len(_rev), sorted(_fwd ^ _rev)))
    # ② package.json 脚本键：两向必须读同一个 SURFACE_SCRIPT_KEYS。
    #    把 prepare 纳入执行面后，正向 gate_text 与反向 missing 必须**同时**变化。
    _saved = mod.SURFACE_SCRIPT_KEYS
    mod.SURFACE_SCRIPT_KEYS = ("gate", "prepare")
    try:
        _sf2 = mod.gather_surfaces(tmp)
        _rev2 = mod.missing_named_paths(tmp)
    finally:
        mod.SURFACE_SCRIPT_KEYS = _saved
    ok("两向共用 SURFACE_SCRIPT_KEYS（常量一改，正反两向同时变化）",
       "lib/index.js" in _sf2["gate_text"] and _rev2 == ["lib/index.js"],
       "forward=%s reverse=%s" % ("lib/index.js" in _sf2["gate_text"], _rev2))

    ok("真仓守卫数 >= 8", real["n_guards"] >= 8, str(real["n_guards"]))
    gc = [r for r in real["guards"] if r["guard"].endswith("check_guard_coverage.py")]
    ok("check_guard_coverage 自身有执行面（本测试即其配对测试）",
       bool(gc) and gc[0]["state"] == "covered_test", str(gc[0]["state"]) if gc else "缺失")

    # ---- 反向判据的**正向控制**：防「一律不报」的空判据 ----
    tmp2 = tempfile.mkdtemp(prefix="guardcov_named_")
    os.makedirs(os.path.join(tmp2, "scripts"))
    os.makedirs(os.path.join(tmp2, ".github", "workflows"))
    with open(os.path.join(tmp2, "package.json"), "w", encoding="utf-8") as fh:
        json.dump({"scripts": {"gate": "python scripts/check_alpha.py scripts/check_ghost.py"}}, fh)
    with open(os.path.join(tmp2, ".github", "workflows", "w.yml"), "w", encoding="utf-8") as fh:
        fh.write("run: python scripts/check_ghost2.py\n")
    with open(os.path.join(tmp2, "scripts", "check_alpha.py"), "w", encoding="utf-8") as fh:
        fh.write("# x\n")
    miss2 = mod.missing_named_paths(tmp2)
    ok("执行面点名的缺失件必被抓（gate + workflow 两向）",
       miss2 == ["scripts/check_ghost.py", "scripts/check_ghost2.py"], str(miss2))
    ok("点名缺失 ⇒ 退 4（#179 反向判据仍有牙齿）",
       mod.exit_code(mod.build(tmp2)) == 4, str(mod.exit_code(mod.build(tmp2))))

    if mutate == "":
        bad = tempfile.mkdtemp(prefix="guardcov_nopj_")
        try:
            mod.build(bad)
            ok("缺 package.json ⇒ OSError（fail-closed）", False, "未抛")
        except OSError:
            ok("缺 package.json ⇒ OSError（fail-closed）", True)
        saved = dict(mod.EXCEPTIONS)
        try:
            mod.EXCEPTIONS["check_delta.py"] = {"reason": "x"}
            ok("登记表缺 owner/review ⇒ 退 3", mod.exit_code(mod.build(tmp)) == 3)
        finally:
            mod.EXCEPTIONS.clear()
            mod.EXCEPTIONS.update(saved)

    print("")
    for x in PASS:
        print("  [PASS] " + x)
    for x in FAIL:
        print("  [FAIL] " + x)
    print("")
    print("  check_guard_coverage 守卫：%d pass / %d fail" % (len(PASS), len(FAIL)))
    return 1 if FAIL else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mutate", default="",
                    choices=("", "covered", "no_registry", "glob", "surface_keys"))
    a = ap.parse_args()
    return run(a.mutate)


if __name__ == "__main__":
    sys.exit(main())
