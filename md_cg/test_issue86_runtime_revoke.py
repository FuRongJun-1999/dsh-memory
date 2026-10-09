# -*- coding: utf-8 -*-
r"""守卫 · #86 令牌吊销须在运行期对常驻进程生效（2026-10-09 DSH 端实施）。

缺陷（GitHub #86）：令牌只在服务启动时 verify_token 一次，之后全程用缓存的
Principal；Principal.expired() 存在却无运行期调用点读 revoked_at/expires_at
⇒ 用户 revoke 之后，常驻宿主里的 MCP 进程一直有效到重启。

本笔处置：在 _dispatch 入口做**廉价**运行期复检——按 _tokens.json 的
(mtime_ns, size) 缓存解析结果；文件没变时开销=一次 stat，变了才重查该 token_id
是否已不存在或带 revoked_at。**fail-open**（表读不到即放行）。

判据：
  G1 复现+修复：签发令牌 → 用其身份 → **吊销** → 同进程再写 ⇒ **被拒**（修前仍成功）
  G2 不误伤：未吊销的令牌 ⇒ 仍可正常写
  G3 缓存生效：复检后缓存键与表 (mtime_ns,size) 一致（同一刻度内不重复解析）
  G4 fail-open：令牌表不可读（指向不存在路径）⇒ 放行，不阻塞服务
运行：python -X utf8 -m md_cg.test_issue86_runtime_revoke
退出码：0 全绿 ｜ 1 断言失败
"""
from __future__ import annotations

import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
if REPO not in sys.path:
    sys.path.insert(0, REPO)

PASS = 0
FAIL = 0
FAILS = []


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("[PASS] %s%s" % (name, ("  · " + detail) if detail else ""))
    else:
        FAIL += 1
        FAILS.append(name)
        print("[FAIL] %s  · %s" % (name, detail))


def main():
    from md_cg import mcp_server as M
    from md_cg.mdcos import MdCGSecure
    from md_cg import tokens as T

    d = tempfile.mkdtemp(prefix="p86_")
    root = os.path.join(d, "mem")
    os.makedirs(root, exist_ok=True)
    tf = os.path.join(d, "_tokens.json")
    os.environ["MDCG_TOKEN_FILE"] = tf          # 隔离到临时令牌表
    try:
        issued = T.issue(role="designer", label="guard86")
        tok = issued.get("token") if isinstance(issued, dict) else issued[0]
        tid = issued.get("token_id") if isinstance(issued, dict) else issued[1]
        p = T.verify_token(tok)
        cg = MdCGSecure(root, principal=p)
        SIX = ("# 功能名：t\n# 生效条件：t\n# 子功能：t\n# 执行：t\n"
               "# 验证方式：t\n# 不适用条件：t\n")

        def write_once(nid):
            try:
                r = M._dispatch(cg, "cg", {"op": "write", "node_id": nid,
                                           "content": SIX, "consistency": False})
                return bool(r and (r.get("ok") if isinstance(r, dict) else True))
            except Exception as exc:
                return "DENY:%s" % type(exc).__name__

        # G2 未吊销 ⇒ 正常
        ok_before = write_once("n_before")
        check("G2 未吊销的令牌 ⇒ 正常写入（不误伤）", ok_before is True, "ok=%r" % (ok_before,))

        # G1 吊销后同进程 ⇒ 必须被拒
        T.revoke(tid) if hasattr(T, "revoke") else None
        ok_after = write_once("n_after")
        check("G1 吊销后**同进程**再写 ⇒ 被拒（修前仍成功——#86 的核心）",
              ok_after is not True, "ok=%r" % (ok_after,))

        # G3 缓存键与表一致
        st = os.stat(tf)
        key = M._TOK_RECHECK_CACHE.get("key")
        check("G3 复检缓存键 == 令牌表 (path, mtime_ns, size)",
              bool(key) and key[1] == st.st_mtime_ns and key[2] == st.st_size,
              "key=%r" % (key,))

        # G4 fail-open：表指向不存在路径 ⇒ 放行
        os.environ["MDCG_TOKEN_FILE"] = os.path.join(d, "_nope.json")
        M._TOK_RECHECK_CACHE.clear()
        ok_fo = write_once("n_failopen")
        check("G4 令牌表不可读 ⇒ 放行（fail-open，不阻塞服务）",
              ok_fo is True, "ok=%r" % (ok_fo,))
    finally:
        os.environ.pop("MDCG_TOKEN_FILE", None)

    print("")
    print("=" * 64)
    print("通过 %d ／ 失败 %d" % (PASS, FAIL))
    if FAILS:
        print("失败项：" + "，".join(FAILS))
    print("=" * 64)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
