# -*- coding: utf-8 -*-
"""issue #754 守卫：index_code/index_doc 的嵌套根守卫（父/子根互相包含时拒绝）。

## 病象
`docindex.node_id` 的键是「相对传入 root 的 path」⇒ 同一物理文件从父根索引得 `sub/a.md`、
从子根得 `a.md`，**两个 id、两套节点**（#352-E 的冲突检测只拦「同 id 被另一根占用」，
本例 id 不同 ⇒ 静默双写）。实测影响：93 份文档各 3 遍、多 2971 切块 / 8 MB。

## 修法（入口守卫）
`mcp_server._nested_root_guard(cg, root)`：从 `<cg.root>/_refindex.json` 的已索引源文件
记录里取全部 root（realpath），新 root 与之**互相包含**且不是同一个根 ⇒ 返回该根；
`index_code` / `index_doc` 入口命中即拒（`error=nested_root`），`allow_nested=true` 可显式强制。
水位缺失/损坏 ⇒ 不拦（fail-open，既有行为不变）。

## 断言面
- N1 父根索引成功；
- N2 子根索引被拒（error=nested_root，conflicts_with 指向父根）；
- N3 被拒时**零写入**（节点数不变）；
- N4 同根重索引不被误拦；
- N5 反向（先子后父）同样被拒；
- N6 allow_nested=true 时放行；
- N7 index_code 同形；
- N8 路径等价写法（尾随 /.）不算嵌套。

运行：python -X utf8 -m md_cg.test_issue754_nested_root_guard
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)
_TMP = tempfile.mkdtemp(prefix="iss754_")
os.environ.update({
    "MDCG_INGEST_ROOT": _TMP,
    "MDCG_SUSTAIN": "0",
    "MDCG_SLEEP": "0",
})

from md_cg import mcp_server   # noqa: E402
from md_cg.mdcos import MdCGOS  # noqa: E402

FAILS = []


def ok(cond, name, detail=""):
    if cond:
        print("  PASS " + name)
    else:
        print("  FAIL " + name + "  " + str(detail)[:300])
        FAILS.append(name)


def _lib(tag):
    return MdCGOS(os.path.join(_TMP, "brain_" + tag), autoflush=1)


def _call(cg, **a):
    r = mcp_server.call_tool(cg, "cg", a)
    if isinstance(r, dict) and "content" in r:
        return json.loads(r["content"][0]["text"])
    return r


def _nodes(cg):
    return len((cg.index.get("nodes") or {}))


def _led_files(cg):
    import json as _json
    fp = os.path.join(cg.root, "_refindex.json")
    if not os.path.exists(fp):
        return {}
    try:
        return (_json.load(open(fp, encoding="utf-8")) or {}).get("files") or {}
    except Exception:
        return {}


def _mk(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def main():
    print("=" * 68)
    print("issue #754 守卫：嵌套根重复索引")
    print("=" * 68)
    docs = os.path.join(_TMP, "docs")
    _mk(os.path.join(docs, "sub", "a.md"),
        "# 标题\n\n## 小节\n\n正文。\n")
    _mk(os.path.join(docs, "b.md"), "# 另一篇\n\n正文。\n")

    cg = _lib("a")
    r1 = _call(cg, op="index_doc", path=docs)
    ok(r1.get("ok") is True and int(r1.get("indexed") or 0) >= 1,
       "N1 父根索引成功", r1)
    n_before = _nodes(cg)
    _n_led = len(_led_files(cg))
    r2 = _call(cg, op="index_doc", path=os.path.join(docs, "sub"))
    ok(r2.get("ok") is False and r2.get("error") == "nested_root",
       "N2 子根索引被拒（nested_root）", r2)
    ok(os.path.realpath(str(r2.get("conflicts_with") or "")) == os.path.realpath(docs),
       "N2b conflicts_with 指向父根", r2.get("conflicts_with"))
    ok(_nodes(cg) == n_before, "N3 被拒时零写入（节点数不变）",
       (_nodes(cg), n_before))
    ok(len(_led_files(cg)) == _n_led, "N3b 被拒时水位未变",
       (len(_led_files(cg)), _n_led))
    r3 = _call(cg, op="index_doc", path=docs, incremental=True)
    ok(r3.get("ok") is True, "N4 同根重索引不被误拦", r3)

    cg2 = _lib("b")
    r4 = _call(cg2, op="index_doc", path=os.path.join(docs, "sub"))
    ok(r4.get("ok") is True, "N5 先子根索引成功", r4)
    r5 = _call(cg2, op="index_doc", path=docs)
    ok(r5.get("ok") is False and r5.get("error") == "nested_root",
       "N5b 反向（后父根）同样被拒", r5)
    r6 = _call(cg2, op="index_doc", path=docs, allow_nested=True)
    ok(r6.get("ok") is True, "N6 allow_nested=true 放行", r6)

    repo = os.path.join(_TMP, "code")
    _mk(os.path.join(repo, "src", "m.py"),
        "def f():\n    \"\"\"doc\"\"\"\n    return 1\n")
    cg3 = _lib("c")
    c1 = _call(cg3, op="index_code", path=repo)
    ok(c1.get("ok") is True, "N7 index_code 父根成功", c1)
    c2 = _call(cg3, op="index_code", path=os.path.join(repo, "src"))
    ok(c2.get("ok") is False and c2.get("error") == "nested_root",
       "N7b index_code 子根被拒", c2)

    ok(bool(r6.get("nested_override")) is True
       and os.path.realpath(str(r6.get("conflicts_with") or ""))
       == os.path.realpath(os.path.join(docs, "sub")),
       "N6b allow_nested 强制时回执留痕（nested_override + conflicts_with=已索引根）", r6)

    # N9：尾随分隔符等价写法不算嵌套
    cg5 = _lib("e")
    e1 = _call(cg5, op="index_doc", path=docs)
    e2 = _call(cg5, op="index_doc", path=docs + os.sep)
    ok(e1.get("ok") is True and e2.get("ok") is True,
       "N9 尾随分隔符不算嵌套", (e1.get("ok"), e2.get("ok")))

    # N10：kind 隔离——代码根内的文档根可独立索引（两种域）
    _mk(os.path.join(repo, "docs", "x.md"), "# 文档\n\n正文。\n")
    cg6 = _lib("f")
    f1 = _call(cg6, op="index_code", path=repo)
    f2 = _call(cg6, op="index_doc", path=os.path.join(repo, "docs"))
    ok(f1.get("ok") is True and f2.get("ok") is True,
       "N10 kind 隔离：code 根内 doc 根可独立索引", (f1.get("ok"), f2.get("ok")))

    # N11：默认 root（未显式给 path）不做嵌套拦截（部署侧全库语义）
    cg7 = _lib("g")
    g1 = _call(cg7, op="index_doc", path=docs)
    g2 = _call(cg7, op="index_doc")
    ok(g1.get("ok") is True and g2.get("ok") is True,
       "N11 默认 root 不被嵌套守卫拦", (g1.get("ok"), g2.get("ok")))

    # N12：水位不可用 ⇒ fail-open + 回执显式降级
    cg8 = _lib("h")
    h1 = _call(cg8, op="index_doc", path=docs)
    _led = os.path.join(cg8.root, "_refindex.json")
    if os.path.exists(_led):
        with open(_led, "w", encoding="utf-8") as _f:
            _f.write("{broken")          # 损坏水位（非删档——删档=全新库，不是降级）
    h2 = _call(cg8, op="index_doc", path=os.path.join(docs, "sub"))
    ok(h2.get("ok") is True and h2.get("nested_guard") == "unavailable",
       "N12 水位损坏 ⇒ 不拦且显式降级（nested_guard=unavailable）",
       (h2.get("ok"), h2.get("nested_guard")))

    cg4 = _lib("d")
    d1 = _call(cg4, op="index_doc", path=docs)
    d2 = _call(cg4, op="index_doc", path=docs + os.sep + ".")
    ok(d1.get("ok") is True and d2.get("ok") is True,
       "N8 等价写法（尾随 /.）不算嵌套", (d1.get("ok"), d2.get("ok")))

    for lib in (cg, cg2, cg3, cg4, cg5, cg6, cg7, cg8):
        try:
            lib.close()
        except Exception:
            pass
    print()
    print("issue #754：%d 项失败" % len(FAILS) if FAILS else "issue #754：全部通过")
    return 1 if FAILS else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        shutil.rmtree(_TMP, ignore_errors=True)
