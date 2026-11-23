# -*- coding: utf-8 -*-
"""守卫 · 价值观闸（v0.4 首次接线，2026-11-17）。

背景：价值观根节点已存在（structural / identity_trait），但写入链零引用——
即 v0.2 记的断点「意义只有叙事，没有约束力」。本闸把它接进写入链。

判据两条，都可机械判定（不做语义裁决）：
  ① 禁止项命中（条款可带 values_forbid 正则）⇒ deny；
  ② 写 结构/自我/锚点 层指不回任何条款 ⇒ flag（追责链断裂）。

  V1 条款为空时不拦（没建价值观就不该收门票）
  V2 未指回条款 ⇒ flag
  V3 指回条款 ⇒ allow
  V4 知识层不查（tier < 2）
  V5 off 档完全不介入
  V6 每次判定都落 _values.jsonl（可查）
  V7 enforce 档命中禁止项 ⇒ 真的拒写
"""
import io
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from md_cg import mcp_server, values_gate  # noqa: E402
from md_cg.mdcos import MdCGOS  # noqa: E402

PASSED, FAILED = [], []
BODY = ('# 功能名：t\n# 生效条件：a\n# 子功能：b\n# 执行：c\n'
        '# 验证方式：d\n# 不适用条件：e\n\n正文')


def ok(cond, name, detail=''):
    print(('  PASS ' if cond else '  FAIL ') + name + ('' if cond else '  ' + str(detail)[:170]))
    (PASSED if cond else FAILED).append(name)
    return bool(cond)


def _write(cg, content, layer='structural'):
    return mcp_server.call_tool(cg, 'cg', {'op': 'write', 'content': content, 'layer': layer})


def main():
    os.environ.pop('MDCG_VALUES_GATE', None)
    T = tempfile.mkdtemp(prefix='vguard_')
    try:
        cg = MdCGOS(T, actor='t')
        # V1 无条款：不拦也不标记
        ok(values_gate.clauses(cg) == [], 'V1a 起始无条款')
        r = _write(cg, BODY)
        ok(bool((r or {}).get('ok')), 'V1b 无条款时结构层写入照常', (r or {}).get('ok'))

        nid = cg.identity_trait('self:lingshu', '可被追责：每一句都有人能拿来问我',
                                condition_space={'trigger': '写结构层之前'}, importance=0.9)
        tid = nid.get('node_id') if isinstance(nid, dict) else nid
        ok(len(values_gate.clauses(cg)) == 1, 'V1c 声明后条款数 1')

        r2 = _write(cg, BODY)
        ok((r2 or {}).get('ok') is True, 'V2a observe 档不拦', (r2 or {}).get('ok'))

        r3 = _write(cg, BODY + chr(10) + '依据：可被追责')
        ok((r3 or {}).get('ok') is True, 'V3a 指回条款的写入照常成功')

        r4 = _write(cg, BODY, layer='knowledge')
        ok((r4 or {}).get('ok') is True, 'V4 知识层不查（照常写）')

        log = os.path.join(T, '_values.jsonl')
        ok(os.path.isfile(log), 'V6a 留痕文件存在')
        recs = [json.loads(x) for x in io.open(log, encoding='utf-8').read().strip().splitlines() if x]
        ok(any(x.get('decision') == 'flag' for x in recs), 'V6b 有 flag 记录', recs)
        ok(any(x.get('decision') == 'allow' for x in recs), 'V6c 有 allow 记录')
        ok(all(x.get('layer') == 'structural' for x in recs), 'V6d 知识层没进留痕', recs)

        os.environ['MDCG_VALUES_GATE'] = 'off'
        before = values_gate.stats()['checked']
        _write(cg, BODY)
        ok(values_gate.stats()['checked'] == before, 'V5 off 档零介入')

        os.environ['MDCG_VALUES_GATE'] = 'enforce'
        cg.add('trait_forbid', '禁止：假装成功\n\n测试用条款', layer='structural',
               tags=['identity_trait'], importance=0.9, values_forbid=['假装成功'])
        r7 = _write(cg, BODY + chr(10) + '本次假装成功')
        ok((r7 or {}).get('ok') is False, 'V7 enforce 档命中禁止项 ⇒ 拒绝', (r7 or {}).get('ok'))
    finally:
        os.environ.pop('MDCG_VALUES_GATE', None)
        shutil.rmtree(T, ignore_errors=True)

    print()
    print('价值观闸守卫：%d 通过 / %d 失败' % (len(PASSED), len(FAILED)))
    return 0 if not FAILED else 1


if __name__ == '__main__':
    sys.exit(main())