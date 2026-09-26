# -*- coding: utf-8 -*-
"""test_none_id_write_guard —— None.md 脏节点写入面守卫（DSH 在役库实测缺陷 P3）

现场（DSH 端在役库实测）：``knowledge/orphan/None.md`` 出现在检索与 route 候选中
参与打分。取证链（2026-09-26，临时库实弹复现）：

  1. 批次 24（2a57c2a2，2026-09-24）之前 ``add()`` 对 node_id **零校验**，
     ``path = os.path.join(d, f"{node_id}.md")`` 直拼——``add(None, ...)`` 直落
     ``None.md``（旧版直接源头，git 取证 ``git show 2a57c2a2^:md_cg/mdcg.py``）。
  2. 现行代码 ``add(None)``/``add("")`` 已被 P0-1 白名单拒绝（mdcg.py _NODE_ID_RE），
     **但字符串 ``"None"``（Python ``str(None)`` 的污染形态）形状合法照常放行**：
     实弹复现 ``add("None", ...)`` → 生成 ``knowledge/orphan/None.md``。
     ``"null"``（TS/JS ``String(null)`` 形态）同族放行。这是现行写入面残留洞。
  3. 盘上存量 ``None.md`` 经 ``_scan_nodes`` 全库扫描收录为 ``id="None"``，
     ``search``/route 候选参与打分（复现实测命中）——与 DSH 病理现象完全吻合。

修复（本守卫的红绿两态锚点）：``md_cg/mdcg.py`` ``add()`` 写入边界把空语义值的
字符串化污染形态（整串精确等值 ``"None"`` / ``"null"``，**大小写敏感、不扩子串**）
结构化拒绝（ValueError，fail-closed）——add 是全部写入链（writepipe 执行器 /
review accept / identity / consolidate / branches）落盘的唯一真源边界，堵一处即
全链路堵死。``_move_layer`` 等直写点只对已在索引中的既有节点操作，不新造 id。

清理面（不在本守卫内，运维建议）：存量 None.md 属历史脏数据——删除
``<root>/knowledge/orphan/None.md`` 文件后 ``rebuild_index()`` 即从索引与检索/
route 候选中消失（[6] 的收录取证即清理有效性依据）；勿用 ``add("None",...)``
覆写清理（修复后该形态被拒）。

隔离纪律：全程 ``tempfile.mkdtemp`` 临时库，MDCG_ROOT/MDCG_TOKEN_FILE 不参与
（库实例以显式 root 构造），不触真实令牌库与真实在役数据目录。

自检 floor：断言总数低于 FLOOR 视为失败——防「探针面失效 → 假绿」。

运行：python -X utf8 -m md_cg.test_none_id_write_guard
"""
from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from md_cg.mdcos import MdCGOS  # noqa: E402

FLOOR = 12           # 断言总数下限（防假绿）
passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print("  [PASS] " + name)
    else:
        failed += 1
        print("  [FAIL] " + name + "  " + str(detail)[:200])


def _none_md_hits(root):
    """盘面上所有 None.md（大小写不敏感——Windows 盘面本就不区分）。"""
    hits = []
    for dirpath, _dirs, files in os.walk(root):
        for f in files:
            if f.lower() == "none.md":
                hits.append(os.path.relpath(os.path.join(dirpath, f), root)
                            .replace("\\", "/"))
    return sorted(hits)


def main():
    root = tempfile.mkdtemp(prefix="mdcg_none_guard_")
    try:
        return _run(root)
    finally:
        import shutil
        shutil.rmtree(root, ignore_errors=True)   # 测毕清理（临时库纪律）


def _run(root):
    cg = MdCGOS(root)

    print("[1] 红形态：字符串 \"None\"（str(None) 污染形态）在写入边界拒绝")
    rejected = False
    try:
        nid = cg.add("None", "污染形态内容 无条件")
        check("add(\"None\") 被拒绝", False, "返回了 " + repr(nid))
    except ValueError as e:
        rejected = True
        check("add(\"None\") 被拒绝", True)
        check("拒绝是结构化 ValueError 且消息点名形态",
              "None" in str(e) and "node_id" in str(e), str(e)[:120])
    check("盘面无 None.md 生成", _none_md_hits(root) == [], _none_md_hits(root))
    check("索引无 id='None' 条目", "None" not in cg.index["nodes"])

    print("[2] 红形态：字符串 \"null\"（String(null) 跨语言同族形态）")
    try:
        nid = cg.add("null", "跨语言污染形态内容 无条件")
        check("add(\"null\") 被拒绝", False, "返回了 " + repr(nid))
    except ValueError:
        check("add(\"null\") 被拒绝", True)
    check("盘面仍无 None.md/null.md", _none_md_hits(root) == [],
          _none_md_hits(root))

    print("[3] 防误杀：含 None/null 子串的合法 id 照常写入（只拒整串精确等值）")
    ok1 = cg.add("NoneBot_1", "含 None 子串的合法 id 无条件")
    ok2 = cg.add("nullify_test", "含 null 子串的合法 id 无条件")
    check("add(\"NoneBot_1\") 正常", ok1 == "NoneBot_1")
    check("add(\"nullify_test\") 正常", ok2 == "nullify_test")

    print("[4] 既有语义不回退：None 本体 / falsy 仍结构化拒绝（P0-1）")
    # 注：add(123) 是既有合法行为（"123" 匹配白名单），不入守卫——非字符串
    # 原值入索引快照属相邻缺陷（_scan_nodes/_load_index 混型键 sorted 崩），
    # 超出本守卫目标，取证记录于修复报告。
    for bad in (None, "", 0):
        try:
            cg.add(bad, "非法形态内容")
            check("add(%r) 仍被拒绝" % (bad,), False, "竟返回成功")
        except ValueError:
            check("add(%r) 仍被拒绝（ValueError）" % (bad,), True)

    print("[5] writepipe 链：node_id=\"None\" 不落盘（DEFER/BLINDSPOT 短路入队"
          "或落盘前被 add 边界拒绝，两态皆 fail-closed）")
    from md_cg import writepipe
    pipe = writepipe.WritePipeline()
    writepipe.install_default_gates(pipe)
    committed = None
    try:
        out = pipe.execute(cg, {"content": "writepipe 污染形态", "node_id": "None",
                                "content_kind": "work_done",
                                "生效条件": "writepipe 守卫探针"})
        committed = out.get("committed")
    except ValueError:
        committed = False                       # 落盘前被 add 边界拒绝（修复态）
    check("writepipe 对 node_id='None' 不提交落盘", committed is not True,
          repr(committed))
    check("盘面无 None.md（writepipe 后复查）", _none_md_hits(root) == [],
          _none_md_hits(root))

    print("[6] 存量脏数据收录取证：盘上 None.md 被 _scan_nodes 收进索引（DSH 病理机理；"
          "亦是清理建议的依据——删文件 + rebuild 即消失）")
    d = os.path.join(root, "knowledge", "orphan")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "None.md"), "w", encoding="utf-8") as f:
        f.write("---\nid: None\nlayer: knowledge\nimportance: 0.5\n"
                "confidence: 0.6\ncreated_at: 1\ntags: []\n---\n\n历史脏数据内容\n")
    cg2 = MdCGOS(root)                      # 重开：走 _scan_nodes 全库扫描
    cg2.rebuild_index()
    check("历史 None.md 被扫描收录（机理复证）", "None" in cg2.index["nodes"])
    res, _m = cg2.search_rrf("历史脏数据内容", k=10, judge=False)
    check("检索候选命中 id='None'（病理复证）",
          any(r[0]["id"] == "None" for r in res), [r[0]["id"] for r in res])
    os.remove(os.path.join(d, "None.md"))   # 清理后即消失（清理建议有效性）
    cg3 = MdCGOS(root)
    cg3.rebuild_index()
    check("删文件 + rebuild 后 id='None' 从索引消失（清理有效）",
          "None" not in cg3.index["nodes"])

    check(f"断言总数不低于 FLOOR（{passed} >= {FLOOR}）", passed >= FLOOR)

    print(f"\nnone_id_write_guard: {passed} 通过 / {failed} 失败")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
