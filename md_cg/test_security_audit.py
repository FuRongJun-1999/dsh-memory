#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""安全审计修复守卫（批次 24，外部审查报告 P0-1/P1-1/P2-1/P1-8）。

P0-1：node_id 是模型可控输入、直接拼落盘路径——`..` 穿越出 root、
Windows 绝对路径（os.path.join 丢弃前缀）= 任意 .md 覆盖。修复 = 白名单
+ realpath 纵深闸。守卫断言（能红修复前实现）：
  - 穿越/绝对路径/超长/空 id 必 ValueError；
  - 合法 id（存量形态）照常写入。
P1-1：mdcg_* 工具此前完全绕过 ops_allow 白名单——只读令牌可经
mdcg_remember 写入。守卫断言（能红修复前实现）：
  - ops_allow=["read"] 的 principal 调 mdcg_remember 必 AccessDenied；
  - ops_allow=None（不限）令牌照常放行（兼容性）；
  - 读工具在 read 令牌下放行。
P1-8：tarfile filter="data"（静态断言 + import 回归）。
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PASS = 0
FAIL = 0
FAILS = []


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  OK   {name}")
    else:
        FAIL += 1
        FAILS.append(name)
        print(f"  FAIL {name}  {detail}")


def main():
    from md_cg.mdcg import _NODE_ID_RE
    from md_cg.mdcos import MdCGSecure
    from md_cg.mcp_server import _dispatch, _MDCG_OP_REQUIRE

    root = tempfile.mkdtemp(prefix="mdcg_secaudit_")
    # 生产形态（MdCGSecure——mdcg_search 分支走 OS 层签名，基类 MdCG 无
    # roles 参数；P1-1c 因此必须用安全实例而非基类）
    cg = MdCGSecure(root)

    print("== P0-1 node_id 白名单 + realpath 纵深闸 ==")
    bad_ids = [
        (".. 穿越", "../evil"),
        ("多层穿越", "sub/../../../evil"),
        ("Windows 绝对路径", "C:/Users/test/evil"),
        ("类 Unix 绝对路径", "/etc/evil"),
        ("隐式 ..", "a/../b..c"),
        ("空 id", ""),
        ("超长 id", "a" * 129),
    ]
    for label, nid in bad_ids:
        try:
            cg.add(nid, "# 功能名：x\n# 正文：y", layer="knowledge")
            check(f"P0-1 拒绝 {label}", False, "未抛异常且写入成功")
        except ValueError:
            check(f"P0-1 拒绝 {label}", True)
        except Exception as e:  # noqa: BLE001
            check(f"P0-1 拒绝 {label}", False, f"异常类型错误: {type(e).__name__}: {e}")

    ok_ids = ["mem_1790156428627", "n00001", "mde_abcdef123456",
              "uuid-4f2b-9c.a-d", "a" * 128]
    ok = True
    for i, nid in enumerate(ok_ids):
        try:
            cg.add(nid, f"# 功能名：合法 {i}\n# 正文：白名单内存活样本 {i}",
                   layer="knowledge")
        except Exception as e:  # noqa: BLE001
            ok = False
            check(f"P0-1 合法 id {nid[:16]}… 照常写入", False,
                  f"{type(e).__name__}: {e}")
    check("P0-1 合法 id（存量 5 形态）照常写入", ok and _NODE_ID_RE.match("mem_1"))

    print("== P1-1 mdcg_* op 闸（能红无闸实现）==")
    from md_cg.security import Principal

    def principal_with(ops):
        return Principal(actor="auditor", clearance="secret",
                         can_write=True, role="recorder", auth_mode="test",
                         ops_allow=ops)

    # 只读令牌：mdcg_remember 必拒（能红：修复前无闸直接写入）
    cg.principal = principal_with(["read"])
    try:
        _dispatch(cg, "mdcg_remember", {"content": "# 功能名：越权\n# 正文：x",
                                        "layer": "contextual"})
        check("P1-1a 只读令牌 mdcg_remember 必拒", False, "未抛 AccessDenied")
    except Exception as e:  # noqa: BLE001
        check("P1-1a 只读令牌 mdcg_remember 必拒（AccessDenied）",
              type(e).__name__ == "AccessDenied",
              f"{type(e).__name__}: {e}")

    # ops_allow=None（不限）令牌：放行（兼容性——存量直构形态零影响；
    # _in_scope(None)=True 是「未声明=不限制」的既有语义）
    saved = cg.principal
    cg.principal = principal_with(None)
    try:
        res = _dispatch(cg, "mdcg_remember",
                        {"content": "# 功能名：兼容\n# 正文：不限令牌照常",
                         "layer": "contextual"})
        check("P1-1b ops_allow=None（不限）令牌照常放行", True)
    except Exception as e:  # noqa: BLE001
        check("P1-1b ops_allow=None（不限）令牌照常放行", False,
              f"{type(e).__name__}: {e}")
    finally:
        cg.principal = saved

    # 读令牌：读工具放行
    cg.principal = principal_with(["read"])
    try:
        res = _dispatch(cg, "mdcg_search", {"query": "星云"})
        check("P1-1c 读令牌读工具放行", not isinstance(res, dict) or not res.get("error"),
              str(res)[:120])
    except Exception as e:  # noqa: BLE001
        check("P1-1c 读令牌读工具放行", False, f"{type(e).__name__}: {e}")
    cg.principal = None

    # 映射完备性：mdcg_* 全部注册工具都被映射覆盖（防未来新增工具漏闸）
    from md_cg import mcp_server as ms
    import re as _re
    src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "mcp_server.py"), encoding="utf-8").read()
    registered = set(_re.findall(r'"name": "(mdcg_[a-z_]+)"', src))
    uncovered = sorted(registered - set(_MDCG_OP_REQUIRE) - {"mdcg_service_info"})
    check("P1-1d mdcg_* 注册工具全覆盖（除自描述 service_info）",
          not uncovered, f"uncovered={uncovered}")

    print("== P1-8 tarfile filter ==")
    src_cf = open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "scripts", "criteria_fingerprint.py"),
        encoding="utf-8").read()
    check("P1-8 extractall 显式 filter=\"data\"", 'extractall(tmp, filter="data")'
          in src_cf)

    # 清理
    import shutil
    shutil.rmtree(root, ignore_errors=True)

    print("\n" + "=" * 60)
    print(f"结果：PASS {PASS} / FAIL {FAIL}")
    if FAILS:
        for f in FAILS:
            print(f"  - {f}")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
