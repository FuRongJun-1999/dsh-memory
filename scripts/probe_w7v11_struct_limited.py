# -*- coding: utf-8 -*-
"""W7v11 第 3 组 · 结构性局限取证（**只读**）

两件取证，供 `docs/eval/W7v11_结构面局限取证_v0.1.md` 引用：

 甲 `fastpath`：§1.6.8 结构互补 —— `md_cg/refindex._fast_path_verdict` 的实库触发读数
     （跳过量 / 探测量 / stale 量 / 水位-节点不一致量），**在役库只读统计**。
     调用真实现 `refindex._fast_path_verdict`（五项全等判据唯一实现）与真解析器
     `nodefile.loads`；不实例化 `MdCG`（避免 makedirs / sweep_stale_temps / atexit flush
     任何写面），改用只读 cg shim（仅 `get(nid)` 复刻 `MdCG.get` 的 frontmatter 解析）。

 丁 `sustain`：§1.6.1 持续运行 —— 长跑周期读数
     ① 心跳戳（`~/.mdcg/sustain/<name>.stamp`）：uptime / last_tick_done / last_tick_error；
     ② `_sustain.jsonl`（heal 巡检台账）：最近周期时间 / 周期间隔分布 / 最长连续无断区间 / 断点。

**只读边界**：本脚本只读、绝不写库根（不 flush、不 append、不 compact、不 touch 源文件）；
`sustain` 只 open(...,'r')。库根经 `--root` 或缺省环境变量 `MDCG_ROOT` 传入，
脚本内不写任何本机绝对路径字面量。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

# 心跳戳目录：显式 --stamp-dir → MDCG_SUSTAIN_DIR → ~/.mdcg/sustain（与 sustain.net_dir 同序）
def _stamp_dir(explicit: str = None) -> str:
    d = explicit or os.environ.get("MDCG_SUSTAIN_DIR")
    if d:
        return d
    return os.path.join(os.path.expanduser("~"), ".mdcg", "sustain")


def _iso(ts: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(ts))


# --------------------------------------------------------------------------
# 甲 · _fast_path_verdict 实库触发读数（只读）
# --------------------------------------------------------------------------

class _ROGet:
    """只读 cg shim：仅复刻 `MdCG.get` 的「索引条目 → 节点 frontmatter」解析。

    真 `MdCG.get` 还做 `_open_content`（涉密钥解密）与 `_maybe_reload_index`
    （写面代际签名比对）；此处不涉密文解密——`ref_of` 只消费 frontmatter，
    无 ref 的节点本就落回退路径。差异只影响「密文节点」的 covered 计数，
    不影响五项全等跳过的判据本身（已在文档如实标注）。
    """

    def __init__(self, root: str, nodes: dict):
        from md_cg import nodefile
        self.root = root
        self.nodes = nodes
        self._nf = nodefile
        self._fm_cache = {}

    def get(self, nid: str):
        e = self.nodes.get(nid)
        if not e:
            return None
        rel = e.get("path") or ""
        p = os.path.join(self.root, rel.replace("/", os.sep))
        if p in self._fm_cache:
            fm, content = self._fm_cache[p]
        else:
            try:
                with open(p, encoding="utf-8") as f:
                    fm, content = self._nf.loads(f.read())
            except Exception:
                return None
            self._fm_cache[p] = (fm, content)
        return {"id": nid, "frontmatter": fm, "content": content, "path": rel}


def cmd_fastpath(root: str, sample: int = 0) -> dict:
    from md_cg import refindex, nodefile  # noqa: F401

    idx = json.load(open(os.path.join(root, "_index.json"), encoding="utf-8"))
    nodes = idx.get("nodes") or {}
    led = refindex.Ledger(root)
    files = led.load().get("files") or {}
    cg = _ROGet(root, nodes)

    out = {
        "cg_root_placeholder": "<库根>",
        "index_nodes": len(nodes),
        "ledger_files": len(files),
        "watermark_nodes": 0,      # 水位条目内、且 id 在索引节点集内的记录数
        "covered": 0,              # 取回节点且有 ref
        "not_covered": 0,          # 取不回 / 无 ref（落回退路径）
        "agree_unchanged_skip": 0,      # 五项全等 + 源 size/mtime 未变 ⇒ probe=None（跳过）
        "probe_with_unchanged_src": 0,  # probe 非 None 但源未变（必为 mismatch 面）——语义标注用
        "mismatch": 0,                  # 五项不全等（归因行，不改判定）
        "probe_needed": 0,          # probe 非 None（需读源）
        "src_unchanged": 0,
        "src_changed": 0,
        "src_stat_fail": 0,
        "probe_status": {},         # 对 probe 面跑 probe_ref 的状态分布
        "stale": 0, "dangling": 0, "unresolved": 0, "error": 0, "ok": 0,
        "examples_skip": [], "examples_mismatch": [],
    }

    seen_ids = set()
    for key in sorted(files):
        e = files[key]
        rel = e.get("path") or ""
        src_root = e.get("root") or os.path.dirname(key)
        try:
            st = os.stat(key)
            unchanged = (e.get("size") == st.st_size
                         and abs(float(e.get("mtime") or 0.0) - st.st_mtime) < 1e-6)
            out["src_unchanged" if unchanged else "src_changed"] += 1
        except OSError:
            unchanged = False
            out["src_stat_fail"] += 1
        for n in (e.get("nodes") or []):
            nid = n.get("id")
            if nid not in nodes:
                continue
            out["watermark_nodes"] += 1
            if nid in seen_ids:
                continue
            seen_ids.add(nid)
            v = refindex._fast_path_verdict(cg, n, e, rel, src_root, unchanged)
            if not v["covered"]:
                out["not_covered"] += 1
                continue
            out["covered"] += 1
            if v["mismatch"]:
                out["mismatch"] += 1
                if len(out["examples_mismatch"]) < 3:
                    out["examples_mismatch"].append(v["mismatch"])
            if v["probe"] is not None:
                out["probe_needed"] += 1
                # probe 非 None 且源未变 ⇒ 必为 mismatch 面（agree+unchanged 会跳过）
                if unchanged:
                    out["probe_with_unchanged_src"] += 1
                # 真探源：判 stale / dangling / unresolved / ok
                if sample and out["probe_needed"] > sample:
                    continue
                p = refindex.probe_ref(v["probe"])
                out["probe_status"][p["status"]] = out["probe_status"].get(p["status"], 0) + 1
                if p["status"] == "stale":
                    out["stale"] += 1
                elif p["status"] == "dangling":
                    out["dangling"] += 1
                elif p["status"] == "unresolved":
                    out["unresolved"] += 1
                elif p["status"] == "error":
                    out["error"] += 1
                else:
                    out["ok"] += 1
                if len(out["examples_skip"]) < 0:
                    pass
            else:
                out["agree_unchanged_skip"] += 1
                if len(out["examples_skip"]) < 3:
                    out["examples_skip"].append({"node_id": nid, "path": rel})
    # agree_unchanged_skip 的语义即「跳过」
    out["probe_rate"] = (round(out["probe_needed"] / out["covered"], 4)
                         if out["covered"] else None)
    return out


# --------------------------------------------------------------------------
# 丁 · 长跑周期读数（只读）
# --------------------------------------------------------------------------

def _read_stamp(name: str, d: str) -> dict:
    # 命名与 sustain.stamp_path 同源：heartbeat.<name>.stamp
    p = os.path.join(d, "heartbeat.%s.stamp" % name)
    if not os.path.isfile(p):
        return {"absent": True, "path_name": "heartbeat.%s.stamp" % name}
    rec = json.load(open(p, encoding="utf-8"))
    rec["_mtime"] = os.path.getmtime(p)
    rec["_mtime_iso"] = _iso(rec["_mtime"])
    rec["_now_age_s"] = round(time.time() - rec["_mtime"], 1)
    return rec


def _stream_times(path: str, key: str = "t"):
    """流式读 jsonl，产出每行的 key 字段（float）。不把整文件读进内存。"""
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except Exception:
                continue
            v = d.get(key)
            if isinstance(v, (int, float)):
                yield float(v)


def _interval_stats(ts: list) -> dict:
    ts = sorted(ts)
    if len(ts) < 2:
        return {"n": len(ts)}
    gaps = [ts[i + 1] - ts[i] for i in range(len(ts) - 1)]
    g = sorted(gaps)

    def pct(p):
        return g[min(len(g) - 1, int(len(g) * p))]
    return {
        "n": len(ts),
        "span_s": round(ts[-1] - ts[0], 1),
        "span_iso": "%s → %s" % (_iso(ts[0]), _iso(ts[-1])),
        "last_iso": _iso(ts[-1]),
        "last_age_s": round(time.time() - ts[-1], 1),
        "gap_min_s": round(g[0], 1),
        "gap_p50_s": round(pct(0.50), 1),
        "gap_p90_s": round(pct(0.90), 1),
        "gap_max_s": round(g[-1], 1),
    }


def _longest_run(ts: list, thresh_s: float) -> dict:
    """最长连续无断区间：相邻记录间隔 ≤ thresh 视为连续，超阈值为断点。"""
    ts = sorted(ts)
    if not ts:
        return {"absent": True}
    runs = []
    start = ts[0]
    prev = ts[0]
    breaks = []
    for t in ts[1:]:
        if t - prev > thresh_s:
            runs.append((start, prev))
            breaks.append({"at_iso": _iso(prev), "next_iso": _iso(t),
                           "gap_s": round(t - prev, 1)})
            start = t
        prev = t
    runs.append((start, prev))
    runs.sort(key=lambda r: r[1] - r[0], reverse=True)
    best = runs[0]
    return {
        "threshold_s": thresh_s,
        "segments": len(runs),
        "longest_s": round(best[1] - best[0], 1),
        "longest_iso": "%s → %s" % (_iso(best[0]), _iso(best[1])),
        "count_in_longest": sum(1 for t in ts if best[0] <= t <= best[1]),
        "breaks": len(breaks),
        "breaks_top": sorted(breaks, key=lambda b: -b["gap_s"])[:5],
    }


def cmd_sustain(root: str, name: str, stamp_dir: str = None) -> dict:
    d = _stamp_dir(stamp_dir)
    out = {"stamp_dir_name": "~/.mdcg/sustain/<name>.stamp", "heartbeat": _read_stamp(name, d)}

    sp = os.path.join(root, "_sustain.jsonl")
    if os.path.isfile(sp):
        ts = list(_stream_times(sp))
        out["sustain_log"] = {
            "file": "_sustain.jsonl",
            "size": os.path.getsize(sp),
            "lines_with_t": len(ts),
            "stats": _interval_stats(ts),
            # heal 巡检缺省间隔 300s；无断阈值取 2×（600s）
            "longest_run_600s": _longest_run(ts, 600.0),
            "longest_run_1800s": _longest_run(ts, 1800.0),
        }
    else:
        out["sustain_log"] = {"absent": True}

    # sleep 轮次台账（_sleep.jsonl，落 sleep_root；若在库根旁则一并统计）
    for cand in (os.path.join(root, "_sleep.jsonl"),
                 os.path.join(d, "..", "sleep", "_sleep.jsonl")):
        if os.path.isfile(cand):
            ts = list(_stream_times(cand))
            out["sleep_log"] = {"file": os.path.basename(cand),
                                "lines_with_t": len(ts),
                                "stats": _interval_stats(ts)}
            break
    return out


# --------------------------------------------------------------------------
# 乙 · 层级映射的机械证据（只读）：一阶留痕 vs 二阶元认知留痕的消费者扫面
# --------------------------------------------------------------------------

def cmd_layers() -> dict:
    """扫 md_cg/*.py：`_reflection.jsonl`（一阶）与 `_metacognition.jsonl`（二阶）的引用点。

    关键判据：二阶元认知留痕（`_metacognition.jsonl`）是否被**任一生产单元读取并再做二阶处理**？
    若只有写入者自身（`metacognition.py`，history/自描述）与测试消费者，则
    `metacognition.trace` 是「对一阶留痕的横向审视（结构性后退）」而非「读上一层输出的更深递归」。
    """
    d = os.path.join(REPO, "md_cg")
    hit = {"reflection": [], "metacognition": []}
    for f in sorted(os.listdir(d)):
        if not f.endswith(".py"):
            continue
        p = os.path.join(d, f)
        with open(p, encoding="utf-8", errors="replace") as fh:
            for i, line in enumerate(fh, 1):
                if "_reflection.jsonl" in line:
                    hit["reflection"].append({"file": f, "line": i, "text": line.strip()[:120]})
                if "_metacognition.jsonl" in line:
                    hit["metacognition"].append({"file": f, "line": i, "text": line.strip()[:120]})
    # 消费者归类：写入者自身 metacognition.py / 测试 / 其它
    def consumers(rows):
        out = {}
        for r in rows:
            out.setdefault(r["file"], 0)
            out[r["file"]] += 1
        return out
    hit["reflection_consumers"] = consumers(hit["reflection"])
    hit["metacognition_consumers"] = consumers(hit["metacognition"])
    hit["note"] = ("metacognition_consumers 除写入者 metacognition.py 与测试外为空 ⇒ "
                   "二阶留痕无生产消费者（无更深递归）")
    return hit


def main():
    ap = argparse.ArgumentParser(description="W7v11 第 3 组结构面局限取证（只读）")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("layers", help="乙：一阶/二阶留痕消费者扫面（层级映射机械证据）")
    p1 = sub.add_parser("fastpath", help="甲：_fast_path_verdict 实库触发读数")
    p1.add_argument("--root", default=os.environ.get("MDCG_ROOT"),
                    help="认知图库根（只读；缺省取环境变量 MDCG_ROOT）")
    p1.add_argument("--sample", type=int, default=0,
                    help="对 probe 面最多真探 N 条（0=全探）")
    p2 = sub.add_parser("sustain", help="丁：长跑周期读数")
    p2.add_argument("--root", default=os.environ.get("MDCG_ROOT"))
    p2.add_argument("--name", default="md_cg")
    p2.add_argument("--stamp-dir", default=None,
                    help="心跳戳目录（缺省取环境变量 MDCG_SUSTAIN_DIR 或 ~/.mdcg/sustain）")
    args = ap.parse_args()

    if args.cmd == "layers":
        print(json.dumps(cmd_layers(), ensure_ascii=False, indent=1, default=str))
        return 0

    if not args.root:
        print("ERROR: 需 --root 或环境变量 MDCG_ROOT 指向认知图库根（只读）")
        return 2
    if not os.path.isdir(args.root):
        print("ERROR: 库根不存在")
        return 2

    if args.cmd == "fastpath":
        res = cmd_fastpath(args.root, sample=args.sample)
    else:
        res = cmd_sustain(args.root, args.name, args.stamp_dir)
    print(json.dumps(res, ensure_ascii=False, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
