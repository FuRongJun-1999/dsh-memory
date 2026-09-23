# -*- coding: utf-8 -*-
"""md_cg · 第 47 篇：会话归属写入 + 会话视图读取（单库多会话 · PR #21）

设计口径
--------
既定设计：**记忆写入必须带会话身份**（区分不同会话的记忆），同时**读取要能看遍
所有会话做了什么**（跨会话视图）。二者不是矛盾，而是「写侧归因 / 读侧视图」的分工：

  · 写侧：每个节点 `frontmatter.session` 记录**它属于哪个会话**（P45 的归因维度，
    与授权正交）；
  · 读侧：`stg.timeline` 的 `session` 是**视图开关**——
      缺省 None / 空串 → 读遍所有会话（向后兼容，旧调用方多如此）；
      `"*"`            → 同上语义，但把「我要看所有会话」写成**显式意图**；
      具体值           → 只取本会话（自动召回用它防串台）。
    跨会话视图下 `items` 仍逐条回带 `session`：「看遍所有会话」不等于丢掉是谁做的。

来源优先级（高 → 低）：env（`MDCG_SESSION` / `DSH_SESSION_ID`）> 请求声明 > 进程身份。
env 已把会话固定在连接/进程上时，请求里的声明一律忽略（守 `MdCGSecure._attribution`
「MCP 面不透传该入参——客户端不得伪造归属」的纪律）；单进程多会话（一个 MCP 进程
服务多个前端会话）时 env 没法固定，才允许请求声明，且必须过 `_normalize_session`
的防编造校验。

覆盖
----
A 写入归属：两个会话各写一条，frontmatter.session 各自落位（含 temporal → timeline 可见）
B timeline 三态视图：缺省 / "" / "*" 读遍所有会话（逐位一致）；具体值精确匹配；
  返回体 session=生效值（跨会话为 None）；items 每条回带 session
C 索引快照同口径：rebuild 后按会话过滤仍生效（防重建后静默全空）
D 候选层过滤：search / recall 的 session 语义与 timeline 一致（"*" 跨会话）
E 图扩展二次过滤：图扩散绕过 _candidates 时按会话兜底（别的会话节点不得顺边回来）
F MCP _declared_session：空/"*" 不声明；env 权威否决请求声明；否则过 _normalize_session
G call_tool 请求级会话：调用内生效、调用后 principal/session 复原（不污染共享身份）

运行：python -m md_cg.test_p47_session_view
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Windows cmd 默认 GBK：带圈数字/中文标点不在 GBK 内，打印即 UnicodeEncodeError，
# 且崩在断言之后、报告之前 —— 同一测试「因环境而异」。自带 UTF-8 兜底。
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from md_cg.mdcos import MdCGOS, MdCGSecure
from md_cg.security import DEFAULT_SENSITIVITY, Principal
from md_cg import stg
from md_cg import mcp_server as ms

PASS = 0
FAILS = []


def check(name, cond, detail=""):
    global PASS
    if cond:
        PASS += 1
        print(f"  [PASS] {name}" + (f"  · {detail}" if detail else ""))
    else:
        FAILS.append(name)
        print(f"  [FAIL] {name}  · {str(detail)[:240]}")


def _setenv(**kw):
    old = {k: os.environ.get(k) for k in kw}
    for k, v in kw.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    return old


def _restore(old):
    for k, v in old.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


def _p(actor, session, clearance=None, can_admin=True):
    # 会话隔离用例（D/E 段）需非 admin 身份（admin 对绑定档豁免）；
    # 其余段维持原口径（designer + 默认密级 + admin）。
    return Principal(actor=actor,
                     clearance=clearance or DEFAULT_SENSITIVITY,
                     can_write=True, can_admin=can_admin, role="designer",
                     session=session, harness="test-harness")


def _row(r):
    """search/recall 原生返回 (node, score, qual, prov) tuple；dict 则原样。"""
    return r if isinstance(r, dict) else (r[0] if r else {})


def _ids(tl):
    return [i["id"] for i in tl["items"]]


def _mk(root):
    """两个会话各写一条（带 temporal → timeline 可见）。"""
    cga = MdCGSecure(root, principal=_p("alice", "sess_A",
                                        clearance="private", can_admin=False))
    cga.add("n_a", "阿尔法 属于 会话A 的知识点", layer="knowledge", temporal=1000.0)
    cga.add("n_pa", "贝塔 会话A 的私有知识点", layer="knowledge",
            sensitivity="private")
    cgb = MdCGSecure(root, principal=_p("bob", "sess_B",
                                        clearance="private", can_admin=False))
    cgb.add("n_b", "阿尔法 属于 会话B 的知识点", layer="knowledge", temporal=2000.0)
    cgb.add("n_pb", "贝塔 会话B 的私有知识点", layer="knowledge",
            sensitivity="private")
    return cgb


def test_ab(cgb):
    print("\n[A] 写入归属（记忆带会话身份）")
    fm_a = cgb.get("n_a")["frontmatter"]
    fm_b = cgb.get("n_b")["frontmatter"]
    check("A1 A 会话写入带 session=sess_A", fm_a.get("session") == "sess_A",
          fm_a.get("session"))
    check("A2 B 会话写入带 session=sess_B", fm_b.get("session") == "sess_B",
          fm_b.get("session"))

    print("\n[B] timeline 会话视图三态")
    all_tl = stg.timeline(cgb, limit=100)
    check("B1 缺省读遍所有会话（可见面=共享档+本会话绑定档）",
          all_tl["count"] == 3, all_tl["count"])
    check("B2 缺省返回体 session=None（跨会话视图）",
          all_tl["session"] is None, all_tl["session"])
    check("B3 items 逐条回带会话归属（看遍≠丢归属）",
          {i["session"] for i in all_tl["items"]} == {"sess_A", "sess_B"},
          {i["session"] for i in all_tl["items"]})

    empty_tl = stg.timeline(cgb, limit=100, session="")
    check("B4 空串 == 缺省（向后兼容）",
          empty_tl["count"] == all_tl["count"] and _ids(empty_tl) == _ids(all_tl))
    cross_tl = stg.timeline(cgb, limit=100, session="*")
    check("B5 \"*\" 显式跨会话，与缺省逐位一致",
          cross_tl["count"] == all_tl["count"] and _ids(cross_tl) == _ids(all_tl)
          and cross_tl["session"] is None, cross_tl["session"])

    a_tl = stg.timeline(cgb, limit=100, session="sess_A")
    check("B6 具体值只取本会话（他人 private 经授权面剔除）",
          _ids(a_tl) == ["n_a"], _ids(a_tl))
    check("B7 返回体 session=生效值（非跨会话）",
          a_tl["session"] == "sess_A", a_tl["session"])
    b_tl = stg.timeline(cgb, limit=100, session="sess_B")
    check("B8 另一会话只取它的节点（含其绑定档）",
          set(_ids(b_tl)) == {"n_b", "n_pb"}, _ids(b_tl))

    z_tl = stg.timeline(cgb, limit=100, session="sess_Z")
    check("B9 未知会话为空（不因缺省而放行）", z_tl["count"] == 0, z_tl["count"])


def test_c(cgb):
    print("\n[C] 索引快照同口径（rebuild 后按会话过滤仍生效）")
    cgb.rebuild_index()
    e_a = cgb.index["nodes"].get("n_a") or {}
    check("C1 索引快照带 session 键", "session" in e_a, list(e_a.keys())[:6])
    check("C2 快照值 = 写入归属", e_a.get("session") == "sess_A", e_a.get("session"))
    a_tl = stg.timeline(cgb, limit=100, session="sess_A")
    check("C3 rebuild 后按会话过滤不静默全空", _ids(a_tl) == ["n_a"], _ids(a_tl))
    all_tl = stg.timeline(cgb, limit=100)
    check("C4 rebuild 后跨会话仍读全（可见面 3）",
          all_tl["count"] == 3, all_tl["count"])


def test_d(cgb):
    print("\n[D] 候选层会话过滤（search / recall）——issue #35 定稿：分档判定")
    # 视角=bob（sess_B）。共享档（internal 默认）跨会话可见：传不传 session
    # 都能看到 alice 的共享节点；绑定档（private）按身份（principal.session）
    # 判定，查询参数自报的会话不构成豁免。
    res, _ = cgb.search("阿尔法", session="sess_A", judge=False, record=False)
    ids = {_row(r).get("id") for r in res}
    check("D1a 共享档（internal 默认）跨会话可见",
          {"n_a", "n_b"} <= ids, ids)
    res_p, _ = cgb.search("贝塔", judge=False, record=False)
    pids = {_row(r).get("id") for r in res_p}
    check("D1b 绑定档（private）仅归属会话（bob 只见自己的）",
          "n_pb" in pids and "n_pa" not in pids, pids)
    res_h, _ = cgb.search("贝塔", session="sess_A", judge=False, record=False)
    hids = {_row(r).get("id") for r in res_h}
    check("D1c 查询参数自报他人会话不越权（仍只见自己的 private）",
          "n_pb" in hids and "n_pa" not in hids, hids)

    res_x, _ = cgb.search("阿尔法", session="*", judge=False, record=False)
    ids_x = {_row(r).get("id") for r in res_x}
    check("D2 search \"*\" 跨会话", {"n_a", "n_b"} <= ids_x, ids_x)

    res_d, _ = cgb.search("阿尔法", judge=False, record=False)
    ids_d = {_row(r).get("id") for r in res_d}
    check("D3 search 缺省不过滤（兼容）", {"n_a", "n_b"} <= ids_d, ids_d)

    pack = cgb.recall("阿尔法", session="sess_A")
    hid = {_row(h).get("id") for h in (pack.get("pack") or [])}
    check("D4a recall（RRF 主链）共享档跨会话",
          {"n_a", "n_b"} <= hid, hid)
    pack_p = cgb.recall("贝塔")
    hid_p = {_row(h).get("id") for h in (pack_p.get("pack") or [])}
    check("D4b recall 绑定档仅归属会话",
          "n_pb" in hid_p and "n_pa" not in hid_p, hid_p)

    pack_x = cgb.recall("阿尔法", session="*")
    hid_x = {_row(h).get("id") for h in (pack_x.get("pack") or [])}
    check("D5 recall \"*\" 跨会话", {"n_a", "n_b"} <= hid_x, hid_x)


def test_e(cgb):
    print("\n[E] 图扩展二次过滤（跨会话串台守卫）——分档口径")
    # 图扩散会绕过 _candidates：直接把父类 RRF 结果替换成「两共享 + 两绑定」，
    # 验证 MdCGSecure.search_rrf 的二次过滤按档判定——视角 bob：共享档
    # （n_a/n_b）互可见，绑定档仅自己的 n_pb 能回来；session 参数三态
    # （他人会话 / "*" / 缺省）不影响绑定档结果（身份不可自报）。
    crafted = [({"id": "n_a"}, 1.0, None, None),
               ({"id": "n_b"}, 0.9, None, None),
               ({"id": "n_pa"}, 0.8, None, None),
               ({"id": "n_pb"}, 0.7, None, None)]
    orig = MdCGOS.search_rrf
    MdCGOS.search_rrf = lambda self, *a, **kw: (list(crafted), {"tier": "RRF"})
    try:
        kept, _ = cgb.search_rrf("q", session="sess_A")
        ids = [r[0]["id"] for r in kept]
        check("E1 绑定档按身份：他人 private 不得顺边回来（共享档保留）",
              {"n_a", "n_b", "n_pb"} <= set(ids) and "n_pa" not in ids, ids)
        kept_x, _ = cgb.search_rrf("q", session="*")
        check("E2 \"*\" 同口径（绑定档不受查询参数影响）",
              {r[0]["id"] for r in kept_x} == {"n_a", "n_b", "n_pb"},
              [r[0]["id"] for r in kept_x])
        kept_all, _ = cgb.search_rrf("q")
        check("E3 缺省同口径（兼容）",
              {r[0]["id"] for r in kept_all} == {"n_a", "n_b", "n_pb"},
              [r[0]["id"] for r in kept_all])
    finally:
        MdCGOS.search_rrf = orig


def test_f():
    print("\n[F] MCP _declared_session 来源优先级")
    old = _setenv(MDCG_SESSION=None, DSH_SESSION_ID=None)
    try:
        check("F1 空串不构成声明（退回进程身份）",
              ms._declared_session("") is None)
        check("F2 空白不构成声明", ms._declared_session("   ") is None)
        check("F3 \"*\" 是读取语法非会话名（不构成声明）",
              ms._declared_session("*") is None)
        check("F4 非 DSH 形态请求声明照收（过归一校验）",
              ms._declared_session("sess_A") == "sess_A",
              ms._declared_session("sess_A"))

        os.environ["MDCG_SESSION"] = "env-sess"
        check("F5 env 存在 → 请求声明被否决（环境权威）",
              ms._declared_session("sess_A") is None)
        os.environ.pop("MDCG_SESSION")

        os.environ["DSH_SESSION_ID"] = "dsh-env"
        check("F6 DSH_SESSION_ID 同样否决请求声明",
              ms._declared_session("sess_A") is None)
        os.environ.pop("DSH_SESSION_ID")

        os.environ["MDCG_SESSION"] = "   "      # 空白不算环境权威
        check("F7 空白 env 不构成权威（请求声明生效）",
              ms._declared_session("sess_A") == "sess_A")
    finally:
        _restore(old)


def test_g(cgb):
    print("\n[G] call_tool 请求级会话（生效且不污染共享身份）")
    p_before = cgb.principal
    s_before = cgb.session
    out = ms.call_tool(cgb, "stg",
                       {"op": "timeline", "limit": 100, "session": "sess_A"})
    check("G1 请求级会话在本调用内生效",
          out.get("count") == 1 and _ids(out) == ["n_a"], out.get("count"))
    check("G2 调用后 principal 复原（未污染共享身份）",
          cgb.principal is p_before)
    check("G3 调用后 session 复原", cgb.session == s_before,
          (cgb.session, s_before))

    cross = ms.call_tool(cgb, "stg",
                         {"op": "timeline", "limit": 100, "session": "*"})
    check("G4 MCP 面 \"*\" 跨会话读全（可见面 3）",
          cross.get("count") == 3, cross.get("count"))

    default = ms.call_tool(cgb, "stg", {"op": "timeline", "limit": 100})
    check("G5 缺省读全（兼容旧调用，可见面 3）",
          default.get("count") == 3, default.get("count"))


def main():
    root = tempfile.mkdtemp(prefix="mdcg_p47_")
    try:
        cgb = _mk(root)
        test_ab(cgb)
        test_c(cgb)
        test_d(cgb)
        test_e(cgb)
        test_g(cgb)
    finally:
        shutil.rmtree(root, ignore_errors=True)
    test_f()

    print("\n通过 %d / 失败 %d" % (PASS, len(FAILS)))
    if FAILS:
        print("失败项：" + ", ".join(FAILS))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
