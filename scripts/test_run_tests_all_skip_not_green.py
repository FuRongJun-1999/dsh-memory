# -*- coding: utf-8 -*-
# 功能名：全跳过假绿守卫（run_tests 入口「零执行仍报绿」第三形态）
# 生效条件：python -X utf8 scripts/test_run_tests_all_skip_not_green.py [--mutate]；被测面＝scripts/run_tests.py 的「全部跳过时退出码」
# 子功能：①全跳过 ⇒ rc=3（不是 0）②部分跳过但至少一条真跑 ⇒ rc=0（不误伤设计内 SKIP）③零选中仍 rc=2（既有语义不被覆盖）④--list 仍 rc=0（查看语义）⑤全通过仍 rc=0 ⑥判别力自证：旧实现（无该门）对同一输入会返回 0
# 执行：子进程跑 run_tests.py 断言退出码与输出行；--mutate 对实现做定点破坏并断言守卫转红
# 验证方式：全部 PASS exit 0；--mutate 下每臂都必须精确打红（见 MUTATIONS）
# 不适用条件：不判 SKIP 原因本身是否正当（那是各守卫自己的依赖探测面）；不判部分跳过时跳过了哪几条
"""全跳过假绿守卫。

病灶（2026-11-08 实测）：`scripts/run_tests.py` 已修过两次「沉默通过」同族缺陷——
  · #1910：`--module` 选择器写错 ⇒ 选中 0 个目标，`SUMMARY 0/0` + rc=0（已修为 rc=2）
  · #284 ：模块内打印 SKIP ⇒ 曾被当 PASS 计入通过数（已修为不计入）
但**第三形态**没被挡住：目标选中了、却**全部跳过**，此时
  `===== SUMMARY 0/N 通过，N 跳过 =====` 而 `rc=0`。
零个断言真正执行，门禁却报绿——与前两形态同族，危害相同。

旁证：`hive/verify_runner.py:161` 的 N9 门早就写了「rc=0 不等于『跑了』」并自补
`passed > 0` 门。**下游消费方早就防着，入口本身却没兜** ——本修复把门移到入口。

退出码契约（本仓既有语义，勿混用）：
  rc=0 真跑且无失败；rc=1 有失败；rc=2 零选中 / 被测件自身「有跳过」；rc=3 全跳过零执行。
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "scripts", "run_tests.py")

#: 用于构造「全部跳过」输入的确定性目标。
#:
#: 为什么不用某个「当前恰好会打印 SKIP」的测试文件：那是**外部行为耦合**——
#: 该文件哪天改成真跑或不再输出 SKIP，A 组就会静默失效（守卫变成永远不会红的
#: 摆设，正是本文件要防的那类病）。改用 `_SERIAL_ONLY` 里的目标：它在
#: `--jobs > 1` 时由 run_tests 自己按声明跳过，与第三方文件的行为无关。
#: 取两个目标是为了让断言对「单条/多条」都成立。
SERIAL_ONLY = ("bench_swarm_parallel", "bench_swarm_scale")
#: 常态会真跑且通过的目标（无外部依赖），用作「真跑」对照。
REAL = "test_check_relation_types"
#: 被 _heavy_reason 判定为「重质检」的目标（--gate fast 会把它移出 targets）。
#: 选它是为了构造「整批都被 fast 档移出」的第四形态输入。
HEAVY = "test_h4_sustain_snapshot"

_PASS, _FAIL = [], []


def ok(cond, msg, detail=""):
    (_PASS if cond else _FAIL).append(msg)
    print(("  PASS " if cond else "  FAIL ") + msg
          + (("  <- " + str(detail)) if detail and not cond else ""))


def _run(*argv, timeout=900, script=None):
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
    r = subprocess.run([sys.executable, "-X", "utf8", script or SCRIPT, *argv],
                       cwd=ROOT,
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", env=env, timeout=timeout)
    return (r.stdout or "") + (r.stderr or ""), r.returncode


def main(script=None):
    script = script or SCRIPT
    print("== A 全跳过：零执行必须非 0（这是本守卫的正题）")
    # 显式 --jobs 4：_SERIAL_ONLY 只在并行下跳过（负载敏感的性能阈值断言）。
    # 选择器由 SERIAL_ONLY 的公共前缀拼出，避免写死字面量与常量各说一套。
    _sel = "_".join(SERIAL_ONLY[0].split("_")[:2])       # bench_swarm
    out, rc = _run("-k", _sel, "--jobs", "4", script=script)
    ok(rc == 3, "A1 全部跳过 ⇒ rc=3（旧实现是 0，即沉默通过）", rc)
    ok("全部跳过" in out, "A2 明确打印「全部跳过」（可检索）", out[-300:])
    ok("无一真正执行" in out, "A3 说明零执行这一事实", out[-300:])
    ok("SUMMARY 0/" in out, "A4 汇总确实声称 0 通过（对照用，非判据）", out[-300:])
    # A5：确保「全跳过」输入的确定性来自 _SERIAL_ONLY 声明（而非某个测试文件
    # 恰好会打印 SKIP）。若哪天 run_tests 的 _SERIAL_ONLY 语义变了，这里先红。
    ok(len(SERIAL_ONLY) >= 1 and "0 跳过" not in out,
       "A5 跳过确实发生且被计入（不依赖第三方文件的 SKIP 行为）", out[-300:])

    print("== B 部分跳过但至少一条真跑：不得误伤（设计内 SKIP 是裸 clone 友好）")
    out2, rc2 = _run("-k", REAL, script=script)
    ok(rc2 == 0, "B1 真跑且通过 ⇒ rc=0", rc2)
    ok("SUMMARY 1/1" in out2, "B2 确实执行了 1 条", out2[-300:])
    ok("全部跳过" not in out2, "B3 不打印「全部跳过」", out2[-300:])

    # B4/B5 是关键补充（2026-11-08 变异 M2 暴露的盲区）：B1..B3 只选中 1 个目标、
    # 零跳过，**触发不到「既有跳过又有通过」**这一分支。而实现里若把条件写成
    # `if skipped or mod_skips:`（漏掉 `_passed == 0`），该分支就会把「2 通过 + 2 跳过」
    # 误判为全部跳过并返回 3 —— 而 B1..B3 依然全绿。故必须显式构造混合输入：
    # -k bench 选中多个 bench 目标，其中既有真跑的也有常态 SKIP 的。
    out2b, rc2b = _run("-k", "test_bench", script=script)
    ok(rc2b == 0, "B4 混合输入（部分通过 + 部分跳过）⇒ rc=0（不得误判为全跳过）", rc2b)
    ok("全部跳过" not in out2b,
       "B5 混合输入不得打印「全部跳过」（_passed>0 时该门必须让路）", out2b[-400:])

    # B6/B7：第四形态（2026-11-08 实测补）。`--gate fast` 会把重质检项移出 targets，
    # 但它们**原先进不了 skipped 集**：若整批都是重质检项，就得到「零执行 + 零跳过」，
    # 于是「全跳过」门的前提 `(skipped or mod_skips)` 为假、门被绕过（rc=0 沉默通过）。
    # 修法是把 _heavy_skipped 并入 skipped；此二条锁死该行为。
    out2c, rc2c = _run("--gate", "fast", "-k", HEAVY, script=script)
    ok(rc2c == 3, "B6 全被 --gate fast 移出 ⇒ rc=3（第四形态，同为零执行）", rc2c)
    ok("gate=fast" in out2c and "重质检" in out2c,
       "B7 报错信息点明是 fast 档移出（不误称「依赖缺失」）", out2c[-400:])

    print("== C 既有语义不被覆盖：零选中仍是 rc=2")
    out3, rc3 = _run("--module", "definitely.not.exist", script=script)
    ok(rc3 == 2, "C1 零选中 ⇒ rc=2（#1910 语义不变）", rc3)
    ok("无匹配目标" in out3, "C2 仍是「无匹配目标」措辞", out3[-300:])
    ok("全部跳过" not in out3, "C3 零选中不该误报为「全部跳过」（两者病因不同）", out3[-300:])

    print("== D --list 是查看语义：恒 rc=0")
    out4, rc4 = _run("--list", script=script)
    ok(rc4 == 0, "D1 --list ⇒ rc=0", rc4)
    ok("共 " in out4, "D2 打印目标总数", out4[-200:])

    # D3：--list 的「已发现 / 磁盘递归」诊断行**不得**受 -k 过滤影响。
    # 该行的语义是「收集面对不对得上磁盘」，与被看的目标无关。早先误用过滤后的
    # targets 计算，`--list -k bench_swarm` 会打出「已发现 0 个 / 磁盘递归 621 个」
    # ——一个永远不为真的差值，读者会误判成收集面坏了（2026-11-08 实测）。
    out4f, rc4f = _run("--list", "-k", "bench_swarm", script=script)
    ok(rc4f == 0, "D3 带 -k 的 --list ⇒ rc=0", rc4f)
    _m = [ln for ln in out4f.splitlines() if "已发现" in ln]
    ok(bool(_m), "D4 诊断行存在", out4f[-300:])
    if _m:
        import re as _re
        _g = _re.search(r"已发现\s+(\d+)\s+个\s*/\s*磁盘递归\s+(\d+)\s+个", _m[0])
        ok(bool(_g) and _g.group(1) == _g.group(2),
           "D5 过滤下两数仍相等（诊断行不受 -k 影响）", _m[0])
    else:
        ok(False, "D5 过滤下两数仍相等（诊断行不受 -k 影响）", "(无诊断行)")

    print("== E 判别力自证：旧实现（无全跳过门）对同一输入返回 0")
    # 旧实现的判据就是 `if bad: return 1` 否则 `return 0`——全跳过时 bad 为空 ⇒ 0。
    # 这里直接对源码做结构断言，证明「若无该门，rc 会是 0」这一路径确实存在。
    src = open(script, encoding="utf-8").read()
    ok("if _passed == 0 and (skipped or mod_skips):" in src,
       "E1 实现里有全跳过门（结构锚点）")
    ok("return 3" in src, "E2 该门返回 3（与 rc=2「有跳过」区分）")
    i_guard = src.find("if _passed == 0 and (skipped or mod_skips):")
    i_fail = src.find("if bad:")
    ok(0 < i_fail < i_guard,
       "E3 全跳过门在 `if bad:` **之后**（有失败时优先报失败，不被覆盖）",
       (i_fail, i_guard))

    print()
    print("全跳过假绿守卫：%d 通过 / %d 失败" % (len(_PASS), len(_FAIL)))
    if _FAIL:
        for f in _FAIL:
            print("  -", f)
    print("VERDICT=%s" % ("PASS" if not _FAIL else "FAIL"))
    return 0 if not _FAIL else 1


# ---- 定点变异（--mutate）：每臂都必须精确打红 ----
# 生效条件：argv 含 --mutate 时，对 scripts/run_tests.py 副本施加单个变异后重跑本守卫，
# 断言其转红且失败项落在预期组；不改动仓内真文件（在临时副本上做）。
def _mutations():
    return [
        ("M1 回缺陷：摘掉全跳过门（回到 rc=0 沉默通过）",
         "if _passed == 0 and (skipped or mod_skips):", "if False:"),
        ("M2 过度收紧：把部分跳过也判失败（_passed > 0 条件去掉）",
         "if _passed == 0 and (skipped or mod_skips):", "if skipped or mod_skips:"),
        ("M3 退出码混淆：改回 rc=2（与「有跳过」语义冲突）",
         "        return 3", "        return 2"),
        # M4 第四形态回归：把 _heavy_skipped 从统一跳过集里摘掉，于是「整批被
        # --gate fast 移出」时 skipped 为空 ⇒ 全跳过门的前提为假 ⇒ 又回到 rc=0。
        ("M4 回缺陷：fast 档移出的重质检项不进统一跳过集",
         "skipped, runnable = list(_heavy_skipped), []",
         "skipped, runnable = [], []"),
    ]


def _run_mutate():

    orig = open(SCRIPT, encoding="utf-8").read()
    results = []
    for label, old, new in _mutations():
        if old not in orig:
            print("  SKIP %s（锚点未命中，实现已漂移——请更新本守卫）" % label)
            results.append((label, None))
            continue
        mutated = orig.replace(old, new, 1)
        # 变异副本必须与真文件**同目录**（scripts/）：run_tests.py 以自身位置推出
        # _REPO（`os.path.dirname(dirname(abspath(__file__)))`）。放到仓根会让它算出
        # 上一层目录当仓库根，于是所有目标都「零选中」，守卫转红却与变异无关——
        # 那种变异验证是假的（2026-11-08 两次踩到：先误放临时目录致 ModuleNotFoundError，
        # 后误放仓根致零选中）。文件名以 `_mut_` 开头，天然不匹配 `test_*.py` 收集面。
        mut_name = "_mut_run_tests_allskip.py"
        mut_path = os.path.join(ROOT, "scripts", mut_name)
        try:
            with open(mut_path, "w", encoding="utf-8") as f:
                f.write(mutated)
            _PASS.clear()
            _FAIL.clear()
            rc = main(script=mut_path)
            red = (rc != 0)
            results.append((label, red))
            print("  %s %s（守卫 rc=%d）" % ("RED  " if red else "GREEN", label, rc))
        finally:
            try:
                os.remove(mut_path)
            except OSError:
                pass
    print()
    bad = [l for l, r in results if r is False]
    missing = [l for l, r in results if r is None]
    print("变异验证：%d 臂打红 / %d 臂未打红 / %d 臂锚点缺失"
          % (sum(1 for _, r in results if r), len(bad), len(missing)))
    print("VERDICT=%s" % ("PASS" if not bad and not missing else "FAIL"))
    return 0 if (not bad and not missing) else 1


if __name__ == "__main__":
    if "--mutate" in sys.argv:
        raise SystemExit(_run_mutate())
    raise SystemExit(main())
