# -*- coding: utf-8 -*-
"""R-405c · HTTP 侧到 Rust `mdcg-eval --serve` 的桥（只读检索后端可切换）。

形态照 `server/mdcg_http.py`：同目录、同「零第三方依赖 + 子进程协议」风格。
它只做一件事：把一条检索请求喂给常驻的 Rust serve 进程，把结果按 **Python
`search_rrf` 的同形**返回（id/score 列表），使 `/health` 的 `backend` 字段可以
在 `lingshu`（Python 内嵌）与 `rust`（本桥）之间切换。

设计约束（每条都有理由，改之前先读）：

  · **不静默回落**：桥起不来 / 半路死了 ⇒ `status()` 报 `degraded=True` + 原因，
    调用方必须把 5xx 报出去。审计 P2「切到 rust 但桥不通必须报 degraded」的落点。
  · **进程常驻**：一次 RPC 一次往返，不每次重建（冷启 ~20ms 在 2000 节点档
    实测是 Python 的 1/200，重建就把优势全吃掉）。
  · **只读面**：本桥只暴露 `search` / `info`，不接写路径——写仍然只走 Python
    （`md_cg` 的写链有锁 / 两段式 / 审计链，Rust 侧没有）。
  · **口径显式**：`--score` 由本模块钉住（缺省 jaccard），不从环境吃缺省，
    避免「两侧各吃各自缺省」的老问题（rank_parity 的 CH-1 教训）。
"""
from __future__ import annotations

import json
import os
import subprocess
import threading

SCORE = "jaccard"
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_EXE = os.path.join(
    _REPO, "rust", "target", "release",
    "mdcg-eval.exe" if os.name == "nt" else "mdcg-eval")


class RustBridge:
    """常驻 serve 进程的薄客户端（线程安全：一把锁串行化一次往返）。"""

    def __init__(self, root: str, exe: str = None, timeout: float = 10.0):
        self.root = root
        self.exe = exe or os.environ.get("MDCG_RUST_EVAL") or DEFAULT_EXE
        self.timeout = timeout
        self._lock = threading.Lock()
        self._p = None
        self.error = None
        self.degraded = False

    # ---- 生命周期 ----
    def start(self) -> bool:
        """拉起 serve 并做一次 `info` 握手；失败置 degraded 并返回 False（不抛）。"""
        if self._p is not None and self._p.poll() is None:
            return True
        if not os.path.isfile(self.exe):
            self._degrade("rust 二进制不存在：%s（先 cd rust && cargo build --release）"
                          % self.exe)
            return False
        env = dict(os.environ)
        env.pop("MDCG_TOKEN", None)
        env.setdefault("MDCG_EN_ZH_MAP",
                       os.path.join(_REPO, "md_cg", "semantic", "en_zh_map.json"))
        try:
            self._p = subprocess.Popen(
                [self.exe, "--root", self.root, "--serve", "--score", SCORE],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True, encoding="utf-8",
                errors="replace", env=env)
            info = self._rpc({"op": "info"})
        except Exception as e:                             # noqa: BLE001
            self._degrade("启动失败：%s: %s" % (type(e).__name__, e))
            return False
        if not isinstance(info, dict) or "score" not in info:
            self._degrade("握手失败：info 未返回 score（%r）" % (info,))
            return False
        if str(info.get("score")) != SCORE:
            self._degrade("口径不一致：进程自报 score=%r，本桥钉住 %r"
                          % (info.get("score"), SCORE))
            return False
        self.degraded, self.error = False, None
        return True

    def close(self) -> None:
        p, self._p = self._p, None
        if p is None:
            return
        try:
            p.stdin.close()
            p.wait(timeout=5)
        except Exception:                                  # noqa: BLE001
            try:
                p.kill()
            except Exception:                              # noqa: BLE001
                pass

    def _degrade(self, why: str) -> None:
        self.degraded = True
        self.error = why

    # ---- 协议 ----
    def _rpc(self, req: dict) -> dict:
        with self._lock:
            if self._p is None or self._p.poll() is not None:
                raise RuntimeError("serve 进程不在（degraded=%s, %s）"
                                   % (self.degraded, self.error))
            self._p.stdin.write(json.dumps(req, ensure_ascii=False) + "\n")
            self._p.stdin.flush()
            line = self._p.stdout.readline()
        if not line.strip():
            self._degrade("serve 无应答（进程可能已退出）")
            raise RuntimeError(self.error)
        return json.loads(line)

    # ---- 对外两面 ----
    def search(self, query: str, k: int = 10):
        """返回 `[(id, score), ...]`——与 Python `search_rrf` 的 `(id, score)` 同形。"""
        out = self._rpc({"op": "search", "query": query, "k": int(k)})
        hits = out.get("hits") or out.get("results") or []
        rows = []
        for h in hits:
            if isinstance(h, dict):
                rows.append((h.get("id"), h.get("score")))
            elif isinstance(h, (list, tuple)) and len(h) >= 2:
                rows.append((h[0], h[1]))
        return rows

    def status(self) -> dict:
        return {"backend": "rust", "exe": self.exe, "root": self.root,
                "degraded": bool(self.degraded), "error": self.error,
                "alive": bool(self._p is not None and self._p.poll() is None),
                "score": SCORE}


# ---- 进程级单例（HTTP 服务里用；测试里可直接 new 一个） ----
_BRIDGE = None
_BRIDGE_LOCK = threading.Lock()


def bridge(root: str = None, exe: str = None) -> RustBridge:
    """按 root 复用同一个桥（避免每次请求重建进程）。"""
    global _BRIDGE
    with _BRIDGE_LOCK:
        if _BRIDGE is None:
            _BRIDGE = RustBridge(root or os.environ.get("MDCG_ROOT", "."), exe)
        return _BRIDGE
