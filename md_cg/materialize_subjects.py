# -*- coding: utf-8 -*-
"""把 _archive 里的 subject 证据聚合成主体档案节点（幂等，可重跑）。

跑法：PYTHONPATH=<仓根> python3 -X utf8 -m md_cg.materialize_subjects [--limit N] [--dry]
根目录取自 `datapath.mdcg_root()`（env MDCG_ROOT > paths.json > 用户级状态根）。
"""
import hashlib
import json
import os
import re
import sys

from . import writepipe
from .mdcos import MdCGSecure
from .security import Principal

# R-564（2026-11-10 审计 P1-F4）：根**不许硬编码本机路径**。
# 修前缺省回落一个**服务器上的具体目录**（形如 /home/<user>/mdcg-data）：换机即失效，
# 且把「某台机器的布局」写进了代码。改走 `datapath.mdcg_root()` 的既有解析链
# （env MDCG_ROOT > paths.json > 用户级状态根），与其余模块同一真源。
from .datapath import mdcg_root as _mdcg_root

ROOT = _mdcg_root()
ARCH = os.path.join(ROOT, "_archive")
SIDECAR = os.path.join(ROOT, "identity", "archive_subjects.json")
SUBJ = re.compile(r"subject:([A-Za-z0-9_.@-]+)")
TAG_SUMMARY = "identity:archive-summary"


def scan():
    agg = {}
    files = 0
    for base, _dirs, names in os.walk(ARCH):
        for fn in names:
            if not fn.endswith(".md"):
                continue
            p = os.path.join(base, fn)
            try:
                head = open(p, encoding="utf-8", errors="replace").read(4000)
                st = os.stat(p)
            except OSError:
                continue
            files += 1
            rel = os.path.relpath(base, ARCH).split(os.sep)
            layer = rel[1] if len(rel) > 1 else (rel[0] if rel else "unknown")
            for sid in set(SUBJ.findall(head)):
                d = agg.setdefault(sid, {"n": 0, "layers": {}, "last": 0, "first": 0, "samples": []})
                d["n"] += 1
                d["layers"][layer] = d["layers"].get(layer, 0) + 1
                d["last"] = max(d["last"], int(st.st_mtime))
                d["first"] = d["first"] or int(st.st_mtime)
                if len(d["samples"]) < 3:
                    d["samples"].append(os.path.splitext(fn)[0])
    return files, agg


def content_for(sid, d):
    layers = "、".join("%s %d" % (k, v) for k, v in sorted(d["layers"].items(), key=lambda kv: -kv[1])[:4])
    return (
        "# 功能名：主体 %s 的归档摘要\n"
        "# 主题：%s 在 L2 整族归档前的 %d 条记录（层分布：%s）\n"
        "# 生效条件：需要回答「这个主体做过什么」时先读这条；原始流水仍在 _archive 下，可按 subject 标签回捞\n"
        "# 子功能：给出该主体的记录规模、层分布与时间范围；要细节时按标签回捞原始文件\n"
        "# 执行：grep -rl 'subject:%s' <MDCG_ROOT>/_archive | head -20\n"
        "# 验证方式：2026-11-06 扫 _archive 的 subject 标签聚合；样本 %s\n"
        "# 不适用条件：不要把这条当成主体的活证据——它只是索引卡，不参与位置效应投票\n"
        % (sid, sid, d["n"], layers, sid, "、".join(d["samples"]))
    )


def nid_for(sid):
    return "subj_arc_" + hashlib.sha1(sid.encode("utf-8")).hexdigest()[:12]


def main():
    limit = 0
    dry = "--dry" in sys.argv
    for i, arg in enumerate(sys.argv):
        if arg == "--limit" and i + 1 < len(sys.argv):
            limit = int(sys.argv[i + 1])
    p = Principal(actor="dsh-memory", role="designer", tenant="default",
                  clearance="private", can_write=True, can_admin=True)
    cg = MdCGSecure(ROOT, principal=p, autoflush=8)
    files, agg = scan()
    sids = sorted(agg, key=lambda s: (-agg[s]["n"], s))
    print("扫到 %d 个归档文件 · %d 个主体" % (files, len(sids)))
    if dry:
        for sid in sids[:3]:
            print("---", sid, agg[sid]["n"], "→", nid_for(sid))
            print(content_for(sid, agg[sid]))
        return
    os.makedirs(os.path.dirname(SIDECAR), exist_ok=True)
    io_side = {sid: {"archived_nodes": agg[sid]["n"], "layers": agg[sid]["layers"],
                     "last_seen": agg[sid]["last"], "first_seen": agg[sid]["first"]} for sid in sids}
    with open(SIDECAR, "w", encoding="utf-8") as f:
        json.dump(io_side, f, ensure_ascii=False, indent=1, sort_keys=True)
    print("sidecar %s · %d 主体" % (SIDECAR, len(io_side)))
    ok = skip = rej = err = 0
    verdicts = {}
    nodes = cg.index.get("nodes") or {}
    for sid in sids[:limit or None]:
        nid = nid_for(sid)
        if nid in nodes:
            skip += 1
            continue
        a = {"node_id": nid, "content": content_for(sid, agg[sid]),
             "layer": "self" if sid.startswith("self:") else "anchor",
             "tags": ["subject:" + sid, "identity_anchor", TAG_SUMMARY],
             "importance": 0.35, "content_kind": "text", "role": "assistant"}
        try:
            out = writepipe.default_pipeline().execute(cg, a)
        except Exception as exc:  # noqa: BLE001 - 逐条记账，不中断
            err += 1
            verdicts.setdefault("EXC:" + type(exc).__name__, 0)
            verdicts["EXC:" + type(exc).__name__] += 1
            continue
        v = str((out or {}).get("verdict") or ("committed" if (out or {}).get("ok") else "?"))
        verdicts[v] = verdicts.get(v, 0) + 1
        if (out or {}).get("ok") and (out or {}).get("committed", True):
            ok += 1
        else:
            rej += 1
    print("写入 ok=%d 拒/待审=%d 已存在跳过=%d 异常=%d" % (ok, rej, skip, err))
    print("verdicts:", json.dumps(verdicts, ensure_ascii=False))


if __name__ == "__main__":
    main()
