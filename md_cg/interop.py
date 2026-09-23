# -*- coding: utf-8 -*-
"""互验工具库（批次10，互验定稿 §7 的 python 落地）。

三断言（§7.5）：
  A1  verifier_instance != subject_instance          —— 是两个人
  A2  verifier_fingerprint != subject_fingerprint    —— 指纹不同
  A3  verifier_fingerprint == 本轮冻结值             —— 看同一把尺子（承重墙）
任一不成立 → 验证结论作废。

verdict 脱敏硬门禁（§7.3）：入库即公开，只允许结构化事实（指纹/断言/计数/
SHA/迭代 id/时间戳/符号化路径）；禁止 spec 正文/prompt/result.content/
API 信息/本机绝对路径——违规抛 InteropSanityError。
"""
from __future__ import annotations

import json
import os
import re
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MANIFEST = os.path.join(HERE, "scripts", "judgment_manifest.py")

_FORBIDDEN_RES = [
    (re.compile(r"[A-Za-z]:[\\\\/]", ), "本机绝对路径（盘符）"),
    (re.compile(r"/Users/|/home/"), "本机绝对路径（unix 家目录）"),
    (re.compile(r"sk[-_][A-Za-z0-9]{8,}"), "疑似 API key"),
    (re.compile(r"https?://[^\s\"']*(api|key|token)", re.I), "API 端点/凭证 URL"),
]
_FORBIDDEN_KEYS = {"prompt", "content", "spec", "api_key", "base", "model",
                   "system_prompt", "user_prompt", "content_head"}


class InteropSanityError(ValueError):
    """verdict 脱敏门禁违规（入库即公开，违规内容不得落盘）。"""


def _manifest(action: str):
    import subprocess
    import sys
    r = subprocess.run([sys.executable, MANIFEST, action],
                       capture_output=True, text=True, encoding="utf-8")
    if r.returncode != 0:
        raise RuntimeError(f"judgment_manifest {action} 失败: {r.stderr[:200]}")
    return r.stdout.strip()


def freeze(iter_id: str, out_dir: str = None) -> dict:
    """第 0 步：记录本轮判据面冻结凭证（A3 的比对基准）。

    out_dir 缺省 = hive/interop/<iter_id>/；显式传入时视为最终目录（不拼 iter_id）。
    """
    manifest = json.loads(_manifest(""))
    credential = {
        "iter_id": iter_id,
        "frozen_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "digest": _manifest("--digest"),
        "files": manifest["files"],
    }
    if out_dir is None:
        out_dir = os.path.join(HERE, "hive", "interop", iter_id)
    os.makedirs(out_dir, exist_ok=True)
    fp = os.path.join(out_dir, "frozen.json")
    with open(fp, "w", encoding="utf-8") as f:
        json.dump(credential, f, ensure_ascii=False, indent=2)
    credential["_path"] = fp
    return credential


def assert_a3(frozen: dict, verifier_fingerprint: str) -> dict:
    """A3（承重墙）：验证者声明的判据面指纹 == 本轮冻结值。"""
    ok = verifier_fingerprint == frozen.get("digest")
    return {"assertion": "A3", "ok": ok,
            "frozen": frozen.get("digest"), "actual": verifier_fingerprint}


def assert_a1(verifier_instance: str, subject_instance: str) -> dict:
    return {"assertion": "A1",
            "ok": bool(verifier_instance and subject_instance
                       and verifier_instance != subject_instance),
            "verifier": verifier_instance, "subject": subject_instance}


def assert_a2(verifier_fingerprint: str, subject_fingerprint: str) -> dict:
    return {"assertion": "A2",
            "ok": bool(verifier_fingerprint and subject_fingerprint
                       and verifier_fingerprint != subject_fingerprint),
            "verifier": verifier_fingerprint, "subject": subject_fingerprint}


def sanity_check_verdict(verdict: dict) -> None:
    """脱敏硬门禁：递归扫描 verdict 全部键与字符串值，违规即抛。"""
    def walk(obj, path="$"):
        if isinstance(obj, dict):
            for k, v in obj.items():
                if str(k).lower() in _FORBIDDEN_KEYS:
                    raise InteropSanityError(
                        f"{path}.{k}: 禁止字段（spec 正文/prompt/API 信息不得入库）")
                walk(v, f"{path}.{k}")
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                walk(v, f"{path}[{i}]")
        elif isinstance(obj, str):
            for i, (pat, why) in enumerate(_FORBIDDEN_RES):
                if pat.search(obj):
                    raise InteropSanityError(
                        f"{path}: 疑似 {why}（命中 {i} 号规则）")

    walk(verdict)


def make_verdict(iter_id: str, verifier_instance: str, verifier_fingerprint: str,
                 subject_instance: str, subject_fingerprint: str,
                 suite_origin: str, frozen_at: str, verdict: str,
                 passed: int, failed: int, details=None) -> dict:
    """§7.3 契约构造 + 脱敏门禁（违规即抛，绝不落盘）。"""
    v = {
        "iter_id": iter_id,
        "verifier_instance": verifier_instance,
        "verifier_fingerprint": verifier_fingerprint,
        "subject_instance": subject_instance,
        "subject_fingerprint": subject_fingerprint,
        "suite_origin": suite_origin,
        "frozen_at": frozen_at,
        "verdict": verdict,
        "passed": passed,
        "failed": failed,
        "details": details or [],
    }
    sanity_check_verdict(v)
    return v
