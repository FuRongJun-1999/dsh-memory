# -*- coding: utf-8 -*-
"""md_cg · Pi⑦② read 截断 + 续读提示（_clip_text / _node_view / schema 落点）

验收三件事：
① 单次 read 返回受「2000 行 / 50KB」双阈值约束，且**不静默丢内容**——
   截断必带 total_lines / total_bytes / next_offset / note；
② 续读按 offset 连续取回可拼回原文（不丢不重，可裁决的等价性判据）；
③ 小内容行为兼容——旧四键（id/path/frontmatter/content）不丢、content 原样；
   验证态 `verification_state` 为**有意的 additive 透出**（不参与排序），
   故 B1 断言「旧键 ⊆ 新键 ∧ 验证态在场」而非「键集逐一相等」。
   真源：protocol.py 的 read.node.required 已把 `verification_state` 列为必需键。

运行：python -m md_cg.test_read_clip
"""

import os
import sys

from .mcp_server import KERNEL_TOOLS, READ_MAX_BYTES, READ_MAX_LINES, \
    _cg_call, _clip_text, _node_view

_ok = 0
_bad = []


def check(name, cond, detail=""):
    global _ok
    if cond:
        _ok += 1
        print(f"  [ok] {name}" + (f"  · {detail}" if detail else ""))
    else:
        _bad.append(name)
        print(f"  [FAIL] {name}  · {detail}")


class _FakeCG:
    """只实现 read 面所需的最小取节点契约。"""

    def __init__(self, nodes):
        self._nodes = nodes

    def get(self, nid, *a, **k):
        return self._nodes.get(nid)


def main():
    print("[A] _clip_text 双阈值与续读语义")
    small = "第一行\n第二行\n第三行"
    c = _clip_text(small)
    check("A1 小文本原样返回（note 空串、无截断位点）",
          c["text"] == small and c["truncated"] is False
          and c["next_offset"] is None and c["total_lines"] == 3
          and c["note"] == "", str(c)[:160])

    many = "\n".join(f"line-{i:05d}" for i in range(READ_MAX_LINES + 500))
    c = _clip_text(many)
    check("A2 行数上限：超 2000 行截断且给出续读位点",
          c["truncated"] is True and c["returned_lines"] == READ_MAX_LINES
          and c["next_offset"] == READ_MAX_LINES + 1
          and str(READ_MAX_LINES) in c["note"], c["note"])

    wide = "\n".join("x" * 60 for _ in range(3000))   # 约定 180KB > 50KB
    c = _clip_text(wide)
    check("A3 字节上限生效（行未满 2000 但字节先到顶）",
          c["truncated"] is True and c["returned_lines"] < READ_MAX_LINES
          and len(c["text"].encode("utf-8")) <= READ_MAX_BYTES
          and str(READ_MAX_BYTES) in c["note"], f"{c['returned_lines']}行/{c['total_bytes']}B")

    # 续读拼接等价性：按 next_offset 连续取回，拼回必须与原文逐字一致
    got, off, hops = [], 0, 0
    while True:
        c = _clip_text(many, offset=off)
        got.append(c["text"])
        hops += 1
        if not c["truncated"]:
            break
        off = c["next_offset"]
        if hops > 10:
            break
    check("A4 续读拼接 == 原文（不丢不重）",
          "\n".join(got) == many and hops == 2, f"hops={hops}")

    c = _clip_text("a\nb", offset=99)
    check("A5 offset 越界：返回空并如实说明（不假装有内容）",
          c["text"] == "" and c["truncated"] is False and "超出总行数" in c["note"],
          c["note"])

    c = _clip_text("y" * (READ_MAX_BYTES + 100))
    check("A6 单行超字节上限也保底返回一行（不返回空）",
          c["returned_lines"] == 1 and c["truncated"] is False
          and len(c["text"]) == READ_MAX_BYTES + 100, str(c["returned_lines"]))

    print("[B] _node_view 兼容与截断字段")
    node = {"id": "n1", "path": "/p/n1.md", "frontmatter": {"layer": "knowledge"},
            "content": "短内容"}
    v = _node_view(node)
    check("B1 旧四键不丢（零回归）+ 验证态 additive 透出",
          {"id", "path", "frontmatter", "content"} <= set(v)
          and v["content"] == "短内容"
          and v["verification_state"] == "unverified", str(sorted(v)))
    check("B2 空节点维持 None（旧契约）", _node_view(None) is None)

    big = dict(node, content=many)
    v = _node_view(big)
    check("B3 大节点截断 + 审计字段（truncated/next_offset/note）",
          v["truncated"] is True and v["next_offset"] == READ_MAX_LINES + 1
          and v["content_lines"] == READ_MAX_LINES + 500
          and v["content"].split("\n")[-1] == f"line-{READ_MAX_LINES - 1:05d}",
          str({k: v[k] for k in ("truncated", "next_offset", "content_lines")}))
    v2 = _node_view(big, offset=v["next_offset"])
    check("B4 按 next_offset 续读可取回尾部且拼回原文",
          "\n".join([v["content"], v2["content"]]) == many
          and v2["offset"] == READ_MAX_LINES + 1, str(v2["offset"]))

    print("[C] 工具面落点（schema + 分发透传）")
    cg = next(t for t in KERNEL_TOOLS if t["name"] == "cg")
    props = cg["inputSchema"]["properties"]
    check("C1 cg schema 暴露 offset 且描述含续读语义",
          props["offset"]["type"] == "integer" and "next_offset" in props["offset"]["description"])
    check("C2 read 面描述声明截断与续读（调用方可知情）",
          "next_offset" in cg["description"] and "截断" in cg["description"])

    fcg = _FakeCG({"n1": node})
    out = _cg_call(fcg, {"op": "read", "node_id": "n1"})
    check("C3 未传 offset：行为与旧版一致",
          out["content"] == "短内容" and "truncated" not in out, str(out)[:160])
    fcg = _FakeCG({"n1": big})
    out = _cg_call(fcg, {"op": "read", "node_id": "n1", "offset": READ_MAX_LINES + 1})
    check("C4 offset 经 _cg_call 透传到节点视图（真实续读通路）",
          out["offset"] == READ_MAX_LINES + 1 and out["truncated"] is False
          and out["content"].startswith(f"line-{READ_MAX_LINES:05d}")
          and out["content"].endswith("line-02499"), str(out["offset"]))

    print(f"\n结果：{_ok} 通过 / {len(_bad)} 失败")
    if _bad:
        print("失败项：" + "、".join(_bad))
    return 1 if _bad else 0


if __name__ == "__main__":
    sys.exit(main())
