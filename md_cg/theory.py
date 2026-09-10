# -*- coding: utf-8 -*-
"""md_cg · 版本层（蜂群互联 · 层0）

设计依据：`docs/蜂群互联_v0.1.md` §2.3 / §3.1 / §10。

版本更新权 = 蜂群**唯一核心权限**（严格唯一，仅 designer）。本模块只做
「声明 + 校验」两件事，不做跨节点证据交换（§9.1 属存在约束，留待 v0.3）：

  ① 声明 —— `~/.mdcg/theory.json` 记录 theory_version / accepted_versions /
     declared_by / declared_at，并以 declaration_hash 封缄（防意外损坏）。
  ② 校验 —— MCP 启动时 `check()`；不合法即 `theory_ok=False`，主体降级为只读
     （写操作全拒，仅保留 theory 修复入口），**不拒绝启动**。

fail-closed 与令牌的差别（有意为之）：

  · 令牌非法 → **拒绝启动**：身份不可信，不能降级为可用；
  · 版本非法 → **降级只读**：身份可信但公理状态未知，禁止改写事实层。

存储与 `_tokens.json` 同目录约定（0600）。零第三方依赖。
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import sys
import time

THEORY_ENV = "MDCG_THEORY"
THEORY_FILE_ENV = "MDCG_THEORY_FILE"
DEFAULT_THEORY_DIR = os.path.join(os.path.expanduser("~"), ".mdcg")
DEFAULT_THEORY_FILE = os.path.join(DEFAULT_THEORY_DIR, "theory.json")
SCHEMA = 1

#: 与《智能论》当前版本对齐；仅为**默认声明值**，权威来源是声明文件本身。
PROTOCOL_VERSION = "3.4"

#: 被 declaration_hash 封缄的字段（改动其一即校验失败）
SEALED_FIELDS = ("theory_version", "accepted_versions", "declared_by", "declared_at")

#: theory_ok=False 时仍可执行的 op（唯一修复入口）
ESCAPE_OPS = ("theory",)


class TheoryError(Exception):
    """版本层声明非法 / 被篡改 / 越权声明。"""


# --------------------------------------------------------------------------
# 存储
# --------------------------------------------------------------------------

def theory_file(path: str = None) -> str:
    return path or os.environ.get(THEORY_FILE_ENV) or DEFAULT_THEORY_FILE


def _canon(payload: dict) -> str:
    """规范化 JSON：键排序 + 紧凑分隔符（哈希可复现的唯一前提）。"""
    return json.dumps(payload, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"))


def declaration_hash(payload: dict) -> str:
    return hashlib.sha256(_canon(payload).encode("utf-8")).hexdigest()


def _payload(decl: dict) -> dict:
    return {k: decl.get(k) for k in SEALED_FIELDS}


def seal(decl: dict) -> dict:
    """封缄：补上 declaration_hash。"""
    d = dict(decl)
    d["declaration_hash"] = declaration_hash(_payload(d))
    return d


def load(path: str = None):
    p = theory_file(path)
    if not os.path.exists(p):
        return None
    try:
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        return None
    return d if isinstance(d, dict) else None


def save(decl: dict, path: str = None) -> str:
    p = theory_file(path)
    os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(decl, f, ensure_ascii=False, indent=1)
    os.replace(tmp, p)
    try:
        os.chmod(p, 0o600)
    except OSError:
        pass
    return p


# --------------------------------------------------------------------------
# 声明与校验
# --------------------------------------------------------------------------

def make_declaration(version: str = None, accepted=None,
                     declared_by: str = "designer", now: float = None) -> dict:
    """构造（未封缄的）版本声明。accepted 默认只含自身版本。"""
    v = (version or PROTOCOL_VERSION).strip()
    if not v:
        raise TheoryError("theory_version 不能为空")
    acc = list(accepted) if accepted else [v]
    acc = [str(x).strip() for x in acc if str(x).strip()]
    if v not in acc:
        acc.insert(0, v)
    return {"schema": SCHEMA, "theory_version": v, "accepted_versions": acc,
            "declared_by": (declared_by or "designer").strip(),
            "declared_at": float(now if now is not None else time.time())}


def check(path: str = None, decl: dict = None) -> dict:
    """校验版本声明 → 状态字典（永不抛异常，供启动路径安全调用）。

    theory_ok=False 的四种成因互斥且各自可归因：
      ① 未声明（文件缺失）  ② schema 不符  ③ 封缄不匹配（被篡改）  ④ 版本不在认可集合
    """
    p = theory_file(path)
    d = decl if decl is not None else load(p)
    base = {"source": p, "theory_ok": False, "version": None, "auto": False,
            "accepted_versions": [], "declared_by": None, "declared_at": None,
            "declaration_hash": None, "schema": SCHEMA, "reason": ""}
    if not d:
        # 未声明 ≠ 违规：既有部署升级后不应被立刻降级只读。
        # 按默认版本放行，并由启动路径 ensure() 落盘声明（声明常态化）。
        base.update({"theory_ok": True, "auto": True,
                     "version": PROTOCOL_VERSION,
                     "accepted_versions": [PROTOCOL_VERSION],
                     "reason": f"未声明版本层（按默认版本 {PROTOCOL_VERSION} 运行）"})
        return base
    if d.get("schema") != SCHEMA:
        base["reason"] = f"声明 schema 不符：{d.get('schema')!r}（期望 {SCHEMA}）"
        return base
    if not hmac.compare_digest(str(d.get("declaration_hash") or ""),
                               declaration_hash(_payload(d))):
        base["reason"] = "声明被篡改（declaration_hash 不匹配）"
        return base
    v = d.get("theory_version")
    acc = [str(x) for x in (d.get("accepted_versions") or [])]
    base.update({"version": v, "accepted_versions": acc,
                 "declared_by": d.get("declared_by"),
                 "declared_at": d.get("declared_at"),
                 "declaration_hash": d.get("declaration_hash")})
    if not v:
        base["reason"] = "声明缺少 theory_version"
        return base
    if v not in acc:
        base["reason"] = f"版本 {v} 不在认可集合 {acc}"
        return base
    base.update({"theory_ok": True, "reason": "ok"})
    return base


def ensure(path: str = None) -> dict:
    """启动路径：无声明则落盘默认声明（声明常态化），再返回校验状态。

    落盘失败**不阻断启动**——退回 `check()` 的判定（此时为未声明态，放行）。
    """
    p = theory_file(path)
    if load(p) is None:
        try:
            declare(PROTOCOL_VERSION, actor="system:autoinit", path=p,
                    append_audit=False)
        except (TheoryError, OSError):
            pass
    return check(p)


def declare(version: str = None, accepted=None, actor: str = "designer",
            path: str = None, append_audit: bool = True) -> dict:
    """写入版本声明（版本更新权的唯一物理落点）。"""
    old = load(path)
    decl = make_declaration(version, accepted=accepted, declared_by=actor)
    decl = seal(decl)
    if append_audit:
        hist = list((old or {}).get("audit") or [])
        if old:
            hist.append({"at": time.time(), "from": old.get("theory_version"),
                         "to": decl["theory_version"], "by": actor})
        decl["audit"] = hist
    save(decl, path)
    return {"ok": True, "declaration": decl, "status": check(path)}


def show(path: str = None) -> dict:
    return {"declaration": load(path), "status": check(path),
            "theory_file": theory_file(path)}


def catalog() -> dict:
    """版本层自描述（供 whoami / service_info 暴露）。"""
    return {"schema": SCHEMA, "theory_file": theory_file(),
            "protocol_version": PROTOCOL_VERSION,
            "sealed_fields": list(SEALED_FIELDS),
            "escape_ops": list(ESCAPE_OPS),
            "env": {"version": THEORY_ENV, "file": THEORY_FILE_ENV}}


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def _print(obj):
    sys.stdout.write(json.dumps(obj, ensure_ascii=False, indent=1) + "\n")


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="python -m md_cg.theory",
        description="版本层（蜂群互联层0）：版本声明与校验（版本更新权唯一）")
    ap.add_argument("--theory-file", default=None,
                    help="声明文件路径（默认 ~/.mdcg/theory.json）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_d = sub.add_parser("declare", help="声明版本（仅设计者）")
    p_d.add_argument("--version", default=None, help=f"默认 {PROTOCOL_VERSION}")
    p_d.add_argument("--accept", default=None, help="认可版本集合，逗号分隔")
    p_d.add_argument("--actor", default="designer")

    sub.add_parser("check", help="校验声明（打印 theory_ok）")
    sub.add_parser("ensure", help="无声明则落盘默认声明（启动路径用）")
    sub.add_parser("show", help="打印声明与校验状态")
    sub.add_parser("catalog", help="版本层自描述")

    a = ap.parse_args(argv)
    try:
        if a.cmd == "declare":
            acc = [x for x in (a.accept or "").split(",") if x.strip()] or None
            _print(declare(a.version, accepted=acc, actor=a.actor,
                           path=a.theory_file))
        elif a.cmd == "check":
            _print(check(a.theory_file))
        elif a.cmd == "ensure":
            _print(ensure(a.theory_file))
        elif a.cmd == "show":
            _print(show(a.theory_file))
        elif a.cmd == "catalog":
            _print(catalog())
    except TheoryError as e:
        sys.stderr.write(f"[theory] {e}\n")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
