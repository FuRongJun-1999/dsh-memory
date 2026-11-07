# -*- coding: utf-8 -*-
"""issue #721 守卫：检索期按标签过滤（域隔离）。

本件钉死 5 条判据 + 1 条向后兼容，改实现而不改语义时至少一条会变红：
  · 单标签 include            —— 只留命中的域
  · 多标签 include = OR       —— **不是 AND**（变异点：改成 AND 必红）
  · exclude 优先于 include    —— 同节点两边都命中时剔除
  · 不存在的标签 => 空集不报错 —— 空集是合法答案，不是异常
  · 缺省不传 => 行为逐位不变   —— 既有调用方不被破坏（meta 不得出现 tag_filtered）

跑法（两种都支持）：
    python -X utf8 tests/test_issue721_tag_filter.py     # 直跑，退出码即结论
    python -X utf8 -m pytest tests/test_issue721_tag_filter.py -q
"""
import json
import shutil
import sys
import tempfile
import os

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from md_cg.mdcos import MdCGSecure as MdCG   # noqa: E402
import md_cg.mcp_server as MS                # noqa: E402

CCG = """# 功能名：域隔离样例 %s
# 生效条件：检索演示
# 子功能：无
# 执行：静态文本
# 验证方式：读回
# 不适用条件：无

%s"""


class _Store(object):
    def __init__(self):
        self.root = tempfile.mkdtemp(prefix="cg721guard_")
        self.cg = MdCG(self.root)

    def call(self, args):
        try:
            return MS.call_tool(self.cg, "cg", args)
        except Exception as exc:  # noqa: BLE001
            return {"__exception__": type(exc).__name__, "msg": str(exc)[:240]}

    def put(self, name, tags):
        r = self.call({"op": "write", "content": CCG % (name, name),
                       "content_kind": "text", "tags": list(tags),
                       "layer": "knowledge", "importance": 0.6})
        ok = bool(r.get("ok")) if isinstance(r, dict) else False
        return ok, (r.get("id") if isinstance(r, dict) else None)

    def read(self, **kw):
        args = {"op": "read", "query": "域隔离样例"}
        args.update(kw)
        return self.call(args)

    def close(self):
        try:
            self.cg.close()
        except Exception:  # noqa: BLE001
            pass
        shutil.rmtree(self.root, ignore_errors=True)


def _ids(resp):
    out = []
    for it in (resp or {}).get("results") or []:
        node = it.get("node") or {}
        out.append(node.get("id") or it.get("ref") or it.get("id"))
    return [x for x in out if x]


def _tags_of(resp):
    got = []
    for it in (resp or {}).get("results") or []:
        node = it.get("node") or {}
        fm = node.get("frontmatter") or {}
        got.append(tuple(fm.get("tags") or ()))
    return got


def _seed():
    s = _Store()
    made = {}
    for name, tags in (
        ("work_a", ["dom:work"]),
        ("work_b", ["dom:work", "kind:fact"]),
        ("personal_c", ["dom:personal"]),
        ("secret_d", ["dom:work", "dom:secret"]),
    ):
        ok, nid = s.put(name, tags)
        assert ok, "写入 %s 失败（样例数据未就绪，后续判据无意义）" % name
        made[name] = nid
    return s, made


def test_baseline_two_domains():
    """基线：不传标签时两个域都返回（证明后续对照不是空库空转）。"""
    s, made = _seed()
    try:
        r = s.read()
        ids = _ids(r)
        assert len(ids) >= 3, "基线应返回至少 3 条，实得 %d：%s" % (len(ids), json.dumps(r)[:200])
        assert "tag_filtered" not in (r.get("meta") or {}), "未传标签时不得出现 tag_filtered"
    finally:
        s.close()


def test_single_include_tag():
    """单标签：只留命中该标签的节点。"""
    s, made = _seed()
    try:
        r = s.read(include_tags=["dom:personal"])
        tags = _tags_of(r)
        assert tags, "应至少返回 1 条（dom:personal）"
        for t in tags:
            assert "dom:personal" in t, "返回了非本域节点：tags=%s" % (t,)
    finally:
        s.close()


def test_multi_include_is_or_not_and():
    """多标签 = OR（**不是 AND**）：这条是 AND→OR 变异的判据。"""
    s, made = _seed()
    try:
        r = s.read(include_tags=["dom:personal", "kind:fact"])
        got = _tags_of(r)
        assert len(got) == 2, "OR 应命中 2 条（personal_c 与 work_b），实得 %d 条：%s" % (len(got), got)
        assert any("dom:personal" in t for t in got), "应有 personal_c"
        assert any("kind:fact" in t for t in got), "应有 work_b"
        # 若是 AND 口径，只剩同时含两标签的节点（本例 0 条）——正是要拦住的反向实现
        assert not all(("dom:personal" in t and "kind:fact" in t) for t in got), \
            "全部命中同时含两标签 => 实现是 AND，不是 OR"
    finally:
        s.close()


def test_exclude_tags():
    """exclude：命中所给任一标签即剔除。"""
    s, made = _seed()
    try:
        r = s.read(exclude_tags=["dom:personal"])
        tags = _tags_of(r)
        assert tags, "应至少返回 1 条"
        for t in tags:
            assert "dom:personal" not in t, "exclude 未生效，仍返回了 personal 域：%s" % (t,)
    finally:
        s.close()


def test_exclude_wins_over_include():
    """exclude 优先于 include：同节点两边都命中时被剔除。"""
    s, made = _seed()
    try:
        r = s.read(include_tags=["dom:work"], exclude_tags=["dom:secret"])
        tags = _tags_of(r)
        assert tags, "应至少返回 1 条（work_a / work_b）"
        for t in tags:
            assert "dom:secret" not in t, "exclude 未优先于 include，仍返回了 secret 节点：%s" % (t,)
        assert any("dom:work" in t for t in tags), "正常的 dom:work 节点不应被误杀"
    finally:
        s.close()


def test_nonexistent_tag_returns_empty_not_error():
    """不存在的标签：返回空集，**不报错**（空集是合法答案）。"""
    s, made = _seed()
    try:
        r = s.read(include_tags=["dom:no_such_domain"])
        assert "__exception__" not in r, "不应抛异常：%s" % json.dumps(r, ensure_ascii=False)[:200]
        assert r.get("ok") is not False, "不应返回错误：%s" % json.dumps(r, ensure_ascii=False)[:200]
        assert _ids(r) == [], "不存在的标签应返回空集，实得 %s" % (_ids(r),)
        assert (r.get("meta") or {}).get("tag_filtered", 0) >= 1, "meta 应如实记录被筛掉的条数"
    finally:
        s.close()


def test_invalid_tag_type_is_structured_error():
    """非法类型 fail-closed：结构化 error，不静默当没传（静默会把域隔离变成全域返回）。"""
    s, made = _seed()
    try:
        r = s.read(include_tags=12345)
        assert "__exception__" not in r, "不应抛裸异常"
        assert r.get("ok") is False and r.get("error") == "invalid_tags", \
            "应返回 invalid_tags，实得 %s" % json.dumps(r, ensure_ascii=False)[:200]
    finally:
        s.close()


def test_backward_compat_no_tags():
    """向后兼容：不传标签时 meta 里不得出现 tag_* 字段，结果条数与基线一致。"""
    s, made = _seed()
    try:
        a = s.read()
        b = s.read()
        assert _ids(a) == _ids(b), "两次无标签检索结果应一致"
        meta = a.get("meta") or {}
        for k in ("include_tags", "exclude_tags", "tag_filtered"):
            assert k not in meta, "未传标签时不得写入 meta[%s]" % k
    finally:
        s.close()


# ---------------------------------------------------------------------------
# 直跑入口（不依赖 pytest：退出码即结论）
# ---------------------------------------------------------------------------
def _main():
    import traceback
    cases = [(k, v) for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    print("=== issue #721 守卫：标签过滤 ===")
    print("repo: %s" % _REPO)
    print("python: %s" % sys.version.split()[0])
    print("")
    passed = failed = 0
    for name, fn in cases:
        try:
            fn()
            passed += 1
            print("  PASS %s" % name)
        except AssertionError as e:
            failed += 1
            print("  FAIL %s" % name)
            print("       %s" % str(e)[:400])
        except Exception as e:  # noqa: BLE001
            failed += 1
            print("  ERROR %s: %s" % (name, type(e).__name__))
            print("       %s" % str(e)[:400])
            traceback.print_exc()
    print("")
    print("===== SUMMARY %d/%d 通过 =====" % (passed, passed + failed))
    print("VERDICT=%s" % ("PASS" if failed == 0 else "FAIL"))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(_main())
