# -*- coding: utf-8 -*-
"""守卫：坏 UTF-8 节点在五个读取面的行为契约（PR #54 面 + 三处读取面同口径扩展）

背景（取证自 `git show --stat ccef3bc0 / 30e0580b` 与本文件注释逐字引用的现场）
--------------------------------------------------------------------------
`30e0580b`（健康检查）与 `ccef3bc0`（读取面）落了「损坏非 UTF-8 节点不应让读取
面崩溃」这条口径；工作区未提交改动把同一口径扩展到另三个站点（`git diff` 逐行
核对：`md_cg/census.py`、`md_cg/mreview/locate.py`、`md_cg/rollback.py`、
`md_cg/mdcos.py` 的 `restore`）。本守卫把**五个读取面的行为**一并钉死——不钉
「源码里有 except」（源文本在场不等于行为成立），全部断言经隔离临时库真跑：

  ① `census.load(root)`：坏 .md 不崩、跳过；良品照常入列。
  ② `MdCGOS.restore(node_id)`：坏 trash 文件 → `ok=False` / `error=="corrupt"`，
     且 trash 源文件**原样保留**（不删不移、逐字节不变）、节点不回索引。
  ③ `rollback.read_preimage(cg, node_id, rel)`：坏前像 → 抛 `RollbackError`
     （`code=="preimage_unreadable"`），**不是裸 UnicodeDecodeError**；
     相邻分支（前像缺失）→ `RollbackError(code=="preimage_missing")`。
  ④ `mreview/locate`：坏节点不崩；「在索引但不可读」与「不在索引」**分野**
     （前者 load 非 None、blindspot 空、正文长 0、按空盘面判定；后者
     `blindspot==["节点 X 不在索引"]` + `load=None` + `hits==[]`）；批量入口
     `locate_many` 把坏节点计入 nodes（不是 missing）并给显式读数。
  ⑤ `health()["skipped_unreadable"] == 1`（1 坏 + 2 良品库；良品照常统计）。

定点变异自证（`--mutate`，与 `md_cg/test_i50e_readside_protection.py` 同口径）
--------------------------------------------------------------------------
每处受护站点配一个定点变异（把对应捕获/计数短路掉），变异**不落盘**——
`inspect.getsource` + 字面替换 + `exec` + `types.FunctionType` 绑回原 globals，
`setattr` 安装/还原（monkeypatch 行为面）。每轮跑全部五个检查面，逐变异打印
「变异 <n> 红项=<k>」；判定 = 红项数逐处吻合**且**红项全部落在对应面
（定点性：一处变异只打红它守的那一面）。表内 expect 列为实施期实测
（2026-10-04 本文件首跑）；锚点漂移（实现改了却没同步本表）→ 报 ANCHOR-MISS
并 **exit 2**（fail-closed，默认模式同样先做锚点自检，不以 git HEAD 为基线源）。

安全边界：一切在 `tempfile.mkdtemp()` 临时库内进行——绝不写工作区、绝不碰
任何在役记忆库（不读不写 `MDCG_ROOT`/DSH 数据根）、不起常驻服务、不重启/终止
任何在跑进程；变异的源码替换只在进程内存里生效，磁盘上的实现文件一字不动。

运行（仓根直跑，退出码 0 ＝ 全绿）：

    python -X utf8 -m md_cg.test_corrupt_utf8_read_surfaces
    python -X utf8 -m md_cg.test_corrupt_utf8_read_surfaces --mutate
    python -X utf8 -m md_cg.test_corrupt_utf8_read_surfaces --mutate --list
"""
from __future__ import annotations

import inspect
import os
import shutil
import sys
import tempfile
import textwrap
import types

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:                # 保证 `import md_cg.*` 能定位到当前树
    sys.path.insert(0, REPO)

from md_cg import census, protect, rollback                # noqa: E402
from md_cg.mdcg import MdCG                                 # noqa: E402
from md_cg.mdcos import MdCGOS                              # noqa: E402
from md_cg.mreview import locate as locate_mod              # noqa: E402

#: 损坏字节：非法 UTF-8 起始字节（0xff 在任何位置都非法）。
BAD_BYTES = bytes((0xff, 0xfe, 0xfd))
#: 良品正文（CCG 六要素齐备；末尾带 \n 让盘上正文与写前逐字一致，
#: 消掉 `nodefile.dumps` 补行尾带来的 hash 归一噪声）。
GOOD_DOC = ("# 功能名：读面守卫良品节点\n"
            "# 生效条件：任意情境\n"
            "# 子功能：守卫夹具\n"
            "# 执行：直接调用\n"
            "# 验证方式：test\n"
            "# 不适用条件：无\n"
            "读面守卫良品正文。\n")
#: ④ 坏节点在 `locate_ex` 下的确定读数（实施期实测 2026-10-04，本文件首跑）：
#: 读不到盘面 ⇒ 正文按空、fm 按空判定的五条命中（content_hash 矛盾 locator
#: 因 `content is None` 而**不**参与——与 locate_many 的读数差异见 ④ 末条）。
BAD_TRIPLES = [
    ("missing_field", "condition_space", "condition_slots"),
    ("missing_field", "content", "ccg_incomplete"),
    ("missing_field", "evidence_count", "field_absent"),
    ("missing_field", "role", "field_absent"),
    ("weak_source", "verification_basis", "basis_absent"),
]

_PASS = []
_FAIL = []
_VERBOSE = True


def _ok(cond, msg, extra=""):
    (_PASS if cond else _FAIL).append(msg)
    if _VERBOSE:
        print(("  PASS " if cond else "  FAIL ") + msg
              + (("  ← " + str(extra)) if (extra and not cond) else ""))


# ---------------------------------------------------------------- 夹具
def _synth(tmp, face, node_ids):
    """隔离临时库：建库 → add 全部节点（同形良品正文）→ flush。"""
    root = os.path.join(tmp, face)
    cg = MdCGOS(root, autoflush=0)
    for nid in node_ids:
        cg.add(nid, GOOD_DOC, tags=["domain:guard"])
    cg.flush()
    return cg, root


def _write_bad(path):
    with open(path, "wb") as fh:
        fh.write(BAD_BYTES)


def _corrupt_node(cg, root, nid):
    """把某节点盘上文件替换成坏字节，返回其绝对路径。"""
    rel = cg.index["nodes"][nid]["path"]
    p = os.path.join(root, str(rel).replace("/", os.sep))
    _write_bad(p)
    return p


# ---------------------------------------------------------------- ① census
def _check_census(tmp):
    cg, root = _synth(tmp, "census", ("good1", "good2", "bad"))
    try:
        _corrupt_node(cg, root, "bad")
        rows = None
        raised = None
        try:
            rows = census.load(root)
        except BaseException as exc:                  # noqa: BLE001
            raised = exc
        _ok(raised is None, "① census.load 遇坏 .md 不崩", repr(raised))
        ids = sorted(r[0] for r in rows or [])
        _ok(ids == ["good1", "good2"], "① 良品照常入列（恰 good1/good2）", ids)
        _ok("bad" not in ids, "① 坏节点被跳过（不在产物中）")
    finally:
        cg.close()


# ---------------------------------------------------------------- ② restore
def _check_restore(tmp):
    cg, root = _synth(tmp, "restore", ("good1", "bad", "victim"))
    try:
        _corrupt_node(cg, root, "bad")
        _ok(cg.forget("victim").get("ok") is True, "② 夹具：victim 已软删（进 trash）")
        tp = os.path.join(cg.trash_dir, "victim.md")
        _ok(os.path.exists(tp), "② 夹具：trash 源文件在位")
        _write_bad(tp)
        before = open(tp, "rb").read()
        out = None
        raised = None
        try:
            out = cg.restore("victim", force=True)
        except BaseException as exc:                  # noqa: BLE001
            raised = exc
        _ok(raised is None, "② 坏 trash 下 restore 不抛异常", repr(raised))
        out = out if isinstance(out, dict) else {}
        _ok(out.get("ok") is False, "② 返回 ok=False", out)
        _ok(out.get("error") == "corrupt", "② error=='corrupt'", out)
        after = open(tp, "rb").read() if os.path.exists(tp) else None
        _ok(after == before,
            "② trash 源文件原样保留（存在且逐字节不变）", after)
        _ok("victim" not in cg.index["nodes"], "② 坏节点未回到索引")
    finally:
        cg.close()


# ---------------------------------------------------------------- ③ read_preimage
def _check_preimage(tmp):
    cg, root = _synth(tmp, "preimage", ("good1", "bad"))
    try:
        _corrupt_node(cg, root, "bad")
        rel = protect.snapshot_preimage(cg, "good1", action="C", pid="guard",
                                        reason="守卫夹具")
        _ok(bool(rel), "③ 夹具：前像已拍（真走 snapshot_preimage）")
        pp = os.path.join(root, str(rel or "").replace("/", os.sep))
        _write_bad(pp)

        exc = None
        try:
            rollback.read_preimage(cg, "good1", rel)
        except BaseException as e:                    # noqa: BLE001
            exc = e
        _ok(isinstance(exc, rollback.RollbackError),
            "③ 坏前像抛 RollbackError", repr(exc))
        _ok(not isinstance(exc, UnicodeDecodeError),
            "③ 不是裸 UnicodeDecodeError")
        _ok(getattr(exc, "code", None) == "preimage_unreadable",
            "③ code=='preimage_unreadable'", getattr(exc, "code", None))

        exc2 = None
        try:
            rollback.read_preimage(cg, "good1",
                                   "_protected_history/good1/absent.md")
        except BaseException as e:                    # noqa: BLE001
            exc2 = e
        _ok(isinstance(exc2, rollback.RollbackError)
            and getattr(exc2, "code", None) == "preimage_missing",
            "③ 相邻分支：前像缺失 → RollbackError(preimage_missing)", repr(exc2))
    finally:
        cg.close()


# ---------------------------------------------------------------- ④ locate
def _check_locate(tmp):
    cg, root = _synth(tmp, "locate", ("good1", "good2", "bad"))
    try:
        _corrupt_node(cg, root, "bad")
        ex = None
        raised = None
        try:
            ex = locate_mod.locate_ex("bad", root=root, index=cg.index)
        except BaseException as exc:                  # noqa: BLE001
            raised = exc
        _ok(raised is None, "④ locate_ex 对坏节点不崩", repr(raised))
        ex = ex if isinstance(ex, dict) else {}
        _ok(sorted(ex) == ["blindspot", "hits", "load"],
            "④ 返回三键契约（hits/blindspot/load）", sorted(ex))
        load = ex.get("load")
        _ok(isinstance(load, dict) and load.get("content_len") == 0,
            "④ 坏节点在索引：load 非 None 且正文长 0（≠ 不在索引）", load)
        _ok(ex.get("blindspot") == [], "④ 不误报「不在索引」", ex.get("blindspot"))
        triples = sorted((h.get("issue_kind"), h.get("field"), h.get("rule"))
                         for h in ex.get("hits") or [])
        _ok(triples == BAD_TRIPLES,
            "④ 按空盘面判定（实测命中集合，不静默放过）", triples)
        _ok(all(h.get("status") == "located" for h in ex.get("hits") or []),
            "④ 命中全部 status=='located'")

        gh = None
        raised = None
        try:
            gh = locate_mod.locate_ex("ghost", root=root, index=cg.index)
        except BaseException as exc:                  # noqa: BLE001
            raised = exc
        _ok(raised is None and isinstance(gh, dict)
            and gh.get("blindspot") == ["节点 ghost 不在索引"]
            and gh.get("load") is None and gh.get("hits") == [],
            "④ 相邻分支：不在索引 → blindspot 点名 / load None / hits 空",
            (repr(raised), gh))

        many = None
        raised = None
        try:
            many = locate_mod.locate_many(node_ids=["bad", "good1"],
                                          root=root, index=cg.index)
        except BaseException as exc:                  # noqa: BLE001
            raised = exc
        _ok(raised is None, "④ locate_many 对坏节点不崩", repr(raised))
        many = many if isinstance(many, dict) else {}
        _ok(many.get("nodes") == 2 and many.get("missing") == [],
            "④ locate_many：坏节点计入 nodes，不是 missing",
            (many.get("nodes"), many.get("missing")))
        _ok(any(h.get("issue_kind") == "contradiction"
                and h.get("field") == "content_hash"
                for h in many.get("hits") or []),
            "④ locate_many：坏节点出显式读数（content_hash 矛盾）")
    finally:
        cg.close()


# ---------------------------------------------------------------- ⑤ health
def _check_health(tmp):
    cg, root = _synth(tmp, "health", ("good1", "good2", "bad"))
    try:
        _corrupt_node(cg, root, "bad")
        h = None
        raised = None
        try:
            h = cg.health()
        except BaseException as exc:                  # noqa: BLE001
            raised = exc
        _ok(raised is None, "⑤ health() 不崩", repr(raised))
        h = h if isinstance(h, dict) else {}
        _ok(h.get("skipped_unreadable") == 1,
            "⑤ skipped_unreadable==1（1 坏）", h.get("skipped_unreadable"))
        _ok(h.get("total_nodes") == 3, "⑤ total_nodes==3（索引三节点）",
            h.get("total_nodes"))
        _ok(sum(v.get("total", 0)
                for v in (h.get("ccg_by_layer") or {}).values()) == 2,
            "⑤ 良品照常统计（层总计 2）", h.get("ccg_by_layer"))
    finally:
        cg.close()


_CHECKS = (("census", _check_census), ("restore", _check_restore),
           ("preimage", _check_preimage), ("locate", _check_locate),
           ("health", _check_health))


def _run_all(tmp):
    """跑全部检查面，返回 ({面名: 失败数}, 通过总数)。

    面内异常计 1 条失败并继续下一面（守卫不因被测面抛异常整体崩）。
    """
    out = {}
    passed = 0
    for name, fn in _CHECKS:
        _PASS.clear()
        _FAIL.clear()
        try:
            fn(tmp)
        except BaseException as exc:                  # noqa: BLE001
            _FAIL.append("面 %s 未捕获异常 %r" % (name, exc))
        out[name] = len(_FAIL)
        passed += len(_PASS)
    return out, passed


# ---------------------------------------------------------------- 定点变异自证
# 表内每项：holder/attr = monkeypatch 落点；old 必须**逐字**出现在目标函数
# 当前源码（dedent 后）里且**唯一**；new 为短路形态；face = 应转红的面；
# expect = 实施期实测的红项数（2026-10-04 本文件首跑，实测构成如下）：
#   m1 红 2 = ①不崩 + ①良品集合（①「坏节点不在产物中」在 load 崩掉、产物为空时
#     仍成立——空集不含 bad，属该断言的固有局限，读数如实记 2）；
#   m2 红 3 = ②不抛 + ok == False + error == "corrupt"（trash 字节/未回索引
#     两条在裸抛下仍成立，不红）；
#   m3 红 3 = ③RollbackError + ③非 UnicodeDecodeError + ③code
#     （③相邻分支 preimage_missing 不受影响，不红）；
#   m4 红 8 = ④不崩 + 三键 + load 非 None + blindspot 空 + 命中集合 + locate_many
#     不崩 + nodes/missing + content_hash 读数（④status 与 ghost 邻支两条不红：
#     空 hits 使 "all()" 恒真、ghost 走「索引无此项」早返回不读盘）；
#   m5 红 1 = ⑤skipped_unreadable（total_nodes 与层统计不受计数短路影响）。
_MUTATIONS = (
    # m1：census.load 去掉 UnicodeDecodeError 捕获（修复前形态）→ ① 红。
    {"n": 1, "face": "census", "holder": census, "attr": "load",
     "old": "except (OSError, UnicodeDecodeError):", "new": "except OSError:",
     "desc": "census.load 丢 UnicodeDecodeError 捕获", "expect": 2},
    # m2：restore 的 except 块改成裸抛（不再落结构化失败）→ ② 红。
    {"n": 2, "face": "restore", "holder": MdCGOS, "attr": "restore",
     "old": "# trash 源损坏：返回结构化失败，源文件原样保留（不删不移）",
     "new": 'raise UnicodeDecodeError("utf-8", b"\\xff", 0, 1, "mut")',
     "desc": "restore 丢 corrupt 结构化返回（改裸抛）", "expect": 3},
    # m3：read_preimage 的捕获子句换成 OSError（UnicodeDecodeError 逃逸）→ ③ 红。
    {"n": 3, "face": "preimage", "holder": rollback, "attr": "read_preimage",
     "old": "except UnicodeDecodeError as exc:",
     "new": "except OSError as exc:",
     "desc": "read_preimage 丢坏字节捕获", "expect": 3},
    # m4：load_node 丢 UnicodeDecodeError 捕获 → ④ 红（其余面不受累）。
    {"n": 4, "face": "locate", "holder": locate_mod, "attr": "load_node",
     "old": "except (OSError, UnicodeDecodeError):", "new": "except OSError:",
     "desc": "locate.load_node 丢 UnicodeDecodeError 捕获", "expect": 8},
    # m5：health 的跳过计数短路 → ⑤ 红。
    {"n": 5, "face": "health", "holder": MdCG, "attr": "health",
     "old": "skipped_unreadable += 1", "new": "pass",
     "desc": "health 丢 skipped_unreadable 计数", "expect": 1},
)


def _target_src(m):
    return textwrap.dedent(inspect.getsource(getattr(m["holder"], m["attr"])))


def _anchor_check():
    """返回 ANCHOR-MISS 说明列表（空 = 全部在位且唯一）。"""
    bad = []
    for m in _MUTATIONS:
        src = _target_src(m)
        cnt = src.count(m["old"])
        if cnt != 1:
            bad.append("变异 %d [%s] 锚点 %r 在目标源码中出现 %d 次（需恰 1 次）"
                       % (m["n"], m["face"], m["old"], cnt))
    return bad


def _mutate_func(func, old, new):
    """按字面替换重编译函数（源码不落盘）——globals 绑回原模块/类。"""
    src = textwrap.dedent(inspect.getsource(func))
    if src.count(old) != 1:
        raise AssertionError("锚点不唯一：%r（%d 处）" % (old, src.count(old)))
    ns = {}
    exec(compile(src.replace(old, new, 1), "<mut:%s>" % func.__name__, "exec"),
         ns)
    maker = ns[func.__name__]
    nf = types.FunctionType(maker.__code__, func.__globals__, func.__name__,
                            maker.__defaults__, maker.__closure__)
    nf.__kwdefaults__ = maker.__kwdefaults__
    nf.__qualname__ = func.__qualname__
    return nf


def _mutate_mode(tmp):
    global _VERBOSE
    _VERBOSE = False
    base, _passed = _run_all(tmp)
    b = sum(base.values())
    print("  未变异基线：红项=%d%s"
          % (b, "" if b == 0 else "  ← 基线即红，变异核验无意义"))
    bad = [] if b == 0 else ["未变异基线即失败"]
    for m in _MUTATIONS:
        live = getattr(m["holder"], m["attr"])
        try:
            setattr(m["holder"], m["attr"], _mutate_func(live, m["old"],
                                                         m["new"]))
            res, _passed = _run_all(tmp)
        finally:
            setattr(m["holder"], m["attr"], live)
        k = sum(res.values())
        faces = [n for n in res if res[n]]
        hit = (k == m["expect"] and faces == [m["face"]])
        print("  变异 %d [%s] %s → 红项=%d（面=%s）%s"
              % (m["n"], m["face"], m["desc"], k, ",".join(faces) or "-",
                 "命中预期" if hit else "**不命中（预期 红项=%s 面=%s）**"
                 % (m["expect"], m["face"])))
        if not hit:
            bad.append("变异 %d" % m["n"])
    print("\n定点变异自证：%s"
          % ("PASS（五处受护站点各被对应面抓住，红项数逐处吻合、无跨面误伤）"
             if not bad else "FAIL —— " + "、".join(bad)))
    return 0 if not bad else 1


# ---------------------------------------------------------------- main
def main():
    if "--list" in sys.argv:
        print("变异表（%d 项）：" % len(_MUTATIONS))
        for m in _MUTATIONS:
            print("  %d [%s] %s（expect 红项=%s）" % (m["n"], m["face"],
                                                    m["desc"], m["expect"]))
        return 0

    anchor_bad = _anchor_check()
    if anchor_bad:
        for b in anchor_bad:
            print("  ANCHOR-MISS " + b)
        print("锚点自检：FAIL（fail-closed，exit 2）——实现改了请同步本文件变异表")
        return 2
    print("坏 UTF-8 读取面守卫（五面）——隔离临时库，不碰工作区与在役库；"
          "锚点自检 PASS")

    tmp = tempfile.mkdtemp(prefix="corrupt_utf8_guard_")
    print("临时根：%s" % tmp)
    try:
        if "--mutate" in sys.argv:
            rc = _mutate_mode(tmp)
        else:
            res, passed = _run_all(tmp)
            print("== 五面汇总 ==")
            for name, fails in res.items():
                print("  面 %s：%s" % (name, "绿" if fails == 0
                                      else "红（%d 项）" % fails))
            red = sum(res.values())
            print("\n读取面守卫：%d 通过，%d 失败" % (passed, red))
            rc = 1 if red else 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return rc


if __name__ == "__main__":
    sys.exit(main())
