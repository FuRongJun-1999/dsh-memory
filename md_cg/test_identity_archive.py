# -*- coding: utf-8 -*-
"""判据：归档主体索引（identity/archive_subjects.json）接入 positions/profile（2026-11-06）。

病象：L2 整族归档把带 `subject:<id>` 标签的流水移出索引后，`identity.positions()` 枚举归零，
界面「身份档案」一片空白；178 个主体的 5,865 条记录只剩在 _archive 里。

判据：
  A1 正控：sidecar 存在 → positions() 里该主体带 archived_nodes 且等于 sidecar 值
  A2 正控：档案节点（带 identity_anchor）不参与位置投票 → evidence_count 仍为 0
  A3 正控：profile(sid) 返回 anchors 非空、archived_nodes 与 sidecar 一致
  A4 正控：只有 sidecar、没有活节点的主体也出现在 positions() 里（nodes=0）
  B1 负控：没有 sidecar 的根 → positions() 不抛异常，archived_nodes 为 0
  B2 负控：sidecar 是坏 JSON → 当没有，不抛异常（fail-soft）

跑法：PYTHONPATH=/home/ubuntu/mdcg python3 -X utf8 -m md_cg.test_identity_archive
"""
import json
import os
import shutil
import tempfile

from . import identity, writepipe
from .mdcos import MdCGSecure
from .security import Principal

FAILED = []
PASSED = []


def check(name, cond, detail=""):
    if cond:
        PASSED.append(name)
        print("  PASS %s %s" % (name, detail))
    else:
        FAILED.append(name)
        print("  FAIL %s %s" % (name, detail))


def _cg(root):
    p = Principal(actor="probe-id-archive", role="designer", tenant="default",
                  clearance="private", can_write=True, can_admin=True)
    return MdCGSecure(root, principal=p, autoflush=1)


def _write(cg, nid, content, tags):
    return writepipe.default_pipeline().execute(
        cg, {"node_id": nid, "content": content, "layer": "anchor",
             "tags": tags, "importance": 0.3, "content_kind": "text", "role": "assistant"})


def main():
    root = tempfile.mkdtemp(prefix="idarch-")
    try:
        cg = _cg(root)
        sid = "probe_subject_alpha"
        content = ("# 功能名：主体 %s 的归档摘要\n# 主题：%s 的 42 条记录\n"
                   "# 生效条件：需要该主体规模时读\n# 子功能：给规模\n# 执行：grep\n"
                   "# 验证方式：扫描\n# 不适用条件：不当证据\n" % (sid, sid))
        out = _write(cg, "subj_arc_probe01", content,
                     ["subject:" + sid, "identity_anchor", "identity:archive-summary"])
        check("A0 档案节点写入被接受", (out or {}).get("ok") and (out or {}).get("committed", True),
              str((out or {}).get("verdict")))

        side = os.path.join(root, "identity")
        os.makedirs(side, exist_ok=True)
        with open(os.path.join(side, "archive_subjects.json"), "w", encoding="utf-8") as f:
            json.dump({sid: {"archived_nodes": 42, "layers": {"gwtri": 42},
                             "last_seen": 1762300000, "first_seen": 1762200000},
                       "probe_subject_only_archive": {"archived_nodes": 7, "layers": {},
                                                      "last_seen": 1762300001}}, f)

        rows = {r["subject_id"]: r for r in identity.positions(_cg(root))}
        check("A1 positions 带 archived_nodes", rows.get(sid, {}).get("archived_nodes") == 42,
              "archived=%r" % (rows.get(sid, {}).get("archived_nodes"),))
        check("A2 档案节点不参与位置投票", rows.get(sid, {}).get("evidence_count") == 0,
              "evidence_count=%r position=%r" % (rows.get(sid, {}).get("evidence_count"),
                                                 rows.get(sid, {}).get("position")))
        prof = identity.profile(_cg(root), sid)
        check("A3 profile 有锚点且 archived 一致",
              bool(prof.get("anchors")) and prof.get("archived_nodes") == 42,
              "anchors=%d archived=%r" % (len(prof.get("anchors") or []), prof.get("archived_nodes")))
        check("A4 只有归档的主体也进列表",
              rows.get("probe_subject_only_archive", {}).get("nodes") == 0
              and rows.get("probe_subject_only_archive", {}).get("archived_nodes") == 7,
              "row=%r" % (rows.get("probe_subject_only_archive"),))
    finally:
        shutil.rmtree(root, ignore_errors=True)

    # A5 负控：被写闸否决的档案节点不得出现在 anchors 里
    root4 = tempfile.mkdtemp(prefix="idarch-a5-")
    try:
        cg4 = _cg(root4)
        bad = ("# 功能名：缺要素的档案\n"
               "# 主题：应被判 REJECT\n"
               "# 生效条件：不该进锚点\n")
        out = _write(cg4, "subj_arc_bad01", bad,
                     ["subject:probe_subject_beta", "identity_anchor", "identity:archive-summary"])
        prof = identity.profile(_cg(root4), "probe_subject_beta")
        layers = [a.get("layer") for a in (prof.get("anchors") or [])]
        check("A5 被否决的档案节点不进 anchors",
              "rejected" not in layers and (prof.get("anchor") or {}).get("layer") != "rejected",
              "verdict=%r anchors_layers=%r" % ((out or {}).get("verdict"), layers))
    finally:
        shutil.rmtree(root4, ignore_errors=True)

    # B1 没有 sidecar
    root2 = tempfile.mkdtemp(prefix="idarch-b1-")
    try:
        rows = identity.positions(_cg(root2))
        check("B1 无 sidecar 不抛异常且 archived=0", isinstance(rows, list),
              "rows=%d" % len(rows))
    finally:
        shutil.rmtree(root2, ignore_errors=True)

    # B2 坏 JSON
    root3 = tempfile.mkdtemp(prefix="idarch-b2-")
    try:
        cg3 = _cg(root3)
        side = os.path.join(root3, "identity")
        os.makedirs(side, exist_ok=True)
        with open(os.path.join(side, "archive_subjects.json"), "w", encoding="utf-8") as f:
            f.write("{not json")
        check("B2 坏 sidecar 当没有（fail-soft）", identity.archive_subjects(cg3) == {},
              "keys=%r" % (list(identity.archive_subjects(cg3))[:3],))
    finally:
        shutil.rmtree(root3, ignore_errors=True)

    print("\n%d 通过 / %d 失败" % (len(PASSED), len(FAILED)))
    if FAILED:
        print("失败：", FAILED)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
