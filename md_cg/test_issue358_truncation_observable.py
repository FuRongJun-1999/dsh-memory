# -*- coding: utf-8 -*-
# 功能名：#358① 近重复比对的 MAX_COMPARE 截断必须可观测（candidate_total/truncated）
# 生效条件：python -u -X utf8 -m md_cg.test_issue358_truncation_observable [--mutate]
# 子功能：A1 超限落键（真值）· A2 未超限不落键（旧报文零变化）· A3 assess 透出
#         · A4 candidate_total 只计同层 · A5 exclude 不计入候选 · A6 边界
#         · A7 limit<=0 既有语义保留；E1 源码锚点自检
# 执行：直接跑；--mutate 时对 forgetting.py 做 4 条定点变异并要求指定红项非空
# 验证方式：断言全过 + 退出码 0；--mutate 下每条变异的红项集合必须非空且含指定项
# 不适用条件：① 不测「漏比本身是否被消除」——本件只钉**可观测**（修法明确不改
#   limit/比对顺序/裁决，见 #358 处置口径）；② 不测真实库性能（240 次读盘成本属
#   N276 性能面，另守卫）；③ 不覆盖 scrub/writepipe 的调用点读数形状。
"""#358① 守卫：截断可观测。"""
import argparse
import importlib.util
import os
import sys
import tempfile

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

PASSED, FAILS = [], []

_TARGET = ("# 功能名：末位目标\n# 生效条件：条件末位\n# 子功能：子功能末位\n"
           "# 执行：执行末位\n# 验证方式：test\n# 不适用条件：无\n\n"
           "末位目标节点唯一正文：蓝色按钮控制字符右移三格。")


def _fill(i):
    return ("# 功能名：填充%04d\n# 生效条件：条件%04d\n# 子功能：子功能%04d\n"
            "# 执行：执行%04d\n# 验证方式：test\n# 不适用条件：无\n\n"
            "填充节点%04d号正文：完全无关的内容%s。" % (i, i, i, i, i, "甲乙丙" * (i % 7 + 1)))


def _stub(n, dup_last=True, other_layer=0):
    """n 个同层候选（末位正文 = _TARGET）+ other_layer 个异层同文节点。"""
    contents = {"n%04d" % i: _fill(i) for i in range(n)}
    if dup_last and n:
        contents["n%04d" % (n - 1)] = _TARGET
    for j in range(other_layer):
        contents["o%04d" % j] = _TARGET

    class _Stub:
        def __init__(self):
            nodes = {"n%04d" % i: {"layer": "contextual"} for i in range(n)}
            for j in range(other_layer):
                nodes["o%04d" % j] = {"layer": "knowledge"}
            self.index = {"nodes": nodes}

        def get(self, nid, probe=True):
            return {"id": nid, "content": contents.get(nid, ""),
                    "frontmatter": {}}

    return _Stub()


def _suite(mod=None, label=''):
    """返回本次 (passed, failed) 局部列表；不污染模块级聚合。"""
    if label:
        print('-- %s --' % label)
    if mod is None:
        from md_cg import forgetting as mod
    red = mod.redundancy
    passed, failed = [], []

    def check(name, cond, detail=''):
        if cond:
            print('  PASS ' + name)
            passed.append(name)
        else:
            print('  FAIL ' + name + '  ' + str(detail)[:170])
            failed.append(name)
        return bool(cond)

    # A1：超限（301 候选 > 240）——两键必须落，且 candidate_total 是真值
    r1 = red(_stub(301), _TARGET, layer="contextual")
    check("A1a 超限：truncated=True", r1.get("truncated") is True, r1)
    check("A1b 超限：candidate_total=301（真值，不是 compared）",
          r1.get("candidate_total") == 301, r1)
    check("A1c 超限：compared=240（旧读数保留）", r1.get("compared") == 240, r1)
    check("A1d 超限：末位命中不在前 240 ⇒ with 不为末位（截断语义未改变）",
          r1.get("with") != "n0300", r1)

    # A2：未超限（5 候选）——不落两键，返回体与改动前逐位一致
    r2 = red(_stub(5), _TARGET, layer="contextual")
    check("A2a 未超限：无 truncated 键", "truncated" not in r2, r2)
    check("A2b 未超限：无 candidate_total 键", "candidate_total" not in r2, r2)
    check("A2c 未超限：compared=5 且命中末位", r2.get("compared") == 5
          and r2.get("with") == "n0004", r2)

    # A3：assess 的 entropy 透出 + reason 带截断提示
    a3 = mod.assess(_stub(301), _TARGET, layer="contextual", role="command",
                    importance_hint=0.1)
    ent = a3.get("entropy") or {}
    check("A3a assess.entropy.truncated=True（裁决读数可见）",
          ent.get("truncated") is True, ent)
    check("A3b assess.entropy.candidate_total=301",
          ent.get("candidate_total") == 301, ent)
    check("A3c assess.reason 带 truncated 提示（审计面可见）",
          "truncated" in str(a3.get("reason") or ""), a3.get("reason"))
    a3s = mod.assess(_stub(5), _TARGET, layer="contextual", role="command",
                     importance_hint=0.1)
    check("A3d 未截断时 entropy 不新增键（旧读数零变化）",
          "truncated" not in (a3s.get("entropy") or {})
          and "candidate_total" not in (a3s.get("entropy") or {}),
          a3s.get("entropy"))

    # A4：candidate_total 只数同层（异层 50 个同文节点不计）
    r4 = red(_stub(301, other_layer=50), _TARGET, layer="contextual")
    check("A4 candidate_total 只计同层候选（301，不是 351）",
          r4.get("candidate_total") == 301, r4)

    # A5：exclude 不计入候选
    r5 = red(_stub(301), _TARGET, layer="contextual", exclude="n0000")
    check("A5 exclude 后 candidate_total=300", r5.get("candidate_total") == 300, r5)

    # A6：边界——恰好 limit 个候选不报截断；多一个才报
    r6a = red(_stub(mod.MAX_COMPARE), _TARGET, layer="contextual")
    r6b = red(_stub(mod.MAX_COMPARE + 1), _TARGET, layer="contextual")
    check("A6a 候选数==limit：不报截断", "truncated" not in r6a, r6a)
    check("A6b 候选数==limit+1：报截断且 candidate_total=limit+1",
          r6b.get("truncated") is True
          and r6b.get("candidate_total") == mod.MAX_COMPARE + 1, r6b)

    # A7：limit<=0 的既有语义（只比首项即停）保留，且截断仍可观测
    r7 = red(_stub(301), _TARGET, layer="contextual", limit=0)
    check("A7 limit=0：compared=1（既有语义）且 truncated=True/candidate_total=301",
          r7.get("compared") == 1 and r7.get("truncated") is True
          and r7.get("candidate_total") == 301, r7)
    return passed, failed


def _mutations():
    src = open(os.path.join(_REPO, 'md_cg', 'forgetting.py'), encoding='utf-8').read()
    anchors = (
        ('M1 删截断落键块（回退为静默截断）',
         '    if scanned < candidate_total:\n'
         '        best["candidate_total"] = candidate_total\n'
         '        best["truncated"] = True\n',
         ''),
        ('M2 truncated 恒真（过度报告）',
         '    if scanned < candidate_total:',
         '    if True:'),
        ('M3 candidate_total 用 compared 冒充',
         '        best["candidate_total"] = candidate_total',
         '        best["candidate_total"] = n'),
        ('M4 assess 不透出截断读数',
         '    if red.get("truncated"):\n'
         '        entropy["candidate_total"] = red.get("candidate_total")\n'
         '        entropy["truncated"] = True',
         '    if False:\n'
         '        entropy["candidate_total"] = red.get("candidate_total")\n'
         '        entropy["truncated"] = True'),
    )
    out = []
    for tag, old, new in anchors:
        n = src.count(old)
        if n != 1:
            print('  [FAIL] 变异锚点「%s」命中 %d 次（应为 1）' % (tag, n))
            FAILS.append('变异锚点 ' + tag)
            continue
        out.append((tag, src.replace(old, new)))
    return out


def _load_mutant(text, tag):
    path = os.path.join(tempfile.mkdtemp(prefix='i358mut_'),
                        'forgetting_%s.py' % tag)
    open(path, 'w', encoding='utf-8').write(text)
    name = 'md_cg.forgetting_mut_%s' % tag
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


def _run_mutations():
    print('== 变异腿 ==')
    reds = {}
    expect = {
        'M1 删截断落键块（回退为静默截断）': 'A1a 超限：truncated=True',
        'M2 truncated 恒真（过度报告）': 'A2a 未超限：无 truncated 键',
        'M3 candidate_total 用 compared 冒充': 'A1b 超限：candidate_total=301（真值，不是 compared）',
        'M4 assess 不透出截断读数': 'A3a assess.entropy.truncated=True（裁决读数可见）',
    }
    for i, (tag, text) in enumerate(_mutations()):
        mod = _load_mutant(text, 'm%d' % i)
        _, fail = _suite(mod, label=tag)
        reds[tag] = sorted(fail)
        print('  %s ⇒ 红项 %s' % (tag, reds[tag]))
        if not fail:
            FAILS.append('变异未转红：' + tag)
        elif expect.get(tag) and expect[tag] not in fail:
            FAILS.append('变异红项不含指定项：' + tag)
    print('  变异红项集合：%s' % reds)
    return reds


def _anchor_selfcheck():
    src = open(os.path.join(_REPO, 'md_cg', 'forgetting.py'),
               encoding='utf-8').read()
    need = ('candidate_total', 'truncated', 'if scanned < candidate_total:',
            'entropy["truncated"] = True')
    miss = [x for x in need if x not in src]
    if miss:
        print('  ANCHOR-MISS 修复关键字面不在源码里：%s' % miss)
        return 2
    print('  PASS E1 源码锚点在位（candidate_total/truncated/条件落键/entropy 透出）')
    PASSED.append('E1 源码锚点在位')
    return 0


def main():
    ap = argparse.ArgumentParser(description='#358① 截断可观测守卫')
    ap.add_argument('--mutate', action='store_true', help='定点变异自证')
    args = ap.parse_args()
    print('== #358① 守卫 ==')
    rc = _anchor_selfcheck()
    if rc == 2:
        return 2
    try:
        ps, fs = _suite()
        PASSED.extend(ps)
        FAILS.extend(fs)
    except Exception as e:
        import traceback
        traceback.print_exc()
        FAILS.append('全套判据内异常（fail-closed）')
    if args.mutate:
        try:
            _run_mutations()
        except Exception as e:
            import traceback
            traceback.print_exc()
            FAILS.append('变异腿内异常（fail-closed）')
    print('=' * 60)
    print('#358① 守卫：%d 通过，%d 失败' % (len(PASSED), len(FAILS)))
    for f in FAILS:
        print('  红项：' + f)
    return 1 if FAILS else 0


if __name__ == '__main__':
    sys.exit(main())
