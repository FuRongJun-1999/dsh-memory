# -*- coding: utf-8 -*-
"""J1 守卫：派生库不得把上游不变量当已知（密文当正文 / 缺失当损坏 / 结构当功能）。

背景（2026-10-21 病灶 J，审计稿 02 §33）：
  ① `_restore` 用 `cg.get()`（基类**不解密**）取正文 ⇒ `sealed` 节点的密文
     原样写进 `nodes.content`，实测 5 935/10 013 = 59.3%；全文检索会命中
     base64、`MdWhitebox` 会把密文当答案吐给用户。
  ② `default_db_path` 平铺系统临时目录、实测 0644 ⇒ 同机可读整库。
  ③ `_counts` 把「库不存在」与「库损坏」都压成 (0, 0) ⇒ 坏了被当不存在静默重建。
  ④ `edges=0` 时没有任何读数说明「是语料没有边」还是「提取失败」。

断言面：
  ① 含 sealed 节点的语料：`sealed_skipped >= 1`，`nodes` 计数不含它，
     且派生库 `nodes.content` **不含** `mdcg-enc`（核心反面）
  ② 全明文语料：`sealed_skipped == 0`、节点数全收
  ③ 边来源计数：语料无 `subgraph`/`edges` 字段 ⇒ `edge_fields` 全 0 且 `edges == 0`
     （读数能把「语料没有」与「提取失败」分开）
  ④ 损坏库（写入垃圾字节）⇒ `_db_status == "corrupt"`，重建成功且返回
     `db_status == "rebuilt"`；再次构建 ⇒ `reused` 且 `db_status == "ok"`
  ⑤ 默认库路径在私有子目录 `md_cg_native/` 下；POSIX 上目录 0700、库 0600
  ⑥ 明文节点内容原样在库（防止跳过逻辑误伤正常节点）

运行：python -m md_cg.test_j1_whitebox_sealed
"""
from __future__ import annotations

import os
import shutil
import sqlite3
import tempfile

from . import md_whitebox
from .mdcos import MdCGSecure
from .security import Principal

PASS = FAIL = 0
FAILS = []


def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        FAILS.append(label)
        print(f"  FAIL {label}")


def _contents(db):
    con = sqlite3.connect(db)
    try:
        return [r[0] for r in con.execute("SELECT content FROM nodes")]
    finally:
        con.close()


def _sealed_root(tmp, n_plain=1):
    """造一个含 sealed 节点的语料根（private 节点 + n_plain 个明文节点）。"""
    kek = os.urandom(32)
    owner = Principal(tenant="t1", actor="alice", clearance="private",
                      can_write=True, can_admin=True)
    cg = MdCGSecure(tmp, principal=owner, master_key=kek)
    for i in range(n_plain):
        cg.add(f"plain{i}", f"# 功能名：明文{i}\n\n这是可以公开的说明 {i}\n")
    cg.add("priv1", "# 功能名：隐私\n\n银行卡尾号 8888，仅本人可见\n",
           sensitivity="private")
    cg.close()
    return tmp


def main():
    base = tempfile.mkdtemp(prefix="mdcg_j1_")
    try:
        # ---------- ① 密文不得入库 ----------
        r1 = os.path.join(base, "root1")
        os.makedirs(r1)
        _sealed_root(r1)
        d1 = md_whitebox.build_db_from_md(r1, db_path=os.path.join(base, "a.db"),
                                          verbose=False)
        ok(d1["sealed_skipped"] == 1, f"① 跳过密文 1 个（实得 {d1['sealed_skipped']}）")
        ok(d1["nodes"] == 1, f"① 入库节点数 1（实得 {d1['nodes']}）")
        body = "\n".join(_contents(d1["db"]))
        ok("mdcg-enc" not in body, "① 派生库正文不含 mdcg-enc（核心反面）")
        ok("银行卡" not in body, "① 派生库正文不含隐私原文")
        ok("可以公开的说明 0" in body, "⑥ 明文节点内容原样在库")

        # ---------- ② 全明文语料不误伤 ----------
        r2 = os.path.join(base, "root2")
        os.makedirs(r2)
        _sealed_root(r2, n_plain=3)
        # 用一个全新的明文-only 根（sealed 节点仍造，但换根只放明文）
        r2b = os.path.join(base, "root2b")
        os.makedirs(r2b)
        kek = os.urandom(32)
        owner = Principal(tenant="t1", actor="alice", clearance="private",
                          can_write=True, can_admin=True)
        cg2 = MdCGSecure(r2b, principal=owner, master_key=kek)
        for i in range(3):
            cg2.add(f"p{i}", f"# 功能名：公开{i}\n\n公开正文 {i}\n")
        cg2.close()
        d2 = md_whitebox.build_db_from_md(r2b, db_path=os.path.join(base, "b.db"),
                                          verbose=False)
        ok(d2["sealed_skipped"] == 0, f"② 无密文时跳过 0（实得 {d2['sealed_skipped']}）")
        ok(d2["nodes"] == 3, f"② 三个明文节点全收（实得 {d2['nodes']}）")

        # ---------- ③ 边来源计数 ----------
        ok(d1["edge_fields"] == {"subgraph": 0, "edges": 0},
           f"③ 无边的语料 edge_fields 全 0（实得 {d1['edge_fields']}）")
        ok(d1["edges"] == 0, "③ 无边的语料 edges=0（读数可判是语料没有）")

        # ---------- ④ 损坏库必须能判出来并重建 ----------
        db4 = os.path.join(base, "c.db")
        with open(db4, "wb") as f:
            f.write(b"not a sqlite file at all")
        ok(md_whitebox._db_status(db4)[0] == "corrupt",
           f"④ 垃圾字节判 corrupt（实得 {md_whitebox._db_status(db4)}）")
        ok(md_whitebox._db_status(os.path.join(base, "nope.db"))[0] == "missing",
           "④ 不存在的库判 missing（与 corrupt 分开）")
        d4 = md_whitebox.build_db_from_md(r2b, db_path=db4, verbose=False)
        ok(d4["db_status"] == "rebuilt" and d4["nodes"] == 3,
           f"④ 损坏库被重建（实得 {d4['db_status']} nodes={d4['nodes']}）")
        d4b = md_whitebox.build_db_from_md(r2b, db_path=db4, verbose=False)
        ok(d4b["reused"] is True and d4b["db_status"] == "ok",
           f"④ 再次构建复用（实得 {d4b['db_status']} reused={d4b['reused']}）")

        # ---------- ⑤ 默认路径落在私有子目录 ----------
        p = md_whitebox.default_db_path(r2b)
        ok(os.path.basename(os.path.dirname(p)) == "md_cg_native",
           f"⑤ 默认库在 md_cg_native/ 子目录（实得 {p}）")
        if os.name == "posix":
            ok((os.stat(os.path.dirname(p)).st_mode & 0o777) == 0o700,
               "⑤ 目录权限 0700")
            ok((os.stat(d4b["db"]).st_mode & 0o777) == 0o600,
               "⑤ 库文件权限 0600")

        # ---------- ⑦ 调用方自有目录的权限不得被改动 ----------
        own = os.path.join(base, "own")
        os.makedirs(own, exist_ok=True)
        if os.name == "posix":
            os.chmod(own, 0o755)
            md_whitebox.build_db_from_md(r2b, db_path=os.path.join(own, "y.db"),
                                         verbose=False)
            ok((os.stat(own).st_mode & 0o777) == 0o755,
               f"⑦ 显式 db_path 的父目录权限不变（实得 {oct(os.stat(own).st_mode & 0o777)}）")
            ok((os.stat(os.path.join(own, "y.db")).st_mode & 0o777) == 0o600,
               "⑦ 库文件仍是 0600")
    finally:
        shutil.rmtree(base, ignore_errors=True)

    print(f"J1 守卫：{PASS} 通过 / {FAIL} 失败")
    if FAILS:
        print("失败项：" + "；".join(FAILS))
        raise SystemExit(1)


if __name__ == "__main__":
    main()
