# -*- coding: utf-8 -*-
"""test_issue545_charset_vs_size_diagnostic · 字符类违规不得被报成尺寸违规（#545）

# 功能名：writepipe._oversize_body 的 reason 分支 —— charset 口径不编造「> 上限」命题
# 生效条件：node_id 不匹配 mdcg._NODE_ID_RE（字符类），或长度超过 128
# 子功能：A 合法 id 放行 · B 字符类违规的 evidence 数学自洽（<= 而非 >）· C 尺寸违规仍是 > · D 源码钉子（reason 分支在位）
# 执行：python -X utf8 -m md_cg.test_issue545_charset_vs_size_diagnostic
# 验证方式：全部 PASS 即通过（退出码 0）
# 不适用条件：不判 hint 的措辞细节；不判其它字段（content/tags）的路径；不判 _NODE_ID_RE 本身（既有真源）
"""
import inspect
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from md_cg import writepipe


def g_a_legal_passes():
    assert writepipe.oversize_response("x", {"node_id": "method.foo_bar", "content": "y"}) is None
    assert writepipe.oversize_response("x", {"node_id": "中文.节点", "content": "y"}) is None
    print("  PASS A 合法 id 放行（反向腿）")


def _claim_gt(ev):
    """从 evidence 里抽出「N 字节 > 上限 M」，返回 (N, M) 或 None。"""
    m = re.search(r"(\d+) 字节 > 上限 (\d+)", ev)
    return (int(m.group(1)), int(m.group(2))) if m else None


def g_b_charset_evidence_consistent():
    r = writepipe.oversize_response("x", {"node_id": "method/foo", "content": "y"})
    assert r and r.get("field") == "node_id"
    ev = r["verdict"]["evidence"]
    assert "字符类契约" in ev, "字符类违规的 evidence 应点名字符类：%r" % ev
    gt = _claim_gt(ev)
    assert gt is None, "字符类违规不得声称「> 上限」：%r" % ev
    m = re.search(r"(\d+) 字节 <= 上限 (\d+)", ev)
    assert m, "应给出 <= 形态的读数：%r" % ev
    assert int(m.group(1)) <= int(m.group(2)), "读数本身应自洽：%r" % ev
    print("  PASS B 字符类违规的 evidence 数学自洽（%s <= %s）" % (m.group(1), m.group(2)))


def g_c_size_evidence_unchanged():
    r = writepipe.oversize_response("x", {"node_id": "a" * 200, "content": "y"})
    ev = r["verdict"]["evidence"]
    gt = _claim_gt(ev)
    assert gt, "尺寸违规仍应给「> 上限」：%r" % ev
    assert gt[0] > gt[1], "尺寸违规的读数应真的大于上限：%r" % ev
    print("  PASS C 尺寸违规仍是「%d 字节 > 上限 %d」（真命题）" % gt)


def g_d_source_nail():
    src = inspect.getsource(writepipe._oversize_body)
    assert "reason" in src, "_oversize_body 应有 reason 形参"
    assert "reason" in src, "_oversize_body 应有 reason 形参"
    # charset 分支体现在 else 腿上：非 size 即走字符类口径（不编造 > 上限）
    assert "reason" in src, "_oversize_body 应有 reason 形参"
    assert "<= 上限" in src, "charset 口径应用 <= 形态"
    so = inspect.getsource(writepipe.oversize_response)
    assert "reason=\"charset\"" in so, "调用点应传 reason=charset"
    print("  PASS D 源码钉子：reason 分支与调用点均在位")


def main():
    print("=== #545 字符类违规 vs 尺寸违规的诊断口径 ===")
    g_a_legal_passes()
    g_b_charset_evidence_consistent()
    g_c_size_evidence_unchanged()
    g_d_source_nail()
    print("===== 全绿 =====")


if __name__ == "__main__":
    main()