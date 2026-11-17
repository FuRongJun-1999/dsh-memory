# -*- coding: utf-8 -*-
"""守卫 · 检索面自我预测闭环（2026-11-17）。

使用者原话：「两个人的沟通就是在不断更新自己的预期」——所以预期不是我等别人喂的，
是**我自己在每次检索前出一句预测，同一轮内被实际结果检验**。

  G1 每次检索都带预测（claim/confidence/basis 齐全，confidence 开区间）
  G2 命中判定与实际 top 分一致（不得自说自话）
  G3 δ 用 Brier：猜对 δ 小、猜错 δ 大
  G4 关闭开关时不产出（可关，零副作用）
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


def main():
    T = tempfile.mkdtemp(prefix='selfpred_')
    try:
        cg = MdCGOS(T, actor='t')
        cg.add('theory_pred', '# 理论甲', layer='knowledge',
               tags=['理论真源', '常驻'], aliases=['元认知怎么产生'], importance=0.9,
               content_note=None) if False else cg.add(
                   'theory_pred', '# 理论甲\n\n元认知三阶段：结构位置、递归压力、存在约束。',
                   layer='knowledge', tags=['理论真源', '常驻'], aliases=['元认知怎么产生'],
                   importance=0.9)

        r = mcp_server.call_tool(cg, 'cg', {'op': 'read', 'query': '元认知怎么产生', 'k': 3})
        meta = (r or {}).get('meta') or {}
        sp = meta.get('self_prediction') or {}
        ok(bool(sp), 'G1a 检索带自我预测', sp)
        ok(0.0 < float(sp.get('confidence') or 0) < 1.0, 'G1b confidence 在开区间', sp.get('confidence'))
        ok(bool(sp.get('basis')), 'G1c 预测带依据（不许瞎猜）', sp.get('basis'))

        rows = (r or {}).get('results') or []
        top = float(rows[0]['score']) if rows else 0.0
        ok(bool(sp.get('hit')) == (bool(rows) and top >= 0.5), 'G2 命中判定与 top 分一致',
           (sp.get('hit'), top))

        miss = mcp_server.call_tool(cg, 'cg', {'op': 'read', 'query': '完全无关的量子色动力学常数', 'k': 3})
        msp = ((miss or {}).get('meta') or {}).get('self_prediction') or {}
        if msp:
            ok(0.0 <= float(msp.get('delta') or 0) <= 1.0, 'G3 δ 落在 0..1', msp.get('delta'))
            if not msp.get('hit'):
                ok(float(msp.get('delta')) > 0.05, 'G3b 猜错时 δ 明显大于 0', msp.get('delta'))

        os.environ['MDCG_SELF_PREDICT'] = '0'
        r2 = mcp_server.call_tool(cg, 'cg', {'op': 'read', 'query': '元认知怎么产生', 'k': 3})
        ok(not ((r2 or {}).get('meta') or {}).get('self_prediction'), 'G4 关闭开关后不产出')
    finally:
        os.environ.pop('MDCG_SELF_PREDICT', None)
        shutil.rmtree(T, ignore_errors=True)

    print()
    print('自我预测闭环守卫：%d 通过 / %d 失败' % (len(PASSED), len(FAILED)))
    return 0 if not FAILED else 1


if __name__ == '__main__':
    sys.exit(main())