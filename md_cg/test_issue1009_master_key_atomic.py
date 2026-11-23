# -*- coding: utf-8 -*-
"""主密钥首次创建的原子性与权限（issue #1009 第 5 项）。

【守什么】
`load_master_key` 首建曾用裸 `open(path, "w")` 写完再 `os.chmod(path, 0o600)`：
  ① POSIX 上存在「已可读、尚未 0600」的窗口；
  ② 两个进程并发首启各写一把 KEK，后写者覆盖前者 → 先写者加密的数据成孤儿。

【判据】
  1. 首建走 O_CREAT|O_EXCL（mode 在创建瞬间生效），源码不再对被创建路径用 `open(path, "w")`；
  2. 已有文件时**读回那一把**，绝不覆盖（并发/重启都不得换 KEK）；
  3. 写入失败不留半截文件；
  4. 已有文件路径仍可正常加载。

运行：python -X utf8 -m md_cg.test_issue1009_master_key_atomic
"""
from __future__ import annotations

import io
import os
import stat
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from md_cg import crypto  # noqa: E402

_OK = 0
_BAD = []


def ok(cond, name, extra=""):
    global _OK
    if cond:
        _OK += 1
        print("  ok   %s %s" % (name, extra))
    else:
        _BAD.append(name)
        print("  FAIL %s %s" % (name, extra))


def main():
    print("=== issue #1009 第 5 项：master.key 首建原子性 ===")
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "sub", "master.key")
        k1 = crypto.load_master_key(path, env_var="MDCG_TEST_NO_SUCH_ENV")
        ok(os.path.exists(path), "P1 首建落盘")
        with open(path, encoding="utf-8") as f:
            on_disk = crypto._b64d(f.read().strip())
        ok(k1 == on_disk and len(k1) == crypto.KEY_LEN, "P2 返回的 KEK == 落盘 KEK")
        if os.name == "posix":
            mode = stat.S_IMODE(os.stat(path).st_mode)
            ok(mode == 0o600, "P3 POSIX 权限 0600（创建瞬间生效）", oct(mode))
        else:
            print("  SKIP P3 Windows 无 0600 语义（见 _tighten_perms 注释）")

        k2 = crypto.load_master_key(path, env_var="MDCG_TEST_NO_SUCH_ENV")
        ok(k2 == k1, "P4 二次加载读回同一把（不覆盖）")

        # P5 并发首启：文件已存在 → 必须用现存那把，而不是新生成
        before = io.open(path, encoding="utf-8").read()
        k3 = crypto.load_master_key(path, env_var="MDCG_TEST_NO_SUCH_ENV")
        after = io.open(path, encoding="utf-8").read()
        ok(k3 == k1 and before == after, "P5 文件已存在时不重写内容")

    # P6 竞态：抢不到独占权时读回对方那把
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "master.key")
        incumbent = os.urandom(crypto.KEY_LEN)
        with open(path, "w", encoding="utf-8") as f:
            f.write(crypto._b64e(incumbent))
        orig_open = crypto.os.open

        def racing_open(p, flags, mode=0o777):
            if p == path and (flags & os.O_EXCL):
                raise FileExistsError(17, "File exists")
            return orig_open(p, flags, mode)

        crypto.os.open = racing_open
        try:
            k = crypto.load_master_key(path, env_var="MDCG_TEST_NO_SUCH_ENV")
        finally:
            crypto.os.open = orig_open
        ok(k == incumbent, "P6 抢不到 O_EXCL 时读回既有 KEK（不覆盖对方）")

    src_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "crypto.py")
    with open(src_path, encoding="utf-8") as f:
        src = f.read()
    ok("os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600" in src, "S1 首建用 O_CREAT|O_EXCL 且带 0o600")
    ok('with open(path, "w", encoding="utf-8") as f:' not in src,
       "S2 源码不再对被创建路径用 open(path, \"w\") 裸写")
    ok("os.unlink(path)" in src, "S3 写失败清理半截文件")

    print()
    print("master.key 首建守卫：%d 通过，%d 失败" % (_OK, len(_BAD)))
    if _BAD:
        print("失败项：" + " / ".join(_BAD))
    return 1 if _BAD else 0


if __name__ == "__main__":
    sys.exit(main())