# -*- coding: utf-8 -*-
"""md_cg · 设备驱动（记忆 OS #3）：把外部会话流接进认知图

设计：
  Source（事件源）—— 把某种外部存储解析成统一事件流：
      {"t": 毫秒时间戳, "seq": 序号, "role": ..., "text": ..., "session": ..., "cwd": ...}
  Ingestor（摄取器）—— 增量 watermark + 去重 + 写节点 + 自动 fix-pair 挖掘。

内置源：
  · JsonlSource        —— 通用 JSONL（每行一个事件对象）
  · DSHSessionSource   —— DeepSeek Harness 会话（~/.dsh/sessions/**/session.jsonl[.zstd]）
                          zstd 为**可选**依赖：缺失时优雅降级（跳过 .zstd 文件并告警）

默认敏感度：会话内容是私有记忆 → sensitivity="private"（避免落入公开根）。

零第三方依赖（zstd 为可选增强）。
"""
from __future__ import annotations

import glob
import json
import os
import time

from .security import DEFAULT_SENSITIVITY

# 会话事件的默认落层与敏感度
SESSION_LAYER = "contextual"
SESSION_SENSITIVITY = "private"


# --------------------------------------------------------------------------
# 事件源
# --------------------------------------------------------------------------

class Source:
    """事件源基类。"""

    name = "source"

    def events(self):
        raise NotImplementedError

    def key(self):
        """源的稳定标识（用于 watermark）。"""
        return self.name


class JsonlSource(Source):
    """通用 JSONL 会话源。

    每行是事件对象；字段映射可配置：
      t_key      —— 时间戳字段（默认 "time"，也接受 ISO 字符串）
      role_key   —— 角色字段（默认 "role"）
      text_key   —— 文本字段（默认 "text"）
    """

    def __init__(self, path: str, name: str = None, t_key="time", role_key="role",
                 text_key="text", default_role="user"):
        self.path = path
        self.name = name or ("jsonl:" + os.path.basename(path))
        self.t_key, self.role_key, self.text_key = t_key, role_key, text_key
        self.default_role = default_role

    def key(self):
        return self.name

    def _ts(self, o):
        v = o.get(self.t_key)
        if isinstance(v, (int, float)):
            return float(v) * (1000.0 if v < 1e12 else 1.0)
        if isinstance(v, str):
            try:
                return time.mktime(time.strptime(v[:19], "%Y-%m-%dT%H:%M:%S")) * 1000
            except ValueError:
                return 0.0
        return 0.0

    def events(self):
        if not os.path.exists(self.path):
            return
        with open(self.path, encoding="utf-8", errors="replace") as f:
            for i, line in enumerate(f):
                line = line.strip()
                if not line:
                    continue
                try:
                    o = json.loads(line)
                except ValueError:
                    continue
                text = o.get(self.text_key)
                if not text:
                    continue
                yield {"t": self._ts(o), "seq": o.get("seq", i),
                       "role": o.get(self.role_key) or self.default_role,
                       "text": str(text), "session": o.get("session"),
                       "cwd": o.get("cwd")}


def _zstd_reader(path):
    """返回可读的文本迭代器；zstd 不可用返回 None。"""
    import io
    try:
        import zstandard as zstd
    except ImportError:
        return None
    with open(path, "rb") as f:
        raw = zstd.ZstdDecompressor().stream_reader(f).read()
    return io.StringIO(raw.decode("utf-8", errors="replace"))


class DSHSessionSource(Source):
    """DeepSeek Harness 会话源。

    事件映射：
      user/message      → role=user
      assistant/message → role=assistant（只取 content[].text，reasoning 默认丢弃）
      tool/call         → role=command（"name(args)" 形式）
      tool/result       → role=tool-output
    """

    def __init__(self, path: str, include_reasoning: bool = False):
        self.path = path
        self.include_reasoning = include_reasoning
        self.name = "dsh:" + os.path.basename(os.path.dirname(path))

    def key(self):
        return self.name

    @staticmethod
    def discover(root: str = None, limit: int = None):
        root = root or os.path.join(os.path.expanduser("~"), ".dsh", "sessions")
        files = glob.glob(os.path.join(root, "**", "session.jsonl"), recursive=True)
        files += glob.glob(os.path.join(root, "**", "session.jsonl.zstd"), recursive=True)
        files.sort(key=lambda p: -os.path.getsize(p))
        return files[:limit] if limit else files

    def _lines(self):
        if self.path.endswith(".zstd"):
            fh = _zstd_reader(self.path)
            if fh is None:
                raise RuntimeError("zstd 不可用（pip install zstandard），跳过该会话")
            try:
                yield from fh
            finally:
                fh.close()
        else:
            with open(self.path, encoding="utf-8", errors="replace") as f:
                yield from f

    @staticmethod
    def _text_of(content):
        """content 可能是 [{type,text}] 或字符串。"""
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for c in content:
                if isinstance(c, dict):
                    if c.get("type") in ("text", "input-text") and c.get("text"):
                        parts.append(str(c["text"]))
                elif isinstance(c, str):
                    parts.append(c)
            return "\n".join(parts)
        return ""

    def events(self):
        sess = None
        cwd = None
        for line in self._lines():
            line = line.strip()
            if not line:
                continue
            try:
                o = json.loads(line)
            except ValueError:
                continue
            t = o.get("type")
            data = o.get("data") or {}
            if t == "session":
                sess, cwd = o.get("id"), o.get("cwd")
                continue
            ev = {"t": float(o.get("time") or 0), "seq": o.get("seq"),
                  "session": sess, "cwd": cwd}
            if t == "user/message":
                ev["role"], ev["text"] = "user", self._text_of(data.get("content"))
            elif t == "assistant/message":
                msg = data.get("message") or {}
                ev["role"] = "assistant"
                ev["text"] = self._text_of(msg.get("content"))
                if self.include_reasoning:
                    for c in (msg.get("content") or []):
                        if isinstance(c, dict) and c.get("type") == "reasoning" \
                                and c.get("text"):
                            ev["text"] = (ev["text"] or "") + "\n[reasoning] " + str(c["text"])
            elif t == "tool/call":
                ev["role"] = "command"
                ev["text"] = f"{data.get('name')}({data.get('arguments') or ''})"
            elif t == "tool/result":
                msg = data.get("message") or {}
                inner = msg.get("content") or []
                txt = ""
                if inner and isinstance(inner[0], dict):
                    txt = self._text_of(inner[0].get("content"))
                ev["role"], ev["text"] = "tool-output", txt
            else:
                continue
            if ev.get("text"):
                yield ev


# --------------------------------------------------------------------------
# 摄取器
# --------------------------------------------------------------------------

class Ingestor:
    """增量摄取：watermark + 去重 + 写节点 + 自动 fix-pair 挖掘。

    watermark 文件：<root>/_sources.json
        {source_key: {"t": 最后时间戳(ms), "seq": 最后序号, "count": 已摄取条数}}
    """

    def __init__(self, cg, layer: str = SESSION_LAYER,
                 sensitivity: str = SESSION_SENSITIVITY):
        self.cg = cg
        self.layer = layer
        self.sensitivity = sensitivity
        self.path = os.path.join(cg.root, "_sources.json")

    # ---- watermark ----

    def _load(self):
        if os.path.exists(self.path):
            try:
                with open(self.path, encoding="utf-8") as f:
                    d = json.load(f)
                if isinstance(d, dict):
                    return d
            except (ValueError, OSError):
                pass
        return {"schema": 1, "sources": {}}

    def _save(self, d):
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.path)

    def watermark(self, key: str):
        return self._load()["sources"].get(key, {})

    def watermarks(self):
        return dict(self._load()["sources"])

    # ---- 摄取 ----

    def ingest(self, source, mine_fix_pairs: bool = True, max_events: int = None,
               dry_run: bool = False):
        """摄取一个源的新事件。返回统计。

        去重键：(session, seq) —— 同一事件不重复入库。
        增量：只处理 (t, seq) 大于 watermark 的事件。
        """
        key = source.key()
        wm = self.watermark(key)
        last_t, last_seq = float(wm.get("t") or 0), wm.get("seq")
        new_events, seen = [], set()
        for ev in source.events():
            if ev.get("t", 0) < last_t:
                continue
            if ev.get("t", 0) == last_t and last_seq is not None \
                    and isinstance(ev.get("seq"), int) and ev["seq"] <= last_seq:
                continue
            dedup = (ev.get("session"), ev.get("seq"))
            if dedup in seen:
                continue
            seen.add(dedup)
            new_events.append(ev)
            if max_events and len(new_events) >= max_events:
                break

        written, ids, denied = 0, [], 0
        if not dry_run:
            for ev in new_events:
                nid = "src_%s_%s" % (_sig(key)[:6], _sig(
                    f"{ev.get('session')}:{ev.get('seq')}")[:10])
                if nid in self.cg.index["nodes"]:
                    continue          # 幂等
                body = ("# 功能名：会话事件\n"
                        f"# 生效条件：检索「{str(ev.get('text'))[:20]}」\n"
                        "# 子功能：记录会话事件\n"
                        f"# 执行：{str(ev.get('text'))[:80]}\n"
                        "# 验证方式：data（会话原始记录）\n"
                        "# 不适用条件：其它会话\n\n"
                        f"{ev.get('text')}\n")
                try:
                    self.cg.add(nid, body, layer=self.layer, role=ev.get("role"),
                                tags=["session", key], sensitivity=self.sensitivity,
                                verification_basis="data",
                                condition_space={"observation_position": key,
                                                 "observation_tool": "会话流",
                                                 "time_window": [ev.get("t") or 0,
                                                                 ev.get("t") or 0]})
                except Exception as exc:   # noqa: BLE001 —— 权限/层错误不中断整批
                    denied += 1
                    self.last_error = f"{type(exc).__name__}: {exc}"
                    continue
                ids.append(nid)
                written += 1

        result = {"source": key, "new_events": len(new_events), "written": written,
                  "denied": denied, "ids": ids, "dry_run": dry_run,
                  "sensitivity": self.sensitivity}
        if denied and getattr(self, "last_error", None):
            result["last_error"] = self.last_error
            result["hint"] = ("会话内容默认 sensitivity=private；"
                              "调用方需 MDCG_CLEARANCE=private 才能写入")
        # 自动 fix-pair 挖掘（对标 deja-vu：错误→修复）
        if mine_fix_pairs and new_events and not dry_run:
            result["fix_pairs"] = self.cg.mine_fix_pairs(
                [{"role": e.get("role"), "text": e.get("text")} for e in new_events])

        if new_events and not dry_run:
            d = self._load()
            last = new_events[-1]
            d["sources"][key] = {
                "t": last.get("t") or last_t,
                "seq": last.get("seq"),
                "count": (wm.get("count") or 0) + written,
                "updated_at": time.time(),
                "path": getattr(source, "path", None),
            }
            self._save(d)
        return result


def _sig(text: str, n: int = 12) -> str:
    import hashlib
    return hashlib.sha1((text or "").encode("utf-8")).hexdigest()[:n]
