# -*- coding: utf-8 -*-
"""签名接口层（蜂群互联 D-4）。

设计裁决 D-4（2026-09-10，设计者）：

  · 协议内核**不实现密码学**，只定义 `sign` / `verify` 契约；
  · 具体签名链（企业 CA / KMS / 签章服务）在**工程项目**中实现；
  · **搭载灵枢的智能体自行决定子系统如何使用签名链**（策略落盘 `_signers.json`）。

因此本模块只做三件事：
  ① 定义可插拔的 `Signer` 契约 + 注册表；
  ② 提供两个最简内置实现（`null` / `hmac-local`）；
  ③ 读取并执行**子系统签名策略**（何时签、是否要求对端签、验签失败如何处置）。

**内核不保存私钥**：私钥归工程侧，这里只持有 `sign` / `verify` 的可调用引用。
工程侧注入方式：

    # 1) 代码注入
    from md_cg.signer import register_signer
    register_signer("corp_pki", lambda: MyCorpSigner(...))

    # 2) 启动自动加载（MCP 子进程推荐）
    MDCG_SIGNER_MODULE=mycorp.signing   # 模块内提供 register()

零第三方依赖。
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import importlib
import json
import os
import secrets
import sys
import time

SIGNER_ENV = "MDCG_SIGNER"
SIGNER_MODULE_ENV = "MDCG_SIGNER_MODULE"
SIGNERS_FILE_ENV = "MDCG_SIGNERS_FILE"
KEY_FILE_ENV = "MDCG_SIGNER_KEY_FILE"

DEFAULT_DIR = os.path.join(os.path.expanduser("~"), ".mdcg")
DEFAULT_SIGNERS_FILE = os.path.join(DEFAULT_DIR, "_signers.json")
DEFAULT_KEY_FILE = os.path.join(DEFAULT_DIR, "_signer.key")

SCHEMA = 1
DEFAULT_SIGNER = "hmac-local"
PREFIX = "hmac1"

# 需要签名的动作（子系统策略里引用）
SIGN_ACTIONS = ("handshake", "evidence", "withdrawal")
# 验签失败的处置档位（宪章第七条降级为默认）
ON_VERIFY_FAIL = ("degrade", "isolate", "reject")


class SignerError(Exception):
    """签名接口层错误。"""


# --------------------------------------------------------------------------
# 契约与内置实现
# --------------------------------------------------------------------------

class Signer:
    """签名器契约。工程侧实现只需满足这两个方法（鸭子类型即可）。"""

    name = "abstract"

    def sign(self, payload: bytes, ctx: dict = None) -> str:
        raise NotImplementedError

    def verify(self, payload: bytes, signature: str, ctx: dict = None) -> bool:
        raise NotImplementedError

    def describe(self) -> dict:
        return {"name": self.name, "kind": "abstract"}

    def public(self) -> dict:
        """可对外公开的验证信息（**不得含密钥**）。"""
        return {"name": self.name}


class NullSigner(Signer):
    """不签名（观察期 / 纯本地）。验签时把「空签名」视为通过。"""

    name = "null"

    def sign(self, payload: bytes, ctx: dict = None) -> str:
        return ""

    def verify(self, payload: bytes, signature: str, ctx: dict = None) -> bool:
        return signature in ("", None)

    def describe(self) -> dict:
        return {"name": self.name, "kind": "none",
                "note": "不签名；仅用于观察期或纯本地场景"}


class HmacLocalSigner(Signer):
    """本地 HMAC-SHA256 实现——与 `_tokens.json` 同一信任根级别的最简方案。

    它**不是**企业级签名链（无不可否认性、无私钥托管），
    仅用于单机自测与「有签名位置但暂无 CA」的过渡期。
    """

    name = "hmac-local"

    def __init__(self, key: bytes = None, key_file: str = None):
        self.key_file = key_file or key_file_path()
        self.key = key or load_key(self.key_file)

    def sign(self, payload: bytes, ctx: dict = None) -> str:
        mac = hmac.new(self.key, canonical(payload, ctx), hashlib.sha256)
        return f"{PREFIX}.{mac.hexdigest()}"

    def verify(self, payload: bytes, signature: str, ctx: dict = None) -> bool:
        sig = (signature or "").strip()
        if not sig.startswith(PREFIX + "."):
            return False
        want = self.sign(payload, ctx)
        return hmac.compare_digest(want, sig)

    def describe(self) -> dict:
        return {"name": self.name, "kind": "hmac-sha256",
                "key_file": self.key_file,
                "note": "本地实现，非企业级签名链；无不可否认性"}

    def public(self) -> dict:
        return {"name": self.name, "kind": "hmac-sha256",
                "key_id": hashlib.sha256(self.key).hexdigest()[:16]}


_REGISTRY = {
    "null": NullSigner,
    DEFAULT_SIGNER: HmacLocalSigner,
}
_LOADED_MODULES = set()


def canonical(payload, ctx: dict = None) -> bytes:
    """规范化待签字节串：payload 走 base64，ctx 按 key 排序——避免表示歧义。"""
    if isinstance(payload, str):
        payload = payload.encode("utf-8")
    body = {"payload": base64.b64encode(bytes(payload)).decode("ascii")}
    if ctx:
        body["ctx"] = {str(k): str(ctx[k]) for k in sorted(ctx)}
    return json.dumps(body, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


# --------------------------------------------------------------------------
# 注册表（工程侧注入点）
# --------------------------------------------------------------------------

def register_signer(name: str, factory) -> dict:
    """注册签名器。`factory` 为无参可调用（返回实例）或类本身。"""
    name = (name or "").strip()
    if not name:
        raise SignerError("签名器名不能为空")
    if not callable(factory):
        raise SignerError("factory 必须可调用（返回 Signer 实例）")
    _REGISTRY[name] = factory
    return {"ok": True, "name": name, "signers": sorted(_REGISTRY)}


def unregister_signer(name: str) -> dict:
    if name not in _REGISTRY:
        raise SignerError(f"签名器不存在：{name}")
    if name in ("null", DEFAULT_SIGNER):
        raise SignerError(f"内置签名器不可注销：{name}")
    _REGISTRY.pop(name, None)
    return {"ok": True, "signers": sorted(_REGISTRY)}


def list_signers() -> dict:
    return {"default": default_name(), "signers": sorted(_REGISTRY)}


def default_name() -> str:
    return (os.environ.get(SIGNER_ENV) or "").strip() or DEFAULT_SIGNER


def _autoload():
    """按 MDCG_SIGNER_MODULE 自动加载工程侧注册模块（进程内只做一次）。"""
    mod = (os.environ.get(SIGNER_MODULE_ENV) or "").strip()
    if not mod or mod in _LOADED_MODULES:
        return
    _LOADED_MODULES.add(mod)
    try:
        m = importlib.import_module(mod)
    except Exception as e:                     # 加载失败不静默：留给调用方判定
        raise SignerError(f"签名器模块加载失败 {mod}：{e}")
    reg = getattr(m, "register", None)
    if not callable(reg):
        raise SignerError(f"签名器模块 {mod} 未提供 register()")
    reg()


def get_signer(name: str = None, key_file: str = None) -> Signer:
    """取签名器实例。未注册即抛错（fail-closed，不静默降级为 null）。"""
    _autoload()
    nm = (name or "").strip() or default_name()
    factory = _REGISTRY.get(nm)
    if factory is None:
        raise SignerError(
            f"签名器未注册：{nm}（已注册：{sorted(_REGISTRY)}）；"
            "工程侧可用 register_signer() 或 MDCG_SIGNER_MODULE 注入")
    try:
        inst = factory(key_file=key_file) if _accepts_key_file(factory) else factory()
    except TypeError:
        inst = factory()
    if not isinstance(inst, Signer) and not (
            callable(getattr(inst, "sign", None))
            and callable(getattr(inst, "verify", None))):
        raise SignerError(f"签名器 {nm} 未实现 sign/verify 契约")
    if not getattr(inst, "name", None):
        inst.name = nm
    return inst


def _accepts_key_file(factory) -> bool:
    try:
        import inspect
        return "key_file" in inspect.signature(factory).parameters
    except (TypeError, ValueError):
        return False


# --------------------------------------------------------------------------
# 密钥（仅内置 hmac-local 需要；工程侧自行管理私钥）
# --------------------------------------------------------------------------

def key_file_path(path: str = None) -> str:
    return path or os.environ.get(KEY_FILE_ENV) or DEFAULT_KEY_FILE


def load_key(path: str = None) -> bytes:
    p = key_file_path(path)
    if os.path.exists(p):
        with open(p, "rb") as f:
            raw = f.read().strip()
        if raw:
            return raw
    key = secrets.token_urlsafe(32).encode("utf-8")
    save_key(key, p)
    return key


def save_key(key: bytes, path: str = None) -> str:
    p = key_file_path(path)
    os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "wb") as f:
        f.write(key if isinstance(key, bytes) else str(key).encode("utf-8"))
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    os.replace(tmp, p)
    return p


# --------------------------------------------------------------------------
# 子系统签名策略（D-4：智能体自行决定子系统怎么用签名链）
# --------------------------------------------------------------------------

def _default_policy() -> dict:
    return {"signer": None, "sign_on": ["handshake"],
            "require_peer_signature": False, "on_verify_fail": "degrade"}


def _normalize(pol: dict) -> dict:
    out = _default_policy()
    out.update({k: pol[k] for k in ("signer", "sign_on",
                                    "require_peer_signature",
                                    "on_verify_fail") if k in pol})
    on = out.get("sign_on")
    if isinstance(on, str):
        on = [x for x in on.split(",") if x.strip()]
    out["sign_on"] = [x for x in (on or []) if x in SIGN_ACTIONS]
    if out.get("on_verify_fail") not in ON_VERIFY_FAIL:
        out["on_verify_fail"] = "degrade"
    out["require_peer_signature"] = bool(out.get("require_peer_signature"))
    return out


def signers_file(path: str = None) -> str:
    return path or os.environ.get(SIGNERS_FILE_ENV) or DEFAULT_SIGNERS_FILE


def load_policies(path: str = None) -> dict:
    p = signers_file(path)
    if os.path.exists(p):
        try:
            with open(p, "r", encoding="utf-8") as f:
                d = json.load(f)
            if isinstance(d, dict):
                d.setdefault("schema", SCHEMA)
                d.setdefault("subsystems", {})
                return d
        except (OSError, ValueError):
            pass
    return {"schema": SCHEMA, "default_signer": DEFAULT_SIGNER,
            "subsystems": {}, "updated_at": None}


def save_policies(data: dict, path: str = None) -> str:
    p = signers_file(path)
    os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
    data = dict(data)
    data["schema"] = SCHEMA
    data["updated_at"] = time.time()
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1, sort_keys=True)
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    os.replace(tmp, p)
    return p


def policy_for(subsystem: str = None, path: str = None) -> dict:
    """取子系统策略；未声明则用默认（`default_signer` + handshake 签名）。"""
    d = load_policies(path)
    pol = (d.get("subsystems") or {}).get(subsystem or "") or {}
    out = _normalize(pol)
    if not out.get("signer"):
        out["signer"] = d.get("default_signer") or DEFAULT_SIGNER
    out["subsystem"] = subsystem or ""
    return out


def set_policy(subsystem: str, path: str = None, **kw) -> dict:
    """声明/更新子系统签名策略——**这是智能体行使 D-4 的入口**。"""
    if not subsystem:
        raise SignerError("子系统名不能为空")
    d = load_policies(path)
    cur = (d["subsystems"].get(subsystem) or {})
    cur.update({k: v for k, v in kw.items() if v is not None})
    d["subsystems"][subsystem] = _normalize(cur)
    if kw.get("default_signer"):
        d["default_signer"] = kw["default_signer"]
    save_policies(d, path)
    return {"ok": True, "subsystem": subsystem,
            "policy": policy_for(subsystem, path),
            "file": signers_file(path)}


def remove_policy(subsystem: str, path: str = None) -> dict:
    d = load_policies(path)
    if subsystem in (d.get("subsystems") or {}):
        d["subsystems"].pop(subsystem)
        save_policies(d, path)
    return {"ok": True, "subsystem": subsystem,
            "subsystems": sorted(d.get("subsystems") or {})}


# --------------------------------------------------------------------------
# 策略驱动的签名 / 验签（连接层调用）
# --------------------------------------------------------------------------

def sign_for(subsystem: str, payload, ctx: dict = None,
             action: str = "handshake", path: str = None) -> dict:
    """按子系统策略签名。策略未把该 action 列入 `sign_on` 则**不签**。"""
    pol = policy_for(subsystem, path)
    if action not in pol["sign_on"]:
        return {"ok": True, "signed": False, "action": action,
                "signer": None, "signature": "",
                "reason": f"子系统 {subsystem or '(默认)'} 策略未对 {action} 要求签名"}
    s = get_signer(pol.get("signer"))
    sig = s.sign(payload, ctx)
    return {"ok": True, "signed": True, "action": action,
            "signer": getattr(s, "name", None), "signature": sig,
            "public": s.public()}


def verify_for(subsystem: str, payload, signature, ctx: dict = None,
               action: str = "handshake", path: str = None) -> dict:
    """按子系统策略验对端签名。

    语义分工（避免歧义）：
      · `sign_on`      —— **本节点**在哪些动作上签名（见 `sign_for`）；
      · `require_peer_signature` —— **对端**是否必须提供签名。

    三种结果：
      · 不要求且未提供 → `ok=True, required=False`（放行）；
      · 要求但缺失     → `ok=False, missing=True, on_fail="reject"`（fail-closed）；
      · 提供了就验     → 失败时 `on_fail` 取策略值，由调用方执行处置。
    """
    pol = policy_for(subsystem, path)
    required = bool(pol["require_peer_signature"])
    sig = (signature or "").strip()

    if not required and not sig:
        return {"ok": True, "required": False, "missing": False,
                "action": action, "signer": None, "on_fail": None,
                "require_peer_signature": False,
                "reason": "策略未要求对端签名，且对端未提供"}
    if required and not sig:
        return {"ok": False, "required": True, "missing": True,
                "action": action, "signer": None, "on_fail": "reject",
                "require_peer_signature": True,
                "reason": "策略要求对端签名，但对端未提供"}

    s = get_signer(pol.get("signer"))
    try:
        ok = bool(s.verify(payload, sig, ctx))
    except Exception as e:
        ok, err = False, str(e)
    else:
        err = ""
    return {"ok": ok, "required": required, "missing": False, "action": action,
            "signer": getattr(s, "name", None),
            "on_fail": None if ok else pol["on_verify_fail"],
            "require_peer_signature": required,
            "reason": "" if ok else (err or "验签失败")}


# --------------------------------------------------------------------------
# 自描述 / CLI
# --------------------------------------------------------------------------

def show(path: str = None) -> dict:
    d = load_policies(path)
    return {"file": signers_file(path),
            "default_signer": d.get("default_signer") or DEFAULT_SIGNER,
            "subsystems": {k: _normalize(v) for k, v in
                           (d.get("subsystems") or {}).items()},
            "updated_at": d.get("updated_at")}


def catalog() -> dict:
    return {
        "layer": "签名接口（蜂群互联 D-4）",
        "decision": "协议内核只定义契约；实现落工程项目；子系统自行决定用法",
        "actions": list(SIGN_ACTIONS),
        "on_verify_fail": list(ON_VERIFY_FAIL),
        "signers": list_signers(),
        "builtin": {n: _REGISTRY[n]().describe() for n in sorted(_REGISTRY)
                    if n in ("null", DEFAULT_SIGNER)},
        "policy_file": signers_file(),
        "env": {"signer": SIGNER_ENV, "module": SIGNER_MODULE_ENV,
                "policy_file": SIGNERS_FILE_ENV, "key_file": KEY_FILE_ENV},
    }


def _print(obj):
    print(json.dumps(obj, ensure_ascii=False, indent=1, default=str))


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="python -m md_cg.signer",
        description="签名接口层：契约 + 子系统策略（D-4：内核不实现密码学）")
    ap.add_argument("--signers-file", default=None,
                    help="策略文件（默认 ~/.mdcg/_signers.json）")
    ap.add_argument("--key-file", default=None,
                    help="本地密钥文件（默认 ~/.mdcg/_signer.key）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("catalog", help="签名接口自描述")
    sub.add_parser("list", help="已注册签名器")
    sub.add_parser("show", help="子系统签名策略")

    p_set = sub.add_parser("set", help="声明子系统签名策略")
    p_set.add_argument("subsystem")
    p_set.add_argument("--signer", default=None)
    p_set.add_argument("--sign-on", default=None, help="逗号分隔：handshake,evidence")
    p_set.add_argument("--require-peer", action="store_true", default=None)
    p_set.add_argument("--on-verify-fail", default=None,
                       choices=list(ON_VERIFY_FAIL))

    p_rm = sub.add_parser("rm", help="删除子系统策略")
    p_rm.add_argument("subsystem")

    p_s = sub.add_parser("sign", help="按策略签名（payload 取自 --payload 或 stdin）")
    p_s.add_argument("--subsystem", default=None)
    p_s.add_argument("--action", default="handshake", choices=list(SIGN_ACTIONS))
    p_s.add_argument("--payload", default=None)

    p_v = sub.add_parser("verify", help="按策略验签")
    p_v.add_argument("--subsystem", default=None)
    p_v.add_argument("--action", default="handshake", choices=list(SIGN_ACTIONS))
    p_v.add_argument("--payload", required=True)
    p_v.add_argument("--signature", required=True)

    a = ap.parse_args(argv)
    try:
        if a.cmd == "catalog":
            _print(catalog())
        elif a.cmd == "list":
            _print(list_signers())
        elif a.cmd == "show":
            _print(show(a.signers_file))
        elif a.cmd == "set":
            on = ([x for x in a.sign_on.split(",") if x.strip()]
                  if a.sign_on else None)
            _print(set_policy(a.subsystem, path=a.signers_file,
                              signer=a.signer, sign_on=on,
                              require_peer_signature=a.require_peer,
                              on_verify_fail=a.on_verify_fail))
        elif a.cmd == "rm":
            _print(remove_policy(a.subsystem, a.signers_file))
        elif a.cmd == "sign":
            payload = a.payload if a.payload is not None else sys.stdin.read()
            _print(sign_for(a.subsystem, payload, action=a.action,
                            path=a.signers_file))
        elif a.cmd == "verify":
            _print(verify_for(a.subsystem, a.payload, a.signature,
                              action=a.action, path=a.signers_file))
    except SignerError as e:
        print(f"[md_cg.signer] {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
