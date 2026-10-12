# -*- coding: utf-8 -*-
r"""#146 守卫：坏 frontmatter 节点**隔离**而非炸库（+ 非法密级不炸全员检索）。

缺陷形态（复现于 HEAD d29a8436，本守卫 A 组在 HEAD 上应红）：
  ① `nodefile.loads` 对解析失败的取值行保留原字符串（`except ValueError: fm[k]=v`）
     ⇒ 手改漏一个 `}` 的 `condition_space` 变成 `str`；`MdCG._node_entry` 的
     `(fm.get("condition_space") or {}).get(...)` 对 str 抛 AttributeError，且该
     调用在 `_scan_nodes` 的 try **之外** ⇒ 异常逃出 `MdCG.__init__`：
     **整库打不开、MCP 服务起不来**（一个坏文件炸全库）。
  ② 非法 `sensitivity`（手改坏）让 `_readable` 里的 `_rank` 抛 `AccessDenied`
     逃出检索入口 ⇒ **炸全员检索**。
  ③ 密文配非加密档密级（手改 `sensitivity: private` → `internal`）时，读方
     身份/会话校验被绕过 ⇒ 他会话读到**密文正文的明文**。

修法（本件）：
  · `nodefile.frontmatter_problem` —— 类型可用性判据**单点**；
  · `MdCG._scan_nodes` —— 坏文件**隔离**（不进索引、不改盘、continue），
    清单经 `self._quarantined` 透出到 `health()`（**仅确有隔离时出键**）；
  · `MdCOS._readable` —— 非法密级按不可见（fail-closed，不抛）；
  · `MdCOS._open_content` —— 密文配非加密档 ⇒ 不可读（fail-closed）；
  · `MdCG.get` / `MdCG._read_status` —— 损坏按不可读（None），挡住
    `protect.mark` 等「读→改→回写」把坏文件写回。

判据组：
  A 坏库不炸（A 组在 HEAD 上应红）：
      A1 坏 frontmatter 节点存在时 `MdCGSecure` 构造**不抛**（MCP 能起来）
      A2 坏节点被隔离：`_quarantined` 含该 id 且 `index["nodes"]` 不含它
      A3 隔离项带 path 与原因（可定位，不是静默消失）
      A4 隔离**不改盘**：坏文件字节与隔离前逐位相同
      A5 健康节点照常可检索（坏文件不拖累其余节点）
  B 健康库键集不变：
      B1 无隔离文件时 `health()` **不含** `quarantined` 键
      B2 健康库 health 键集与 HEAD 基线逐位一致（对照硬编码键集）
      B3 有隔离文件时才出该键，且是 dict
  C 非法密级不炸全员检索：
      C1 非法 sensitivity 节点存在时 `search` 不抛异常
      C2 `search_rrf` 不抛异常
      C3 该节点判不可见（fail-closed），其余节点照常可见
  D 密文配非加密档 ⇒ 不可读：
      D1 同身份**异会话**读不到明文（HEAD 上读到明文 ⇒ 红）
      D2 解密结果恒 None（不是「读到空串」）
  E 损坏按不可读（挡写回）：
      E1 索引内节点盘上被改坏后 `get()` 返回 None
      E2 `_read_status` 返回 (None, None, None)（三态里的终态缺失）
      E3 `protect.mark` 返回 node_not_found 且**盘上字节不变**（未写回）
  F 判据单点：
      F1 `nodefile.frontmatter_problem` 对合法 fm 返回 []
      F2 对 str 型 condition_space / list 型 tags 反向 / number 型 importance
         成 str 各返回非空，且 bool 不算 number

定点变异（`--mutate=…`，抽掉修复 ⇒ 对应断言必红）：
  nofix   ：`_scan_nodes` 换回 HEAD 版（`_node_entry` 在 try 之外）+ 类型判据
            恒返回空 ⇒ A 组必红（构造抛 AttributeError）
  nomut   ：`_readable` 换回无非法密级守卫版 ⇒ C 组必红（AccessDenied 逃逸）
  nocipher：`_open_content` 抽掉「密文配非加密档」闸 ⇒ D 组必红（读到明文）

用法：
  python -X utf8 -m md_cg.test_issue146_frontmatter_quarantine
  python -X utf8 -m md_cg.test_issue146_frontmatter_quarantine --mutate=nofix
  python -X utf8 -m md_cg.test_issue146_frontmatter_quarantine --mutate=nomut
  python -X utf8 -m md_cg.test_issue146_frontmatter_quarantine --mutate=nocipher
退出码：0 = 全绿；1 = 有失败。
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile

PASS = 0
FAIL = 0
FAILS = []

BODY = ("# 功能名：坏件对照\n# 生效条件：沙箱\n# 子功能：对照\n"
        "# 执行：读\n# 验证方式：守卫\n# 不适用条件：无\n正文\n")
BAD_FM_FILE = ('---\n'
               'id: "badnode"\n'
               'layer: "knowledge"\n'
               'condition_space: {"observation_position": "沙箱"\n'
               'tags: ["x"]\n'
               'importance: 0.5\n'
               '---\n'
               '正文\n')

#: HEAD 基线（d29a8436）健康库 health() 的键集——B2 的对照面。
#: 与「无隔离文件时键集逐位不变」同义（quarantined 只在确有隔离时出现）。
HEALTH_KEYS_BASELINE = {
    "buckets", "ok", "problems", "total_nodes", "expected_scan",
    "max_bucket_share", "singleton_ratio", "bucket_scope", "ccg_by_layer",
    "neg_memory_counts", "skipped_unreadable", "nodes",
}


def ok(cond, label, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        FAILS.append(label)
    print("  [%s] %s%s" % ("PASS" if cond else "FAIL", label,
                           ("  · " + str(detail)) if detail else ""))
    return bool(cond)


def _head_scan_nodes(self):
    """HEAD 版 `MdCG._scan_nodes`（`_node_entry` 在 try **之外**）——变异用。"""
    from md_cg import nodefile
    from md_cg.mdcg import LAYERS
    nodes = {}
    for layer in LAYERS:
        base = os.path.join(self.root, layer)
        for dirpath, _dirs, files in os.walk(base):
            for fn in files:
                if not fn.endswith(".md"):
                    continue
                p = os.path.join(dirpath, fn)
                try:
                    with open(p, encoding="utf-8") as f:
                        fm, content = nodefile.loads(f.read())
                except (OSError, UnicodeDecodeError):
                    continue
                nid = str(fm.get("id") or fn[:-3])
                nodes[nid] = self._node_entry(p, layer, fm, content)
    return {k: nodes[k] for k in sorted(nodes)}


def _head_readable(self, e, session=None):
    """HEAD 版 `MdCGSecure._readable`（无非法密级守卫）——变异用。"""
    from md_cg.security import DEFAULT_SENSITIVITY, _rank
    sens = e.get("sensitivity")
    if not sens:
        fm, _c = self._read(e)
        sens = "secret" if fm is None else (fm.get("sensitivity")
                                            or DEFAULT_SENSITIVITY)
        e["sensitivity"] = sens
    if sens == "restricted":
        from md_cg.security import can_read_restricted
        return (self.principal.allows("internal")
                and can_read_restricted(self.principal))
    if not self.principal.allows(sens):
        return False
    if _rank(sens) >= _rank("private"):
        if self.principal.can_admin:
            return True
        nsess = e.get("session")
        return bool(nsess) and nsess == self.principal.session
    return True


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    mut = ""
    for a in argv:
        if a.startswith("--mutate="):
            mut = a.split("=", 1)[1]

    from md_cg import crypto
    from md_cg import nodefile
    from md_cg.mdcg import MdCG
    from md_cg.mdcos import MdCGSecure
    from md_cg.security import Principal

    _orig_problem = nodefile.frontmatter_problem
    _orig_scan = MdCG._scan_nodes
    _orig_readable = MdCGSecure._readable
    _orig_levels = crypto.ENCRYPTED_LEVELS

    if mut == "nofix":
        # 抽掉类型判据 + 换回 HEAD 版 _scan_nodes（修复整体被摘掉）
        nodefile.frontmatter_problem = lambda fm, content=None: []
        MdCG._scan_nodes = _head_scan_nodes
    elif mut == "nomut":
        MdCGSecure._readable = _head_readable
    elif mut == "nocipher":
        # 等价注入：把「加密档」集合放宽到含 internal ⇒ `_open_content` 的
        # 「密文配非加密档 ⇒ 不可读」闸对 internal 失效（等价于抽掉该闸）。
        crypto.ENCRYPTED_LEVELS = tuple(_orig_levels) + ("internal",)

    sb = tempfile.mkdtemp(prefix="iss146_")
    sb2 = tempfile.mkdtemp(prefix="iss146c_")
    sb3 = tempfile.mkdtemp(prefix="iss146d_")
    sb4 = tempfile.mkdtemp(prefix="iss146e_")
    try:
        # ---------- A 组：坏库不炸 ----------
        print("\n[A] 坏 frontmatter 节点 ⇒ 隔离而非炸库")
        root = os.path.join(sb, "lib")
        os.makedirs(os.path.join(root, "knowledge"), exist_ok=True)
        cg = MdCG(root, autoflush=1)
        cg.add("healthy", BODY, layer="knowledge", importance=0.5)
        cg.close() if hasattr(cg, "close") else None
        bad_path = os.path.join(root, "knowledge", "bad.md")
        with open(bad_path, "w", encoding="utf-8") as f:
            f.write(BAD_FM_FILE)
        before = open(bad_path, "rb").read()

        raised = None
        cg2 = None
        try:
            cg2 = MdCG(root, autoflush=1)
        except Exception as exc:                     # noqa: BLE001
            raised = "%s: %s" % (type(exc).__name__, exc)
        ok(raised is None, "A1 坏件在场时 MdCG 构造不抛（整库可开）", raised)
        if cg2 is None:
            print("  （构造失败，A2-A5 记红）")
            for _lbl in ("A2 坏节点被隔离且不进索引", "A3 隔离项带 path 与原因",
                         "A4 隔离不改盘（字节逐位相同）",
                         "A5 健康节点照常可检索"):
                ok(False, _lbl, "前置构造失败")
        else:
            q = getattr(cg2, "_quarantined", {}) or {}
            ok("badnode" in q and "badnode" not in cg2.index["nodes"],
               "A2 坏节点被隔离且不进索引",
               (sorted(q), sorted(cg2.index["nodes"])))
            _item = q.get("badnode") or {}
            ok(bool(_item.get("path")) and bool(_item.get("reason")),
               "A3 隔离项带 path 与原因", _item)
            ok(open(bad_path, "rb").read() == before,
               "A4 隔离不改盘（字节逐位相同）")
            hit = cg2.search("正文", k=5)
            ok(any("healthy" in str(r) for r in hit),
               "A5 健康节点照常可检索", len(hit))

        # ---------- B 组：健康库键集不变 ----------
        print("\n[B] 健康库 health 键集不变")
        clean = os.path.join(sb2, "lib")
        cgc = MdCG(clean, autoflush=1)
        cgc.add("n1", BODY, layer="knowledge", importance=0.5)
        h = cgc.health()
        ok("quarantined" not in h, "B1 无隔离文件 ⇒ 不含 quarantined 键",
           sorted(h.keys()))
        ok(set(h.keys()) == HEALTH_KEYS_BASELINE,
           "B2 健康库键集与基线逐位一致",
           sorted(set(h.keys()) ^ HEALTH_KEYS_BASELINE))
        cgc.close() if hasattr(cgc, "close") else None
        # 加一个坏件后必须出键
        with open(os.path.join(clean, "knowledge", "bad2.md"), "w",
                  encoding="utf-8") as f:
            f.write(BAD_FM_FILE.replace('"badnode"', '"badnode2"'))
        _h2 = None
        try:
            cgc2 = MdCG(clean, autoflush=1)
            _h2 = cgc2.health().get("quarantined")
        except Exception:                            # noqa: BLE001
            _h2 = None
        ok(isinstance(_h2, dict),
           "B3 有隔离文件 ⇒ 出 quarantined 键（dict）",
           type(_h2).__name__)

        # ---------- C 组：非法密级不炸全员检索 ----------
        print("\n[C] 非法 sensitivity 不炸全员检索")
        try:
            key = os.urandom(32)
            sec = MdCGSecure(os.path.join(sb3, "lib"),
                             principal=Principal(tenant="t", actor="a",
                                                 clearance="secret",
                                                 can_write=True,
                                                 can_admin=True),
                             master_key=key)
            sec.add("good", BODY, layer="knowledge")
            sec.add("priv", BODY, layer="knowledge", sensitivity="private")
            p_priv = None
            for dp, _dn, fn in os.walk(sec.root):
                for f in fn:
                    if f == "priv.md":
                        p_priv = os.path.join(dp, f)
            t = open(p_priv, encoding="utf-8").read().replace(
                'sensitivity: "private"', 'sensitivity: "internl"')
            with open(p_priv, "w", encoding="utf-8") as f:
                f.write(t)
            sec2 = MdCGSecure(os.path.join(sb3, "lib"),
                              principal=Principal(tenant="t", actor="a",
                                                  clearance="secret",
                                                  can_write=True,
                                                  can_admin=True),
                              master_key=key)
            sec2.rebuild_index()
            err = None
            try:
                r1 = sec2.search("正文", k=5)
            except Exception as exc:                 # noqa: BLE001
                err = "%s: %s" % (type(exc).__name__, exc)
                r1 = []
            ok(err is None, "C1 非法密级在场时 search 不抛异常", err)
            err2 = None
            try:
                sec2.search_rrf("正文", k=5)
            except Exception as exc:                 # noqa: BLE001
                err2 = "%s: %s" % (type(exc).__name__, exc)
            ok(err2 is None, "C2 search_rrf 不抛异常", err2)
            e_bad = sec2.index["nodes"].get("priv")
            ok(e_bad is not None and sec2._readable(e_bad) is False,
               "C3 非法密级节点判不可见（fail-closed）",
               (sec2.index["nodes"].get("priv") or {}).get("sensitivity"))
            ok(any("good" in str(x) for x in r1),
               "C3b 其余节点照常可见（未殃及全员）", len(r1))
        except Exception as exc:                     # noqa: BLE001
            for _l in ("C1 非法密级在场时 search 不抛异常",
                       "C2 search_rrf 不抛异常",
                       "C3 非法密级节点判不可见（fail-closed）",
                       "C3b 其余节点照常可见（未殃及全员）"):
                ok(False, _l, "C 段异常：%s: %s" % (type(exc).__name__, exc))

        # ---------- D 组：密文配非加密档 ⇒ 不可读 ----------
        print("\n[D] 密文配非加密档 ⇒ 不可读（不泄漏明文）")
        try:
            key4 = os.urandom(32)
            sec4 = MdCGSecure(os.path.join(sb4, "lib"),
                              principal=Principal(tenant="t", actor="a",
                                                  clearance="secret",
                                                  can_write=True,
                                                  can_admin=True),
                              master_key=key4)
            sec4.add("priv", BODY + "绝密正文内容ABC\n", layer="knowledge",
                     sensitivity="private")
            p4 = None
            for dp, _dn, fn in os.walk(sec4.root):
                for f in fn:
                    if f == "priv.md":
                        p4 = os.path.join(dp, f)
            t4 = open(p4, encoding="utf-8").read().replace(
                'sensitivity: "private"', 'sensitivity: "internal"')
            with open(p4, "w", encoding="utf-8") as f:
                f.write(t4)
            # 同身份、**异会话**（principal.session 自动随机）同一 KEK
            sec5 = MdCGSecure(os.path.join(sb4, "lib"),
                              principal=Principal(tenant="t", actor="a",
                                                  clearance="secret",
                                                  can_write=True),
                              master_key=key4)
            sec5.rebuild_index()
            g = sec5.get("priv")
            got = (g or {}).get("content")
            ok(got is None, "D1 同身份异会话读不到明文（fail-closed）",
               (repr(got)[:60] if got else got))
            ok("绝密" not in str(got), "D2 返回值不含明文正文片段",
               repr(got)[:40])
        except Exception as exc:                     # noqa: BLE001
            for _l in ("D1 同身份异会话读不到明文（fail-closed）",
                       "D2 返回值不含明文正文片段"):
                ok(False, _l, "D 段异常：%s: %s" % (type(exc).__name__, exc))

        # ---------- E 组：损坏按不可读（挡写回） ----------
        print("\n[E] 损坏按不可读 ⇒ protect.mark 不回写")
        root_e = os.path.join(sb4, "lib_e")
        cge = MdCG(root_e, autoflush=1)
        cge.add("victim", BODY, layer="knowledge", importance=0.5)
        pe = None
        for dp, _dn, fn in os.walk(root_e):
            for f in fn:
                if f == "victim.md":
                    pe = os.path.join(dp, f)
        with open(pe, "w", encoding="utf-8") as f:
            f.write(BAD_FM_FILE.replace('"badnode"', '"victim"'))
        be = open(pe, "rb").read()
        ok(cge.get("victim") is None, "E1 索引内节点盘上损坏后 get() 返回 None")
        _ent = cge.index["nodes"].get("victim")
        ok(cge._read_status(_ent) == (None, None, None),
           "E2 _read_status 返回 (None,None,None)（终态缺失）",
           cge._read_status(_ent))
        from md_cg import protect
        mr = protect.mark(cge, "victim", "test-reason")
        ok(mr.get("ok") is False and mr.get("error") == "node_not_found",
           "E3 protect.mark 判 node_not_found（不写回坏文件）", mr)
        ok(open(pe, "rb").read() == be, "E3b 盘上字节未被改写")

        # ---------- F 组：判据单点 ----------
        print("\n[F] frontmatter_problem 单点判据")
        ok(nodefile.frontmatter_problem({"id": "a", "layer": "knowledge",
                                         "condition_space": {},
                                         "tags": ["x"], "importance": 0.5}) == [],
           "F1 合法 fm 返回 []")
        ok(nodefile.frontmatter_problem({"condition_space": "x"}) != [],
           "F2a str 型 condition_space 判损坏")
        ok(nodefile.frontmatter_problem({"tags": "x"}) != [],
           "F2b str 型 tags 判损坏")
        ok(nodefile.frontmatter_problem({"importance": "0.5"}) != [],
           "F2c str 型 importance 判损坏")
        ok(nodefile.frontmatter_problem({"importance": True}) != [],
           "F2d bool 不算 number（True 判损坏）")
        ok(nodefile.frontmatter_problem({"sensitivity": "internal",
                                         "depends_on": "a,b"}) == [],
           "F2e depends_on 的逗号串形态合法（不误判）")
        # F2f/F2g 是本批修复的反向判据（补 negative）：判据写宽了会把
        # 合法存量形态判成损坏，整节点从索引里消失——两条回归现场即此。
        ok(nodefile.frontmatter_problem({"subgraph": ["a", "b"]}) == [],
           "F2f 纯 id 列表形态的 subgraph 合法（引用式写入，勿误判）")
        ok(nodefile.frontmatter_problem({"subgraph": {"nodes": ["a"]}}) == [],
           "F2f2 映射形态的 subgraph 合法")
        ok(nodefile.frontmatter_problem({"subgraph": "a,b"}) != [],
           "F2f3 既非映射也非序列的 subgraph 仍判损坏")
        ok(nodefile.frontmatter_problem({"id": 123}) == [],
           "F2g 毒 id（id: 123）不判损坏——legacy P3 归一自愈腿")
    finally:
        nodefile.frontmatter_problem = _orig_problem
        MdCG._scan_nodes = _orig_scan
        MdCGSecure._readable = _orig_readable
        crypto.ENCRYPTED_LEVELS = _orig_levels
        for _d in (sb, sb2, sb3, sb4):
            shutil.rmtree(_d, ignore_errors=True)

    print("\n通过 %d / 失败 %d%s"
          % (PASS, FAIL, ("（变异=%s）" % mut) if mut else ""))
    for f in FAILS:
        print(" - 红：%s" % f)
    return 1 if FAIL else 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
