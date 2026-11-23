# -*- coding: utf-8 -*-
"""守卫 · 常驻循环自查：任何一次工具调用都顺手把它拉起来（2026-11-18）。

病灶（实机）：重启后心跳 ok，但本进程 `loop.running=false` ⇒ 心跳第七档
（主动队列）永不运行。启动期 `_start_sustain` 实测不总生效。

  S1 调一次 cg(op=info) 之后，loop 存在且 running=True
  S2 ensure 幂等：连调 3 次仍同一个 loop（不重复起线程）
  S3 MDCG_SUSTAIN=0 时尊重显式关闭（不起）
  S4 ensure 自身异常不外溢（不影响工具调用）
"""
import os
import shutil
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from md_cg import mcp_server, sustain  # noqa: E402
from md_cg.mdcos import MdCGOS  # noqa: E402

PASSED, FAILED = [], []


def ok(cond, name, detail=''):
    print(('  PASS ' if cond else '  FAIL ') + name + ('' if cond else '  ' + str(detail)[:170]))
    (PASSED if cond else FAILED).append(name)
    return bool(cond)


def main():
    print('=== 常驻循环自查守卫 ===')
    os.environ.pop('MDCG_SUSTAIN', None)
    T = tempfile.mkdtemp(prefix='susguard_')
    try:
        cg = MdCGOS(os.path.join(T, 'a'), actor='t')
        mcp_server.call_tool(cg, 'cg', {'op': 'info'})
        time.sleep(0.5)
        lp = sustain.get_loop(cg, 'md_cg')
        ok(lp is not None and lp.status().get('running') is True,
           'S1 一次 cg(op=info) 后 loop 已运行', None if lp is None else lp.status().get('running'))

        for _ in range(3):
            mcp_server.call_tool(cg, 'cg', {'op': 'info'})
        lp2 = sustain.get_loop(cg, 'md_cg')
        ok(lp2 is lp, 'S2 幂等：三次调用后仍是同一个 loop 对象')
    finally:
        sustain.stop_all()
        shutil.rmtree(T, ignore_errors=True)

    os.environ['MDCG_SUSTAIN'] = '0'
    T2 = tempfile.mkdtemp(prefix='susguard2_')
    try:
        cg2 = MdCGOS(os.path.join(T2, 'b'), actor='t')
        mcp_server.call_tool(cg2, 'cg', {'op': 'info'})
        ok(sustain.get_loop(cg2, 'md_cg') is None, 'S3 MDCG_SUSTAIN=0 时不起循环')
    finally:
        os.environ.pop('MDCG_SUSTAIN', None)
        sustain.stop_all()
        shutil.rmtree(T2, ignore_errors=True)

    class _Boom:
        root = '/nonexistent/boom'
        index = {'nodes': {}}
    try:
        mcp_server._ensure_sustain_quiet(_Boom())
        ok(True, 'S4 ensure 不抛（怪 root / 异常一律吞掉）')
    except Exception as e:  # noqa: BLE001
        ok(False, 'S4 ensure 不抛（怪 root / 异常一律吞掉）', e)

    print()
    print('守卫结果：%d 通过 / %d 失败' % (len(PASSED), len(FAILED)))
    return 0 if not FAILED else 1


if __name__ == '__main__':
    sys.exit(main())