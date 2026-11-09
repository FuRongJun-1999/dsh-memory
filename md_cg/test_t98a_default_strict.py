# -*- coding: utf-8 -*-
"""签名巡检「默认即最弱」判别力守卫（t98a-20261011 / t3）。

运行：python -X utf8 -m md_cg.test_t98a_default_strict
      python -m md_cg.run_tests md_cg -k t98a

被测对象是**新脚本** `md_cg/check_security_defaults.py`（不是库函数）——
它靠退出码说话，所以本套的核心动作是**起子进程拿返回码**。

两种工况（都在 tempfile 临时目录里造，绝不碰真实 ~/.mdcg）：

  G1 **缺失** —— 指向一个不存在的 `_signers.json`。
      断言：退出码 **非 0**（报红），且报告里 exists=False。
      这正是「默认即最弱」的现场：什么都没配 == 最弱配置，而且原先静默。
  G2 **显式从严** —— 写一个显式声明 `subsystems[""]` 为
      `require_peer_signature: true` + `on_verify_fail: "reject"` 的
      `_signers.json`。断言：退出码 **0**（不报红）。

**探针读的是哪个键（实测钉死，别想当然）**：`signer.policy_source()` 取的是
`d["subsystems"][""]` 再 `_normalize()` —— **文件顶层的
`require_peer_signature` / `on_verify_fail` 根本不参与**。顶层写 false/degrade
时，空策略经 `_normalize` 会补成默认的 True/reject，探针反而报「已从严」；
而 `subsystems[""]` 里写什么就原样生效。G3/G4 的工况因此必须写在
`subsystems[""]` 里，否则造出来的不是「弱」而是被静默补严的空策略。

另外三条防「判据空转」的补强（都在临时目录内，只读校验）：

  G3 **弱但不缺** —— 文件存在，但 `require_peer_signature=false` +
      `on_verify_fail="degrade"`。断言：仍**报红**。
  G4 **半严** —— 文件存在且 `require_peer_signature=true`，但
      `on_verify_fail="isolate"`。断言：仍**报红**（「严」要求两者同时满足）。
  G5 **只读** —— G1 跑完后，那个（缺失的）路径上**仍不存在**任何文件；
      且真实默认路径 `signer.signers_file()` 在跑前跑后的存在性**不变**。
      `~/.mdcg/_signers.json` 绝不因巡检而被创建。

沙箱注记：DSH 文件沙箱禁 CreatePipe，故子进程输出一律**重定向到文件**
（`stdout=open(log,'w')`），不用 `capture_output` / `PIPE`。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if __package__:
    from . import signer
else:                                  # 直接 `python md_cg/test_t98a_default_strict.py` 也能跑
    sys.path.insert(0, _REPO)
    from md_cg import signer

_SCRIPT = os.path.join(_REPO, "md_cg", "check_security_defaults.py")

_PASS = []
_FAIL = []


# 生效条件：cond 为真记录 PASS 并返回 True，否则记录 FAIL 并返回 False；n 为断言名。
def ok(cond: bool, n: str) -> bool:
    if cond:
        _PASS.append(n)
    else:
        _FAIL.append(n)
    return bool(cond)


# 生效条件：在 args 上起 check_security_defaults.py 子进程（cwd=_REPO），stdout+stderr 重定向到 logpath 文件后返回 (returncode, log_text)；无法启动返回 (-1, 错误文本)。
def _run_check(args, logpath):
    """起巡检子进程，输出重定向到文件（**不用管道** —— 沙箱禁 CreatePipe）。"""
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    argv = [sys.executable, "-X", "utf8", _SCRIPT] + list(args)
    try:
        with open(logpath, "wb") as fh:
            p = subprocess.run(argv, cwd=_REPO, stdout=fh,
                               stderr=subprocess.STDOUT,
                               stdin=subprocess.DEVNULL, env=env,
                               shell=False, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return -1, "无法启动/超时：%r" % (exc,)
    try:
        with open(logpath, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    except OSError as exc:
        text = "<日志读不出：%r>" % (exc,)
    return p.returncode, text


# 生效条件：dirp 下写 _signers.json，把**空子系统策略**（subsystems[""]，探针实际读的键）设为从严，返回该文件路径。
def _write_strict(dirp):
    """造「显式从严」工况：`subsystems[""]` 要求对端签名、验签失败即拒绝。"""
    p = os.path.join(dirp, "_signers.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump({"schema": 1,
                   "default_signer": signer.DEFAULT_SIGNER,
                   "subsystems": {"": {"signer": signer.DEFAULT_SIGNER,
                                       "sign_on": ["handshake"],
                                       "require_peer_signature": True,
                                       "on_verify_fail": "reject"}}},
                  f, ensure_ascii=False, indent=1)
    return p


# 生效条件：dirp 下写 _signers.json，按给定的 require_peer/on_fail 组合设定**空子系统策略**（探针实际读的键），返回该文件路径。
def _write_policy(dirp, require_peer, on_fail):
    """弱 / 半严工况：写在 `subsystems[""]` —— 顶层键探针不读，写了也不生效。"""
    p = os.path.join(dirp, "_signers.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump({"schema": 1,
                   "default_signer": signer.DEFAULT_SIGNER,
                   "subsystems": {"": {"signer": signer.DEFAULT_SIGNER,
                                       "sign_on": ["handshake"],
                                       "require_peer_signature": require_peer,
                                       "on_verify_fail": on_fail}}},
                  f, ensure_ascii=False, indent=1)
    return p


# 生效条件：无前置；脚本文件可导入且 evaluate 为可调用时返回 True，否则记录 FAIL。
def _g0_script_present():
    """G0 前置：被测脚本在，且能被 import 拿到判据函数。"""
    ok(os.path.isfile(_SCRIPT), "G0 巡检脚本存在")
    if not os.path.isfile(_SCRIPT):
        return
    try:
        if __package__:
            from . import check_security_defaults as chk
        else:                                             # 直接跑文件时按包名导入
            from md_cg import check_security_defaults as chk
    except Exception as exc:                              # noqa: BLE001
        ok(False, "G0 巡检脚本可导入：%r" % (exc,))
        return
    ok(callable(getattr(chk, "evaluate", None)), "G0 evaluate 可调用")
    ok(callable(getattr(chk, "main", None)), "G0 main 可调用")


# 生效条件：在临时目录造「文件缺失」工况并起子进程；断言退出码非 0 且报告 exists=False。
def _g1_missing_reports_red(tmp):
    """G1 缺失 → 非 0 退出码报红。"""
    d = os.path.join(tmp, "missing")
    os.makedirs(d, exist_ok=True)
    target = os.path.join(d, "_signers.json")
    ok(not os.path.exists(target), "G1 前置：目标策略文件确实不存在")

    rc, log = _run_check(["--signers-file", target,
                          "--json", ], os.path.join(tmp, "g1.log"))
    ok(rc != 0, "G1 缺失 → 非 0 退出码（实得 %s）" % rc)
    ok(rc not in (2,), "G1 缺失是**报红**(1) 而非巡检自身故障(2)（实得 %s）" % rc)
    try:
        rep = json.loads(log)["report"]
    except Exception:                                     # noqa: BLE001
        ok(False, "G1 输出可解析为 JSON 报告：%r" % (log[-300:],))
        return
    ok(rep.get("exists") is False, "G1 报告 exists=False")
    # 注：缺失时 load_policies 的回落值**本身就是严的**（True/reject），所以
    # 报告里 strict 会是 True —— 报红的理由是「文件不在（隐式回落）」这条，
    # 而不是取值弱。判据 A 与判据 B/C 是**两条独立的报红线**，此处钉住 A 独走。
    ok(rep.get("strict") is True,
       "G1 缺失时回落值本身为严（strict=True）—— 报红只能来自「文件缺失」这条")
    ok(bool(rep.get("missing_strict")) is True,
       "G1 报告 missing_strict=True（探针自报「默认即最弱」现场）")


# 生效条件：在临时目录写显式从严 _signers.json 并起子进程；断言退出码为 0。
def _g2_strict_not_red(tmp):
    """G2 显式从严 → 退出码 0（不报红）。"""
    d = os.path.join(tmp, "strict")
    os.makedirs(d, exist_ok=True)
    p = _write_strict(d)
    ok(os.path.isfile(p), "G2 前置：从严策略文件已写出")

    rc, log = _run_check(["--signers-file", p, "--json"],
                         os.path.join(tmp, "g2.log"))
    ok(rc == 0, "G2 从严 → 退出码 0（实得 %s；日志尾 %r）" % (rc, log[-300:]))
    try:
        rep = json.loads(log)["report"]
    except Exception:                                     # noqa: BLE001
        ok(False, "G2 输出可解析为 JSON 报告：%r" % (log[-300:],))
        return
    ok(rep.get("exists") is True, "G2 报告 exists=True")
    ok(rep.get("require_peer_signature") is True, "G2 要求对端签名=True")
    ok(rep.get("on_verify_fail") == "reject", "G2 验签失败处置=reject")
    ok(rep.get("strict") is True, "G2 报告 strict=True")


# 生效条件：在临时目录写「存在但弱」（不要求对端签名 + degrade）策略并起子进程；断言仍非 0 报红。
def _g3_weak_present_still_red(tmp):
    """G3 弱但不缺 → 仍报红（证明判据不是「只看文件在不在」）。"""
    d = os.path.join(tmp, "weak")
    os.makedirs(d, exist_ok=True)
    p = _write_policy(d, False, "degrade")

    rc, log = _run_check(["--signers-file", p, "--json"],
                         os.path.join(tmp, "g3.log"))
    ok(rc != 0, "G3 弱配置 → 非 0 报红（实得 %s）" % rc)
    try:
        rep = json.loads(log)["report"]
    except Exception:                                     # noqa: BLE001
        ok(False, "G3 输出可解析为 JSON 报告：%r" % (log[-300:],))
        return
    ok(rep.get("exists") is True, "G3 报告 exists=True（文件在）")
    ok(rep.get("strict") is False, "G3 报告 strict=False")


# 生效条件：在临时目录写「半严」（要求对端签名但 on_verify_fail=isolate）策略并起子进程；断言仍非 0 报红。
def _g4_half_strict_still_red(tmp):
    """G4 半严 → 仍报红（「严」要求两者同时满足）。"""
    d = os.path.join(tmp, "half")
    os.makedirs(d, exist_ok=True)
    p = _write_policy(d, True, "isolate")

    rc, log = _run_check(["--signers-file", p, "--json"],
                         os.path.join(tmp, "g4.log"))
    ok(rc != 0, "G4 半严 → 非 0 报红（实得 %s）" % rc)
    try:
        rep = json.loads(log)["report"]
    except Exception:                                     # noqa: BLE001
        ok(False, "G4 输出可解析为 JSON 报告：%r" % (log[-300:],))
        return
    ok(rep.get("require_peer_signature") is True, "G4 要求对端签名=True")
    ok(rep.get("on_verify_fail") == "isolate", "G4 处置=isolate")
    ok(rep.get("strict") is False, "G4 未达从严（strict=False）")


# 生效条件：起子进程指向不存在路径与真实默认路径（只读 --json），断言两者都不会被创建；返回后真实路径的存在性须与跑前一致。
def _g5_readonly(tmp):
    """G5 只读：巡检不创建任何策略文件（含真实默认路径）。"""
    real = signer.signers_file()
    real_before = os.path.exists(real)

    d = os.path.join(tmp, "readonly")
    os.makedirs(d, exist_ok=True)
    target = os.path.join(d, "_signers.json")
    _rc, _log = _run_check(["--signers-file", target],
                           os.path.join(tmp, "g5a.log"))
    ok(not os.path.exists(target), "G5 巡检未创建指向的（缺失）策略文件")

    _rc2, _log2 = _run_check([], os.path.join(tmp, "g5b.log"))
    ok(os.path.exists(real) == real_before,
       "G5 真实默认路径存在性不变（%s：%s）"
       % (real, "在" if real_before else "本就不在"))

    if not real_before:
        ok(not os.path.exists(real),
           "G5 ~/.mdcg/_signers.json 未被巡检创建")


def main() -> int:
    if not os.path.isfile(_SCRIPT):                       # 极早失败，信息清楚
        print("巡检脚本缺失：%s" % _SCRIPT)
        return 1
    tmp = tempfile.mkdtemp(prefix="t98a_")
    try:
        _g0_script_present()
        _g1_missing_reports_red(tmp)
        _g2_strict_not_red(tmp)
        _g3_weak_present_still_red(tmp)
        _g4_half_strict_still_red(tmp)
        _g5_readonly(tmp)
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)

    for n in _FAIL:
        print("  FAIL  %s" % n)
    print("\nt98a 签名巡检「默认即最弱」守卫：%d 通过，%d 失败"
          % (len(_PASS), len(_FAIL)))
    return 0 if not _FAIL else 1


if __name__ == "__main__":
    sys.exit(main())
