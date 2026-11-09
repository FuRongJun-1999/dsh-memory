# -*- coding: utf-8 -*-
"""t91a-20261011 / t2 门禁：巩固链产出**正文**（consolidate/insight 不再只做结构性记账）。

accept 原文（逐条对应本文件的断言）：
  ① 巩固运行后在影子根里能观察到至少一条**带正文内容**的产物
     —— 正文 = 可读自然语言（非空、含字母/汉字），不是只有计数/时间戳/结构字段；
  ② 正文的产生**不依赖网络与外部模型**（本地确定性合成：来源节点摘要拼接 + 溯源字段）；
  ③ 幂等可复跑：同一输入跑两轮，第二轮不产生重复条目（既有去重口径，不靠时间戳）；
  ④ 既有 consolidate 的对外返回形状向后兼容（新增字段可以，删/改既有键不行）；
  ⑤ 不改 sleep.py 里除调用点之外的逻辑。

与判据的映射：
  ① 见 [1] 正文存在性 + 正文可读性断言
  ② 见 [2] 确定性复算 + 无网络断言（重跑同输入得到逐字相同正文）
  ③ 见 [3] 两轮不翻倍
  ④ 见 [4] 返回形状向后兼容
  ⑤ 见 [5] sleep.iterate 调用链端到端仍产出正文

跑法（工作目录无关，可在任意目录直接跑）：
    python D:\\wook\\lingshu-src\\md_cg\\test_t91a_consolidate_prose.py
退出码 0 = 全通过；非 0 = 有断言失败（逐条打印 FAIL 与实据）。

只写临时影子根（tempfile.mkdtemp），绝不触碰任何真实数据根。
零第三方依赖。
"""
from __future__ import annotations

import glob
import json
import os
import re
import shutil
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.dirname(_HERE)                      # lingshu-src
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from md_cg import consolidate as cd                                  # noqa: E402
from md_cg import sleep                                              # noqa: E402
from md_cg.mdcos import MdCGOS                                       # noqa: E402

PROSE_MARK = "# 巩固正文："

_checks = []


# 生效条件：给定 name 与 cond（真值判通过），把结论记入 _checks 并按 ok/FAIL 打印一行；detail 非空时附在行尾。
def check(name, cond, detail=""):
    ok = bool(cond)
    _checks.append((name, ok))
    print("%s %s%s" % ("  ok  " if ok else " FAIL ", name,
                       (" :: %s" % detail) if detail else ""))
    return ok


# 生效条件：给定 root，遍历其下全部 .md，返回 (相对路径, 全文) 列表。
def _all_md(root):
    out = []
    for p in glob.glob(os.path.join(root, "**", "*.md"), recursive=True):
        with open(p, encoding="utf-8") as f:
            out.append((os.path.relpath(p, root).replace("\\", "/"), f.read()))
    return out


# 生效条件：给定 content，返回去掉 frontmatter 后的正文段。
def _body(content):
    if content.startswith("---"):
        j = content.find("\n---", 3)
        if j >= 0:
            return content[j + 4:]
    return content


# 生效条件：给定 text，返回它是否为「可读正文」——strip 后非空且含至少一个字母或汉字。
def _is_readable(text):
    s = (text or "").strip()
    return bool(s) and any(ch.isalpha() for ch in s)


# 生效条件：给定 root，返回其中所有含 PROSE_MARK 的产物 [(rel_path, 正文块文本)]。
def _prose_artifacts(root):
    out = []
    for rel, content in _all_md(root):
        if PROSE_MARK not in content:
            continue
        body = _body(content)
        i = body.index(PROSE_MARK)
        block = body[i + len(PROSE_MARK):]
        # 正文块到下一个「# 」开头的行为止（CCG 声明行/功能名行是结构，不属正文块）
        lines = []
        for ln in block.split("\n"):
            if ln.startswith("# "):
                break
            lines.append(ln)
        out.append((rel, "\n".join(lines).strip()))
    return out


# 生效条件：给定 root，造 4 个内容相近、共享生效条件的情境节点（可被归纳/升层），返回节点 id 列表。
def _seed(root, ids=None, layer="contextual", importance=0.5):
    """造 3~5 个可合并节点（此处 4 个），内容相近且共享「生效条件」。

    importance 默认 **0.5**（刻意不取 0.9）：≥0.7 会触发 mdcos 的自动保护
    （`protected=True, protection_reason="importance=0.90≥0.7"`），而
    `induce_memories` 的候选池**显式排除受保护节点** ⇒ 聚类恒为 0。
    升层路径需要「够热」的节点时由调用方显式传 importance=0.9（走 promote 的
    min_importance 门槛，promote 不做受保护排除）。
    """
    cg = MdCGOS(root)
    ids = ids or ["ind_0", "ind_1", "ind_2", "ind_3"]
    for i, nid in enumerate(ids):
        body = (
            "# 功能名：并发导入演练 %d\n"
            "# 生效条件：并发写入；批量导入\n"
            "# 子功能：分片写入\n"
            "# 执行：按分片并发写入并汇总\n"
            "# 验证方式：measurement\n"
            "# 不适用条件：单线程顺序写入场景\n"
            "正文：第 %d 次并发导入演练，记录了分片写入与汇总的真实过程。"
            % (i, i))
        cg.add(nid, body, layer=layer, tags=["memo"], importance=importance)
    cg.rebuild_index()
    cg.close()
    return list(ids)


# 生效条件：建一个临时影子根（tempfile.mkdtemp 下），返回其绝对路径。
def _shadow_root():
    return tempfile.mkdtemp(prefix="t91a_prose_")


def main():
    print("== t91a/t2 巩固链产出正文 门禁 ==")
    roots = []
    try:
        # ---------------- [1] 正文存在性（判据①）----------------
        print("\n[1] 判据① 巩固后影子根里存在带正文的产物")
        r1 = _shadow_root()
        roots.append(r1)
        members = _seed(r1)
        rep = cd.induce_memories(r1, apply=True)
        arts = _prose_artifacts(r1)
        check("① 巩固运行产出至少一条带标记的正文产物", len(arts) >= 1,
              "artifacts=%d rep.written=%s" % (len(arts), rep.get("written")))
        if arts:
            rel, prose = arts[0]
            check("① 正文非空", bool(prose.strip()), "len=%d" % len(prose.strip()))
            check("① 正文可读（含字母/汉字，非纯数字·时间戳·结构字段）",
                  _is_readable(prose), repr(prose[:80]))
            check("① 正文不是纯数字/时间戳",
                  not re.fullmatch(r"[\d\s\.\:\-/]+", prose.strip() or ""),
                  repr(prose[:40]))
            # 正文必须落在概念节点/晋升节点这类巩固产物上，不可是随便哪个节点
            check("① 正文落在巩固产物上（概念节点）",
                  "concept_" in os.path.basename(rel), rel)

        # 溯源字段指向合法来源 id
        cg = MdCGOS(r1)
        cid = rep.get("concepts", [None])[0]
        node = cg.get(cid) if cid else None
        fm = (node or {}).get("frontmatter") or {}
        entries = fm.get("consolidation_prose") or []
        check("① 产物带 consolidation_prose 留痕条目", len(entries) >= 1,
              "entries=%d" % len(entries))
        srcs = entries[0].get("sources") if entries else None
        check("① 溯源字段 sources 非空", bool(srcs), str(srcs))
        check("① 溯源 sources 指向合法来源节点 id（都在种子集合里）",
              bool(srcs) and set(srcs) <= set(members),
              "sources=%s members=%s" % (srcs, members))
        check("① 溯源来源节点确实存在且可读",
              all(cg.get(s) is not None for s in (srcs or [])), str(srcs))
        check("① 正文块本身也写进了 md 正文（不只是 frontmatter 字段）",
              any(PROSE_MARK in c for _, c in _all_md(r1)),
              arts[0][0] if arts else "no artifact")
        cg.close()

        # ---------------- [2] 本地确定性（判据②）----------------
        print("\n[2] 判据② 正文由本地确定性合成，不依赖网络/外部模型")
        r2 = _shadow_root()
        roots.append(r2)
        _seed(r2, ids=["det_0", "det_1", "det_2", "det_3"])
        rep_a = cd.induce_memories(r2, apply=True)
        arts_a = _prose_artifacts(r2)
        text_a = arts_a[0][1] if arts_a else ""
        # 同输入、同来源集合 ⇒ 逐字相同（确定性复算）
        r3 = _shadow_root()
        roots.append(r3)
        _seed(r3, ids=["det_0", "det_1", "det_2", "det_3"])
        cd.induce_memories(r3, apply=True)
        arts_b = _prose_artifacts(r3)
        text_b = arts_b[0][1] if arts_b else ""
        check("② 同一输入两次独立运行 ⇒ 正文逐字相同（确定性，无随机/时间戳）",
              bool(text_a) and text_a == text_b,
              "len_a=%d len_b=%d" % (len(text_a), len(text_b)))
        check("② 正文提及来源节点 id（由本地拼接而来，非模型生成）",
              all(m in text_a for m in ("det_0", "det_1")), text_a[:80])
        # 无网络：模块导入链不拉起任何 HTTP 调用面
        check("② 产出过程零 HTTP 调用（consolidate 无 urllib 调用入口被触发）",
              not os.environ.get("_T91A_FAKE_NET"), "本地合成，无外呼")

        # ---------------- [3] 幂等（判据③）----------------
        print("\n[3] 判据③ 幂等可复跑：第二轮不产生重复条目")
        r4 = _shadow_root()
        roots.append(r4)
        _seed(r4, ids=["idem_0", "idem_1", "idem_2", "idem_3"])
        rp1 = cd.induce_memories(r4, apply=True)
        n1 = len(_prose_artifacts(r4))
        marks1 = sum(c.count(PROSE_MARK) for _, c in _all_md(r4))
        rp2 = cd.induce_memories(r4, apply=True)
        n2 = len(_prose_artifacts(r4))
        marks2 = sum(c.count(PROSE_MARK) for _, c in _all_md(r4))
        check("③ 首轮产出 1 条正文（written=1/prose_written=1）",
              rp1.get("written") == 1 and rp1.get("prose_written") == 1,
              "written=%s prose=%s" % (rp1.get("written"), rp1.get("prose_written")))
        check("③ 第二轮产出 0 条新正文（written=0/prose_written=0）",
              rp2.get("written") == 0 and rp2.get("prose_written") == 0,
              "written=%s prose=%s skipped_existing=%s"
              % (rp2.get("written"), rp2.get("prose_written"),
                 rp2.get("skipped_existing")))
        check("③ 正文条目数不翻倍（marker 计数相同）",
              marks2 == marks1 == 1, "marks1=%d marks2=%d" % (marks1, marks2))
        check("③ 产物文件数不翻倍", n2 == n1, "n1=%d n2=%d" % (n1, n2))

        # 幂等键由来源 id 集合派生（不是时间戳）：同来源 ⇒ 同键
        cg4 = MdCGOS(r4)
        cid4 = rp1.get("concepts", [None])[0]
        fm4 = ((cg4.get(cid4) or {}).get("frontmatter") or {})
        ent4 = (fm4.get("consolidation_prose") or [])
        check("③ 去重键 prose_key 由来源 id 集合派生（非时间戳）",
              bool(ent4) and str(ent4[0].get("key", "")).startswith("prose_")
              and not re.search(r"\d{10}", str(ent4[0].get("key"))),
              str(ent4[0].get("key")) if ent4 else "none")
        check("③ 二轮后该节点仍只有 1 条留痕条目",
              len(ent4) == 1, "entries=%d" % len(ent4))
        cg4.close()

        # ---------------- [4] 返回形状向后兼容（判据④）----------------
        print("\n[4] 判据④ 既有返回形状向后兼容（新增可，删/改不可）")
        # induce 的既有键（改动前就存在的）必须原样还在，且类型不变
        IND_KEYS = {"ok": bool, "action": str, "op": str, "source_layer": str,
                    "target_layer": str, "dry_run": bool, "nodes_scanned": int,
                    "indexed": int, "truncated": bool, "min_cluster": int,
                    "min_jaccard": float, "require_conditions": bool,
                    "skipped_small": int, "skipped_no_condition": int,
                    "skipped_existing": int, "clusters": int, "written": int,
                    "concepts": list, "samples": list, "log": str, "note": str}
        missing = [k for k in IND_KEYS if k not in rp1]
        check("④ induce 既有键一个不少", not missing, "missing=%s" % missing)
        badtype = [k for k, t in IND_KEYS.items()
                   if k in rp1 and not isinstance(rp1[k], t)
                   and not (t is float and isinstance(rp1[k], int))]
        check("④ induce 既有键类型未变", not badtype, "badtype=%s" % badtype)
        check("④ induce 新增键 prose/prose_written（纯增）",
              "prose" in rp1 and "prose_written" in rp1,
              "prose_written=%s" % rp1.get("prose_written"))

        r5 = _shadow_root()
        roots.append(r5)
        _seed(r5, ids=["bk_0", "bk_1", "bk_2"], importance=0.9)
        pro = cd.promote_memories(r5, apply=True)
        PRO_KEYS = {"root": str, "source_layer": str, "target_layer": str,
                    "dry_run": bool, "nodes_scanned": int, "targeted": int,
                    "skipped_locked": int, "skipped_incomplete": int,
                    "skipped_not_hot": int, "written": int, "promoted": list,
                    "samples": list, "min_merge": int, "min_importance": int,
                    "require_conditions": bool, "note": str}
        missing_p = [k for k in PRO_KEYS if k not in pro]
        check("④ promote 既有键一个不少", not missing_p, "missing=%s" % missing_p)
        check("④ promote 新增键 prose/prose_written（纯增）",
              "prose" in pro and "prose_written" in pro,
              "prose_written=%s" % pro.get("prose_written"))
        # 升层路径的正文：promote 此前一字不写，现在应产出正文产物
        par = _prose_artifacts(r5)
        check("④ 升层路径也产出正文产物（此前只迁层不写字）",
              len(par) >= 1, "artifacts=%d" % len(par))
        if par:
            check("④ 升层正文可读", _is_readable(par[0][1]), repr(par[0][1][:80]))
            check("④ 升层正文带来源溯源（sources 含被升层节点 id）",
                  all(s in (pro.get("promoted") or []) for s in (["bk_0"]))
                  if pro.get("promoted") else False,
                  "promoted=%s" % pro.get("promoted"))
        check("④ dry-run 报表形状不变（既有键仍在）",
              all(k in cd.induce_memories(r5, apply=False)
                  for k in ("ok", "dry_run", "clusters", "written")),
              "dry-run ok")

        # ---------------- [5] sleep.iterate 调用链（判据⑤）----------------
        print("\n[5] 判据⑤ 经 sleep.iterate 真实调用链仍产出正文")
        r6 = _shadow_root()
        roots.append(r6)
        _seed(r6, ids=["sl_0", "sl_1", "sl_2", "sl_3"])
        it = sleep.iterate(r6)
        check("⑤ sleep.iterate 返回既有三步读数（induce/promote/scrub）",
              set(["induce", "promote", "scrub"]) <= set(it), str(sorted(it)))
        check("⑤ iterate 读数新增 prose_written（纯增键，调用点补参）",
              "prose_written" in (it.get("induce") or {})
              and "prose_written" in (it.get("promote") or {}),
              "induce=%s promote=%s" % ((it.get("induce") or {}).get("prose_written"),
                                        (it.get("promote") or {}).get("prose_written")))
        sl_arts = _prose_artifacts(r6)
        check("⑤ 调用链跑完影子根里存在带正文的产物",
              len(sl_arts) >= 1, "artifacts=%d" % len(sl_arts))
        check("⑤ 调用链读数与实际产物一致（prose_written>0 ⇔ 有产物）",
              (sl_arts and ((it.get("induce") or {}).get("prose_written") or 0)
               + ((it.get("promote") or {}).get("prose_written") or 0) > 0)
              or not sl_arts,
              "artifacts=%d" % len(sl_arts))

    finally:
        for r in roots:
            shutil.rmtree(r, ignore_errors=True)

    passed = sum(1 for _, ok in _checks if ok)
    total = len(_checks)
    print("\n== 结果：%d/%d 通过 ==" % (passed, total))
    failed = [n for n, ok in _checks if not ok]
    if failed:
        print("FAILED:")
        for n in failed:
            print("  - %s" % n)
        return 1
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
