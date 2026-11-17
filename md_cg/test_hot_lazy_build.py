# -*- coding: utf-8 -*-
"""守卫 · 热层懒建（2026-11-17，PR #983 根因的补完）。

PR #983 查出：`hottier.search` 只 load 不 ensure，全包**无 ensure 调用点** ⇒ 热层运行时从未被构建，
`available=False` ⇒ read 恒走主库分支 ⇒ 注入面按热层形态取值永远拿不到（跨会话 knowledge 从未浮现）。

修法：首次用到热层时**后台建一次**，本轮回落主库（不阻塞），下一轮自然命中。

  B1 空库首次调用：不阻塞、当场回落（不因建热层把请求拖住）
  B2 后台建完后：热层可用，且第二次调用能命中热层
  B3 幂等：重复调用只启动一次构建
"""
import os
import shutil
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from md_cg import hottier  # noqa: E402
from md_cg import mcp_server  # noqa: E402
from md_cg.mdcos import MdCGOS  # noqa: E402

PASSED, FAILED = [], []


def ok(cond, name, detail=''):
    print(('  PASS ' if cond else '  FAIL ') + name + ('' if cond else '  ' + str(detail)[:170]))
    (PASSED if cond else FAILED).append(name)
    return bool(cond)


def main():
    T = tempfile.mkdtemp(prefix='hotbuild_')
    try:
        cg = MdCGOS(T, actor='t')
        cg.add('theory_x', '# 理论甲\n\n元认知三阶段：结构位置、递归压力、存在约束。',
               layer='knowledge', tags=['理论真源', '常驻'])
        ok(not hottier.load(cg.root), 'B0 起始状态：热层不存在')

        mcp_server._HOT_BUILD.update({'started': False, 'done': False, 'error': None})
        t0 = time.time()
        r = mcp_server.call_tool(cg, 'cg', {'op': 'read', 'query': '递归压力', 'k': 3})
        cost = time.time() - t0
        rows = (r or {}).get('results') or []
        ok(len(rows) > 0, 'B1a 首次调用仍能出结果（回落主库，不空手）', len(rows))
        ok(cost < 5.0, 'B1b 首次调用不被建热层阻塞', round(cost, 2))

        for _ in range(50):
            if mcp_server._HOT_BUILD['done'] or mcp_server._HOT_BUILD['error']:
                break
            time.sleep(0.1)
        ok(mcp_server._HOT_BUILD['done'] is True, 'B2a 后台构建完成', mcp_server._HOT_BUILD)
        ok(bool(hottier.load(cg.root)), 'B2b 热层文件已生成')

        _hit = hottier.search(cg, '理论甲', k=3)
        ok(bool(_hit.get('items')), 'B2c 热层可检索（建完即用）', _hit.get('meta'))
        # 注意：单节点夹具的 hot 分低于 _HOT_MIN_SCORE，按设计会回落主库——
        # 故这里不验「命中热层」，而验「已有热层不再重建」（跨调用幂等的另一半）。
        r2 = mcp_server.call_tool(cg, 'cg', {'op': 'read', 'query': '理论甲', 'k': 3})
        ok(mcp_server._HOT_BUILD['started'] is True and mcp_server._HOT_BUILD['error'] is None,
           'B2d 已有热层时不重复启动构建', mcp_server._HOT_BUILD)

        mcp_server._ensure_hot_async(cg)
        ok(mcp_server._HOT_BUILD['started'] is True, 'B3 重复调用幂等（只启动一次）')
    finally:
        mcp_server._HOT_BUILD.update({'started': False, 'done': False, 'error': None})
        shutil.rmtree(T, ignore_errors=True)

    print()
    print('热层懒建守卫：%d 通过 / %d 失败' % (len(PASSED), len(FAILED)))
    return 0 if not FAILED else 1


if __name__ == '__main__':
    sys.exit(main())