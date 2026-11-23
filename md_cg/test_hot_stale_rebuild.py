# -*- coding: utf-8 -*-
"""守卫 · 热层陈旧必须能重建（2026-11-22，#1002 回归）。

a6870f09（PR #983 补完）修了「热层从不构建」，但同时写死了两件事：
  ① 调用点只判「热层存在」，不问「新不新鲜」⇒ is_fresh 的正确判据无人读；
  ② _HOT_BUILD 是进程级终态位 ⇒ 建过一次之后永远不再建。
后果：几小时前的热层**直接作答**，新写入的记忆结构上不可能出现在答案里。
危险形状是「旧内容强命中」——有结果、看起来正常、但时间窗过期。

  S1 新鲜时：判新鲜、走热层、meta.stale=False
  S2 写一条后：立刻判不新鲜（靠索引指纹，不是靠 TTL 蒙过去）
  S3 陈旧超宽限（MDCG_HOT_STALE_OK_S=0）：不直答热层，回落主库
  S4 陈旧未超宽限：仍可直答，但 meta.stale=True 且 hint 明说「已陈旧」
  S4d/E scope=hot（明示只看热层）不因陈旧白屏，但仍自曝陈旧与 stale_reason
  S5 重建不是一次性：冷却过后陈旧会**再次**触发后台重建
  S6 懒建调用点单点化（AST 计数，不数注释）
  S7 重建连续失败 ≥3 次 ⇒ 降级为「带标注的旧快照」，不再每次打回 24 秒主库

夹具注意：热层只收 self/anchor/近 7 天 contextual/importance≥0.7，
故夹具节点必须给 importance=0.9，否则永远进不了热层（首版测试就栽在这）。
复审教训（2026-11-22 蜂巢验证单元）：wait_build 曾把 error 当成功，
S3b/S3c/S5b 在重建持续报错时全绿——现在一律要求 error is None。
"""
import ast
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
Q = '递归压力 存在约束'


def ok(cond, name, detail=''):
    print(('  PASS ' if cond else '  FAIL ') + name + ('' if cond else '  ' + str(detail)[:200]))
    (PASSED if cond else FAILED).append(name)
    return bool(cond)


def wait_build(t=10.0):
    """等后台构建落定。返回 'done' / 'error' / 'timeout' —— 不把 error 当成功。"""
    end = time.time() + t
    while time.time() < end:
        if not mcp_server._HOT_BUILD['running']:
            if mcp_server._HOT_BUILD['error']:
                return 'error'
            if mcp_server._HOT_BUILD['done']:
                return 'done'
        time.sleep(0.05)
    return 'timeout'


def fresh(cg):
    return mcp_server._hot_state(cg)[1]


def call(cg, **kw):
    args = {'op': 'read', 'query': Q, 'k': 3}
    args.update(kw)
    return mcp_server._try_hot_first(cg, args, args['query'])


def main():
    T = tempfile.mkdtemp(prefix='hotstale_')
    try:
        cg = MdCGOS(T, actor='t')
        cg.add('theory_a', '# 理论甲\n\n递归压力 存在约束 两个词都命中。',
               layer='knowledge', importance=0.9)
        mcp_server._HOT_BUILD.update({'started': False, 'done': False, 'error': None,
                                      'running': False, 'last': 0.0, 'builds': 0, 'fails': 0})
        hottier.ensure(cg)

        e1, f1, _h1 = mcp_server._hot_state(cg)
        ok(e1 and f1, 'S1a 刚建好：存在且新鲜', (e1, f1))
        r1 = call(cg)
        ok((r1 or {}).get('source') == 'hot', 'S1b 新鲜时走热层', (r1 or {}).get('source'))
        hf = ((r1 or {}).get('meta') or {}).get('hot_first') or {}
        ok(hf.get('stale') is False, 'S1c meta.stale=False', hf)
        ok(hf.get('built_age_s') is not None, 'S1d built_age_s 有值', hf)

        cg.add('theory_b', '# 理论乙\n\n新写入的一条，陈旧热层里没有它。',
               layer='knowledge', importance=0.9)
        e2, f2, _ = mcp_server._hot_state(cg)
        ok(e2 and not f2, 'S2 写一条后立刻判不新鲜（索引指纹）', (e2, f2))

        # S3：严格模式（宽限 0）⇒ 陈旧即回落主库
        os.environ['MDCG_HOT_STALE_OK_S'] = '0'
        mcp_server._HOT_BUILD['last'] = 0.0
        ok(call(cg) is None, 'S3a 陈旧超宽限：不给热层答案（由主库作答）')
        ok(wait_build() == 'done', 'S3b 该次调用顺带触发了后台重建', mcp_server._HOT_BUILD)
        ok(mcp_server._HOT_BUILD['builds'] >= 1, 'S3c 重建计数增加', mcp_server._HOT_BUILD)
        ok(fresh(cg), 'S3d 重建后回到新鲜（下一轮自然命中）')

        # S4：宽限放大 ⇒ 陈旧仍直答，但必须自曝陈旧
        os.environ['MDCG_HOT_STALE_OK_S'] = '3600'
        cg.add('theory_c', '# 理论丙\n\n再写一条制造陈旧。', layer='knowledge', importance=0.9)
        mcp_server._HOT_BUILD['last'] = 0.0
        r4 = call(cg)
        ok((r4 or {}).get('source') == 'hot', 'S4a 陈旧未超宽限：仍可直答', (r4 or {}).get('source'))
        hf4 = ((r4 or {}).get('meta') or {}).get('hot_first') or {}
        ok(hf4.get('stale') is True, 'S4b meta.stale=True（自曝陈旧）', hf4)
        ok('陈旧' in ((r4 or {}).get('hint') or ''), 'S4c hint 明说已陈旧', (r4 or {}).get('hint'))

        # S4d/E：scope=hot 不因陈旧白屏（先等后台落定，避免读到半写状态）
        wait_build()
        cg.add('theory_e', '# 理论戊\n\n再制造一次陈旧。', layer='knowledge', importance=0.9)
        os.environ['MDCG_HOT_STALE_OK_S'] = '0'
        mcp_server._HOT_BUILD['last'] = 0.0
        r4d = call(cg, scope='hot')
        ok((r4d or {}).get('source') == 'hot', 'S4d scope=hot 陈旧超宽限也不白屏', (r4d or {}).get('source'))
        hf4d = ((r4d or {}).get('meta') or {}).get('hot_first') or {}
        ok(hf4d.get('stale') is True and hf4d.get('stale_reason') == 'stale_window',
           'S4e scope=hot 同样标 stale 且给 stale_reason', hf4d)

        # S5：重建不是一次性 —— 冷却过后 stale 仍会再次触发
        wait_build()
        before = int(mcp_server._HOT_BUILD['builds'])
        cg.add('theory_d', '# 理论丁\n\n又写一条。', layer='knowledge', importance=0.9)
        mcp_server._HOT_BUILD['last'] = 0.0
        call(cg)
        ok(wait_build() == 'done', 'S5a 第二次陈旧也能重建完成', mcp_server._HOT_BUILD)
        ok(int(mcp_server._HOT_BUILD['builds']) > before, 'S5b 重建计数再增（非进程终态）',
           (before, mcp_server._HOT_BUILD['builds']))
        ok(fresh(cg), 'S5c 重建后回到新鲜')

        # S8：判据自身的护栏（复审 P0-1 后半）
        os.environ['MDCG_HOT_STALE_OK_S'] = 'inf'
        ok(mcp_server._hot_stale_ok() == mcp_server._HOT_STALE_OK, 'S8a 宽限 env=inf 回落缺省',
           mcp_server._hot_stale_ok())
        os.environ['MDCG_HOT_STALE_OK_S'] = 'nan'
        ok(mcp_server._hot_stale_ok() == mcp_server._HOT_STALE_OK, 'S8b 宽限 env=nan 回落缺省')
        import math
        ok(math.isinf(mcp_server._age_of({})), 'S8c 缺 built_at ⇒ inf（不是 1.79e9）',
           mcp_server._age_of({}))
        ok(math.isinf(mcp_server._age_of({'meta': {'built_at': 0}})), 'S8d built_at=0 ⇒ inf')

        # S6：懒建调用点单点化（AST 计数，不数注释）
        src_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'mcp_server.py')
        tree = ast.parse(open(src_path, encoding='utf-8').read())
        calls = [n for n in ast.walk(tree)
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                 and n.func.id == '_ensure_hot_async']
        # 合法调用点恰好两处：_try_hot_first（读路径）与 dispatch 尾部（理论/自指绕过热层那条）。
        # 原 bug 是同一段代码在一次改动里被**粘贴两遍**（相隔不到 10 行）；这里断言总数为 2
        # 即同时覆盖「去重成功」与「没有误删另一条合法入口」。
        ok(len(calls) == 2, 'S6 懒建调用点恰好两处（AST 计数，粘贴副本已去重）', len(calls))

        # S7：重建连续失败 ⇒ 不把每次 read 都打回主库，而是带标注降级
        orig_ensure = hottier.ensure
        hottier.ensure = lambda *a, **k: (_ for _ in ()).throw(RuntimeError('boom'))
        try:
            # 先把热层弄陈旧，再让重建失败——顺序反了测不到（首版就错在这）
            cg.add('theory_f', '# 理论己\n\n制造陈旧，且重建会失败。', layer='knowledge', importance=0.9)
            os.environ['MDCG_HOT_STALE_OK_S'] = '0'
            mcp_server._HOT_BUILD['fails'] = 3
            mcp_server._HOT_BUILD['last'] = 0.0
            r7 = call(cg)
            ok((r7 or {}).get('source') == 'hot', 'S7a 重建连续失败：降级为直答不清空', (r7 or {}).get('source'))
            hf7 = ((r7 or {}).get('meta') or {}).get('hot_first') or {}
            ok(hf7.get('stale_reason') == 'rebuild_failed', 'S7b stale_reason=rebuild_failed', hf7)
            ok('重建连续失败' in ((r7 or {}).get('hint') or ''), 'S7c hint 说明重建失败', (r7 or {}).get('hint'))
        finally:
            hottier.ensure = orig_ensure
    finally:
        os.environ.pop('MDCG_HOT_STALE_OK_S', None)
        mcp_server._HOT_BUILD.update({'started': False, 'done': False, 'error': None,
                                      'running': False, 'last': 0.0, 'fails': 0})
        shutil.rmtree(T, ignore_errors=True)

    print()
    print('热层陈旧重建守卫：%d 通过 / %d 失败' % (len(PASSED), len(FAILED)))
    return 0 if not FAILED else 1


if __name__ == '__main__':
    sys.exit(main())
