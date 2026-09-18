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
import time

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
MASTER_FILE = os.path.join(os.path.expanduser("~"), ".mdcg", "master.key")

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


# 生效条件：root 为入参；若 os.path.exists(keys_path(root)) 为假，返回 {"v": ENVELOPE_VERSION, "alg": ALG, "envelopes": {}}；否则尝试 json.load，若结果为 dict 且其 "envelopes" 为 dict 则返回该 dict；若 json 解析 ValueError 或 OSError 则返回同样的空结构。
def _load_keys(root):
    p = keys_path(root)
    if not os.path.exists(p):
        return {"v": ENVELOPE_VERSION, "alg": ALG, "envelopes": {}}
    try:
        with open(p, "r", encoding="utf-8") as f:
            d = json.load(f)
        if isinstance(d, dict) and isinstance(d.get("envelopes"), dict):
            return d
    except (ValueError, OSError):
        pass
    return {"v": ENVELOPE_VERSION, "alg": ALG, "envelopes": {}}


# 生效条件：root、data 为入参，将 data 经 json.dumps(data, ensure_ascii=False, indent=1) 后由 atomic_write 写入 keys_path(root)。
def _save_keys(root, data):
    from .fsutil import atomic_write
    atomic_write(keys_path(root),
                 json.dumps(data, ensure_ascii=False, indent=1))


# 生效条件：tenant、actor 为入参，返回 f"{tenant}|{actor}"。
def _envelope_key(tenant, actor):
    return f"{tenant}|{actor}"


# 生效条件：root、kek、tenant、actor、clearance="private"、rotate=False 为入参；若 kek 为假抛 LockedError；否则加载 keys，若 _envelope_key(tenant, actor) 已在 envelopes 中且 rotate 为假则返回 unwrap_dek(root, kek, tenant, actor, clearance)；否则生成新 DEK 与 nonce，用 aead_encrypt(kek, nonce, dek, _dek_aad(tenant, actor)) 包裹后写入 envelopes[k] 并保存，返回 dek。
def provision_dek(root, kek, tenant, actor, clearance="private", rotate=False):
    """为 (tenant, actor) 生成 / 取回 DEK，用 KEK 包裹后存入 `_keys.json`。

    rotate=True 强制换新密钥（旧密文需先迁移，见 `reencrypt_all`）。
    """
    if not kek:
        raise LockedError("无主密钥（KEK）：拒绝签发数据密钥")
    data = _load_keys(root)
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


# 生效条件：content、dek、node_id、tenant、actor 为入参，生成 NONCE_LEN 随机 nonce，将 str(content).encode("utf-8") 以 aead_encrypt(dek, nonce, ..., _node_aad(node_id, tenant, actor)) 加密，返回 f"{ENC_PREFIX}{_b64e(nonce + tag + ct)}{ENC_SUFFIX}"。
def seal_node(content, dek, node_id, tenant, actor):
    """明文 → 密文标记块（正文整体加密；frontmatter 不在此处处理）。"""
    nonce = secrets.token_bytes(NONCE_LEN)
    ct, tag = aead_encrypt(dek, nonce, str(content).encode("utf-8"),
                           _node_aad(node_id, tenant, actor))
    return f"{ENC_PREFIX}{_b64e(nonce + tag + ct)}{ENC_SUFFIX}"


# 生效条件：content、dek、node_id、tenant、actor 为入参；若 is_encrypted(content) 为假则原样返回 content；否则 strip 后切掉 ENC_PREFIX/ENC_SUFFIX，base64 解出 raw，按 NONCE_LEN、TAG_LEN 切出 nonce/tag/ct，调 aead_decrypt(dek, nonce, ct, tag, _node_aad(node_id, tenant, actor)) 并 utf-8 解码返回；aead_decrypt 失败抛 CryptoError。
def open_node(content, dek, node_id, tenant, actor):
    """密文标记块 → 明文；未加密原样返回；失败抛 CryptoError。"""
    if not is_encrypted(content):
        return content
    body = content.strip()
    body = body[len(ENC_PREFIX):-len(ENC_SUFFIX)]
    raw = _b64d(body)
    nonce = raw[:NONCE_LEN]
    tag = raw[NONCE_LEN:NONCE_LEN + TAG_LEN]
    ct = raw[NONCE_LEN + TAG_LEN:]
    return aead_decrypt(dek, nonce, ct, tag,
                        _node_aad(node_id, tenant, actor)).decode("utf-8")


# ---- 审计（payload-free）-------------------------------------------------

# 生效条件：root、rec 为入参，复制 rec，若未提供 ts 则设 time.time()，设 payload_free=True，尝试 append_jsonl(os.path.join(root, AUDIT_FILE), rec)；OSError 时静默忽略。
def audit(root, rec):
    from .fsutil import append_jsonl
    rec = dict(rec)
    rec.setdefault("ts", time.time())
    rec["payload_free"] = True
    try:
        append_jsonl(os.path.join(root, AUDIT_FILE), rec)
    except OSError:
        pass


# 生效条件：root 为入参，返回 list(read_jsonl(os.path.join(root, AUDIT_FILE))) 得到的记录列表。
def audit_records(root):
    from .fsutil import read_jsonl
    return list(read_jsonl(os.path.join(root, AUDIT_FILE)))


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