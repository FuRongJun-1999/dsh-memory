# -*- coding: utf-8 -*-
"""test_dsh_log_index_token —— dsh-log 派生标识跨会话碰撞守卫（N167）

背景（2026-09-27 缺陷 N167，severity=high）：derive_session_token 的
basis=sha256(f"{createdAt毫秒}|{首条 user 消息全文}")[:16] 不含日志文件
自身身份——「日志缺 type=session 首行（created_at_ms 取 None）」「同毫秒
+同首条 user」「同为无 user 退化」等场景下**不同会话**派生出同一 token。
ingest_transcript 对 dsh-log-<token>-* 的 skip-existing 不核验既有节点
归属，把第二会话全部章节静默跳过：独有正文零节点入库、rc=0、stderr 无
告警——静默数据丢失（归因混淆面：不同会话共享同一派生身份）。

守卫断言面（哑环境：系统临时目录 + 哑 zstd 日志 + MDCG_MASTER_KEY 哑密钥；
绝不触真实令牌库/真实 serve/在役数据目录，测毕清理）：
  红面（修前 FAIL / 修后须 PASS）：
    R1 主 token 跨会话唯一——同批 5 会话（覆盖四碰撞场景）token 互不相同
    R2 碰撞第二会话（sess-BBBB/sess-CCCC）独有正文入库且归属正确
    R3 退化组（缺 session 首行+无 user）两会话各自入库
    R4 碰撞时 stderr 有 WARNING（不再静默 rc=0）
    R5 跨批碰撞（sess-AAAA 先落库，sess-BBBB 后到）同样不丢
  绿面护栏（修前已绿 / 修复不得破坏）：
    G1 幂等——重跑全批库中 dsh-log 节点总数不变、无重复摄取
    G2 未碰撞会话（对照组 sess-FFFF）token 与众不同（主公式未破坏）
    G3 先占者（sess-AAAA）保持主 token 空间（节点 id 前缀不迁移）

运行：python -X utf8 scripts/test_dsh_log_index_token.py
依赖：zstandard（缺失 → SKIP 退出 0，对齐 run_tests 裸 clone 不假红口径）
"""
import contextlib
import io
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print("  [PASS] " + name)
    else:
        failed += 1
        print("  [FAIL] " + name + "  " + str(detail)[:300])


def _load_mod():
    import importlib.util
    p = os.path.join(HERE, "scripts", "dsh_log_index.py")
    spec = importlib.util.spec_from_file_location("dsh_log_index_guard", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------- 哑 zstd 日志构造（v4 形态，正文全哑数据） ----------------

def _lines(created, first_user, assistant, sid):
    """单会话日志行；created=None → 缺 type=session 首行；
    first_user=None → 无 user 消息（退化日志）。"""
    ls = []
    if created is not None:
        ls.append(json.dumps({"type": "session", "id": f"uuid-{sid}",
                              "createdAt": created, "cwd": "D:/gt-ws",
                              "agentPreset": "p"}, ensure_ascii=False))
    ls.append(json.dumps({"type": "turn/start", "data": {"turn": 1}}))
    if first_user is not None:
        ls.append(json.dumps(
            {"type": "user/message",
             "data": {"id": "u-1", "content": [
                 {"type": "text", "text": first_user}]}},
            ensure_ascii=False))
    ls.append(json.dumps(
        {"type": "assistant/message",
         "data": {"turn": 1, "message": {"id": "a-1", "content": [
             {"type": "text", "text": assistant}]}}},
        ensure_ascii=False))
    return ls


def _write_log(sroot, ws, sid, lines):
    import zstandard as zstd
    p = os.path.join(sroot, ws, sid, _MOD.LOG_NAME)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "wb") as f:
        f.write(zstd.ZstdCompressor().compress(
            ("\n".join(lines) + "\n").encode("utf-8")))


# ---------------- 摄取驱动（直调 main，收 stdout JSON 行 / stderr） ----------------

def _run_ingest(sroot, lib_root, extra=None):
    argv = ["--sessions-root", sroot, "--root", lib_root, "--allow-init",
            "--actor", "gt-guard", "--cleanup-transcripts"] + (extra or [])
    buf_out, buf_err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(buf_out), \
            contextlib.redirect_stderr(buf_err):
        rc = _MOD.main(argv)
    rows = {}
    total = None
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
            rows[o["session"]] = o
    return rc, rows, total, buf_err.getvalue()


def _dsh_log_nodes(lib_root):
    """库中 dsh-log- 节点清册：{nid: {session, workspace, content}}。"""
    from md_cg.mdcos import MdCGSecure
    from md_cg.security import Principal
    p = Principal(tenant="default", actor="gt-guard-reader",
                  clearance="internal", can_write=False, role="designer",
                  harness="dsh", unit="agent", auth_mode="local-cli")
    cg = MdCGSecure(lib_root, principal=p)
    try:
        out = {}
        for nid in sorted(cg.index.get("nodes") or {}):
            if not nid.startswith("dsh-log-"):
                continue
            g = cg.get(nid)
            fm = (g or {}).get("frontmatter") or {}
            dl = fm.get("dsh_log") or {}
            out[nid] = {"session": dl.get("session"),
                        "workspace": dl.get("workspace"),
                        "content": (g or {}).get("content") or ""}
        return out
    finally:
        cg.close()


# ---------------- 场景布置 ----------------

_MS = 1700000000000                    # 四会话同一 createdAt 毫秒（碰撞源）
_PROMPT = "批量任务首条 prompt（哑数据）"   # 同一首条 user 消息（碰撞源）

# (workspace, sid, created, first_user, assistant 独有正文标记)
SCEN = [
    # 四碰撞场景①②：同毫秒+同首条（AAAA 与 BBBB 同 ws 异 sid；CCCC 异 ws）
    ("gt-guard-ws-a", "sess-AAAA", _MS, _PROMPT, "ALPHA-UNIQUE-9f27"),
    ("gt-guard-ws-a", "sess-BBBB", _MS, _PROMPT, "BETA-UNIQUE-3c51"),
    ("gt-guard-ws-b", "sess-CCCC", _MS, _PROMPT, "GAMMA-UNIQUE-7b04"),
    # 碰撞场景③：缺 type=session 首行 + 无 user 消息（双双退化）
    ("gt-guard-ws-c", "sess-DDDD", None, None, "DELTA-UNIQUE-2e86"),
    ("gt-guard-ws-c", "sess-EEEE", None, None, "EPSI-UNIQUE-5a19"),
    # 对照组：createdAt 不同——主公式本就不碰撞（护栏 G2）
    ("gt-guard-ws-d", "sess-FFFF", _MS + 1, _PROMPT, "FFFF-UNIQUE-0d72"),
]

_WS_NAMES = sorted({s[0] for s in SCEN})


def _rmtree_retry(path):
    """rmtree 间歇失败（Windows：新落盘文件句柄关闭滞后）→ 退出前多次重试。

    实测形态：当场 rmtree 偶发 OSError、新进程立即可删——按「当场 1 次 +
    atexit 3 次×0.3s」重试兜底，哑库不在系统临时目录留残留。
    """
    import time
    try:
        shutil.rmtree(path)
        return
    except OSError:
        pass

    def _try(p):
        for _ in range(3):
            try:
                shutil.rmtree(p)
                return True
            except OSError:
                time.sleep(0.3)
        return False

    import atexit
    atexit.register(lambda p=path: _try(p))


def main():
    global passed, failed
    try:
        import zstandard                                   # noqa: F401
    except ImportError:
        print("SKIP: 缺 zstandard（pip install zstandard）——本守卫依赖哑"
              " zstd 日志构造")
        return 0
    _MOD = globals().get("_MOD")
    if _MOD is None:
        globals()["_MOD"] = _MOD = _load_mod()

    sroot = tempfile.mkdtemp(prefix="gt_guard_sessions_")
    lib_root = tempfile.mkdtemp(prefix="gt_guard_lib_")
    old_key = os.environ.get("MDCG_MASTER_KEY")
    os.environ["MDCG_MASTER_KEY"] = "ab" * 32      # 哑密钥（64 hex）
    # 读缓存 opt-out：哑环境显式关闭（缓存实例句柄常驻进程至退出，
    # 会锁住哑库 _index.json 使 rmtree 间歇失败留残留）
    old_cache = os.environ.get("MDCG_READ_CACHE")
    os.environ["MDCG_READ_CACHE"] = "0"
    try:
        for ws, sid, created, fu, body in SCEN:
            _write_log(sroot, ws, sid, _lines(created, fu, body, sid))

        # ---- R5 前置：sess-AAAA 先单独落库（占住碰撞 token），其余后到 ----
        rc0, rows0, _t0, err0 = _run_ingest(
            sroot, lib_root, ["--workspace", "gt-guard-ws-a",
                              "--session", "sess-AAAA"])
        check("R5pre AAAA 先行摄取 rc=0", rc0 == 0, (rc0, err0))
        n0 = _dsh_log_nodes(lib_root)
        aaaa0 = [n for n, v in n0.items()
                 if v["session"] == "sess-AAAA"]
        check("R5pre AAAA 先行入库有节点", len(aaaa0) >= 1, sorted(n0))

        # ---- 全批摄取（BBBB/CCCC/DDDD/EEEE 后到：批内+跨批碰撞全触发） ----
        rc, rows, total, err = _run_ingest(sroot, lib_root)
        check("rc=0", rc == 0, (rc, err))
        check("6 会话全部出报告", set(rows) ==
              {s[1] for s in SCEN}, sorted(rows))

        # R1 主 token 跨会话唯一（覆盖四碰撞场景）
        toks = {sid: r.get("session_token") for sid, r in rows.items()}
        check("R1 全部 6 会话 session_token 互不相同",
              len(set(toks.values())) == len(toks), toks)

        # R2 碰撞第二会话独有正文入库且归属正确
        nodes = _dsh_log_nodes(lib_root)
        for sid, marker, ws in (("sess-BBBB", "BETA-UNIQUE-3c51",
                                 "gt-guard-ws-a"),
                                ("sess-CCCC", "GAMMA-UNIQUE-7b04",
                                 "gt-guard-ws-b")):
            hit = [n for n, v in nodes.items() if v["session"] == sid]
            check(f"R2 {sid} 有入库节点", len(hit) >= 1,
                  f"库中归属: {sorted({v['session'] for v in nodes.values()})}")
            check(f"R2 {sid} 节点正文含独有标记", any(
                marker in v["content"] for n, v in nodes.items()
                if v["session"] == sid), hit)
            check(f"R2 {sid} 节点 workspace 锚正确", any(
                v["workspace"] == ws for v in nodes.values()
                if v["session"] == sid), hit)

        # R3 退化组（缺 session 首行+无 user）各自入库
        for sid, marker in (("sess-DDDD", "DELTA-UNIQUE-2e86"),
                            ("sess-EEEE", "EPSI-UNIQUE-5a19")):
            hit = [n for n, v in nodes.items() if v["session"] == sid]
            check(f"R3 {sid} 有入库节点", len(hit) >= 1,
                  sorted({v['session'] for v in nodes.values()}))
            check(f"R3 {sid} 正文含独有标记", any(
                marker in v["content"] for v in nodes.values()
                if v["session"] == sid), hit)

        # R4 碰撞告警不再静默（stderr 出 WARNING 且点名碰撞语义）
        check("R4 stderr 有派生标识碰撞 WARNING",
              "WARNING" in err and "碰撞" in err, err[:300])

        # R5 跨批：BBBB 后到仍入库（前置已保证 AAAA 先落库）
        check("R5 先占者 AAAA 与后到 BBBB 节点并存",
              any(v["session"] == "sess-AAAA" for v in nodes.values())
              and any(v["session"] == "sess-BBBB" for v in nodes.values()),
              sorted({v['session'] for v in nodes.values()}))

        # G2 对照组（不同 createdAt）token 与众不同
        check("G2 对照组 sess-FFFF token 与其余不同",
              rows.get("sess-FFFF", {}).get("session_token") not in
              {v for k, v in toks.items() if k != "sess-FFFF"},
              toks)

        # G3 先占者 AAAA 保持主 token 空间（节点 id 前缀=主公式派生值）
        main_tok_aaaa = rows0.get("sess-AAAA", {}).get("session_token")
        check("G3 AAAA 节点 id 前缀仍为主 token",
              any(n.startswith(f"dsh-log-{main_tok_aaaa}-") for n in nodes),
              (main_tok_aaaa, sorted(nodes)[:5]))

        # ---- G1 幂等：全批重跑，库中节点总数不变 ----
        before = len(nodes)
        rc2, rows2, _t2, err2 = _run_ingest(sroot, lib_root)
        nodes2 = _dsh_log_nodes(lib_root)
        check("G1 重跑 rc=0", rc2 == 0, (rc2, err2))
        check("G1 重跑库中 dsh-log 节点总数不变",
              len(nodes2) == before, (before, len(nodes2)))
        check("G1 重跑报告零新增节点（全 skip）",
              total is not None and
              all(r.get("nodes_indexed") == 0 for r in rows2.values()),
              {k: v.get("nodes_indexed") for k, v in rows2.items()})
        check("G1 重跑 token 与首轮一致（同文件派生稳定）",
              {k: v.get("session_token") for k, v in rows2.items()} == toks,
              (toks, {k: v.get("session_token")
                      for k, v in rows2.items()}))
    finally:
        if old_key is None:
            os.environ.pop("MDCG_MASTER_KEY", None)
        else:
            os.environ["MDCG_MASTER_KEY"] = old_key
        if old_cache is None:
            os.environ.pop("MDCG_READ_CACHE", None)
        else:
            os.environ["MDCG_READ_CACHE"] = old_cache
        _rmtree_retry(sroot)
        _rmtree_retry(lib_root)
        for ws in _WS_NAMES:                   # 只清守卫专属转写子目录
            shutil.rmtree(os.path.join(_MOD.TRANSCRIPT_ROOT, ws),
                          ignore_errors=True)

    print(f"\n{passed} passed, {failed} failed")
    return 1 if failed else 0


_MOD = None


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
