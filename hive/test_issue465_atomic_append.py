# -*- coding: utf-8 -*-
# 功能名：hive 台账跨进程原子追加单点（issue #465）——三处 open("a") 并发丢行/撕裂收口
# 生效条件：python -X utf8 -m hive.test_issue465_atomic_append [--mutate]；
#           被测面＝hive/atomic_append.py::append_line 与三处接线
#           （scoreboard._scoreboard.jsonl / orch._adjudication.jsonl / exec_cmd.log.txt）
# 子功能：U 组＝单点基本语义；C 组＝8 worker × 400 行并发完整性与无撕裂；
#         B 组＝三落点单进程行为；E 组＝接线与单点源码钉子
# 执行：--mutate 时就地短路一条判据（单点改无锁 read-modify-write / 三处接线各回裸 open），
#       指定断言须恰好转红
# 不适用条件：不判 seq + 尾部校验（issue #465 修复建议第二段，另案）；不判 Rust 侧写者
"""issue #465 守卫：hive 台账多 worker 并发 append 丢行 + 撕裂。

病象（修前）：三处权威台账都用 open("a") 逐条写、无跨进程锁。Windows CRT 的
O_APPEND 是 lseek(END)+write 两步（非原子），8 worker 各 400 行实测丢 221–279 行
并留下半截 JSON 行；单 worker / bulk 一次写完整。「可审计可回放」实为静默丢记录。

修复语义：新增 hive/atomic_append.append_line 判据单点——FileLock(path, strict=True)
池级互斥 + O_APPEND 单次 os.write（短写抛错）；三处台账改走该单点，失败语义按各面
性质保留（权威台账上抛 / 观测面降级 stderr）。本件只解决并发丢行与撕裂，不含 seq。
"""
from __future__ import annotations

import ast
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
_SELF = os.path.abspath(__file__)
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

try:
    from hive.atomic_append import append_line as _append_line
except Exception:                                    # noqa: BLE001
    _append_line = None
from hive import exec_cmd as exc
from hive import orch, scoreboard

_CHECKS = []
FAILS = []


def _check(name, cond, detail=""):
    if name not in _CHECKS:
        _CHECKS.append(name)
    if cond:
        print("  PASS " + name)
    else:
        print("  FAIL " + name + "  " + str(detail)[:200])
        FAILS.append(name)


def _concurrent_write(path, workers=8, per=400):
    procs = []
    for w in range(workers):
        code = (
            "import sys; sys.path.insert(0, %r)\n"
            "from hive.atomic_append import append_line\n"
            "import json\n"
            "for i in range(%d): append_line(%r, json.dumps({'w': %d, 'i': i}))\n"
            % (_REPO, per, path, w))
        procs.append(subprocess.Popen(
            [sys.executable, "-X", "utf8", "-c", code], cwd=_REPO,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE))
    rcs, errs = [], []
    for pr in procs:
        out, err = pr.communicate(timeout=600)
        rcs.append(pr.returncode)
        if pr.returncode != 0:
            errs.append((out or b"").decode("utf-8", "replace")[-120:] + " | "
                        + (err or b"").decode("utf-8", "replace")[-120:])
    if errs:
        print("  [worker-errors]", errs[:2])
    return rcs


def _assertions():
    print("== U 组：append_line 单点基本语义 ==")
    tmp = tempfile.mkdtemp(prefix="iss465_")
    try:
        p = os.path.join(tmp, "sub", "a.jsonl")
        if _append_line is None:
            _check("U01 单点存在且可写单行（基线/误删即红）", False,
                   "hive.atomic_append.append_line 不存在")
            _check("U02 建父目录 + 末尾换行补足", False, "同上")
        else:
            _append_line(p, "hello")
            _append_line(p, "world\n")
            with io.open(p, encoding="utf-8") as fh:
                got = fh.read()
            _check("U01 单点存在且可写单行", os.path.isfile(p), p)
            _check("U02 建父目录 + 末尾换行恰好一次", got == "hello\nworld\n", repr(got))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("== C 组：8 worker × 400 行并发（期望 3200 行完整、无撕裂） ==")
    tmp2 = tempfile.mkdtemp(prefix="iss465_c_")
    try:
        cp = os.path.join(tmp2, "ledger.jsonl")
        if _append_line is None:
            _check("C01 并发后总行数 = 3200", False, "append_line 不存在")
            _check("C02 每行 JSON 可解析且 (w,i) 集合完整", False, "append_line 不存在")
        else:
            rc = _concurrent_write(cp, workers=8, per=400)
            lines = []
            if os.path.exists(cp):
                with io.open(cp, encoding="utf-8", errors="replace") as fh:
                    lines = [x for x in fh.read().split("\n") if x != ""]
            bad = []
            seen = set()
            for ln in lines:
                try:
                    r = json.loads(ln)
                    seen.add((r.get("w"), r.get("i")))
                except Exception:                     # noqa: BLE001
                    bad.append(ln[:40])
            need = {(w, i) for w in range(8) for i in range(400)}
            _check("C01 并发后总行数 = 3200（无丢行）", len(lines) == 3200,
                   (len(lines), rc))
            _check("C02 每行 JSON 可解析且 (w,i) 集合完整（无撕裂/无缺）",
                   not bad and seen == need,
                   (bad[:2], len(seen), len(need)))
    finally:
        shutil.rmtree(tmp2, ignore_errors=True)

    print("== B 组：三落点单进程行为 ==")
    tmp3 = tempfile.mkdtemp(prefix="iss465_b_")
    try:
        exc._log(tmp3, "hello465")
        with io.open(os.path.join(tmp3, "log.txt"), encoding="utf-8") as fh:
            log_txt = fh.read()
        _check("B01 exec_cmd._log 写入 log.txt", "hello465" in log_txt, repr(log_txt))
        jobs = os.path.join(tmp3, "jobs")
        os.makedirs(jobs, exist_ok=True)
        scoreboard.main(["--jobs", jobs, "--write"])
        sp = os.path.join(jobs, "_scoreboard.jsonl")
        ok_score = False
        try:
            with io.open(sp, encoding="utf-8") as fh:
                row = json.loads(fh.read().strip().split("\n")[-1])
                ok_score = isinstance(row.get("totals"), dict)
        except Exception:                             # noqa: BLE001
            pass
        _check("B02 scoreboard --write 落 _scoreboard.jsonl（末行 JSON）", ok_score, sp)
        old_dir = orch._CFG.get("job_dir")
        orch._CFG["job_dir"] = tmp3
        try:
            r = orch._record_adjudication({
                "kind": "confirm", "subject": "j_sub",
                "evidence": ["j_ev"], "verdict_note": "issue465 守卫"})
        finally:
            orch._CFG["job_dir"] = old_dir
        ap = os.path.join(tmp3, orch._ADJ_FILE)
        ok_adj = False
        try:
            with io.open(ap, encoding="utf-8") as fh:
                rec = json.loads(fh.read().strip().split("\n")[-1])
                ok_adj = rec.get("kind") == "confirm" and rec.get("subject") == "j_sub"
        except Exception:                             # noqa: BLE001
            pass
        _check("B03 orch._record_adjudication 落 _adjudication.jsonl（JSON 行）",
               bool(r.get("ok")) and ok_adj, (r, ap))
    finally:
        shutil.rmtree(tmp3, ignore_errors=True)

    print("== E 组：接线与单点源码钉子 ==")
    def _read(rel):
        try:
            with io.open(os.path.join(_REPO, rel), encoding="utf-8") as fh:
                return fh.read()
        except OSError:
            return ""

    atom_src = _read("hive/atomic_append.py")
    sc_src = _read("hive/scoreboard.py")
    orch_src = _read("hive/orch.py")
    exc_src = _read("hive/exec_cmd.py")
    _check("E01 ★钉子：三处落点均调用 append_line 单点",
           "append_line(p, json.dumps(doc" in sc_src
           and "append_line(path, json.dumps(rec" in orch_src
           and "append_line(os.path.join(job_dir, \"log.txt\")" in exc_src,
           (sc_src.count("append_line("), orch_src.count("append_line("),
            exc_src.count("append_line(")))
    _check("E02 ★钉子：三处裸 open(\"a\") 写台账均已撤除",
           'io.open(p, "a"' not in sc_src
           and 'open(path, "a", encoding="utf-8") as f' not in orch_src
           and 'open(os.path.join(job_dir, "log.txt"), "a"' not in exc_src)
    _check("E03 ★钉子：单点用 FileLock(strict=True) + O_APPEND 单次 write",
           "FileLock(path" in atom_src and "strict=True" in atom_src
           and "O_APPEND" in atom_src and "os.write(fd, data)" in atom_src)


def _run_assertions():
    global FAILS
    FAILS = []
    del _CHECKS[:]
    _assertions()
    print("通过 %d / 失败 %d" % (len(_CHECKS) - len(FAILS), len(FAILS)))
    return len(FAILS)


def _subprocess_fail_names():
    r = subprocess.run([sys.executable, "-X", "utf8", _SELF, "--assert-only"],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", cwd=_REPO, timeout=900)
    names = set(re.findall(r"(?m)^\s*FAIL\s+([A-Z]\d+)", r.stdout or ""))
    return names, (r.stdout or "") + (r.stderr or "")


_LOCK_BODY = chr(10).join([
    "    with FileLock(path, timeout=lock_timeout, strict=True):",
    "        fd = os.open(path, os.O_CREAT | os.O_WRONLY | os.O_APPEND, 0o600)",
    "        try:",
    "            n = os.write(fd, data)",
    "            if n != len(data):",
    "                raise OSError(",
    "                    \"短写：%d/%d 字节（不静默接受半行，issue #465）\"",
    "                    % (n, len(data)))",
    "        finally:",
    "            os.close(fd)",
])
_ARMS = {
    "M1": (
        "hive/atomic_append.py",
        _LOCK_BODY,
        chr(10).join([
            "    # mutation M1：无锁 read-modify-write（缺陷原形；并发必然丢行）",
            "    try:",
            "        with open(path, \"rb\") as fh:",
            "            _old = fh.read()",
            "    except OSError:",
            "        _old = b\"\"",
            "    with open(path, \"wb\") as fh:",
            "        fh.write(_old + data)",
            "",
        ]),
        {"C01", "C02", "E03"},
    ),
    "M2": (
        "hive/scoreboard.py",
        "        append_line(p, json.dumps(doc, ensure_ascii=False, sort_keys=True))",
        "        with io.open(p, \"a\", encoding=\"utf-8\", newline=\"\\n\") as fh:\n"
        "            fh.write(json.dumps(doc, ensure_ascii=False, sort_keys=True) + \"\\n\")",
        {"E01", "E02"},
    ),
    "M3": (
        "hive/orch.py",
        "        append_line(path, json.dumps(rec, ensure_ascii=False))",
        "        with open(path, \"a\", encoding=\"utf-8\") as f:\n"
        "            f.write(json.dumps(rec, ensure_ascii=False) + \"\\n\")",
        {"E01", "E02"},
    ),
    "M4": (
        "hive/exec_cmd.py",
        "        append_line(os.path.join(job_dir, \"log.txt\"), line.rstrip(\"\\n\"))",
        "        with open(os.path.join(job_dir, \"log.txt\"), \"a\", encoding=\"utf-8\") as f:\n"
        "            f.write(line)",
        {"E01", "E02"},
    ),
}


def _mutate(argv):
    want = ""
    for a in argv:
        if a == "--mutate":
            want = want or "ALL"
        elif a.startswith("--mutate="):
            want = a.split("=", 1)[1]
    if not want:
        return 0
    ids = sorted(_ARMS) if want == "ALL" else [want]
    red = 0
    for mid in ids:
        if mid not in _ARMS:
            print("[ANCHOR-MISS] %s：未登记该变异臂" % mid)
            return 2
        rel, old, new, expect = _ARMS[mid]
        target = os.path.join(_REPO, *rel.split("/"))
        with open(target, "rb") as fh:
            orig = fh.read()
        try:
            text = orig.decode("utf-8")
            nl = "\r\n" if "\r\n" in text else "\n"
            norm = text.replace("\r\n", "\n")
            _cnt = norm.count(old)
            if _cnt != 1:
                print("[ANCHOR-MISS] %s：锚点命中 %d 次（期望 1）⇒ 无法变异，判据失效"
                      % (mid, _cnt))
                return 2
            with open(target, "wb") as fh:
                fh.write(norm.replace(old, new).replace("\n", nl).encode("utf-8"))
            actual, out = _subprocess_fail_names()
            if actual == expect:
                print("[MUTATE-OK]   %s：指定断言转红 %s" % (mid, sorted(actual)))
            else:
                print("[MUTATE-FAIL] %s：期望红 %s，实际红 %s"
                      % (mid, sorted(expect), sorted(actual)))
                for line in out.splitlines():
                    if line.strip().startswith("FAIL"):
                        print("    " + line)
                red += 1
        finally:
            with open(target, "wb") as fh:
                fh.write(orig)
    print("反证结果：%d 条变异，%s" % (len(ids), "全部恰好命中" if red == 0 else "%d 条未命中" % red))
    return 1 if red else 0


if __name__ == "__main__":
    _f = _run_assertions()
    if "--assert-only" in sys.argv:
        sys.exit(1 if _f else 0)
    _m = _mutate(sys.argv[1:])
    sys.exit(1 if (_f or _m) else 0)
