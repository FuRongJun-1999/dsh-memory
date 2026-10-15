# -*- coding: utf-8 -*-
# 功能名：负条件判据 neg_condition_hits 的否定作用域与字符归一（issue #362 a/b/c）
# 生效条件：python -X utf8 -m md_cg.test_issue362_neg_condition [--mutate]；被测面＝md_cg/mdcg.py 的 neg_condition_hits（否定作用域 _negated_at + 归一 fold_for_match + 摘词面 _strip_variant）与 md_cg/routing.py 的 nfkc_text / fold_variants / 繁简折叠注入单点；直调判据面 + 资格/边界两面端到端
# 子功能：A 组＝#362 a/b 正题（否定句不误拒、全角/大小写 6/6 互通）；K 组＝非恒真对照（**过度收紧与过度放宽两个方向**：真负条件仍命中、`不适合X` 不被吞、不是A而是B、多次出现、自主题豁免/词长下限/全词分支仍在、不过度归一、归一既定后果留痕）；E 组＝判据单点（NFKC 实现全仓唯一、fold 走 routing 单点、neg 判据全仓唯一、normalize_domain 零位移）；C 组＝#362c 机制在位/数据待补；D 组＝#362d 取证（**不锁裁定**）
# 执行：--mutate 时在镜像树里逐条把判据改回缺陷形态／归一退化／过度放宽／过度收紧／单点分裂，守卫必须按指定项转红（多红/少红皆不合格）
# 验证方式：全部 PASS 即通过（退出码 0）；--mutate 下每条变异的红项集合须与预期逐项相符，锚点未命中即 fail-closed（打印 ANCHOR-MISS 并计入不合格）
# 不适用条件：① #362d 已按 Lead 裁定取**案②零破坏子形态**（证据并入顶层 reason、键集与 state 一字不动），D 组锁 D1–D6；**案①（不覆盖 REJECT）未采**、**案③（`is_boundary_query` 标记表过宽，「…适用吗，还是不适用」这类是非问句被「不适用」误判）为独立小项，本守卫不覆盖**；② #362c（繁简互通）**生产未生效**：仓内无既有繁简映射表，证据三重——(a) 全仓 grep `繁简|简繁|t2s|s2t|opencc|zhconv|traditional|simplified|hant|hans|big5` 仅命中 md_cg/bench_p0.py 的计时变量 t2s 与英文单词 traditional，无映射表；(b) 全仓 grep 常用繁体字 `個|說|會|這|對` 命中 **0**（真表不可能在这些字上零命中），`國` 仅 1 处、在 md_cg/lexicon/char_atoms_clean.json:31152 的 en_raw 注记「楚國|楚国」里，是个案不是表；(c) Python312 下 zhconv/opencc/hanziconv/zhon/langconv 的 find_spec 全为 None，且 .tmp/ 里 lingshu/core/condition_normalize.py 只做图像域同义词归一。故 c 只落机制（C1 注入表证明链路通），**数据待补**，C-BLOCKED 为如实登记的覆盖缺口；③ 不判非 CJK 的其它语种变体归一（希腊/阿拉伯变体等）；④ 不判 Rust 侧（无对应实现）；⑤ 不判 mdcos/_emit 的呈现面字段（本任务写面只有 mdcg.py/routing.py/本文件）
"""issue #362 守卫：负条件判据的否定作用域与字符归一（a/b/c）。

病象（修前，本守卫 A 组逐条复现）：
  a 否定句误拒（8/8）：neg=['梅雨季节'] + 「现在**不是**梅雨季节，需要防晒」
     ⇒ 命中 ⇒ 资格 REJECT。判据只做空白归一再整条子串匹配，**不看否定作用域**。
  b 全角/大小写不归一（6/6 漏拒）：４Ｇ单模终端 vs 4G单模终端、PDF 扫描件 vs
     pdf 扫描件——两侧只去空白，无 NFKC/casefold。
  c 繁简不互通（6/6 漏拒）：載貨電梯 vs 载货电梯。**本轮挂起**（见顶部不适用条件②）。

修法（判据单点，不新造第二份口径）：
  · 归一：routing.nfkc_text（NFKC 唯一单点，normalize_domain 同源）→
    routing.fold_variants（+ casefold + 繁简折叠表，表当前为空）→
    mdcg.fold_for_match（再 + 去全部空白）。两侧都过同一条链。
  · 否定作用域（#362a）：整条命中后**逐次出现**判 _negated_at——向前最多
    NEG_SCOPE_WINDOW 个字符内存在否定词，且否定词与被否定成分之间**只由
    连接字组成**（不是X / 不是这种X）才算否定；任一出现未被否定即命中。
    刻意**不**取「窗口内出现否定词就算否定」：那会把「不适合梅雨季节的施工」
    （真负条件）一起吞掉——过度收紧方向由 M3 定点变异钉住。

#362d（2026-10-14 Lead 裁定，案②零破坏子形态）：上面的 §5.2 不变量是 P0-4/P2-2 的
有意设计，不改；真正缺的是可观测性。故在「抑制确实发生 ∧ 未摘词面原判 REJECT」时，把
该证据并入既有顶层 reason 串——键集与 state 不动。案①（不覆盖 REJECT）未采，案③
（is_boundary_query 标记表过宽）列为独立小项、本守卫不覆盖。

本守卫的判别力来自四处**非恒真**对照，而不是「修完就绿」：
  K3（过度收紧）不适合X 仍须命中；K5（过度收紧）任一出现未被否定即命中；
  K11（既定后果留痕）罗马数字与德语 sharp s 的改写是 NFKC/casefold 的固有后果，显式钉住；
  D3（新证据不恒真）非边界问句下 reason 必须**不含**那条 REJECT 证据。
"""
from __future__ import annotations

import inspect
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

_TMP = tempfile.mkdtemp(prefix="iss362_")
os.environ.update({"MDCG_ROOT": os.path.join(_TMP, "brain"),
                   "MDCG_STATE_ROOT": os.path.join(_TMP, "state"),
                   "MDCG_AUX_ROOT": os.path.join(_TMP, "aux"),
                   "MDCG_DATA_ROOT": os.path.join(_TMP, "data"),
                   "MDCG_EXPORT_ROOT": _TMP,
                   "MDCG_SUSTAIN": "0", "MDCG_SLEEP": "0"})

from md_cg import mdcg as M                       # noqa: E402
from md_cg import routing as RT                   # noqa: E402
from md_cg.mdcg import MdCG, fold_for_match, neg_condition_hits   # noqa: E402

FAILS = []
PASSED = []


def _check(name, cond, detail=''):
    if cond:
        print("  PASS " + name)
        PASSED.append(name)
    else:
        print("  FAIL " + name + "  " + str(detail)[:260])
        FAILS.append(name)


def _note(text):
    print("  NOTE " + text)


def _scene(q, **ctx):
    d = {"query": q}
    d.update(ctx)
    return json.dumps(d, ensure_ascii=False)


def _hit(neg, q, own='', **ctx):
    return neg_condition_hits(neg, _scene(q, **ctx), own)


def _legacy_normalize_domain(raw):
    """#362 之前的**内联 NFKC** 版 normalize_domain（E6 等价性对照用）。

    刻意写在 test_*.py 里（E1 的单点扫描排除 test_*.py）：守卫需要**引用**那个
    字面量才能断言「真源只有一处」，不能在断言里就把它复制第二份。
    """
    if not raw:
        return RT.ORPHAN
    s = unicodedata.normalize("NFKC", str(raw)).strip()
    for _ in range(3):
        new = RT._INSTANCE_TAIL.sub("", s)
        if new == s:
            break
        s = new.strip()
    s = RT._SKELETON_TAIL.sub("", s).strip()
    s = re.sub(r"\s+", "_", s)
    return s or RT.ORPHAN


#: #362a 的语料条目（与 issue 正文同形）
NEG = ['梅雨季节']


def group_a():
    print("== A 组：#362 a/b 正题（否定句误拒 / 全角大小写不归一）==")
    _check('A1 a·紧邻否定「不是X」不计命中',
           not _hit(NEG, '现在不是梅雨季节，需要防晒'),
           _hit(NEG, '现在不是梅雨季节，需要防晒'))
    _check('A2 a·「不是X」在独立问句里同样不计命中',
           not _hit(NEG, '现在不是梅雨季节'), _hit(NEG, '现在不是梅雨季节'))
    _check('A3 a·「不是这种X」（否定词 + 连接字）不计命中',
           not _hit(NEG, '现在不是这种梅雨季节'),
           _hit(NEG, '现在不是这种梅雨季节'))
    _check('A4 b·全角条目 vs 半角情境', bool(_hit(['４Ｇ单模终端'], '4G单模终端怎么配')))
    _check('A5 b·半角条目 vs 全角情境', bool(_hit(['4G单模终端'], '４Ｇ单模终端怎么配')))
    _check('A6 b·全角含全角标点条目 vs 半角情境',
           bool(_hit(['ＵＳＢ２．０接口'], 'USB2.0接口')))
    _check('A7 b·半角条目 vs 全角情境', bool(_hit(['USB2.0接口'], 'ＵＳＢ２．０接口')))
    _check('A8 b·大写条目 vs 小写情境', bool(_hit(['PDF 扫描件'], 'pdf 扫描件')))
    _check('A9 b·小写条目 vs 大写情境', bool(_hit(['pdf 扫描件'], 'PDF 扫描件')))


def group_k():
    print("== K 组：非恒真对照（过度收紧 / 过度放宽两个方向）==")
    _check('K1 真负条件仍命中（肯定句）', bool(_hit(NEG, '现在是梅雨季节，需要防潮')))
    _check('K2 真负条件仍命中（词面在句中）',
           bool(_hit(NEG, '梅雨季节的施工方案要注意什么')))
    _check('K3 **过度收紧对照**：不适合X 的否定词作用在「适合」上，仍须命中',
           bool(_hit(NEG, '不适合梅雨季节的施工方案')),
           _hit(NEG, '不适合梅雨季节的施工方案'))
    _check('K4 不是A而是B：B 未被否定仍命中',
           bool(_hit(NEG, '现在不是旱季而是梅雨季节')))
    _check('K5 多次出现：任一出现未被否定即命中',
           bool(_hit(NEG, '不是梅雨季节，现在是梅雨季节')))
    _check('K6 自主题豁免仍在（本节点讲的就是它）',
           not _hit(['抓取管线'], '抓取管线的做法', '抓取管线的做法；问抓取管线时')
           and bool(_hit(['抓取管线'], '抓取管线的做法')),
           _hit(['抓取管线'], '抓取管线的做法', '抓取管线的做法；问抓取管线时'))
    _check('K7 词长下限仍在（单字符碎片不是拒绝理由）',
           not _hit(['抓'], '抓取管线的做法'))
    _check('K8a 全词命中分支仍在（词面齐全即命中）',
           bool(_hit(['其它 机器'], '机器 其它')))
    _check('K8b 全词命中分支仍在（缺一词不命中）', not _hit(['其它 机器'], '其它'))
    _check('K9 空列表 / 空条目 / 空白条目 / None 条目不命中',
           not _hit([], '任意问句') and not _hit([''], '任意问句')
           and not _hit(['   '], '任意问句') and not _hit([None], '任意问句'))
    _check('K10 **不过度归一**：标点与连字符不被折叠',
           not _hit(['C++'], '用 C 语言写') and not _hit(['A-B'], 'AB 两个字母'),
           (_hit(['C++'], '用 C 语言写'), _hit(['A-B'], 'AB 两个字母')))
    _check('K11 归一的既定后果留痕（NFKC/casefold 使然，刻意保留）',
           bool(_hit(['IV'], 'Ⅳ 是罗马数字')) and bool(_hit(['ß'], 'ss 这种写法')),
           (_hit(['IV'], 'Ⅳ 是罗马数字'), _hit(['ß'], 'ss 这种写法')))
    _check('K12 **过度收紧对照**：正反问 A-not-A（是不是X / 有没有X）不算否定，仍须命中',
           bool(_hit(NEG, '现在是不是梅雨季节'))
           and bool(_hit(['USB2.0接口'], '有没有 USB2.0 接口')),
           (_hit(NEG, '现在是不是梅雨季节'),
            _hit(['USB2.0接口'], '有没有 USB2.0 接口')))
    _check('K13 **反向对照**：真否定照旧被吞（并不是X / 他说不是X）',
           not _hit(NEG, '并不是梅雨季节') and not _hit(NEG, '他说不是梅雨季节'),
           (_hit(NEG, '并不是梅雨季节'), _hit(NEG, '他说不是梅雨季节')))


_TEST_PREFIX = 'test_'


def _py_sources():
    """md_cg 下的**非测试** Python 源码（相对路径, 文本）——E 组单点扫描面。

    为什么排除 test_*.py：守卫必须**引用** normalize(NFKC 那个字面量才能断言它
    全仓唯一（见 _legacy_normalize_domain），把守卫自己算进去会自伤。"""
    out = []
    root = os.path.join(_REPO, "md_cg")
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d != '__pycache__']
        for fn in sorted(filenames):
            if not fn.endswith('.py') or fn.startswith(_TEST_PREFIX):
                continue
            p = os.path.join(dirpath, fn)
            with open(p, encoding='utf-8', errors='replace') as f:
                out.append((os.path.relpath(p, _REPO).replace(os.sep, '/'),
                            f.read()))
    return out


_NFKC_MARK = 'normalize(' + chr(34) + 'NFKC' + chr(34)


def group_e():
    print("== E 组：判据单点（源码面）==")
    sites = []
    for rel, src in _py_sources():
        for i, line in enumerate(src.splitlines(), 1):
            if line.lstrip().startswith('#'):
                continue
            if _NFKC_MARK in line:
                sites.append((rel, i))
    _check('E1 NFKC 归一实现全仓唯一（排除 test_*.py；不得长出第二份口径）',
           len(sites) == 1 and sites[0][0] == "md_cg/routing.py", sites)
    fold_src = inspect.getsource(fold_for_match)
    _check('E2 fold_for_match 走 routing.fold_variants 单点（不新造一份全角/大小写处理）',
           'routing.fold_variants(' in fold_src, fold_src[:160])
    _check('E3 fold_variants 走 nfkc_text 单点',
           'nfkc_text(' in inspect.getsource(RT.fold_variants))
    _check('E4 judge_qualification 的负条件腿走 neg_condition_hits 单点',
           'neg_condition_hits(' in inspect.getsource(MdCG.judge_qualification))
    n_def = sum(len(re.findall(r'def neg_condition_hits', src))
                for _rel, src in _py_sources())
    _check('E5 neg_condition_hits 全仓唯一实现', n_def == 1, n_def)
    cases = ['数学分析知识点内容（按骨架填充）', '工程学 知识点（内力与截面法）',
             '高中物理知识点内容（按骨架填充） 知识点（贝塞尔不等式）',
             None, '', '  观察 位置  ']
    same = all(RT.normalize_domain(x) == _legacy_normalize_domain(x) for x in cases)
    _check('E6 normalize_domain 行为零位移（与 #362 前的内联 NFKC 逐字一致）', same,
           [(RT.normalize_domain(x), _legacy_normalize_domain(x)) for x in cases])


_TRAD_TEST = {'載': '载', '貨': '货', '電': '电', '腎': '肾'}


def group_c():
    print("== C 组：#362c 机制在位 / 数据待补（按 Lead 裁定：c 本轮挂起）==")
    old = RT.set_trad_to_simp(_TRAD_TEST)
    try:
        r1 = bool(_hit(['載貨電梯'], '载货电梯'))
        r2 = bool(_hit(['载货电梯'], '載貨電梯'))
        r3 = bool(_hit(['腎功能不全患者'], '肾功能不全患者'))
        r4 = bool(_hit(['肾功能不全患者'], '腎功能不全患者'))
    finally:
        RT.set_trad_to_simp(old)
    _check('C1 **非恒真对照**：注入测试用折叠表后，繁简互通链路即通（4/4）',
           r1 and r2 and r3 and r4, (r1, r2, r3, r4))
    _note('C-BLOCKED(待裁定)：生产表 routing.TRAD_TO_SIMP 当前为 %r ⇒ #362c 未生效；'
          '原因与三重证据见本文件顶部「不适用条件」②。表一旦有，C1 证明链路是通的。'
          % (RT.trad_to_simp(),))
    _note('C-BLOCKED 复现读数（应为 []，数据待补而非机制缺陷）：載貨電梯→%r / 载货电梯→%r'
          % (_hit(['載貨電梯'], '载货电梯'), _hit(['载货电梯'], '載貨電梯')))


_NEG_D = '梅雨季节'
_DOC_D = ('# 功能名：施工窗口选择' + chr(10)
          + '# 生效条件：问施工安排时' + chr(10)
          + '# 子功能：md_cg/mdcg.py' + chr(10)
          + '# 执行：读判据代码' + chr(10)
          + '# 验证方式：静态检查通过' + chr(10)
          + '# 不适用条件：%s' % _NEG_D)
_Q_D = '现在是梅雨季节吗，适用吗，还是不适用'


def _node_d():
    return {'frontmatter': {'non_applicable_conditions': [_NEG_D],
                            'verification_basis': 'test'},
            'content': _DOC_D}


def group_d():
    print("== D 组：#362d 案②已落（零破坏子形态）——证据在场 + 键集一字不动 ==")
    plain = MdCG.judge_qualification(_node_d(), _Q_D, None)
    jb = MdCG.judge_with_boundary(_node_d(), _Q_D, None)
    _check('D1 共同前提：未摘词面的资格判定仍是 REJECT（且该问句是边界问句）',
           plain['state'] == 'REJECT' and M.is_boundary_query(_Q_D) is True,
           (plain['state'], M.is_boundary_query(_Q_D)))
    _check('D2 案②证据在场：抑制确实发生 ⇒ 顶层 reason 里看得到「摘词面前原判 REJECT」',
           jb['qualification']['boundary_suppressed'] is True
           and '摘词面前原判 REJECT' in str(jb['reason']),
           (jb['qualification']['boundary_suppressed'], jb['reason']))
    nb = MdCG.judge_with_boundary(_node_d(), '现在是不是梅雨季节', None)
    _check('D3 **非恒真对照**：非边界问句下 reason 不含该证据（证据不恒真）',
           nb['qualification']['boundary_suppressed'] is False
           and '摘词面前原判' not in str(nb['reason']), nb['reason'])
    _check('D4 **零破坏子形态**：顶层/boundary/counts/qualification 键集逐项不变',
           set(jb) == {'qualification', 'boundary', 'counts', 'recallable', 'reason'}
           and set(jb['qualification']) == {'state', 'reason', 'boundary_suppressed'}
           and set(jb['boundary']) == {'hit', 'terms', 'marker', 'reason'}
           and set(jb['counts']) == {'accept', 'reject', 'defer', 'blindspot',
                                     'boundary_hit'},
           (sorted(jb), sorted(jb['qualification'])))
    _check('D5 §5.2 不变量仍成立：边界命中**不构成**资格否定（state 非 REJECT 且可召回）',
           jb['qualification']['state'] != 'REJECT' and jb['recallable'] is True,
           (jb['qualification']['state'], jb['recallable']))
    _check('D6 非边界问句口径零位移：state ≡ judge_qualification 的 state',
           nb['qualification']['state'] == MdCG.judge_qualification(
               _node_d(), '现在是不是梅雨季节', None)['state'],
           nb['qualification']['state'])
    _note('D7 当前读数（证据）：judge_qualification=%s；judge_with_boundary=%s'
          ' boundary_suppressed=%s recallable=%s counts=%s'
          % (plain['state'], jb['qualification']['state'],
             jb['qualification']['boundary_suppressed'], jb['recallable'],
             jb['counts']))
    _note('D7 **覆盖缺口（如实登记）**：reason 已带证据，但 mdcos.search_rrf 与 MdCG._emit'
          ' 都只取 qualification/counts，**不主动透出**该串；透出需改 md_cg/mdcos.py'
          '（不在本轮写面），交后续轮次或维护者。')
    _note('D7 三案（Lead 2026-10-14 已裁：取 ②）：① 不覆盖 REJECT ⇒ 破 §5.2 不变量 +'
          ' 转红 test_boundary_hit B1c/B2c/B3b/B4/B5b 与 test_p2_six_elements（两文件不在'
          ' 写面）+ 重开「问它何时不适用⇒它被否」的自否定 ⇒ 未采；② 零破坏子形态 ⇒'
          ' 本组 D2–D6 锁住；③ 报告例「…适用吗，还是不适用」是**是非问句**，被'
          ' BOUNDARY_QUERY_MARKERS 的「不适用」误判成边界问句 ⇒ **标记表过宽**，'
          ' Lead 列为独立小项，本守卫不覆盖。')


# ---- 定点变异表（镜像树里逐条把判据打回缺陷态／退化／过度收紧／过度放宽／单点分裂）
# 每条 (标签, 目标文件, ((现实现锚点, 改后), ...), 期望转红的检查 ID 集合)。
# 锚点缺失 → ANCHOR-MISS → fail-closed；红项集合与期望**逐项相符**才算合格。
_Q = chr(34)
_MUTATIONS = (
    ('M1 缺陷回退：整条命中后不判否定作用域（#362a 修前形态）', 'md_cg/mdcg.py',
     (('                if any(not _negated_at(scene_norm, k)'
       + chr(10) + '                       for k in _occurrences(scene_norm, item)):',
       '                if True:'),),
     ('A1', 'A2', 'A3', 'K13')),
    ('M2 过度放宽：否定作用域窗口缩到 2（「不是这种X」不再算紧邻）', 'md_cg/mdcg.py',
     (('NEG_SCOPE_WINDOW = 6', 'NEG_SCOPE_WINDOW = 2'),),
     ('A3',)),
    ('M3 过度收紧：不看紧邻连接字（窗口内出现否定词即算否定）', 'md_cg/mdcg.py',
     (('                if all(ch in NEG_LINK_CHARS for ch in s[j + len(cue):i]):',
       '                if True:'),),
     ('K3', 'K4')),
    ('M4 过度收紧：要求**每次**出现都被否定（任一未被否定即命中 → 全部）', 'md_cg/mdcg.py',
     (('                if any(not _negated_at(scene_norm, k)',
       '                if all(not _negated_at(scene_norm, k)'),),
     ('K5',)),
    ('M5 归一退化：fold_for_match 退回只做去空白（#362b 修前形态）', 'md_cg/mdcg.py',
     (('    return compact_exact_text(routing.fold_variants(text))',
       '    return compact_exact_text(text)'),),
     ('A4', 'A5', 'A6', 'A7', 'A8', 'A9', 'C1', 'E2', 'K11')),
    ('M6 判据退化：全词命中 all → any（单个通用词即整片否决）', 'md_cg/mdcg.py',
     (('        if words and all(w in scene_norm for w in words):',
       '        if words and any(w in scene_norm for w in words):'),),
     ('K8b',)),
    ('M7 单点分裂：fold_for_match 自写一份内联 NFKC（不走 routing 单点）', 'md_cg/mdcg.py',
     (('    return compact_exact_text(routing.fold_variants(text))',
       '    return compact_exact_text(' + chr(10)
       + '        __import__(' + _Q + 'unicodedata' + _Q + ').normalize(' + _Q + 'NFKC' + _Q + ', str(text))).casefold()'),),
     ('C1', 'E1', 'E2')),
    ('M8 案②回退：摘掉 reason 里的「未摘词面原判 REJECT」证据（可观测性缺失）',
     'md_cg/mdcg.py',
     (('            why += ("；**摘词面前原判 %s**（查询逐字含本节点的拒绝域条目，该 REJECT "'
       + chr(10) + '                    "被边界问句的摘词面抑制；边界命中使其可召回可展示）"'
       + chr(10) + '                    % STATE_REJECT)',
       '            why += ' + _Q + _Q),),
     ('D2',)),
    ('M9 过度收紧：取消正反问（A-not-A）豁免 ⇒「是不是X」被当成否定', 'md_cg/mdcg.py',
     (('        if j >= 1 and j + 1 < len(s) and s[j - 1] == s[j + 1]:',
       '        if False:'),),
     ('K12',)),
)


def _mirror_build():
    """镜像树：md_cg/scripts/根级 .py 拷到临时树——**绝不在真实工作树里改源**。"""
    dst = tempfile.mkdtemp(prefix='iss362_mut_')
    for name in ('md_cg', 'scripts'):
        src = os.path.join(_REPO, name)
        if os.path.isdir(src):
            shutil.copytree(src, os.path.join(dst, name),
                            ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    for name in sorted(os.listdir(_REPO)):
        p = os.path.join(_REPO, name)
        if os.path.isfile(p) and (name.endswith('.py')
                                  or name in ('README.md', 'pyproject.toml',
                                              'package.json')):
            shutil.copy2(p, os.path.join(dst, name))
    return dst


def _run_in(tree):
    env = dict(os.environ)
    env['PYTHONPATH'] = tree
    env['PYTHONUTF8'] = '1'
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    for k in ('MDCG_ROOT', 'MDCG_STATE_ROOT', 'MDCG_AUX_ROOT',
              'MDCG_DATA_ROOT', 'MDCG_EXPORT_ROOT', 'MDCG_INGEST_ROOT'):
        env.pop(k, None)
    pr = subprocess.run([sys.executable, '-X', 'utf8', '-m',
                         'md_cg.test_issue362_neg_condition'],
                        capture_output=True, text=True, encoding='utf-8',
                        errors='replace', cwd=tree, env=env, timeout=1800)
    out = (pr.stdout or '') + (pr.stderr or '')
    reds = [ln.split('FAIL ', 1)[1].strip()
            for ln in out.splitlines() if ln.strip().startswith('FAIL ')]
    return pr.returncode, reds, out


def _apply_text(text, rel, pairs):
    """按目标文件**实际行尾**折算锚点后逐条替换；任一锚点命中数 != 1 返回 (None, 原因)。"""
    eol = (chr(13) + chr(10)) if (chr(13) + chr(10)) in text else chr(10)
    for old, new in pairs:
        o = old.replace(chr(10), eol)
        n = new.replace(chr(10), eol)
        if text.count(o) != 1:
            return None, '锚点在 %s 里命中 %d 次' % (rel, text.count(o))
        text = text.replace(o, n, 1)
    return text, ''


def _mutate():
    print('!! 定点变异自证：逐条把判据改回缺陷形态／判据退化／过度放宽／过度收紧／单点分裂，守卫必须按指定项转红')
    tree = _mirror_build()
    bad = []
    try:
        rc, reds, out = _run_in(tree)
        print('  未变异镜像基线：rc=%d 红项=%d（必须 rc=0 且 0 红）' % (rc, len(reds)))
        if rc != 0 or reds:
            bad.append('未变异镜像基线即红')
            print(chr(10).join(out.splitlines()[-25:]))
        for desc, rel, pairs, exp in _MUTATIONS:
            p = os.path.join(tree, rel)
            with open(p, encoding='utf-8', newline='') as f:
                bak = f.read()
            mut, why = _apply_text(bak, rel, pairs)
            if mut is None:
                bad.append('%s —— %s' % (desc, why))
                print('  ANCHOR-MISS ' + desc + '  ' + why)
                continue
            with open(p, 'w', encoding='utf-8', newline='') as f:
                f.write(mut)
            for root, dd, ff in os.walk(tree):
                if os.path.basename(root) == '__pycache__':
                    shutil.rmtree(root, ignore_errors=True)
            rc2, reds2, out2 = _run_in(tree)
            with open(p, 'w', encoding='utf-8', newline='') as f:
                f.write(bak)
            hit = sorted({r.split(' ')[0] for r in reds2})
            if rc2 != 0 and hit == sorted(exp):
                print('  OK   %s  红项=%d 指定命中=%s' % (desc, len(reds2), hit))
            else:
                bad.append(desc)
                print('  MISMATCH %s  实际红项=%s  期望=%s  rc=%d'
                      % (desc, hit, sorted(exp), rc2))
                for r in reds2[:12]:
                    print('        FAIL ' + r)
        print('定点变异自证：%s（%d 条不合格）'
              % ('PASS' if not bad else 'FAIL', len(bad)))
        for b in bad:
            print('  不合格：' + b)
        return len(bad)
    finally:
        shutil.rmtree(tree, ignore_errors=True)


def main():
    group_a()
    group_k()
    group_e()
    group_c()
    group_d()
    print('=' * 68)
    print('#362 负条件判据守卫：%d 通过，%d 失败' % (len(PASSED), len(FAILS)))
    for f in FAILS:
        print('  红项：' + f)
    _bad = _mutate() if '--mutate' in sys.argv else 0
    return 1 if (FAILS or _bad) else 0


if __name__ == '__main__':
    sys.exit(main())
