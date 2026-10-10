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
  ③d **独立实现扫描（2026-10-10 DSH 端独立复核补）**：全仓 .py 里构造分片名
     （basename 加 6 位零填充序号 + `.jsonl`）的文件集合必须**恰好**等于已声明集
     `{md_cg/rotate.py, md_cg/sustain.py}`——`rotate.py` 自述此前写「轮转机制唯一
     实现点」，与 `sustain.py::rotate_heartbeat` 自带第三份独立轮转的事实不符；
     现订正措辞，并让本断言在「他处存在/新增独立实现」时**点名到具体文件**。

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
#:
#: **平台维度（2026-10-10 DSH 端复核，根因判定）**：golden 必须按平台区分——
#: 同一序列在 Windows 与 Linux 上**改动前**就产出不同字节。根因：`fsutil.append_jsonl`
#: 以 `os.open`/`os.write` 写日志，Windows 的 fd 默认文本模式把 `\n` 翻成 `\r\n`
#: （Linux 为二进制、保持 `\n`），每条记录多 1 字节；分片/索引里记录的 `bytes`
#: 尺寸随之差 9（= 每片行数）。**这不是共享件引入的行为改变**：改动前的代码在真
#: Linux 容器里跑同一序列，产出与改动后**逐位相同**（即 CI 报出的 got 值就是
#: 改动前的 Linux 值）⇒ 判定为「golden 未声明平台」，非 `rotate.py` 真改行为。
#: 故两张表各自锁「本平台改动前后逐位不变」，判别力不削。
_GOLDEN_FROZEN_TS = 1700000000.0
_GOLDEN_WIN = {
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
_GOLDEN_LIN = {
    "_audit.jsonl":
        "91dcc9231e2b0992df91fcece56546eaf7dbe5353e4fb43f7d4914b7b925f676",
    "_audit_archive/_audit.000002.jsonl":
        "268e7e36f93c7db3b52c279aae0407496efbcb021f37c8d0e5ab3053a69a2501",
    "_audit_archive/_audit.000003.jsonl":
        "82e6a57db8ccb9ed82ddaef5cb2c475b224aba1998f2dbb119a6e2a54790fd7b",
    "_audit_archive/_audit.000004.jsonl":
        "d2d72a856e4421a3c336607466c124cfc5bd0929eee45727efd98fcfd882b8f8",
    "_audit_archive/_index.json":
        "643deb64679cfbeeada4e55902e7bb8c731ad4877654e8a3d2c2848429ea82da",
}
#: 按运行平台选表（Windows fd 文本模式 ⇒ CRLF；Linux 二进制 ⇒ LF）。
_GOLDEN = _GOLDEN_WIN if os.name == "nt" else _GOLDEN_LIN
_PLATFORM = "win" if os.name == "nt" else "lin"


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


#: 分片名构造式（防本守卫自命中：写成拼接式，文件内不出现完整字面量）。
_SHARD_MARK = "%0" + "6d.jsonl"
#: 已声明的独立轮转实现（`rotate.Rotator` 之外）：心跳台账自带一份。
_DECLARED_ROTATORS = {"md_cg/rotate.py", "md_cg/sustain.py"}


def _scan_shard_builders():
    """全仓 .py 里构造零填充分片名（basename + 6 位序号 + `.jsonl`）的文件。

    归一化为仓内相对路径；跳过 `.git` 等点目录与构建产物目录，并排除本守卫
    自身（它必须引用该构造式做扫描）。
    """
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    me = os.path.relpath(os.path.abspath(__file__), root).replace("\\", "/")
    hits = set()
    skip = {"node_modules", "target", "__pycache__", "venv", "build", "dist"}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames
                       if d not in skip and not d.startswith(".")]
        for fn in filenames:
            if not fn.endswith(".py"):
                continue
            p = os.path.join(dirpath, fn)
            rel = os.path.relpath(p, root).replace("\\", "/")
            if rel == me:
                continue
            try:
                with open(p, "r", encoding="utf-8", errors="replace") as f:
                    txt = f.read()
            except OSError:
                continue
            if _SHARD_MARK in txt:
                hits.add(rel)
    return hits


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
            ok(got == want,
               "①逐位不变[%s] %s（%s == %s）" % (_PLATFORM, rel, got[:16],
                                                want[:16]))

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
           "③b md_cg/rotate.py 是审计/密文两路共用实现（class Rotator）；"
           "心跳另有独立轮转见 ③d")
        ok("_rotator(root).maybe_rotate()" in s_crypto,
           "③c crypto.audit 已接共享件（写前轮转闸门在位）")
        # ③d 独立实现扫描：分片名构造者集合必须恰好等于已声明集。
        hits = _scan_shard_builders()
        extra = sorted(hits - _DECLARED_ROTATORS)
        ok(hits == _DECLARED_ROTATORS,
           "③d 独立轮转实现扫描：构造零填充分片名的文件集 = %s（应为 %s；"
           "未声明/新增的独立实现 = %s）"
           % (sorted(hits), sorted(_DECLARED_ROTATORS), extra or "无"))
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