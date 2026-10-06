#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""export_zcode_transcript —— 把 ZCode 会话**全量**导出为 md 转写（增量追加），
并可选建灵枢 doc_ref 索引（`cg(op=index_doc)` 面），供 `cg(op=ref)` 回读完整原文。

定位（使用者 2026-10-06「每次完整会话通过写 md 文档，和 mdcg 认知图来管理」）：
  · 运行态窗口（_recent）只留近期；**完整原文**落在本转写 md（持久、可检索、可回读）；
  · 格式沿双角色转写体例：`**我说：**` / `**ZCode说：**`（与语料管线同构）；
  · 落点：`<AEIS 数据根>/zcode-log-transcripts/<session_id>.md`（先例：dsh-log-transcripts）；
  · 转写只收**真人轮**（origin=='realUser'）＋同回合最终回复——系统注入/后台回执不收；
  · 追加式增量：水位存 ~/.mdcg/zcode_sync.json（分键 `<root>|transcript|session`）。

用法：
  python -X utf8 scripts/export_zcode_transcript.py                 # 最近含真人输入的会话
  python -X utf8 scripts/export_zcode_transcript.py --session sess_xxx
  python -X utf8 scripts/export_zcode_transcript.py --index         # 转写后顺带 index_doc
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _load_sync_module():
    spec = importlib.util.spec_from_file_location(
        "sync_zcode_session", HERE / "sync_zcode_session.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    ap = argparse.ArgumentParser(description="ZCode 会话 → md 转写（全量增量）＋可选灵枢索引")
    ap.add_argument("--session", default=None)
    ap.add_argument("--root", default=None, help="灵枢数据根（--index 用；缺省 env/默认）")
    ap.add_argument("--index", action="store_true", help="转写后执行 cg(op=index_doc) 建引用")
    a = ap.parse_args()

    sync_mod = _load_sync_module()
    con = sync_mod._open_db_ro()
    sid = a.session or sync_mod.latest_realuser_session(con)
    if not sid:
        print("未找到含真人输入的 zcode 会话")
        return 1
    total = len(sync_mod.extract_turns(con, sid, 10 ** 6))
    print(f"会话 {sid}｜真人轮总数 {total}")

    added = sync_mod.append_transcript(sid, con=con)      # 单点：追加逻辑在 sync 模块
    out = sync_mod.TRANSCRIPT_ROOT / f"{sid}.md"
    print(f"新增轮 {added}｜转写文件 {out}（{out.stat().st_size if out.exists() else 0} 字节）")
    con.close()

    if a.index:
        sys.path.insert(0, str(HERE.parent))
        from md_cg.mdcos import MdCGOS
        root = a.root or sync_mod._resolve_root()
        cg = MdCGOS(root)
        fn = getattr(cg, "index_doc", None)
        if fn is None:
            print("（库层无 index_doc 方法——请以 cg(op=index_doc, path=...) 经 MCP 建索引）")
            return 0
        try:
            r = fn(str(TRANSCRIPT_ROOT), incremental=True)
            print("index_doc:", json.dumps(r, ensure_ascii=False)[:300])
        except TypeError:
            r = fn(str(TRANSCRIPT_ROOT))
            print("index_doc:", json.dumps(r, ensure_ascii=False)[:300])
    return 0


if __name__ == "__main__":
    sys.exit(main())
