# -*- coding: utf-8 -*-
"""md_cg · 真源索引契约层（P0）——通用层 + 细化层，零解码 / 零模型 / 零第三方依赖。

设计依据：`docs/plans/真源索引_通用机制_v0.3.md`（使用者裁定 2026-09-28）。
本模块只做**契约与纯函数**：把任意文件变成「可寻址单位」，并提供按单位回读。
落库（写认知图 ref 节点）在 P1 接 `refindex.add_items`，本模块不写任何状态。

三层（v0.3）：
  ① **通用层**（任意文件）：条目 = {path, name, type, size, mtime, file_hash}，span=whole，
     text_view = 文件名 + 路径 + 类型（+ 伴随文本）。类型只进检索面，**不决定能否索引**。
  ② **细化层**（仅当真源本身可读文本）：按章节切成 line 区间单位（每单位自带区间哈希），
     并产摘要/简介；带 `# 生效条件：` 一类 CCG 行的走既有 condition_space 同源机制。
  ③ **伴随文本**（多模态的语义通道）：同名 sidecar / 目录说明 —— 它们**本身即真源**，
     由调用方照常索引；本模块负责**发现并挂到通用层条目上**（`companions()`）。

为什么不需要解码器与模型（v0.3 撤回项）：通用层是**整文件粒度**，不做时间点/区域切片；
语义面走伴随文本而非模型产出。二者降级为后续可选（方案 §12）。

区间单位（`unit`）本版只有两种：`whole`（整文件）与 `line`（文本行区间）。`time` / `region` /
`byte` 三种 locator 属后续可选，**本模块显式不实现**（不静默假装支持）。

生效条件：入参 path 指向常规文件（`os.path.isfile` 为真）；`units()` 对不可读/无权限文件返回
只含通用层单位的列表（不抛），`read_unit('whole')` 一律返回原始字节。
不适用于：无文件实体的真源（须先物化）；跨机指针（路径为绝对路径，跨机需另立锚）。
"""
from __future__ import annotations

import hashlib
import io
import os

CHUNK = 1 << 20          # 文件哈希分块（大文件不整读进内存）
SNIFF_BYTES = 4096       # 类型嗅探与「可读文本」判定取的前缀长度

# 本版实现的 unit 类型；time/region/byte 属后续可选（方案 §12），此处显式声明未实现
UNITS = ("whole", "line")

TEXT_SUFFIX = {
    ".md": "text/markdown", ".markdown": "text/markdown", ".txt": "text/plain",
    ".json": "application/json", ".jsonl": "application/x-ndjson",
    ".yaml": "application/yaml", ".yml": "application/yaml",
    ".csv": "text/csv", ".tsv": "text/tab-separated-values",
    ".py": "text/x-python", ".rs": "text/x-rust", ".ts": "text/x-typescript",
    ".js": "text/javascript", ".sh": "text/x-shellscript", ".toml": "application/toml",
    ".ini": "text/plain", ".cfg": "text/plain", ".log": "text/plain",
    ".html": "text/html", ".htm": "text/html", ".xml": "text/xml",
    ".sql": "text/x-sql", ".c": "text/x-c", ".h": "text/x-c", ".cpp": "text/x-c++",
}
# 魔数 → 类型（只列常见；未命中即回落扩展名 / octet-stream，绝不因未知类型拒绝入索引）
MAGIC = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"), (b"GIF89a", "image/gif"),
    (b"RIFF", "audio-or-video/riff"),           # 细分再看子类型（WAVE / AVI）
    (b"ID3", "audio/mpeg"), (b"\xff\xfb", "audio/mpeg"),
    (b"OggS", "audio-or-video/ogg"),
    (b"fLaC", "audio/flac"),
    (b"\x00\x00\x00\x18ftyp", "video/mp4"),
    (b"\x1aE\xdf\xa3", "video/webm-or-matroska"),
    (b"PK\x03\x04", "application/zip"),
    (b"%PDF-", "application/pdf"),
    (b"BZh", "application/x-bzip2"),
    (b"\x1f\x8b", "application/gzip"),
    (b"\x7fELF", "application/x-elf"),
    (b"MZ", "application/x-dosexec"),
)


# 生效条件：path 为字符串且可 os.stat；返回 {path, name, dir, suffix, size, mtime, file_hash}，
# 路径取 abspath（真源身份要跨调用稳定）；file_hash 为文件级 sha256（P0 的 staleness 判据）。
def src_id(path: str) -> dict:
    """真源身份：**文件名 / 路径 / 大小 / 时间 / 文件哈希**（索引的通用层主键面）。"""
    ap = os.path.abspath(path)
    st = os.stat(ap)
    return {
        "path": ap,
        "name": os.path.basename(ap),
        "dir": os.path.dirname(ap),
        "suffix": os.path.splitext(ap)[1].lower(),
        "size": st.st_size,
        "mtime": st.st_mtime,
        "file_hash": file_hash(ap),
    }


def file_hash(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(CHUNK)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


# 生效条件：prefix 为 bytes 时按 MAGIC 表逐条 startswith 判定，首个命中即返回其类型；
# 未命中回落 suffix 表；仍未命中返回 "application/octet-stream"（未知类型**不是**拒绝理由）。
def sniff_type(path: str, prefix: bytes = None) -> str:
    """类型判据＝魔数优先、扩展名兜底（零依赖）；只用于检索面与分组，不决定可索引性。"""
    if prefix is None:
        try:
            with open(path, "rb") as f:
                prefix = f.read(SNIFF_BYTES)
        except OSError:
            prefix = b""
    for magic, t in MAGIC:
        if prefix.startswith(magic):
            if magic == b"RIFF":
                if prefix[8:12] == b"WAVE":
                    return "audio/wav"
                if prefix[8:12] == b"AVI ":
                    return "video/x-msvideo"
            return t
    return TEXT_SUFFIX.get(os.path.splitext(path)[1].lower(),
                           "application/octet-stream")


# 生效条件：prefix 含 NUL 字节即判不可读；否则尝试 utf-8 严格解码，成功即判可读文本。
# 语义边界：只读前缀，宁少判不多判（截断在多字节字符中间的假阴性可接受——细化层缺席不致命）。
def is_text_readable(prefix: bytes) -> bool:
    if b"\x00" in prefix:
        return False
    try:
        prefix.decode("utf-8")
        return True
    except UnicodeDecodeError:
        return False


def _read_prefix(path: str) -> bytes:
    try:
        with open(path, "rb") as f:
            return f.read(SNIFF_BYTES)
    except OSError:
        return b""


# 生效条件：text 与 1-based 行区间给定；返回该区间的哈希——**委托唯一实现**
# `codeindex.region_hash`（sha1 前 12 位）。其 docstring 明写「必须是唯一定义：索引侧与回读侧
# 共用同一个函数」，两侧各写一份就会让漂移检测悄悄失效（永远 hash_match=True）。
# 本模块 P0 初版在此自写了 sha256 第二份，被守卫 5b/5c 当场抓出——本函数即那次修正的产物。
def region_hash(text: str, lineno: int, end: int) -> str:
    from . import codeindex
    return codeindex.region_hash(text.split("\n"), lineno, end)


# 生效条件：path 为常规文件时返回单位列表——**至少一条**通用层单位（span=whole，任意文件）；
# 若前缀可读文本则追加细化层 line 单位（章节来自 docindex.extract，无提取器后缀则不切）。
# 返回的每条单位形如 {src, span, span_hash, text_view, reader}；不写任何状态。
def units(path: str, *, with_sections: bool = True) -> list[dict]:
    """把任意文件变成可寻址单位：通用层恒在（含伴随文本挂载），细化层仅对可读文本追加。"""
    sid = src_id(path)
    prefix = _read_prefix(path)
    typ = sniff_type(path, prefix)
    sid["type"] = typ
    out = [{
        "src": sid,
        "span": {"unit": "whole"},
        "span_hash": sid["file_hash"],
        "text_view": "文件 %s（%s）｜路径 %s" % (sid["name"], typ, sid["path"]),
        "reader": {"kind": "whole"},
    }]
    # 伴随文本属**通用层**：多模态文件的语义面就靠它（P0 初版误挂在「可读文本」分支里，
    # 而媒体根本不进那个分支 ⇒ 恰好废掉方案的 §10.3 语义通道，被守卫 6b 抓出）
    comps = companions(sid["path"])
    if comps:
        out[0]["text_view"] += "｜伴随文本 " + "、".join(c["name"] for c in comps)
        out[0]["companions"] = [c["path"] for c in comps]
        out[0]["companion_kinds"] = sorted({c["kind"] for c in comps})
    if not is_text_readable(prefix):
        return out
    try:
        text = io.open(path, encoding="utf-8").read()
    except (OSError, UnicodeDecodeError):
        return out
    if not with_sections:
        return out
    try:
        from . import docindex
        items = docindex.extract(text, path=sid["path"])
    except Exception:  # noqa: BLE001  —— 无提取器/解析失败：停在通用层，不抛
        return out
    lines = text.split("\n")
    for it in items:
        lineno = int(it.get("lineno") or 1)
        end = int(it.get("end") or lineno)
        head = it.get("heading") or it.get("name") or ""
        body = "\n".join(lines[lineno - 1:end])
        out.append({
            "src": sid,
            "span": {"unit": "line", "start": lineno, "end": end,
                     "anchor": it.get("anchor"), "level": it.get("level"),
                     "heading_path": it.get("heading_path")},
            # 哈希单一实现：优先用 docindex 已算的（与 region_hash 同源），缺则现算
            "span_hash": it.get("hash") or region_hash(text, lineno, end),
            "text_view": ("%s ｜ %s" % (sid["name"], head)).strip(),
            "reader": {"kind": "line"},
            # CCG 条件面：与正文同源（docindex.condition_space 解析 `# 生效条件：` 行）
            "condition_space": (docindex.condition_space(it)
                                if hasattr(docindex, "condition_space") else None),
            "summary": body[:200],
        })
    return out


# 生效条件：同目录下存在与媒体同主的可读文本→视为伴随文本；判定＝同 stem 且后缀属
# 可读文本集合（.md/.txt/.json/.caption/.prompt），另加同目录 README/_index.md（目录说明）。
# 只发现与返回路径，不索引、不改动任何文件。
def companions(path: str) -> list[dict]:
    """伴随文本发现（多模态的语义通道）：同名 sidecar + 目录说明。"""
    d = os.path.dirname(os.path.abspath(path))
    stem = os.path.splitext(os.path.basename(path))[0]
    found = []
    for suffix in (".md", ".txt", ".json", ".caption", ".prompt"):
        p = os.path.join(d, stem + suffix)
        if os.path.isfile(p) and os.path.abspath(p) != os.path.abspath(path):
            found.append({"path": os.path.abspath(p), "name": os.path.basename(p),
                          "kind": "sidecar"})
    for name in ("README.md", "_index.md", "INDEX.md"):
        p = os.path.join(d, name)
        if os.path.isfile(p):
            found.append({"path": os.path.abspath(p), "name": name, "kind": "dir_doc"})
            break
    return found


# 生效条件：unit 含 span；unit.span.unit == "whole" 时返回原文件字节；== "line" 时按
# src.path 读文本并返回 [start, end] 行；未知 unit 返回 ok=False 与 error（**不静默**）。
# with_hash=True 时附带 span_hash 复核结果（回读文本重算 vs unit 内记录）。
def read_unit(unit: dict, *, with_hash: bool = True) -> dict:
    """按单位回读真源：通用层返回整文件字节，细化层返回行区间文本。"""
    src = unit.get("src") or {}
    path = src.get("path") or ""
    span = unit.get("span") or {}
    kind = span.get("unit")
    if kind == "whole":
        try:
            with open(path, "rb") as f:
                data = f.read()
        except OSError as e:
            return {"ok": False, "error": "读取失败：%s" % e}
        out = {"ok": True, "bytes": len(data), "hash": hashlib.sha256(data).hexdigest()}
        if with_hash:
            out["hash_match"] = out["hash"] == unit.get("span_hash")
        return out
    if kind == "line":
        try:
            text = io.open(path, encoding="utf-8").read()
        except (OSError, UnicodeDecodeError) as e:
            return {"ok": False, "error": "读取失败：%s" % e}
        a = int(span.get("start") or 1)
        b = int(span.get("end") or 1)
        seg = "\n".join(text.split("\n")[max(0, a - 1):max(max(0, a - 1), b)])
        out = {"ok": True, "text": seg, "lines": b - a + 1, "hash": region_hash(text, a, b)}
        if with_hash:
            out["hash_match"] = out["hash"] == unit.get("span_hash")
        return out
    return {"ok": False,
            "error": "未知 span.unit=%r（本版支持 %s；time/region/byte 属后续可选）"
                     % (kind, "/".join(UNITS))}


# ==========================================================================
# 日志真源适配器（P1）：DSH 会话日志 → 真源身份 + 区间表
#
# 日志这一路与普通文件的差别只有一处（v0.3 §9 裁定①）：**真源是 zstd JSONL，
# 可读区间却落在确定性转写上**。所以适配器把两件事分开交付——
#   · 真源身份（`session_src_id`）：日志本体的 7 键 + 会话身份 4 键；
#   · 区间表（`log_units`）：span 取自转写（docindex 切分），src 指向日志本体。
# 二者都只是**把既有单点拼起来**：身份仍由 `src_id` 定、区间仍由 `docindex.extract`
# 切、哈希仍由 `region_hash` 算。本模块不写任何状态、不 import scripts。
# ==========================================================================

#: `srcindex.session_src_id` 认的 path_mode——见函数 docstring 的暴露面说明
SRC_PATH_MODES = ("abs", "rel", "hash")


# 生效条件：log_path 为可 stat 的常规文件；path_mode 属 SRC_PATH_MODES（否则抛 ValueError）；
# 返回 src_id 的 7 键 + {kind, session_uuid, workspace, sensitivity} 4 键，共 11 键。
def session_src_id(log_path: str, *, session_uuid: str = None,
                   workspace: str = None, sensitivity: str = "internal",
                   path_mode: str = "abs", base: str = None) -> dict:
    """DSH 会话日志的真源身份：`src_id` 7 键 + 会话身份 4 键（只做加法）。

    `file_hash` 是 staleness 的**唯一**判据（P0 裁定），故任何降级都不得动它。

    `path_mode` 是**暴露面降级开关**：src 含真源绝对路径 + 会话 uuid，而节点是
    internal 档（跨会话共享可见，dsh_log_index.py:16-21 的共享档语义）⇒ 任何能读
    该节点的会话都拿到本机日志绝对路径与会话 uuid。三档语义：
      · `abs`（缺省）——绝对路径，探测能力完整；
      · `rel`——相对 `base`（缺省取日志自身目录）且 **`dir` 一并置空**：留下绝对
        目录等于把 rel 刚省下的又落回库里；
      · `hash`——**path 置空**。
    rel 与 hash 两档都不支持探测（`logref.probe_src` 返回 unresolved，属「明确
    不探测」而非静默通过——不猜、不假装能核）；探测能力完整只有 `abs`。
    """
    sid = src_id(log_path)
    ap = sid["path"]
    if path_mode == "rel":
        b = os.path.abspath(base) if base else os.path.dirname(ap)
        sid["path"] = os.path.relpath(ap, b).replace("\\", "/")
        sid["dir"] = ""
    elif path_mode == "hash":
        sid["path"] = ""
        sid["dir"] = ""
    elif path_mode != "abs":
        raise ValueError("未知 path_mode=%r（支持 %s）"
                         % (path_mode, "/".join(SRC_PATH_MODES)))
    return {**sid, "kind": "dsh_session_log", "session_uuid": session_uuid,
            "workspace": workspace, "sensitivity": sensitivity}


# 生效条件：transcript_path 为可读 md、src 为日志真源身份（session_src_id 的产物）；
# 返回按 docindex 章节切分的区间表，每条 {src, span(unit=line), span_hash, text_view,
# reader, item}；`item` 是**落库口径**的原始条目（path 已按入参 path 定）。
def log_units(transcript_path: str, src: dict, *, path: str = None) -> list[dict]:
    """日志真源的区间表：span 落在**确定性转写**上，src 指向 zstd 日志本体。

    `path` 是 docindex 的寻址键面（`path#heading_path` 里的 path，须与最终写进
    `doc_ref.path` 的值同源），缺省回落转写的 basename——**缺省只用于单会话、
    单转写根的临时场景**：多工作区同 sid 时会撞 id（见 `md_cg/test_logref.py`
    的 path 口径守卫）。
    """
    from . import docindex          # 局部 import：与 units() 同款，避免模块级循环依赖
    text = io.open(transcript_path, encoding="utf-8").read()
    p = path or os.path.basename(transcript_path)
    out = []
    for it in docindex.extract(text, path=p):
        lineno = int(it.get("lineno") or 1)
        end = int(it.get("end") or lineno)
        out.append({
            "src": src,
            "span": {"unit": "line", "start": lineno, "end": end,
                     "anchor": it.get("anchor"), "level": it.get("level"),
                     "heading_path": it.get("heading_path")},
            "span_hash": it.get("hash") or region_hash(text, lineno, end),
            "text_view": "%s ｜ %s" % (src.get("name") or "", it.get("heading") or ""),
            "reader": {"kind": "line"},
            "item": it,
        })
    return out


# 生效条件：无（诊断用）；返回本模块对「通用层/细化层」的能力自陈，供文档与守卫比对。
def capability() -> dict:
    return {"units": list(UNITS),
            "universal_layer": "任意常规文件（span=whole）",
            "detail_layer": "仅可读文本（line 区间 + 摘要 + CCG 条件面）",
            "companions": ["sidecar", "dir_doc"],
            "not_implemented": ["time", "region", "byte"],
            "deps": [], "writes_state": False}
