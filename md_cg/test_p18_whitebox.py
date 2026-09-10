# -*- coding: utf-8 -*-
"""P18：md_cg 显式调用白箱 + 能力验证（`whitebox.py`）。

背景（2026-09-10）：白箱 LLM provider 已下线，AEIS 降为**能力库**；
改由 md_cg 通过 `cg(op=whitebox)` 显式调用白箱，并验证其：
  · 编码能力（remember → 追问命中）
  · 已有知识回答能力（route=self 且回答非空）

本测试不依赖真实 AEIS（用 FakeClient 注入），验证协议/判定/留痕/分发逻辑。
"""
import os

from . import whitebox

PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}" + (f"  · {detail}" if detail else ""))
    else:
        FAIL += 1
        print(f"  [FAIL] {name}" + (f"  · {detail}" if detail else ""))


# --------------------------------------------------------------------------
# 测试替身
# --------------------------------------------------------------------------

class FakeClient:
    def __init__(self, answer="", route="self", remember_ok=True, fail=False):
        self.answer = answer
        self.route = route
        self.remember_ok = remember_ok
        self.fail = fail
        self.started = False
        self.closed = False
        self.remembered = []

    def start(self):
        if self.fail:
            raise RuntimeError("whitebox offline")
        self.started = True
        return self

    def close(self):
        self.closed = True

    def ask(self, message, session_id="md_cg-whitebox-verify"):
        if self.fail:
            raise RuntimeError("whitebox offline")
        return {"ok": True, "route": self.route, "reply": self.answer, "raw": {}}

    def remember(self, content, importance=0.9, tags=None):
        if self.fail:
            raise RuntimeError("whitebox offline")
        self.remembered.append(content)
        return {"ok": self.remember_ok, "raw": {}}

    def call(self, name, args):
        if self.fail:
            raise RuntimeError("whitebox offline")
        return {"isError": False, "text": "{}", "data": {"tool": name}}


class FakeCG:
    def __init__(self):
        self.nodes = []

    def add(self, nid, content, **kw):
        self.nodes.append({"id": nid, "content": content, "frontmatter": kw})
        return nid

    def search(self, query, **kw):
        return ([(n, 1.0, {}) for n in self.nodes], {"k": len(self.nodes)})


def main():
    # ---------- A. 协议与解析 ----------
    print("\n[A] 客户端协议与结果归一化")
    saved = {k: os.environ.get(k) for k in ("MDCG_WHITEBOX_CMD", "MDCG_WHITEBOX_ARGS")}
    try:
        os.environ["MDCG_WHITEBOX_CMD"] = "python3"
        os.environ["MDCG_WHITEBOX_ARGS"] = "-m aeis.mcp.server --x"
        check("A1 启动命令可用环境变量覆盖",
              whitebox._launch_cmd() == ["python3", "-m", "aeis.mcp.server", "--x"])
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    check("A2 route 解析", whitebox._extract_route({"route": "self"}) == "self")
    check("A3 reply 多键解析",
          whitebox._extract_reply({"answer": "hi"}) == "hi"
          and whitebox._extract_reply({"text": "yo"}) == "yo")
    check("A4 reply 嵌套解析",
          whitebox._extract_reply({"data": {"reply": "deep"}}) == "deep")
    check("A5 缺字段回落", whitebox._extract_reply({}, "fallback") == "fallback")

    # ---------- B. 验证·编码能力 ----------
    print("\n[B] 验证「编码能力」（remember → 追问命中）")
    cg = FakeCG()
    hit = FakeClient(answer="口令ABC")
    r1 = whitebox.verify_encoding(cg, client=hit, marker="口令ABC")
    check("B1 编码成功且追问命中 → ok",
          r1["ok"] and r1["encoded"] and r1["recalled"], str(r1.get("route")))
    check("B2 编码后写入留痕节点", bool(r1.get("node_id")))
    miss = FakeClient(answer="我不知道")
    r2 = whitebox.verify_encoding(cg, client=miss, marker="口令XYZ")
    check("B3 追问未命中 → 失败", (not r2["ok"]) and r2["encoded"]
          and (not r2["recalled"]))
    r3 = whitebox.verify_encoding(cg, client=FakeClient(fail=True), marker="X")
    check("B4 白箱不可用 → 如实失败且不抛",
          (not r3["ok"]) and "error" in r3)

    # ---------- C. 验证·已有知识回答能力 ----------
    print("\n[C] 验证「已有知识回答能力」（route=self 且非空）")
    cg = FakeCG()
    r4 = whitebox.verify_existing(cg, client=FakeClient(answer="我是灵枢", route="self"))
    check("C1 route=self 且非空 → ok", r4["ok"])
    r5 = whitebox.verify_existing(cg, client=FakeClient(answer="…", route="llm"))
    check("C2 route=llm → 未通过（非白箱自答）", not r5["ok"])
    r6 = whitebox.verify_existing(cg, client=FakeClient(answer="", route="self"))
    check("C3 空回答 → 未通过", not r6["ok"])

    # ---------- D. 留痕与报告 ----------
    print("\n[D] 验证结论留痕 + 报告")
    cg = FakeCG()
    whitebox.verify_encoding(cg, client=FakeClient(answer="口令D"), marker="口令D")
    whitebox.verify_existing(cg, client=FakeClient(answer="我是灵枢"))
    check("D1 结论写入 self 层", len(cg.nodes) == 2
          and all(n["frontmatter"].get("layer") == "self" for n in cg.nodes))
    check("D2 留痕带 whitebox:verify 标签",
          all(whitebox.VERIFY_TAG in n["frontmatter"].get("tags", [])
              for n in cg.nodes))
    rep = whitebox.report(cg)
    check("D3 报告可读回验证留痕", rep["ok"] and rep["count"] == 2)
    check("D4 无 cg 时报告不抛", whitebox.report(None)["ok"] is False)

    # ---------- E. MCP 分发 ----------
    print("\n[E] cg(op=whitebox) 分发")
    saved_cls = whitebox.WhiteboxClient
    try:
        whitebox.WhiteboxClient = (lambda *a, **k: FakeClient(answer="我是灵枢",
                                                              route="self"))
        check("E1 action=ping",
              whitebox.dispatch(None, {"action": "ping"})["ok"])
        check("E2 action=ask",
              whitebox.dispatch(None, {"action": "ask",
                                       "question": "你好"})["reply"] == "我是灵枢")
        enc = whitebox.dispatch(FakeCG(), {"action": "verify_encoding",
                                           "marker": "M"})
        check("E3 action=verify_encoding", enc["kind"] == "encoding")
        try:
            whitebox.dispatch(None, {"action": "nope"})
            check("E4 未知 action → 抛错", False)
        except ValueError:
            check("E4 未知 action → 抛错", True)
    finally:
        whitebox.WhiteboxClient = saved_cls

    print(f"\n==== P18 结果：{PASS} 通过 / {FAIL} 失败 ====")
    return FAIL


if __name__ == "__main__":
    import sys
    sys.exit(1 if main() else 0)
