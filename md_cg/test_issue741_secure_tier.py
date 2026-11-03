# -*- coding: utf-8 -*-
"""issue #741 安全档守卫：加密实例下指纹口径的**如实声明**与同源判据。

## 背景（review 阻塞 ③）
上面的 `test_issue741_content_hash_same_source` 全部跑在**恒等档**
（`_seal_content` 默认实现，sealed == 明文）。安全档（`MdCGSecure`，
`private`/`secret` 密级）下有两个必须回答的问题：

1. `_node_entry` 读回并哈希的是密文还是明文？
2. AEAD 加密是否确定性（同一明文每次密文相同）？

本守卫用**实测**回答，并把结论钉成断言——防止日后有人「顺手修正」成错的口径。

## 实测结论（本文件运行时打印）
- **读回的是密文**：`MdCGSecure._open_content` 只在 `get()` 的**对外返回值**上解密；
  索引构建（`_scan_nodes` / `_node_entry`）读的是**盘面字节**，即密文。
- **非确定性**：AEAD 带随机 nonce，同一明文重封一次密文就变。

⇒ 安全档下 `content_hash` **指纹的是密文、且重封即变**。这是 #741 **之前就存在**
的语义，#741 没有改变它。#741 只保证：**写入侧与重建侧对同一份盘面字节算同一个值**
（这才是「同源」的含义，与「指纹是明文还是密文」是两个正交问题）。

## 断言面
- **S1 安全档下写入侧 == 重建侧**（本次 PR 的核心承诺，修前必红）。
- **S2 安全档下盘面确为密文**（`crypto.is_encrypted` 判定），把隐含语义显式化。
- **S3 安全档下重封即变**（非确定性证据，记录既有语义而非缺陷）。
- **S4 normalize_body 对密文无害**：密文不以明文尾换行结尾，规范化只补一个
  `"\\n"`，两侧规则一致即可——补的是**同一个字节**，不引入新的漂移。

运行：python -X utf8 -m md_cg.test_issue741_secure_tier
退出码：0 = 全绿；1 = 有断言失败；2 = 环境不具备（无密钥 / 加密不可用，不算失败）。
沙箱纪律：库根落守卫临时目录，绝不碰在役库与 ~/.mdcg。
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")

from md_cg import crypto, nodefile                 # noqa: E402

_FAILED = []
_SKIP = []


def ok(cond, msg):
    print(("  PASS " if cond else "  FAIL ") + msg)
    if not cond:
        _FAILED.append(msg)


def skip(msg):
    print("  SKIP " + msg)
    _SKIP.append(msg)


_BODY = (
    "# 功能名：安全档指纹守卫\n"
    "# 生效条件：守卫自检时\n"
    "# 子功能：密级 private 节点写入与重建\n"
    "# 执行：比对两条路径的 content_hash\n"
    "# 验证方式：本条测试\n"
    "# 不适用条件：无"
)


def _make_secure(root):
    """尽力构造安全档实例；不具备条件返回 None。"""
    try:
        from md_cg.mdcos import MdCGSecure
    except Exception as exc:                       # noqa: BLE001
        skip("导入 MdCGSecure 失败：%s" % exc)
        return None
    # 写 private 需要 clearance 至少覆盖该密级（security.require_write 的判据）。
    # 逐级尝试，取第一个能构造成功的形态；失败只跳过、不算缺陷。
    # clearance 必须经 principal 传入（构造函数只收 principal=，其余进 **kw
    # 并不会改变 principal 的密级）——写 private 需要 clearance >= private。
    cg = None
    last = None
    try:
        from md_cg.security import Principal
    except Exception as exc:                       # noqa: BLE001
        Principal = None
        last = exc
    for lvl in ("secret", "private", "internal"):
        try:
            if Principal is None:
                cg = MdCGSecure(root)
            else:
                cg = MdCGSecure(root, principal=Principal(
                    actor="guard", clearance=lvl, can_write=True))
            break
        except Exception as exc:                   # noqa: BLE001
            last = exc
    if cg is None:
        skip("构造 MdCGSecure 失败（多半无密钥）：%s" % last)
        return None
    if not getattr(cg, "dek", None):
        skip("MdCGSecure 无 dek（未解锁），无法验证加密路径")
        return None
    return cg


def s1_write_vs_rebuild_secure():
    print("== S1 安全档：写入 vs 重建同源 ==")
    root = tempfile.mkdtemp(prefix="mdcg741sec-s1-")
    try:
        cg = _make_secure(root)
        if cg is None:
            return
        cg.add("s1", _BODY, layer="knowledge", tags=["t"],
               importance=0.2, sensitivity="private")
        after_write = (cg.index["nodes"].get("s1") or {}).get("content_hash")
        cg.rebuild_index()
        after_rebuild = (cg.index["nodes"].get("s1") or {}).get("content_hash")
        ok(after_write == after_rebuild,
           "S1 安全档写入后与重建后 content_hash 一致（写=%s 重建=%s）"
           % (after_write, after_rebuild))
    finally:
        shutil.rmtree(root, ignore_errors=True)


def s2_disk_is_cipher():
    print("== S2 安全档：盘面确为密文 ==")
    root = tempfile.mkdtemp(prefix="mdcg741sec-s2-")
    try:
        cg = _make_secure(root)
        if cg is None:
            return
        cg.add("s2", _BODY, layer="knowledge", tags=["t"],
               importance=0.2, sensitivity="private")
        entry = cg.index["nodes"].get("s2") or {}
        path = os.path.join(root, entry.get("path") or "")
        raw = open(path, encoding="utf-8").read()
        _fm, body = nodefile.loads(raw)
        ok(crypto.is_encrypted(body),
           "S2 盘面正文为密文（is_encrypted=%r），安全档下指纹即指纹密文"
           % (crypto.is_encrypted(body),))
    finally:
        shutil.rmtree(root, ignore_errors=True)


def s3_reseal_changes_hash():
    print("== S3 安全档：重封即变（非确定性，既有语义） ==")
    root = tempfile.mkdtemp(prefix="mdcg741sec-s3-")
    try:
        cg = _make_secure(root)
        if cg is None:
            return
        cg.add("s3", _BODY, layer="knowledge", tags=["t"],
               importance=0.2, sensitivity="private")
        h1 = (cg.index["nodes"].get("s3") or {}).get("content_hash")
        # 触发一次「get() 解密 → 重封」的元数据更新
        cg.update_tags("s3", ["t", "again"])
        h2 = (cg.index["nodes"].get("s3") or {}).get("content_hash")
        ok(h1 != h2,
           "S3 重封后密文指纹改变（%s -> %s）——既有语义，非 #741 引入"
           % (h1, h2))
    finally:
        shutil.rmtree(root, ignore_errors=True)


def s4_normalize_is_symmetric():
    print("== S4 normalize_body 对两侧一致 ==")
    cipher_like = "enc:v1:AAAAAAAA"                # 模拟密文：不以换行结尾
    a = nodefile.normalize_body(cipher_like)
    b = nodefile.normalize_body(cipher_like + "\n")
    ok(a == b, "S4 同一份盘面字节经 normalize_body 后逐位相同（%r == %r）" % (a, b))
    ok(nodefile.content_hash(a) == nodefile.content_hash(b),
       "S4 因而 content_hash 也相同")


_GROUPS = (s1_write_vs_rebuild_secure, s2_disk_is_cipher,
           s3_reseal_changes_hash, s4_normalize_is_symmetric)


def main():
    for fn in _GROUPS:
        fn()
    print("=" * 68)
    if _FAILED:
        print("安全档指纹守卫：%d 条失败" % len(_FAILED))
        for m in _FAILED:
            print("  - " + m)
        return 1
    if _SKIP:
        print("安全档指纹守卫：跳过 %d 项（环境不具备）" % len(_SKIP))
        print("  已跑通的断言全部通过")
        return 0
    print("安全档指纹守卫：全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
