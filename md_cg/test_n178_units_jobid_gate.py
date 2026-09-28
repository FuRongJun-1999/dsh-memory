# -*- coding: utf-8 -*-
"""md_cg · units 派发通道 job_id 结构闸守卫（N178，越池读写）

缺陷（修复前）：`md_cg/units.py` 把**调用方给的** job_id 直接 `os.path.join`
进池路径，全程无结构校验——
  · `poll(job_id, jobs)`（units.py:336）`d = os.path.join(jobs_dir(jobs), str(job_id or ""))`
    → `poll("../victim")`、`poll("<绝对路径>")` 都把 d 指到**池外**，随后
    `RESULT_FILE`（result.json）被正常读出、`content` 原样进返回值
    （:353-373）——越池读全文；`wait`（:386 循环 poll）与 `run` 同源继承。
  · `submit(...)`（:305-306）`jd, job_id = jobs_dir(jobs), _job_id()` 后
    `d = os.path.join(jd, job_id)` 直接 `os.makedirs(d)` + 落 spec.json/status.json
    ——job_id 来源一旦不是 `_job_id()`（同族 N145 池推导、外部派发器注入、
    未来新增 id 源），就是「任意目录 + 生成名」的建目录/写文件原语。
同族家法已有：`hive/hive_mcp/mcp_server.py:133-143 _valid_job_id`（`_t_poll`
:481、`_t_kill` :515 用）与 `hive/src/job.rs:63-67 valid_job_id`（同为
「单路径分量」结构闸，2026-09-25 缺陷）。units 是本缺口的**漏网面**。

修复：`units._valid_job_id`（单点结构闸，deny-by-default 字符白名单）+
三处接线——`poll` 入口拒（`state="invalid_job_id"` 结构化拒、content 恒 None）、
`wait` 入口拒（**不得进轮询循环**：否则非法 id 要空转满 timeout_s）、
`submit` 落盘前拒（makedirs 之前）。

口径说明（为何**不**照抄 hive 的 "h" 前缀）：`_valid_job_id` 家法要求
`startswith("h")`，而本模块对外的既有契约允许任意宿主派发器的 job 目录——
`md_cg/test_units_poll.py:47/53/57` 用的就是 "j_empty"/"j_good"/"j_fail"。
前缀收紧会误杀既有契约，故此处只保留「**不含路径成分**」的结构判据
（ASCII 字母/数字/_/-/.；首尾非点；拒 `/` `\\` `:` NUL 与首尾空白），
判别力等价于路径穿越防护，且 `_job_id()` 自身产物必过（下方 :[0] 自洽断言）。

守卫（五组，全部临时池 + 临时目录，**绝不碰在役 jobs 目录**）：
  ① 红转绿：池外造 `outside/result.json`（content="SECRET-OUTSIDE"）→
     `poll("../outside")` 修前**读到池外全文**（ok=True/content 泄漏）；
     修后结构化拒 `state="invalid_job_id"` 且 content 为 None；
  ② 绝对路径形态同拒（`os.path.join` 遇绝对路径会丢弃池前缀）；
  ③ 拒形态清单：`..` / 分隔符 / 盘符·ADS(`C:x`) / NUL / 空串 / 纯点 / 尾点 /
     空白 / 非 str，全拒且 content 恒 None；
  ④ `wait` 同闸且**立即返回**（不进轮询：无 timeout 键、无 waited_s）；
  ⑤ `submit` 落盘前拒：注入 `_job_id` 返回 "../escaped"（证明落点无闸）——
     修前在**池外**建出 `escaped/spec.json`；修后 ok=False 且该目录不存在；
     并验证合法 submit→poll 闭环不回归（状态 pending、终态 False）。

运行：python -m md_cg.test_n178_units_jobid_gate
"""
from __future__ import annotations

import gc
import json
import os
import shutil
import sys
import tempfile
import time

from . import units

PASS = FAIL = 0
FAILS = []

SECRET = "SECRET-OUTSIDE"           # 池外 result.json 的正文（泄漏探针）


def _clean(root):
    """尽力清理临时池：Windows 下句柄未释放会让 rmtree 静默失败，故重试并告警。"""
    for _ in range(4):
        shutil.rmtree(root, ignore_errors=True)
        if not os.path.exists(root):
            return
        gc.collect()
        time.sleep(0.2)
    print("  [warn] 临时目录未能清理（句柄占用？）：%s" % os.path.basename(root))


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}" + (f" · {detail}" if detail else ""))
    else:
        FAIL += 1
        FAILS.append(f"{name} · {detail}" if detail else name)
        print(f"  [FAIL] {name}" + (f" · {detail}" if detail else ""))


def _mk_job(root, job_id, payload):
    """在 root 下造一个终态 job 目录（result.json + status.json）。"""
    d = os.path.join(root, job_id)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "result.json"), "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    with open(os.path.join(d, "status.json"), "w", encoding="utf-8") as f:
        json.dump({"job_id": job_id, "state": "done", "model": "stub"}, f,
                  ensure_ascii=False)
    return d


def _leaked(r) -> bool:
    """结果是否带出池外正文（越池读成立的判据）。"""
    return SECRET in str(r.get("content") or "")


def main():
    print("=" * 68)
    print("md_cg units · job_id 结构闸（N178 越池读写）")
    print("=" * 68)
    tmp = tempfile.mkdtemp(prefix="mdcg_units_n178_")
    pool = os.path.join(tmp, "pool")
    outside = os.path.join(tmp, "outside")
    os.makedirs(pool, exist_ok=True)
    _mk_job(outside, "", {"ok": True, "content": SECRET})
    # 注：_mk_job(root=outside, job_id="") 落到 outside 本身（result.json 直接在池外根）
    vj = getattr(units, "_valid_job_id", None)

    try:
        # ---------- [0] 闸门自洽：合法形态必过（含既有测试契约） ----------
        print("\n[0] 闸门存在且合法形态必过（不误杀既有契约）")
        check("① _valid_job_id 已定义且可调用", callable(vj),
              f"got {vj!r}（修前无此闸）")
        for good in ("h1758000000000_1a2b", "j_empty", "j_good", "j_fail",
                     units._job_id()):
            check(f"① 合法 id 放行：{good!r}", callable(vj) and vj(good) is True,
                  f"got {vj(good) if callable(vj) else None!r}")

        # ---------- [1] 红转绿：相对穿越读池外 ----------
        print("\n[1] poll 相对穿越（../outside）")
        r1 = units.poll("../outside", jobs=pool)
        check("① 结构化拒（state=invalid_job_id）",
              r1.get("state") == "invalid_job_id", str(r1)[:140])
        check("① 池外正文未进返回值（修前 content=SECRET-OUTSIDE）",
              not _leaked(r1) and r1.get("content") is None,
              f"content={r1.get('content')!r}")
        check("① ok 为 False 且给出可归因 error",
              r1.get("ok") is False and "非法" in str(r1.get("error") or ""),
              str(r1.get("error"))[:120])
        check("① 池内对照：同名相对形态不误伤（pool/<合法名>）",
              units.poll("j_none", jobs=pool).get("state") == "missing",
              str(units.poll("j_none", jobs=pool))[:100])

        # ---------- [2] 绝对路径形态 ----------
        print("\n[2] poll 绝对路径（os.path.join 遇绝对路径丢弃池前缀）")
        r2 = units.poll(outside, jobs=pool)
        check("② 结构化拒且未泄漏", r2.get("state") == "invalid_job_id"
              and not _leaked(r2), str(r2)[:140])

        # ---------- [3] 拒形态清单 ----------
        print("\n[3] 拒形态清单（均须结构化拒且 content 恒 None）")
        bad_ids = ["..", "../outside", r"..\outside", "a/b", "a\\b", "C:x", "h:x",
                   "a\x00b", "", ".", "...", "x.", "x..", " x", "x ", "   ",
                   "h/../../x", "h/."]
        for bad in bad_ids:
            r = units.poll(bad, jobs=pool)
            check(f"③ 拒 {bad!r}",
                  r.get("state") == "invalid_job_id" and r.get("content") is None,
                  f"state={r.get('state')!r} content={r.get('content')!r}")
        for bad_ns in (123, None, 1.5, ["a"], {"a": 1}):
            r = units.poll(bad_ns, jobs=pool)
            check(f"③ 拒非 str {bad_ns!r}",
                  r.get("state") == "invalid_job_id" and r.get("content") is None,
                  f"state={r.get('state')!r}")

        # ---------- [4] wait 同闸且不进轮询 ----------
        print("\n[4] wait 入口同闸（fail-fast，不空转 timeout_s）")
        r4 = units.wait("../outside", jobs=pool, timeout_s=0.3, poll_s=0.05)
        check("④ 结构化拒且未泄漏", r4.get("state") == "invalid_job_id"
              and not _leaked(r4), str(r4)[:140])
        check("④ 未进轮询循环（无 timeout 键 / 无 waited_s）",
              "timeout" not in r4 and r4.get("waited_s") is None, str(r4)[:140])

        # ---------- [5] submit 落盘前拒 ----------
        print("\n[5] submit 落盘前拒（注入生成器证明落点无闸）")
        escaped = os.path.join(tmp, "escaped")
        orig_gen = units._job_id
        units._job_id = lambda: "../escaped"          # 模拟非生成器的 id 来源
        try:
            r5 = units.submit(prompt="探针", role=units.REFLECT,
                              model="stub-model", jobs=pool)
        finally:
            units._job_id = orig_gen
        check("⑤ 池外未建出 escaped/spec.json（修前会被建出）",
              not os.path.isfile(os.path.join(escaped, "spec.json")),
              f"ok={r5.get('ok')!r} spec存在={os.path.isfile(os.path.join(escaped, 'spec.json'))}")
        check("⑤ 绿：submit 结构化拒",
              r5.get("ok") is False and "非法" in str(r5.get("error") or ""),
              str(r5.get("error"))[:120])

        print("\n[5b] 合法 submit → poll 闭环不回归")
        sub = units.submit(prompt="探针", role=units.REFLECT, model="stub-model",
                           jobs=pool)
        check("⑤ 合法 submit 仍可用（ok=True 且 id 过闸）",
              sub.get("ok") is True and callable(vj) and vj(sub.get("job_id")) is True,
              str(sub)[:140])
        check("⑤ job 目录落在池内",
              str(sub.get("job_dir") or "").startswith(os.path.abspath(pool)),
              str(sub.get("job_dir")))
        p = units.poll(sub.get("job_id"), jobs=pool)
        check("⑤ 合法 poll 读到 pending（不误伤正常路径）",
              p.get("state") == "pending" and p.get("terminal") is False,
              f"state={p.get('state')!r} terminal={p.get('terminal')!r}")
    finally:
        _clean(tmp)

    print("\n" + "=" * 68)
    print(f"PASS={PASS}  FAIL={FAIL}")
    if FAILS:
        print("失败项：" + "；".join(FAILS))
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
