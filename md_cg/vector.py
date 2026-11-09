# -*- coding: utf-8 -*-
"""vector.py —— 第 7 路：本地语义向量（bge-small-zh-v1.5 ONNX，CPU）

为什么是 ONNX 而不是 torch/sentence-transformers：服务器 4 核 / 3.7 GB / 盘余 4.5 GB，
torch 一套 ~800 MB 且吃内存；bge-small-zh 量化版 24 MB + onnxruntime 24 MB，单条
embed 在 4 核上 ~5-15 ms，建全库索引 375 条 ~4 s。

设计取舍（写进 docstring 是因为它会被下一个人质疑）：
  · 只索引 `content_kind != "work_log"` 的节点 —— 531 条网关流水/探针属 episodic，
    进向量库会淹没语义召回（P0-b 已用 0.6 降权表达同一判断，这里保持一致）。
  · 模型缺失 / onnxruntime 缺失 / 索引缺失 一律 **返回空结果**而不是抛异常：
    检索是热路径，一路坏不许拖垮另外六路。
  · 向量归一化后存 float32，检索就是矩阵乘（375×512 微不足道）。
"""
import io
import json
import os
import threading

import numpy as np

ENV_MODEL = "MDCG_VEC_MODEL"          # onnx 路径
ENV_TOK = "MDCG_VEC_TOKENIZER"        # tokenizer.json 路径
ENV_ENABLED = "MDCG_VECTOR"           # 0 关掉这一路
INDEX_DIR = "vector"
VEC_FILE = "emb.npy"
META_FILE = "meta.json"
# 512：库里节点中位 353 字符，256 会把长节点后半段整段丢掉；
# 512 是 BGE 的训练长度上限，再长没有收益（索引体积翻倍、重建时间翻倍）。
MAX_LEN = 512
DEFAULT_MODEL = "/home/ubuntu/.mdcg/models/bge-small-zh-v1.5/model_quantized.onnx"
DEFAULT_TOK = "/home/ubuntu/.mdcg/models/bge-small-zh-v1.5/tokenizer.json"

_lock = threading.Lock()
_session = None
_tokenizer = None
_load_error = None


def enabled():
    return (os.environ.get(ENV_ENABLED) or "1").strip() not in ("0", "false", "off")


def _paths():
    return (os.environ.get(ENV_MODEL) or DEFAULT_MODEL,
            os.environ.get(ENV_TOK) or DEFAULT_TOK)


def _load():
    """惰性加载模型；失败只记一次错误，之后快速返回 None。"""
    global _session, _tokenizer, _load_error
    if _session is not None and _tokenizer is not None:
        return _session, _tokenizer
    if _load_error is not None:
        return None, None
    with _lock:
        if _session is not None and _tokenizer is not None:
            return _session, _tokenizer
        if _load_error is not None:
            return None, None
        try:
            import onnxruntime as ort
            from tokenizers import Tokenizer
            mp, tp = _paths()
            if not (os.path.exists(mp) and os.path.exists(tp)):
                raise FileNotFoundError("模型或分词器不存在：%s / %s" % (mp, tp))
            so = ort.SessionOptions()
            so.intra_op_num_threads = 2
            so.log_severity_level = 3
            _session = ort.InferenceSession(mp, so, providers=["CPUExecutionProvider"])
            tk = Tokenizer.from_file(tp)
            tk.enable_truncation(max_length=MAX_LEN)
            tk.enable_padding(length=None)
            _tokenizer = tk
        except Exception as exc:                       # noqa: BLE001
            _load_error = "%s: %s" % (type(exc).__name__, exc)
            return None, None
    return _session, _tokenizer


def available():
    s, t = _load()
    return s is not None and t is not None


def load_error():
    _load()
    return _load_error


def embed(texts):
    """返回 (n, d) float32、L2 归一化；模型不可用时返回 None。"""
    sess, tok = _load()
    if sess is None or not texts:
        return None
    encs = tok.encode_batch([str(t or "") for t in texts])
    ids = np.array([e.ids for e in encs], dtype=np.int64)
    mask = np.array([e.attention_mask for e in encs], dtype=np.int64)
    types = np.zeros_like(ids)
    feeds = {"input_ids": ids, "attention_mask": mask}
    names = {i.name for i in sess.get_inputs()}
    if "token_type_ids" in names:
        feeds["token_type_ids"] = types
    out = sess.run(None, feeds)[0]
    # CLS pooling + L2 归一化（bge 官方用法）
    v = out[:, 0, :].astype(np.float32)
    n = np.linalg.norm(v, axis=1, keepdims=True)
    n[n == 0] = 1.0
    return v / n


# ---------------------------------------------------------------- 索引

def index_dir(root):
    d = os.path.join(root, INDEX_DIR)
    os.makedirs(d, exist_ok=True)
    return d


def build(cg, root=None, skip_kinds=("work_log",), limit=0, progress=None):
    """重建向量索引。返回统计 dict（不抛异常，失败给 error 字段）。"""
    root = root or getattr(cg, "root", None) or "."
    rows = []
    for nid, e in cg.index["nodes"].items():
        layer = (e.get("layer") or "").strip()
        if layer in ("rejected", "trash"):
            continue
        r = cg.get(nid, probe=True) or {}
        fm = r.get("frontmatter") or {}
        kind = (fm.get("content_kind") or "").strip()
        if kind and kind in skip_kinds:
            continue
        body = r.get("content") or ""
        if not body.strip():
            continue
        rows.append((nid, body))
        if limit and len(rows) >= limit:
            break
    if progress:
        progress("collected", len(rows))

    vecs = []
    ids = []
    # 批大小可控：2026-11-06 22:41 用 32 条 × 512 token 重建，峰值 anon-rss
    # 1.43 GB，把整台 3.7G 的机器打到 OOM（dmesg 有 Killed process python3）。
    # 缺省降到 8：索引体积不变，峰值内存降到约 1/4，重建时间只多几秒。
    step = max(1, int(os.environ.get("MDCG_VEC_BATCH") or 8))
    for i in range(0, len(rows), step):
        chunk = rows[i:i + step]
        v = embed([b for _, b in chunk])
        if v is None:
            return {"ok": False, "error": load_error() or "embedding 不可用"}
        vecs.append(v)
        ids.extend(nid for nid, _ in chunk)
        if progress and i % (step * 8) == 0:
            progress("embedded", len(ids))
    if not vecs:
        return {"ok": False, "error": "没有可索引的节点"}
    mat = np.vstack(vecs).astype(np.float32)
    d = index_dir(root)
    np.save(os.path.join(d, VEC_FILE), mat)
    io.open(os.path.join(d, META_FILE), "w", encoding="utf-8", newline="\n").write(
        json.dumps({"ids": ids, "dim": int(mat.shape[1]), "count": len(ids),
                    "skip_kinds": list(skip_kinds),
                    "model": os.path.basename(_paths()[0])},
                   ensure_ascii=False))
    return {"ok": True, "count": len(ids), "dim": int(mat.shape[1])}


_cache = {}


def _load_index(root):
    key = os.path.abspath(root)
    hit = _cache.get(key)
    if hit:
        return hit
    d = os.path.join(root, INDEX_DIR)
    mp = os.path.join(d, META_FILE)
    vp = os.path.join(d, VEC_FILE)
    if not (os.path.exists(mp) and os.path.exists(vp)):
        _cache[key] = (None, None)
        return _cache[key]
    try:
        meta = json.load(io.open(mp, encoding="utf-8"))
        mat = np.load(vp)
        _cache[key] = (meta, mat)
    except Exception:                                  # noqa: BLE001
        _cache[key] = (None, None)
    return _cache[key]


def invalidate(root=None):
    if root is None:
        _cache.clear()
    else:
        _cache.pop(os.path.abspath(root), None)


# 0.42：按 bge-base 实测标定——相关查询中位 0.396 / 最高 0.509，无关查询
# 最高 0.329；0.30 会让相关查询 330/331 全过线（等于不筛），0.42 落在
# 「相关仍进、无关被拒」的中间带。可用 MDCG_VEC_MIN_SCORE 覆盖。
MIN_SCORE = float(os.environ.get("MDCG_VEC_MIN_SCORE") or 0.42)


def search(cg, query, k=10, root=None, min_score=None):
    """返回 [(node_id, score)]，按余弦降序；索引/模型不可用时返回 []。"""
    if not enabled():
        return []
    if min_score is None:
        min_score = MIN_SCORE
    root = root or getattr(cg, "root", None) or "."
    meta, mat = _load_index(root)
    if meta is None or mat is None or not meta.get("ids"):
        return []
    v = embed([query])
    if v is None:
        return []
    sims = mat.dot(v[0])
    order = np.argsort(-sims)[:max(k, 1)]
    out = []
    ids = meta["ids"]
    for i in order:
        s = float(sims[i])
        if s < min_score:
            break
        out.append((ids[int(i)], s))
    return out


def stats(root):
    meta, mat = _load_index(os.path.abspath(root))
    if meta is None:
        return {"ok": False, "built": False, "error": load_error()}
    return {"ok": True, "built": True, "count": meta.get("count"),
            "dim": meta.get("dim"), "model": meta.get("model"),
            "skip_kinds": meta.get("skip_kinds"),
            "enabled": enabled(), "matrix_bytes": int(getattr(mat, "nbytes", 0))}
