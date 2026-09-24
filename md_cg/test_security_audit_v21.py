#!/usr/bin/env python3
"""批次 34 守卫：V21 报告八项缺陷的能红断言。

V21-1 editKeyHint 无限自递归（TS 侧静态断言）
V21-2 _readable 密级回填 fail-open（行为断言：_read 失败 → secret 档拒读）
V21-3 _NODE_ID_RE 中文/逗号（5 官方红同源——直断言 + 防线不回退）
V21-4 run_channel_b 主体归位（冒烟：队列空场景返回 dict 非 None + 沙箱模块级）
V21-5 P2-3 就地剥离自愈（门控残留两次查询后消失）
V21-6 P2-4 doc_key[0] 可哈希（reach 分支不再 TypeError）
V21-7 lingshu_cg 返回体递归脱敏（_redact_deep 行为 + 接线静态断言）
V21-8 敏感名族匹配（报告 8 类实测样本全拒 + 正常文件不误伤）
"""
import ast
import os
import sys
import tempfile

PASS = 0
FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}  {detail}")


def v21_1_editkeyhint():
    print("== V21-1 editKeyHint 真分支非自调用 ==")
    src = open("src/lib/roleplay_web.ts", encoding="utf-8").read()
    check("已配置分支返回终止文案（非自调用）",
          "? '缺少编辑密钥（x-edit-key 头）'" in src)
    check("无限递归形态已消除", "? editKeyHint()" not in src)
    check("未配置分支引导文案保留",
          "编辑未开放：服务端需配置环境变量 ROLEPLAY_EDIT_KEY" in src)


def v21_2_readable_failclosed():
    print("== V21-2 _readable 密级未知 fail-closed ==")
    root = tempfile.mkdtemp(prefix="v21_2_")
    from md_cg.mdcos import MdCGSecure
    from md_cg.security import Principal
    cg = MdCGSecure(root, principal=Principal(
        actor="peer", clearance="internal", can_write=False, can_admin=False,
        auth_mode="test"))
    saved = cg._read
    cg._read = lambda e: (None, None)      # 模拟盘读失败（V21-2 触发形态）
    e = {"path": "knowledge/prot.md", "layer": "knowledge",
         "sensitivity": None}
    try:
        ok = cg._readable(e)
    finally:
        cg._read = saved
    check("密级未知节点对平级 internal 身份不可见", ok is False,
          f"_readable={ok!r}（fail-open 则为 True）")
    check("回填落为最高档 secret", e.get("sensitivity") == "secret",
          str(e.get("sensitivity")))


def v21_3_nodeid_charset():
    print("== V21-3 node_id 中文/逗号放行 + 防线不回退 ==")
    from md_cg.mdcg import _NODE_ID_RE, MdCG
    root = tempfile.mkdtemp(prefix="v21_3_")
    cg = MdCG(root)
    for nid in ("task_任务-名-一", "metal_铜", "perturb_0a_电路",
                "comma,node", "票据-research-审计"):
        check(f"中文/逗号 id 放行：{nid}", bool(_NODE_ID_RE.match(nid)))
        got = cg.add(nid, f"# 功能名：占位{nid}\n# 生效条件：占位\n"
                         f"# 子功能：占位\n# 执行：占位\n# 验证方式：占位\n"
                         f"# 不适用条件：占位\n# 正文四要素：占位", "contextual")
        check(f"  落盘成功：{nid}", got == nid, repr(got))
    for bad in ("../evil", "a:b", "/abs/path", "x" * 129, ""):
        check(f"  恶意 id 仍拒：{bad[:20]!r}", not _NODE_ID_RE.match(bad)
              if bad else True)


def v21_4_run_channel_b():
    print("== V21-4 run_channel_b 主体归位 ==")
    src = open("scripts/bootstrap_loop.py", encoding="utf-8").read()
    tree = ast.parse(src)
    lines = src.splitlines()
    # 沙箱函数必须在模块级（不在任何函数体内）
    sandbox_at_top = any(
        isinstance(n, ast.FunctionDef) and n.name == "_safe_exec_gen"
        and isinstance(getattr(n, "parent", None), ast.Module)
        for n in ast.walk(tree))
    top_names = {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}
    check("_safe_exec_gen 在模块级", "_safe_exec_gen" in top_names)
    # run_channel_b 体量恢复（V21-4 定案：7 行 → 恢复主体）
    rc = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "run_channel_b")
    check("run_channel_b 主体行数 > 60", rc.end_lineno - rc.lineno > 60,
          f"{rc.end_lineno - rc.lineno} 行（被掏空态为 7 行）")
    check("return 后无同块后继（unreachable 扫描同判据）",
          not isinstance(rc.body[-2], (ast.Return, ast.Continue))
          or rc.body[-1] is rc.body[-2])
    # 冒烟：队列空且无 llm_generate → 返回 stats dict（不静默 None）
    sys.path.insert(0, "scripts")
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "bl_v21", "scripts/bootstrap_loop.py")
    m = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(m)
    except SystemExit:
        pass
    res = m.run_channel_b(None, max_tasks=2)
    check("队列空场景返回 dict（非静默 None）", isinstance(res, dict),
          repr(res)[:80])


def v21_5_p23_selfheal():
    print("== V21-5 P2-3 门控残留就地自愈 ==")
    os.environ.pop("MDCG_RETRIEVAL_PIPELINE", None)
    from md_cg.mdcg import MdCG
    root = tempfile.mkdtemp(prefix="v21_5_")
    cg = MdCG(root)
    cg.add("n1", "阿尔法 贝塔 电路 板", "knowledge")
    cg.index["nodes"]["n1"]["big_domain"] = []       # 注入门控残留
    cg.index["nodes"]["n1"]["observation_position"] = []
    cg.search("阿尔法 电路")
    e = cg.index["nodes"]["n1"]
    check("首次查询后残留已剥离（自愈）",
          "big_domain" not in e and "observation_position" not in e,
          str({k: e.get(k) for k in ("big_domain", "observation_position")}))


def v21_6_p24_hashable():
    print("== V21-6 doc_key[0] 可哈希 ==")
    from md_cg import pooling
    doc = ({"path": "knowledge/n1.md"},
           {"id": "n1", "layer": "knowledge"}, "正文")
    k = pooling.doc_key(doc)
    check("doc_key 返回二元组", isinstance(k, tuple) and len(k) == 2)
    try:
        {k[0]: 1}
        hashable = True
    except TypeError:
        hashable = False
    check("node_id（doc_key[0]）可哈希", hashable)
    try:
        {k: 1}
        whole = True
    except TypeError:
        whole = False
    check("整键（含 entry dict）确实不可哈希（缺陷形态确认）", whole is False)


def v21_7_redact_deep():
    print("== V21-7 lingshu_cg 返回体递归脱敏 ==")
    sys.path.insert(0, "hive")
    import importlib.util
    spec = importlib.util.spec_from_file_location("hv", "hive/exec.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    body = {"ok": True, "results": [
        {"content": "联系 13812345678", "frontmatter": {"note": "mail a@b.com"}},
        {"path": "knowledge/x.md"}]}
    out = m._redact_deep(body)
    s = repr(out)
    check("嵌套正文手机号已脱敏", "13812345678" not in s and "已脱敏" in s)
    check("嵌套邮箱已脱敏", "a@b.com" not in s)
    check("结构保持", out["ok"] is True and out["results"][1]["path"]
          == "knowledge/x.md")
    src = open("hive/exec.py", encoding="utf-8").read()
    check("tool_lingshu_cg 返回体已接线", "_redact_deep(out)" in src)


def v21_8_sensitive_family():
    print("== V21-8 敏感名族匹配 ==")
    sys.path.insert(0, "hive")
    import importlib.util
    spec = importlib.util.spec_from_file_location("hv8", "hive/exec.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    base = tempfile.mkdtemp(prefix="v21_8_")
    leaks = ["id_rsa", "id_rsa.bak", "id_rsa_copy", "id_rsa.old", "id_rsa~",
             "prod.env", "app.env", "creds.json", "aws_credentials",
             "service-account.json"]
    for fn in leaks:
        p = os.path.join(base, fn)
        open(p, "w").close()
        check(f"  拒读：{fn}", m._sensitive_read(p) is not None)
    for fn in ("notes.md", "readme.md", "data.json"):
        p = os.path.join(base, fn)
        open(p, "w").close()
        check(f"  不误伤：{fn}", m._sensitive_read(p) is None)


def main():
    os.chdir(os.path.join(os.path.dirname(__file__), ".."))
    v21_1_editkeyhint()
    v21_2_readable_failclosed()
    v21_3_nodeid_charset()
    v21_4_run_channel_b()
    v21_5_p23_selfheal()
    v21_6_p24_hashable()
    v21_7_redact_deep()
    v21_8_sensitive_family()
    print(f"\ntest_security_audit_v21: {PASS} 通过 / {FAIL} 失败")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
