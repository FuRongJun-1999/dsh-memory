# -*- coding: utf-8 -*-
"""test_session_isolation —— 会话隔离模型守卫（issue #35 设计定稿）

设计定稿（2026-09-23 使用者拍板）：
  · public / internal = 跨会话共享档——通过 clearance 即可见（含他人会话写入）；
  · private / secret  = 会话绑定档——仅归属会话可见；
    - 归属会话 = frontmatter.session（服务端身份不可伪造）；
    - 绑定档无归属（存量）→ fail-closed 仅设计者可见；
    - 查询侧 "*" 不再越过 private 绑定（非 admin 的 "*" 与不传等价）；
  · can_admin（设计者）豁免——整体判断需要全景；错误/冲突信息（rejected/
    unresolved）恒不进默认正排，设计者经显式通道获取；
  · tenant 物理根接线（issue #35 本体）：已登记租户走登记根，冲突 fail-closed，
    未登记回落 MDCG_ROOT（零变更）。

运行：python -X utf8 -m md_cg.test_session_isolation
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from md_cg.mcp_server import _resolve_root                # noqa: E402
from md_cg.mdcos import MdCGSecure                        # noqa: E402
from md_cg.security import Principal, TenantRegistry      # noqa: E402

passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print("  [PASS] " + name)
    else:
        failed += 1
        print("  [FAIL] " + name + "  " + str(detail)[:200])


def _principal(sess, **kw):
    kw.setdefault("actor", "tester")
    kw.setdefault("clearance", "private")
    kw.setdefault("can_write", True)
    kw.setdefault("role", "recorder")
    return Principal(session=sess, **kw)


def _search_ids(cg, q="共享 私有 标记", k=20, **kw):
    res, _m = cg.search_rrf(q, k=k, judge=False, **kw)
    return sorted(r[0]["id"] for r in res)


def main():
    root = tempfile.mkdtemp(prefix="sess_iso_")
    pa = _principal("sessA")
    a = MdCGSecure(os.path.join(root, "mem"), principal=pa)
    a.add("pub1", "共享公开级记忆：发布窗口每周三", "knowledge",
          sensitivity="public")
    a.add("int1", "共享默认级记忆：接口约定时间戳毫秒", "knowledge",
          sensitivity="internal")
    a.add("priv1", "会话私有记忆：A 的个人偏好与口令提示", "knowledge",
          sensitivity="private")
    a.flush()

    print("[1] 跨会话共享档：B 能看到 A 的 public/internal，看不到 private")
    b = MdCGSecure(os.path.join(root, "mem"), principal=_principal("sessB"))
    ids = _search_ids(b)
    check("B（不传 session）见共享档", "pub1" in ids and "int1" in ids, ids)
    check("B（不传 session）不见 A 的 private", "priv1" not in ids, ids)
    check("B get(private) → None（不可见即不存在）",
          b.get("priv1") is None)
    check("B get(public) 可读", b.get("pub1") is not None)

    print("[2] 查询侧 session 参数与收紧的 \"*\"")
    ids2 = _search_ids(b, session="sessB")
    check("B 传自己 session 仍见共享档（super 硬等值已上收）",
          "pub1" in ids2 and "int1" in ids2 and "priv1" not in ids2, ids2)
    ids3 = _search_ids(b, session="*")
    check("B 传 \"*\" 不越过 private 绑定（收紧）", "priv1" not in ids3, ids3)

    print("[3] 归属会话自身与设计者豁免")
    a2 = MdCGSecure(os.path.join(root, "mem"), principal=_principal("sessA"))
    ids4 = _search_ids(a2)
    check("A（归属会话）见自己的全部三档",
          {"pub1", "int1", "priv1"} <= set(ids4), ids4)
    adm = MdCGSecure(os.path.join(root, "mem"),
                     principal=_principal("sessAdmin", can_admin=True,
                                          role="designer"))
    ids5 = _search_ids(adm)
    check("设计者（can_admin）跨会话见全部（含 private）",
          {"pub1", "int1", "priv1"} <= set(ids5), ids5)

    print("[4] 绑定档无归属（存量）fail-closed")
    import json as _json
    e = a.index["nodes"]["priv1"]
    p = os.path.join(root, "mem", e["path"])
    fm, content = a._read(e)
    fm.pop("session", None)
    a._write_node("priv1", p, fm, content)
    a.index["nodes"]["priv1"]["session"] = None
    a.rebuild_index()
    b2 = MdCGSecure(os.path.join(root, "mem"), principal=_principal("sessB"))
    check("无归属 private：普通会话不可见（fail-closed）",
          "priv1" not in _search_ids(b2))
    check("无归属 private：设计者可见",
          "priv1" in _search_ids(adm))

    print("[5] rejected（错误标记）不进默认正排")
    rj = a.add_rejected("会话私有的错误假设", "守卫用", sensitivity="public")
    a.flush()
    check("rejected 不进任何会话的默认正排",
          rj not in _search_ids(b2) and rj not in _search_ids(adm))

    print("[6] 租户物理根解析（_resolve_root）")
    reg_path = os.path.join(root, "_tenants.json")
    reg = TenantRegistry(path=reg_path)
    reg.register("tenantA", os.path.join(root, "A"))
    reg.register("tenantB", os.path.join(root, "B"))

    r, err = _resolve_root({"MDCG_ROOT": os.path.join(root, "A"),
                            "MDCG_TENANT": "tenantA",
                            "MDCG_TENANT_REGISTRY": reg_path})
    check("已登记租户 + 一致 MDCG_ROOT → 登记根",
          not err and os.path.abspath(r) == os.path.abspath(
              os.path.join(root, "A")), (r, err))

    r, err = _resolve_root({"MDCG_TENANT": "tenantB",
                            "MDCG_TENANT_REGISTRY": reg_path})
    check("已登记租户 + 无 MDCG_ROOT → 登记根（私库可零配置）",
          not err and r == os.path.abspath(os.path.join(root, "B")), (r, err))

    r, err = _resolve_root({"MDCG_ROOT": os.path.join(root, "A"),
                            "MDCG_TENANT": "tenantB",
                            "MDCG_TENANT_REGISTRY": reg_path})
    check("登记根与 MDCG_ROOT 冲突 → fail-closed（root=None + 冲突说明）",
          r is None and "fail-closed" in (err or ""), (r, err))

    r, err = _resolve_root({"MDCG_ROOT": os.path.join(root, "X")})
    check("未设租户 → 维持 MDCG_ROOT（零变更）",
          not err and r == os.path.join(root, "X"), (r, err))

    r, err = _resolve_root({"MDCG_ROOT": os.path.join(root, "X"),
                            "MDCG_TENANT": "未登记租户"})
    check("租户未登记 → 回落 MDCG_ROOT（不误伤）",
          not err and r == os.path.join(root, "X"), (r, err))

    r, err = _resolve_root({})
    check("全空 → (None, None)（main 侧报缺 MDCG_ROOT）",
          r is None and not err, (r, err))

    print("[7] 双租户物理隔离端到端（各自根，互不可见）")
    ta = MdCGSecure(os.path.join(root, "A"), principal=_principal("sessA"))
    ta.add("only_a", "租户A的记忆", "knowledge", sensitivity="public")
    ta.flush()
    tb = MdCGSecure(os.path.join(root, "B"), principal=_principal("sessB"))
    tb.add("only_b", "租户B的记忆", "knowledge", sensitivity="public")
    tb.flush()
    check("A 根检索只见 A（物理隔离）",
          "only_a" in _search_ids(ta) and "only_b" not in _search_ids(ta))
    check("B 根检索只见 B（物理隔离）",
          "only_b" in _search_ids(tb) and "only_a" not in _search_ids(tb))

    print(f"\nsession_isolation: {passed} 通过 / {failed} 失败")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
