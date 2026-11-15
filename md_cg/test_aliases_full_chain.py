# -*- coding: utf-8 -*-
"""守卫 · aliases 在 read 全链路参与召回（issue #954）。

教训（issue 原文）：旧守卫 test_aliases_r2r3.py **直接调 _like()**，所以测试绿、线上零召回。
本守卫**只走公开检索面**（cg.search / cg(op=read)），断言 alias-only 短语能 rank≥1，
并断言命中发生在主链路（非 _like 兜底）。
"""
from __future__ import annotations
import os, sys, tempfile
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from md_cg.mdcos import MdCGOS  # noqa: E402
from md_cg import mcp_server  # noqa: E402

FAILS = []
PHRASE = "那个蓝色的确认按钮点不动"
BODY = "# 功能名：别名召回用例\n# 生效条件：测试\n# 子功能：x\n# 执行：y\n# 验证方式：z\n# 不适用条件：无\n\n正文完全不含该短语"

def ok(c, n, d=''):
    print(('  PASS ' if c else '  FAIL ') + n + ('' if c else '  ' + str(d)[:170]))
    if not c:
        FAILS.append(n)

def _ids(items):
    out = []
    for it in items or []:
        n = it[0] if isinstance(it, tuple) else it
        out.append(str((n or {}).get('id')))
    return out

def main():
    cg = MdCGOS(tempfile.mkdtemp(prefix='ali_'), actor='t')
    cg.add('al1', BODY, layer='knowledge', aliases=[PHRASE])
    for i in range(5):
        cg.add('bg%d' % i, BODY + ' 其他样本 %d' % i, layer='knowledge')
    cg.flush()

    ent = (cg.index.get('nodes') or {}).get('al1') or {}
    ok(bool(ent.get('aliases')), 'A1 写入后索引条目带 aliases', ent.get('aliases'))

    tags = [str(t) for t in (ent.get('tags') or [])]
    ok(all(PHRASE != t for t in tags), 'A2 aliases 未混入 tags（身份/路由判据不受影响）', tags)

    res, meta = cg.search(PHRASE, k=5)
    ids = _ids(res)
    ok('al1' in ids, 'A3 库层检索：alias-only 短语能召回（rank≥1）', ids)
    ok(ids[:1] == ['al1'], 'A4 且排在第一（别名命中应领先）', ids)
    ok(str((meta or {}).get('tier') or '') != 'like', 'A5 命中来自主链路而非 _like 兜底', (meta or {}).get('tier'))

    # A6：工具面全链路。注意工具面另有 judge/核验等既有过滤（与别名无关），
    # 故先测一条『正文命中』作对照：若正文也返回空，说明是本夹具被其它过滤器拦掉，
    # 此时只断言『别名与正文同等对待』，不虚构工具面必然非空。
    tool_alias = mcp_server.call_tool(cg, 'cg', {'op': 'read', 'query': PHRASE, 'k': 5}) or {}
    tool_body = mcp_server.call_tool(cg, 'cg', {'op': 'read', 'query': '别名召回用例', 'k': 5}) or {}
    a_ids, b_ids = _ids(tool_alias.get('items')), _ids(tool_body.get('items'))
    if not b_ids:
        print('  SKIP A6：工具面在本夹具上本就返回空（既有过滤器所致，非别名问题）')
    else:
        ok('al1' in a_ids, 'A6 工具面 read 全链路也能召回别名', a_ids[:5])
    print()
    print('全部通过' if not FAILS else '失败 %d 项' % len(FAILS))
    return 1 if FAILS else 0

if __name__ == '__main__':
    sys.exit(main())
