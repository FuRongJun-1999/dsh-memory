# -*- coding: utf-8 -*-
r"""#152③ 守卫：解密产物缓存（每查询逐节点 AEAD 解密 → 缓存命中）。

缺陷形态（复现于 HEAD）：
    `md_cg/mdcos.py` 的 `_open_content` 每次读面都重跑一次 AEAD 解密。实测
    `_read` 命中缓存后 0.25 µs/节点，而 `_read + 解密` 为 160.18 µs/节点
    （解密占 99.8%）；3000 节点一次查询外推 480 ms，而 internal 库仅
    0.14 µs/节点——密文库检索的**全部**额外成本几乎都在这里。

修法（本件）：
    增设「解密产物缓存」——键 `(node_id, sha256(密文)[:16], sha256(dek)[:16])`：
      · 键含**密文摘要** ⇒ 任何写盘（AEAD 随机 nonce 使密文逐次不同）自动失效；
      · 键含 **dek 指纹** ⇒ lock/unlock 换密钥态自然失配（同 `bm25.access_key`）；
      · 另在 lock/unlock（`_invalidate_caches_on_key_change`）**整清**，
        保证锁后内存里不留明文（与 `get()` 的 lock 语义一致）。
    只缓存**成功**的解密结果（失败/隔离不缓存）。

断言组（解密次数用 `crypto.open_node` 计数器，不靠计时）：
  A 缓存命中：
      A1 首读解密 1 次 / A2 再读同节点解密 0 次 / A3 缓存内已有条目
      A4 两次返回同一明文（值正确、非空）/ A5 两节点各自只解一次
  B lock/unlock（fail-closed）：
      B1 lock 后缓存整清（len == 0）
      B2 lock 后 get() 返回 None（不可读）
      B3 lock 后不尝试解密（无 dek 短路，解密计数不增）
      B4 unlock 后必须**重新解密**（换密钥态不得复用旧明文），且读到明文
  C 写后失效：
      C1 覆写同 id 后 get 读到新正文且重新解密
      C2 覆写后再读（同新键）解密 0 次
      C3 源码级 pin：`_plain_key` 绑密文摘要 + dek 指纹
  D 定点变异自证（守卫须转红）：
      D1 --mutate=nocache：摘掉缓存读写 ⇒ A1/A2 转红
      D2 --mutate=noclear：摘掉 lock/unlock 清缓存 ⇒ B1 转红

用法：
  python -X utf8 -m md_cg.test_issue152b_decrypt_cache
  python -X utf8 -m md_cg.test_issue152b_decrypt_cache --mutate=nocache
  python -X utf8 -m md_cg.test_issue152b_decrypt_cache --mutate=noclear
退出码：0 = 全绿（或变异如期转红）；1 = 有断言失败 / 变异未转红。
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PASS = 0
FAIL = 0
FAILS = []


def ok(cond, label, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        FAILS.append(label)
    print("  [%s] %s%s" % ("PASS" if cond else "FAIL", label,
                           ("  · " + str(detail)) if detail else ""))
    return bool(cond)


def _here():
    return os.path.dirname(os.path.abspath(__file__))


def _tmp_root(prefix):
    root = tempfile.mkdtemp(prefix=prefix)
    _rt, _tt = os.path.realpath(root), os.path.realpath(tempfile.gettempdir())
    assert _rt.startswith(_tt), "沙箱断言失败：%r 不在 tempdir 内" % _rt
    return root


class _Counter:
    def __init__(self, mod):
        self.mod = mod
        self._orig = mod.open_node
        self.n = 0

    def __enter__(self):
        outer = self

        def _wrapped(*a, **kw):
            outer.n += 1
            return outer._orig(*a, **kw)

        self.mod.open_node = _wrapped
        return self

    def __exit__(self, *exc):
        self.mod.open_node = self._orig
        return False


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    mut = ""
    for a in argv:
        if a.startswith("--mutate="):
            mut = a.split("=", 1)[1]

    from md_cg import crypto
    from md_cg import mdcos
    from md_cg.mdcos import MdCGSecure
    from md_cg.security import Principal

    _orig_inval = MdCGSecure._invalidate_caches_on_key_change

    if mut == "nocache":
        # 摘掉缓存读写（等价于 HEAD：每次都真解密）
        MdCGSecure._plain_get = lambda self, key: None
        MdCGSecure._plain_put = lambda self, key, plain: None
    elif mut == "noclear":
        # 摘掉 lock/unlock 的缓存整清（含 readcache/hotcache 一并摘）
        MdCGSecure._invalidate_caches_on_key_change = lambda self: None

    sb = _tmp_root("iss152b_")
    try:
        owner = Principal(tenant="t1", actor="alice", clearance="secret")
        key = os.urandom(32)
        cg = MdCGSecure(os.path.join(sb, "lib"), principal=owner,
                        master_key=key)
        B1 = "# 功能名：n1\n\n# 生效条件：x\n\n甲甲甲 乙乙乙 丙丙丙\n"
        B2 = "# 功能名：n2\n\n# 生效条件：y\n\n丁丁丁 戊戊戊 己己己\n"
        cg.add("n1", B1, layer="knowledge", sensitivity="secret")
        cg.add("n2", B2, layer="knowledge", sensitivity="secret")
        cg.flush()

        # ---------- A 组：缓存命中 ----------
        print("\n[A] 解密产物缓存命中")
        with _Counter(crypto) as c1:
            g1 = cg.get("n1")
        _a1 = (c1.n == 1)
        ok(_a1, "A1 首读 n1 解密恰 1 次", c1.n)

        with _Counter(crypto) as c2:
            g1b = cg.get("n1")
        ok(c2.n == 0, "A2 再读 n1 解密 0 次（缓存命中）", c2.n)
        ok(len(getattr(cg, "_plain_cache", {})) >= 1,
           "A3 缓存内已有条目", len(getattr(cg, "_plain_cache", {})))
        _p1 = (g1 or {}).get("content")
        _p1b = (g1b or {}).get("content")
        ok(_p1 and _p1 == _p1b and "甲甲甲" in _p1,
           "A4 两次返回同一明文（值正确、非空）",
           repr(_p1)[:40] if _p1 else _p1)

        with _Counter(crypto) as c3:
            cg.get("n2")
            cg.get("n1")
            cg.get("n2")
        ok(c3.n == 1, "A5 两节点各自只解一次（n2 首读=1，n1/n2 复读=0）", c3.n)

        # ---------- B 组：lock / unlock ----------
        print("\n[B] lock 后不留明文（fail-closed）")
        cg.lock()
        ok(len(getattr(cg, "_plain_cache", {})) == 0,
           "B1 lock 后缓存整清（len == 0）",
           len(getattr(cg, "_plain_cache", {})))
        with _Counter(crypto) as c4:
            gl = cg.get("n1")
        ok(gl is None, "B2 lock 后 get() 返回 None（不可读）", gl)
        ok(c4.n == 0, "B3 lock 后不尝试解密（无 dek 短路）", c4.n)

        cg.unlock(key)
        with _Counter(crypto) as c5:
            gu = cg.get("n1")
        ok(c5.n == 1, "B4 unlock 后必须重新解密（不复用旧明文）", c5.n)
        ok((gu or {}).get("content") == _p1,
           "B4b unlock 后读到正确明文",
           repr((gu or {}).get("content"))[:40])

        # ---------- C 组：写后失效 ----------
        print("\n[C] 写后缓存失效")
        NEW = "# 功能名：n1\n\n# 生效条件：z\n\n庚庚庚 辛辛辛\n"
        with _Counter(crypto) as c6:
            cg.add("n1", NEW, layer="knowledge", sensitivity="secret")
            cg.flush()
            gw = cg.get("n1")
        ok(c6.n >= 1, "C1 覆写同 id 后读到新正文且重新解密", c6.n)
        _pw = (gw or {}).get("content")
        ok(_pw == NEW, "C1b 覆写后返回新正文",
           repr(_pw)[:40])
        with _Counter(crypto) as c7:
            cg.get("n1")
        ok(c7.n == 0, "C2 覆写后再读（同新键）解密 0 次", c7.n)

        _src = open(os.path.join(_here(), "mdcos.py"), encoding="utf-8").read()
        _pin_key = ("sha256(content.encode" in _src
                    and "hashlib.sha256(_dek).hexdigest()[:16]" in _src)
        _pin_lock = "_pc.clear()" in _src
        ok(_pin_key and _pin_lock,
           "C3 源码级 pin：_plain_key 绑密文摘要 + dek 指纹；lock 路径含 clear",
           (_pin_key, _pin_lock))

        # ---------- D 组：变异读数 ----------
        print("\n[D] 定点变异读数（正常态应全绿；变异应转红）")
        print("    变异=%s ⇒ A1/A2（缓存命中）与 B1（lock 清缓存）为判据锚点"
              % (mut or "无"))

        cg.close() if hasattr(cg, "close") else None
    finally:
        MdCGSecure._invalidate_caches_on_key_change = _orig_inval
        shutil.rmtree(sb, ignore_errors=True)

    print("\n通过 %d / 失败 %d%s"
          % (PASS, FAIL, ("（变异=%s）" % mut) if mut else ""))
    if FAILS:
        for _f in FAILS:
            print(" - 红：%s" % _f)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
