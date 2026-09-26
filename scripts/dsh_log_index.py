# -*- coding: utf-8 -*-
"""dsh_log_index.py — DSH 会话日志（zstd jsonl）→ 转写 md → 摄取灵枢检索面。

定位
----
把 DSH 端（deepseek harness）的私有会话日志离线转写为 md 并摄取进**私有活库**
（MDCG_ROOT 指向的认知图根），使历史会话正文可被 cg search 检索面召回。
本脚本是一次性/可重跑的摄取工具，不是常驻服务。

隐私纪律（工程纪律第 9 条）
--------------------------
· DSH 会话日志是**私有侧数据**：摄取目标只能是私有活库 root，绝不推公开库
  （本脚本拒绝把 root 指到本仓库检出内，见 `_guard_root`）。
· 节点密级显式 **private**（docindex.sensitivity_for 显式覆盖；私有档会话绑定，
  仅归属会话 + 设计者可读，见 md_cg/mdcos.py `_readable`）。
· 工具与报告**不打印日志正文原文**：stdout 只出统计与计数，无任何消息文本。
· 节点 id 前缀 `dsh-log-`：便于识别与将来回收（在役库只增不删，回收留钩子）。

日志形态（2026-09-26 对真实会话逐行探测得出）
--------------------------------------------
<DSH 会话根>/<工作区目录名>/<session-id>/session.v4.jsonl.zstd，zstd 压缩、
解压后逐行 JSON。与本脚本相关的行型：
  · type=session                首行元数据（id / createdAt(ms) / cwd / agentPreset）
  · type=turn/start             data.turn —— 轮次号从这里跟踪
  · type=user/message           用户消息：data.content[].text（type=text 块），
                                以 data.id 去重
  · type=agent/inbox/spliced    用户消息第二通道：data.inserted[]（content[] /
                                source.kind=="user" / id）——与 user/message
                                **同 id 重复**（实测 16/16 重复），按 id 去重
  · type=assistant/message      助手消息：正文在 data.message.content[] 内
                                （type=="text" 块；reasoning / tool-call 块不是
                                正文）。无 text 块的行跳过并计数
  · 其余（tool/call、step/end 等）跳过并计数

转写结构（每会话一个 md，写系统临时目录、路径确定→幂等）
------------------------------------------------------
    # 会话 <session-id>（cwd=<cwd> · <ISO 时间> · 预设=<agentPreset>）
    ## turn <n>（用户）
    ## turn <n>（助手）
正文逐段落在对应轮次标题下；空正文消息跳过。转写体内可能出现的 ATX 标题样
行首加反斜杠转义（不虚构内容，只防正文里的 markdown 标题被章节切分误认）。

摄取（原则=生产同款章节切分）
----------------------------
不走 cg index_doc（其节点 id 由 docindex.node_id 固定为 `doc_` 前缀，无法满足
dsh-log- 前缀要求），而是**直调同款索引入口**：`refindex.index_dir(kind="doc_ref")`
（内含 docindex.extract 的 level≤3 章节切分、小节合并、围栏感知，与生产
mcp_server index_doc op 同一实现），写入侧逐条对照 refindex.add_items 的
doc_ref 分支（render / condition_space / sensitivity / tags / domain 同源），
仅节点 id 改为 `dsh-log-<session-id>-<章节序号>`。
不写 doc_ref 绑定列：转写文件是系统临时目录里的暂存物（会被系统清理），
绑定列会系统性变 dangling；且 op=ref 回读原文会开第二个日志原文暴露面。
来源溯源改记 frontmatter.dsh_log（session / workspace / 来源相对形态）。
不登记 refindex.Ledger：水位台账在活库根，登临目目录等于把暂存路径写进活库。

幂等
----
· 节点 id 由 (session-id, 章节序号) 决定 → 确定性；
· 写入前查活库索引，已存在即计「已索引跳过」，**不覆写**（活库只增不删）；
· 转写路径确定（临时根 + 工作区 + 会话 id），重跑生成逐字节相同的转写。

用法（第 15 条：argv 列表 + 显式 UTF-8，不经 Windows shell）
    set PYTHONUTF8=1
    python scripts/dsh_log_index.py --sessions-root <DSH会话根> --dry-run
    python scripts/dsh_log_index.py --sessions-root <DSH会话根> --root <灵枢库root>
    python scripts/dsh_log_index.py --sessions-root <DSH会话根> --session <id>
依赖：zstandard（pip install zstandard）；md_cg 包（经 sys.path 仓库根导入）。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from datetime import datetime

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from md_cg import docindex, refindex, security            # noqa: E402
from md_cg.mdcos import MdCGSecure                        # noqa: E402
from md_cg.security import Principal                      # noqa: E402

#: 转写暂存根（系统临时目录下、路径确定——幂等与来源稳定都靠它）
TRANSCRIPT_ROOT = os.path.join(tempfile.gettempdir(), "dsh-log-transcripts")
#: 会话日志文件名（v4 形态）
LOG_NAME = "session.v4.jsonl.zstd"
#: ATX 标题样行（正文里的 markdown 标题须转义，防章节切分误认）
_ATX_LIKE = re.compile(r"^#{1,6}\s")


# ==========================================================================
# 1. 发现会话
# ==========================================================================

def discover_sessions(sessions_root: str, workspace: str = None,
                      session: str = None) -> list:
    """枚举 <sessions_root>/<工作区目录名>/<session-id>/session.v4.jsonl.zstd。

    返回 [{workspace, session_id, log}]，按 (workspace, session_id) 稳定排序。
    """
    out = []
    if not os.path.isdir(sessions_root):
        raise SystemExit(f"会话根不存在或不是目录：{sessions_root}")
    for ws in sorted(os.listdir(sessions_root)):
        if workspace and ws != workspace:
            continue
        ws_dir = os.path.join(sessions_root, ws)
        if not os.path.isdir(ws_dir):
            continue
        for sid in sorted(os.listdir(ws_dir)):
            if session and sid != session:
                continue
            log = os.path.join(ws_dir, sid, LOG_NAME)
            if os.path.isfile(log):
                out.append({"workspace": ws, "session_id": sid, "log": log})
    return out


# ==========================================================================
# 2. 解析日志（只产计数与消息序列，绝不落正文到 stdout）
# ==========================================================================

def _text_of(blocks) -> str:
    """content 块列表 → 正文（type=="text" 且 text 为 str 的块，双换行拼接）。"""
    parts = [b.get("text") for b in (blocks or [])
             if isinstance(b, dict) and b.get("type") == "text"
             and isinstance(b.get("text"), str)]
    return "\n\n".join(p for p in parts if p.strip())


def parse_session_log(log_path: str) -> dict:
    """流式解析一个会话日志 → {meta, msgs, stats}。

    msgs：按日志出现顺序的 [{turn, role, text}]（用户/助手正文，空正文不收）。
    stats：各行型计数 + 跳过明细（不含任何正文）。
    """
    try:
        import zstandard                                   # noqa: F401
    except ImportError as e:
        raise SystemExit("缺少依赖 zstandard：pip install zstandard") from e
    import io
    import zstandard as zstd

    meta, msgs = {}, []
    seen_ids = set()                 # 消息 id 去重（spliced 与 user/message 同 id）
    cur_turn = 0
    st = {"lines_total": 0, "lines_skipped_other": 0, "lines_json_error": 0,
          "user_dup_events": 0, "assistant_no_text": 0, "assistant_msgs": 0,
          "assistant_text_msgs": 0,
          "user_msgs": 0, "chars_user": 0, "chars_assistant": 0,
          "turns_seen": 0}
    with open(log_path, "rb") as f:
        text = io.TextIOWrapper(zstd.ZstdDecompressor().stream_reader(f),
                                encoding="utf-8", errors="replace")
        for line in text:
            line = line.strip()
            if not line:
                continue
            st["lines_total"] += 1
            try:
                o = json.loads(line)
            except ValueError:
                st["lines_json_error"] += 1
                continue
            t = o.get("type")
            d = o.get("data") or {}
            if t == "session":
                meta = {"id": o.get("id"),
                        "created_at_ms": o.get("createdAt"),
                        "cwd": o.get("cwd") or "",
                        "agent_preset": o.get("agentPreset") or ""}
            elif t == "turn/start":
                if isinstance(d.get("turn"), int):
                    cur_turn = d["turn"]
                    st["turns_seen"] += 1
            elif t == "user/message":
                mid = d.get("id")
                if mid and mid in seen_ids:
                    st["user_dup_events"] += 1
                    continue
                if mid:
                    seen_ids.add(mid)
                body = _text_of(d.get("content"))
                if not body.strip():
                    continue                      # 空正文轮跳过（不计消息）
                st["user_msgs"] += 1
                st["chars_user"] += len(body)
                msgs.append({"turn": cur_turn, "role": "user", "text": body})
            elif t == "agent/inbox/spliced":
                for it in d.get("inserted") or []:
                    if not isinstance(it, dict):
                        continue
                    if (it.get("source") or {}).get("kind") != "user":
                        continue                  # 只收 source.kind=="user"
                    mid = it.get("id")
                    if mid and mid in seen_ids:
                        st["user_dup_events"] += 1
                        continue
                    if mid:
                        seen_ids.add(mid)
                    body = _text_of(it.get("content"))
                    if not body.strip():
                        continue
                    st["user_msgs"] += 1
                    st["chars_user"] += len(body)
                    msgs.append({"turn": cur_turn, "role": "user", "text": body})
            elif t == "assistant/message":
                m = d.get("message") or {}
                mid = m.get("id") or d.get("id")
                if mid and mid in seen_ids:
                    st["user_dup_events"] += 1
                    continue
                if mid:
                    seen_ids.add(mid)
                st["assistant_msgs"] += 1
                body = _text_of(m.get("content"))
                if not body.strip():
                    st["assistant_no_text"] += 1  # 无 text 块（reasoning/tool）跳过
                    continue
                st["assistant_text_msgs"] += 1
                st["chars_assistant"] += len(body)
                msgs.append({"turn": d.get("turn")
                             if isinstance(d.get("turn"), int) else cur_turn,
                             "role": "assistant", "text": body})
            else:
                st["lines_skipped_other"] += 1
    return {"meta": meta, "msgs": msgs, "stats": st}


# ==========================================================================
# 3. 转写 md（临时目录、路径确定）
# ==========================================================================

def _iso(ms) -> str:
    try:
        return datetime.fromtimestamp(int(ms) / 1000).isoformat(timespec="seconds")
    except (TypeError, ValueError, OSError, OverflowError):
        return ""


def render_transcript(workspace: str, parsed: dict) -> str:
    """解析产物 → 转写 md 文本（结构：# 会话 → ## turn N（用户/助手）→ 正文）。"""
    meta, msgs = parsed["meta"], parsed["msgs"]
    sid = meta.get("id") or "?"
    head = (f"# 会话 {sid}（cwd={meta.get('cwd', '')}"
            f" · {_iso(meta.get('created_at_ms'))}"
            f" · 预设={meta.get('agent_preset', '')}）")
    prov = (f"来源：DSH 会话根/{workspace}/{sid}/{LOG_NAME}"
            f"（scripts/dsh_log_index.py 转写；私有侧数据，密级 private）")
    lines = [head, "", prov, ""]
    for m in msgs:
        lines.append(f"## turn {m['turn']}（{'用户' if m['role'] == 'user' else '助手'}）")
        lines.append("")
        for ln in m["text"].split("\n"):
            # 正文里的 ATX 标题样行加 `\` 转义：不改动一个字，只防章节切分误认
            lines.append("\\" + ln if _ATX_LIKE.match(ln) else ln)
        lines.append("")
    return "\n".join(lines)


def transcript_path(workspace: str, session_id: str) -> str:
    """确定性转写路径：<系统临时目录>/dsh-log-transcripts/<工作区>/<会话>/。"""
    return os.path.join(TRANSCRIPT_ROOT, workspace, session_id)


# ==========================================================================
# 4. 摄取（生产同款章节切分 + dsh-log- 节点 id + private 密级）
# ==========================================================================

def ingest_transcript(cg, workspace: str, session_id: str, tdir: str) -> dict:
    """索引一个会话的转写目录并写入活库（已存在节点跳过，不覆写）。

    章节切分走 refindex.index_dir(kind="doc_ref")——与 mcp_server index_doc op
    同一实现（docindex.extract：level≤3、小节合并、围栏感知）。写入逐条对照
    refindex.add_items 的 doc_ref 分支（refindex.py:378-392），差异仅：
      · 节点 id = dsh-log-<session-id>-<章节序号>（前缀纪律，便于将来回收）；
      · 密级显式 private（sensitivity_for override；私有侧数据）；
      · 不写 doc_ref / 不登记 Ledger（理由见模块 docstring），
        溯源改记 frontmatter.dsh_log。
    """
    items, errors, stats = refindex.index_dir(
        tdir, kind="doc_ref", max_files=100, max_items=50000)
    indexed, skipped_existing, sens_counts = [], 0, {}
    for i, it in enumerate(items):
        nid = f"dsh-log-{session_id}-{i:04d}"
        if nid in (cg.index.get("nodes") or {}):
            skipped_existing += 1                   # 已索引：幂等跳过，不覆写
            continue
        s, _basis = docindex.sensitivity_for(it.get("path"), "private")
        sens_counts[s] = sens_counts.get(s, 0) + 1
        cg.add(
            nid, docindex.render(it),
            layer="knowledge",
            tags=["doc", "doc:md", "dsh-log", f"level:{it.get('level')}",
                  "domain:" + refindex._domain_of(it)],
            condition_space=docindex.condition_space(it),
            verification_basis="data",
            sensitivity=s,
            dsh_log={"session": session_id, "workspace": workspace,
                     "source": f"DSH 会话根/{workspace}/{session_id}/{LOG_NAME}",
                     "transcript": it.get("path"),
                     "heading_path": it.get("heading_path"),
                     "lineno": it.get("lineno"), "end": it.get("end")})
        indexed.append(nid)
    return {"items": len(items), "indexed": indexed,
            "skipped_existing": skipped_existing,
            "sensitivity": sens_counts,
            "extract_errors": errors[:5], "stats": stats}


# ==========================================================================
# 5. root 守卫（严禁公开库；只允许既有活库）
# ==========================================================================

def _guard_root(root: str, allow_init: bool) -> str:
    """校验摄取目标 root：拒绝空值 / 仓库检出内（公开库）/ 非活库根。"""
    root = os.path.realpath(os.path.abspath(root))
    repo = os.path.realpath(REPO_ROOT)
    if root == repo or root.startswith(repo + os.sep):
        raise SystemExit(
            "拒绝：目标 root 位于本仓库检出内（公开库）。"
            "DSH 会话日志是私有侧数据，只能摄取进私有活库（MDCG_ROOT）。")
    if not allow_init and not os.path.isfile(os.path.join(root, "_index.json")):
        raise SystemExit(
            f"拒绝：{root} 不是既有认知图根（缺 _index.json）。"
            "防止手滑新建空库；确认目标无误可用 --allow-init 显式初始化。")
    # 与 mcp_server index_doc op（mcp_server.py:2324）同款部署白名单开关
    security.check_path_root(root, "MDCG_INGEST_ROOT", "dsh_log_index")
    return root


# ==========================================================================
# 6. CLI
# ==========================================================================

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="DSH 会话日志（zstd jsonl）→ 转写 md → 摄取灵枢检索面"
                    "（统计输出不含日志正文）")
    ap.add_argument("--sessions-root", required=True,
                    help="DSH 会话根目录（其下为 <工作区目录名>/<session-id>/）")
    ap.add_argument("--root", default=(os.environ.get("MDCG_ROOT") or "").strip() or None,
                    help="灵枢库 root（缺省取环境变量 MDCG_ROOT；dry-run 可省）")
    ap.add_argument("--session", default=None, help="只处理指定 session-id")
    ap.add_argument("--workspace", default=None, help="只处理指定工作区目录名")
    ap.add_argument("--dry-run", action="store_true",
                    help="只转写与统计，不连库不摄取")
    ap.add_argument("--allow-init", action="store_true",
                    help="允许目标 root 为空库（缺省拒绝，防手滑）")
    ap.add_argument("--actor", default="dsh-memory",
                    help="写入身份 actor（须与活库 DEK 身份一致，缺省 dsh-memory）")
    ap.add_argument("--tenant", default="default", help="租户（缺省 default）")
    ap.add_argument("--cleanup-transcripts", action="store_true",
                    help="摄取完成后删除转写暂存目录（默认保留：幂等重跑更快）")
    args = ap.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    sessions = discover_sessions(args.sessions_root, args.workspace, args.session)
    if not sessions:
        print("未发现匹配的会话日志（检查 --sessions-root / --workspace / --session）")
        return 1

    total = {"sessions": 0, "turns_user": 0, "turns_assistant": 0,
             "nodes_indexed": 0, "nodes_skipped_existing": 0,
             "chars": 0, "lines_skipped": 0}
    cg = None
    try:
        for s in sessions:
            parsed = parse_session_log(s["log"])
            md = render_transcript(s["workspace"], parsed)
            tdir = transcript_path(s["workspace"], s["session_id"])
            os.makedirs(tdir, exist_ok=True)
            tpath = os.path.join(tdir, f"{s['session_id']}.md")
            with open(tpath, "w", encoding="utf-8", newline="\n") as f:
                f.write(md)
            st = parsed["stats"]
            row = {"session": s["session_id"], "workspace": s["workspace"],
                   "lines_total": st["lines_total"],
                   "turns_seen": st["turns_seen"],
                   "msgs_user": st["user_msgs"],
                   "msgs_assistant": st["assistant_text_msgs"],
                   "assistant_lines_total": st["assistant_msgs"],
                   "chars_user": st["chars_user"], "chars_assistant": st["chars_assistant"],
                   "skipped": {"other_type": st["lines_skipped_other"],
                               "json_error": st["lines_json_error"],
                               "assistant_no_text": st["assistant_no_text"],
                               "dup_events": st["user_dup_events"]},
                   "transcript": tpath}
            total["sessions"] += 1
            total["turns_user"] += st["user_msgs"]
            total["turns_assistant"] += st["assistant_text_msgs"]
            total["chars"] += st["chars_user"] + st["chars_assistant"]
            total["lines_skipped"] += (st["lines_skipped_other"]
                                       + st["lines_json_error"]
                                       + st["assistant_no_text"]
                                       + st["user_dup_events"])
            if args.dry_run:
                row["mode"] = "dry-run（未连库未摄取）"
            else:
                if not args.root:
                    raise SystemExit("未指定 --root 且环境变量 MDCG_ROOT 为空："
                                     "拒绝猜测摄取目标（严禁写公开库）")
                if cg is not None:
                    cg.close()                    # 私有档会话绑定：逐会话换身份
                    cg = None
                root = _guard_root(args.root, args.allow_init)
                # 直调生产写面（review_cli 同款）：直构 Principal + autoflush=1
                # （写一条落一条索引，跨进程立即可见）。principal.session=该会话 id
                # ——私有档节点按 frontmatter.session 绑定归属（mdcos._readable）
                p = Principal(tenant=args.tenant, actor=args.actor,
                              clearance="private", can_write=True,
                              session=s["session_id"],        # 会话绑定归属
                              harness="dsh", unit="agent",
                              auth_mode="local-cli")
                cg = MdCGSecure(root, principal=p, autoflush=1)
                cs = cg.crypto_status()
                if not cs.get("unlocked"):
                    raise SystemExit(f"加密未解锁，拒绝写入私有内容：{cs}")
                ing = ingest_transcript(cg, s["workspace"], s["session_id"], tdir)
                row["chapters"] = ing["items"]
                row["nodes_indexed"] = len(ing["indexed"])
                row["nodes_skipped_existing"] = ing["skipped_existing"]
                row["sensitivity"] = ing["sensitivity"]
                row["node_ids"] = ing["indexed"][:5]
                if ing["extract_errors"]:
                    row["extract_errors"] = ing["extract_errors"]
                if ing["stats"].get("truncated"):
                    row["truncated"] = ing["stats"].get("truncated_reason")
                total["nodes_indexed"] += len(ing["indexed"])
                total["nodes_skipped_existing"] += ing["skipped_existing"]
            print(json.dumps(row, ensure_ascii=False))
    finally:
        if cg is not None:
            cg.close()
        if args.cleanup_transcripts and not args.dry_run:
            for s in sessions:
                tdir = transcript_path(s["workspace"], s["session_id"])
                if os.path.isdir(tdir):
                    for name in os.listdir(tdir):
                        try:
                            os.remove(os.path.join(tdir, name))
                        except OSError:
                            pass
                    try:
                        os.rmdir(tdir)
                    except OSError:
                        pass

    print(json.dumps({"TOTAL": total,
                      "mode": "dry-run" if args.dry_run else "ingest"},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
