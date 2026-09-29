# -*- coding: utf-8 -*-
"""test_logref —— N203 P1/P2 守卫：日志真源 → ref 索引（临时库）。

覆盖 plan §6 守卫表的六条口径（幂等 / 插话两代 / 悬空 / 回读逐字节 / 密级跟源 /
path 口径）＋两面（⓪ 写面边界、⑦ 生产读面端到端），并自带**定点变异红基线**（见下）。

链路：合成 zstd 日志 → `scripts/dsh_log_index.py` 的转写（**该模块一行不改**，只
importlib 复用）→ `md_cg/logref.write_session` 落 ref 节点 → 两代对账。

守卫面（判据全走**合成夹具**：哑日志/哑正文/临时库，绝不触活库、真实会话与真实转写根）
  ⓪ 写面边界 —— 库根必须在 tempfile 之下，且不得等于转写根/仓检出；**比对走 normcase**
     （Windows realpath 会改大小写，纯 realpath 比对会让「库根=转写根」过闸，评审⑨）。
  ① 幂等 —— 同源重跑 `updated == 0`、全库区间哈希复核全 ok。
  ② 同标题异内容 —— 同区间换正文（**长度不变**）⇒ id 不变而 hash 变：必须被计成
     `updated`；把落库判据改回「id 撞即跳」（变异）后 `updated == 0` 且区间哈希复核
     出现不一致 ⇒ 该判据必转红。这是 N203 静默的根因面。
  ③ 插话两代 —— 旧式非根章错位槽 ≥ 2（判别力）、新式 `missing/misplaced/roundtrip` 全 0、
     `updated == updated_expected`、旧式重跑全撞 id（旧节点留 v1）。
  ④ 悬空 —— 删真源 ⇒ src 层 dangling；删转写 ⇒ 区间层 dangling 而 **src 层仍 ok**（两层
     解耦）；带 `regenerable` 的节点不被 `prune_dangling` 列入（计数透出），反向对照的
     非 regenerable 悬空节点**必须**被列入。
  ⑤ 密级跟源 —— 节点密级 == `docindex.sensitivity_for(src["path"], None)` 的**真源路径判**；
     落进 `crypto.ENCRYPTED_LEVELS` 时报告里必须出现加密告警计数（v1.0 误标 private 致
     检索零命中，静默复现不可接受）；且一律不低于 internal。
  ⑥ path 口径 —— `doc_ref.root` == 转写根、path 为相对路径；同 sid 跨 ws 时**裸文件名
     口径必撞 id**、改写口径 0 撞；绝对 path 当 rel 在 `probe_ref` 里仍会 status=ok
     （既有实现不拦）⇒ 口径必须由落库侧写死。

红基线（判别力自证，见 `_MUTATIONS`/`EXPECTED_RED`）
    python -X utf8 -m md_cg.test_logref --head-baseline
读**工作区** `md_cg/logref.py` 的源码文本，按定点变异表把落库判据（「区间哈希 + 行位
全等才算已索引」）改回 N203 v1.0 的「**id 撞即跳**」，用变异后的 `node_state` 跑**同一
套** check，断言「红项集合 == 预期红项」（恰好命中，多一项少一项都报红）。锚点命中次数
不是恰好 1（漂移/歧义）即 ANCHOR-MISS → fail-closed（**两态都查**：绿态也查，免得锚点
漂移后绿线还绿着、红基线已静默失效）。不取 `git show HEAD:` 做基线源——HEAD 在改动
提交那一刻就变成实现本身，判别力会静默失效（前车之鉴见
`md_cg/test_policy_required_ccg.py` 头注：批次 70/77）。

运行：python -X utf8 -m md_cg.test_logref [--head-baseline]
依赖：zstandard（缺失 → 正文链路 SKIP 退出 0，对齐 run_tests 裸 clone 不假红口径；
      但锚点 + 红项表自证照跑——漂移/陈化仍退出 2，不因缺依赖而变纯空转）
退出码：绿态 0=全绿；红基线 0=红项集合符合预期；2=锚点漂移／红项表陈化（fail-closed）
"""
from __future__ import annotations

import argparse
import contextlib
import importlib.util
import io
import json
import os
import shutil
import sys
import tempfile
import traceback

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from md_cg import codeindex, crypto, docindex, logref, refindex, srcindex   # noqa: E402
from md_cg.mdcos import MdCGSecure                       # noqa: E402
from md_cg.security import Principal                     # noqa: E402

PASS = FAIL = 0
FAILS = []
RED = []          # 转红项 cid（红基线模式比对用；绿态为空）
TOOL = None


def ck(cid: str, ok: bool, detail="") -> None:
    global PASS, FAIL
    if ok:
        PASS += 1
    else:
        FAIL += 1
        RED.append(cid)
        FAILS.append("%s %s" % (cid, detail))
    print("  %s %s%s" % ("OK  " if ok else "FAIL", cid, "" if ok else "  " + str(detail)[:220]))


# ---------------- 夹具（全合成：哑 zstd 日志 + 哑正文） ----------------

def _body(tag: str, n: int = 16) -> str:
    """合成正文。**必须 ≥ docindex.MIN_BODY=200 字**：不足的章会被并入父章
    （docindex.py:186/:190），夹具就造不出「多节」结构。"""
    return ("【%s】" % tag) + ("合成哑正文片段，仅用于夹具对齐。" * n)


def _msg(turn: int, role: str, text: str, mid: str) -> str:
    if role == "user":
        return json.dumps({"type": "user/message",
                           "data": {"id": mid,
                                    "content": [{"type": "text", "text": text}]}},
                          ensure_ascii=False)
    return json.dumps({"type": "assistant/message",
                       "data": {"turn": turn, "id": mid,
                                "message": {"content": [{"type": "text",
                                                         "text": text}]}}},
                      ensure_ascii=False)


def _log_lines(sid: str, mark: int = 1, n_turns: int = 3, splice: bool = False) -> list:
    """合成 v4 日志行：首行 session 元数据 + 每轮 user/assistant（正文各 ≥200 字）。

    `mark` 换**同长度**的哑正文（用于「同标题同区间换内容」：行数不变、hash 变）。
    `splice=True` 在**首条 user 之后**插入一条 user 消息（靠前处插一节）：插入点必须
    在首条之后，否则 `derive_session_token` 的 basis 变、旧式 id 空间整体换掉。
    """
    ls = [json.dumps({"type": "session", "id": "uuid-" + sid,
                      "createdAt": 1750000000000, "cwd": "D:/gt-ws",
                      "agentPreset": "p"}, ensure_ascii=False)]
    for t in range(1, n_turns + 1):
        ls.append(json.dumps({"type": "turn/start", "data": {"turn": t}}))
        ls.append(_msg(t, "user", _body("用户%d" % t), "u-%d" % t))
        if splice and t == 1:
            ls.append(_msg(1, "user", _body("插话"), "u-1b"))
        ls.append(_msg(t, "assistant", _body("助手%dr%d" % (t, mark)), "a-%d" % t))
    return ls


def _write_log(path: str, lines: list) -> bytes:
    import zstandard as zstd
    raw = ("\n".join(lines) + "\n").encode("utf-8")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(zstd.ZstdCompressor().compress(raw))
    with open(path, "rb") as f:
        return f.read()


#: 夹具会话（ws-a/private-ws 下同名 sid —— ⑥ 的「同 sid 跨 ws」前提就靠它）
SESSIONS = (("ws-a", "sess-1"), ("ws-a", "sess-2"), ("private-ws", "sess-1"))


def make_fixture(base: str) -> str:
    sroot = os.path.join(base, "sessions")
    for ws, sid in SESSIONS:
        _write_log(os.path.join(sroot, ws, sid, "session.v4.jsonl.zstd"),
                   _log_lines(sid))
    return sroot


def log_path(sroot: str, ws: str, sid: str) -> str:
    return os.path.join(sroot, ws, sid, "session.v4.jsonl.zstd")


# ---------------- 工具驱动（importlib 复用 scripts/_mdcg_reindex_dshlogs.py） ----------------

def load_tool():
    p = os.path.join(REPO, "scripts", "_mdcg_reindex_dshlogs.py")
    spec = importlib.util.spec_from_file_location("_n203_guard_tool", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run_tool(argv: list) -> tuple:
    """直调入口 main(argv)（沙箱友好）：返回 (rc, 每会话报告, TOTAL, stderr)。"""
    buf_out, buf_err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(buf_out), contextlib.redirect_stderr(buf_err):
        rc = TOOL.main(list(argv))
    rows, total = {}, None
    for ln in buf_out.getvalue().splitlines():
        ln = ln.strip()
        if not ln.startswith("{"):
            continue
        try:
            o = json.loads(ln)
        except ValueError:
            continue
        if "TOTAL" in o:
            total = o["TOTAL"]
        elif o.get("session"):
            rows["%s/%s" % (o.get("workspace"), o.get("session"))] = o
    return rc, rows, total, buf_err.getvalue()


def base_argv(lib: str, sroot: str, tr: str, mode: str, ws: str = None,
              sid: str = None) -> list:
    a = ["--root", lib, "--sessions-root", sroot, "--transcripts-root", tr,
         "--reconcile", mode]
    if ws:
        a += ["--workspace", ws]
    if sid:
        a += ["--session", sid]
    return a


def paths(tmp: str, name: str) -> tuple:
    d = os.path.join(tmp, name)
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "lib"), os.path.join(d, "tr")


def tr_path(tr: str, ws: str, sid: str) -> str:
    return os.path.join(tr, ws, sid, sid + ".md")


def open_lib(lib: str, *, can_write: bool = True, can_admin: bool = True,
             session: str = None):
    """读库身份：**actor 必须与写入侧一致**（工具缺省 n203-p1）——私有档的 DEK 按身份
    封装，换 actor 连密钥都解不开（`cg.get` 恒 None）；这与密级/会话无关，是密钥面。"""
    p = Principal(actor=TOOL_ARGS["actor"], clearance="private",
                  can_write=can_write, can_admin=can_admin, role="designer",
                  session=session)
    return MdCGSecure(lib, principal=p, master_key=TOOL.DEFAULT_MASTER_KEY)


#: 与工具缺省一致的身份/租户（守卫只用它们构造读写两侧实例）
TOOL_ARGS = {"actor": "n203-p1", "tenant": "default"}


def entries_of(cg, tag: str = "logsrc") -> dict:
    """库中带 tag 的**索引条目**（元数据快照，不经读隔离）——private 档节点在
    「非本会话」身份下 `cg.get` 读不回（会话绑定），故需要元数据面时走这里。"""
    return {nid: (e or {}) for nid, e in list((cg.index.get("nodes") or {}).items())
            if tag in ((e or {}).get("tags") or [])}


def nodes_of(cg, tag: str = "logsrc") -> dict:
    """库中带 tag 的节点 → {nid: node}（读面：cg.get，密级/加密均按真实读隔离）。"""
    out = {}
    for nid, e in sorted((cg.index.get("nodes") or {}).items()):
        if tag not in ((e or {}).get("tags") or []):
            continue
        g = cg.get(nid)
        if g:
            out[nid] = g
    return out


def _int_or(v, d: int = -1) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return d


def _it_key(it: dict) -> tuple:
    return (it.get("hash"), _int_or(it.get("lineno")), _int_or(it.get("end")))


def ref_keys(cg) -> dict:
    """快照库里每个 logsrc 节点**自己的** doc_ref 判据键：{nid: (hash,lineno,end)}。

    用于在落库**之前**取「覆写前态」——落库后再取就变成后态，等式会退化成 0==0。
    """
    out = {}
    for nid, node in nodes_of(cg).items():
        _k, ref = refindex.ref_of(node)
        out[nid] = _it_key(ref or {})
    return out


def expected_updated(cg, items, rel: str, pre: dict = None) -> int:
    """`updated` 的**独立**期望值：同 id 但 (hash,lineno,end) 与**前态**不全等的条数。

    口径与工具里对账器的 `updated_expected` 同源（「同 id 不同内容必被计数」），但
    数据面**不借道 `node_state`**——否则变异态下判据会自己跟自己对偶（`node_state`
    说 unchanged、计数也是 0，等式恒真）。red-baseline 要求这条等式在变异态**必不成立**。
    `pre` 为 `ref_keys` 的前态快照；不给则取**当前**节点（仅适合后态未写的情形）。
    """
    n = 0
    for it in items or []:
        it2 = dict(it)
        it2["path"] = rel
        nid = docindex.node_id(it2)
        if pre is not None:
            cur = pre.get(nid, _MISSING)
        else:
            _k, r = refindex.ref_of(cg.get(nid))
            cur = _it_key(r or {}) if r else _MISSING
        if cur != _it_key(it2):
            n += 1
    return n


#: 「库里没有这个 id / 没有可读 doc_ref」的哨兵（与任何判据键都不相等）
_MISSING = object()


def hash_audit(cg, tpath: str) -> list:
    """逐节点复核：节点 doc_ref 的 (hash,lineno,end) 与**当前**转写同区间重算是否一致。

    返回不一致清单（空即全 ok）。判据与落库判据同源（docindex.region_hash）。
    """
    if not os.path.isfile(tpath):
        return [{"why": "转写缺失", "path": tpath}]
    with open(tpath, encoding="utf-8") as f:
        lines = f.read().split("\n")
    bad = []
    for nid, node in nodes_of(cg).items():
        _k, ref = refindex.ref_of(node)
        if not isinstance(ref, dict) or not ref:
            bad.append({"id": nid, "why": "无 doc_ref"})
            continue
        lo = int(ref.get("lineno") or 1)
        hi = int(ref.get("end") or lo)
        got = codeindex.region_hash(lines, lo, hi)   # 区间哈希的**唯一实现**
        if got != ref.get("hash"):
            bad.append({"id": nid, "node_hash": ref.get("hash"), "now": got})
    return bad


# ---------------- ⓪ 写面边界 ----------------

def guard_boundary(tmp: str) -> None:
    lib, tr = paths(tmp, "g0")
    # 活库形态用**相对尾段**造（`<tmp>/AEIS/data/mdcg`）——证明「活库」这道判据本身生效，
    # 而不是被「必须在 tempdir 之下」那句顺手拦下（否则它是一条永不触发的死判据）。
    cases = [("空 root", "", tr),
             ("仓检出", REPO, tr),
             ("tempdir 之外", os.path.dirname(tempfile.gettempdir()), tr),
             ("转写根自身", tr, tr),
             ("转写根的**大小写变体**", tr.upper(), tr),
             ("活库形态尾段", os.path.join(tmp, "AEIS", "data", "mdcg"), tr)]
    for label, r, t in cases:
        try:
            TOOL.guard_root(r, t)
            ck("0a[拒绝 %s]" % label, False, "未拒：%r" % (r,))
        except ValueError:
            ck("0a[拒绝 %s]" % label, True)
    ck("0b[normcase 判据存在] 大小写变体的归一结果相等",
       TOOL._norm(tr) == TOOL._norm(tr.upper()),
       (TOOL._norm(tr), TOOL._norm(tr.upper())))
    ck("0c[放行] tempfile 之下的库根", bool(TOOL.guard_root(lib, tr)))


# ---------------- ① 幂等 + ② 同标题异内容（含变异必红） ----------------

#: 「id 撞即跳」的变异判据（**进程内对照**，非发版红基线）：只认 id，不认 hash/行位。
#: 发版红基线是 `--head-baseline`（对工作区 logref.py 源文本做定点变异、须恰好命中
#: EXPECTED_RED）；这里保留一份手写对照，是为了在**绿态**也能就地看到「静默」长什么样
#: （2c/2d：updated==0 而区间哈希复核不一致）——它不随实现漂移，故不能替代定点变异。
def _id_only_state(cg, it, kind="doc_ref"):
    nid = refindex.node_id_of(it, kind)
    if nid in ((getattr(cg, "index", {}) or {}).get("nodes") or {}):
        return {"id": nid, "state": "unchanged"}
    return {"id": nid, "state": "new"}


def guard_idem_and_content(tmp: str, sroot: str) -> None:
    lib, tr = paths(tmp, "g1")
    a = base_argv(lib, sroot, tr, "off", "ws-a", "sess-1")
    rc1, _r1, t1, _e1 = run_tool(a)
    ck("1a[首轮] rc=0 且新增条目数 > 0",
       rc1 == 0 and (t1 or {}).get("new_items", 0) > 0, (rc1, t1))
    first_new = (t1 or {}).get("new_items", 0)
    ck("1a'[首轮] 未跳过任何会话（无既有节点 ⇒ 水位判据无从生效）",
       (t1 or {}).get("sessions_skipped") == 0, (t1 or {}).get("sessions_skipped"))
    rc2, rows2, t2, _e2 = run_tool(a)
    ck("1b[同源重跑] 会话级 src 水位未变 ⇒ 跳过 re-parse（增量的替代口径）",
       rc2 == 0 and (t2 or {}).get("sessions_skipped") == 1
       and "src 水位未变" in (((rows2 or {}).get("ws-a/sess-1") or {}).get("skip_reason") or ""),
       (rc2, (t2 or {}).get("sessions_skipped")))
    ck("1c[同源重跑] 新增 == 0、updated == 0（无重写）",
       (t2 or {}).get("new_items") == 0 and (t2 or {}).get("updated") == 0,
       (t2 or {}).get("new_items"))
    tp1 = tr_path(tr, "ws-a", "sess-1")
    rel1 = "ws-a/sess-1/sess-1.md"
    _src = srcindex.session_src_id(log_path(sroot, "ws-a", "sess-1"),
                                   session_uuid="sess-1", workspace="ws-a")
    cg = open_lib(lib)
    try:
        ck("1d[区间哈希全 ok] 节点 doc_ref 与当前转写逐条一致（跳过的前提真的成立）",
           not hash_audit(cg, tp1))
        # 判据的**正例**（单元级）：同一条目在库里必须判 unchanged——上面 1b 走的是
        # 水位跳过，这条直接钉落库判据本身，免得「跳过」把判据的可观测性一起跳掉
        states = [logref.node_state(cg, dict(u["item"], path=rel1))
                  for u in srcindex.log_units(tp1, _src, path=rel1)]
        ck("1f[落库判据正例] 未变源上逐条判 unchanged",
           bool(states) and all(s["state"] == "unchanged" for s in states),
           [s["state"] for s in states])
    finally:
        cg.close()

    # ② 同标题同区间换正文（真源侧换字，长度不变 ⇒ 行数与区间不变、hash 变）
    lp = log_path(sroot, "ws-a", "sess-1")
    _write_log(lp, _log_lines("sess-1", mark=2))
    cg = open_lib(lib)
    try:
        pre3 = ref_keys(cg)                 # **落库前**的前态（落库后取就退化成 0==0）
    finally:
        cg.close()
    rc3, _r3, t3, _e3 = run_tool(a)
    ck("2a[同标题异内容] 被计成 updated（不静默）",
       rc3 == 0 and (t3 or {}).get("updated", 0) > 0, (rc3, t3))
    # 交叉核验（独立数据面，不经 node_state）：期望值 = 覆写前态与当前条目 (hash,lineno,end)
    # 不全等的条数。变异态（id 撞即跳 ⇒ updated==0 而期望数 > 0）下本条必转红。
    cg = open_lib(lib)
    try:
        exp3 = expected_updated(cg, [u["item"] for u in
                                     srcindex.log_units(tp1, _src, path=rel1)],
                                rel1, pre=pre3)
    finally:
        cg.close()
    ck("2b[同标题异内容] updated == 节点 doc_ref 判「需覆写」的条数（交叉核验）",
       exp3 > 0 and (t3 or {}).get("updated") == exp3,
       ((t3 or {}).get("updated"), exp3))

    # 2c/2d 变异：把落库判据换回「id 撞即跳」——再换一次正文后重跑，必须表现为静默
    _write_log(lp, _log_lines("sess-1", mark=3))
    orig = logref.node_state
    logref.node_state = _id_only_state
    try:
        rc4, _r4, t4, _e4 = run_tool(a)
    finally:
        logref.node_state = orig
    ck("2c[变异必红] id 撞即跳 ⇒ updated == 0（静默放过）",
       rc4 == 0 and (t4 or {}).get("updated") == 0, (rc4, (t4 or {}).get("updated")))
    cg = open_lib(lib)
    try:
        bad = hash_audit(cg, tr_path(tr, "ws-a", "sess-1"))
        ck("2d[变异必红] 区间哈希复核出现不一致（判据可判）", bool(bad),
           bad[:2])
    finally:
        cg.close()
    _write_log(lp, _log_lines("sess-1"))          # 还原真源（后续守卫不吃残留）
    ck("1e[夹具自净] 首轮新增数 == 章节数（可复核的基线）", first_new >= 4, first_new)


# ---------------- ③ 插话两代对账 ----------------

def guard_two_generations(tmp: str, sroot: str) -> None:
    lib, tr = paths(tmp, "g3")
    rc, rows, total, err = run_tool(base_argv(lib, sroot, tr, "full", "ws-a", "sess-1"))
    row = (rows or {}).get("ws-a/sess-1") or {}
    rec = row.get("reconcile") or {}
    lg = rec.get("legacy") or {}
    ck("3a[两代] rc=0", rc == 0, (rc, err[:200]))
    ck("3b[两代] 新增条目数 > 0", (total or {}).get("new_items", 0) > 0, total)
    ck("3c[两代] 遗漏数 == 0", (total or {}).get("missing") == 0,
       (total or {}).get("missing"))
    ck("3d[两代] 错位数 == 0", (total or {}).get("misplaced") == 0,
       (total or {}).get("misplaced"))
    ck("3e[两代] 回读逐字节 roundtrip == 0", rec.get("roundtrip_mismatch") == 0,
       rec.get("roundtrip_rows"))
    ck("3f[判别力] 旧式非根章错位槽 >= 2",
       lg.get("misplaced_slots", 0) >= 2, lg.get("misplaced_slots"))
    ck("3f'[判别力] 错位槽行的 recorded != now（确为错位而非同章）",
       bool(lg.get("misplaced_rows")) and all(
           list(r.get("recorded") or []) != list(r.get("now") or [])
           for r in (lg.get("misplaced_rows") or [])), lg.get("misplaced_rows")[:1])
    ck("3g[基线自洽] 旧节点记录 == items_v1（legacy_claim == 0）",
       lg.get("claim") == 0, lg.get("claim_rows")[:1])
    ck("3h[交叉核验] updated == updated_expected", rec.get("updated") == rec.get("updated_expected"),
       (rec.get("updated"), rec.get("updated_expected")))
    ck("3i[旧式位置化] 第 1 代全写（旧式无既有节点，skipped=0）",
       lg.get("skipped_existing") == 0 and lg.get("nodes") == row.get("items_v1"),
       (lg.get("skipped_existing"), lg.get("nodes"), row.get("items_v1")))
    ck("3i'[旧式位置化] 第 2 代按 id 撞即跳 ⇒ 跳过数 == 第 1 代条目数（旧节点留 v1）",
       lg.get("gen2_skipped") == row.get("items_v1"),
       (lg.get("gen2_skipped"), row.get("items_v1")))
    ck("3j[旧式位置化] 尾部新增槽 == max(0, n2-n1)",
       lg.get("tail_ok") is True, (lg.get("gen2_indexed"), lg.get("tail_expected")))
    ck("3k[新式认领自己] misplaced_rows 为空", not rec.get("misplaced_rows"),
       rec.get("misplaced_rows")[:1])


# ---------------- ③' 派生标识碰撞（N167 面）下的两代对账 ----------------

def guard_token_collision(tmp: str, sroot: str) -> None:
    """夹具里 ws-a/sess-1 与 ws-a/sess-2 的 createdAt 与首条 user 正文逐字相同 ⇒
    `derive_session_token` 派生同一 token（N167 的碰撞面）。此时旧式节点会整体切
    `ext_token` 兜底空间（dsh_log_index.py:596-607）——对账必须按**生效 token** 取旧节点。
    """
    lib, tr = paths(tmp, "g3c")
    rc, rows, total, _err = run_tool(base_argv(lib, sroot, tr, "full", "ws-a"))
    r1 = (rows or {}).get("ws-a/sess-1") or {}
    r2 = (rows or {}).get("ws-a/sess-2") or {}
    lv2 = r2.get("legacy_v1") or {}
    ck("3l[同 token] 两会话派生同一 token（夹具即碰撞面）",
       bool(r1.get("session_token")) and r1.get("session_token") == r2.get("session_token"),
       (r1.get("session_token"), r2.get("session_token")))
    ck("3m[同 token] 第二会话旧式写入切兜底空间（collision=True）",
       lv2.get("collision") is True, lv2)
    ck("3n[同 token] 对账按生效 token ⇒ 基线自洽 + 缺/错位全 0",
       rc == 0 and (r2.get("counts") or {}).get("legacy_claim") == 0
       and (r2.get("counts") or {}).get("missing") == 0
       and (r2.get("counts") or {}).get("misplaced") == 0,
       (rc, r2.get("counts")))


# ---------------- ④ 悬空（两层解耦 + regenerable 免清退） ----------------

def guard_dangling(tmp: str, sroot: str) -> None:
    lib, tr = paths(tmp, "g4")
    rc, _rows, _t, _e = run_tool(base_argv(lib, sroot, tr, "off", "ws-a", "sess-1"))
    ck("4a[前置] 落库 rc=0", rc == 0, rc)
    lp = log_path(sroot, "ws-a", "sess-1")
    tp = tr_path(tr, "ws-a", "sess-1")
    with open(lp, "rb") as f:
        log_bytes = f.read()
    cg = open_lib(lib)
    try:
        ns = nodes_of(cg)
        ck("4b[前置] 有 logsrc 节点", bool(ns), len(ns))
        nid, node = sorted(ns.items())[0]
        _k, ref = refindex.ref_of(node)
        with open(tp, "rb") as f:
            t_bytes = f.read()
        # fail-closed 三例（**必须在改动真源之前**：本守卫会删/恢复真源，mtime 一变
        # 「同 stat」就不成立，那时再测是测错东西）。src 用现采身份，避免 mtime 漂移。
        fresh = {"path": ref.get("path"), "root": ref.get("root"),
                 "lineno": ref.get("lineno"), "end": ref.get("end"),
                 "hash": ref.get("hash"),
                 "src": srcindex.session_src_id(lp, session_uuid="sess-1",
                                                workspace="ws-a")}
        p_stat = logref.probe_src(fresh, verify="stat")
        ck("4b'[stat 快路径 fail-closed] verify=stat 同 stat ⇒ unverified 且 ok=False",
           p_stat.get("status") == "unverified" and p_stat.get("ok") is False
           and p_stat.get("hash_verified") is False, p_stat)
        p_noh = dict(fresh)
        p_noh["src"] = {k: v for k, v in fresh["src"].items() if k != "file_hash"}
        ck("4b''[缺 file_hash] fail-closed ⇒ unverified（不假装核过）",
           logref.probe_src(p_noh).get("status") == "unverified",
           logref.probe_src(p_noh).get("status"))
        p_nos = {"path": ref.get("path"), "root": ref.get("root")}
        ck("4b'''[无 src 子键] ⇒ unresolved（不抛 KeyError）",
           logref.probe_src(p_nos).get("status") == "unresolved",
           logref.probe_src(p_nos).get("status"))
        try:
            os.remove(lp)                          # 删真源
            ck("4c[删真源] src 层 dangling",
               logref.probe_src(ref).get("status") == "dangling",
               logref.probe_src(ref))
        finally:
            with open(lp, "wb") as f:
                f.write(log_bytes)
        ck("4d[真源恢复] src 层 ok", logref.probe_src(ref).get("status") == "ok")
        try:
            with open(lp, "ab") as f:
                f.write(b"x")             # 追加一字节：内容变、大小变
            ck("4c'[改真源] src 层 stale（hash 已变）",
               logref.probe_src(ref).get("status") == "stale",
               logref.probe_src(ref).get("status"))
        finally:
            with open(lp, "wb") as f:
                f.write(log_bytes)
        ck("4d'''[真源再恢复] src 层回 ok", logref.probe_src(ref).get("status") == "ok")
        try:
            os.remove(tp)                          # 删转写
            rd = logref.read_index_node(node, with_src=True)
            ck("4e[删转写] 区间层 dangling 而 src 层仍 ok（两层解耦）",
               rd.get("span_status") == "dangling"
               and (rd.get("src") or {}).get("status") == "ok",
               (rd.get("span_status"), (rd.get("src") or {}).get("status")))
            ck("4f[删转写] 指路离线再生（服务态不写临时目录）",
               "repair" in (rd.get("rematerialize") or ""), rd.get("rematerialize"))
            # regenerable 免清退：dry_run 里不出现，且实做后节点仍在
            pl = refindex.prune_dangling(cg, dry_run=True, max_nodes=5000)
            ck("4g[regenerable 免清退] dry_run 候选为空且计数透出",
               pl.get("candidates") == 0 and pl.get("regenerable_skipped", 0) >= len(ns),
               (pl.get("candidates"), pl.get("regenerable_skipped"), len(ns)))
            refindex.prune_dangling(cg, max_nodes=5000)
            ck("4h[regenerable 免清退] 实做后节点仍在库",
               cg.get(nid) is not None and cg.get(nid) is not None)
            # 反向对照：非 regenerable 的悬空 doc 节点**必须**被列入
            fake = {"path": "nope/missing.md", "heading": "合成悬空章",
                    "heading_path": ["合成悬空章"], "level": 1, "lineno": 1,
                    "end": 3, "anchor": "synth", "hash": "deadbeef", "lang": "md",
                    "precise": True, "parent": "", "children": [], "summary_parts": "哑"}
            refindex.add_items(cg, [fake], kind="doc_ref",
                               root=os.path.join(tmp, "g4", "nope"))
            fid = docindex.node_id(fake)
            pl2 = refindex.prune_dangling(cg, dry_run=True, max_nodes=5000)
            ck("4i[反向对照] 非 regenerable 的悬空节点被列入（判据有判别力）",
               fid in (pl2.get("pruned") or []) or pl2.get("candidates", 0) >= 1,
               (pl2.get("candidates"), (pl2.get("pruned") or [])[:3]))
        finally:
            with open(tp, "wb") as f:
                f.write(t_bytes)
        ck("4j[转写恢复] 区间层回 ok",
           logref.read_index_node(cg.get(nid)).get("span_status") == "ok")
    finally:
        cg.close()


# ---------------- ④'' heal 重建后「可再生」仍生效（判据不依赖标签存活） ----------------

def guard_regenerable_after_rebuild(tmp: str, sroot: str) -> None:
    """`refindex.rebuild`（sustain.heal 的修复动作）只重放 layer 与 src，**不重放**
    extra 标签 ⇒ `regenerable` 会消失。此时「可再生免清退」必须仍成立——第二判据是
    `doc_ref.src.file_hash`（真源仍在）。只认标签 = 这条保护在重建后静默失效。
    """
    lib, tr = paths(tmp, "g4s")
    rc, _rows, _t, _e = run_tool(base_argv(lib, sroot, tr, "off", "ws-a", "sess-1"))
    ck("4o[前置] 落库 rc=0", rc == 0)
    cg = open_lib(lib)
    try:
        before = entries_of(cg)
        out = refindex.rebuild(cg, only_roots=[tr])
        after = entries_of(cg)
        ck("4p[heal] rebuild 重建完成且报告按序（indexed>0）",
           out.get("ok") is True and out.get("indexed", 0) > 0, out.get("errors")[:1])
        ck("4q[heal] rebuild 保留了 doc_ref.src（真源身份层不丢）",
           all((refindex.ref_of(cg.get(n))[1] or {}).get("src")
               for n in after), sorted(after)[:2])
        ck("4r[heal] 前提成立：附加标签确实被 rebuild 丢掉（logsrc 消失）",
           bool(before) and all("logsrc" not in (e.get("tags") or [])
                                for e in after.values()), sorted(after))
        # 删转写 → 全部 dangling：但「可再生」必须仍生效（第二判据靠 doc_ref.src）
        os.remove(tr_path(tr, "ws-a", "sess-1"))
        pl = refindex.prune_dangling(cg, dry_run=True, max_nodes=5000)
        ck("4s[heal 后] 无 regenerable 标签仍免清退（判据不依赖标签存活）",
           pl.get("candidates") == 0 and pl.get("regenerable_skipped", 0) >= len(after),
           (pl.get("candidates"), pl.get("regenerable_skipped"), len(after)))
    finally:
        cg.close()


# ---------------- ④' 再生（--repair 1 的离线再生面） ----------------

def guard_repair(tmp: str, sroot: str) -> None:
    """转写被清理（系统清 %TEMP%）后：服务态只报 dangling 指路，离线 `--repair 1` 再生。"""
    lib, tr = paths(tmp, "g4r")
    rc, _rows, _t, _e = run_tool(base_argv(lib, sroot, tr, "off", "ws-a", "sess-1"))
    tp = tr_path(tr, "ws-a", "sess-1")
    ck("4k[前置] 落库 rc=0 且转写在位", rc == 0 and os.path.isfile(tp))
    os.remove(tp)                                   # 模拟系统清理转写
    rc2, _r2, t2, _e2 = run_tool(base_argv(lib, sroot, tr, "off", "ws-a", "sess-1")
                                 + ["--repair", "1"])
    rep = (t2 or {}).get("repair") or {}
    ck("4l[--repair 1] 前置 dangling > 0 且再生后归零",
       rc2 == 0 and rep.get("pre_dangling", 0) > 0 and rep.get("post_dangling") == 0,
       (rc2, rep))
    ck("4m[--repair 1] 转写被重生成且层位一致",
       os.path.isfile(tp) and (t2 or {}).get("missing", 0) == 0)
    cg = open_lib(lib)
    try:
        ns = nodes_of(cg)
        nid = sorted(ns)[0]
        rd = logref.read_index_node(cg.get(nid), with_src=True)
        ck("4n[--repair 1] 区间层回读 ok 且哈希一致",
           rd.get("span_status") == "ok" and rd.get("hash_match") is True,
           (rd.get("span_status"), rd.get("hash_match")))
    finally:
        cg.close()


# ---------------- ⑤ 密级跟源 ----------------

def guard_sensitivity(tmp: str, sroot: str) -> None:
    lib, tr = paths(tmp, "g5a")
    rc, _rows, t, _e = run_tool(base_argv(lib, sroot, tr, "off", "ws-a", "sess-1"))
    cg = open_lib(lib)
    try:
        bad = []
        for nid, node in nodes_of(cg).items():
            _k, ref = refindex.ref_of(node)
            src = (ref or {}).get("src") or {}
            want = docindex.sensitivity_for(src.get("path") or "", None)[0]
            got = (node.get("frontmatter") or {}).get("sensitivity")
            if got != want:
                bad.append({"id": nid, "got": got, "want": want})
        ck("5a[密级跟源] 节点密级 == 真源路径判", not bad, bad[:2])
        _first = next(iter(nodes_of(cg).values()), None)
        _src_path = ((refindex.ref_of(_first)[1] or {}) if _first else {}).get(
            "src", {}).get("path") or ""
        ck("5a'[密级跟源] 真源路径判结果为内部档（夹具 ws-a 路径无私有提示）",
           docindex.sensitivity_for(_src_path, None)[0] == "internal", _src_path)
        ck("5b[不低于 internal] 无节点落 public 及更低档",
           all((n.get("frontmatter") or {}).get("sensitivity") in
               ("internal", "private", "secret") for n in nodes_of(cg).values()))
    finally:
        cg.close()
    ck("5c[internal 档] 无加密告警（加密计数 == 0）", (t or {}).get("encrypted_nodes") == 0,
       (t or {}).get("encrypted_nodes"))

    # 私有提示路径（private-ws）⇒ 真源路径判为 private ⇒ 加密档 + 告警计数必现
    lib2, tr2 = paths(tmp, "g5b")
    rc2, _r2, t2, err2 = run_tool(base_argv(lib2, sroot, tr2, "off", "private-ws", "sess-1"))
    cg2 = open_lib(lib2)
    try:
        ent = entries_of(cg2)
        sens = {(e.get("sensitivity")) for e in ent.values()}
        ck("5d[密级跟源] 私有提示路径 ⇒ 节点落 private", sens == {"private"}, sens)
        ck("5e[加密档] private ∈ crypto.ENCRYPTED_LEVELS",
           "private" in tuple(crypto.ENCRYPTED_LEVELS))
        ck("5f[加密告警计数必现] 报告 encrypted_nodes > 0",
           (t2 or {}).get("encrypted_nodes", 0) > 0, (t2 or {}).get("encrypted_nodes"))
        ck("5g[加密告警计数必现] stderr 有 WARNING（不静默）",
           "WARNING" in (err2 or "") and "加密" in (err2 or ""), (err2 or "")[:200])
    finally:
        cg2.close()
    # 读面复核：private 档按 frontmatter.session 绑定（mdcos.py:4048-4056），**can_admin
    # 豁免**（:4049-4050）——故此处必须用非 admin 身份，否则「绑定」这条看不出差别。
    tok = ((_r2 or {}).get("private-ws/sess-1") or {}).get("session_token")
    same = open_lib(lib2, can_write=False, can_admin=False, session=tok)
    try:
        n_same = nodes_of(same)
        ck("5h[会话绑定] 归属会话身份可回读且密级为 private",
           bool(n_same) and all((n.get("frontmatter") or {}).get("sensitivity")
                                == "private" for n in n_same.values()),
           len(n_same))
    finally:
        same.close()
    for label, sess in (("异会话身份", "sess_other"), ("无会话身份", None)):
        other = open_lib(lib2, can_write=False, can_admin=False, session=sess)
        try:
            ck("5i[会话绑定] %s读不回 private 档节点（可见性单点在 sensitivity）" % label,
               not nodes_of(other), len(nodes_of(other)))
        finally:
            other.close()


# ---------------- ⑥ path 口径 ----------------

def guard_path_convention(tmp: str, sroot: str) -> None:
    lib, tr = paths(tmp, "g6")
    rc, _rows, _t, _e = run_tool(base_argv(lib, sroot, tr, "off", "ws-a", "sess-1"))
    tp = tr_path(tr, "ws-a", "sess-1")
    cg = open_lib(lib)
    try:
        ns = nodes_of(cg)
        bad = []
        for nid, node in ns.items():
            _k, ref = refindex.ref_of(node)
            ref = ref or {}
            if os.path.normcase(os.path.realpath(ref.get("root") or "")) != \
                    os.path.normcase(os.path.realpath(tr)):
                bad.append({"id": nid, "root": ref.get("root")})
            elif os.path.isabs(ref.get("path") or "") or \
                    (ref.get("path") or "").startswith(("/", "\\")):
                bad.append({"id": nid, "path": ref.get("path")})
        ck("6a[口径] doc_ref.root == 转写根 且 path 为相对路径", not bad, bad[:2])
        ck("6b[口径] path 逐字为 <ws>/<sid>/<sid>.md",
           bool(ns) and all((refindex.ref_of(n)[1] or {}).get("path")
                            == "ws-a/sess-1/sess-1.md" for n in ns.values()))
        _k, ref0 = refindex.ref_of(next(iter(ns.values())))
        # 绝对 path 当 rel：既有 probe_ref 的 os.path.join 会丢前缀 ⇒ 仍 status=ok（不拦）
        abs_ref = dict(ref0 or {})
        abs_ref["path"] = tp
        ck("6c[陷阱存在] 绝对 path 当 rel 时 probe_ref 仍 status=ok（既有实现不拦）",
           refindex.probe_ref(abs_ref).get("status") == "ok",
           refindex.probe_ref(abs_ref).get("status"))
    finally:
        cg.close()

    # 撞 id 前提 = **同 sid 跨 ws**：裸文件名口径必撞，改写口径 0 撞
    text = open(tp, encoding="utf-8").read()
    def _ids(rel_of):
        out = []
        for ws, sid in (("ws-a", "sess-1"), ("private-ws", "sess-1")):
            out += [docindex.node_id(it) for it in
                    docindex.extract(text, path=rel_of(ws, sid))]
        return out
    bare = _ids(lambda ws, sid: "%s.md" % sid)                       # 裸文件名口径
    rel = _ids(lambda ws, sid: "%s/%s/%s.md" % (ws, sid, sid))       # 本工具的口径
    # 降级档：--src-path hash ⇒ path 置空 ⇒ probe_src 必须如实 unresolved（不猜、不假装能核）
    lib_h, tr_h = paths(tmp, "g6h")
    rc_h, _r_h, _t_h, _e_h = run_tool(base_argv(lib_h, sroot, tr_h, "off", "ws-a", "sess-1")
                                      + ["--src-path", "hash"])
    cg_h = open_lib(lib_h)
    try:
        n_h = nodes_of(cg_h)
        _k, ref_h = refindex.ref_of(next(iter(n_h.values())))
        pr = logref.probe_src(ref_h)
        ck("6f[降级档 hash] src.path 置空且 probe_src 如实 unresolved",
           rc_h == 0 and (ref_h or {}).get("src", {}).get("path") == ""
           and pr.get("status") == "unresolved" and pr.get("ok") is False,
           (rc_h, (ref_h or {}).get("src", {}).get("path"), pr.get("status")))
        ck("6g[降级档 hash] 候选路径仍带 file_hash（身份层不因降级而丢判据）",
           bool(((ref_h or {}).get("src") or {}).get("file_hash")))
    finally:
        cg_h.close()

    ck("6d[撞 id 前提] 裸文件名口径**同 sid 跨 ws** 撞 id",
       len(bare) - len(set(bare)) > 0, (len(bare), len(set(bare))))
    ck("6e[改写口径] <ws>/<sid>/<sid>.md 零撞 id",
       len(rel) - len(set(rel)) == 0, (len(rel), len(set(rel))))


# ---------------- ⑦ P2 端到端：检索命中 → 区间回读真源 ----------------

def _read_lines(p: str) -> list:
    with open(p, encoding="utf-8") as f:
        return f.read().split("\n")


def _write_text(p: str, text: str) -> None:
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def _roundtrip(cg, tp: str, query: str, k: int = 10) -> tuple:
    """检索命中 → `refindex.read_ref`（**唯一实现**）→ 逐字节比对源同区间切片。"""
    lines = _read_lines(tp)
    res, _meta = cg.search(query, k=k)
    detail, mism = [], []
    for n, _s, _q in res:
        _kd, ref = refindex.ref_of(n)
        if not isinstance(ref, dict) or not ref:
            mism.append({"id": n.get("id"), "why": "命中项无 doc_ref"})
            continue
        got = refindex.read_ref(ref)
        lo = max(0, int(ref.get("lineno") or 1) - 1)
        hi = max(lo, int(ref.get("end") or lo))
        want = "\n".join(lines[lo:hi])
        ok = (bool(got.get("ok")) and got.get("text") == want
              and got.get("hash_match") is True)
        detail.append((n.get("id"), ref.get("lineno"), ref.get("end"),
                       len(want), ok))
        if not ok:
            mism.append({"id": n.get("id"), "ok": got.get("ok"),
                         "hash_match": got.get("hash_match")})
    return res, detail, mism


def guard_p2_search_readback(tmp: str, sroot: str) -> None:
    """P2 三条证明（全部走真实检索入口与 read_ref 单点）：
    ①端到端：问句 → cg.search 命中索引节点 → 命中的 doc_ref → read_ref 取回区间；
    ②逐字节：read_ref 文本 == **源**（转写）同区间切片，且 hash_match=True；
    ③幂等：源不变重跑 ⇒ 新增条目数 0；
    ④无静默：源在靠前处插入一节 ⇒ 旧条目仍可读（text 取回）但按哈希判为 stale（计数
      非零）；重跑后新条目出现、报告计数非零、旧 id 仍可读。
    """
    lib, tr = paths(tmp, "g7")
    ws, sid = "ws-a", "sess-1"
    tp = tr_path(tr, ws, sid)
    lp = log_path(sroot, ws, sid)
    dlg = TOOL.load_dsh_log_index()
    a = base_argv(lib, sroot, tr, "off", ws, sid)
    rc, _rows, total, _e = run_tool(a)
    ck("7a[前置] 落库 rc=0 且新增条目数 > 0",
       rc == 0 and (total or {}).get("new_items", 0) > 0, (rc, total))

    cg = open_lib(lib, can_write=False)
    try:
        res, detail, mism = _roundtrip(cg, tp, "合成哑正文片段，仅用于夹具对齐")
        ck("7b[检索命中] 命中的日志索引节点全部带 doc_ref（命中即指得回）",
           bool(res) and all(refindex.ref_of(n)[1] for n, _s, _q in res),
           len(res))
        ck("7c[逐字节] read_ref 文本 == 源同区间切片（逐条）", not mism, mism[:1])
        print("      [P2① 检索命中 %d 条 → 区间回读] " % len(detail)
              + "；".join("%s L%s-%s %d 字符 逐字节相等=%s" % d for d in detail[:4]))
        old_ids = [n.get("id") for n, _s, _q in res]
    finally:
        cg.close()

    # ③ 幂等：源不变重跑
    rc2, _rows2, t2, _e2 = run_tool(a)
    cg = open_lib(lib, can_write=False)
    try:
        _res3, _d3, mism3 = _roundtrip(cg, tp, "合成哑正文片段，仅用于夹具对齐")
        ck("7d[幂等] 源不变重跑 ⇒ 新增条目数 == 0",
           rc2 == 0 and (t2 or {}).get("new_items") == 0,
           (rc2, (t2 or {}).get("new_items"), (t2 or {}).get("sessions_skipped")))
        ck("7e[幂等] 重跑后回读仍逐字节相等（区间未漂）", not mism3, mism3[:1])
    finally:
        cg.close()

    # ④ 无静默：源在靠前处插入一节（真源日志插入一条消息 + 真代码重渲染转写）
    parsed_before = dlg.parse_session_log(lp)
    tok_before = dlg.derive_session_token(parsed_before["meta"], parsed_before["msgs"])
    _write_log(lp, _log_lines(sid, splice=True))
    parsed2 = dlg.parse_session_log(lp)
    tok_after = dlg.derive_session_token(parsed2["meta"], parsed2["msgs"])
    _write_text(tp, dlg.render_transcript(ws, parsed2))     # 源已变、索引尚未重跑
    ck("7f[无静默/插入] 插入点在首条 user 之后 ⇒ 派生标识不变（同 id 空间）",
       bool(tok_before) and tok_before == tok_after, (tok_before, tok_after))
    cg = open_lib(lib, can_write=False)
    try:
        stale = readable = 0
        for nid in old_ids:
            node = cg.get(nid)
            _kd, ref = refindex.ref_of(node)
            got = refindex.read_ref(ref)
            if got.get("ok"):
                readable += 1
                if got.get("hash_match") is False:
                    stale += 1
        ck("7g[无静默/stale] 旧条目仍**可读**（text 取回）且按哈希判为 stale，计数非零",
           stale > 0 and readable > 0, (stale, readable, len(old_ids)))
        print("      [P2④ 插入后·重跑前] 旧节点 %d 条：可读 %d · 判 stale %d（计数非零=%s）"
              % (len(old_ids), readable, stale, stale > 0))
    finally:
        cg.close()
    rc3, rows3, t3, _e3 = run_tool(a)
    row3 = (rows3 or {}).get("%s/%s" % (ws, sid)) or {}
    ck("7h[无静默/新条目] 重跑后新条目出现（恰好插入的那一节 ⇒ 新增 == 1）",
       rc3 == 0 and (t3 or {}).get("new_items") == 1, (rc3, (t3 or {}).get("new_items")))
    ck("7i[无静默/计数非零] 报告同时透出覆写数（旧条目被计数，不静默）",
       (t3 or {}).get("updated", 0) > 0 and bool(row3.get("gen1")), row3.get("gen1"))
    cg = open_lib(lib, can_write=False)
    try:
        alive = 0
        for nid in old_ids:
            node = cg.get(nid)
            _kd, ref = refindex.ref_of(node)
            got = refindex.read_ref(ref)
            if got.get("ok") and got.get("hash_match") is True:
                alive += 1
        ck("7j[无静默/重跑后] 旧 id 全部仍可读且哈希一致", alive == len(old_ids),
           (alive, len(old_ids)))
        _res4, detail4, mism4 = _roundtrip(cg, tp, "合成哑正文片段，仅用于夹具对齐")
        ck("7k[重跑后] 命中项回读仍逐字节相等（含插入节的新条目）",
           not mism4 and len(detail4) > len(old_ids) - 1, (len(detail4), mism4[:1]))
        print("      [P2② 重跑后·检索命中 %d 条 → 逐字节回读] 全部相等=%s"
              % (len(detail4), not mism4))

        # ---- 生产读面（mcp_server op=ref action=read）：同一单点 read_ref + 两层状态 ----
        from md_cg.mcp_server import call_tool
        nid0 = (_res4[0][0].get("id") if _res4 else None)
        _kd, ref0 = refindex.ref_of(cg.get(nid0))
        lines4 = _read_lines(tp)
        want0 = "\n".join(lines4[max(0, int(ref0["lineno"]) - 1):max(0, int(ref0["end"]))])
        out = call_tool(cg, "cg", {"op": "ref", "action": "read", "node_id": nid0})
        ck("7l[生产读面] op=ref read 走同一 read_ref：文本逐字节 == 源切片",
           out.get("ok") is True and out.get("hash_match") is True
           and out.get("text") == want0, (out.get("ok"), out.get("hash_match")))
        out2 = call_tool(cg, "cg", {"op": "ref", "action": "read", "node_id": nid0,
                                    "with_src": True})
        ck("7m[生产读面] 日志节点带两层状态；with_src=True 才核真源（src.status=ok）",
           out2.get("span_status") == "ok" and out2.get("src_verified") is True
           and (out2.get("src") or {}).get("status") == "ok",
           (out2.get("span_status"), out2.get("src_verified")))
        out_default = call_tool(cg, "cg", {"op": "ref", "action": "read", "node_id": nid0})
        ck("7m'[生产读面] with_src 缺省不核真源且显式标注（src_verified=False）",
           out_default.get("src_verified") is False
           and "未看真源" in (out_default.get("src_note") or ""),
           (out_default.get("src_verified"), out_default.get("src_note")))
        os.remove(tp)
        out3 = call_tool(cg, "cg", {"op": "ref", "action": "read", "node_id": nid0,
                                    "with_src": True})
        ck("7n[生产读面] 转写被清理：区间层 dangling 而真源层仍 ok，且指路离线再生",
           out3.get("span_status") == "dangling"
           and (out3.get("src") or {}).get("status") == "ok"
           and "repair" in (out3.get("rematerialize") or ""),
           (out3.get("span_status"), (out3.get("src") or {}).get("status"),
            out3.get("rematerialize")))
        _write_text(tp, "\n".join(lines4))
    finally:
        cg.close()


# ---------------- 红基线：定点变异（锚点漂移 fail-closed） ----------------

#: 定点变异表：(标签, 现实现锚点, 改回后的旧行为)。
#: **源 = 工作区 md_cg/logref.py 的文本**（不取 git HEAD：HEAD 在改动提交那一刻就等于
#: 实现本身，判别力静默失效——同款教训见 md_cg/test_policy_required_ccg.py 头注）。
#: 锚点必须**恰好命中 1 次**：0 次＝漂移、≥2 次＝歧义，皆 ANCHOR-MISS → fail-closed。
_MUTATIONS = (
    ("落库判据：区间哈希 + 行位全等",
     '    same = (ref.get("hash") == it.get("hash")\n'
     '            and _int(ref.get("lineno")) == _int(it.get("lineno"))\n'
     '            and _int(ref.get("end")) == _int(it.get("end")))',
     "    same = True"),
)

#: 变异态下**必须**转红的项：**恰好**命中这个集合（多一项少一项都报红——多一项说明
#: 该断言另有依赖面、少一项说明该断言与「已索引」判据无关）。逐条＝该断言确实钉在
#: 「区间哈希 + 行位全等才算已索引」上，全部由**同一次**变异实跑得出：
#:  2a  同标题异内容（真源换同长度正文）⇒ updated > 0 —— 「id 撞即跳」下 updated == 0
#:  2b  updated == 前态快照判「需覆写」的条数（独立数据面交叉核验）—— 变异下 0 而期望 > 0
#:  3a  两代对账 rc == 0 —— 变异下 updated != updated_expected ⇒ ok=False ⇒ rc=1
#:  3d  两代错位数 == 0 —— 未覆写的节点仍记 v1 行位，locate 到插入后的别的章
#:  3h  两代 updated == updated_expected
#:  3k  新式节点「认领自己」：变异下旧节点认领到别人的 heading_path
#:  3n  同 token 会话下的 rc=0 与缺/错位全 0（同 3a+3d）
#:  7i  插入后重跑「覆写计数非零」（不静默）
#:  7j  插入后重跑「旧 id 全部仍可读且哈希一致」—— 变异下哈希仍指 v1 区间 ⇒ 不一致
#:  7k  重跑后检索命中 → 区间回读**逐字节 + hash_match**（变异下 hash_match=False）
#:  7l  生产读面 op=ref read 的 hash_match —— 同上（同一单点 read_ref）
#:  7m  生产读面 with_src=True 的区间状态与真源状态 —— 变异下节点带旧区间哈希**与旧
#:      真源身份**（doc_ref.src 一并冻结）⇒ span=stale 且 src=stale
#:  7n  转写被清理时应为「区间 dangling 而 **src 仍 ok**」—— 同一冻结使 src 报 stale
EXPECTED_RED = ("2a", "2b", "3a", "3d", "3h", "3k", "3n", "7i", "7j", "7k", "7l",
                "7m", "7n")


# 生效条件：锚点命中次数不是恰好 1 时由 _mutated_node_state 抛出（fail-closed）。
class AnchorMiss(RuntimeError):
    pass


#: 导入时的实现体字节码（红基线模式会把变异体挂回 logref.node_state，故不能与属性现值比）
_IMPL_CODEC = logref.node_state.__code__.co_code


# 生效条件：锚点仍在且 EXPECTED_RED 全部是本文件里真实存在的 check id 时静默返回；
# 否则抛 AnchorMiss（供缺依赖 zstandard 的 SKIP 出口复用，免得该环境里本守卫成纯空转）。
def _anchor_selfcheck() -> None:
    _mutated_node_state()                       # 锚点漂移/歧义 → AnchorMiss
    with open(os.path.abspath(__file__), encoding="utf-8") as f:
        src = f.read()
    gone = [i for i in EXPECTED_RED if ('ck("%s[' % i) not in src]
    if gone:
        raise AnchorMiss("EXPECTED_RED 含本文件里不存在的 check id（红项表已陈化）：%s"
                         % "、".join(gone))


# 生效条件：读工作区 md_cg/logref.py（**只读，不落盘**），按 _MUTATIONS 逐处文本替换，
# 把变异后的模块体 exec 进真模块 globals 的副本，返回变异后的 node_state 函数；
# 锚点漂移/歧义时抛 AnchorMiss。
def _mutated_node_state():
    p = os.path.join(REPO, "md_cg", "logref.py")
    with open(p, encoding="utf-8") as f:
        text = f.read()
    for label, anchor, repl in _MUTATIONS:
        n = text.count(anchor)
        if n != 1:
            raise AnchorMiss(
                "ANCHOR-MISS：定点变异锚点漂移/歧义 —— %s 命中 %d 次（应恰好 1 次）"
                "｜锚点首行：%s" % (label, n, anchor.splitlines()[0].strip()))
        text = text.replace(anchor, repl)
    g = dict(vars(logref))          # __name__/__package__ 保留 ⇒ 相对 import 照旧解析
    exec(compile(text, "<mutated md_cg/logref.py>", "exec"), g)
    fn = g["node_state"]
    # 与**导入时**的实现体比（不能比当前属性：红基线模式会把变异体挂回该属性，
    # 同进程二次调用就会「自己等于自己」而误报 ANCHOR-MISS——探针实测踩过）
    if fn.__code__.co_code == _IMPL_CODEC:
        raise AnchorMiss("ANCHOR-MISS：变异后字节码与实现相同（替换未生效）")
    return fn


# ---------------- 主流程 ----------------

#: 守卫段（顺序即执行顺序；label 用于打印与崩溃定位）
SECTIONS = (
    ("⓪ 写面边界（库根只许 tempfile；normcase 归一）",
     lambda tmp, sroot: guard_boundary(tmp)),
    ("① 幂等 ＋ ② 同标题异内容（含变异必红）", guard_idem_and_content),
    ("③ 插话两代对账", guard_two_generations),
    ("③' 派生标识碰撞（N167 面）下的两代对账", guard_token_collision),
    ("④ 悬空（两层解耦 + regenerable 免清退）", guard_dangling),
    ("④'' heal 重建后「可再生」仍生效", guard_regenerable_after_rebuild),
    ("④' 离线再生（--repair 1）", guard_repair),
    ("⑤ 密级跟源（含加密告警计数）", guard_sensitivity),
    ("⑥ path 口径（含同 sid 跨 ws 撞 id 前提）", guard_path_convention),
    ("⑦ P2 端到端：检索命中 → 区间回读真源", guard_p2_search_readback),
)


def main(argv=None) -> int:
    global TOOL, PASS, FAIL
    PASS = FAIL = 0                      # 同进程多次调用（探针/自证）不累积计数
    FAILS.clear()
    RED.clear()
    ap = argparse.ArgumentParser(
        description="N203 P1 守卫：日志真源 → ref 索引（临时库）")
    ap.add_argument("--head-baseline", action="store_true",
                    help="红基线：对工作区 md_cg/logref.py 做定点变异（落库判据改回"
                         "「id 撞即跳」），断言红项集合 == 预期红项")
    args = ap.parse_args(argv)
    try:
        import zstandard                                       # noqa: F401
    except ImportError:
        # 缺依赖时正文链路无法复核（SKIP，对齐 run_tests 裸 clone 不假红口径），但
        # **判别力自证仍跑**：锚点漂移 / 红项表陈化依旧 fail-closed——否则本守卫在没有
        # zstandard 的环境（CI 容器只装 pyyaml）里就是纯空转。
        try:
            _anchor_selfcheck()
        except AnchorMiss as exc:
            print("!! %s" % exc)
            print("结果：SKIP 态自证未过（fail-closed）")
            return 2
        print("SKIP  md_cg.test_logref：缺依赖 zstandard（日志转写链路无法复核）"
              "——对齐 run_tests 裸 clone 不假红口径；锚点/红项表自证已跑且通过")
        return 0
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    TOOL = load_tool()
    # 锚点自证：**两态都查**（绿态也查）——锚点漂移后若只查红基线，绿线会继续绿着而
    # 判别力已死（本守卫的判别力全靠这条表）。漂移即 fail-closed。
    try:
        mut_state = _mutated_node_state()
    except AnchorMiss as exc:
        print("!! %s" % exc)
        print("结果：锚点自证未过（fail-closed）——定点变异表须同步实现")
        return 2
    if args.head_baseline:
        logref.node_state = mut_state                 # 变异体注入（只在本进程内）
        print("!! 红基线模式：md_cg/logref.py 经定点变异 —— %s ⇒ 「id 撞即跳」"
              % "；".join(lbl for lbl, _a, _r in _MUTATIONS))
    tmp = tempfile.mkdtemp(prefix="n203_p1_guard_")
    try:
        sroot = make_fixture(tmp)
        for label, fn in SECTIONS:
            print("== %s ==" % label)
            try:
                fn(tmp, sroot)
            except Exception as exc:                  # 段内崩溃：计数为红项，不吞、不静默
                ck("EXC:%s" % label, False, "%s: %s\n%s"
                   % (type(exc).__name__, exc, traceback.format_exc()[-400:]))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("\n结果：PASS %d / FAIL %d" % (PASS, FAIL))
    if FAILS:
        print("失败项：" + "；".join(FAILS))
    if args.head_baseline:
        # 短码比对：ck 的 cid 带方括号内的说明（同一短码可多次出现，如 0a 六个拒绝面），
        # 取方括号前的前缀——段内崩溃记的 "EXC:<段名>" 无方括号 ⇒ 整串参与比对（必不等于
        # 任何预期红项 ⇒ 报「红基线与预期不符」，fail-closed，不静默放过）。
        got = sorted({(c or "").split("[")[0].strip() for c in RED})
        exp = sorted(EXPECTED_RED)
        if got == exp:
            print("红基线符合预期：变异后恰好命中 %d 项 —— %s"
                  % (len(exp), "、".join(exp)))
            return 0
        print("红基线与预期不符（fail-closed）——预期红项：%s；实得红项：%s"
              % ("、".join(exp) or "（无）", "、".join(got) or "（无）"))
        return 1
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
