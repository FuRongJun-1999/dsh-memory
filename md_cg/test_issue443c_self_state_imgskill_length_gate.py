# -*- coding: utf-8 -*-
"""test_issue443c_self_state_imgskill_length_gate · 批次 C 两落点长度闸（#443）

# 功能名：self_state._append_log 与 imgskill._audit_write 对单条记录设总字节闸
# 生效条件：rec 序列化后 UTF-8 字节数超过上限（self_state 走 fsutil._MAX_RECORD_BYTES；imgskill 走本地 _MAX_AUDIT_RECORD_BYTES）
# 子功能：A 正常记录照常写 · B self_state 超限跳过写 · C imgskill 超限返回结构化 code 且零落盘 · D 源码钉子（含两处常量相等）
# 执行：python -X utf8 -m md_cg.test_issue443c_self_state_imgskill_length_gate
# 验证方式：全部 PASS 即通过（退出码 0）
# 不适用条件：不判轮转（另立）；不判 imgskill 的 TOCTOU/符号链接判定（既有 #352-C 语义）；不判 extra 嵌套字段
"""
import inspect
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from md_cg import fsutil
from md_cg import imgskill
from md_cg import self_state
from md_cg.mdcos import MdCG


def _cg():
    return MdCG(tempfile.mkdtemp() + "/brain")


def g_a_short_ok():
    cg = _cg()
    self_state._append_log(cg, {"subject": "s", "slot": "sl"})
    assert len(self_state.history(cg)) >= 1, "正常记录应落盘"
    out = imgskill._audit_write(cg.root, {"op": "x", "ok": True})
    assert not (isinstance(out, dict) and out.get("code") == "audit_record_too_large")
    cg.close()
    print("  PASS A 正常记录照常写（反向腿）")


def g_b_self_state_oversize():
    cg = _cg()
    p = self_state.log_path(cg)
    before = os.path.getsize(p) if os.path.exists(p) else 0
    self_state._append_log(cg, {"subject": "s", "blob": "Z" * (fsutil._MAX_RECORD_BYTES + 1)})
    after = os.path.getsize(p) if os.path.exists(p) else 0
    assert after == before, "超限记录不得写入（%d -> %d）" % (before, after)
    cg.close()
    print("  PASS B self_state 超限跳过写且盘面零增长")


def g_c_imgskill_oversize():
    root = tempfile.mkdtemp()
    out = imgskill._audit_write(root, {"op": "x", "blob": "Z" * (imgskill._MAX_AUDIT_RECORD_BYTES + 1)})
    assert isinstance(out, dict), "超限应返回结构化结果"
    assert out.get("code") == "audit_record_too_large", "code 不符：%r" % (out,)
    assert out.get("detail") == imgskill._MAX_AUDIT_RECORD_BYTES
    print("  PASS C imgskill 超限返回结构化 code（fail-open 且不静默）")


def g_d_source_nail():
    assert "bounded_record" in inspect.getsource(self_state._append_log)
    si = inspect.getsource(imgskill._audit_write)
    assert "_MAX_AUDIT_RECORD_BYTES" in si and "audit_record_too_large" in si
    assert imgskill._MAX_AUDIT_RECORD_BYTES == fsutil._MAX_RECORD_BYTES, \
        "两处上限常量必须相等，否则单方面漂移"
    print("  PASS D 源码钉子：两处过闸、两处常量相等（%d）" % fsutil._MAX_RECORD_BYTES)


def main():
    print("=== #443 批次 C · self_state / imgskill 单条记录总字节闸 ===")
    g_a_short_ok()
    g_b_self_state_oversize()
    g_c_imgskill_oversize()
    g_d_source_nail()
    print("===== 全绿 =====")


if __name__ == "__main__":
    main()