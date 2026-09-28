# -*- coding: utf-8 -*-
"""N203 · P1：DSH 会话日志 → ref 索引落库 + 两代对账（**只写临时库**）。

链路（真源零改动）：
    discover_sessions(:213) → parse_session_log(:260) → render_transcript(:486)
    → 写转写（transcript_path :514）→ `md_cg/logref.write_session`
    → `refindex.prune_orphans(kind="doc_ref", root=transcript_root, items)`

硬边界（写面）
--------------
· 活库（AEIS 私有库，仓内约定形态 `AEIS/data/mdcg`）**不在**本脚本写面内：`_guard_root` 启动即
  断言 `normcase(realpath(root))` 位于 `normcase(realpath(tempfile.gettempdir()))`
  之下，且不等于/不属于活库根、不属于本仓检出、**不等于转写根自身**。比对一律走
  `normcase`（评审⑨）：Windows 上 realpath 可能改大小写/8.3 形态，纯 realpath 比对
  会让「库根 == 转写根」这类错配过闸。
· 写面只有两类：认知图节点（`MdCGSecure(root=命令行给的临时库, master_key=显式)`，
  clearance=private 才过 `mdcos.py:3918 require_layer_write` 落 knowledge 层）与
  转写 md（只写 transcript_root 之下，root 由本侧注入）。
· 环境变量清洗：`ENV_CLEAN` 全清（`datapath.py:254-266` 的 `MDCG_AUX_ROOT` 可改 aux
  根 ⇒ 影响 `_keys.json`/令牌面）——root 与白名单一律由命令行显式给出，**不靠环境**。
· **不注册 refindex.Ledger**（不开活库根的 `_refindex.json`）：其增量只在 ledger 非空
  时生效，且记进水位的是走查时的裸 rel `<sid>.md`（refindex.py:311-317），与改写后的
  `doc_ref.path` 不同源 ⇒ check_refs 快路径会拿它拼 root 误判 dangling。真源增量改由
  节点自描述的 `doc_ref.src.file_hash` 承担（自描述水位，不新造台账）：
  `--reconcile off` 下「该会话每个节点的 src 哈希 == 当前真源 且转写在位」即跳过
  re-parse（计 `sessions_skipped`）；要强行重切用 `--reconcile generation`。

对账（`--reconcile full`，两代构造显式写进流程）
-----------------------------------------------
第 1 代：真代码 `dsh_log_index.ingest_transcript` 写旧式 `dsh-log-*` 节点 v1
        ＋ 新路线 `logref.write_session` 写 ref 节点 v1；
第 2 代：转写改成**插话版** v2（在首条 user 消息**之后**插入一条合成消息——插在
        它之前会改 `derive_session_token` 的 basis，旧式 id 空间就换了，见 :523-538）
        → 旧式公式重跑（:`611-613` id 撞即跳 ⇒ 旧节点留在 v1 区间、不被覆写）
        ＋ 新路线重跑（按 hash+行位判据覆写/幂等）。
判据（任一不满足即退出码 1）：
  · `missing == 0` —— v2 每条 item 的 `docindex.node_id` 都在库中；
  · `misplaced == 0` —— 每个新节点 `docindex.locate(items_v2, doc_ref.lineno)` 的
    `heading_path` 等于它自己的（没有节点认领别人的正文）；
  · `roundtrip_mismatch == 0` —— `read_ref.text` 逐字等于转写同区间切片；
  · `updated == updated_expected` —— 交叉核验「同 id 不同内容」被**计数**而非静默
    （评审⑤）；
  · `legacy_misplaced_slots >= 2` —— 判别力反向判据：剔除**根章**（docindex.py:183-186
    使最外层章 end=全文行数，任何改动都让它变 ⇒ 不排除则判据几乎恒真）后，旧式错位槽
    少于 2 即报「对账无判别力」并失败；
  · `legacy_claim == 0` —— 旧节点记录的 heading_path/lineno/end 与 items_v1 同序号
    条目一致（对账基线自洽）。

用法（第 15 条：argv 列表 + 显式 UTF-8，不经 Windows shell）
    python -X utf8 scripts/_mdcg_reindex_dshlogs.py --root <临时库根> \\
        --sessions-root <会话根> --transcripts-root <转写根> --reconcile full
依赖：zstandard（转写链路的既有依赖，缺则 SystemExit）；md_cg 包（仓根导入）。
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import tempfile

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from md_cg import docindex, logref, refindex, srcindex             # noqa: E402
from md_cg.mdcos import MdCGSecure                                  # noqa: E402
from md_cg.security import Principal                                # noqa: E402

#: 启动即清的环境变量（root 与白名单绝不靠环境定；见模块 docstring）
ENV_CLEAN = ("MDCG_ROOT", "MDCG_TOKEN", "MDCG_TOKEN_FILE", "MDCG_MASTER_KEY",
             "MDCG_AUX_ROOT", "MDCG_VERIFY_KEY", "MDCG_INGEST_ROOT")

#: 临时库专用的固定合成主密钥（**显式**传给 MdCGSecure，不走 MDCG_MASTER_KEY）。它是
#: 哑值：本脚本只写 tempfile 库，故可公开且可复现；换成 32 字节 0..31 只为可复跑。
DEFAULT_MASTER_KEY = bytes(range(32))

KIND = "doc_ref"


# 生效条件：无入参；删除 ENV_CLEAN 中存在的环境变量并返回实际删掉的名单。
def clean_env() -> list:
    gone = []
    for k in ENV_CLEAN:
        if os.environ.pop(k, None) is not None:
            gone.append(k)
    return gone


# 生效条件：p 为任意值；返回 normcase(realpath(abspath(str(p or ""))))——大小写/短名/相对形态归一。
def _norm(p) -> str:
    return os.path.normcase(os.path.realpath(os.path.abspath(str(p or ""))))


# 生效条件：root 与 transcript_root 非空；归一后 root 未落在 tempfile.gettempdir() 之下、
# 或等于/属于活库根（AEIS 私有库）、或等于/属于本仓检出、或等于 transcript_root 时抛
# ValueError（原因逐条给出）；否则返回归一后的 root。
def guard_root(root: str, transcript_root: str) -> str:
    """库根守卫：只许「tempfile 之下的目录」，且不得与转写根/仓检出/活库根重合。

    判据全走 `normcase` 归一——Windows 的 realpath 会改大小写、短名与分隔符，
    不归一时「库根=转写根」这类错配会静默过闸（评审⑨实锚）。
    """
    if not root:
        raise ValueError("必须显式给出 --root（本工具不读 MDCG_ROOT，也不猜目标）")
    r = _norm(root)
    tmp = _norm(tempfile.gettempdir())
    if not (r == tmp or r.startswith(tmp + os.sep)):
        raise ValueError(
            "拒绝：库根不在系统临时目录之下 —— 本工具只写临时库（真源=活库）"
            "，root=%s（归一）不在 %s 之下" % (r, tmp))
    # 活库（AEIS 私有库）按**仓内既有约定**的相对形态认（`AEIS/data/mdcg`，见
    # docs/mdcg/ 多份裁定单）——不写盘符：换盘/换机/CI 上绝对形态不同，写死只会
    # 变成假阴性。尾段比对是**第二道**（第一道「必须在 tempdir 之下」已能拦它）。
    live_tail = os.path.normcase(os.path.join("aeis", "data", "mdcg"))
    if r == live_tail or r.endswith(os.sep + live_tail):
        raise ValueError("拒绝：库根命中活库（AEIS 私有库，…/AEIS/data/mdcg）：%s" % r)
    repo = _norm(REPO_ROOT)
    if r == repo or r.startswith(repo + os.sep):
        raise ValueError("拒绝：库根位于本仓检出内：%s" % r)
    if _norm(transcript_root) and r == _norm(transcript_root):
        raise ValueError("拒绝：库根 == 转写根（%s）——两者共用会把转写当库面处理" % r)
    return r


# 生效条件：无入参；返回经 importlib 加载的 scripts/dsh_log_index.py 模块对象。
# 该模块**一行不改**（含常量与读写语义）——只用其既有函数（同款先例：
# scripts/test_dsh_log_index_token.py:52-58、scripts/test_dsh_log_index_shape.py）。
def load_dsh_log_index():
    p = os.path.join(REPO_ROOT, "scripts", "dsh_log_index.py")
    spec = importlib.util.spec_from_file_location("_n203_dsh_log_index", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# 生效条件：tdir 为转写目录、rel 为本会话相对转写根的路径；返回 (items, errors, stats)，
# 其中每条 it["path"] 已改写成 rel（docindex.node_id 的寻址键面随之确定）。
def doc_items(tdir: str, rel: str) -> tuple:
    items, errors, stats = refindex.index_dir(
        tdir, kind=KIND, max_files=100, max_items=50000)
    for it in items:
        it["path"] = rel
    return items, errors, stats


# 生效条件：p 的父目录已存在或可建；把 text 以 UTF-8 + LF 逐字写入 p（幂等：同 text 同字节）。
def write_text(p: str, text: str) -> None:
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


#: 插话版合成的正文（哑数据）。**必须 ≥ docindex.MIN_BODY=200 字**：不足 200 的章会被
#: 并入父章（docindex.py:186/:190）而不产生新章 ⇒ 位移消失、对账退化为无判别力。
SPLICE_BODY = ("【合成插话】" + "这是用于两代对账的哑正文片段，" * 16)


# 生效条件：msgs 为 parse_session_log 的消息序列；返回在其**首条之后**插入一条合成
# user 消息的新序列（原序列不被修改）。插在首条之前会改 derive_session_token 的 basis。
def splice_message(msgs: list) -> list:
    out = [dict(m) for m in (msgs or [])]
    if not out:
        return out
    turn = out[0].get("turn") if isinstance(out[0].get("turn"), int) else 1
    out.insert(1, {"turn": turn, "role": "user", "text": SPLICE_BODY})
    return out


# 生效条件：legacy 为 ingest_transcript 的返回（None 时直接返回 token）；返回旧式节点实际
# 落在哪个 token 空间——派生标识碰撞（N167）时 ingest_transcript 会整体切 ext_token。
def _eff_token(token: str, ext_token: str, legacy: dict) -> str:
    col = (legacy or {}).get("collision") or {}
    return col.get("token_ext") or token if col else token


# 生效条件：p 为文件路径；返回其按 "\n" 切分的行列表。
def _lines(p: str) -> list:
    with open(p, "r", encoding="utf-8") as f:
        return f.read().split("\n")


# 生效条件：node 为 cg.get 的产物；返回 (kind, ref) 或 ('', None)。
def _ref_of(node) -> tuple:
    return refindex.ref_of(node)


# 生效条件：cg 的节点带 logsrc 标签且其 ref 探测为 dangling 时列入返回列表（只读）。
def dangling_logsrc(cg) -> list:
    nodes = (getattr(cg, "index", {}) or {}).get("nodes") or {}
    out = []
    for nid, e in nodes.items():
        if "logsrc" not in ((e or {}).get("tags") or []):
            continue
        try:
            node = cg.get(nid)
        except Exception:
            continue
        if not node:
            continue
        _k, ref = _ref_of(node)
        if not isinstance(ref, dict) or not ref:
            continue
        try:
            if refindex.probe_ref(ref).get("status") == "dangling":
                out.append(nid)
        except Exception:
            continue
    return sorted(out)


# 生效条件：传入两代 items、两代 write_session 结果与转写正文；返回对账计数 dict
# （missing/misplaced/roundtrip_mismatch/updated_expected/legacy_*）。
def reconcile(cg, *, items_v1: list, items_v2: list, gen2: dict, tpath: str,
              token: str, legacy1: dict = None, legacy2: dict = None,
              lines_v1: list = None) -> dict:
    """对账器：全部判据机械可执行（口径见模块 docstring），不猜、不抽样。"""
    nodes = (getattr(cg, "index", {}) or {}).get("nodes") or {}
    lines_v2 = _lines(tpath)
    total_v2 = len(lines_v2)

    def key(it):
        return (it.get("hash"), logref._int(it.get("lineno")), logref._int(it.get("end")))

    ids_v1 = [docindex.node_id(it) for it in items_v1]
    ids_v2 = [docindex.node_id(it) for it in items_v2]
    missing = [i for i in ids_v2 if i not in nodes]

    # 错位：新节点必须认领自己的正文（locate 取最内层，嵌套即最近者）
    misplaced = []
    for it, nid in zip(items_v2, ids_v2):
        node = cg.get(nid)
        if not node:
            misplaced.append({"id": nid, "why": "cg.get 读不回"})
            continue
        _k, ref = _ref_of(node)
        if not isinstance(ref, dict) or not ref:
            misplaced.append({"id": nid, "why": "无 doc_ref"})
            continue
        hit = docindex.locate(items_v2, ref.get("lineno"))
        if hit is None or hit.get("heading_path") != ref.get("heading_path"):
            misplaced.append({"id": nid, "lineno": ref.get("lineno"),
                              "claimed": (hit or {}).get("heading_path"),
                              "own": ref.get("heading_path")})

    # 回读逐字节：read_ref（唯一实现）的文本 == 转写同区间切片
    rtm = []
    for it, nid in zip(items_v2, ids_v2):
        node = cg.get(nid)
        if not node:
            rtm.append({"id": nid, "why": "cg.get 读不回"})
            continue
        _k, ref = _ref_of(node)
        if not isinstance(ref, dict) or not ref:
            rtm.append({"id": nid, "why": "无 doc_ref"})
            continue
        got = refindex.read_ref(ref)
        lo = max(0, logref._int(ref.get("lineno")) - 1)
        hi = max(lo, logref._int(ref.get("end")))
        want = "\n".join(lines_v2[lo:hi])
        if not got.get("ok") or got.get("text") != want:
            rtm.append({"id": nid, "ok": bool(got.get("ok")),
                        "hash_match": got.get("hash_match")})

    # 交叉核验：updated 必须等于「id 交集内 (hash,lineno,end) 不全等」的条数
    m1 = {nid: key(it) for it, nid in zip(items_v1, ids_v1)}
    m2 = {nid: key(it) for it, nid in zip(items_v2, ids_v2)}
    inter = sorted(set(ids_v1) & set(ids_v2))
    expected_updated = sum(1 for i in inter if m1[i] != m2[i])
    updated = len(gen2.get("overwritten") or [])
    no_ref = gen2.get("overwritten_no_ref") or 0

    # 旧式对照（仅 --reconcile full 有旧节点）
    legacy = {"nodes": len(items_v1) if legacy1 else 0,
              "claim": 0, "claim_rows": [], "misplaced_slots": 0,
              "misplaced_rows": [], "root_excluded": 0,
              "indexed": (legacy1 or {}).get("indexed") or [],
              "skipped_existing": (legacy1 or {}).get("skipped_existing"),
              # 旧式 id 是**位置化**的（`dsh-log-<token>-<序号>`）：重跑时前
              # min(n1,n2) 个槽全撞 id 被跳过，只有**尾部新增槽** n2-n1 个被写成
              # 新节点。这条等式即是「id 与位置绑定」的机械见证（不是判据的装饰）。
              "gen2_indexed": len((legacy2 or {}).get("indexed") or []),
              "gen2_skipped": (legacy2 or {}).get("skipped_existing"),
              "tail_expected": max(0, len(items_v2) - len(items_v1)),
              "tail_ok": (len((legacy2 or {}).get("indexed") or [])
                          == max(0, len(items_v2) - len(items_v1)))}
    if legacy1:
        for i, it in enumerate(items_v1):
            nid = "dsh-log-%s-%04d" % (token, i)
            node = cg.get(nid)
            if not node:
                legacy["claim"] += 1
                legacy["claim_rows"].append({"id": nid, "why": "旧式节点缺失"})
                continue
            dl = (node.get("frontmatter") or {}).get("dsh_log") or {}
            if (list(dl.get("heading_path") or []) != list(it.get("heading_path") or [])
                    or logref._int(dl.get("lineno")) != logref._int(it.get("lineno"))
                    or logref._int(dl.get("end")) != logref._int(it.get("end"))):
                legacy["claim"] += 1
                legacy["claim_rows"].append({"id": nid, "recorded": {
                    "heading_path": dl.get("heading_path"),
                    "lineno": dl.get("lineno"), "end": dl.get("end")}})
            if logref._int(it.get("end")) >= len(lines_v1):
                # 根章（最外层章 end=全文行数）：任何改动都让它变，留着判据几乎恒真
                legacy["root_excluded"] += 1
                continue
            hit = docindex.locate(items_v2, dl.get("lineno"))
            if hit is None or list(hit.get("heading_path") or []) != list(dl.get("heading_path") or []):
                legacy["misplaced_slots"] += 1
                legacy["misplaced_rows"].append(
                    {"id": nid, "lineno": dl.get("lineno"),
                     "recorded": dl.get("heading_path"),
                     "now": (hit or {}).get("heading_path")})

    return {"missing": len(missing), "missing_ids": missing[:10],
            "misplaced": len(misplaced), "misplaced_rows": misplaced[:10],
            "roundtrip_mismatch": len(rtm), "roundtrip_rows": rtm[:10],
            "updated": updated, "updated_expected": expected_updated,
            "updated_no_ref": no_ref, "id_intersection": len(inter),
            "new_items_gen2": len(gen2.get("new") or []),
            "unchanged": len(gen2.get("unchanged") or []),
            "blocked": len(gen2.get("blocked") or []),
            "blocked_rows": (gen2.get("blocked") or [])[:5],
            "total_lines_v2": total_v2, "legacy": legacy}


# 生效条件：s 为 discover_sessions 的一条；返回该会话的一代/两代落库报告（含对账）。
def run_session(cg, dlg, s: dict, *, sessions_root: str, transcripts_root: str,
                reconcile_mode: str, src_path_mode: str, pruned: list,
                src_state: dict = None) -> dict:
    ws, sid = s["workspace"], s["session_id"]
    rel = logref.default_rel_of(ws, sid)
    tdir = os.path.join(transcripts_root, ws, sid)
    tpath = os.path.join(tdir, sid + ".md")
    # 会话级 src 水位（节点自描述，不新造台账）：每个节点的 doc_ref.src.file_hash
    # 与当前真源相同 ⇒ 真源未变。off 模式下可跳过 re-parse（省掉 zstd 解压 + 重切），
    # 计 sessions_skipped——这条正是 `--incremental` 被删后的替代增量口径。
    # 只在**转写在位**时跳过：转写被系统清理后必须重生成（那是 --repair 的活）。
    wm = ((src_state or {}).get("sessions") or {}).get("%s/%s" % (ws, sid)) or {}
    if (reconcile_mode == "off" and wm.get("n") and wm.get("changed") is False
            and os.path.isfile(tpath)):
        return {"workspace": ws, "session": sid, "sessions_skipped": 1,
                "src_watermark": {"changed": False, "nodes": wm.get("n")},
                "skip_reason": ("会话级 src 水位未变（每个节点的 doc_ref.src.file_hash "
                                "== 当前真源）且转写在位 ⇒ 跳过 re-parse；"
                                "要强行重切用 --reconcile generation"),
                "transcript_md": tpath, "ok": True,
                "counts": {"new_items": 0, "updated": 0, "unchanged": 0,
                           "blocked": 0, "missing": 0, "misplaced": 0,
                           "roundtrip_mismatch": 0, "legacy_misplaced_slots": 0,
                           "legacy_claim": 0, "legacy_tail_mismatch": 0,
                           "encrypted_nodes": 0, "sessions_skipped": 1}}
    parsed = dlg.parse_session_log(s["log"])
    token = dlg.derive_session_token(parsed["meta"], parsed["msgs"])
    ext_token = dlg.derive_session_token_ext(parsed["meta"], parsed["msgs"], ws, sid)
    src = srcindex.session_src_id(s["log"], session_uuid=sid, workspace=ws,
                                 path_mode=src_path_mode, base=sessions_root)
    rep = {"workspace": ws, "session": sid, "session_token": token,
           "sessions_skipped": 0,
           "src": {"kind": src.get("kind"),
                   "path": src.get("path"),
                   "file_hash": src.get("file_hash")}}
    # ---- 第 1 代 ----
    md_v1 = dlg.render_transcript(ws, parsed)
    write_text(tpath, md_v1)
    lines_v1 = md_v1.split("\n")
    items_v1, err_v1, st_v1 = doc_items(tdir, rel)
    legacy1 = None
    if reconcile_mode == "full":
        legacy1 = dlg.ingest_transcript(cg, ws, sid, tdir, token, ext_token)
    gen1 = logref.write_session(cg, items_v1, transcript_root=transcripts_root,
                                src=src, session=token, workspace=ws,
                                session_uuid=sid)
    po1 = refindex.prune_orphans(cg, kind=KIND, root=transcripts_root, items=items_v1)
    pruned.append({"stage": "gen1", "session": sid, "count": po1.get("count"),
                   "scanned": po1.get("scanned"),
                   "touched_files": po1.get("touched_files")})
    rep.update({
        "files_v1": st_v1.get("files"), "items_v1": len(items_v1),
        "extract_errors": err_v1[:3],
        "gen1": {"new": len(gen1["new"]), "overwritten": len(gen1["overwritten"]),
                 "unchanged": len(gen1["unchanged"]),
                 "blocked": len(gen1["blocked"]), "encrypted": gen1["encrypted"]},
        "sensitivity": gen1["sensitivity"], "sens_counts": gen1["sens"],
        "legacy_v1": None if legacy1 is None else {
            "items": legacy1["items"], "indexed": len(legacy1["indexed"]),
            "skipped_existing": legacy1["skipped_existing"],
            "collision": bool(legacy1.get("collision")),
            # 旧式节点实际写在哪个 token 空间：派生标识碰撞（N167）时 ingest_transcript
            # 会整体切 `ext_token`（dsh_log_index.py:596-607）——对账必须按**生效 token**
            # 取旧节点，否则会去查别人会话的节点、把基线判成不自洽（实测踩过）。
            "effective_token": _eff_token(token, ext_token, legacy1)},
    })
    cg_now = logref.session_src_state(cg).get("sessions", {}).get("%s/%s" % (ws, sid))
    rep["src_watermark"] = {"changed": (cg_now or {}).get("changed"),
                            "nodes": (cg_now or {}).get("n", 0)}
    if reconcile_mode == "off":
        rep["ok"] = not gen1["blocked"]
        rep["counts"] = {"new_items": len(gen1["new"]),
                         "updated": len(gen1["overwritten"]),
                         "unchanged": len(gen1["unchanged"]),
                         "blocked": len(gen1["blocked"]),
                         "encrypted_nodes": gen1["encrypted"],
                         "sessions_skipped": 0}
        rep["transcript_md"] = tpath
        return rep

    # ---- 第 2 代：插话版 ----
    msgs_v2 = splice_message(parsed["msgs"])
    md_v2 = dlg.render_transcript(ws, {"meta": parsed["meta"], "msgs": msgs_v2})
    write_text(tpath, md_v2)
    items_v2, err_v2, st_v2 = doc_items(tdir, rel)
    legacy2 = None
    if reconcile_mode == "full":
        # 旧式公式重跑：id 撞即跳（dsh_log_index.py:611-613）⇒ 旧节点留在 v1 区间
        legacy2 = dlg.ingest_transcript(cg, ws, sid, tdir, token, ext_token)
    gen2 = logref.write_session(cg, items_v2, transcript_root=transcripts_root,
                                src=src, session=token, workspace=ws,
                                session_uuid=sid)
    po2 = refindex.prune_orphans(cg, kind=KIND, root=transcripts_root, items=items_v2)
    pruned.append({"stage": "gen2", "session": sid, "count": po2.get("count"),
                   "scanned": po2.get("scanned"),
                   "touched_files": po2.get("touched_files")})
    rec = reconcile(cg, items_v1=items_v1, items_v2=items_v2, gen2=gen2,
                    tpath=tpath, token=_eff_token(token, ext_token, legacy1),
                    legacy1=legacy1, legacy2=legacy2, lines_v1=lines_v1)
    g2 = {"items": len(items_v2), "new": len(gen2["new"]),
          "overwritten": len(gen2["overwritten"]), "unchanged": len(gen2["unchanged"]),
          "blocked": len(gen2["blocked"]), "encrypted": gen2["encrypted"],
          # 逐条状态只留头 20 条：真实会话可上千条，报告要能被人看（全量在进程内
          # 结果里，不在此处的 stdout 面）。
          "rows": [{"id": r["id"], "state": r["state"]} for r in gen2["rows"][:20]],
          "rows_total": len(gen2["rows"])}
    ok = (rec["missing"] == 0 and rec["misplaced"] == 0
          and rec["roundtrip_mismatch"] == 0
          and rec["updated"] == rec["updated_expected"]
          and rec["blocked"] == 0)
    if reconcile_mode == "full":
        ok = (ok and rec["legacy"]["claim"] == 0
              and rec["legacy"]["misplaced_slots"] >= 2
              and rec["legacy"]["tail_ok"])
        if rec["legacy"]["misplaced_slots"] < 2:
            rec["no_discriminating_power"] = (
                "旧式错位槽 < 2：对账无判别力（夹具未造成位置漂移或漂移过小）")
    rep.update({
        "files_v2": st_v2.get("files"), "items_v2": len(items_v2),
        "extract_errors_v2": err_v2[:3],
        "gen2": g2,
        "legacy_v2": None if legacy2 is None else {
            "indexed": len(legacy2["indexed"]),
            "skipped_existing": legacy2["skipped_existing"]},
        "reconcile": rec, "ok": ok,
        "counts": {"new_items": len(gen1["new"]),      # 新增条目数（新路线首次落库）
                   "new_items_gen2": len(gen2["new"]),
                   "updated": rec["updated"],
                   "updated_expected": rec["updated_expected"],
                   "unchanged": rec["unchanged"],
                   "blocked": rec["blocked"],
                   "missing": rec["missing"],          # 遗漏数（应为 0）
                   "misplaced": rec["misplaced"],      # 错位数（应为 0）
                   "roundtrip_mismatch": rec["roundtrip_mismatch"],
                   "legacy_misplaced_slots": rec["legacy"]["misplaced_slots"],
                   "legacy_claim": rec["legacy"]["claim"],
                   "legacy_tail_mismatch": 0 if rec["legacy"]["tail_ok"] else 1,
                   "encrypted_nodes": gen1["encrypted"] + gen2["encrypted"],
                   "sessions_skipped": 0},
    })
    rep["transcript_md"] = tpath
    return rep


# 生效条件：无入参（除 argv）；按 args 执行落库＋对账（或 --repair 自检），
# 返回进程退出码（0=全绿；1=对账未过；2=参数/守卫拒绝）。
def main(argv=None) -> int:
    gone_env = clean_env()
    ap = argparse.ArgumentParser(
        description="DSH 会话日志 → ref 索引（临时库）＋两代对账"
                    "（输出不含日志正文）")
    ap.add_argument("--root", required=True,
                    help="认知图库根（**只许系统临时目录之下**；不读 MDCG_ROOT）")
    ap.add_argument("--sessions-root", required=True,
                    help="DSH 会话根（其下为 <工作区目录名>/<session-id>/）")
    ap.add_argument("--transcripts-root",
                    default=os.path.join(tempfile.gettempdir(),
                                         "dsh-log-transcripts"),
                    help="转写根（缺省与 scripts/dsh_log_index.py:138 同址）")
    ap.add_argument("--workspace", default=None, help="只处理指定工作区目录名")
    ap.add_argument("--session", default=None, help="只处理指定 session-id")
    ap.add_argument("--reconcile", default="off",
                    choices=("off", "generation", "full"),
                    help="off=单代落库；generation=两代（含插话）；full=两代＋旧式对照")
    ap.add_argument("--repair", default="0", choices=("0", "1"),
                    help="1=先扫 dangling 的 logsrc 节点、落库后复核（再生转写）")
    ap.add_argument("--max-nodes", type=int, default=refindex.MAX_CHECK,
                    help="清退巡检上限")
    ap.add_argument("--src-path", default="abs", choices=srcindex.SRC_PATH_MODES,
                    help="真源路径落库档位（abs 全功能；rel/hash 为暴露面降级，"
                         "此时 probe_src 返回 unresolved）")
    ap.add_argument("--master-key", default=None,
                    help="显式主密钥（64 位 hex）；缺省用固定合成哑密钥（临时库专用）")
    ap.add_argument("--tenant", default="default")
    ap.add_argument("--actor", default="n203-p1")
    args = ap.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    tmark = os.path.join(tempfile.gettempdir(), "dsh-log-transcripts")
    try:
        root = guard_root(args.root, args.transcripts_root or tmark)
    except ValueError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 2
    if not os.path.isdir(args.sessions_root):
        print(json.dumps({"ok": False,
                          "error": "会话根不存在或不是目录：%s" % args.sessions_root},
                         ensure_ascii=False))
        return 2
    try:
        dlg = load_dsh_log_index()
    except Exception as exc:                    # 依赖缺失（zstandard）等 → fail-closed
        print(json.dumps({"ok": False, "error": "加载 dsh_log_index 失败：%s" % exc},
                         ensure_ascii=False))
        return 2

    mkey = bytes.fromhex(args.master_key) if args.master_key else DEFAULT_MASTER_KEY
    p = Principal(tenant=args.tenant, actor=args.actor, clearance="private",
                  can_write=True, can_admin=True)
    cg = MdCGSecure(root, principal=p, autoflush=1, master_key=mkey)
    total = {"sessions": 0, "ok": True, "env_cleaned": gone_env,
             "root": root, "transcripts_root": args.transcripts_root,
             "reconcile": args.reconcile, "src_path": args.src_path,
             "new_items": 0, "missing": 0, "misplaced": 0, "sessions_skipped": 0,
             "updated": 0, "updated_expected": 0,
             "legacy_misplaced_slots": 0, "legacy_claim": 0,
             "legacy_tail_mismatch": 0,
             "encrypted_nodes": 0, "blocked": 0}
    pruned = []
    try:
        pre_dangling = dangling_logsrc(cg) if args.repair == "1" else []
        sessions = dlg.discover_sessions(args.sessions_root, args.workspace,
                                         args.session)
        if not sessions:
            print(json.dumps({"ok": False, "error": "未发现匹配的会话日志"},
                             ensure_ascii=False))
            return 1
        # 会话级 src 水位**一次**算好（O(节点)），供各会话判「真源是否未变」
        src_state = logref.session_src_state(cg)
        for s in sessions:
            rep = run_session(cg, dlg, s, sessions_root=args.sessions_root,
                              transcripts_root=args.transcripts_root,
                              reconcile_mode=args.reconcile,
                              src_path_mode=args.src_path, pruned=pruned,
                              src_state=src_state)
            total["sessions"] += 1
            total["ok"] = total["ok"] and bool(rep.get("ok"))
            c = rep.get("counts") or {}
            for k in ("new_items", "missing", "misplaced", "updated",
                      "updated_expected", "legacy_misplaced_slots",
                      "legacy_claim", "legacy_tail_mismatch",
                      "encrypted_nodes", "blocked", "sessions_skipped"):
                total[k] += c.get(k, 0) or 0
            if c.get("encrypted_nodes"):
                print("WARNING: 会话 %s/%s 的 %d 个索引节点落在加密档"
                      "（sensitivity ∈ crypto.ENCRYPTED_LEVELS）——正文被封套，"
                      "检索会零命中（v1.0 的实测坑）。请核真源路径判"
                      "（docindex.sensitivity_for）与密级裁决。" %
                      (s["workspace"], s["session_id"], c["encrypted_nodes"]),
                      file=sys.stderr)
            print(json.dumps(rep, ensure_ascii=False))
        if args.repair == "1":
            post = dangling_logsrc(cg)
            fixed = [n for n in pre_dangling if n not in post]
            total["repair"] = {"pre_dangling": len(pre_dangling),
                               "post_dangling": len(post),
                               "repaired": len(fixed),
                               "remaining": post[:10]}
            print(json.dumps({"repair": total["repair"]}, ensure_ascii=False))
        total["prune_orphans"] = pruned
        if args.reconcile == "full":
            # 悬空清退：带 regenerable 的节点被排除（计数 regenerable_skipped）——
            # 转写落临时目录、被清理后必然 dangling，软删它们与「可再生」冲突。
            pd = refindex.prune_dangling(cg, only_roots=[args.transcripts_root],
                                         dry_run=True, max_nodes=args.max_nodes)
            total["prune_dangling_dry"] = {
                "candidates": pd.get("candidates"),
                "regenerable_skipped": pd.get("regenerable_skipped"),
                "truncated": pd.get("truncated")}
    except SystemExit as exc:                    # dsh_log_index 的 fail-closed 出口
        print(json.dumps({"ok": False, "error": "SystemExit: %s" % exc},
                         ensure_ascii=False))
        cg.close()
        return 2
    finally:
        try:
            cg.close()
        except Exception:
            pass

    print(json.dumps({"TOTAL": total,
                      "mode": "reconcile-%s" % args.reconcile},
                     ensure_ascii=False))
    return 0 if total["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
