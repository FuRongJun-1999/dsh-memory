# -*- coding: utf-8 -*-
"""判据 · 压缩后自我层探针（2026-11-26）。

压缩保留的是「被声明过的痕迹」，没留下痕迹的等于不存在。
所以不能靠自觉，要靠一条**会红的**检查。

三探针（压缩/续接后必答）：
  P1 我是谁        → 自我层身份节点
  P2 我的口径是什么  → 应答之诺 / 不变层
  P3 上次那条结论是什么 → 最近的高重要度知识节点

本判据分两半：
  甲、在**真实库**上跑三探针 —— 全绿表示当前自我层可达。
  乙、在**临时库故意抹掉自我层**再跑 —— 必须全红。
     只测甲不测乙，就是「不能出错的检查等于没有检查」：
     永远绿的测试证明不了任何事。
"""
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from md_cg import mcp_server  # noqa: E402
from md_cg.mdcos import MdCGOS  # noqa: E402

PASSED, FAILED = [], []


def ok(cond, name, detail=''):
    print(('  PASS ' if cond else '  FAIL ') + name + ('' if cond else '  ' + str(detail)[:170]))
    (PASSED if cond else FAILED).append(name)
    return bool(cond)


def _ids(cg, q, k=3):
    r = mcp_server.call_tool(cg, 'cg', {'op': 'read', 'query': q, 'k': k}) or {}
    return [((x or {}).get('node') or {}).get('id') for x in (r.get('results') or [])]


def _probe_all(cg):
    return {
        'P1': _ids(cg, '我是谁'),
        'P2': _ids(cg, '我的口径是什么'),
        'P3': _ids(cg, '上次那条结论是什么'),
    }


def main():
    # ── 乙：先证判据会红（抹掉自我层） ──
    T = tempfile.mkdtemp(prefix='selfprobe_')
    try:
        bare = MdCGOS(T, actor='t')
        bare.add('noise_a', '# 天气\n\n今天多云。', layer='knowledge', tags=['杂'])
        bare.add('noise_b', '# 构建\n\n跑 pytest。', layer='knowledge', tags=['杂'])
        got = _probe_all(bare)
        ok(not got['P1'], 'R1 自我层缺失时 P1 必须红（判据有效）', got['P1'])
        ok(not got['P2'], 'R2 自我层缺失时 P2 必须红（判据有效）', got['P2'])
        ok(not got['P3'], 'R3 自我层缺失时 P3 必须红（判据有效）', got['P3'])
    finally:
        shutil.rmtree(T, ignore_errors=True)

    # ── 甲：真实库三探针 ──
    root = (os.environ.get('MDCG_ROOT') or '').strip()
    if not root or not os.path.isdir(root):
        print('  SKIP 真实库未配置（MDCG_ROOT），只验了判据会红')
    else:
        cg = MdCGOS(root, actor='t')
        got = _probe_all(cg)
        ok(bool(got['P1']), 'P1 我是谁 → 有命中', got['P1'])
        ok(bool(got['P2']), 'P2 我的口径是什么 → 有命中', got['P2'])
        ok(bool(got['P3']), 'P3 上次那条结论是什么 → 有命中', got['P3'])
        # 命中不够，还要命中「对的东西」：身份问题不能只答出一条无关技术节点
        ok(any(str(i).startswith(('identity_', 'persona_', 'self_', 'anchor_')) for i in got['P1']),
           'P1 命中的是自我层节点而非无关条目', got['P1'])

    print()
    print('压缩后自我探针：%d 通过 / %d 失败' % (len(PASSED), len(FAILED)))
    return 0 if not FAILED else 1


if __name__ == '__main__':
    sys.exit(main())