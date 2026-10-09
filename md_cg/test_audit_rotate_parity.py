# -*- coding: utf-8 -*-
"""A2 共享件守卫：审计轮转「改前/改后逐位不变」+ 两侧同源（md_cg.rotate.Rotator）。

背景（2026-10-10 设计者裁定 A2）：把 `mdcos` 的审计分片轮转抽成**参数化共享件**
`md_cg/rotate.Rotator`，让 `mdcos` 的 `_audit.jsonl` 轮转与 `crypto.audit` 的
`_crypto.jsonl` 轮转**同时改调它**。硬要求是**审计侧行为逐位不变**。

本守卫的证据形态（可复现、非自证）：
  ① 固定序列 + **冻结时钟** ⇒ `_audit.jsonl` / 归档分片 / 归档索引 字节确定；
     与**改动前**（同一序列真跑）捕获的 sha256 常量逐位比对——任何漂移即红。
  ② 两侧同源：`MdCGOS._audit_rot` 与 `crypto._rotator(root)` 是**同一个类对象**
     （`md_cg.rotate.Rotator`）。
  ③ 源面：轮转实现体已从 `mdcos.py` 抽出（旧 `publish(self.audit_log, dst)` 不再
     出现在 mdcos），`crypto.audit` 已接共享件（`maybe_rotate()` 在位）。

运行：python -m md_cg.test_audit_rotate_parity
"""
from __future__ import annotations

import hashlib
import os
import shutil
import tempfile

from . import crypto
from . import mdcos as mdcos_mod
from . import rotate as rotate_mod
from .mdcos import MdCGOS

PASS = FAIL = 0
FAILS = []

#: 改动前（抽出共享件之前，同一序列真跑）捕获的字节指纹。**判据常量**——
#: 改后任一处字节漂移 ⇒ 逐位比对失败（这就是「审计侧逐位不变」的可执行断言）。
_GOLDEN_FROZEN_TS = 1700000000.0
_GOLDEN = {
    "_audit.jsonl":
        "ada0801b4e5764723b896df75500474879a7118010514ebac19912fdfbe4367c",
    "_audit_archive/_audit.000002.jsonl":
        "777d0008d21e8f6d044a26a1aef92c8e2b58f76084c0047c6585891dafc2066c",
    "_audit_archive/_audit.000003.jsonl":
        "4bdb34c7b9d227a8959b21c81b2b45afcb0460ece2431043ba1e2b207620319f",
    "_audit_archive/_audit.000004.jsonl":
        "7044512d3b3a95b4db039bbc18f94196e59ed9acb7f9ac7e22633ca5aede28a6",
    "_audit_archive/_index.json":
        "186ff64d9f51a0183528e2f2d57da74997d6a15ee560bfbc08d6660d1ad42fc6",
}


def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        FAILS.append(label)
        print(f"  FAIL {label}")


class _Frozen(object):
    """冻结时源：轮转自述与索引时间戳据此确定（否则哈希不可复现）。"""

    @staticmethod
    def time():
        return _GOLDEN_FROZEN_TS


def _sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _read_src(name):
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), name),
              "r", encoding="utf-8") as f:
        return f.read()


def main():
    tmp = tempfile.mkdtemp(prefix="mdcg_a2_parity_")
    orig_time = mdcos_mod.time
    try:
        # ---------- ① 逐位不变：固定序列 + 冻结时钟 ----------
        mdcos_mod.time = _Frozen
        root = os.path.join(tmp, "root")
        os.makedirs(root)
        cg = MdCGOS(root)
        cg.AUDIT_ROTATE_BYTES = 2048
        cg.AUDIT_KEEP_SHARDS = 3
        cg.AUDIT_PROBE_EVERY = 1
        for i in range(40):
            cg._audit("add", "node_%d" % i, pad="z" * 160)
        cg.close()
        mdcos_mod.time = orig_time

        for rel, want in _GOLDEN.items():
            got = _sha(os.path.join(root, rel))
            ok(got == want, "①逐位不变 %s（%s == %s）" % (rel, got[:16], want[:16]))

        # ---------- ② 两侧同源：同一个 Rotator 类对象 ----------
        cg2 = MdCGOS(os.path.join(tmp, "root2"))
        crypto.CRYPTO_ROTATE_BYTES = 1 << 30
        try:
            r_crypto = crypto._rotator(cg2.root)
            ok(type(cg2._audit_rot) is rotate_mod.Rotator
               and type(r_crypto) is rotate_mod.Rotator
               and type(cg2._audit_rot) is type(r_crypto),
               "②两侧同源：mdcos._audit_rot 与 crypto._rotator 均为同一个 "
               "md_cg.rotate.Rotator 类")
        finally:
            crypto.CRYPTO_ROTATE_BYTES = 64 << 20
            cg2.close()

        # ---------- ③ 源面：实现体已抽出、crypto 已接线 ----------
        s_mdcos = _read_src("mdcos.py")
        s_crypto = _read_src("crypto.py")
        s_rotate = _read_src("rotate.py")
        ok("publish(self.audit_log, dst)" not in s_mdcos
           and "self._audit_rot" in s_mdcos,
           "③a mdcos 轮转实现体已抽出（旧 publish 体不在 mdcos，改走 _audit_rot）")
        ok("class Rotator" in s_rotate and "def maybe_rotate" in s_rotate,
           "③b md_cg/rotate.py 是唯一实现点（class Rotator）")
        ok("_rotator(root).maybe_rotate()" in s_crypto,
           "③c crypto.audit 已接共享件（写前轮转闸门在位）")
    finally:
        mdcos_mod.time = orig_time
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"\naudit_rotate_parity: {PASS} pass / {FAIL} fail")
    if FAILS:
        for f in FAILS:
            print(f" - {f}")
    raise SystemExit(1 if FAIL else 0)


if __name__ == "__main__":
    main()