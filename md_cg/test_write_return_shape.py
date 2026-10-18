# -*- coding: utf-8 -*-
'''写返回体判据守卫（issue #109 相邻面）：committed 必须可机器判定。

背景：`mdcg_remember` 工具面的**同一个返回体**在闸门短路分支给 `committed=False`，
成功分支此前**不给 `committed`** ⇒ 按 `committed` 判「是否落盘」的调用方会把**成功**
读成**未提交**；而按 `ok` 判的调用方会把**待审**读成**已提交**（#109 报的那一面）。
两面同源：**工具面的 committed 不是恒在的判据键**。

权威依据：`md_cg/protocol.py:57-59` 的 `WRITE_TRIO` 铁律（write 任一形态必含
ok/id/committed——「客户端据此判定『是否落盘』而非猜测」）与
`docs/mdcg/灵枢记忆动词协议_v1.0-draft.md:28/:31-32/:43`。

本守卫只钉**可判据面**：committed 恒在且与落盘事实一致；pending 态用 committed 可判。
不改写入语义。

运行：python -X utf8 -m md_cg.test_write_return_shape
      python -X utf8 -m md_cg.test_write_return_shape --mutate
'''
import argparse
import ast as _ast
import io
import json
import os
import shutil
import sys
import tempfile

_SANDBOX = tempfile.mkdtemp(prefix='write_shape_sandbox_')
os.environ['MDCG_AUX_ROOT'] = _SANDBOX
os.environ['MDCG_ROOT'] = os.path.join(_SANDBOX, 'root')
os.environ['MDCG_MASTER_KEY'] = os.urandom(32).hex()
os.environ.pop('MDCG_TEST_LIVE_ROOT', None)
_pol = os.path.join(_SANDBOX, 'policy.json')
with io.open(_pol, 'w', encoding='utf-8') as _f:
    json.dump({'forbidden': ['FORBIDDEN_WORD'], 'required': ['PASSED']}, _f)
os.environ['MDCG_POLICY_FILE'] = _pol

from . import mcp_server, protocol                # noqa: E402
from .mdcos import MdCGOS                          # noqa: E402

_HERE = os.path.dirname(os.path.abspath(__file__))
_PASS = []
_FAIL = []
_RUN = [0]


def ok(cond, msg, extra=''):
    (_PASS if cond else _FAIL).append(msg)
    print(('  PASS ' if cond else '  FAIL ') + msg
          + (('  <- ' + str(extra)) if (extra and not cond) else ''))


def _lib(tag):
    _RUN[0] += 1
    return MdCGOS(os.path.join(_SANDBOX, '%s_r%d' % (tag, _RUN[0])), autoflush=0)


BODY = '# 功能名：%s' + chr(10) + chr(10) + '# 生效条件：PASSED' + chr(10)


def _args(text, nid):
    return {'content_kind': 'text', 'content': text, 'layer': 'knowledge',
            'node_id': nid, 'verification_basis': 'test'}


def tool_write(cg, text, nid):
    return mcp_server.call_tool(cg, 'mdcg_remember', _args(text, nid))


def verb_write(cg, text, nid):
    a = dict(op='write')
    a.update(_args(text, nid))
    return mcp_server.call_tool(cg, 'cg', a)


def g_tool_success():
    cg = _lib('toolok')
    o = tool_write(cg, BODY % '初版', 'w1')
    ok(o.get('ok') is True, 'G1a 工具面首次写入 ok=True', o.get('ok'))
    ok('committed' in o, 'G1b 工具面成功返回体含 committed（三键铁律）', sorted(o))
    ok(o.get('committed') is True, 'G1c 工具面成功 => committed is True', o.get('committed'))
    ok('初版' in ((cg.get('w1') or {}).get('content') or ''),
       'G1d 与落盘事实一致（正文确在盘上）')


def g_tool_pending():
    cg = _lib('toolpend')
    tool_write(cg, BODY % '初版', 'w2')
    o = tool_write(cg, BODY % '改写版', 'w2')
    ok('committed' in o, 'G2a pending 返回体含 committed', sorted(o))
    ok(o.get('committed') is False, 'G2b pending => committed is False', o.get('committed'))
    ok(bool(o.get('moved_to')), 'G2c 未 committed 必给去向（moved_to）', o.get('moved_to'))
    ok('改写版' not in ((cg.get('w2') or {}).get('content') or ''),
       'G2d 与落盘事实一致（新正文未落盘）')


def g_machine_decidable():
    cg = _lib('decide')
    a = tool_write(cg, BODY % 'A', 'w3')
    b = tool_write(cg, BODY % 'B', 'w3')
    ok(a.get('committed') is True and b.get('committed') is False,
       'G3a 「已提交 / 待审」两态仅凭 committed 即可机器区分（不依赖 ok）',
       (a.get('committed'), b.get('committed')))
    ok(a.get('ok') is True and b.get('ok') is True,
       'G3b 两态 ok 相同 => 印证「只判 ok 必然误判」（#109 要害；本守卫不以 ok 作判据）')


def g_verb_face():
    cg = _lib('verb')
    a = verb_write(cg, BODY % 'VA', 'v1')
    b = verb_write(cg, BODY % 'VB', 'v1')
    for tag, o, want in (('G4a verb 成功', a, True), ('G4b verb 待审', b, False)):
        miss = [k for k in protocol.WRITE_TRIO if k not in o]
        ok(not miss and o.get('committed') is want,
           '%s => 含三键且 committed is %s' % (tag, want), (miss, o.get('committed')))


def _scan_ok_without_committed(src):
    '''找出 return {"ok": True ...} 且同一字典字面量内无 committed 的返回。'''
    bad = []
    lines = src.split(chr(10))
    for n, l in enumerate(lines):
        if 'return {' not in l:
            continue
        if '\"ok\": True' not in l and "'ok': True" not in l:
            continue
        head = chr(10).join(lines[n:n + 6]).split('}')[0]
        if 'committed' not in head:
            bad.append('第 %d 行' % (n + 1))
    return bad


def _write_shapes():
    '''协议里 write 的声明形态表（判据真源，不在本文件另立一份）。'''
    return protocol.VERB_SPECS['write']['shapes']


def _required_of(name):
    return tuple(_write_shapes()[name].get('required') or ())


def _static_violations(keys):
    '''静态面判据（只有键名）：①三键齐 ②命中至少一个声明形态 ③不构成任何形态的**降级**。

    返回 (违规列表, 命中的最具体形态名)。「最具体」＝required 键数最多——
    于是「自治出单」不会被更松的 committed 形态吞掉：形态判定可判据、不靠猜。

    ★**降级判据**（2026-10-12 加）：形态声明里的 `fingerprint` 是「本形态的特征键集
    （不含那条最容易漏的键）」。若某返回体**命中特征键却没满足 required**，说明它
    本该是本形态、却缺了必需键 —— 缺的那一个键（如 verdict）会让它退回去命中更松的
    形态（committed），**判据静默失效**。故此处显式判红。
    '''
    ks = set(keys)
    bad = []
    miss = [k for k in protocol.WRITE_TRIO if k not in ks]
    if miss:
        bad.append('缺三键%s' % miss)
    hit = [n for n in _write_shapes() if set(_required_of(n)) <= ks]
    if not hit:
        bad.append('不属任何声明形态')
    best = max(hit, key=lambda n: len(_required_of(n))) if hit else None
    for name, spec in _write_shapes().items():
        fp = tuple(spec.get('fingerprint') or ())
        if fp and set(fp) <= ks and name not in hit:
            missing = [k for k in _required_of(name) if k not in ks]
            bad.append('降级：命中 %s 的特征键却缺 %s' % (name, missing))
    return bad, best


def _runtime_violations(body):
    '''运行面判据（有真值）：静态面 + 「未 committed 必给去向（moved_to/gate）」。'''
    bad, best = _static_violations(body)
    if body.get('committed') is not True and not (body.get('moved_to')
                                                 or body.get('gate')):
        bad.append('未 committed 但无去向（moved_to/gate 皆缺）')
    return bad, best


def _dict_returns_in_block(path, tool):
    '''AST 取工具面分支块内的**字典字面量**返回：(行号, 键列表, 源码片段)。

    用 AST 而非正则：单引号/换行/多行字典都要认出（正则漏提＝假绿灯）。
    命名返回（return out / return res）不是字面量——其键集由运行面判据覆盖。
    '''
    import ast
    src = io.open(path, encoding='utf-8').read()
    tree = ast.parse(src)
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.If) or not isinstance(node.test, ast.Compare):
            continue
        c = node.test
        if not (isinstance(c.left, ast.Name) and c.left.id == "name"
                and len(c.comparators) == 1
                and isinstance(c.comparators[0], ast.Constant)
                and c.comparators[0].value == tool):
            continue
        for sub in ast.walk(node):
            if not isinstance(sub, ast.Return):
                continue
            # 生效条件：返回体是字典字面量时直接取；若是**包了一层调用**
            # （如 return _am.apply_dedup({...}, _pr)），则递归看它的 args——
            # 被包一层的字典仍是「工具分支块内的字典返回」，而按 ast.Dict 硬匹配
            # 会**静默看不见它**（不报错，表现为锚点漂移）。issue #552。
            cand = []
            if isinstance(sub.value, ast.Dict):
                cand.append(sub.value)
            elif isinstance(sub.value, ast.Call):
                for arg in list(sub.value.args) + [kw.value for kw in sub.value.keywords]:
                    if isinstance(arg, ast.Dict):
                        cand.append(arg)
            for d in cand:
                ks = [k.value for k in d.keys if isinstance(k, ast.Constant)]
                out.append((d.lineno, ks, ast.get_source_segment(src, d) or ''))
    return sorted(out)


def g_declared_shapes_full():
    '''G6 按声明形态**全量**校验工具面（静态 AST 面）。

    每个字典字面量返回都必须 ①三键齐 ②命中声明形态；并按锚串钉住**具体形态**
    （锚串不在 ⇒ 判红：实现改了却没同步本表＝判据漂移，不静默放行）。
    '''
    src_path = os.path.join(_HERE, 'mcp_server.py')
    found = _dict_returns_in_block(src_path, 'mdcg_remember')
    ok(len(found) >= 3,
       'G6a 工具面分支块内字典返回数 >= 3（实测 %d 个）' % len(found),
       [r[0] for r in found])
    anchors = {
        'autonomy_forbidden': {'must': protocol.WRITE_TRIO + ('moved_to',)},
        'conflict_deferred': {'must': protocol.WRITE_TRIO + ('moved_to', 'verdict'),
                              'best': 'gate_short_circuit'},
        'review_queue': {'must': _required_of('autonomy_ticket'),
                         'best': 'autonomy_ticket',
                         # ★2026-10-12 设计者裁定：verdict **键必在场**、值取盲区标记
                         # None（`no` 从 ('verdict',) 改为「不许有值」由 G6e' 判）。
                         'no_value': ('verdict',)},
    }
    seen = {}
    for ln, keys, seg in found:
        bad, best = _static_violations(keys)
        ok(not bad, 'G6b 行 %d 满足三键铁律且属声明形态（形态=%s）' % (ln, best),
           (bad, sorted(keys)))
        for name, spec in anchors.items():
            if name in seg:
                seen[name] = ln
                miss = [k for k in spec['must'] if k not in keys]
                ok(not miss, 'G6c 行 %d 是 %s 形态且含必需键' % (ln, name), miss)
                if spec.get('best'):
                    ok(best == spec['best'],
                       'G6d 行 %d（%s）命中的最具体形态 == %s'
                       % (ln, name, spec['best']), best)
                for k in spec.get('no', ()):
                    ok(k not in keys,
                       'G6e 行 %d（%s）不得含 %s（无该判据不许编造）'
                       % (ln, name, k), sorted(keys))
                # ★2026-10-12 裁定新增：键**必在场**，但值必须是盲区标记 None。
                for k in spec.get('no_value', ()):
                    ok(k in keys,
                       'G6e\u2032 行 %d（%s）必须含 %s 键（盲区声明：键必在场）'
                       % (ln, name, k), sorted(keys))
                    vals = _literal_values_of(seg)
                    ok(k in vals and vals[k] is None,
                       'G6e\u2033 行 %d（%s）的 %s 值必须是盲区标记 None'
                       '（该路径无 audit 裁决，不许编造有值裁决）'
                       % (ln, name, k), vals.get(k, '<缺键>'))
    for name in anchors:
        ok(name in seen,
           'G6f 锚点 %s 仍存在于工具面分支块（锚点漂移即判红）' % name,
           sorted(seen))


def g_runtime_shapes():
    '''G7 运行面：逐分支真跑，按声明形态全量校验。'''
    cg = _lib('shapes')
    a = tool_write(cg, BODY % '初版', 's1')
    bad, best = _runtime_violations(a)
    ok(not bad, 'G7a 成功分支满足全量校验（形态=%s）' % best, bad)
    ok(best == 'committed', 'G7b 成功分支最具体形态 == committed', best)

    b = tool_write(cg, BODY % '改写版', 's1')
    bad, best = _runtime_violations(b)
    ok(not bad, 'G7c 自治出单分支满足全量校验（形态=%s）' % best, bad)
    ok(best == 'autonomy_ticket',
       'G7d 自治出单分支最具体形态 == autonomy_ticket（不并入 gate_short_circuit）',
       best)
    ok('verdict' in b and b.get('verdict') is None,
       'G7e 自治出单分支 verdict **键必在场且值为盲区标记 None**'
       '（2026-10-12 裁定：该路径无 audit 裁决 ⇒ 留显式标记，不编造有值裁决）',
       (sorted(b), b.get('verdict', '<缺键>')))
    ok(b.get('committed') is False and b.get('moved_to') == 'review_queue',
       'G7f 自治出单 = 未落盘 + 去向 review_queue + 可轮询 pid',
       (b.get('committed'), b.get('moved_to'), b.get('pid')))

    # on_conflict 必须显式给 defer：工具面缺省是 reject（抛 ConsistencyError），
    # 只有 defer 才会让 cg.add 返回 None 并走冲突 DEFER 出口（本批新增的去向词）。
    _ca = _args('# 功能名：冲突体' + chr(10) * 2
                + '# 生效条件：超时 30s 允许并发' + chr(10)
                + '# 不适用条件：超时' + chr(10), 's2')
    _ca['on_conflict'] = 'defer'
    c = mcp_server.call_tool(cg, 'mdcg_remember', _ca)
    bad, best = _runtime_violations(c)
    ok(not bad, 'G7g 冲突 DEFER 分支满足全量校验（形态=%s）' % best, bad)
    ok(c.get('moved_to') == 'conflict_deferred',
       'G7h 冲突 DEFER 去向词 == conflict_deferred（未落盘也未入队）',
       (c.get('moved_to'), c.get('committed'), sorted(c)))
    ok(c.get('committed') is False and 'pid' not in c,
       'G7i 冲突 DEFER：committed is False 且不给 pid（未入队 ⇒ 不轮询）', sorted(c))


def g_autonomy_forbidden_and_guest():
    '''G8 自治禁止（plan 档）+ 无权限（guest）两面。'''
    from unittest.mock import patch
    from . import autonomy_modes as _am
    # 纪律（autonomy_modes.py:124）：档位 env 名只在唯一入口模块写字面量 ——
    # 本守卫经 AUTONOMY_ENV_KEYS 取键（同 test_autonomy_modes 的 _ENV_MODE 口径），
    # 绝不在此处再写一处带引号的档位 env 字面量。
    with patch.dict(os.environ, {_am.AUTONOMY_ENV_KEYS['mode']: 'plan'}):
        cg = _lib('forbid')
        tool_write(cg, BODY % '初版', 'f1')
        o = tool_write(cg, BODY % '改写版', 'f1')
        bad, best = _runtime_violations(o)
        ok(not bad, 'G8a 自治禁止分支满足全量校验（形态=%s）' % best, bad)
        ok(o.get('moved_to') == 'autonomy_forbidden'
           and o.get('committed') is False,
           'G8b plan 档 => moved_to=autonomy_forbidden + committed False',
           (o.get('moved_to'), o.get('committed')))
    from .mdcos import MdCGSecure
    from .security import AccessDenied, Principal
    root = os.path.join(_SANDBOX, 'guest_root')
    master = bytes(range(32))
    owner = Principal(tenant='t', actor='owner', session='s', clearance='secret',
                      role='designer', can_write=True, can_admin=True)
    cg2 = MdCGSecure(root, master_key=master, principal=owner)
    guest = MdCGSecure(root, master_key=master, principal=Principal(
        tenant='t', actor='guest', session='g', clearance='public',
        role='guest', can_write=False))
    try:
        raised = None
        try:
            mcp_server.call_tool(guest, 'mdcg_remember', _args(BODY % 'guest', 'gx'))
        except Exception as exc:                       # noqa: BLE001
            raised = exc
        ok(isinstance(raised, AccessDenied),
           'G8c 无权限分支=异常面（抛 AccessDenied），不返回形状不全的 dict',
           type(raised).__name__ if raised else None)
    finally:
        guest.close()
        cg2.close()


def g_gated_envelope_exempt():
    '''G9 gated=true 分支的**显式豁免**判据（双向钉，防静默两面）。

    该分支委托 mdcos.remember_gated，返回**闸门裁决信封**（ok/gate/verdict/
    written），不含 id/committed ⇒ 不在三键面。本判据不断言它「合规」，而是钉：
      ① 现状确实缺三键（记录下来，不假装已覆盖）；
      ② 它仍给出机器可判的裁决/落盘判据（gate|verdict|written）；
      ③ 若将来补上三键 ⇒ 必须同时满足声明形态（改善也不许无声明）。
    '''
    cg = _lib('gatedenv')
    o = mcp_server.call_tool(cg, 'mdcg_remember',
                             dict(_args(BODY % 'gated', 'ge1'), gated=True))
    trio_complete = all(k in o for k in protocol.WRITE_TRIO)
    ok(not trio_complete,
       'G9a gated 分支现状不在三键面（实测键=%s）——显式记录，未假装覆盖'
       % sorted(o), sorted(o))
    ok(any(k in o for k in ('gate', 'verdict', 'written')),
       'G9b gated 分支仍给出机器可判的裁决/落盘判据（gate|verdict|written）',
       sorted(o))
    if trio_complete:
        bad, best = _runtime_violations(o)
        ok(not bad,
           'G9c gated 分支已补三键 => 必须满足声明形态（形态=%s）' % best, bad)


def g_tool_face_binding_declared():
    '''G10 声明面：mdcg_remember 已绑定 write 动词（题1 的声明落地）。'''
    bind = getattr(protocol, 'TOOL_FACE_BINDINGS', {}).get('mdcg_remember')
    ok(bool(bind), 'G10a 协议声明了工具面 mdcg_remember → 动词绑定', bind)
    ok(bool(bind) and bind.get('verb') == 'write',
       'G10b 绑定动词 == write（受 WRITE_TRIO 铁律约束）', bind)
    rep = protocol.audit()
    ok(rep.get('ok') is True and not rep.get('shape_errors'),
       'G10c 协议静态对账 ok=True 且零 shape_errors', rep.get('shape_errors'))
    ok('autonomy_ticket' in protocol.VERB_SPECS['write']['shapes'],
       'G10d write 声明形态含 autonomy_ticket（题3b 落地）')
    ok('verdict' in _required_of('autonomy_ticket'),
       'G10e autonomy_ticket.required **含** verdict（2026-10-12 裁定：该路径无 audit 裁决'
       ' ⇒ 值取盲区标记 None，但**键必在场**——缺席是歧义源）',
       _required_of('autonomy_ticket'))



def g_source_no_silent_gap():
    src = io.open(os.path.join(_HERE, 'mcp_server.py'), encoding='utf-8').read()
    i = src.find('if name == \"mdcg_remember\":')
    j = src.find('if name == \"mdcg_recall\":')
    block = src[i:j] if (i >= 0 and j > i) else ''
    ok(bool(block), 'G5a 定位到 mdcg_remember 工具面分支块', (i, j))
    bad = _scan_ok_without_committed(block)
    ok(not bad,
       'G5b 工具面分支内不存在「ok:True 却不给 committed」的返回（防静默回退）', bad)


#: protocol.gate_short_circuit（任一 before 闸门短路）的必需键集——本批补齐的判据面。
_GATE_REQ = protocol.WRITE_TRIO + ('moved_to', 'verdict', 'hint')


def _scan_gate_missing(src, markers=('moved_to', 'gate')):
    '''按 protocol 形状表核对写面返回体（**AST 级**，避免内层字典 `}` 误切）。

    `markers`：认定「本返回属闸门短路类」的键。默认 `moved_to`/`gate`（写链/引擎面）；
    工具面额外加 `verdict`——因为那里最初的缺口正是**连 moved_to 都没有**的那一态。
    形状判定（按返回字典键集）：
      · 含 `gate`     ⇒ gate_gated：需 WRITE_TRIO + (gate, verdict)
      · 含 `moved_to` ⇒ gate_short_circuit：需 WRITE_TRIO + (moved_to, verdict, hint)
      · 其余          ⇒ 落盘形态：需 WRITE_TRIO
    豁免：字面量之后补键的既有写法（如 `out["hint"] = ...`）视为满足（源码全文出现该赋值即豁免）。
    '''
    bad = []
    try:
        tree = _ast.parse(src)
    except SyntaxError as exc:
        return ['源码解析失败：%s' % exc]
    late = set()
    for k in ('hint',):
        if ('["%s"] = ' % k) in src or ("['%s'] = " % k) in src:
            late.add(k)
    for node in _ast.walk(tree):
        if not isinstance(node, _ast.Return) or not isinstance(node.value, _ast.Dict):
            continue
        keys = set()
        for k in node.value.keys:
            if isinstance(k, _ast.Constant) and isinstance(k.value, str):
                keys.add(k.value)
        if not (set(markers) & keys):
            continue
        if 'gate' in keys:
            need, shape = protocol.WRITE_TRIO + ('gate', 'verdict'), 'gate_gated'
        elif 'moved_to' in keys:
            need, shape = _GATE_REQ, 'gate_short_circuit'
        else:
            need, shape = protocol.WRITE_TRIO, 'committed'
        miss = [k for k in need if k not in keys and k not in late]
        if miss:
            bad.append('第 %d 行 [%s] 缺 %s' % (node.lineno, shape, ','.join(miss)))
    return bad


def g_autonomy_gate_shape():
    '''自治档位短路的两条分支（出单 / 兜底拒绝）须满足 gate_short_circuit 形状。

    背景（#109 三处仍开着之二）：工具面 `mdcg_remember` 的自治档位分支此前**缺 verdict**，
    不满足 protocol 声明的形状；直写面无校验闸 ⇒ verdict 键必在、值取 None（照
    writepipe.py:758 既有惯例，不编造裁决）。
    '''
    from . import autonomy_modes as _am
    env_mode = _am.AUTONOMY_ENV_KEYS['mode']
    cg = _lib('autgate')
    tool_write(cg, BODY % '初版', 'g1')            # 先造既有节点（触发 C 改写）
    old = os.environ.get(env_mode)
    try:
        os.environ[env_mode] = 'confirm'           # 变更确认档 ⇒ 出单
        o = tool_write(cg, BODY % '改写版', 'g1')
        miss = [k for k in _GATE_REQ if k not in o]
        ok(not miss and o.get('committed') is False
           and o.get('moved_to') == 'review_queue' and o.get('verdict', '缺键') is None,
           'G6a 自治出单分支满足 gate_short_circuit（含 verdict 键且为 None、committed=False）',
           (miss, o.get('committed'), o.get('verdict', '缺键')))
        os.environ[env_mode] = 'plan'              # 计划档 ⇒ **A 新增** fail-closed
        o2 = tool_write(cg, BODY % '计划外新增', 'g2')   # 新 id ⇒ A 新增（非改写）
        miss2 = [k for k in _GATE_REQ if k not in o2]
        ok(not miss2 and o2.get('committed') is False
           and o2.get('moved_to') == 'autonomy_forbidden',
           'G6b 自治兜底拒绝分支（plan 档 A 新增）同样满足该形状（含 verdict 键、committed=False）',
           (miss2, o2.get('moved_to')))
    finally:
        if old is None:
            os.environ.pop(env_mode, None)
        else:
            os.environ[env_mode] = old


def g_gate_source_no_gap():
    '''写动词面三个文件的闸门短路返回，必须含对应形状的必需键。

    面与标记（避免扫到非写面同名字段）：
      · `mcp_server.py`：**只扫 `mdcg_remember` 工具面分支块**；标记含 `verdict`
        ——该面最初的缺口正是「连 `moved_to` 都没有」的那一态。
      · `writepipe.py` / `mdcos.py`：整文件按 `moved_to`/`gate` 标记（两文件均写面）。
    '''
    bad = []
    src = io.open(os.path.join(_HERE, 'mcp_server.py'), encoding='utf-8').read()
    i = src.find('if name == "mdcg_remember":')
    j = src.find('if name == "mdcg_recall":')
    block = src[i:j] if (i >= 0 and j > i) else ''
    bad += ['mcp_server.py mdcg_remember 块 %s' % s
            for s in _scan_gate_missing(block,
                                        markers=('moved_to', 'gate', 'verdict'))]
    for fn, marks in (('writepipe.py', ('moved_to', 'gate')),
                      # mdcos 只按 moved_to 标记：其 `remember_gated` 的**内部返回形状**
                      # （verdict/bypass/gate/written）契约属 #109 第③项「工具面是否受三键
                      # 铁律约束」的**待裁范围**，本判据不替它裁（不误报、也不擅改）。
                      ('mdcos.py', ('moved_to',))):
        s = io.open(os.path.join(_HERE, fn), encoding='utf-8').read()
        bad += ['%s %s' % (fn, x) for x in _scan_gate_missing(s, markers=marks)]
    ok(not bad,
       'G7 写动词面闸门短路返回均含对应形状的必需键（gate_short_circuit = WRITE_TRIO'
       '+moved_to+verdict+hint；gate_gated = WRITE_TRIO+gate+verdict；防缺键回退）', bad)


# ---------------------------------------------------------------- #142（2026-10-12 DSH 端）
#: #142 定点变异的注入开关（默认全关；只在 --mutate 的自证段打开）。
_142_MUT = {'oversize_keys': False, 'halt_2pc': False}


def _ledger_rows(cg):
    '''两段式账本行数（#142② 的覆盖判据用）。'''
    from . import twophase
    p = twophase.log_path(cg)
    if not os.path.isfile(p):
        return 0
    with io.open(p, encoding='utf-8') as f:
        return sum(1 for l in f if l.strip())


def g_142_oversize_trio():
    '''#142①：**超限出口**必须满足 WRITE_TRIO 铁律。

    这是「写返回体形状」此前**未被覆盖的出口**——它不经任何 before 闸，直接在
    execute 入口返回；修前只有 ok/bytes/error/limit/verdict（三键缺二，且不属任何
    声明形态）。判据真源＝protocol.WRITE_TRIO + VERB_SPECS['write']['shapes']。
    '''
    from . import writepipe
    cg = _lib('o142')
    big = '# 功能名：超限' + chr(10) + chr(10) + '# 生效条件：PASSED' + chr(10) \
        + ('x' * (writepipe.MAX_WRITE_BYTES + 8))
    out = writepipe.default_pipeline().execute(cg, _args(big, 'o142_big'))
    if _142_MUT['oversize_keys']:          # 变异：还原修前返回体
        out = {k: v for k, v in out.items() if k not in ('id', 'committed')}
    miss = [k for k in protocol.WRITE_TRIO if k not in out]
    ok(not miss, 'H1a 超限出口含三键（ok/id/committed）', sorted(out))
    ok(bool(out.get('id')), 'H1b 超限出口带非空 id（与 ctx 同源）', out.get('id'))
    ok(out.get('committed') is False, 'H1c 超限 => committed is False', out.get('committed'))
    bad, best = _static_violations(sorted(out))
    ok(not bad, 'H1d 超限出口命中协议声明形态（静态判据）', (bad, best))
    ok(best == 'gate_hard_reject', 'H1e 命中 gate_hard_reject（硬拒＋结构化 error）', best)
    src = io.open(os.path.join(_HERE, 'writepipe.py'), encoding='utf-8').read()
    ok('return {"ok": False, "error": "content 超过写入硬上限' not in src,
       'H1f 源码级：修前的无三键超限出口字面量已不存在',
       '（若本项红说明被回退）')


def g_142_halt_2pc():
    '''#142②：**短路出口零两段式覆盖**——现状如实钉住 + 口径冲突标注（本件未改）。

    实测：audit REJECT / 缺必需要素等短路出口落 **0** 条两段式记录（twophase 只覆盖
    「全放行」与 gated 两段）；但 `md_cg/test_twophase.py:9/⑧2` 把「未落盘的分支
    （闸门拒绝 / 入队）**不产生 intent**——没打算写就不记账」钉成不变量，而该守卫
    文件**不在本件写面**（task-35：写面仅 writepipe.py + 本批守卫）⇒ 本件**回退了**
    「短路补记账」的改法（回退前 test_twophase 34/1，⑧2 红），改为在此如实钉现状。
    若将来裁定「短路也要落账」，本组断言会转红——那正是升级断言的信号。
    '''
    from . import writepipe
    cg = _lib('h142')
    cases = [
        ('audit REJECT·禁表词',
         _args('# 功能名：禁' + chr(10) * 2 + '# 生效条件：PASSED' + chr(10)
               + '内容 FORBIDDEN_WORD 在此', 'h_rej')),
        ('audit REJECT·缺必需要素',
         _args('# 功能名：缺' + chr(10) * 2 + '正文无必需要素词', 'h_miss')),
        ('gated 闸（自记账）', dict(_args(BODY % '遗忘闸', 'h_gated'), gated=True)),
    ]
    for label, a in cases:
        before = _ledger_rows(cg)
        writepipe.default_pipeline().execute(cg, a)
        delta = _ledger_rows(cg) - before
        want = 2 if label.startswith('gated') else 0
        ok(delta == want,
           'H2 %s ⇒ 账本 +%d（现状口径：短路不记账 / gated 自记一对）' % (label, want),
           'delta=%d（期望 %d）' % (delta, want))
    rep = cg.reconcile_writes()
    ok(rep.get('unpaired') == 0, 'H2d 两段式对账零悬空（unpaired=0）', rep)
    print('        [需裁定] ②：短路出口零账（本件未改，因与 test_twophase ⑧2 的不变量冲突）——改法已写进 _team/writepipe/report.md，待 Lead/设计者裁定')


def g_142_two_path_divergence():
    '''#142④：两条写通路（mdcg_remember 直写 vs cg(op=write) 走 writepipe）结论相反。

    **本守卫只如实记录现状**：统一判据的改动点落在 `mcp_server.py:3571` 分支
    （本件**只读**，见 task-35 写面约束）⇒ 不在本守卫红绿面内。若 Lead 后续统一了
    通路，H3a 会转红——那正是「把断言升级为『两通路一致』」的信号。
    '''
    cg = _lib('twopath142')
    text = ('# 功能名：同一内容' + chr(10) * 2 + '# 生效条件：PASSED' + chr(10)
            + '内容 FORBIDDEN_WORD 在此')
    o_t = mcp_server.call_tool(cg, 'mdcg_remember', _args(text, 'tp_tool'))
    o_v = mcp_server.call_tool(cg, 'cg', dict(op='write', **_args(text, 'tp_verb')))
    ok(bool(o_t.get('committed')) != bool(o_v.get('committed')),
       'H3a 现状：同一内容两通路结论相反（报告已记录；统一需改 mcp_server）',
       (o_t.get('committed'), o_v.get('committed')))
    ok(not [k for k in protocol.WRITE_TRIO if k not in o_t]
       and not [k for k in protocol.WRITE_TRIO if k not in o_v],
       'H3b 两通路返回体各自满足三键铁律（形状面已覆盖）',
       (sorted(o_t), sorted(o_v)))
    print('        [需协调] 统一判据的改动点在 mcp_server.py:3571（本件只读）——'
          '现状：工具面落盘 / 动词面 REJECT')

_CASES = (g_tool_success, g_tool_pending, g_machine_decidable, g_verb_face,
          g_source_no_silent_gap,
          # issue #109 三题（2026-10-10 裁定）新增判据组：
          g_tool_face_binding_declared,   # G10 声明面：工具面绑定 + autonomy_ticket 落地
          g_declared_shapes_full,         # G6 静态面：按声明形态全量校验工具面
          g_runtime_shapes,               # G7 运行面：成功/自治出单/冲突 DEFER 逐分支
          g_autonomy_forbidden_and_guest,  # G8 自治禁止（plan 档）+ 无权限（异常面）
          g_gated_envelope_exempt,        # G9 gated 分支显式豁免（双向钉）
          # PR #113（2026-10-12 合并，经设计者裁定收束 verdict 语义）：
          g_autonomy_gate_shape,          # 自治短路两分支满足 gate_short_circuit（verdict 键必在）
          g_gate_source_no_gap,           # 三写面源码级：闸门短路返回必含对应形状必需键
          # #142（2026-10-12 DSH 端）新增判据组：
          g_142_oversize_trio,            # H1 超限出口（此前未覆盖的出口）三键+声明形态
          g_142_halt_2pc,                 # H2 短路出口两段式覆盖（恰一对 intent/outcome）
          g_142_two_path_divergence)      # H3 两通路相反结论（现状记录·待 Lead 协调）


def _run_all():
    del _PASS[:]
    del _FAIL[:]
    for fn in _CASES:
        try:
            fn()
        except Exception as exc:                       # noqa: BLE001
            ok(False, '%s 组抛异常：%s: %s' % (fn.__name__, type(exc).__name__, exc))
    return list(_FAIL)


_SYN = (
    ('M0 合成合规源码（同一字典内含 committed）',
     'return {"ok": True, "id": nid, "committed": True}', False),
    ('M1 合成缺 committed（本轮修掉的那一态）',
     'return {"ok": True, "id": nid}', True),
    ('M2 合成 committed 换行后仍在同一字典内',
     'return {"ok": True, "id": nid,' + chr(10) + '        "committed": True}', False),
    ('M3 合成 committed 落在字典之外（应判红）',
     'return {"ok": True, "id": nid}' + chr(10) + 'x = {"committed": True}', True),
)


def _syn_shape_report(src):
    '''对**合成源码**跑本批新增的静态形态判据（不读盘、不定点改真实源码）。

    返回 [(违规列表, 最具体形态, 键列表)] —— 一个 return 一行。
    '''
    import ast as _ast
    import textwrap as _tw
    tree = _ast.parse(_tw.dedent(src))
    rows = []
    for node in _ast.walk(tree):
        if isinstance(node, _ast.Return) and isinstance(node.value, _ast.Dict):
            ks = [k.value for k in node.value.keys if isinstance(k, _ast.Constant)]
            bad, best = _static_violations(ks)
            rows.append((bad, best, ks))
    return rows


#: 新增判据的定点变异表：每行 = (名称, 合成源码, 期望特征)。
#: 期望特征键：violations_red（静态面应否报违规）/ best（应为的最具体形态）/
#:             fabricated_verdict（「autonomy_ticket 形态下 verdict 被编造成有值」
#:             应否被检出 —— ★2026-10-12 设计者裁定后，**verdict 键必在场、值取 None
#:             是盲区声明**；仍被禁止的只是**编造一个有值的裁决**）。
_SYN_SHAPES = (
    ('V0 改前的冲突 DEFER 体（只有 ok/id/verdict/reason）＝本批修掉的那一态',
     'return {"ok": False, "id": nid, "verdict": "DEFER", "reason": "x"}',
     {'violations_red': True}),
    ('V1 改后的冲突 DEFER 体（三键 + moved_to + verdict + hint）',
     'return {"ok": False, "id": nid, "committed": False,'
     ' "moved_to": "conflict_deferred", "verdict": "DEFER", "hint": "h"}',
     {'violations_red': False, 'best': 'gate_short_circuit'}),
    ('V2 自治出单体（真实键集，含 verdict: None ＝盲区声明）',
     'return {"ok": True, "id": nid, "committed": False,'
     ' "moved_to": "review_queue", "pid": p, "mutation": m,'
     ' "autonomy": a, "verdict": None, "hint": "h"}',
     {'violations_red': False, 'best': 'autonomy_ticket',
      'fabricated_verdict': False}),
    ('V2b 自治出单体**缺 verdict 键**（盲区未声明 ⇒ 静态面应判红）',
     'return {"ok": True, "id": nid, "committed": False,'
     ' "moved_to": "review_queue", "pid": p, "mutation": m,'
     ' "autonomy": a, "hint": "h"}',
     {'violations_red': True}),
    ('V3 自治出单体被**编造有值裁决**（verdict: "DEFER" ⇒ 应被检出）',
     'return {"ok": True, "id": nid, "committed": False,'
     ' "moved_to": "review_queue", "pid": p, "mutation": m,'
     ' "autonomy": a, "verdict": "DEFER", "hint": "h"}',
     {'violations_red': False, 'best': 'autonomy_ticket',
      'fabricated_verdict': True}),
    ('V4 自治出单体丢掉 autonomy（形态降级 ⇒ 最具体形态退化为 committed）',
     'return {"ok": True, "id": nid, "committed": False,'
     ' "moved_to": "review_queue", "pid": p, "hint": "h"}',
     {'violations_red': False, 'best': 'committed',
      'body': {'ok': True, 'id': 'x', 'committed': False,
               'moved_to': 'review_queue', 'pid': 'prop_x', 'hint': 'h'},
      'runtime_red': False}),
    ('V5 三键齐但未 committed 且无去向（运行面应判红）',
     'return {"ok": False, "id": nid, "committed": False, "verdict": "DEFER"}',
     {'violations_red': False,
      'body': {'ok': False, 'id': 'x', 'committed': False, 'verdict': 'DEFER'},
      'runtime_red': True}),
)


def _literal_values(src):
    '''从源码片段里的字典字面量取 {键: 值}（值只认字面常量；名字→哨兵 `'<expr>'`）。

    输入既可是**合成源码**（`return {...}`），也可是**真实源码里的一个返回片段**
    （G6 的 `seg`，形如 `{"ok": True, ...}`）。故先试 `return` 包裹，失败则当表达式解析。
    '''
    import ast as _ast
    import textwrap as _tw
    text = _tw.dedent(src).strip()
    for candidate in (text, 'return ' + text, 'x = ' + text):
        try:
            tree = _ast.parse(candidate)
        except SyntaxError:
            continue
        for node in _ast.walk(tree):
            d = node.value if (isinstance(node, (_ast.Return, _ast.Assign))
                               and isinstance(node.value, _ast.Dict)) else (
                node if isinstance(node, _ast.Dict) else None)
            if d is None:
                continue
            out = {}
            for k, v in zip(d.keys, d.values):
                if isinstance(k, _ast.Constant) and isinstance(k.value, str):
                    out[k.value] = v.value if isinstance(v, _ast.Constant) else '<expr>'
            if out:
                return out
    return {}


#: G6 的片段级取值：对真实源码里的返回片段做同样的事（供 `no_value` 判据用）。
_literal_values_of = _literal_values


def _fabricated_verdict(ks):
    '''autonomy_ticket 形态下 verdict 是否为**编造的有值裁决**。

    判据（2026-10-12 设计者裁定）：该形态 required 含 verdict，取值必须是盲区
    标记 None；**任何非 None 值都是编造**（该路径无 audit 裁决可透出）。
    '''
    return ('verdict' in ks and ks['verdict'] is not None) if isinstance(ks, dict) \
        else False


def _run_shape_mutations():
    print('!! 新增判据定点变异自证（G6/G7 静态+运行面）')
    bad = 0
    for name, src, expect in _SYN_SHAPES:
        rows = _syn_shape_report(src)
        got_red = bool(rows) and bool(rows[0][0])
        got_best = rows[0][1] if rows else None
        ks = rows[0][2] if rows else []
        got_fv = _fabricated_verdict(_literal_values(src))
        # 运行面判据吃**显式真实值的 body**（键集 fromkeys 会把值全变 None，
        # 那是假读：committed=None 既非 True 也非 False，moved_to=None 会被
        # 误当「无去向」）。故用表里给的 body；未给则跳过该项。

        _body = expect.get('body')
        rt_bad = _runtime_violations(_body)[0] if _body is not None else []
        got_rt = bool(rt_bad)
        checks = []
        if 'violations_red' in expect:
            checks.append(('静态面判红=%s' % expect['violations_red'],
                           got_red == expect['violations_red']))
        if 'best' in expect:
            checks.append(('最具体形态=%s' % expect['best'],
                           got_best == expect['best']))
        if 'fabricated_verdict' in expect:
            checks.append(('autonomy_ticket 编造有值裁决被检出=%s'
                           % expect['fabricated_verdict'],
                           got_fv == expect['fabricated_verdict']))
        if 'runtime_red' in expect:
            checks.append(('运行面判红=%s' % expect['runtime_red'],
                           got_rt == expect['runtime_red']))
        good = all(v for _l, v in checks)
        if not good:
            bad += 1
        print('  %s %s' % ('PASS' if good else 'FAIL', name))
        for label, v in checks:
            print('        %s %s' % ('ok ' if v else 'MISS', label))
        if not good:
            print('        实际：red=%s best=%s keys=%s runtime_bad=%s'
                  % (got_red, got_best, sorted(ks), rt_bad))
    print('')
    return bad


#: 本批（gate_short_circuit 形状）的合成变异：喂 `_scan_gate_missing`，判别力必须成立。
_SYN_GATE = (
    ('M4 合成合规（三键 + moved_to + verdict + hint）',
     'return {"ok": False, "id": nid, "committed": False,'
     ' "moved_to": "conflict_deferred", "verdict": "DEFER", "hint": "x"}', False),
    ('M5 合成缺 verdict（本批修掉的那一态）',
     'return {"ok": True, "id": nid, "committed": False,'
     ' "moved_to": "review_queue", "hint": "x"}', True),
    ('M6 合成缺 hint（形状要求的下一步说明）',
     'return {"ok": False, "id": nid, "committed": False,'
     ' "moved_to": "x", "verdict": None}', True),
    ('M7 合成缺 committed（原冲突 DEFER 分支那一态）',
     'return {"ok": False, "id": nid, "verdict": "DEFER", "reason": "r"}', True),
)


def _run_142_mutations():
    '''#142 的两条定点变异（都作用于**被验实现**，不是断言侧）。'''
    print('!! #142 定点变异自证（短路两段式 / 超限三键）')
    bad = 0
    from . import twophase
    _p0, _f0 = list(_PASS), list(_FAIL)
    # ---- M5：注入「短路出口补两段式账」的改法（＝本件曾尝试、后回退的那一版）
    #          ⇒ H2 必须判红（证明「现状口径」这条断言有判别力） ----
    from . import writepipe
    _oe = writepipe.WritePipeline.execute

    def _me(self, cg, a):
        out = _oe(self, cg, a)
        if isinstance(out, dict) and out.get('committed') is False:
            _t = twophase.begin(cg, out.get('id') or '', a.get('content', ''),
                                actor='mut5:halt')
            twophase.commit(cg, _t, status=twophase.STATUS_ABORTED,
                            reason='halted_by=mut5')
        return out

    writepipe.WritePipeline.execute = _me
    del _PASS[:]
    del _FAIL[:]
    try:
        g_142_halt_2pc()
    except Exception as exc:                       # noqa: BLE001
        ok(False, '变异段抛异常：%s: %s' % (type(exc).__name__, exc))
    red2 = [m for m in _FAIL if m.startswith('H2')]
    writepipe.WritePipeline.execute = _oe
    good2 = len(red2) >= 1
    bad += 0 if good2 else 1
    print('  %s M5 注入「短路补记账」改法 ⇒ H2 判红 %d 条%s'
          % ('PASS' if good2 else 'FAIL', len(red2),
             ('：' + '; '.join(red2[:2])) if red2 else ''))
    # ---- M6：超限出口还原修前（缺 id/committed）⇒ H1 必须判红 ----
    _142_MUT['oversize_keys'] = True
    del _PASS[:]
    del _FAIL[:]
    try:
        g_142_oversize_trio()
    except Exception as exc:                       # noqa: BLE001
        ok(False, '变异段抛异常：%s: %s' % (type(exc).__name__, exc))
    red1 = [m for m in _FAIL if m.startswith('H1')]
    _142_MUT['oversize_keys'] = False
    good1 = len(red1) >= 2
    bad += 0 if good1 else 1
    print('  %s M6 超限出口缺 id/committed（还原修前）⇒ H1 判红 %d 条%s'
          % ('PASS' if good1 else 'FAIL', len(red1),
             ('：' + '; '.join(red1[:3])) if red1 else ''))
    del _PASS[:]
    del _FAIL[:]
    _PASS.extend(_p0)
    _FAIL.extend(_f0)
    print('')
    return bad

def _run_mutations():
    print('!! 定点变异自证：给 G5b 判据体喂合成源码，判别力必须成立')
    bad = 0
    for name, src, expect_red in _SYN:
        got = _scan_ok_without_committed(src)
        good = (bool(got) == expect_red)
        if not good:
            bad += 1
        print('  %s %s' % ('PASS' if good else 'FAIL', name))
        if not good:
            print('        预期有红=%s 实际=%s' % (expect_red, got))
    print('')
    bad += _run_shape_mutations()
    print('!! 定点变异自证：给 G7 判据体喂合成源码，判别力必须成立')
    for name, src, expect_red in _SYN_GATE:
        # AST 判据要求 return 处于函数体内 ⇒ 合成样本统一包一层 def
        wrapped = 'def _f():' + chr(10) + chr(10).join(
            '    ' + l for l in src.split(chr(10)))
        got = _scan_gate_missing(wrapped, markers=('moved_to', 'gate', 'verdict'))
        good = (bool(got) == expect_red)
        if not good:
            bad += 1
        print('  %s %s' % ('PASS' if good else 'FAIL', name))
        if not good:
            print('        预期有红=%s 实际=%s' % (expect_red, got))
    print('')
    bad += _run_142_mutations()
    return bad


def main() -> int:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    ap = argparse.ArgumentParser(description='写返回体判据守卫（issue #109 相邻面）')
    ap.add_argument('--mutate', action='store_true', help='定点变异自证')
    a = ap.parse_args()
    reds = _run_all()
    print('')
    print('SUMMARY: 写返回体判据守卫：%d 通过，%d 失败' % (len(_PASS), len(reds)))
    if reds:
        print('失败判据：' + '; '.join(reds))
    rc = 1 if reds else 0
    if a.mutate:
        rc = 1 if (_run_mutations() or reds) else 0
        print('SUMMARY: 定点变异自证：%s' % ('全部按预期' if rc == 0 else '存在偏差'))
    shutil.rmtree(_SANDBOX, ignore_errors=True)
    return rc


if __name__ == '__main__':
    sys.exit(main())
