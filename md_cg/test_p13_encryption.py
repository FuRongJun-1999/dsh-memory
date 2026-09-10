# -*- coding: utf-8 -*-
"""P13：用户私有内容端到端加密（`crypto.py`）。

覆盖：密码学内核（RFC 8439 官方向量）→ KDF / 主密钥 → DEK 信封与身份一致性
→ 节点正文封装（跨节点 / 跨身份挪用防护）→ MdCGSecure 端到端（加密范围 /
密钥即访问权 / 身份一致性识别）。
"""
import os
import shutil
import tempfile

from . import crypto, nodefile
from .crypto import (aead_decrypt, aead_encrypt, CryptoError, LockedError,
                     identity_fingerprint, is_encrypted, load_master_key,
                     open_node, provision_dek, seal_node, unwrap_dek)
from .mdcos import MdCGSecure
from .security import Principal

PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}" + (f"  · {detail}" if detail else ""))
    else:
        FAIL += 1
        print(f"  [FAIL] {name}" + (f"  · {detail}" if detail else ""))


def hx(s):
    return bytes.fromhex(s.replace(" ", "").replace("\n", ""))


def main():
    # ---------- A. 密码学内核（RFC 8439 官方测试向量）----------
    print("\n[A] ChaCha20-Poly1305 内核（RFC 8439 官方向量）")
    key = hx("808182838485868788898a8b8c8d8e8f"
             "909192939495969798999a9b9c9d9e9f")
    nonce = hx("070000004041424344454647")
    aad = hx("50515253c0c1c2c3c4c5c6c7")
    pt = (b"Ladies and Gentlemen of the class of '99: If I could offer "
          b"you only one tip for the future, sunscreen would be it.")
    ct = hx("d31a8d34648e60db7b86afbc53ef7ec2"
            "a4aded51296e08fea9e2b5a736ee62d6"
            "3dbea45e8ca9671282fafb69da92728b"
            "1a71de0a9e060b2905d6a5b67ecd3b36"
            "92ddbd7f2d778b8c9803aee328091b58"
            "fab324e4fad675945585808b4831d7bc"
            "3ff4def08e4b7a9de576d26586cec64b"
            "6116")
    tag = hx("1ae10b594f09e26a7e902ecbd0600691")
    c2, t2 = aead_encrypt(key, nonce, pt, aad)
    check("A1 AEAD 加密匹配 RFC 8439 §2.8.2 密文", c2 == ct, f"len={len(c2)}")
    check("A2 AEAD 标签匹配 RFC 8439 §2.8.2", t2 == tag, t2.hex())
    check("A3 AEAD 解密回环", aead_decrypt(key, nonce, c2, t2, aad) == pt)

    bad = bytearray(c2)
    bad[0] ^= 1
    try:
        aead_decrypt(key, nonce, bytes(bad), t2, aad)
        check("A4 篡改密文 → 拒绝", False)
    except CryptoError:
        check("A4 篡改密文 → 拒绝", True)
    try:
        aead_decrypt(key, nonce, c2, t2, aad + b"x")
        check("A5 AAD 不符 → 拒绝", False)
    except CryptoError:
        check("A5 AAD 不符 → 拒绝", True)

    pkey = hx("85d6be7857556d337f4452fe42d506a8"
              "0103808afb0db2fd4abff6af4149f51b")
    check("A6 Poly1305 匹配 RFC 8439 §2.5.2",
          crypto._poly1305(pkey, b"Cryptographic Forum Research Group")
          == hx("a8061dc1305136c6c22b8baf0c0127a9"))

    # ---------- B. KDF / 主密钥 ----------
    print("\n[B] KDF / 主密钥（KEK）")
    s1 = crypto.scrypt_kek("passphrase", b"saltsalt")
    check("B1 scrypt 确定性且 32 字节",
          s1 == crypto.scrypt_kek("passphrase", b"saltsalt") and len(s1) == 32)
    check("B2 不同盐 → 不同密钥",
          crypto.scrypt_kek("passphrase", b"othersalt") != s1)

    tmp = tempfile.mkdtemp(prefix="mdcg_p13b_")
    try:
        mf = os.path.join(tmp, "master.key")
        k1 = load_master_key(master_file=mf, env_var="MDCG_TEST_KEY_NONE")
        check("B3 主密钥文件自动生成 32B", os.path.exists(mf) and len(k1) == 32)
        check("B4 再次读取一致",
              load_master_key(master_file=mf, env_var="MDCG_TEST_KEY_NONE") == k1)
        os.environ["MDCG_TEST_KEY_HEX"] = k1.hex()
        check("B5 环境变量 hex 优先",
              load_master_key(master_file=os.path.join(tmp, "nope"),
                              env_var="MDCG_TEST_KEY_HEX") == k1)
        os.environ["MDCG_TEST_KEY_B64"] = crypto._b64e(k1)
        check("B6 环境变量 base64 支持",
              load_master_key(master_file=os.path.join(tmp, "nope"),
                              env_var="MDCG_TEST_KEY_B64") == k1)
        del os.environ["MDCG_TEST_KEY_HEX"], os.environ["MDCG_TEST_KEY_B64"]
        check("B7 无来源且 create=False → None",
              load_master_key(master_file=os.path.join(tmp, "none"),
                              env_var="MDCG_TEST_KEY_NONE", create=False) is None)
        check("B8 KEK 指纹稳定且不泄露密钥",
              crypto.kek_fingerprint(k1) == crypto.kek_fingerprint(k1)
              and k1.hex() not in crypto.kek_fingerprint(k1))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ---------- C. DEK 信封 / 身份一致性 ----------
    print("\n[C] DEK 信封 + 身份一致性识别")
    root = tempfile.mkdtemp(prefix="mdcg_p13c_")
    try:
        kek = os.urandom(32)
        dek = provision_dek(root, kek, "t1", "alice", clearance="private")
        check("C1 DEK 32 字节", len(dek) == 32)
        check("C2 同身份取回同一 DEK",
              unwrap_dek(root, kek, "t1", "alice") == dek)
        with open(crypto.keys_path(root), encoding="utf-8") as f:
            raw = f.read()
        check("C3 信封文件不落明文密钥", dek.hex() not in raw)
        try:
            provision_dek(root, None, "t1", "bob")
            check("C4 无 KEK → 拒绝签发", False)
        except LockedError:
            check("C4 无 KEK → 拒绝签发", True)
        try:
            unwrap_dek(root, kek, "t1", "bob")
            check("C5 身份不符（actor）→ 拒绝", False)
        except LockedError:
            check("C5 身份不符（actor）→ 拒绝", True)
        try:
            unwrap_dek(root, kek, "t2", "alice")
            check("C6 身份不符（tenant）→ 拒绝", False)
        except LockedError:
            check("C6 身份不符（tenant）→ 拒绝", True)
        try:
            unwrap_dek(root, os.urandom(32), "t1", "alice")
            check("C7 KEK 不对 → 拒绝", False)
        except LockedError:
            check("C7 KEK 不对 → 拒绝", True)
        check("C8 身份指纹不含明文身份",
              "alice" not in identity_fingerprint("t1", "alice"))
        check("C9 信封清单可审计",
              crypto.envelopes(root)[0]["actor"] == "alice")
        d2 = crypto.rotate_dek(root, kek, "t1", "alice")
        check("C10 rotate 换新密钥",
              d2 != dek and unwrap_dek(root, kek, "t1", "alice") == d2)
    finally:
        shutil.rmtree(root, ignore_errors=True)

    # ---------- D. 节点正文封装 ----------
    print("\n[D] 节点正文封装（跨节点 / 跨身份挪用防护）")
    root = tempfile.mkdtemp(prefix="mdcg_p13d_")
    try:
        kek = os.urandom(32)
        dek = provision_dek(root, kek, "t1", "alice")
        text = "用户私有笔记：家庭住址与联系方式……"
        blob = seal_node(text, dek, "n1", "t1", "alice")
        check("D1 密文标记块可识别", is_encrypted(blob))
        check("D2 密文不含明文", text not in blob)
        check("D3 解密回环", open_node(blob, dek, "n1", "t1", "alice") == text)
        try:
            open_node(blob, dek, "n2", "t1", "alice")
            check("D4 跨节点挪用 → 拒绝", False)
        except CryptoError:
            check("D4 跨节点挪用 → 拒绝", True)
        dek_b = provision_dek(root, kek, "t1", "bob")
        try:
            open_node(blob, dek_b, "n1", "t1", "bob")
            check("D5 跨身份密钥 → 拒绝", False)
        except CryptoError:
            check("D5 跨身份密钥 → 拒绝", True)
        check("D6 明文原样返回",
              open_node("普通内容", dek, "n1", "t1", "alice") == "普通内容")
        check("D7 每次加密 nonce 不同（同明文密文不同）",
              seal_node("same", dek, "n1", "t1", "alice")
              != seal_node("same", dek, "n1", "t1", "alice"))
        big = "长文本" * 3000
        check("D8 跨块（>64B 密钥流）正确",
              open_node(seal_node(big, dek, "n1", "t1", "alice"),
                        dek, "n1", "t1", "alice") == big)
    finally:
        shutil.rmtree(root, ignore_errors=True)

    # ---------- E. MdCGSecure 端到端 ----------
    print("\n[E] MdCGSecure 端到端（私有加密范围 + 密钥即访问权 + 身份一致性）")
    root = tempfile.mkdtemp(prefix="mdcg_p13e_")
    try:
        kek = os.urandom(32)
        secret = "银行卡尾号 8888，仅本人可见"
        public = "公开知识：Python 用 PEP8"
        body = "# 功能名：测试\n# 执行：{}\n\n{}\n"
        owner = Principal(tenant="t1", actor="alice", clearance="private",
                          can_write=True, can_admin=True)
        cg = MdCGSecure(root, principal=owner, master_key=kek)
        cg.add("priv1", body.format(secret, secret), sensitivity="private")
        cg.add("pub1", body.format(public, public), sensitivity="public")

        with open(os.path.join(root, "knowledge/orphan/priv1.md"),
                  encoding="utf-8") as f:
            raw_priv = f.read()
        with open(os.path.join(root, "knowledge/orphan/pub1.md"),
                  encoding="utf-8") as f:
            raw_pub = f.read()
        _, c_priv = nodefile.loads(raw_priv)
        _, c_pub = nodefile.loads(raw_pub)
        check("E1 私有正文落盘为密文", is_encrypted(c_priv))
        check("E2 私有节点文件不含明文", secret not in raw_priv)
        check("E3 公开正文保持明文", public in c_pub)
        check("E4 同身份可解密读回",
              secret in (cg.get("priv1") or {}).get("content", ""))

        same = MdCGSecure(root, principal=owner, master_key=kek)
        check("E5 同身份重开实例可读",
              secret in (same.get("priv1") or {}).get("content", ""))
        other = MdCGSecure(root, master_key=kek, principal=Principal(
            tenant="t1", actor="bob", clearance="private", can_write=True))
        check("E6 同租户不同 actor 不可读（身份一致性）",
              other.get("priv1") is None)
        outsider = MdCGSecure(root, master_key=kek, principal=Principal(
            tenant="t2", actor="alice", clearance="private", can_write=True))
        check("E7 不同租户不可读", outsider.get("priv1") is None)
        web = MdCGSecure(root, master_key=kek, principal=Principal(
            tenant="t1", actor="web", clearance="public"))
        check("E8 低密级读隔离", web.get("priv1") is None)
        same.lock()
        check("E9 无密钥 fail-closed", same.get("priv1") is None)
        check("E10 payload-free 审计留痕",
              os.path.exists(os.path.join(root, "_crypto.jsonl")))
    finally:
        shutil.rmtree(root, ignore_errors=True)

    print(f"\n==== P13 结果：{PASS} 通过 / {FAIL} 失败 ====")
    return FAIL


if __name__ == "__main__":
    import sys
    sys.exit(1 if main() else 0)
