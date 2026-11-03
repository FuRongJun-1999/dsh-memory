# -*- coding: utf-8 -*-
"""content_hash 口径迁移工具（issue #741 升级面）。

## 为什么需要它
`content_hash` 的**输入口径**在 #741 之前是不一致的（4 个写点里 3 个各算各的）。
#741 把算法与输入双双收口到 `nodefile.content_hash` + `nodefile.normalize_body`
之后，**新写入**一律是新口径；但存量 `_index.json` 里的值仍是旧口径。

于是升级后第一次对账会出现**升级假阳性**：读回正文恒带尾换行（`dumps()` 补的），
与存量旧口径值差一个字节 ⇒ 凡「原正文不以 \\n 结尾」的节点都可能报
`hash_drift`。这会把「真 drift」淹没在「假 drift」里——正是 #741 要消灭的状态。

## 为什么不自动跑
迁移会**改写全库索引**。升级时静默改写 = 把一次可解释的「一次性动作」变成
不可见的副作用，违反本仓「不静默」的取向。故本工具**默认只扫描报告**，
必须显式 `--apply` 才改写，且改写前后都打印读数。

## 用法
```
# ① 只扫描：报告有多少节点处在旧口径（不写盘）
python -X utf8 -m md_cg.migrate_content_hash --root <认知图根>

# ② 执行迁移：按新口径重算并改写索引（原子写 + 一次性标记）
python -X utf8 -m md_cg.migrate_content_hash --root <认知图根> --apply

# ③ 迁移后复验：期望 drift 归零
python -X utf8 -m md_cg.migrate_content_hash --root <认知图根> --verify
```

## 判据（三条都是可复算的）
- **M1** 迁移前：报告 `old`（与新口径不符者）与 `ok`（已符）计数。
- **M2** 迁移后：同一扫描 `old == 0`。
- **M3** `--verify`：逐节点比对「索引值 vs `content_hash(normalize_body(读回正文))`」，
  全部相等才算收敛。
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")

from md_cg import nodefile                       # noqa: E402
from md_cg.mdcg import MdCG                      # noqa: E402

MARKER = "_content_hash_migrated.json"


def _expected(cg, nid, entry):
    """按**新口径**算该条目应有的值；读不到正文返回 None。"""
    node = cg.get(nid)
    if not node:
        return None
    content = node.get("content")
    if content is None:
        return None
    return nodefile.content_hash(nodefile.normalize_body(content))


def scan(cg, apply=False):
    """返回 (old_ids, ok_count, unreadable)。apply=True 时就地改写。"""
    old_ids = []
    ok_count = 0
    unreadable = []
    for nid, entry in list(cg.index["nodes"].items()):
        want = _expected(cg, nid, entry)
        if want is None:
            unreadable.append(nid)
            continue
        cur = entry.get("content_hash")
        if cur == want:
            ok_count += 1
        else:
            old_ids.append((nid, cur, want))
            if apply:
                entry["content_hash"] = want
    return old_ids, ok_count, unreadable


def main(argv=None):
    ap = argparse.ArgumentParser(description="content_hash 口径迁移（issue #741）")
    ap.add_argument("--root", required=True, help="认知图根目录")
    ap.add_argument("--apply", action="store_true", help="真的改写索引（缺省只扫描）")
    ap.add_argument("--verify", action="store_true", help="只复验：期望全部收敛")
    ap.add_argument("--json", action="store_true", help="机器可读输出")
    a = ap.parse_args(argv)

    cg = MdCG(a.root)
    old_ids, ok_count, unreadable = scan(cg, apply=a.apply)

    rep = {
        "root": a.root,
        "mode": "verify" if a.verify else ("apply" if a.apply else "scan"),
        "total": len(cg.index["nodes"]),
        "ok": ok_count,
        "old": len(old_ids),
        "unreadable": len(unreadable),
        "sample_old": [{"id": n, "was": w, "now": x} for n, w, x in old_ids[:10]],
    }

    if a.apply and old_ids:
        # flush() 只落增量日志；`_index.json` 要显式写盘才会含新值。
        # 走公共收口（若存在），否则直接原子写索引文档。
        _save = getattr(cg, "_save_index", None) or getattr(cg, "save_index", None)
        if callable(_save):
            _save()
        else:
            cg.flush()
            from md_cg.fsutil import atomic_write
            atomic_write(os.path.join(a.root, "_index.json"),
                         json.dumps(cg.index, ensure_ascii=False))
        # 一次性标记：记录本次迁移完成，供后续审计
        mark = os.path.join(a.root, MARKER)
        try:
            with open(mark, "w", encoding="utf-8") as f:
                json.dump({"migrated": len(old_ids), "total": rep["total"]},
                          f, ensure_ascii=False, indent=1)
            rep["marker"] = mark
        except OSError as exc:
            rep["marker_error"] = "%s: %s" % (type(exc).__name__, exc)

    if a.json:
        print(json.dumps(rep, ensure_ascii=False, indent=1))
    else:
        print("== content_hash 口径%s ==" % ("复验" if a.verify else ("迁移" if a.apply else "扫描")))
        print("  根目录      : %s" % a.root)
        print("  节点总数    : %d" % rep["total"])
        print("  新口径(ok)  : %d" % rep["ok"])
        print("  旧口径(old) : %d" % rep["old"])
        print("  不可读      : %d" % rep["unreadable"])
        for row in rep["sample_old"]:
            print("    - %s  %s -> %s" % (row["id"], row["was"], row["now"]))

    # 退出码（fail-closed）：verify 模式下 old>0 即 1；其余模式恒 0（扫描不该失败）
    if (a.verify or a.apply) and rep["old"] > 0 and not a.apply:
        return 1
    if a.apply and rep["old"] > 0:
        return 0            # 已迁移，正常退出
    return 0


if __name__ == "__main__":
    sys.exit(main())
