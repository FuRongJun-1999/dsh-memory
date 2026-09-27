# -*- coding: utf-8 -*-
"""N139 守卫（第 5 轮，2026-09-27）：密钥库损坏/漂移回落 fail-closed——
provision_dek 不得据空表静默重签整份覆盖。

留档复测（v8 N139 首报 → v9/v15/v16 历轮成立 → 本轮第 5 次，medium 维持）：

病灶①（crypto.py:263-274）：_load_keys 遇「文件在但 JSON 截断/损坏」
（ValueError）或「OSError 不可读」或「顶层 dict 但 envelopes 缺失/非 dict」
（版本漂移）时 `except (ValueError, OSError): pass` 静默回落空 envelopes
——零告警零标记。
病灶②（:290-314）：provision_dek 据空表走重签分支生成新 DEK 并 _save_keys
（:313，唯一写点；rotate_dek :343-345 委托之）整份覆盖写回——旧信封无痕
抹除、旧密文永久不可解，全程无备份无审计无 stderr。

红守卫（哑 KEK=os.urandom(32) + 临时目录，确定性、零真实状态）：
  R1 截断 _keys.json → provision_dek 必失败（LockedError）+ stderr 告警
     + 原文件字节不被覆盖；
  R2 读面零闸变：unwrap_dek 对损坏文件照旧按无信封抛 LockedError；
  R3 fresh install（缺文件 ≠ 损坏）零闸变：provision 照常签发；
  R4 完好文件幂等路径零误伤（同 (tenant, actor) 重进 → 原 DEK 原样）；
  R5 版本漂移面（合法 JSON 但 envelopes 非映射）同闸；
  R6 生产面（mdcos.MdCGSecure 构造）：损坏文件下 _crypto_error 留痕、
     dek=None、坏文件字节原样（fail-closed 降级不崩进程）。

运行：python -m md_cg.test_n139_dek_provision_failclosed
"""
from __future__ import annotations

import contextlib
import io
import os
import shutil
import sys
import tempfile

from . import crypto
from .mdcos import MdCGSecure

PASS = FAIL = 0
FAILS = []
MARK = "密钥库损坏"              # stderr 告警/拒绝消息稳定锚点


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  OK   " + name)
    else:
        FAIL += 1
        FAILS.append(name)
        print("  FAIL " + name + "  " + str(detail)[:110])


def _provision(root, kek, tenant, actor, **kw):
    """provision_dek 捕获异常，返回 (dek|None, exc|None)。"""
    try:
        return crypto.provision_dek(root, kek, tenant, actor, **kw), None
    except crypto.CryptoError as e:
        return None, e


def _unwrap(root, kek, tenant, actor):
    try:
        return crypto.unwrap_dek(root, kek, tenant, actor), None
    except crypto.CryptoError as e:
        return None, e


def _read(p):
    with open(p, "rb") as f:
        return f.read()


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    tmp = tempfile.mkdtemp(prefix="mdcg_n139_")
    kek = os.urandom(32)           # 哑 KEK：仅本守卫用，绝不触真实主密钥
    try:
        # ---------- R1 截断文件 → provision fail-closed ----------
        print("== R1 截断 _keys.json → provision_dek 必失败且原文件不被覆盖 ==")
        root1 = os.path.join(tmp, "r1")
        os.makedirs(root1)
        dek_a, e_a = _provision(root1, kek, "tenantA", "actorA")
        check("R1a 基线：正常签发 DEK", dek_a is not None and e_a is None,
              f"dek={'有' if dek_a else '无'} exc={e_a}")
        kf = crypto.keys_path(root1)
        good = _read(kf)
        with open(kf, "wb") as f:
            f.write(b'{"v": 1, "alg": "cha')   # 截断 JSON（哑损坏样本）
        corrupt = _read(kf)
        check("R1b 损坏样本在位（截断 JSON）",
              corrupt != good and len(corrupt) < len(good),
              f"len={len(corrupt)} vs {len(good)}")
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            dek_b, e_b = _provision(root1, kek, "tenantB", "actorB")
        check("R1c 损坏标记下 provision 被拒（LockedError 且含锚点）",
              dek_b is None and e_b is not None and MARK in str(e_b),
              f"dek={'有' if dek_b else '无'} "
              f"exc={type(e_b).__name__}: {str(e_b)[:80]}")
        check("R1d stderr 告警开口（含锚点与路径）",
              MARK in buf.getvalue() and kf in buf.getvalue(),
              buf.getvalue().strip()[:100])
        check("R1e 原文件字节不被覆盖（无痕抹除被阻断）",
              _read(kf) == corrupt,
              f"len={len(_read(kf))} vs {len(corrupt)}")

        # ---------- R2 读面零闸变 ----------
        print("== R2 读面零闸变：unwrap 照旧按无信封抛 ==")
        _, e2 = _unwrap(root1, kek, "tenantA", "actorA")
        check("R2 损坏文件下 unwrap 仍抛 LockedError（不假装能解密）",
              e2 is not None, f"exc={type(e2).__name__ if e2 else None}")

        # ---------- R3 fresh install 零闸变 ----------
        print("== R3 fresh install（缺文件≠损坏）零闸变 ==")
        root3 = os.path.join(tmp, "r3")
        os.makedirs(root3)
        dek3, e3 = _provision(root3, kek, "tenantC", "actorC")
        check("R3 缺文件时 provision 照常签发",
              e3 is None and dek3 is not None
              and os.path.isfile(crypto.keys_path(root3)),
              f"dek={'有' if dek3 else '无'} exc={e3}")

        # ---------- R4 完好文件幂等路径零误伤 ----------
        print("== R4 完好文件幂等路径零误伤 ==")
        dek4, e4 = _provision(root3, kek, "tenantC", "actorC")
        check("R4 同 (tenant, actor) 重进 → 原 DEK 原样",
              e4 is None and dek4 == dek3, f"exc={e4}")

        # ---------- R5 版本漂移面 ----------
        print("== R5 版本漂移（顶层合法但 envelopes 缺失/非 dict）同闸 ==")
        root5 = os.path.join(tmp, "r5")
        os.makedirs(root5)
        drift = b'{"v": 0, "note": "legacy-without-envelopes"}'
        with open(crypto.keys_path(root5), "wb") as f:
            f.write(drift)
        buf5 = io.StringIO()
        with contextlib.redirect_stderr(buf5):
            dek5, e5 = _provision(root5, kek, "tenantD", "actorD")
        check("R5a 漂移文件下 provision 被拒（LockedError 且含锚点）",
              dek5 is None and e5 is not None and MARK in str(e5),
              f"dek={'有' if dek5 else '无'} "
              f"exc={type(e5).__name__}: {str(e5)[:80]}")
        check("R5b 漂移原文件字节不被覆盖",
              _read(crypto.keys_path(root5)) == drift)

        # ---------- R6 生产面（MdCGSecure 构造） ----------
        print("== R6 生产面：MdCGSecure 构造遇损坏密钥库 fail-closed 降级 ==")
        root6 = os.path.join(tmp, "r6")
        os.makedirs(root6)
        with open(crypto.keys_path(root6), "wb") as f:
            f.write(b'{"v": 1, "alg": "cha')
        corrupt6 = _read(crypto.keys_path(root6))
        old_mk = os.environ.get(crypto.MASTER_ENV)
        os.environ[crypto.MASTER_ENV] = os.urandom(32).hex()   # 哑主密钥（env 路径）
        try:
            cg = MdCGSecure(root6, principal=None, master_key=bytes(range(32)))
            check("R6a 构造不崩（LockedError ⊂ CryptoError 被既有 catch 捕获）",
                  cg is not None)
            check("R6b _crypto_error 留痕且含锚点",
                  MARK in str(getattr(cg, "_crypto_error", "")),
                  f"_crypto_error={str(getattr(cg, '_crypto_error', ''))[:90]}")
            check("R6c dek=None（fail-closed 降级，private/secret 写被拒）",
                  getattr(cg, "dek", "MISSING") is None,
                  f"dek={getattr(cg, 'dek', 'MISSING')}")
            check("R6d 坏文件字节原样", _read(crypto.keys_path(root6)) == corrupt6)
        finally:
            if old_mk is None:
                os.environ.pop(crypto.MASTER_ENV, None)
            else:
                os.environ[crypto.MASTER_ENV] = old_mk
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    if FAILS:
        print("FAILED: %d 项 → %s" % (len(FAILS), ", ".join(FAILS)))
        return 1
    print("ALL OK: %d 项（N139 密钥库损坏回落 fail-closed 守卫全绿）" % PASS)
    return 0


if __name__ == "__main__":
    sys.exit(main())
