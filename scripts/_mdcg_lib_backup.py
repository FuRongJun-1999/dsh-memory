# -*- coding: utf-8 -*-
"""重索引前置备份：把将被覆盖的 code_ 节点正文 + 两个元数据文件复制到库外新目录。

只读源库、只写新目录；不修改库内任何文件。
产物目录：<root>_backup_code_<ts>/（同级，默认）
"""
import os
import sys
import json
import time
import shutil
import argparse

ap = argparse.ArgumentParser()
ap.add_argument("--root", required=True, help="认知图库根")
ap.add_argument("--dest", default=None, help="备份目标目录（默认 <root>_backup_code_<ts>）")
a = ap.parse_args()

root = os.path.abspath(a.root)
ts = time.strftime("%Y%m%d_%H%M%S")
dest = a.dest or (root.rstrip("\\/") + "_backup_code_" + ts)
os.makedirs(dest, exist_ok=True)

kn = os.path.join(root, "knowledge")
n = 0
for d, _sub, fs in os.walk(kn):
    for f in fs:
        if f.startswith("code_") and f.endswith(".md"):
            src = os.path.join(d, f)
            rp = os.path.relpath(src, root)
            tp = os.path.join(dest, rp)
            os.makedirs(os.path.dirname(tp), exist_ok=True)
            shutil.copy2(src, tp)
            n += 1

meta = []
for m in ("_index.json", "_refindex.json", "_comment_gate.jsonl"):
    p = os.path.join(root, m)
    if os.path.isfile(p):
        shutil.copy2(p, os.path.join(dest, m))
        meta.append({"file": m, "bytes": os.path.getsize(p)})

print(json.dumps({"ok": True, "dest": dest, "code_nodes": n,
                  "meta": meta}, ensure_ascii=False))
sys.exit(0)
