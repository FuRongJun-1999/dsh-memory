# -*- coding: utf-8 -*-
"""md_cg · 令牌库并发写守卫（N199，多进程共用一个令牌库：无锁读-改-写 + 固定共享临时名）

缺陷（修复前，本守卫红态实跑）：
  · `md_cg/tokens.py:343`（`_save`）`tmp = p + ".tmp"` —— **固定共享临时名**；
    :346 `publish(tmp, p)`（`fsutil._publish` **只重试 PermissionError**，
    FileNotFoundError 直逃）。两个写者共享同一临时文件时：一个在被 rename 前
    它的 tmp 已被另一个消费掉 → `FileNotFoundError`；或第二个截断第一个正在
    写的内容 → 半截/损坏 JSON（`fsutil.py:6-8` 模块 docstring 正把固定临时名
    列为头号反模式）。`_write_secret`（:666 起）同款。
  · `issue`（:420-423）/ `derive`（:517→:557）/ `revoke`（:605-610）都是
    「`_load` → 改内存 → `_save` 整份写回」，**全程无跨进程锁**——
    写者互不见彼此快照，后写者按自己的陈旧快照整份写回即无痕抹除前者刚落的
    记录（**静默丢凭据**：调用方拿到明文令牌，盘上却没有它的记录，此后
    verify 一律「令牌不存在」）。
  · 叠加本批 N198 的 `_save` 写前对账 fail-closed 后：固定名竞态还可把主令牌
    库撕成不可解析 → 此后每次写都抛 TokenError（**永久不可写、全库令牌失效**）。

  `grep -n "FileLock\\|mkstemp\\|atomic_write" md_cg/tokens.py` → 修复前 0 命中。
  同族 N184 已在位：`crypto._save_keys` / `provision_dek` 用
  `FileLock(keys_path(root), strict=True)` + 写前合并（批次 65）。

修复（与 N184 同口径）：
  ① 三条写路径（issue/derive/revoke）在**同一把** `FileLock(token_file(path),
     strict=True)` 临界区内完成「读快照 → 改 → 整份写回」（revoke 的级联
     递归在同一次持锁内完成——`_revoke_locked` 复用临界区，递归里再取锁会
     自锁）；锁超时转 TokenError fail-closed，绝不无锁放行整份写回。
     derive 另在临界区内复核父令牌**落盘态**（revoked_at）——并发 revoke 的
     级联只覆盖它落锁那一刻已存在的子令牌，无此复核会产出「父已吊销、子
     仍有效」的凭据（同族第二面，组 ③ 的 3d/3d2 腿钉住）。
  ② `_save` 落盘改走 `fsutil.atomic_write`（同目录 `mkstemp` **唯一**临时名 +
     带 Windows 重试的 replace）——固定共享临时名从两个点位消失；`_write_secret`
     同改。
  ③ `_save` 加写前合并（防线纵深，镜像 crypto）：盘面已有而本次快照没有的
     令牌记录逐条并入（陈旧快照整份写回不得抹除并发新增；键同在时以本次为准
     ——revoke 的 revoked_at / 派生的夹紧语义不受影响），并对 `tokens` 非映射
     的快照 fail-closed 拒写。

守卫（八组，全部临时令牌库 + 哑主密钥，**绝不触真实 ~/.mdcg/_tokens.json**）：
  ⓿ 隔离自证：aux 根 / 默认令牌文件都须落在守卫临时目录，否则中止；
  ① 陈旧快照整份写回（确定性红腿，不复现概率）：A 取快照 → B 签发 → A 写回
     → B 的令牌必须仍在盘上且可验（修前 = 被无痕抹除、verify 抛 TokenError）；
  ② 多进程并发签发（barrier 对齐，8 进程 × 8 枚）：零异常、零静默丢失，
     每枚返回的明文令牌事后都能 verify 通过，盘面记录数 == 成功签发数；
  ③ 并发签发 + 派生 + 吊销混合：零异常，最终状态自洽（吊销生效、级联子令牌
     一并吊销、未被吊销者仍可验）；3d/3d2 以「钉住 verify 结果」确定性复现
     「verify 通过后被并发吊销」窗口，判定须拒绝派生且盘上不留孤儿记录；
  ④ 固定共享临时名残影：源断言（不再出现 `= p + ".tmp"` 赋值形态，且
     `atomic_write(` 在两个写点出现）+ 落盘临时名唯一性实测；
  ⑤ N198 面不回退：并发写者遇到损坏库仍一律 fail-closed（TokenError），
     且盘面损坏原文零改写（不得被并发写者覆盖成「半解析」态）；
  ⑥ 令牌库始终可解析（并发撕库面）：全流程任意时刻读盘都必须 json 可解析，
     且确有写入发生（防「一个都没写成」的空转假绿）；
  ⑦ 守卫自检：实弹断言数下限（LIVE_FLOOR）。

实测（本机）：修前 7 passed / 14 failed（含 3d「child=True」= 真造出父已吊销
的子凭据）；修后 21 passed / 0 failed（live=12）。

运行：python -X utf8 -m md_cg.test_n199_tokens_concurrent_write
"""
from __future__ import annotations

import atexit
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

# ── 隔离前置（须早于 import md_cg 子模块：aux 常量在模块级冻结） ──
_TMP = tempfile.mkdtemp(prefix="n199_")
os.environ["MDCG_AUX_ROOT"] = os.path.join(_TMP, "auxroot")
os.environ["MDCG_MASTER_KEY"] = "cd" * 32
os.environ["MDCG_TOKEN_FILE"] = os.path.join(_TMP, "tokens.json")
os.environ["MDCG_ROOT"] = os.path.join(_TMP, "cgroot")
for _k in ("MDCG_TOKEN", "MDCG_TENANT", "MDCG_LEGACY_ENV_AUTH",
           "MDCG_LEGACY_ENV_ADMIN", "MDCG_CAN_ADMIN", "MDCG_CAN_WRITE",
           "MDCG_TENANT_REGISTRY", "PYTHONIOENCODING", "PYTHONUTF8"):
    os.environ.pop(_k, None)

from . import tokens                                    # noqa: E402
from .tokens import TokenError                          # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PASS = FAIL = LIVE = 0
LIVE_FLOOR = 10           # 实弹（真 spawn/真落盘）断言数下限：防并发面失效假绿
FAILS = []
PROCS = 8            # 并发进程数
PER_PROC = 8         # 每进程签发枚数

# 子进程工作体：等 barrier 文件出现（对齐起跑）→ 连续签发 → stdout 回 JSON 结果表
_CHILD = r'''
import json, os, sys, time
from md_cg import tokens
p, n, barrier = sys.argv[1], int(sys.argv[2]), sys.argv[3]
while not os.path.exists(barrier):
    time.sleep(0.002)
out = []
for i in range(n):
    try:
        r = tokens.issue("record", actor="w%d-%d" % (os.getpid(), i), path=p)
        out.append({"ok": True, "token": r["token"]})
    except Exception as e:                      # noqa: BLE001
        out.append({"ok": False, "err": "%s: %s" % (type(e).__name__, e)})
sys.stdout.write(json.dumps(out))
'''


def check(name, cond, detail="", live=False):
    global PASS, FAIL, LIVE
    if live:
        LIVE += 1
    if cond:
        PASS += 1
        print("  [PASS] %s" % name)
    else:
        FAIL += 1
        FAILS.append(name)
        print("  [FAIL] %s · %s" % (name, detail))


def _read_disk(path):
    """盘面原文与解析结果（不可解析时 (raw, None)）。"""
    with open(path, encoding="utf-8", errors="replace") as fh:
        raw = fh.read()
    try:
        return raw, json.loads(raw)
    except ValueError:
        return raw, None


def _verify_ok(token, path):
    try:
        tokens.verify_token(token, path=path)
        return True, ""
    except Exception as e:                       # noqa: BLE001
        return False, "%s: %s" % (type(e).__name__, e)


def _race_issue(path, procs=PROCS, per=PER_PROC, timeout=180):
    """barrier 对齐起跑 → 并发签发 → 汇总 (返回表, 子进程 stderr 列表)。"""
    barrier = os.path.join(_TMP, "barrier_%d" % int(time.time() * 1000))
    ps = [subprocess.Popen(
        [sys.executable, "-X", "utf8", "-c", _CHILD, path, str(per), barrier],
        cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace") for _ in range(procs)]
    time.sleep(0.35)                    # 让所有子进程起来等 barrier
    open(barrier, "w").close()          # 对齐放行
    rows, errs = [], []
    for p in ps:
        try:
            out, err = p.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            p.kill()
            out, err = p.communicate()
            errs.append("TIMEOUT")
        try:
            rows.extend(json.loads(out or "[]"))
        except ValueError:
            errs.append("BAD_JSON_OUT: %r" % (out or "")[:200])
        if (err or "").strip():
            errs.append(err.strip()[-200:])
    return rows, errs


def _cleanup(path) -> bool:
    import gc
    for _ in range(6):
        shutil.rmtree(path, ignore_errors=True)
        if not os.path.exists(path):
            return True
        gc.collect()
        time.sleep(0.25)
    return not os.path.exists(path)


# 退场清洁：库层 mdcg._atexit_flush_all 会在退出时对存活实例补 close 并把
# `_index.json` 写回已删除的目录 → 本钩子在实例创建前注册（LIFO 后执行）。
atexit.register(lambda: _cleanup(_TMP))


def main():
    print("[0] 隔离自证")
    tokfile = tokens.token_file()
    aux = tokens.DEFAULT_TOKEN_DIR
    check("0a 默认令牌文件与 aux 根都落在守卫临时目录（绝不触真实凭据）",
          os.path.abspath(tokfile).lower().startswith(
              os.path.abspath(_TMP).lower())
          and os.path.abspath(aux).lower().startswith(
              os.path.abspath(_TMP).lower()),
          "tokfile=%s aux=%s" % (tokfile, aux))
    if not os.path.abspath(tokfile).lower().startswith(
            os.path.abspath(_TMP).lower()):
        print("FATAL: 隔离失败，中止（绝不带病跑真实 ~/.mdcg）")
        return 2

    # ---------- ① 陈旧快照整份写回（确定性：不复现概率） ----------
    print("[1] 陈旧快照整份写回：后写者不得抹除并发新增（确定性红腿）")
    p1 = os.path.join(_TMP, "stale.json")
    t_b = tokens.issue("record", actor="B", path=p1)["token"]
    stale = tokens._load(p1)              # A 在 B 落盘**之前**拿的快照语义
    stale["tokens"] = {"tk_stale_snapshot": {"role": "record", "actor": "A",
                                             "hash": "deadbeef"}}
    tokens._save(stale, p1)               # A 用陈旧快照整份写回
    _raw, disk = _read_disk(p1)
    disk_ids = sorted((disk or {}).get("tokens", {}).keys())
    b_id = t_b.split(".")[2]
    check("1a 陈旧快照写回后，B 的令牌记录仍在盘上（修前 = 被无痕抹除）",
          b_id in disk_ids, "disk_ids=%s" % disk_ids, live=True)
    ok, why = _verify_ok(t_b, p1)
    check("1b 由此 B 的明文令牌仍可 verify（修前 = 令牌不存在）", ok, why,
          live=True)
    check("1c A 的快照记录也已落盘（合并语义：键同在时以本次为准，不反向丢）",
          "tk_stale_snapshot" in disk_ids, "disk_ids=%s" % disk_ids)

    # ---------- ② 多进程并发签发 ----------
    print("[2] %d 进程 × %d 枚 并发签发（barrier 对齐）" % (PROCS, PER_PROC))
    p2 = os.path.join(_TMP, "concurrent_issue.json")
    rows, errs = _race_issue(p2)
    oks = [r["token"] for r in rows if r.get("ok")]
    bad = [r for r in rows if not r.get("ok")]
    check("2a 零失败：无进程抛异常（修前 = FileNotFoundError/PermissionError 成批）",
          len(bad) == 0 and len(oks) == PROCS * PER_PROC,
          "fail=%d errs=%s" % (len(bad), [r.get("err") for r in bad[:3]]),
          live=True)
    check("2b 子进程 stderr 干净（无 traceback/超时）", not errs,
          str(errs[:2]), live=True)
    _raw2, disk2 = _read_disk(p2)
    check("2c 令牌库可解析且记录数 == 成功签发数（无静默丢失）",
          isinstance(disk2, dict)
          and len((disk2.get("tokens") or {})) == len(oks),
          "disk=%s oks=%d"
          % (len((disk2 or {}).get("tokens") or {}) if isinstance(disk2, dict)
             else "UNPARSABLE", len(oks)), live=True)
    unverified = [(t, why) for t, (ok, why) in
                  ((t, _verify_ok(t, p2)) for t in oks) if not ok]
    check("2d 每枚返回的明文令牌事后都能 verify 通过（修前 = 拿到明文却验不过）",
          not unverified,
          "n_bad=%d sample=%s" % (len(unverified), unverified[:2]), live=True)

    # ---------- ③ 并发签发 + 派生 + 吊销混合 ----------
    print("[3] 并发签发 + 派生 + 吊销混合（同一令牌库）")
    p3 = os.path.join(_TMP, "mixed.json")
    par = tokens.issue("designer", actor="root", path=p3)
    child = tokens.derive(par["token"], "record", actor="child", path=p3)
    rows3, errs3 = _race_issue(p3, procs=4, per=4)
    ok3 = [r["token"] for r in rows3 if r.get("ok")]
    rv, rv_err = {}, ""
    try:
        rv = tokens.revoke(par["token_id"], path=p3)
    except TokenError as exc:      # 修前 = 父记录已被并发写回抹除 → 吊销打空
        rv_err = "TokenError: %s" % exc
    pv_ok, pv_why = _verify_ok(par["token"], p3)
    cv_ok, cv_why = _verify_ok(child["token"], p3)
    a_ok = all(_verify_ok(t, p3)[0] for t in ok3)
    check("3a 混合并发零失败且子进程 stderr 干净",
          len(ok3) == 16 and not errs3,
          "ok=%d errs=%s" % (len(ok3), errs3[:2]), live=True)
    check("3b 吊销生效：父与级联子令牌都失效（revoked_children=%s）"
          % rv.get("revoked_children"),
          not rv_err and not pv_ok and not cv_ok,
          "%s | %s | %s" % (rv_err, pv_why, cv_why), live=True)
    check("3c 并发签发的 16 枚不受吊销波及、仍全部可验（无连带丢失）", a_ok,
          "ok=%d" % len(ok3), live=True)

    # 3d 并发吊销 × 派生（同族第二面 · 授权泄漏）：父令牌在 verify 通过之后、
    #    派生落盘之前被并发吊销——级联只覆盖吊销那一刻盘上已有的子令牌，故
    #    修前会造出「父已吊销、子仍有效」的凭据。以「钉住校验结果」确定性复现
    #    该竞态窗口（不依赖运气），判定须落在锁内对父令牌落盘态的复核上。
    p3d = os.path.join(_TMP, "revoke_vs_derive.json")
    par3 = tokens.issue("designer", actor="root", path=p3d)
    stale_prin = tokens.verify_token(par3["token"], path=p3d)   # 校验已通过
    tokens.revoke(par3["token_id"], path=p3d)                    # 并发吊销落盘
    _orig_vt, child3d, err3d = tokens.verify_token, None, ""
    tokens.verify_token = lambda *a, **kw: stale_prin            # 钉住竞态窗口
    try:
        try:
            child3d = tokens.derive(par3["token"], "record", actor="x", path=p3d)
        except TokenError as exc:
            err3d = str(exc)
    finally:
        tokens.verify_token = _orig_vt
    check("3d 父令牌在 verify 后被并发吊销：拒绝派生（修前 = 造出父已吊销、"
          "子仍有效」的凭据）",
          child3d is None and "吊销" in err3d,
          "child=%s err=%s" % (child3d is not None, err3d[:60]), live=True)
    _raw3d, disk3d = _read_disk(p3d)
    _kids3d = [t for t, r in ((disk3d or {}).get("tokens") or {}).items()
               if r.get("parent") == par3["token_id"]]
    check("3d2 拒绝派生后盘上无「父已吊销」的新子记录（fail-closed 无副作用）",
          not _kids3d, "kids=%s" % _kids3d, live=True)

    # ---------- ④ 固定共享临时名残影 ----------
    print("[4] 固定共享临时名（反模式）残影：源断言 + 落盘临时名唯一性")
    with open(os.path.join(ROOT, "md_cg", "tokens.py"), encoding="utf-8",
              errors="replace") as fh:
        src = fh.read()
    check("4a tokens.py 不再把临时名赋成 `p + \".tmp\"`（固定共享名·两处写点）",
          re.search(r'=\s*p\s*\+\s*"\.tmp"', src) is None,
          "仍命中：%d 处" % len(re.findall(r'=\s*p\s*\+\s*"\.tmp"', src)))
    check("4b _save 与 _write_secret 两个写点都走 fsutil.atomic_write"
          "（同目录唯一临时名 + 重试 replace）",
          src.count("atomic_write(") >= 2 and "from .fsutil import" in src
          and "atomic_write" in src.split("from .fsutil import")[1][:80],
          "atomic_write( 出现 %d 次" % src.count("atomic_write("))
    d = os.path.join(_TMP, "tmpname")
    os.makedirs(d, exist_ok=True)
    left = [n for n in os.listdir(d) if ".tmp-" in n]
    check("4c 写后不残留固定名临时文件（落盘目录里无 `*.tmp` 共享名）",
          not [n for n in os.listdir(d) if n.endswith(".tmp")],
          "leftover=%s" % (left + [n for n in os.listdir(d)
                                   if n.endswith(".tmp")]))

    # ---------- ⑤ N198 面不回退：损坏库并发写仍 fail-closed ----------
    print("[5] 损坏库 + 并发写：一律 fail-closed 且损坏原文零改写")
    p5 = os.path.join(_TMP, "corrupt.json")
    with open(p5, "w", encoding="utf-8") as fh:
        fh.write('{"tokens": {')          # 部分写/手工编辑典型形态
    before = open(p5, encoding="utf-8").read()
    refused = []
    for i in range(3):
        try:
            tokens.issue("record", actor="c%d" % i, path=p5)
            refused.append("ok?!")
        except TokenError:
            refused.append("refused")
    check("5a 损坏库下签发一律抛 TokenError（N198 闸未回退）",
          refused.count("refused") == 3, str(refused))
    check("5b 损坏原文零改写（并发失败路径不得覆盖盘面）",
          open(p5, encoding="utf-8").read() == before)

    # ---------- ⑥ 令牌库全程可解析（并发撕库面） ----------
    print("[6] 任意时刻读盘都必须可解析（原子替换，无撕裂）")
    p6 = os.path.join(_TMP, "torn.json")
    stolen = []
    rows6, _errs6 = _race_issue(p6, procs=4, per=6)
    for _ in range(40):                   # 并发期多次抽样读盘
        _raw, obj = _read_disk(p6)
        if obj is None:
            stolen.append("UNPARSABLE")
        time.sleep(0.01)
    check("6a 并发写入期间/之后读盘一律 json 可解析（无半截文件）",
          not stolen, str(stolen[:2]), live=True)
    _obj6 = _read_disk(p6)[1]
    check("6b 6a 腿确有写入发生（24 枚记录，防空转假绿）",
          isinstance(_obj6, dict)
          and len((_obj6.get("tokens") or {})) >= 24,
          "n=%s" % (len((_obj6.get("tokens") or {}))
                    if isinstance(_obj6, dict) else "UNPARSABLE"))

    print("[7] 守卫自检")
    check("7a 实弹断言数 ≥ %d（防 spawn/扫描面失效假绿）" % LIVE_FLOOR,
          LIVE >= LIVE_FLOOR, "LIVE=%d" % LIVE)

    print("\n=== N199 tokens concurrent write: %d passed, %d failed (live=%d) ==="
          % (PASS, FAIL, LIVE))
    if FAILS:
        print("失败项：%s" % "；".join(FAILS))
    return 1 if FAIL else 0


if __name__ == "__main__":
    _code = 0
    try:
        _code = main()
    finally:
        if not _cleanup(_TMP):
            print("WARN: 临时根残留未清（%s）——请人工清理" % _TMP)
    sys.exit(_code)
