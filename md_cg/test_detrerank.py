# -*- coding: utf-8 -*-
"""确定性重排（detrerank）守卫。

钉三件事：
  1. 四信号可数且确定（同输入同输出）；
  2. **无模型分**——模块源码不得出现 embedding/similarity/模型调用；
  3. **时钟显式**——rerank 必须由调用方传 now，函数内不得取 time.time()。
"""
from __future__ import annotations

import inspect
import io
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)

from md_cg import detrerank as D  # noqa: E402

FAILS = []
NOW = 1_800_000_000.0


def ok(cond, name, detail=""):
    if cond:
        print("  PASS " + name)
    else:
        print("  FAIL " + name + "  " + str(detail)[:200])
        FAILS.append(name)


def _code_only(path):
    """把源码解析成 AST 后**去掉 docstring**再 unparse —— 只留代码。

    为什么需要：本模块的说明文字会提到「不得出现 embedding / time.time」这类词，
    直接 grep 源码会把**守卫自己的说明**判成违规（假红）。守卫要盯实现，不是措辞。
    """
    import ast
    tree = ast.parse(io.open(path, encoding="utf-8").read())
    for nd in ast.walk(tree):
        body = getattr(nd, "body", None)
        if (isinstance(body, list) and body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)):
            body[0] = ast.Pass()
    return ast.unparse(tree)


def node(nid, content, tags=None, created_at=None, edges=None, layer="knowledge", session=None):
    fm = {"layer": layer, "tags": tags or []}
    if created_at is not None:
        fm["created_at"] = created_at
    if edges is not None:
        fm["edges"] = edges
    if session:
        fm["session"] = session
    return {"id": nid, "content": content, "frontmatter": fm}


def main():
    print("=" * 66)
    print("确定性重排（detrerank）")
    print("=" * 66)
    q = "灯箱 报价 制作"
    terms = D._terms(q)
    ok(terms == ["灯箱", "报价", "制作"], "D1 分词确定", terms)

    a = node("a", "灯箱已有报价，尚未安排制作", ["灯箱"], created_at=NOW - 3600)
    b = node("b", "无关内容", [], created_at=NOW - 86400 * 365)
    sa = D.signals(a, terms, NOW)
    sb = D.signals(b, terms, NOW)
    ok(sa["lexical"] == 3 and sb["lexical"] == 0,
       "D2 词法信号 = query 词命中数", (sa["lexical"], sb["lexical"]))
    ok(0.0 < sa["temporal"] <= 1.0, "D3 时间信号落在 (0,1]", sa["temporal"])
    ok(sb["temporal"] < sa["temporal"], "D4 旧条目时间分更低", (sa["temporal"], sb["temporal"]))

    n_edge = node("e", "灯箱 报价", ["灯箱"], created_at=NOW - 10,
                  edges=[{"target": "x", "relation_type": "causal"}])
    se = D.signals(n_edge, terms, NOW)
    ok(se["interaction"] == 1, "D5 交互信号 = 出边数（真的发生过作用）", se["interaction"])

    n_same = node("s", "灯箱", ["灯箱"], created_at=NOW, session="sess-1")
    ss = D.signals(n_same, terms, NOW, session="sess-1")
    sn = D.signals(n_same, terms, NOW, session="sess-2")
    ok(ss["spatial"] > sn["spatial"], "D6 空间信号含同会话加成", (ss["spatial"], sn["spatial"]))

    # D7 全序 + 幂等：同输入两次结果逐位相同
    items = [(a, 0.9, {}, []), (b, 0.9, {}, []), (n_edge, 0.9, {}, [])]
    r1 = D.rerank(items, q, NOW)
    r2 = D.rerank(items, q, NOW)
    ok([x[0][0]["id"] for x in r1] == [x[0][0]["id"] for x in r2], "D7 同输入同输出（可回放）")
    ok([x[0][0]["id"] for x in r1][0] != "b", "D8 词法强的排在前面", [x[0][0]["id"] for x in r1])

    # D9 分数相同按 id 字典序（全序兜底）
    twins = [(node("z", "同样内容", []), 0.5, {}, []),
             (node("a", "同样内容", []), 0.5, {}, [])]
    rt = D.rerank(twins, q, NOW)
    ok([x[0][0]["id"] for x in rt] == ["a", "z"], "D9 同分按 id 字典序",
       [x[0][0]["id"] for x in rt])

    # D10/D11b：只扫**代码**（去 docstring/注释）——说明文字里出现这些词是允许的，
    # 守卫要盯的是「实现里有没有真的引入模型分/隐式取时钟」。
    code = _code_only(os.path.join(_REPO, "md_cg", "detrerank.py")).lower()
    banned = [w for w in ("embedding", "cosine", "similarity", "openai", "model.")
              if w in code]
    ok(not banned, "D10 代码内无模型分/相似度项", banned)

    sig = inspect.signature(D.rerank)
    ok("now" in sig.parameters, "D11a rerank 形参含 now（时钟显式）", list(sig.parameters))
    ok("time.time" not in code and "datetime.now" not in code,
       "D11b 代码内不取系统时钟")

    # D12 权重是固定常量（改值必须走评审）
    ok(isinstance(D.WEIGHTS, dict) and set(D.WEIGHTS) == {"lexical", "interaction", "spatial", "temporal"},
       "D12 四信号权重常量齐全", D.WEIGHTS)

    # ---------- 端到端：接线层（recall 的 MDCG_DET_RERANK 开关） ----------
    import tempfile
    from md_cg.mdcos import MdCGOS
    root = tempfile.mkdtemp(prefix="det_e2e_")
    g2 = MdCGOS(root, actor="test")
    ccg = ("# 功能名：{n}\n# 生效条件：{c}\n# 子功能：s\n# 执行：e\n"
           "# 验证方式：test\n# 不适用条件：无\n\n{b}\n")
    g2.add("a", ccg.format(n="灯箱报价记录", c="灯箱 报价",
                           b="灯箱 已有报价 制作 待安排"), tags=["灯箱"])
    g2.add("b", ccg.format(n="灯箱制作安排", c="灯箱 制作",
                           b="制作 安排 灯箱"), tags=["灯箱"])
    g2.add("c", ccg.format(n="其它项目", c="别的",
                           b="别的内容 灯箱 提了一句"), tags=["其它"])
    os.environ["MDCG_DET_RERANK"] = "1"
    try:
        p1 = g2.recall("灯箱 报价 制作", budget_tokens=3000, k=10)
        ids1 = [e["id"] for e in p1["pack"]]
        ok(p1["meta"].get("det_reranked") is True, "E1 开启后 meta.det_reranked=True")
        ok(all("det" in e for e in p1["pack"]), "E2 每条带四信号读数（可审计）")
        ok(ids1[0] == "a", "E3 词法最强的排第一", ids1)
        sig0 = p1["pack"][0]["det"]["signals"]
        ok(set(sig0) == {"lexical", "interaction", "spatial", "temporal"},
           "E4 信号四键齐全", sig0)
        p2 = g2.recall("灯箱 报价 制作", budget_tokens=3000, k=10)
        ok([e["id"] for e in p2["pack"]] == ids1, "E5 同输入同输出（可回放）")
    finally:
        os.environ.pop("MDCG_DET_RERANK", None)
    p3 = g2.recall("灯箱 报价 制作", budget_tokens=3000, k=10)
    ok(p3["meta"].get("det_reranked") in (False, None), "E6 缺省关闭")
    ok(not any("det" in e for e in p3["pack"]), "E7 关闭时不注入 det 读数")

    print()
    print("detrerank：%d 项失败" % len(FAILS) if FAILS else "detrerank：全部通过")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())