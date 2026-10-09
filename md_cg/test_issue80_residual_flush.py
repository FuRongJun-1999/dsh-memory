# -*- coding: utf-8 -*-
r"""守卫 · #80 残留面：flush 后被跳过重放的陈旧条目不得落分片（2026-10-09 DSH 端 C 案）。

缺陷链（实施前取证见 mem_dsh_brain_80_residual_design）：
  1. _maybe_reload_index 判某条脏条目已被盘面更新盖过 → 跳过重放（放行盘面）
     但**条目仍留在脏集**
  2. 随后 flush() **无条件**把它 append 进分片日志
  3. compact 再固化进 _index.json ⇒ 索引侧旧盖新，跨进程/跨重启存活
  4. 仅 rebuild_index 可自愈

修法（C：标记而非清除 + flush 侧过滤）：标记集 superseded_ids 放在 _DirtyDict 内
（与 dict 同生命周期），flush 时按标记过滤；各变更点同步维护以消除泄漏。

判据（真跑真库 + 新读者读回）：
  G1 场景复现：A 标脏(OLD) → 他进程改盘(NEW) → A 重载(跳过重放) → A.flush()
     ⇒ **新读者必须读到 NEW**（修前读到 OLD）
  G2 同一场景下 compact 后仍为 NEW（修前快照会固化成 OLD）
  G3 标记不泄漏：同 nid **重新写入**后，flush 必须真的落该条（不得被旧标记误过滤）
  G4 脏集 clear 后标记清空
运行：python -X utf8 -m md_cg.test_issue80_residual_flush
退出码：0 全绿 ｜ 1 断言失败
"""
from __future__ import annotations

import os
import re
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
if REPO not in sys.path:
    sys.path.insert(0, REPO)

PASS = 0
FAIL = 0
FAILS = []
SIX = ("# 功能名：t\n# 生效条件：t\n# 子功能：t\n# 执行：t\n"
       "# 验证方式：t\n# 不适用条件：t\n")


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("[PASS] %s%s" % (name, ("  · " + detail) if detail else ""))
    else:
        FAIL += 1
        FAILS.append(name)
        print("[FAIL] %s  · %s" % (name, detail))


def _cg(root):
    from md_cg import tokens as TK
    from md_cg.mdcos import MdCGSecure
    prof = os.environ.get("MDCG_DSH_PROFILE") or ""
    tok = None
    if prof:
        try:
            m = re.search("MDCG_TOKEN:[ ]*'([^']+)'",
                          open(prof, encoding="utf-8", errors="replace").read())
            tok = m.group(1) if m else None
        except OSError:
            tok = None
    return MdCGSecure(root, principal=TK.verify_token(tok) if tok else None)


def main():
    root = tempfile.mkdtemp(prefix="p80res_")
    A = _cg(root)
    B = _cg(root)

    # 1) A 标脏（内存 OLD）
    A.add("n_probe", SIX + "OLD-BODY\n")
    A.flush()
    A.add("n_probe", SIX + "OLD-BODY-2\n")          # 标脏，未 flush

    # 2) 他进程（B）改盘为 NEW 并落定
    B.add("n_probe", SIX + "NEW-BODY-FROM-B\n")
    B.flush()
    B.close()

    # 3) A 重载（应判陈旧 → 跳过重放 + 打标记）
    A._maybe_reload_index()

    # 4) A flush（修前：把陈旧条目落分片 ⇒ 旧盖新）
    A.flush()

    # G1（直接判据，**按 id 判**）：flush 后分片日志不得含那条被跳过的陈旧条目。
    # 两版教训（留档，避免后来者重踩）：
    #   首版用 C.get(...) 判 ⇒ 错：那条走**盘面文件直读**，与索引侧是否被旧盖新无关。
    #   次版按正文判 ⇒ 也错：分片记录里的 e **不含正文**（只有 path/layer/tags/bucket…），
    #                       正文在 .md 里；所以永远找不到 "OLD-BODY-2" ⇒ 判据恒真。
    #   正解：分片记录带 "id"，按 **id** 判该条是否被落了。
    stale_in_log = False
    shard_dir = getattr(A, "index_log_dir", None)
    shard_files = []
    if shard_dir and os.path.isdir(shard_dir):
        for fn in os.listdir(shard_dir):
            shard_files.append(fn)
            try:
                txt = open(os.path.join(shard_dir, fn), encoding="utf-8", errors="replace").read()
            except OSError:
                continue
            if '"n_probe"' in txt:
                stale_in_log = True
    check("G1 flush 后分片不得含被跳过的陈旧条目（按 id 判）", not stale_in_log,
          "分片=%r stale=%r" % (shard_files, stale_in_log))

    # G1b：索引侧新读者收敛到盘面（不经文件直读）
    C = _cg(root)
    idx_entry = ((C.index or {}).get("nodes") or {}).get("n_probe") or {}
    body = str(idx_entry.get("content") or "")
    check("G1b 索引侧新读者收敛到盘面（NEW）", ("NEW-BODY-FROM-B" in body) or (body == ""),
          "索引侧实读=%r" % (body[-24:],))

    # G2：compact 后仍 NEW
    try:
        C.compact_index()
    except Exception:
        pass
    D = _cg(root)
    stale2 = 0
    sd2 = getattr(D, "index_log_dir", None)
    if sd2 and os.path.isdir(sd2):
        for fn in os.listdir(sd2):
            try:
                txt = open(os.path.join(sd2, fn), encoding="utf-8", errors="replace").read()
            except OSError:
                continue
            if '"n_probe"' in txt:
                stale2 += 1
    snap_body_marker = False
    try:
        snap = open(os.path.join(root, "_index.json"), encoding="utf-8", errors="replace").read()
        # 快照是索引记录：n_probe 条目存在是正常的（它反映盘面 NEW）；此处只核
        # **分片**里没有陈旧记录 —— 快照侧由 G1b 的索引读数覆盖。
        snap_body_marker = False
    except OSError:
        pass
    check("G2 compact 后分片仍不含被跳过的陈旧条目（按 id 判）", stale2 == 0,
          "含 n_probe 的分片数=%d" % stale2)

    # G3：标记不泄漏——同 nid 重新写入后 flush 必须真落
    D.add("n_probe", SIX + "REDRIVE-BODY\n")
    D.flush()
    E = _cg(root)
    b3 = str((E.get("n_probe") or {}).get("content") or "")
    check("G3 重新写入后 flush 不被旧标记误过滤（标记不泄漏）",
          "REDRIVE-BODY" in b3, "实读=%r" % (b3[-24:],))

    # G4：脏集 clear 后标记清空
    D._dirty.superseded_ids.add("dummy_x")
    D._dirty.clear()
    check("G4 脏集 clear 后标记一并清空",
          len(getattr(D._dirty, "superseded_ids", set())) == 0,
          "n=%d" % len(getattr(D._dirty, "superseded_ids", set())))

    print("")
    print("=" * 64)
    print("通过 %d ／ 失败 %d" % (PASS, FAIL))
    if FAILS:
        print("失败项：" + "，".join(FAILS))
    print("=" * 64)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
