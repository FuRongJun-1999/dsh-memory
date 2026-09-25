# -*- coding: utf-8 -*-
"""test_p1x_ref_root.py · P1-X 回归守卫：op=ref / index_code / index_doc 的根白名单

安全缺陷（两份独立报告合并，severity=high）：op=ref 是越权任意文件读原语——
probe_ref 以调用方自报的 root 与 ref.path 直接 os.path.join 后 open 全文回读
（refindex.py），无租户根校验、无 check_path_root、无密级闸。三形态全部漏：

  ① 自报 root 指向记忆根外（victim/secret.txt 全文进模型上下文）；
  ② ref.path 绝对路径（os.path.join 遇绝对路径丢弃 root）；
  ③ '../' 上跳。
同族缺口：index_code / index_doc 的 path 同样不走 check_path_root
（P1-4 只覆盖 ingest/export/link/mdcg_ingest）。

修复：_ref_call 的 read/get 分支按「最终将打开的完整路径」挂
check_path_root(MDCG_INGEST_ROOT)；index_code/index_doc 对模型可控的显式
path 挂同闸。语义与 P1-4 先例一致：env 未设置 = 放开（部署开关，默认行为
不变）；设置了 = realpath 落根内否则拒（fail-closed，上跳与绝对路径在
realpath 归一后自然涵盖）。

本文件钉死：三形态 + 索引越界必须拒绝；白名单内索引/回读不误伤；
env 未设保持放开语义；ingest 先例闸与 guest op 闸不回归。
运行：python -m md_cg.test_p1x_ref_root
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile

from . import corpus, tokens
from .mdcg import MdCG
from .mcp_server import call_tool
from .security import AccessDenied

PASS = FAIL = 0
FAILS = []

SECRET_TEXT = ("AKIAIOSFODNN7EXAMPLE-DUMMY\n"        # 哑数据，非真实凭据
               "secret-line-2=dummy\nsecret-line-3=dummy\n")
ALPHA_TEXT = '""" 供能注释。"""\n\ndef compute(mass):\n    return mass\n'


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}" + (f"  · {detail}" if detail else ""))
    else:
        FAIL += 1
        FAILS.append(name)
        print(f"  [FAIL] {name}  · {detail}")


def denied(fn):
    """断言 fn 被拒：抛 PermissionError，或返回 ok=False。"""
    try:
        out = fn()
        return out.get("ok") is False, f"returned ok={out.get('ok')}"
    except PermissionError as exc:
        return True, f"PermissionError({str(exc)[:40]}…)"


def main():
    print("=" * 68)
    print("md_cg P1-X 验收 · op=ref/index_code/index_doc 根白名单（三形态防越权读）")
    print("=" * 68)

    tmp = tempfile.mkdtemp(prefix="mdcg_p1x_")
    memroot = os.path.join(tmp, "memroot")      # 认知图根（服务器侧）
    allow = os.path.join(tmp, "allow")          # 部署白名单内的代码目录
    victim = os.path.join(tmp, "victim")        # 白名单外（宿主敏感区模拟）
    os.makedirs(allow)
    os.makedirs(victim)
    with open(os.path.join(victim, "secret.txt"), "w", encoding="utf-8") as f:
        f.write(SECRET_TEXT)
    with open(os.path.join(allow, "alpha.py"), "w", encoding="utf-8") as f:
        f.write(ALPHA_TEXT)

    env = "MDCG_INGEST_ROOT"
    old = os.environ.get(env)
    os.environ[env] = allow                      # 部署声明：只有 allow/ 可读入

    corpus.reset_root(memroot)
    cg = MdCG(memroot)
    full = {"lineno": 1, "end": 99}              # 无 hash → 不做漂移校验直读

    try:
        print("\n【1】三形态越权读必须被拒（fail-closed）")
        ok, d = denied(lambda: call_tool(cg, "cg", {
            "op": "ref", "ref": dict(path="secret.txt", root=victim, **full)}))
        check("①a 自报 root 越界被拒（secret 不进上下文）", ok, d)
        ok, d = denied(lambda: call_tool(cg, "cg", {
            "op": "ref", "root": allow,
            "ref": dict(path=os.path.join(victim, "secret.txt"), **full)}))
        check("①b ref.path 绝对路径被拒（join 丢弃 root 也拦）", ok, d)
        ok, d = denied(lambda: call_tool(cg, "cg", {
            "op": "ref", "root": allow,
            "ref": dict(path=os.path.join("..", "victim", "secret.txt"),
                        **full)}))
        check("①c '../' 上跳被拒", ok, d)

        print("\n【2】同族：index_code / index_doc 越界 path 必须被拒")
        ok, d = denied(lambda: call_tool(cg, "cg", {"op": "index_code",
                                                    "path": victim}))
        check("②a index_code 越界 path 被拒", ok, d)
        ok, d = denied(lambda: call_tool(cg, "cg", {"op": "index_doc",
                                                    "path": victim}))
        check("②b index_doc 越界 path 被拒", ok, d)

        print("\n【3】白名单内不误伤")
        out = call_tool(cg, "cg", {"op": "index_code", "path": allow})
        nid = (out.get("ids") or [None])[0]
        rr = call_tool(cg, "cg", {"op": "ref", "node_id": nid}) if nid \
            else {"ok": False, "error": "no ids"}
        check("③a 白名单内索引 + node 回读正常",
              out.get("ok") and out.get("indexed", 0) >= 1
              and rr.get("ok") is True and "compute" in (rr.get("text") or ""),
              f"indexed={out.get('indexed')} ref_ok={rr.get('ok')}")
        rr = call_tool(cg, "cg", {"op": "ref", "root": allow,
                                  "ref": dict(path="alpha.py", lineno=1, end=2)})
        check("③b 白名单内 inline ref 回读正常", rr.get("ok") is True,
              f"ok={rr.get('ok')} err={rr.get('error')}")

        print("\n【4】先例与开关语义不回归")
        ok, d = denied(lambda: call_tool(cg, "cg", {
            "op": "ingest", "action": "file",
            "path": os.path.join(victim, "secret.txt")}))
        check("④a ingest 越界仍被 P1-4 拦（先例闸不回归）", ok, d)
        os.environ.pop(env, None)
        rr = call_tool(cg, "cg", {
            "op": "ref", "ref": dict(path="secret.txt", root=victim, **full)})
        check("④b env 未设 = 部署开关放开（默认行为不变）",
              rr.get("ok") is True
              and "AKIAIOSFODNN7EXAMPLE" in (rr.get("text") or ""),
              f"ok={rr.get('ok')}")
        try:
            tokens.Principal(role="guest", ops_allow=("read",), theory_ok=True
                             ).require_op("ref")
            ok, d = False, "guest 未被拒"
        except AccessDenied:
            ok, d = True, "AccessDenied"
        check("④c guest 令牌 op=ref 仍被 require_op 拒", ok, d)
    finally:
        if old is None:
            os.environ.pop(env, None)
        else:
            os.environ[env] = old
        corpus.reset_root(memroot)              # 收尾：指向本次临时根
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n" + "=" * 68)
    print(f"P1-X 根白名单守卫: {PASS}/{PASS + FAIL} 通过")
    if FAILS:
        print("未过：" + "；".join(FAILS))
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
