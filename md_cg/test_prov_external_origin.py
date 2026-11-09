# 判据：provenance.check 把「来源标签端点」与「真悬空端点」分开计数。
# 生效条件：给定 cg（含 root 与 index.nodes）与台账 _link.jsonl 时运行。
# 验证方式：正控——来源标签边的 external_origin_count 计数、dangling_count 为 0；
#           负控——把来源标签换成同前缀族的幽灵 id，必须落回 dangling_count。
import io
import json
import os
import tempfile

from . import provenance


class FakeCG:
    def __init__(self, root, nodes):
        self.root = root
        self.index = {"nodes": {n: {"layer": "knowledge"} for n in nodes}}


def _write(root, rows):
    p = os.path.join(root, "_link.jsonl")
    with io.open(p, "w", encoding="utf-8", newline="\n") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")


def main():
    ok = 0
    bad = []
    with tempfile.TemporaryDirectory() as root:
        nodes = ["mn_alpha", "mn_beta"]
        cg = FakeCG(root, nodes)
        # 正控：parent 是来源标签（不在本库前缀族里）
        _write(root, [
            {"schema": 1, "child": "mn_alpha", "parent": "mcp_memory_add", "rel": "derived_from"},
            {"schema": 1, "child": "mn_beta", "parent": "gateway-profile:profile:偏好:工作模式", "rel": "derived_from"},
        ])
        rep = provenance.check(cg, include_index=False)
        if rep["external_origin_count"] == 2 and rep["dangling_count"] == 0 and rep["ok"]:
            ok += 1
        else:
            bad.append(("正控 来源标签不算悬空", rep.get("external_origin_count"), rep.get("dangling_count"), rep.get("ok")))
        # 负控：同前缀族的幽灵 id 必须算悬空
        _write(root, [
            {"schema": 1, "child": "mn_ghost", "parent": "mcp_memory_add", "rel": "derived_from"},
        ])
        rep2 = provenance.check(cg, include_index=False)
        if rep2["dangling_count"] == 1 and rep2["external_origin_count"] == 0 and not rep2["ok"]:
            ok += 1
        else:
            bad.append(("负控 mn_ 幽灵要算悬空", rep2.get("external_origin_count"), rep2.get("dangling_count"), rep2.get("ok")))
        # 负控：全部端点都在索引里 → 两个计数都为 0
        _write(root, [{"schema": 1, "child": "mn_alpha", "parent": "mn_beta", "rel": "derived_from"}])
        rep3 = provenance.check(cg, include_index=False)
        if rep3["dangling_count"] == 0 and rep3["external_origin_count"] == 0 and rep3["ok"]:
            ok += 1
        else:
            bad.append(("负控 完好边", rep3.get("external_origin_count"), rep3.get("dangling_count")))
    print("通过 %d / %d" % (ok, 3))
    for b in bad:
        print("FAIL", b)
    print("RESULT", "PASS" if not bad else "FAIL")


if __name__ == "__main__":
    main()
