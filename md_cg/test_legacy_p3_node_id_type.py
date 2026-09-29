# -*- coding: utf-8 -*-
"""md_cg · node_id 类型混淆（legacy P3）守卫：非字符串 id 混型索引键 → 整库重扫崩

沿革（legacy，不新占 N 号）：docs/eval/DSH端缺陷专项_v1.0.md:106/:204/:249 第 4 条
（§六-3「P3 相邻发现未修」）+ md_cg/test_none_id_write_guard.py:111-114 自注
「add(123) 属相邻缺陷（_scan_nodes/_load_index 混型键 sorted 崩），超出本守卫目标」。
本轮为首次第一手全链复现与修复。

缺陷（修复前）：md_cg/mcp_server.py:3090 `nid = a.get("node_id") or (...)` 不做类型
归一；md_cg/mdcg.py:1481 `nid_s = str(node_id or "")` **只**用于白名单校验与落盘
路径，而索引键（:1813 `_stage(node_id, …)`）、frontmatter `id`（:1590，落盘路径
:1571）、分片日志 `{"id": …}` 仍写**原对象**——行号按修复后记（修复前上述四行分别
为 1449/1781/1558/1526，即缺陷报告口径）。于是 `add(123)` 落
`knowledge/orphan/123.md`、盘面 frontmatter `id: 123`（YAML int）、索引键 int 123；
此后任何一次全量重扫（`_scan_nodes`，md_cg/mdcg.py:1338 `sorted(nodes)`）都会在
「int 键 vs 其它节点的 str 键」上抛 TypeError——崩点在 `MdCGSecure.__init__`
（mdcg.py:966→1004→1338），早于启动对账 reconcile_state，无自愈路径 ⇒ 整库永久
打不开。触发面：新建库首会话 + 任一字符串 id、既有快照库 + 一份外部 .md、
删/缺 `_index.json`（复制/还原/新机）。

修复（两层，各司其职）：
  · 写面 fail-closed（md_cg/mdcg.py:1461 区，`add` 的 node_id 校验前）：`node_id`
    非 str 一律 ValueError 拒绝——与既有 `add(None)`/`add("")`/`add(0)` 拒绝同族
    （那三个也是非字符串），毒不再落盘；`bool` 亦拒（True 是 int 子类，
    `str(True)="True"` 会匹配白名单）。引擎单点，全部写面（MCP cg/mdcg_*
    op=write、writepipe、review accept、restore、consolidate…）同源收口。
  · 派生面自愈（`_scan_nodes` :1325 + 两处分片日志重放 :1006/:1148）：索引是
    **派生物**（可重建），键一律归一到 str——存量毒文件（旧版本写出/外部编辑）
    与新机复制还原的库由此可自愈，不再「永久打不开」。

守卫（五组，全部临时库 + 哑主密钥/哑令牌，绝不触真实 ~/.mdcg）：
  [1] 写面契约：add(123)/add(True)/add(1.5) 被 ValueError 拒（修前放行=毒落盘）；
      add(None)/add("")/add(0) 仍拒、add("123") 正常（不误伤合法字符串 id）；
  [2] 存量毒文件（frontmatter `id: 123`）：删快照重开 / 保留快照+外部 .md 两种
      形态，修前 `sorted()` TypeError 整库打不开，修后正常且键归一为 "123"；
  [3] 分片日志 int 键：重开后索引键全为 str（潜伏毒不再进索引）；
  [4] MCP 端到端（真实 stdio 子进程）：mdcg_remember({node_id:123})，修前回执
      {"ok": true, "id": 123} 且落盘 `id: 123`；修后回结构化 error 且库仍可正常
      打开写读（服务不崩）；
  [5] 合法路径不回归：字符串 id 的 add/get/search/rebuild/close 全绿。

运行：python -m md_cg.test_legacy_p3_node_id_type
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile

from . import crypto, nodefile
from .mdcos import MdCGSecure
from .security import Principal

PASS = FAIL = 0
FAILS = []

DUMMY_KEK = bytes.fromhex("ab" * 32)     # 哑主密钥：本进程与子进程绝不触真实 ~/.mdcg
POISON_ID = 123
POISON_BODY = "# 正文：存量毒节点（旧版本写出 / 外部编辑形态）"


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}" + (f"  · {detail}" if detail else ""))
    else:
        FAIL += 1
        FAILS.append(name)
        print(f"  [FAIL] {name}  · {detail}")


def _principal(**kw):
    d = dict(actor="p3", clearance="secret", can_write=True, can_admin=True,
             role="designer", auth_mode="test")
    d.update(kw)
    return Principal(**d)


def _lib(root):
    return MdCGSecure(root, principal=_principal(), master_key=DUMMY_KEK)


def _poison_file(root, nid=POISON_ID, stem="123"):
    """在盘面直接落一个 frontmatter id 非字符串的节点文件（存量脏数据形态）。"""
    d = os.path.join(root, "knowledge", "orphan")
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, stem + ".md")
    with open(p, "w", encoding="utf-8") as f:
        f.write(nodefile.dumps({"id": nid, "layer": "knowledge",
                                "importance": 0.5, "tags": []}, POISON_BODY))
    return p


def _open_raises(root):
    """构造实例；返回 (异常实例 or None, 实例 or None)。"""
    try:
        return None, _lib(root)
    except Exception as e:                                    # noqa: BLE001
        return e, None


def _keys_all_str(cg):
    return all(isinstance(k, str) for k in (list(cg.index.get("nodes") or {})))


class _Mcp:
    """最小 MCP stdio 客户端（测试用；协议细节同 test_p21_tokens）。"""

    def __init__(self, env):
        self.p = subprocess.Popen(
            [sys.executable, "-m", "md_cg.mcp_server"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, encoding="utf-8", env=env,
            cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        self.i = 0
        self.send("initialize", {"protocolVersion": "2024-11-05",
                                 "capabilities": {},
                                 "clientInfo": {"name": "p3", "version": "1"}})
        self.send("notifications/initialized", {}, notify=True)

    def send(self, method, params=None, notify=False):
        msg = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            msg["params"] = params
        if not notify:
            self.i += 1
            msg["id"] = self.i
        self.p.stdin.write(json.dumps(msg, ensure_ascii=False) + "\n")
        self.p.stdin.flush()
        if notify:
            return None
        line = self.p.stdout.readline()
        if not line:
            raise RuntimeError("MCP 无响应："
                               + (self.p.stderr.read() or "")[:400])
        return json.loads(line)

    def call(self, name, args):
        r = self.send("tools/call", {"name": name, "arguments": args})
        if "error" in r:
            return {"error": str(r["error"])}
        return json.loads(r["result"]["content"][0]["text"])

    def __exit__(self, *a):
        try:
            self.send("shutdown")
            self.p.wait(timeout=10)
        except Exception:                                     # noqa: BLE001
            self.p.kill()


def main():
    roots = []
    try:
        tmp = tempfile.mkdtemp(prefix="p3_nodeid_")
        roots.append(tmp)

        # ---------- [1] 写面契约：非字符串 id 必须 fail-closed ----------
        print("\n[1] 写面契约（非 str node_id）")
        cg1 = _lib(os.path.join(tmp, "lib1"))
        bad = []
        for v in (123, True, 1.5):
            try:
                cg1.add(v, "# 正文：非字符串 id 写入")
                bad.append("%r 竟成功" % (v,))
            except ValueError:
                pass
            except Exception as e:                            # noqa: BLE001
                bad.append("%r 抛 %s（非 ValueError）" % (v, type(e).__name__))
        check("[1] 绿：add(123)/add(True)/add(1.5) 一律 ValueError 拒（修前放行=毒）",
              not bad, "；".join(bad))
        check("[1] 绿：索引键全为 str（毒未进内存索引）",
              _keys_all_str(cg1),
              str(sorted(map(repr, (cg1.index.get("nodes") or {}))))[:90])
        still = []
        for v in (None, "", 0):
            try:
                cg1.add(v, "# 正文：falsy 形态")
                still.append("%r 竟成功" % (v,))
            except ValueError:
                pass
        check("[1] 既有 falsy 契约不变（None/\"\"/0 仍拒）", not still,
              "；".join(still))
        ok_id = cg1.add("123", "# 功能名：字符串 id\n# 正文：合法形态")
        check("[1] 反向：add(\"123\") 字符串形态正常（不误伤）",
              ok_id == "123", repr(ok_id))
        # close → compact/rebuild → _scan_nodes → sorted(nodes)：修前既有毒键
        # 就在这一步炸（本会话第一手：TypeError: '<' not supported between
        # instances of 'str' and 'float'）
        close_err = None
        try:
            cg1.close()
        except Exception as e:                                # noqa: BLE001
            close_err = e
        check("[1] 绿：close()（内部 rebuild→_scan_nodes→sorted）不崩",
              close_err is None,
              "%s: %s" % (type(close_err).__name__, str(close_err)[:80])
              if close_err else "")

        # ---------- [2] 存量毒文件：重开/重扫不得整库打不开 ----------
        print("\n[2] 存量毒文件（frontmatter id: 123）")
        # 形态 A：删/缺 _index.json（复制、还原、新机）后重开
        lib_a = os.path.join(tmp, "lib_a")
        a = _lib(lib_a)
        a.add("ok_node", "# 功能名：字符串节点\n# 正文：与毒节点混型的另一半")
        a.close()                                    # 落快照
        _poison_file(lib_a)
        os.remove(os.path.join(lib_a, "_index.json"))
        ea, ca = _open_raises(lib_a)
        check("[2] 绿：毒文件 + 缺快照 → 库仍可打开（修前 sorted TypeError）",
              ea is None, "%s: %s" % (type(ea).__name__, str(ea)[:90]) if ea
              else "")
        check("[2] 绿：索引键全为 str（毒 id 归一为 \"123\"）",
              ca is not None and _keys_all_str(ca)
              and str(POISON_ID) in (ca.index.get("nodes") or {}),
              str(sorted((ca.index.get("nodes") or {}).keys()))[:80]
              if ca else "库打不开")
        if ca is not None:
            got = ca.get(str(POISON_ID))
            check("[2] 绿：毒节点经归一 id 可见（HTTP 语义未丢）",
                  got is not None and POISON_BODY in (got.get("content") or ""),
                  repr((got or {}).get("content"))[:60])
            # 重扫路径也不得崩（record 修复前：_scan_nodes 的 sorted）
            try:
                ca.rebuild_index()
                check("[2] 绿：rebuild_index（含 sorted）不崩", True)
            except Exception as e:                        # noqa: BLE001
                check("[2] 绿：rebuild_index（含 sorted）不崩", False,
                      "%s: %s" % (type(e).__name__, str(e)[:90]))
            ca.close()

        # 形态 B：保留快照 + 事后落一份外部 .md（指纹失配 → 全量重扫）
        lib_b = os.path.join(tmp, "lib_b")
        b = _lib(lib_b)
        b.add("ok_node", "# 功能名：字符串节点\n# 正文：`b` 库另一半")
        b.close()
        _poison_file(lib_b)                          # 快照已存，事后外部落毒
        eb, cb = _open_raises(lib_b)
        check("[2] 绿：快照在 + 外部毒 .md（指纹失配全扫）→ 库仍可打开",
              eb is None, "%s: %s" % (type(eb).__name__, str(eb)[:90]) if eb
              else "")
        if cb is not None:
            check("[2] 绿：形态 B 索引键亦全为 str", _keys_all_str(cb))
            cb.close()

        # ---------- [3] 分片日志 int 键：潜伏毒不进索引 ----------
        print("\n[3] 分片日志 `{\"id\": 123}` 形态")
        lib_c = os.path.join(tmp, "lib_c")
        c = _lib(lib_c)
        c._dirty[POISON_ID] = {"path": "knowledge/orphan/123.md",
                               "layer": "knowledge"}      # 复刻修前 _stage(123, …)
        c.flush()                                          # 落分片日志（不落快照）
        ec, cc = _open_raises(lib_c)
        check("[3] 绿：重开后索引键全为 str（修前残留 int 键）",
              ec is None and cc is not None and _keys_all_str(cc),
              ("%s" % (sorted(map(repr, (cc.index.get("nodes") or {})))
                       if cc else ec))[:80])
        if cc is not None:
            cc.close()

        # ---------- [4] MCP 端到端（真实 stdio 子进程） ----------
        print("\n[4] MCP 端到端 mdcg_remember({node_id: 123})")
        mcp_root = os.path.join(tmp, "mcp_cg")
        aux_root = os.path.join(tmp, "auxdir")   # 注意：不能叫 aux（Win32 保留设备名）
        os.makedirs(aux_root, exist_ok=True)
        from . import tokens as _tk
        tf = os.path.join(tmp, "_tokens.json")
        d = _tk.issue("designer", actor="p3-mcp", path=tf)
        env = dict(os.environ)
        env.update({
            "MDCG_ROOT": mcp_root, "MDCG_TOKEN_FILE": tf,
            "MDCG_TOKEN": d["token"],
            "MDCG_MASTER_KEY": DUMMY_KEK.hex(),     # 哑主密钥（子进程不读/不建真实密钥）
            "MDCG_AUX_ROOT": aux_root,              # 辅助根一并指向临时目录
            "MDCG_SUSTAIN": "0", "MDCG_SUSTAIN_ENABLED": "0",
            "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"})
        for k in ("MDCG_LEGACY_ENV_AUTH", "MDCG_CAN_ADMIN", "MDCG_CAN_WRITE",
                  "MDCG_CLEARANCE", "MDCG_ACTOR", "MDCG_LEGACY_ENV_ADMIN"):
            env.pop(k, None)
        check("[4] 隔离声明：子进程主密钥为哑值 + 辅助根指向临时目录",
              env.get("MDCG_MASTER_KEY") == DUMMY_KEK.hex()
              and env.get(crypto.MASTER_ENV) is not None
              and os.path.abspath(env["MDCG_AUX_ROOT"]).startswith(
                  os.path.abspath(tmp)))
        m = None
        try:
            m = _Mcp(env)
        except Exception as e:                                # noqa: BLE001
            check("[4] MCP 子进程可启动", False,
                  "%s: %s" % (type(e).__name__, str(e)[:200]))
        if m is not None:
            try:
                r = m.call("mdcg_remember",
                           {"node_id": POISON_ID,
                            "content": "# 功能名：数字 id 探针\n# 正文：毒"})
                check("[4] 绿：MCP 回结构化 error（修前回 {\"ok\": true, \"id\": 123}）",
                      isinstance(r, dict) and "error" in r
                      and "ValueError" in str(r.get("error")), str(r)[:140])
                poisoned = os.path.join(mcp_root, "knowledge", "orphan",
                                        "123.md")
                int_id = False
                if os.path.exists(poisoned):
                    with open(poisoned, encoding="utf-8") as f:
                        fm, _c = nodefile.loads(f.read())
                    int_id = not isinstance(fm.get("id"), str)
                check("[4] 绿：盘面未落 int id 毒文件", not int_id,
                      "poisoned=%s" % os.path.exists(poisoned))
                check("[4] 服务未崩（MCP 进程仍在）", m.p.poll() is None,
                      "poll=%s" % (m.p.poll(),))
            finally:
                m.__exit__()
        # 端到端后果：毒节点 + 任一字符串 id 节点共存，缺快照（复制/还原/新机
        # 形态）重开 → 全量重扫 sorted 混型崩 ⇒ 整库打不开（doc:106 定性）
        try:
            em, cm = _open_raises(mcp_root)
            check("[4] 绿：该库可打开（快照可用态）", em is None,
                  "%s: %s" % (type(em).__name__, str(em)[:90]) if em else "")
            if cm is not None:
                nid2 = cm.add("after_probe",
                              "# 功能名：正常写入探针\n# 正文：库可用")
                check("[4] 绿：正常字符串 id 写入可用", nid2 == "after_probe",
                      repr(nid2))
                try:
                    cm.close()
                except Exception:            # noqa: BLE001 —— 修前 close→compact→全扫混型崩
                    pass
            snap = os.path.join(mcp_root, "_index.json")
            if os.path.exists(snap):
                os.remove(snap)
            em2, cm2 = _open_raises(mcp_root)
            check("[4] 绿：毒+字符串共存库缺快照重开 → 不崩（修前 TypeError 整库打不开）",
                  em2 is None,
                  "%s: %s" % (type(em2).__name__, str(em2)[:90]) if em2 else "")
            if cm2 is not None:
                check("[4] 绿：重开后字符串节点在场",
                      cm2.get("after_probe") is not None)
                cm2.close()
        except Exception as e:                                # noqa: BLE001
            check("[4] 端到端后果腿自身未崩", False,
                  "%s: %s" % (type(e).__name__, str(e)[:120]))

        # ---------- [5] 合法路径不回归 ----------
        print("\n[5] 合法字符串 id 路径全绿")
        lib_d = os.path.join(tmp, "lib_d")
        e = _lib(lib_d)
        e.add("n_str_1", "# 功能名：字符串一\n# 正文：数字 ids 全程用字符串")
        e.add("task_123", "# 功能名：任务\n# 正文：task_123")
        e.flush()
        check("[5] get/search/rebuild 正常",
              e.get("n_str_1") is not None
              and any(n.get("id") == "task_123" for n, _s, _q in e.search("任务")[0]))
        e.rebuild_index()
        check("[5] rebuild 后键仍全为 str 且节点在场",
              _keys_all_str(e) and e.get("task_123") is not None)
        e.close()
        re_ = _lib(lib_d)
        check("[5] 重开正常（无混型崩）", re_.get("n_str_1") is not None)
        re_.close()
    finally:
        for r_ in roots:
            shutil.rmtree(r_, ignore_errors=True)

    print("\n" + "=" * 64)
    print(f"PASS={PASS}  FAIL={FAIL}")
    if FAILS:
        print("失败项：" + "；".join(FAILS))
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
