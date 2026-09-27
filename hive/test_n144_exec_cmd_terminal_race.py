# -*- coding: utf-8 -*-
"""N144 守卫（第 23 轮，2026-09-28）：exec_cmd 确定性分支终态写竞态——
固定共享 tmp + 裸 replace + _fail 无成功终态回看（v10 N82 两件套欠账）。

病灶（hive/exec_cmd.py:40-62 / :269-272，本轮 HEAD 读核在位；git log 末触
批次 53 be88744c，exec.py 同族 N82 件 1d022a6b 批次 47 只落 exec.py——欠账
实证）：_write_result 用固定共享临时名 p+".tmp"+裸 os.replace 无重试；
_fail 直写 {"ok": false} 无成功终态回看。同仓 exec.py:104-156/:171-191 的
N82 三件套一件未移植。攻击面无需攻击者：rust 重投/N92 孤儿+recover_orphans
并存或双 serve 抢同池 → 同一 job_dir 被两个执行器并发写——共享 tmp 撞车
PermissionError 外逃进 main 顶层兜底(:269-272)，兜底再调 _fail 用同一坏
路径可再抛（任务无终态）；或对撞写者已落地的成功终态被 _fail 覆写为
ok=False（成功被记死，数据丢失面）。

红守卫（临时 job 目录 + 真实 exec_cmd 代码路径；T2 为真子进程）：
  T1 共享 tmp 被对撞者持握 → 旧 _write_result 裸 replace 必抛
     PermissionError 外逃（确定性红）；修后 mkstemp 唯一名照常落地且
     自有 .tmp 零残留；
  T1b 成功终态拒覆写：预置 {ok:true,PRE-SUCCESS-TERMINAL} 后 _fail——
     旧代码覆写为 ok=False（红）；修后拒写留痕、成功终态在位、退出码
     照实；error→error 更新不受限（零闸变对照）；
  T1c main 兜底二次抛出：run_cmd 注入异常 + 共享 tmp 被持握 → 旧 main
     兜底 _fail 再抛 PermissionError 外逃（无终态，红）；修后 main 正常
     返回 EXIT_EXEC 且 result.json 落地 ok=False；
  T2 跨进程真并发写同一 job_dir（双子进程 × 轮次 × 大 payload，对应
     缺陷报告 t1_concurrent.py 口径）：旧代码两写者 PermissionError/
     FileNotFoundError 成批外逃（红）；修后零外逃零 .tmp 残留。
运行：python -X utf8 hive/test_n144_exec_cmd_terminal_race.py
"""
from __future__ import annotations

import glob
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import exec_cmd  # noqa: E402

PY = sys.executable
fails = []


def check(name, cond, detail=""):
    print(f"{'PASS' if cond else 'FAIL'} {name}" + (f"  {detail}" if detail else ""))
    if not cond:
        fails.append(name)


def _jd(tmp, name):
    d = os.path.join(tmp, name)
    os.makedirs(d, exist_ok=True)
    return d


def _read_result(d):
    p = os.path.join(d, "result.json")
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def main():
    tmp = tempfile.mkdtemp(prefix="hive_n144_")
    try:
        # ---------- T1 共享 tmp 被持握（确定性红） ----------
        print("== T1 共享 tmp 被对撞者持握 → _write_result 不得外逃 ==")
        d1 = _jd(tmp, "t1")
        hold = open(os.path.join(d1, "result.json.tmp"), "w")  # 对撞者持握共享 tmp
        esc = None
        try:
            exec_cmd._write_result(d1, {"ok": True, "note": "writer"})
        except PermissionError as e:
            esc = e
        finally:
            hold.close()
        check("T1 共享 tmp 被持握时 _write_result 不外逃（mkstemp 唯一名）",
              esc is None, f"esc={esc!r}")
        check("T1a result.json 落地且内容正确",
              os.path.exists(os.path.join(d1, "result.json"))
              and _read_result(d1).get("note") == "writer")
        check("T1b 自有 .tmp 零残留",
              not glob.glob(os.path.join(d1, "result.json.*.tmp")))

        # ---------- T1b 成功终态拒覆写 ----------
        print("== T1b 成功终态拒覆写：_fail 不得把 ok=true 改写成 error ==")
        d2 = _jd(tmp, "t1b")
        with open(os.path.join(d2, "result.json"), "w", encoding="utf-8") as f:
            json.dump({"ok": True, "note": "PRE-SUCCESS-TERMINAL",
                       "model": "cmd"}, f)
        rc = exec_cmd._fail(d2, "对撞兜底失败")
        got = _read_result(d2)
        check("T1b-1 退出码照实返回（EXIT_SPEC）", rc == exec_cmd.EXIT_SPEC,
              f"rc={rc}")
        check("T1b-2 成功终态不被覆写（PRE-SUCCESS-TERMINAL 在位）",
              got.get("ok") is True and got.get("note") == "PRE-SUCCESS-TERMINAL",
              f"ok={got.get('ok')} note={got.get('note')!r}")
        log2 = os.path.join(d2, "log.txt")
        check("T1b-3 拒写留痕（log.txt 诚实记录）",
              os.path.exists(log2) and "拒" in open(log2, encoding="utf-8").read())
        # error→error 更新不受限（零闸变对照）
        d2b = _jd(tmp, "t1b_err")
        with open(os.path.join(d2b, "result.json"), "w", encoding="utf-8") as f:
            json.dump({"ok": False, "error": "旧 error", "model": "cmd"}, f)
        exec_cmd._fail(d2b, "新 error")
        got2 = _read_result(d2b)
        check("T1b-4 error→error 更新不受限（零闸变）",
              got2.get("ok") is False and got2.get("error") == "新 error",
              f"got={got2}")

        # ---------- T1c main 兜底二次抛出（确定性红） ----------
        print("== T1c main 兜底二次抛出：兜底 _fail 不得再外逃 ==")
        d3 = _jd(tmp, "t1c")
        hold3 = open(os.path.join(d3, "result.json.tmp"), "w")
        real_run = exec_cmd.run_cmd
        exec_cmd.run_cmd = lambda jd: (_ for _ in ()).throw(
            RuntimeError("注入内部异常"))
        old_argv = sys.argv
        sys.argv = ["exec_cmd.py", d3]
        esc3 = None
        rc3 = None
        try:
            rc3 = exec_cmd.main()
        except PermissionError as e:
            esc3 = e
        finally:
            sys.argv = old_argv
            exec_cmd.run_cmd = real_run
            hold3.close()
        check("T1c main 兜底不再二次抛出且终态落地（EXIT_EXEC + ok=False）",
              esc3 is None and rc3 == exec_cmd.EXIT_EXEC
              and _read_result(d3).get("ok") is False,
              f"esc={esc3!r} rc={rc3}")

        # ---------- T2 跨进程真并发写同一 job_dir ----------
        print("== T2 跨进程真并发：双子进程各 N 轮写同一 job_dir ==")
        d4 = _jd(tmp, "t2")
        worker = os.path.join(tmp, "_t2_worker.py")
        with open(worker, "w", encoding="utf-8") as f:
            f.write(
                "import json, os, sys\n"
                "sys.path.insert(0, %r)\n" % HERE +
                "import exec_cmd\n"
                "d, rounds, size = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])\n"
                "fails = 0\n"
                "for i in range(rounds):\n"
                "    try:\n"
                "        exec_cmd._write_result(d, {'ok': True, 'i': i,\n"
                "                                  'pad': 'x' * size})\n"
                "    except OSError as e:\n"
                "        fails += 1\n"
                "print(fails)\n")
        rounds, size = 20, 256 * 1024
        env = dict(os.environ, PYTHONUTF8="1")
        procs = [subprocess.Popen(
            [PY, "-X", "utf8", worker, d4, str(rounds), str(size)],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env)
            for _ in range(2)]
        outs = [p.communicate(timeout=120)[0].decode("utf-8", "replace").strip()
                for p in procs]
        total_fails = 0
        for o in outs:
            try:
                total_fails += int(o.splitlines()[-1])
            except (ValueError, IndexError):
                total_fails += 999       # worker 崩溃 = 更红
        check(f"T2 双进程 × {rounds} 轮零写失败外逃（合计外逃 {total_fails}）",
              total_fails == 0, f"worker 输出={outs}")
        check("T2b 终态文件可解析且零 .tmp 残留",
              isinstance(_read_result(d4), dict)
              and not glob.glob(os.path.join(d4, "*.tmp")))
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)

    print("\nRESULT:", "ALL_PASS" if not fails else f"FAILED={fails}")
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
