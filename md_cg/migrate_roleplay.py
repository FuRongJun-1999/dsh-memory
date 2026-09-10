# -*- coding: utf-8 -*-
"""md_cg · 角色扮演 / 互维数据迁移（LIB 本地库 → 认知图）

背景（2026-09-10 决定）
------------------------
  · `src/lib/roleplay_web.ts`、`src/lib/mutual.ts` 归 **LIB 本地库**；
  · 其数据改由 **认知图**（md_cg = 唯一真源）承载；
  · 本脚本把历史数据一次性迁入认知图，迁移后读写都走 md_cg。

数据来源与映射
--------------
  角色扮演（`--data-dir <roleplay_data>`）
    roleplay/_roles.json                       → role 节点（layer=knowledge）
      · <role>.memory_items                     → layer=knowledge
      · <role>.anchors_items                    → layer=self
      · <role>.values_items                     → layer=structural
    transcripts/<role>__<client>.jsonl         → 逐轮 turn 节点（layer=contextual）

  互维（`--mutual-dir <~/.lingxu_net>`，可选）
    tasks/result-<id>.json                     → 裁决节点（layer=contextual，带 verdict）
    tasks/task-<id>.json（无 result 时）        → 待验证节点（layer=contextual）

用法
----
    python -m md_cg.migrate_roleplay --data-dir <roleplay_data> --root <md_root> \
        [--mutual-dir <~/.lingxu_net>] [--tenant default] [--actor dsh-memory] \
        [--clearance private] [--dry-run]

身份（--tenant/--actor）：私有内容按 (tenant, actor) 派生 DEK 加密，换身份读
同一条也会「不可读即不存在」。默认与 DSH 插件对齐（tenant=default /
actor=dsh-memory），迁移后插件才读得到。

幂等：按 id 原子覆盖写（override=True），可反复执行。
校验：写入后按 id 回读，逐字段比对 content / layer / tags。
"""
from __future__ import annotations

import io
import json
import os
import sys
import time

from .mdcos import MdCGSecure
from .security import Principal, DEFAULT_SENSITIVITY

#: 三导入 kind → 认知图层（与 roleplay_web.ts 的注释一致）。
ITEM_LAYER = {"memory": "knowledge", "anchors": "self", "values": "structural"}
#: 转录角色 → turn 标签。
TURN_ROLE = {"user": "user", "bot": "assistant", "assistant": "assistant"}


# --------------------------------------------------------------------------
# 读取源数据
# --------------------------------------------------------------------------

def _read_json(path, default):
    try:
        with io.open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def load_roles(roleplay_dir):
    """读取 `_roles.json`，归一化根/嵌套两种格式 → {role_id: meta}。"""
    raw = _read_json(os.path.join(roleplay_dir, "_roles.json"), {})
    if isinstance(raw, dict) and isinstance(raw.get("meta"), dict):
        raw = raw["meta"]
    return raw if isinstance(raw, dict) else {}


def load_transcripts(transcripts_dir):
    """读取全部 `*.jsonl` 转录 → [(role_id, client_id, idx, entry)]。"""
    out = []
    if not os.path.isdir(transcripts_dir):
        return out
    for name in sorted(os.listdir(transcripts_dir)):
        if not name.endswith(".jsonl"):
            continue
        stem = name[:-len(".jsonl")]
        role_id, _, client_id = stem.partition("__")
        client_id = client_id or "shared"
        path = os.path.join(transcripts_dir, name)
        idx = 0
        try:
            with io.open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except ValueError:
                        continue
                    out.append((role_id, client_id, idx, entry))
                    idx += 1
        except OSError:
            continue
    return out


def load_mutual(mutual_dir):
    """读取互维任务/裁决 → [(task_id, claim, result|None)]。"""
    out, seen = [], set()
    tasks_dir = os.path.join(mutual_dir, "tasks") if mutual_dir else ""
    if not tasks_dir or not os.path.isdir(tasks_dir):
        return out
    for name in sorted(os.listdir(tasks_dir)):
        if not name.startswith("result-") or not name.endswith(".json"):
            continue
        tid = name[len("result-"):-len(".json")]
        result = _read_json(os.path.join(tasks_dir, name), None)
        task = _read_json(os.path.join(tasks_dir, f"task-{tid}.json"), {}) or {}
        claim = ((task.get("payload") or {}).get("claim") or "").strip()
        out.append((tid, claim, result))
        seen.add(tid)
    for name in sorted(os.listdir(tasks_dir)):
        if not name.startswith("task-") or not name.endswith(".json"):
            continue
        tid = name[len("task-"):-len(".json")]
        if tid in seen:
            continue
        task = _read_json(os.path.join(tasks_dir, name), {}) or {}
        claim = ((task.get("payload") or {}).get("claim") or "").strip()
        out.append((tid, claim, None))
    return out


# --------------------------------------------------------------------------
# 迁移
# --------------------------------------------------------------------------

def _role_content(role_id, meta):
    name = meta.get("name") or role_id
    lines = [f"# 角色 {name}（{role_id}）"]
    for key in ("scenario", "first_mes", "nsfw"):
        if meta.get(key) not in (None, "", False):
            lines.append(f"- {key}: {meta[key]}")
    return "\n".join(lines)


def migrate(data_dir, root, mutual_dir=None, dry_run=False,
            clearance="private", tenant="default", actor="dsh-memory", verbose=True):
    """把角色扮演 / 互维数据迁入认知图。

    **身份必须与调用方一致**：私有内容按 (tenant, actor) 派生 DEK 加密，
    换身份读同一条也会「不可读即不存在」。默认 tenant=default /
    actor=dsh-memory，与 DSH 插件 `config.mdcg.actor` 及 MCP 默认租户对齐；
    迁移后用插件读取才看得到。
    """
    roleplay_dir = os.path.join(data_dir, "roleplay")
    transcripts_dir = os.path.join(data_dir, "transcripts")
    roles = load_roles(roleplay_dir)
    turns = load_transcripts(transcripts_dir)
    mutual = load_mutual(mutual_dir) if mutual_dir else []

    principal = Principal(tenant=tenant, actor=actor,
                          clearance=clearance, can_write=True, can_admin=True)
    cg = MdCGSecure(root, principal=principal, autoflush=500)

    plans = []  # (node_id, content, layer, tags, importance, created_at, basis)

    # 1) 角色定义
    for role_id, meta in roles.items():
        if not isinstance(meta, dict):
            continue
        plans.append((
            f"roleplay_role_{role_id}", _role_content(role_id, meta),
            "knowledge", ["roleplay", f"role:{role_id}", "roleplay:role"],
            0.7, float(meta.get("created_at") or 0), "other",
        ))
        # 2) 三导入项
        for kind, layer in ITEM_LAYER.items():
            items = meta.get(f"{kind}_items") or []
            if not isinstance(items, list):
                continue
            for i, it in enumerate(items):
                content = it.get("content") if isinstance(it, dict) else str(it)
                if not content:
                    continue
                plans.append((
                    f"roleplay_{role_id}_{kind}_{i}", str(content), layer,
                    ["roleplay", f"role:{role_id}", f"roleplay:{kind}"],
                    0.6, float(meta.get("created_at") or 0), "other",
                ))

    # 3) 对话转录
    for role_id, client_id, idx, entry in turns:
        if not isinstance(entry, dict):
            continue
        text = (entry.get("text") or "").strip()
        if not text:
            continue
        who = TURN_ROLE.get(str(entry.get("role") or "user"), "user")
        ts = entry.get("time")
        created = float(ts) / 1000.0 if isinstance(ts, (int, float)) else 0.0
        plans.append((
            f"roleplay_turn_{role_id}_{client_id}_{idx}", text, "contextual",
            ["roleplay", f"role:{role_id}", f"session:{client_id}", f"turn:{who}"],
            0.4, created, "other",
        ))

    # 4) 互维任务/裁决
    for tid, claim, result in mutual:
        if result and isinstance(result, dict):
            verdict = str(result.get("verdict") or "")
            w = result.get("whitebox") or {}
            body = (f"[互维裁决 task={tid}] verdict={verdict}\n"
                    f"claim: {claim}\n"
                    f"白箱: {w.get('judgment', '')}（best={w.get('best', '')}）")
            basis = "test" if verdict == "pass" else "other"
            created = float(result.get("at") or 0)
            tags = ["mutual", f"task:{tid}", f"verdict:{verdict}"]
        else:
            if not claim:
                continue
            body = f"[互维待验证 task={tid}] {claim}"
            basis, created, tags = "other", 0.0, ["mutual", f"task:{tid}", "state:pending"]
        plans.append((f"mutual_task_{tid}", body, "contextual", tags, 0.5, created, basis))

    # ---------- 写入 ----------
    t0 = time.time()
    if not dry_run:
        for nid, content, layer, tags, importance, created_at, basis in plans:
            cg.add(
                nid, content, layer=layer, override=True,
                sensitivity=DEFAULT_SENSITIVITY if clearance != "private" else "private",
                tags=tags, importance=importance, created_at=created_at,
                verification_basis=basis, ccg_exempt=True,
                migrated_from="lingxu_net" if nid.startswith("mutual_") else "roleplay_data",
            )
        cg.flush()

    # ---------- 回读校验 ----------
    bad = []
    if not dry_run:
        for nid, content, layer, tags, _imp, _ts, _basis in plans:
            got = cg.get(nid)
            if not got:
                bad.append((nid, "missing"))
                continue
            fm = got.get("frontmatter") or {}
            if (got.get("content") or "").rstrip("\n") != content.rstrip("\n"):
                bad.append((nid, "content"))
            elif (fm.get("layer") or "") != layer:
                bad.append((nid, "layer"))
            elif list(fm.get("tags") or []) != list(tags):
                bad.append((nid, "tags"))

    report = {
        "data_dir": data_dir, "root": root, "mutual_dir": mutual_dir,
        "dry_run": dry_run,
        "roles": len(roles), "turns": len(turns), "mutual": len(mutual),
        "planned_nodes": len(plans),
        "written": 0 if dry_run else len(plans),
        "field_mismatches": len(bad), "samples": bad[:5],
        "md_nodes_total": len(cg.index["nodes"]),
        "elapsed_sec": round(time.time() - t0, 1),
    }
    if verbose:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    cg.close()
    return report


def main(argv):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

    def opt(name, default=None):
        return argv[argv.index(name) + 1] if name in argv else default

    data_dir = opt("--data-dir")
    root = opt("--root")
    if not data_dir or not root:
        print(__doc__)
        return 1
    migrate(data_dir, root, mutual_dir=opt("--mutual-dir"),
            dry_run="--dry-run" in argv, clearance=opt("--clearance", "private"),
            tenant=opt("--tenant", "default"), actor=opt("--actor", "dsh-memory"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
