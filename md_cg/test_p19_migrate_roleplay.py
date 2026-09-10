# -*- coding: utf-8 -*-
"""P19：角色扮演 / 互维数据迁移到认知图（`migrate_roleplay.py`）。

用合成数据验证：读取归一化 → 落图（层/标签/内容）→ 回读等价 → 幂等。
不依赖真实 roleplay_data / ~/.lingxu_net。
"""
import io
import json
import os
import shutil
import tempfile

from . import migrate_roleplay as M
from .mdcos import MdCGSecure
from .security import Principal

PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}" + (f"  · {detail}" if detail else ""))
    else:
        FAIL += 1
        print(f"  [FAIL] {name}" + (f"  · {detail}" if detail else ""))


def _write(path, obj_or_text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with io.open(path, "w", encoding="utf-8") as f:
        if isinstance(obj_or_text, str):
            f.write(obj_or_text)
        else:
            json.dump(obj_or_text, f, ensure_ascii=False)


def _build_fixture(base):
    data = os.path.join(base, "roleplay_data")
    _write(os.path.join(data, "roleplay", "_roles.json"), {
        "alice": {
            "name": "Alice", "scenario": "雨夜咖啡馆", "first_mes": "欢迎光临",
            "memory_items": [{"content": "Alice 喜欢猫"}],
            "anchors_items": [{"content": "Alice 永不背叛"}],
            "values_items": [{"content": "诚实优先"}],
        },
        "bob": {"name": "Bob", "scenario": ""},
    })
    lines = [
        json.dumps({"time": 1700000000000, "role": "user", "text": "你好"},
                   ensure_ascii=False),
        json.dumps({"time": 1700000001000, "role": "bot", "text": "你好呀",
                    "route": "self"}, ensure_ascii=False),
    ]
    _write(os.path.join(data, "transcripts", "alice__shared.jsonl"),
           "\n".join(lines) + "\n")

    net = os.path.join(base, "lingxu_net", "tasks")
    _write(os.path.join(net, "task-t1.json"),
           {"id": "t1", "payload": {"claim": "地球是圆的", "source_ref": "wiki"}})
    _write(os.path.join(net, "result-t1.json"),
           {"task_id": "t1", "verdict": "pass", "at": 1700000002,
            "whitebox": {"judgment": "采纳", "best": "地球是圆的"}})
    _write(os.path.join(net, "task-t2.json"),
           {"id": "t2", "payload": {"claim": "月亮是奶酪做的"}})
    return data, os.path.dirname(net)


def main():
    base = tempfile.mkdtemp(prefix="mdcg_p19_")
    try:
        data, net = _build_fixture(base)
        root = os.path.join(base, "mdcg_root")

        # ---------- A. 读取归一化 ----------
        print("\n[A] 源数据读取与归一化")
        roles = M.load_roles(os.path.join(data, "roleplay"))
        check("A1 角色字典", set(roles) == {"alice", "bob"})
        turns = M.load_transcripts(os.path.join(data, "transcripts"))
        check("A2 转录逐行读取", len(turns) == 2 and turns[0][0] == "alice"
              and turns[0][1] == "shared")
        mut = M.load_mutual(net)
        check("A3 互维任务/裁决配对", len(mut) == 2
              and any(m[0] == "t1" and m[2] for m in mut)
              and any(m[0] == "t2" and m[2] is None for m in mut))

        # ---------- B. 迁移落图 ----------
        print("\n[B] 迁移落图 + 回读等价")
        rep = M.migrate(data, root, mutual_dir=net, verbose=False)
        # 角色 2 + 三导入 3 + 转录 2 + 互维 2 = 9
        check("B1 计划节点数", rep["planned_nodes"] == 9, str(rep["planned_nodes"]))
        check("B2 无字段失配", rep["field_mismatches"] == 0,
              str(rep["samples"]))
        # 回读必须用同一 (tenant, actor)：私有内容按身份派生 DEK 加密，
        # 换身份读取视为「不可读即不存在」（security.py 的物理/逻辑隔离）。
        cg = MdCGSecure(root, principal=Principal(
            tenant="default", actor="dsh-memory", clearance="private",
            can_write=True, can_admin=True))
        role = cg.get("roleplay_role_alice")
        check("B3 角色节点落 knowledge 层",
              bool(role) and role["frontmatter"].get("layer") == "knowledge")
        mem = cg.get("roleplay_alice_memory_0")
        anchor = cg.get("roleplay_alice_anchors_0")
        value = cg.get("roleplay_alice_values_0")
        check("B4 三导入映射到 knowledge/self/structural",
              mem["frontmatter"]["layer"] == "knowledge"
              and anchor["frontmatter"]["layer"] == "self"
              and value["frontmatter"]["layer"] == "structural")
        turn = cg.get("roleplay_turn_alice_shared_1")
        check("B5 转录落 contextual 层且保留 turn 标签",
              bool(turn) and turn["frontmatter"]["layer"] == "contextual"
              and "turn:assistant" in turn["frontmatter"]["tags"])
        task = cg.get("mutual_task_t1")
        check("B6 互维裁决落图且 basis=test（强依据）",
              bool(task) and task["frontmatter"].get("verification_basis") == "test")
        pending = cg.get("mutual_task_t2")
        check("B7 无裁决任务标记 pending",
              bool(pending) and "state:pending" in pending["frontmatter"]["tags"])
        cg.close()

        # ---------- C. 幂等 ----------
        print("\n[C] 幂等（重复迁移不产生重复节点）")
        rep2 = M.migrate(data, root, mutual_dir=net, verbose=False)
        cg = MdCGSecure(root, principal=Principal(
            tenant="default", actor="dsh-memory", clearance="private",
            can_write=True, can_admin=True))
        check("C1 重复迁移节点总数不变", rep2["md_nodes_total"] == rep["md_nodes_total"],
              f'{rep["md_nodes_total"]} → {rep2["md_nodes_total"]}')
        check("C2 重复迁移仍无失配", rep2["field_mismatches"] == 0)
        cg.close()

        # ---------- D. dry-run ----------
        print("\n[D] dry-run 不落盘")
        root2 = os.path.join(base, "mdcg_root_dry")
        repd = M.migrate(data, root2, mutual_dir=net, dry_run=True, verbose=False)
        check("D1 dry-run 报告计划数但不写入",
              repd["planned_nodes"] == 9 and repd["written"] == 0
              and repd["md_nodes_total"] == 0)
    finally:
        shutil.rmtree(base, ignore_errors=True)

    print(f"\n==== P19 结果：{PASS} 通过 / {FAIL} 失败 ====")
    return FAIL


if __name__ == "__main__":
    import sys
    sys.exit(1 if main() else 0)
