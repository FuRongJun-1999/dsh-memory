# -*- coding: utf-8 -*-
"""写入路径拦截器链（writepipe）验收：Pi 钩子化移植（交接文档 §3⑥）。

验收口径：
- 默认链行为与重构前 _cg_dispatch write 分支逐字节一致
  （ACCEPT 直写 / REJECT 负记忆 / DEFER 入队 + 幂等去重联动 / gated 闸 /
  冲突 cvd 透传）；
- 新增/移除一个拦截器不改核心文件（register/unregister 即插即拔）；
- 角色/层权限校验结构上不可被拦截器绕过（反面清单：信任必须结构强制）；
- REWRITE（拦截器改写 ctx["a"]["content"]）/ 链序 / 短路 / after 观测者。
"""

import json
import os
import shutil
import sys
import tempfile
import traceback

from . import writepipe
from .mdcos import MdCGSecure
from .security import AccessDenied, Principal

_ok = 0
_bad = []
_seq = [0]


def _check(name, cond, detail=""):
    global _ok
    if cond:
        _ok += 1
        print("  ok   %s" % name)
    else:
        _bad.append("%s %s" % (name, detail))
        print("  FAIL %s %s" % (name, detail))


def _mk_cg(tmp, role="designer"):
    _seq[0] += 1
    root = os.path.join(tmp, "root_%02d_%s" % (_seq[0], role))
    p = Principal(tenant="default", actor="t_" + role, role=role,
                  can_write=(role != "guest"),
                  can_admin=(role == "designer"))
    return MdCGSecure(root, principal=p)


def _policy(tmp, required=("PASSED",), forbidden=("FORBIDDEN_WORD",)):
    path = os.path.join(tmp, "policy.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"forbidden": list(forbidden),
                   "required": list(required)}, f)
    os.environ["MDCG_POLICY_FILE"] = path
    return path


def main():
    tmp = tempfile.mkdtemp(prefix="writepipe_")
    old_policy = os.environ.pop("MDCG_POLICY_FILE", None)
    try:
        _run(tmp)
    except Exception:
        traceback.print_exc()
        _bad.append("未捕获异常")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        if old_policy is not None:
            os.environ["MDCG_POLICY_FILE"] = old_policy
        else:
            os.environ.pop("MDCG_POLICY_FILE", None)
    print("\nwritepipe 验收：%d 通过%s" % (
        _ok, ("，%d 失败：%s" % (len(_bad), "; ".join(_bad))) if _bad else ""))
    return 1 if _bad else 0


def _run(tmp):
    policy = _policy(tmp)

    # ---------- 1 默认链：与重构前 write 分支行为一致 ----------
    pipe = writepipe.install_default_gates(writepipe.WritePipeline())
    cg = _mk_cg(tmp)

    out = pipe.execute(cg, {"content_kind": "text",
                            "content": "要素齐全 PASSED",
                            "layer": "knowledge"})
    _check("默认链ACCEPT直写", out.get("committed") is True and out.get("ok") is True,
           repr(out))
    _check("冲突闸cvd透传", isinstance(out.get("consistency"), dict), repr(out))

    out = pipe.execute(cg, {"content_kind": "text",
                            "content": "含 FORBIDDEN_WORD 的违禁内容",
                            "layer": "knowledge"})
    _check("REJECT负记忆", out.get("moved_to") == "rejected"
           and out.get("committed") is False, repr(out))

    # DEFER（无规则文件 → 无法判定 → 入审核队列）+ 幂等去重联动
    os.environ.pop("MDCG_POLICY_FILE", None)
    a = {"content_kind": "text", "content": "无规则可判的内容",
         "layer": "knowledge"}
    out1 = pipe.execute(cg, dict(a))
    _check("DEFER入队", out1.get("moved_to") == "review_queue"
           and bool(out1.get("pid")), repr(out1))
    out2 = pipe.execute(cg, dict(a))
    _check("幂等去重联动", out2.get("dedup") is True
           and out2.get("dup_of") == out1.get("pid"), repr(out2))
    os.environ["MDCG_POLICY_FILE"] = policy

    out = pipe.execute(cg, {"content_kind": "text",
                            "content": "PASSED 情境记忆", "gated": True,
                            "layer": "contextual"})
    _check("gated闸代执行", "gate" in out, repr(out))

    # ---------- 2 注册/移除拦截器不改核心文件 ----------
    singleton = writepipe.default_pipeline()

    def _block_skipme(ctx):
        if "SKIPME" in (ctx["a"].get("content") or ""):
            return {"ok": False, "committed": False,
                    "moved_to": "hook_blocked", "by": "test_block"}
        return None

    singleton.register_before("test_block", _block_skipme)
    out = singleton.execute(cg, {"content_kind": "text",
                                 "content": "PASSED SKIPME",
                                 "layer": "knowledge"})
    _check("注册即拦", out.get("moved_to") == "hook_blocked", repr(out))
    singleton.unregister_before("test_block")
    out = singleton.execute(cg, {"content_kind": "text",
                                 "content": "PASSED SKIPME",
                                 "layer": "knowledge"})
    _check("移除即恢复(核心文件零改动)", out.get("committed") is True, repr(out))
    _check("单例默认链", singleton.names()["before"]
           == ["audit", "consistency", "gated"],
           repr(singleton.names()))

    # ---------- 3 链序 / 短路 / REWRITE ----------
    p3 = writepipe.WritePipeline()
    order = []
    p3.register_before("g1", lambda ctx: order.append("g1") or None)
    p3.register_before("g2", lambda ctx: order.append("g2") or None)
    p3.register_before("g3", lambda ctx: order.append("g3")
                       or {"ok": False, "moved_to": "halt"})
    cg3 = _mk_cg(tmp)
    out = p3.execute(cg3, {"content_kind": "text", "content": "PASSED",
                           "layer": "knowledge"})
    _check("链序按注册序", order == ["g1", "g2", "g3"], repr(order))
    _check("终态短路不落盘", out.get("moved_to") == "halt"
           and "id" not in out and "committed" not in out, repr(out))

    p4 = writepipe.WritePipeline()
    p4.register_before("rw", lambda ctx:
                       ctx["a"].__setitem__("content",
                                            ctx["a"].get("content") + " REWRITTEN")
                       or None)
    cg4 = _mk_cg(tmp)
    out = p4.execute(cg4, {"content_kind": "text", "content": "PASSED",
                           "layer": "knowledge"})
    _check("REWRITE改写生效", out.get("committed") is True
           and bool(cg4.search("REWRITTEN")), repr(out))

    # ---------- 4 权限结构上不可被拦截器绕过 ----------
    cg_guest = _mk_cg(tmp, role="guest")
    p5 = writepipe.WritePipeline()
    p5.register_before("always_pass", lambda ctx: None)
    try:
        p5.execute(cg_guest, {"content_kind": "text", "content": "PASSED",
                              "consistency": False, "layer": "knowledge"})
        _check("权限不可绕", False, "guest 写入未被拒")
    except AccessDenied:
        _check("权限不可绕", True)
    except Exception as e:  # noqa: BLE001
        _check("权限不可绕", False,
               "异常类型=%s:%s" % (type(e).__name__, e))

    # ---------- 5 after 观测者 ----------
    p6 = writepipe.WritePipeline()
    seen = []
    p6.register_after("spy", lambda ctx, out: seen.append(out.get("committed")))
    cg6 = _mk_cg(tmp)
    p6.execute(cg6, {"content_kind": "text", "content": "PASSED",
                     "layer": "knowledge"})
    _check("after观测成功", seen == [True], repr(seen))

    def _boom(ctx, out):
        raise RuntimeError("after钩子故障")

    p6.register_after("boom", _boom)
    try:
        p6.execute(cg6, {"content_kind": "text", "content": "PASSED 二次",
                         "layer": "knowledge"})
        _check("after故障不吞", False, "异常被静默")
    except RuntimeError:
        _check("after故障不吞", True)

    # ---------- 6 注册表卫生 ----------
    p7 = writepipe.WritePipeline()
    p7.register_before("x", lambda ctx: None)
    p7.register_before("x", lambda ctx: None)  # 同名幂等替换
    _check("同名幂等注册", p7.names()["before"] == ["x"], repr(p7.names()))
    try:
        p7.register_before("y", 123)
        _check("类型守卫", False, "非可调用未拒")
    except TypeError:
        _check("类型守卫", True)
    _check("注销返回布尔", p7.unregister_before("x") is True
           and p7.unregister_before("x") is False)


if __name__ == "__main__":
    sys.exit(main())
