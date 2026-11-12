# -*- coding: utf-8 -*-
r"""hive/test_issue158_scoreboard_settle.py —— #158 守卫（结算须看完成状态 ＋ 坏件不计分 ＋ 落盘 append-only）。

# 功能名：#158 守卫——scoreboard 结算的完成度口径 / 坏件不计分 / 落盘 append-only
# 生效条件：凡改 hive/scoreboard.py 的 score()/scan()/main(--write) 三处时；触发语=#158、scoreboard 结算、坏件计分、append-only。
# 子功能：A1 结算看完成状态（正相关：成功 > 失败后重投成功 > 全失败）／A2 坏件只进 bad_ids 不计分／A3 --write 为 append-only
# 执行：python -X utf8 hive/test_issue158_scoreboard_settle.py ｜ --mutate 自证（源码级短路 ⇒ 恰好转红）
# 验证方式：A1~A3 断言 ＋ 3 条源码级定点变异（e 改回常量／坏件继续计分／落盘改覆写）
# 不适用条件：情感交互｜闲聊｜纯查询无改动；不覆盖对外域结算（走 dsh-bounty 账本）。
"""
from __future__ import annotations

import io
import json
import os
import shutil
import sys
import tempfile
import types

SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scoreboard.py")
PASS = 0
FAIL = 0


def ok(cond, label, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
    print("  [%s] %s%s" % ("PASS" if cond else "FAIL", label, ("  · " + str(detail)) if detail else ""))
    return bool(cond)


def _load(src_text):
    mod = types.ModuleType("sb158")
    mod.__file__ = SRC
    exec(compile(src_text, "<sb158>", "exec"), mod.__dict__)
    return mod


def _fixture(sb):
    root = tempfile.mkdtemp(prefix="iss158_")
    J = os.path.join(root, "jobs")
    os.makedirs(J, exist_ok=True)

    def W(p, o):
        with io.open(p, "w", encoding="utf-8") as f:
            json.dump(o, f, ensure_ascii=False)

    def job(jid, state, result=None, bad=False):
        d = os.path.join(J, jid)
        os.makedirs(d, exist_ok=True)
        W(os.path.join(d, "spec.json"), {})
        if bad:
            with io.open(os.path.join(d, "status.json"), "w", encoding="utf-8") as f:
                f.write("{ 坏件 ")
        else:
            W(os.path.join(d, "status.json"), {"job_id": jid, "state": state})
        W(os.path.join(d, "result.json"), result or {})

    job("h_B端_T5_验证单元_0001", "error")                      # 全失败
    job("h_B端_T6_验证单元_0001", "error")                      # 失败后重投成功
    job("h_B端_T6_验证单元_0002", "done", {"ok": True, "content": "ok"})
    job("h_B端_T7_验证单元_0001", "done", {"ok": True, "content": "ok"})  # 单次成功
    job("h_B端_T8_输出单元_0001", "", bad=True)                 # 坏件
    return root, J


def run_checks(sb):
    root, J = _fixture(sb)
    try:
        doc = sb.build(J)
        bu = {(r["identity"], r["task"], r["unit"]): r for r in doc["by_unit"]}
        d_fail = bu[("B端", "T5", "验证单元")]["delta"]
        d_retry = bu[("B端", "T6", "验证单元")]["delta"]
        d_ok = bu[("B端", "T7", "验证单元")]["delta"]
        e_retry = bu[("B端", "T6", "验证单元")]["e"]
        print("    读数：单次成功 Δ=%d ｜ 失败后重投成功 Δ=%d（e=%.2f）｜ 全失败 Δ=%d" % (d_ok, d_retry, e_retry, d_fail))
        ok(bu[("B端", "T7", "验证单元")]["e_measured"] is True
           and abs(bu[("B端", "T7", "验证单元")]["e"] - 1.0) < 1e-9
           and abs(e_retry - 0.5) < 1e-9 and d_fail == 1,
           "A1 结算看完成状态：e 为实测（成功 1.0／失败后重投 0.5／全失败保底 1）",
           (d_ok, d_retry, d_fail, e_retry))
        ok(d_ok > d_retry > d_fail,
           "A1b 正相关：成功 > 失败后重投成功 > 全失败（修前是 12 > 6 = 12 的反向）",
           (d_ok, d_retry, d_fail))
        ok(doc["bad_ids"] == ["h_B端_T8_输出单元_0001"]
           and ("B端", "T8", "输出单元") not in bu
           and doc["totals"]["jobs"] == 4,
           "A2 坏件只进 bad_ids、不计分（修前既进 bad_ids 又拿 Δ）",
           (doc["bad_ids"], doc["totals"]["jobs"], sorted(k[1] for k in bu)))
        p = os.path.join(J, "_scoreboard.jsonl")
        import contextlib
        for _ in range(2):
            with contextlib.redirect_stdout(io.StringIO()):
                sb.main(["--jobs", J, "--write"])
        n = len(io.open(p, encoding="utf-8").read().splitlines()) if os.path.isfile(p) else -1
        ok(n == 2, "A3 --write 为 append-only（跑两次 ⇒ jsonl 追加 2 行）", n)
    finally:
        shutil.rmtree(root, ignore_errors=True)


_MUT = (
    ("M1 e 改回常量 1.0（修前形态）",
     "        e = (float(done) / n) if n else 0.0",
     "        e = 1.0  # MUT", "A1"),
    ("M2 坏件继续计分（摘掉 continue）",
     "            bad.append(name)\n            continue",
     "            bad.append(name)  # MUT", "A2"),
    ("M3 落盘改覆写（\"a\" → \"w\"）",
     '        with io.open(p, "a", encoding="utf-8", newline="\\n") as fh:',
     '        with io.open(p, "w", encoding="utf-8", newline="\\n") as fh:  # MUT', "A3"),
)


def _run_and_count(src_text):
    """跑一次断言并返回 (pass, fail, 输出文本)。"""
    global PASS, FAIL
    PASS, FAIL = 0, 0
    buf = io.StringIO()
    import contextlib
    with contextlib.redirect_stdout(buf):
        run_checks(_load(src_text))
    return PASS, FAIL, buf.getvalue()


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    src = io.open(SRC, encoding="utf-8").read()
    print("== 正常实现 ==")
    p0, f0, out0 = _run_and_count(src)
    print(out0.rstrip())
    bad = 0
    if "--mutate" in argv:
        print()
        print("!! 定点变异自证：源码级短路一条判据 ⇒ 对应断言必须恰好转红")
        for name, old, new, expect in _MUT:
            if src.count(old) != 1:
                print("  [FAIL] %s：锚点命中 %d 次（期望 1）" % (name, src.count(old)))
                bad += 1
                continue
            pm, fm, om = _run_and_count(src.replace(old, new))
            reds = [ln.strip() for ln in om.splitlines() if "[FAIL]" in ln]
            good = (fm >= 1)
            print("  [%s] %s：红项 %d（期望命中 %s）" % ("PASS" if good else "FAIL", name, fm, expect))
            for ln in reds:
                print("        %s" % ln)
            bad += 0 if good else 1
    print()
    print("通过 %d / 失败 %d" % (p0, f0))
    return 1 if (f0 or bad) else 0


if __name__ == "__main__":
    sys.exit(main())