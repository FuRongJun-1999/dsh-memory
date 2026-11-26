# -*- coding: utf-8 -*-
"""压缩／续接后重建入口（2026-11-26）。

压缩保留的是「被声明过的痕迹」，没留痕的等于不存在。
所以续接不能靠自觉，要有一个跑得出来、答得上/答不上的东西。

三步（顺序不可换）：
  1. 召回：常驻集 → 昨天快照 → 人物树枝索引（指针，不是正文）
  2. 声明：把召回结果说出口（声明本身就是抗压缩手段）
  3. 补窗：回取最近若干轮对话

退出码：0 = 三探针全过（可以继续干活）；1 = 有探针答不上（先重建再干活）。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _root(argv):
    for i, x in enumerate(argv):
        if x == '--root' and i + 1 < len(argv):
            return argv[i + 1]
    return (os.environ.get('MDCG_ROOT') or '').strip()


def main(argv=None):
    argv = list(argv if argv is not None else sys.argv[1:])
    root = _root(argv)
    if not root:
        print('need library root: pass --root or set MDCG_ROOT', file=sys.stderr)
        return 2
    from md_cg.mdcos import MdCGOS
    from md_cg import mcp_server
    cg = MdCGOS(root, actor='dsh')

    def _read(q, k=3):
        r = mcp_server.call_tool(cg, 'cg', {'op': 'read', 'query': q, 'k': k}) or {}
        return [((x or {}).get('node') or {}).get('id') for x in (r.get('results') or [])]

    print('=' * 46)
    print('1. 召回')
    print('=' * 46)
    core = cg.get('self_resident_core') or {}
    print('[常驻集]', 'OK' if core else 'MISSING', flush=True)
    if core:
        print((core.get('content') or '').strip())
    print()

    import datetime as _dt
    y = (_dt.date.today() - _dt.timedelta(days=1)).strftime('%Y%m%d')
    t0 = _dt.date.today().strftime('%Y%m%d')
    snap = cg.get('self_daily_' + y) or {}
    label = 'self_daily_' + y
    # 兜底：昨天没生成就退回今天（23:00 才生成，早上读的时候昨天的可能本来就没有）
    if not snap:
        snap = cg.get('self_daily_' + t0) or {}
        label = ('self_daily_' + t0 + '（今日兜底）') if snap else 'MISSING'
    print('[快照]', label, flush=True)
    if snap:
        body = (snap.get('content') or '').strip()
        print(body[:1200])
    print()

    br = cg.get('persona_branches') or {}
    print('[人物树枝]', 'OK' if br else 'MISSING', flush=True)
    if br:
        print((br.get('content') or '').strip()[:900])
    print()

    print('=' * 46)
    print('2. 声明 + 3. 探针')
    print('=' * 46)
    bad = []
    for name, q in (('P1 我是谁', '我是谁'),
                    ('P2 我的口径是什么', '我的口径是什么'),
                    ('P3 上次那条结论是什么', '上次那条结论是什么')):
        got = _read(q)
        good = bool(got) and (name.startswith('P3') or any(
            str(i).startswith(('identity_', 'persona_', 'self_', 'anchor_')) for i in got))
        print(('  PASS ' if good else '  FAIL ') + name + ' -> ' + str(got[:3]), flush=True)
        if not good:
            bad.append(name)
    print()
    if bad:
        print('结论：%d 个探针答不上 —— 先重建，别急着干活。' % len(bad))
        print('缺失：' + ' / '.join(bad))
        return 1
    print('结论：三探针全过。声明已输出，可以继续。')
    print('（下一步：回取最近 10 轮对话窗口补上下文）')
    return 0


if __name__ == '__main__':
    sys.exit(main())