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

#: 转写落点根（持久、仓外；与 dsh-log-transcripts 同级先例）
TRANSCRIPT_ROOT = Path(r"D:\program\AEIS\data\zcode-log-transcripts")


def _load_sync_module():
    spec = importlib.util.spec_from_file_location(
        "sync_zcode_session", HERE / "sync_zcode_session.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _render_header(sid: str) -> str:
    return (f"# ZCode 会话转录：{sid}\n\n"
            f"> 导出器：scripts/export_zcode_transcript.py（增量追加；只收真人轮与其回合最终回复）\n"
            f"> 回读：灵枢 `cg(op=ref)` 按区间读回本文件原文\n\n---\n")


def _render_turn(t: dict) -> str:
    parts = ["**我说：**", "", t["user"].strip(), "", "**ZCode说：**", "",
             (t.get("assistant") or "").strip(), "", "---", ""]
    return "\n".join(parts)


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

    turns = sync_mod.extract_turns(con, sid, 10 ** 6)     # 全量
    print(f"会话 {sid}｜真人轮总数 {len(turns)}")

    state = sync_mod.load_state()
    key = "transcript|" + sid
    sst = state.setdefault(key, {})
    last_t = int(sst.get("last_turn_created") or 0)
    fresh = [t for t in turns if int(t.get("t") or 0) > last_t]

    TRANSCRIPT_ROOT.mkdir(parents=True, exist_ok=True)
    out = TRANSCRIPT_ROOT / f"{sid}.md"
    if not out.exists():
        out.write_text(_render_header(sid), encoding="utf-8")
    if fresh:
        with open(out, "a", encoding="utf-8", newline="\n") as f:
            for t in fresh:
                f.write(_render_turn(t))
        sst["last_turn_created"] = int(fresh[-1].get("t") or 0)
        sync_mod.save_state(state)
    print(f"新增轮 {len(fresh)}｜转写文件 {out}（{out.stat().st_size} 字节）")

    if a.index:
        sys.path.insert(0, str(HERE.parent))
        from md_cg.mdcos import MdCGOS
        root = a.root or os.environ.get("MDCG_ROOT")
        if not root:
            from md_cg.datapath import mdcg_root
            root = mdcg_root()
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
