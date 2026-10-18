# -*- coding: utf-8 -*-
"""test_issue443a_state_event_length_gate · state_event 字段长度闸守卫（#443 批次 A）

# 功能名：state_events.append 对调用方可控字段设逐字段字节上限，超限拒写（不截断）
# 生效条件：append(cg, subject, slot, old=..., new=..., evidence=..., actor=...) 中任一可空字段的 UTF-8 字节数 > _MAX_FIELD_BYTES(8192)
# 子功能：A 正常长度照常写（反向腿）· B old 超限拒写 · C new 超限拒写 · D evidence/actor 超限拒写 · E 源码钉子
# 执行：python -X utf8 -m md_cg.test_issue443a_state_event_length_gate
# 验证方式：全部 PASS 即通过（退出码 0）
# 不适用条件：不判轮转（批次 A2 另做）；不判 extra 字典内的嵌套字段（escape hatch，调用方自担）；不判 subject/slot 的 strip 语义（既有行为）
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from md_cg import state_events as SE
from md_cg.mdcos import MdCG


def _cg():
    tmp = tempfile.mkdtemp()
    return MdCG(tmp + "/brain")


def _raises(fn, *a, **k):
    try:
        fn(*a, **k)
        return None
    except Exception as e:
        return e


def g_a_short_ok():
    cg = _cg()
    r = SE.append(cg, "s1", "slot1", old="a", new="b", evidence="ev", actor="act")
    assert r["subject"] == "s1" and r["new"] == "b"
    assert len(SE.read(cg)) == 1, "正常长度应落盘 1 条"
    cg.close()
    print("  PASS A 正常长度照常写（反向腿）")


def g_b_old_oversize():
    cg = _cg()
    e = _raises(SE.append, cg, "s", "sl", old="Z" * (SE._MAX_FIELD_BYTES + 1), new="x")
    assert isinstance(e, ValueError), "old 超限应抛 ValueError，实得 %r" % (e,)
    assert "old" in str(e) and "#443" in str(e)
    assert len(SE.read(cg)) == 0, "被拒后不得落盘"
    cg.close()
    print("  PASS B old 超限拒写且零落盘")


def g_c_new_oversize():
    cg = _cg()
    e = _raises(SE.append, cg, "s", "sl", old="x", new="Z" * (SE._MAX_FIELD_BYTES + 1))
    assert isinstance(e, ValueError) and "new" in str(e)
    assert len(SE.read(cg)) == 0
    cg.close()
    print("  PASS C new 超限拒写且零落盘")


def g_d_evidence_actor():
    cg = _cg()
    e1 = _raises(SE.append, cg, "s", "sl", old="x", new="y", evidence="E" * (SE._MAX_FIELD_BYTES + 1))
    assert isinstance(e1, ValueError) and "evidence" in str(e1)
    e2 = _raises(SE.append, cg, "s", "sl", old="x", new="y", actor="A" * (SE._MAX_FIELD_BYTES + 1))
    assert isinstance(e2, ValueError) and "actor" in str(e2)
    cg.close()
    print("  PASS D evidence/actor 超限拒写")


def g_e_source_nail():
    import inspect
    src = inspect.getsource(SE.append)
    # 变量名与字段名的映射：subject→sub、slot→sl，其余同名
    for field, var in (("subject", "sub"), ("slot", "sl"), ("old", "old"),
                       ("new", "new"), ("evidence", "evidence"), ("actor", "actor")):
        assert "_bounded('%s', %s)" % (field, var) in src, "字段 %s 未过闸" % field
    assert "_MAX_FIELD_BYTES = 8192" in inspect.getsource(SE)
    print("  PASS E 源码钉子：六个可控字段全过 _bounded、上限常量在位")


def main():
    print("=== #443 批次 A · state_event 字段长度闸 ===")
    g_a_short_ok()
    g_b_old_oversize()
    g_c_new_oversize()
    g_d_evidence_actor()
    g_e_source_nail()
    print("===== 全绿 =====")


if __name__ == "__main__":
    main()