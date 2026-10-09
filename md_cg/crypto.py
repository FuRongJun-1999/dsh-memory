# -*- coding: utf-8 -*-
"""用户私有内容的端到端加密（at-rest）——密钥即访问权 + 身份一致性识别。

设计边界（诚实标注）
--------------------
· **加密范围**：仅 `sensitivity >= private` 的节点**正文**（private / secret）。
  public / internal 保持明文——它们是可公开知识，加密只增加成本。
· **元数据明文**：frontmatter（layer / tags / condition_space / importance /
  sensitivity）不加密。原因：条件路由与召回依赖元数据，加密它等于让记忆 OS
  失能。代价：元数据本身可被读出——这是**明确取舍**，不是疏漏。
· **密文不参与全文索引**：正文加密后，明文查询词不会命中密文。因此无密钥者
  只能走元数据路（知道「存在一条 private 记忆」，读不到内容）。
· **威胁模型**：防磁盘 / 备份 / 仓库泄露、防无密钥者读取。
  **不防**本地内存取证与侧信道（纯 Python 实现的固有限制，不虚报）。

密钥层级
--------
    KEK（主密钥，仓库外）── wrap ──> DEK（每租户数据密钥，存 _keys.json）
                                      │
                                      └── AEAD 加密 ──> 节点正文

· KEK 来源（按优先级）：
    ① 环境变量 `MDCG_MASTER_KEY`（64 位 hex 或 base64）
    ② 主密钥文件 `~/.mdcg/master.key`（首次自动生成，0600）
· KEK 不落仓库；DEK 被 KEK 包裹后存租户根目录，单独拿走 `_keys.json` 无法解密。
· **身份一致性识别**：DEK 信封绑定 `(tenant, actor, clearance)`，且节点密文把
  `(node_id, tenant, actor)` 作为 AEAD 的 AAD。因此
    ① 换了身份（actor / tenant 不符）→ 解不开；
    ② 把密文拷贝到另一个节点 → 校验失败。
  即「密钥 + 身份」双因子，缺一不可。
· **跨身份可在解密前判定**（B1，2026-10-10）：密文块另携**非敏感**指纹
  `enc_id_fp`（= `identity_fingerprint(tenant, actor)`，与 `_keys.json` 信封同款，
  16 位 hex、不泄露身份原文），读方零解密即可判「是否跨身份」——设计内隔离与
  「密文被篡改」不再混进同一条审计文案（存量旧格式无该段，读方走旧路径）。

密码学实现
----------
ChaCha20-Poly1305（RFC 8439）**纯标准库实现**（对齐 D-005「核心零外部依赖」）。
正确性由 RFC 8439 §2.8.2 官方测试向量验证（见 `test_p13_encryption.py`）。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import struct
import sys
import time

from .datapath import aux_root
from .fsutil import FileLock
from .rotate import Rotator

# ---- 常量 ----------------------------------------------------------------

ENVELOPE_VERSION = 1
ALG = "chacha20poly1305"
NONCE_LEN = 12
KEY_LEN = 32
TAG_LEN = 16

ENC_PREFIX = "<!-- mdcg-enc:v1:"
ENC_SUFFIX = " -->"

# 需要加密的密级（用户私有内容）
ENCRYPTED_LEVELS = ("private", "secret")

KEYS_FILE = "_keys.json"
AUDIT_FILE = "_crypto.jsonl"
MASTER_ENV = "MDCG_MASTER_KEY"
MASTER_FILE = os.path.join(aux_root(), "master.key")

# ---- 审计分片轮转（A2，2026-10-10）-------------------------------------
# `_crypto.jsonl` 此前「直接 append + except OSError: pass」——无阈值/无归档/无
# 索引/无淘汰/无体检/失败静默（在役库实测 682 MB / 302 万条无界增长）。现与
# `_audit.jsonl` 共用唯一实现 `md_cg.rotate.Rotator`（参数化共享件）。
AUDIT_BASENAME = "_crypto"
CRYPTO_ARCHIVE = "_crypto_archive"
CRYPTO_INDEX = "_index.json"
CRYPTO_ROTATE_BYTES = 64 << 20     # 活动文件轮转阈值（≤0 关闭，退回无上界）
CRYPTO_KEEP_SHARDS = 8             # 归档分片保留数（≤0 不淘汰；淘汰必留痕）
CRYPTO_PROBE_EVERY = 32            # 每 N 次写入探测一次大小（写入税摊到 1/N）
CRYPTO_COUNT_MAX_BYTES = 64 << 20  # 超此规模的分片只给量级（不付 O(n) 全量计数）

#: 每 root 一个巡转器（进程内缓存）：分片索引缓存据此在重复体检间保持 O(1)。
_ROTATORS = {}

#: 审计写失败告警上限（进程内）：N126 点名「审计写入 best-effort 静默吞错」——
#: 通道坏死时**不再静默**，但告警有界（防刷屏），计数面恒完整。
_AUDIT_WRITE_FAILURES = 0
_AUDIT_WRITE_WARN_CAP = 16

# scrypt 参数（交互式场景：N=2^14 / r=8 / p=1，约 16MB 内存）
SCRYPT_N, SCRYPT_R, SCRYPT_P, SCRYPT_DKLEN = 2 ** 14, 8, 1, 32


# 生效条件：不适用（无必需形参与模块级常量）
class CryptoError(Exception):
    """加解密 / 密钥相关错误。"""


# 生效条件：不适用（无必需形参与模块级常量）
class LockedError(CryptoError):
    """无密钥或身份不符——内容不可读（fail-closed，绝不降级为明文）。"""


# ---- ChaCha20（RFC 8439 §2.3）--------------------------------------------

# 生效条件：x、n 为入参，返回 ((x << n) & 0xFFFFFFFF) | (x >> (32 - n))；源码未校验 x、n 类型或范围。
def _rotl32(x, n):
    return ((x << n) & 0xFFFFFFFF) | (x >> (32 - n))


# 生效条件：s、a、b、c、d 为入参，依次读写 s[a]、s[b]、s[c]、s[d] 并按源码顺序做加法、异或、_rotl32 更新；源码未校验 s 元素类型或索引范围。
def _quarter_round(s, a, b, c, d):
    s[a] = (s[a] + s[b]) & 0xFFFFFFFF
    s[d] = _rotl32(s[d] ^ s[a], 16)
    s[c] = (s[c] + s[d]) & 0xFFFFFFFF
    s[b] = _rotl32(s[b] ^ s[c], 12)
    s[a] = (s[a] + s[b]) & 0xFFFFFFFF
    s[d] = _rotl32(s[d] ^ s[a], 8)
    s[c] = (s[c] + s[d]) & 0xFFFFFFFF
    s[b] = _rotl32(s[b] ^ s[c], 7)


# 生效条件：key、counter、nonce 为入参，按 const + key 解包 + counter 低 32 位 + nonce 解包构造 state，执行 10 次双轮后返回 16 个 32 位小端打包的 64 字节块。
def _chacha_block(key, counter, nonce):
    """生成 64 字节密钥流块。"""
    const = b"expand 32-byte k"
    st = (list(struct.unpack("<4I", const))
          + list(struct.unpack("<8I", key))
          + [counter & 0xFFFFFFFF]
          + list(struct.unpack("<3I", nonce)))
    w = list(st)
    for _ in range(10):                      # 20 轮 = 10 次双轮
        _quarter_round(w, 0, 4, 8, 12)
        _quarter_round(w, 1, 5, 9, 13)
        _quarter_round(w, 2, 6, 10, 14)
        _quarter_round(w, 3, 7, 11, 15)
        _quarter_round(w, 0, 5, 10, 15)
        _quarter_round(w, 1, 6, 11, 12)
        _quarter_round(w, 2, 7, 8, 13)
        _quarter_round(w, 3, 4, 9, 14)
    return struct.pack("<16I", *[(w[i] + st[i]) & 0xFFFFFFFF for i in range(16)])


# 生效条件：key、counter、nonce、data 为入参，对 data 从 0 到 len(data) 步长 64 分块，每块用 _chacha_block(key, counter + i//64, nonce) 生成密钥流并逐字节异或，返回等长 bytes；data 为空时返回 b""。
def _chacha20_xor(key, counter, nonce, data):
    out = bytearray(len(data))
    for i in range(0, len(data), 64):
        ks = _chacha_block(key, counter + i // 64, nonce)
        for j, b in enumerate(data[i:i + 64]):
            out[i + j] = b ^ ks[j]
    return bytes(out)


# ---- Poly1305（RFC 8439 §2.5）-------------------------------------------

# 生效条件：key、msg 为入参，取 key[:16] 掩码得 r、key[16:] 得 s，msg 按 16 字节分块加 b"\x01" 累加，返回 (acc + s) 低 128 位的 16 字节小端；源码未校验 key 长度或 msg 类型。
def _poly1305(key, msg):
    r = int.from_bytes(key[:16], "little") & 0x0FFFFFFC0FFFFFFC0FFFFFFC0FFFFFFF
    s = int.from_bytes(key[16:], "little")
    p = (1 << 130) - 5
    acc = 0
    for i in range(0, len(msg), 16):
        n = int.from_bytes(msg[i:i + 16] + b"\x01", "little")
        acc = ((acc + n) * r) % p
    return ((acc + s) & ((1 << 128) - 1)).to_bytes(16, "little")


# 生效条件：b 为入参，返回 b"\x00" * ((16 - len(b) % 16) % 16)；b 长度为 16 的倍数（含空）时返回 b""。
def _pad16(b):
    return b"\x00" * ((16 - len(b) % 16) % 16)


# 生效条件：otk、aad、ct 为入参，返回 _poly1305(otk, aad + _pad16(aad) + ct + _pad16(ct) + struct.pack("<Q", len(aad)) + struct.pack("<Q", len(ct))) 的结果。
def _aead_mac(otk, aad, ct):
    return _poly1305(otk, aad + _pad16(aad) + ct + _pad16(ct)
                     + struct.pack("<Q", len(aad)) + struct.pack("<Q", len(ct)))


# ---- AEAD：ChaCha20-Poly1305（RFC 8439 §2.8）-----------------------------

# 生效条件：key、nonce、plaintext、aad=b"" 为入参；len(key) != KEY_LEN 或 len(nonce) != NONCE_LEN 时抛 CryptoError；否则以 _chacha_block(key,0,nonce)[:32] 为 otk、_chacha20_xor(key,1,nonce,plaintext) 为 ct，返回 (ct, _aead_mac(otk, aad, ct))。
def aead_encrypt(key, nonce, plaintext, aad=b""):
    """返回 (ciphertext, tag)。key=32B / nonce=12B。"""
    if len(key) != KEY_LEN:
        raise CryptoError(f"密钥长度须为 {KEY_LEN} 字节")
    if len(nonce) != NONCE_LEN:
        raise CryptoError(f"nonce 长度须为 {NONCE_LEN} 字节")
    otk = _chacha_block(key, 0, nonce)[:32]
    ct = _chacha20_xor(key, 1, nonce, plaintext)
    return ct, _aead_mac(otk, aad, ct)


# 生效条件：key、nonce、ct、tag、aad=b"" 为入参；len(key) != KEY_LEN 或 len(nonce) != NONCE_LEN 时抛 CryptoError；否则算 otk，若 hmac.compare_digest(_aead_mac(otk,aad,ct), tag) 为假抛 CryptoError，为真返回 _chacha20_xor(key,1,nonce,ct)。
def aead_decrypt(key, nonce, ct, tag, aad=b""):
    """验签后解密；失败抛 CryptoError（不返回任何明文）。"""
    if len(key) != KEY_LEN:
        raise CryptoError(f"密钥长度须为 {KEY_LEN} 字节")
    if len(nonce) != NONCE_LEN:
        raise CryptoError(f"nonce 长度须为 {NONCE_LEN} 字节")
    otk = _chacha_block(key, 0, nonce)[:32]
    if not hmac.compare_digest(_aead_mac(otk, aad, ct), tag):
        raise CryptoError("认证标签校验失败（密钥/身份/节点不匹配或密文被篡改）")
    return _chacha20_xor(key, 1, nonce, ct)


# ---- KDF / 主密钥（KEK）--------------------------------------------------

# 生效条件：b 为入参，返回 base64.b64encode(b).decode("ascii") 得到的字符串。
def _b64e(b):
    return base64.b64encode(b).decode("ascii")


# 生效条件：s 为入参，返回 base64.b64decode(str(s).encode("ascii")) 的结果；默认 validate=False，非字母字符被丢弃，可能返回空字节或部分数据，源码未校验 s 合法性。
def _b64d(s):
    return base64.b64decode(str(s).encode("ascii"))


# 生效条件：passphrase、salt 为入参，将 str(passphrase).encode("utf-8") 作为口令、salt 作为盐，按 SCRYPT_N、SCRYPT_R、SCRYPT_P、SCRYPT_DKLEN 调 hashlib.scrypt 返回 KEK。
def scrypt_kek(passphrase, salt):
    """口令 → KEK（scrypt）。用于「人类口令」场景，避免直接存放原始密钥。"""
    return hashlib.scrypt(str(passphrase).encode("utf-8"), salt=salt,
                          n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=SCRYPT_DKLEN)


# 生效条件：master_file=None、env_var=MASTER_ENV、create=True 为可选入参；从 os.environ.get(env_var) 读取并 strip，若 raw 非空则长度 64 走 bytes.fromhex、否则 _b64d，解码失败抛 CryptoError；否则 path = master_file or MASTER_FILE，若 os.path.exists(path) 为真则读取并 _b64d；若 create 为假返回 None；否则生成 KEY_LEN 随机密钥写入 path 并返回 key。
def load_master_key(master_file=None, env_var=MASTER_ENV, create=True):
    """KEK 来源：环境变量 → 主密钥文件（可选自动生成）；都没有返回 None。"""
    raw = (os.environ.get(env_var) or "").strip()
    if raw:
        try:
            return bytes.fromhex(raw) if len(raw) == 64 else _b64d(raw)
        except ValueError as e:
            raise CryptoError(f"环境变量 {env_var} 不是合法 hex / base64 主密钥") from e
    path = master_file or MASTER_FILE
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return _b64d(f.read().strip())
    if not create:
        return None
    key = secrets.token_bytes(KEY_LEN)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(_b64e(key))
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return key


# 生效条件：kek 为入参，返回 hashlib.sha256(b"mdcg-kek|" + kek).hexdigest()[:16]；源码未校验 kek 类型。
def kek_fingerprint(kek):
    return hashlib.sha256(b"mdcg-kek|" + kek).hexdigest()[:16]


# ---- 身份一致性（AAD 绑定）----------------------------------------------

# 生效条件：tenant、actor 为入参，返回 hashlib.sha256(f"mdcg-id|v{ENVELOPE_VERSION}|{tenant}|{actor}".encode("utf-8")).hexdigest()[:16]；ENVELOPE_VERSION 为模块级常量。
def identity_fingerprint(tenant, actor):
    """身份指纹：tenant + actor 的确定性摘要（不泄露原文）。"""
    raw = f"mdcg-id|v{ENVELOPE_VERSION}|{tenant}|{actor}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:16]


# 生效条件：tenant、actor 为入参，返回 f"mdcg-dek|v{ENVELOPE_VERSION}|{tenant}|{actor}".encode("utf-8")。
def _dek_aad(tenant, actor):
    return f"mdcg-dek|v{ENVELOPE_VERSION}|{tenant}|{actor}".encode("utf-8")


# 生效条件：node_id、tenant、actor 为入参，返回 f"mdcg-node|v{ENVELOPE_VERSION}|{tenant}|{actor}|{node_id}".encode("utf-8")。
def _node_aad(node_id, tenant, actor):
    return (f"mdcg-node|v{ENVELOPE_VERSION}|{tenant}|{actor}|{node_id}"
            .encode("utf-8"))


# ---- 密钥库（DEK 信封）---------------------------------------------------

# 生效条件：root 为入参，返回 os.path.join(root, KEYS_FILE)；KEYS_FILE 为模块级常量。
def keys_path(root):
    return os.path.join(root, KEYS_FILE)


# 生效条件：root 为入参；keys_path(root) 不存在时返回 {"v": ENVELOPE_VERSION, "alg": ALG, "envelopes": {}}（缺文件=fresh install，零告警零标记）；否则尝试 json.load，结果为 dict 且 "envelopes" 为 dict 时原样返回；json 解析 ValueError、OSError、或顶层为 dict 但 "envelopes" 缺失/非 dict（版本漂移）时向 stderr 写「密钥库损坏/不可读」告警（N139，2026-09-27 第 5 轮：静默回落会让 provision_dek 据空表重签新 DEK 并经 _save_keys 整份覆盖写回，旧信封无痕抹除、旧密文永久不可解——告警必须开口）并返回带 load_error 标记的空结构；provision_dek 见 load_error 即 fail-closed 拒绝重签，unwrap_dek 照旧按无信封抛 LockedError（读面零闸变）。
def _load_keys(root):
    p = keys_path(root)
    if not os.path.exists(p):
        return {"v": ENVELOPE_VERSION, "alg": ALG, "envelopes": {}}
    err = None
    try:
        with open(p, "r", encoding="utf-8") as f:
            d = json.load(f)
        if isinstance(d, dict) and isinstance(d.get("envelopes"), dict):
            return d
        err = "顶层不是对象或 envelopes 非映射（版本漂移？）"
    except (ValueError, OSError) as e:
        err = f"{type(e).__name__}: {e}"
    sys.stderr.write(
        f"[mdcg-crypto] ⚠ 密钥库损坏/不可读（{err}）：{p}"
        f"——按回落口径返回空结构并置损坏标记（load_error）；签发/重写在"
        f"标记下拒绝（静默重签会无痕抹除旧信封，N139）。"
        f"请修复或恢复该文件后重试。\n")
    return {"v": ENVELOPE_VERSION, "alg": ALG, "envelopes": {},
            "load_error": err}


# 生效条件：root、data 为入参；先调 _load_keys 读盘面写前对账（N184）：盘面带 load_error 时抛 LockedError（N139 同闸延申到写点——解析不了的密钥库不得被整份覆盖），随后把盘面已有而 data["envelopes"] 没有的信封逐键并入（陈旧快照整份写回不得无痕抹除并发新增的他身份信封；键同时存在时以本次写回为准，rotate 语义不受影响），最后 json.dumps(data, ensure_ascii=False, indent=1) 由 atomic_write 写入 keys_path(root)。调用方须已持有 keys_path(root) 的 FileLock（provision_dek 持锁调用）；对账合并是防线纵深，兜底任何未持锁的陈旧快照写者。
def _save_keys(root, data):
    from .fsutil import atomic_write
    disk = _load_keys(root)
    if disk.get("load_error"):
        raise LockedError(
            f"密钥库损坏/不可读（{disk['load_error']}）：{keys_path(root)}"
            f"——写前对账发现盘面不可解析，拒绝整份覆盖（解析不了的信封"
            f"一概不能被写掉，N139/N184）。请先手工处理该文件。")
    env = data.setdefault("envelopes", {})
    for k, v in (disk.get("envelopes") or {}).items():
        if k not in env:
            env[k] = v
    atomic_write(keys_path(root),
                 json.dumps(data, ensure_ascii=False, indent=1))


# 生效条件：tenant、actor 为入参，返回 f"{tenant}|{actor}"。
def _envelope_key(tenant, actor):
    return f"{tenant}|{actor}"


# 生效条件：root、kek、tenant、actor、clearance="private"、rotate=False 为入参；若 kek 为假抛 LockedError；否则以 FileLock(keys_path(root), strict=True) 持跨进程写锁进入临界区（N184，2026-09-28 第 23 轮：读快照→签发→写回全程持锁，写者互斥——原子替换只防撕裂不防丢失更新，两写者按各自陈旧快照整份写回会无痕抹除对方信封；锁竞争超时经 TimeoutError 转 LockedError fail-closed，绝不无锁放行整份写回）；临界区内加载 keys，keys 带 load_error 损坏标记时抛 LockedError（N139：损坏/漂移回落下静默重签会经 _save_keys 整份覆盖写回并无痕抹除旧信封——旧密文永久不可解）；若 _envelope_key(tenant, actor) 已在 envelopes 中且 rotate 为假则返回 unwrap_dek(root, kek, tenant, actor, clearance)（临界区内互见 → 同身份并发 provision 幂等同 DEK）；否则生成新 DEK 与 nonce，用 aead_encrypt(kek, nonce, dek, _dek_aad(tenant, actor)) 包裹后写入 envelopes[k]，经 _save_keys 写前对账合并并发新增信封（N184 防线纵深）后保存，返回 dek。
def provision_dek(root, kek, tenant, actor, clearance="private", rotate=False):
    """为 (tenant, actor) 生成 / 取回 DEK，用 KEK 包裹后存入 `_keys.json`。

    rotate=True 强制换新密钥（旧密文需先迁移，见 `reencrypt_all`）。
    """
    if not kek:
        raise LockedError("无主密钥（KEK）：拒绝签发数据密钥")
    try:
        with FileLock(keys_path(root), timeout=10.0, strict=True):
            data = _load_keys(root)
            if data.get("load_error"):
                raise LockedError(
                    f"密钥库损坏/不可读（{data['load_error']}）：{keys_path(root)}"
                    f"——损坏标记下拒绝重签数据密钥（静默整份覆盖会无痕抹除旧信封，"
                    f"N139）。请修复或恢复 _keys.json 后重试；若有意重置，请先手工"
                    f"处理该文件（备份/移除）再重试。")
            data.setdefault("envelopes", {})
            k = _envelope_key(tenant, actor)
            if k in data["envelopes"] and not rotate:
                return unwrap_dek(root, kek, tenant, actor, clearance)
            dek = secrets.token_bytes(KEY_LEN)
            nonce = secrets.token_bytes(NONCE_LEN)
            ct, tag = aead_encrypt(kek, nonce, dek, _dek_aad(tenant, actor))
            data["envelopes"][k] = {
                "id_fp": identity_fingerprint(tenant, actor),
                "clearance": clearance,
                "nonce": _b64e(nonce), "ct": _b64e(ct + tag),
                "created_at": time.time(),
            }
            data["v"] = ENVELOPE_VERSION
            data["alg"] = ALG
            _save_keys(root, data)
            return dek
    except TimeoutError as e:
        raise LockedError(
            f"密钥库写锁（{keys_path(root)}.lock）竞争超时：并发 provision "
            f"未在限时内获得互斥——fail-closed 拒绝签发（无锁整份写回会无痕"
            f"抹除他身份信封，N184）。请稍后重试。") from e


# 生效条件：root、kek、tenant、actor、clearance=None 为入参；若 kek 为假抛 LockedError；否则取 _load_keys(root)["envelopes"] 中 _envelope_key(tenant, actor) 的信封，无则抛 LockedError；若 env["id_fp"] 不等于 identity_fingerprint(tenant, actor) 抛 LockedError；否则从 env["ct"] 解出 raw，按 TAG_LEN 切出 ct/tag，调 aead_decrypt；若 aead_decrypt 抛 CryptoError 则转抛 LockedError；clearance 形参默认 None 但源码未在条件中使用。
def unwrap_dek(root, kek, tenant, actor, clearance=None):
    """解出 DEK；身份指纹不符 / KEK 不对 / 无信封 → LockedError。"""
    if not kek:
        raise LockedError("无主密钥（KEK）：无法解开数据密钥")
    env = (_load_keys(root).get("envelopes") or {}).get(_envelope_key(tenant, actor))
    if not env:
        raise LockedError(f"无 {tenant}|{actor} 的密钥信封")
    if env.get("id_fp") != identity_fingerprint(tenant, actor):
        raise LockedError("身份指纹不符：密钥信封不属于当前身份")
    raw = _b64d(env["ct"])
    ct, tag = raw[:-TAG_LEN], raw[-TAG_LEN:]
    try:
        return aead_decrypt(kek, _b64d(env["nonce"]), ct, tag,
                            _dek_aad(tenant, actor))
    except CryptoError as e:
        raise LockedError(f"身份 / 主密钥不匹配：{e}") from e


# 生效条件：root、tenant、actor 为入参，返回 _envelope_key(tenant, actor) in (_load_keys(root).get("envelopes") or {}) 的布尔结果。
def has_envelope(root, tenant, actor):
    return _envelope_key(tenant, actor) in (
        _load_keys(root).get("envelopes") or {})


# 生效条件：root、kek、tenant、actor、clearance="private" 为入参，返回 provision_dek(root, kek, tenant, actor, clearance=clearance, rotate=True)。
def rotate_dek(root, kek, tenant, actor, clearance="private"):
    return provision_dek(root, kek, tenant, actor, clearance=clearance,
                         rotate=True)


# 生效条件：root 为入参，遍历 _load_keys(root).get("envelopes") or {} 的每项，按 "|" partition 出 tenant/actor，收集 id_fp、clearance、created_at 后返回列表；无信封时返回 []。
def envelopes(root):
    """信封清单（不含密钥材料）：供运维审计「谁被签发了密钥」。"""
    out = []
    for k, v in (_load_keys(root).get("envelopes") or {}).items():
        tenant, _, actor = k.partition("|")
        out.append({"tenant": tenant, "actor": actor,
                    "id_fp": v.get("id_fp"), "clearance": v.get("clearance"),
                    "created_at": v.get("created_at")})
    return out


# ---- 节点正文封装 --------------------------------------------------------

# 生效条件：content 为入参；bool(content) 为假（如空串或 None）时返回 False；否则返回 content.lstrip().startswith(ENC_PREFIX)。
def is_encrypted(content):
    return bool(content) and content.lstrip().startswith(ENC_PREFIX)


# 生效条件：content 为入参；非密文（is_encrypted 为假）时返回 None；密文块正文中不含 ":"（旧格式，仅 base64）时返回 None；否则返回 ":" 前的 enc_id_fp 字串（空串亦返回 None）。base64 标准字母表不含 ":"，故该分隔符无歧义；旧格式密文天然无此段 ⇒ 返回 None（调用方走旧路径）。
def enc_id_fp(content):
    """从密文标记块取出**非敏感**身份指纹 `enc_id_fp`（B1）。

    新格式：`<!-- mdcg-enc:v1:<enc_id_fp>:<base64(nonce+tag+ct)> -->`
    存量旧格式（无该段）返回 None —— 不需要迁移，读方走旧路径（新写逐步带上）。
    """
    if not is_encrypted(content):
        return None
    body = content.strip()[len(ENC_PREFIX):-len(ENC_SUFFIX)]
    if ":" not in body:
        return None
    return body.split(":", 1)[0] or None


# 生效条件：content、dek、node_id、tenant、actor 为入参，生成 NONCE_LEN 随机 nonce，将 str(content).encode("utf-8") 以 aead_encrypt(dek, nonce, ..., _node_aad(node_id, tenant, actor)) 加密，返回 f"{ENC_PREFIX}{enc_id_fp}:{_b64e(nonce + tag + ct)}{ENC_SUFFIX}"，其中 enc_id_fp=identity_fingerprint(tenant, actor)（非敏感 16 位 hex，随密文同行，读方零解密即可判跨身份）。
def seal_node(content, dek, node_id, tenant, actor):
    """明文 → 密文标记块（正文整体加密；frontmatter 不在此处处理）。

    A2/B1（2026-10-10）：密文块携带 `identity_fingerprint(tenant, actor)`（16 位
    hex，与 `_keys.json` 信封同款指纹）——它是**非敏感**标识（不泄露身份原文），
    使「跨身份读」在解密前可判（省掉无谓 MAC、并把真异常留给 open_failed）。
    """
    nonce = secrets.token_bytes(NONCE_LEN)
    ct, tag = aead_encrypt(dek, nonce, str(content).encode("utf-8"),
                           _node_aad(node_id, tenant, actor))
    return (f"{ENC_PREFIX}{identity_fingerprint(tenant, actor)}:"
            f"{_b64e(nonce + tag + ct)}{ENC_SUFFIX}")


# 生效条件：content、dek、node_id、tenant、actor 为入参；若 is_encrypted(content) 为假则原样返回 content；否则 strip 后切掉 ENC_PREFIX/ENC_SUFFIX，正文含 ":" 时丢弃其前的 enc_id_fp 段（新格式），base64 解出 raw，按 NONCE_LEN、TAG_LEN 切出 nonce/tag/ct，调 aead_decrypt(dek, nonce, ct, tag, _node_aad(node_id, tenant, actor)) 并 utf-8 解码返回；aead_decrypt 失败抛 CryptoError；旧格式（无 ":" 段）与新格式同一路径解密（向后兼容）。
def open_node(content, dek, node_id, tenant, actor):
    """密文标记块 → 明文；未加密原样返回；失败抛 CryptoError（兼容旧格式）。"""
    if not is_encrypted(content):
        return content
    body = content.strip()
    body = body[len(ENC_PREFIX):-len(ENC_SUFFIX)]
    if ":" in body:                        # 新格式：<enc_id_fp>:<b64>
        body = body.split(":", 1)[1]
    raw = _b64d(body)
    nonce = raw[:NONCE_LEN]
    tag = raw[NONCE_LEN:NONCE_LEN + TAG_LEN]
    ct = raw[NONCE_LEN + TAG_LEN:]
    return aead_decrypt(dek, nonce, ct, tag,
                        _node_aad(node_id, tenant, actor)).decode("utf-8")


# ---- 审计（payload-free）-------------------------------------------------

# 生效条件：root 为入参，按 root 取/建进程内缓存的 Rotator（basename=_crypto、archive=_crypto_archive、index=_index.json、lock=<root>/_crypto.rotate.lock），每次调用把模块级 CRYPTO_* 常量同步进实例（守卫可原地改阈值）后返回；同一 root 复用同一实例（分片索引缓存 ⇒ 重复体检 O(1)）。
def _rotator(root):
    key = os.path.abspath(root)
    r = _ROTATORS.get(key)
    if r is None:
        r = Rotator(root=root, basename=AUDIT_BASENAME,
                    archive_name=CRYPTO_ARCHIVE, index_name=CRYPTO_INDEX,
                    rotate_bytes=CRYPTO_ROTATE_BYTES,
                    keep_shards=CRYPTO_KEEP_SHARDS,
                    probe_every=CRYPTO_PROBE_EVERY,
                    count_max_bytes=CRYPTO_COUNT_MAX_BYTES,
                    mark_factory=_rotate_mark,
                    clock=lambda: time.time())
        _ROTATORS[key] = r
    r.rotate_bytes = CRYPTO_ROTATE_BYTES
    r.keep_shards = CRYPTO_KEEP_SHARDS
    r.probe_every = CRYPTO_PROBE_EVERY
    r.count_max_bytes = CRYPTO_COUNT_MAX_BYTES
    return r


# 生效条件：name（分片名）、size、events、pruned、reason 为入参，返回 crypto 协议形状的轮转自述记录（ts/op=crypto_rotate/node_id=分片名/bytes/events/pruned/reason/payload_free=True）。
def _rotate_mark(name, size, events, pruned, reason):
    return {"ts": time.time(), "op": "crypto_rotate", "node_id": name,
            "bytes": size, "events": events, "pruned": pruned,
            "reason": reason, "payload_free": True}


# 生效条件：root、exc 为入参，无条件把 _AUDIT_WRITE_FAILURES 累加 1；累计不超过 _AUDIT_WRITE_WARN_CAP 时向 stderr 写一行含库根与异常类型的告警（N126：不再静默吞错）；返回是否写了告警行。
def _note_audit_write_failure(root, exc):
    """登记一次审计写失败 + stderr 告警（N126 口径：容忍 ≠ 静默）。

    审计仍是 best-effort（写失败不阻断业务），但**通道坏死不得无痕**——磁盘满 /
    文件被独占 / 权限回收时，运维必须有可见线索（有界告警，防刷屏）。
    """
    global _AUDIT_WRITE_FAILURES
    _AUDIT_WRITE_FAILURES += 1
    if _AUDIT_WRITE_FAILURES > _AUDIT_WRITE_WARN_CAP:
        return False
    sys.stderr.write(
        "[mdcg-crypto] 审计写入失败（best-effort，已容忍）%s：%s: %s"
        "——本次后进程内累计 %d 次。排查方向：磁盘满 / 文件被独占 / "
        "权限回收；轮转面经 crypto.audit_scale(root) 可读。\n"
        % (root, type(exc).__name__, exc, _AUDIT_WRITE_FAILURES))
    return True


# 生效条件：root、rec 为入参，复制 rec，若未提供 ts 则设 time.time()，设 payload_free=True；先经 _rotator(root).maybe_rotate() 做写前轮转闸门（阈值内零切分），再 append_jsonl(os.path.join(root, AUDIT_FILE), rec)；轮转或追加抛 (OSError, TimeoutError) 时经 _note_audit_write_failure 记账 + 有界 stderr 告警，不阻断调用方（best-effort 语义不变）。
def audit(root, rec):
    from .fsutil import append_jsonl
    rec = dict(rec)
    rec.setdefault("ts", time.time())
    rec["payload_free"] = True
    try:
        _rotator(root).maybe_rotate()
    except (OSError, TimeoutError) as e:      # 轮转失败不得阻断审计写
        _note_audit_write_failure(root, e)
    try:
        append_jsonl(os.path.join(root, AUDIT_FILE), rec)
    except OSError as e:
        _note_audit_write_failure(root, e)


# 生效条件：root 为入参；limit 为 None 时返回 _crypto_archive 各分片（时间序）与活动文件的全部记录（跨分片合并）；limit 非 None（含 0）时从 reversed(paths) 读取并在 len(out) >= limit 时停止，返回 out[-limit:]（有界日志不被读成 O(n) 全量）。
def audit_records(root, limit: int = None):
    """审计记录读取——轮转后跨分片按时间序（旧片在前）合并。

    与 `MdCGOS.audit_records` 同款口径（A2 共享件）：默认全量语义保持既有调用方
    零改动；`limit=N` 取尾部 N 条。**旧实现 `list(read_jsonl(...))` 无 limit、把
    682 MB 单文件全量物化**——轮转后不改就会漏掉归档分片，故此处必须跨片合并。
    """
    from .fsutil import read_jsonl
    r = _rotator(root)
    paths = [os.path.join(r.archive, n) for n in r.shards()]
    paths.append(r.active)
    if limit is None:
        out = []
        for p in paths:
            out.extend(read_jsonl(p))
        return out
    out = []
    for p in reversed(paths):                 # 从最新往回读，读满 limit 即停
        if len(out) >= limit:
            break
        out = list(read_jsonl(p)) + out
    return out[-limit:]


# 生效条件：root 为入参，返回 _rotator(root).scale()——活动文件实时读数 + 归档分片索引缓存聚合（shards/shard_bytes/shard_events/oversized/total_bytes/total_events/total_exact/rotate_bytes/keep_shards）。
def audit_scale(root) -> dict:
    """审计面量级/有界性读数（O(1) 稳态，与 audit_scale 同款共享件）。"""
    return _rotator(root).scale()


# ---- 自描述 --------------------------------------------------------------

# 生效条件：无入参，返回包含 module="crypto"、ALG、ENCRYPTED_LEVELS、MASTER_ENV、KEYS_FILE 等模块级常量的自描述字典。
def catalog():
    """自描述：加密范围、密钥层级、身份一致性、威胁模型（供 MCP 对照）。"""
    return {
        "module": "crypto",
        "alg": ALG,
        "rfc": "RFC 8439（ChaCha20-Poly1305）",
        "encrypted_levels": list(ENCRYPTED_LEVELS),
        "key_hierarchy": {
            "KEK": f"环境变量 {MASTER_ENV} 或主密钥文件（仓库外，0600）",
            "DEK": f"每 (tenant, actor) 一把，用 KEK 包裹后存 {KEYS_FILE}",
            "node": "DEK + 每节点随机 nonce 做 AEAD",
        },
        "identity_binding": [
            "DEK 信封 AAD = mdcg-dek|v|tenant|actor",
            "节点 AAD = mdcg-node|v|tenant|actor|node_id",
            "信封另存 id_fp 指纹，解密前先比对（快速失败）",
            "密文块携带 enc_id_fp 指纹（新格式），读方零解密即可判跨身份",
        ],
        "plaintext_metadata": ["layer", "tags", "condition_space", "importance",
                               "sensitivity", "created_at"],
        "ciphertext_limits": "密文不参与全文索引；无密钥者只能走元数据路",
        "threat_model": {
            "covered": ["磁盘 / 备份 / 仓库泄露", "无密钥读取",
                        "跨身份 / 跨节点密文挪用"],
            "not_covered": ["本地内存取证", "侧信道（纯 Python 实现的固有限制）"],
        },
        "fail_closed": "无 KEK 时拒绝写入 private/secret，不静默降级为明文",
    }