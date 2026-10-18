# -*- coding: utf-8 -*-
"""test_issue443b_audit_record_length_gate · 审计/台账单条记录总字节闸（#443 批次 B）

# 功能名：insight._append 与 identity.log 在 append_jsonl 前过 fsutil.bounded_record（单条总字节闸）
# 生效条件：rec 经 json.dumps(ensure_ascii=False) 后的 UTF-8 字节数 > fsutil._MAX_RECORD_BYTES(65536)
# 子功能：A 正常记录照常写（反向腿）· B insight 超限跳过写 · C identity 超限跳过写 · D 源码钉子
# 执行：python -X utf8 -m md_cg.test_issue443b_audit_record_length_gate
# 验证方式：全部 PASS 即通过（退出码 0）
# 不适用条件：不判轮转（批次 A2/B2 另做）；不判 extra 嵌套字段的逐字段上限（本闸按整条总字节算）；不判 fsutil.append_jsonl 自身的严格模式（既有行为）
"""
import inspect
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from md_cg import fsutil
from md_cg import identity
from md_cg import insight
from md_cg.mdcos import MdCG


def _cg():
    tmp = tempfile.mkdtemp()
    return MdCG(tmp + "/brain")


def g_a_short_ok():
    cg = _cg()
    rec = {"k": "v", "n": 1}
    assert fsutil.bounded_record(rec) is True, "小记录应放行"
    insight._append(cg, {"kind": "t", "detail": "ok"})
    identity.log(cg, {"action": "x"})
    cg.close()
    print("  PASS A 正常记录照常写（反向腿）")


def g_b_insight_oversize():
    cg = _cg()
    big = {"kind": "t", "detail": "Z" * (fsutil._MAX_RECORD_BYTES + 1)}
    assert fsutil.bounded_record(big) is False, "超限记录应被判不可写"
    before = os.path.getsize(insight.log_path(cg)) if os.path.exists(insight.log_path(cg)) else 0
    insight._append(cg, big)
    after = os.path.getsize(insight.log_path(cg)) if os.path.exists(insight.log_path(cg)) else 0
    assert after == before, "超限记录不得写入（%d -> %d）" % (before, after)
    cg.close()
    print("  PASS B insight 超限跳过写且盘面零增长")


def g_c_identity_oversize():
    cg = _cg()
    big = {"action": "x", "raw": "Z" * (fsutil._MAX_RECORD_BYTES + 1)}
    before = os.path.getsize(os.path.join(cg.root, identity.AUDIT_FILE)) if os.path.exists(os.path.join(cg.root, identity.AUDIT_FILE)) else 0
    identity.log(cg, big)
    after = os.path.getsize(os.path.join(cg.root, identity.AUDIT_FILE)) if os.path.exists(os.path.join(cg.root, identity.AUDIT_FILE)) else 0
    assert after == before, "超限记录不得写入（%d -> %d）" % (before, after)
    cg.close()
    print("  PASS C identity 超限跳过写且盘面零增长")


def g_d_source_nail():
    si = inspect.getsource(insight._append)
    assert "bounded_record" in si, "insight._append 未过闸"
    sii = inspect.getsource(identity.log)
    assert "bounded_record" in sii, "identity.log 未过闸"
    src = inspect.getsource(fsutil)
    assert "_MAX_RECORD_BYTES = 65536" in src
    assert "def bounded_record(rec) -> bool" in src
    print("  PASS D 源码钉子：两处调用点均过闸、上限常量与函数在位")


def main():
    print("=== #443 批次 B · 审计/台账单条记录总字节闸 ===")
    g_a_short_ok()
    g_b_insight_oversize()
    g_c_identity_oversize()
    g_d_source_nail()
    print("===== 全绿 =====")


if __name__ == "__main__":
    main()