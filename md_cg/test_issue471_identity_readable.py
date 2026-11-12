# -*- coding: utf-8 -*-
# 功能名：identity 读面的可见性闸守卫（issue #471 · 三处功能面的载体）
# 生效条件：python -u -X utf8 -m md_cg.test_issue471_identity_readable；夹具钉临时区
# 子功能：A private 主体不得被 internal 枚举（且共享档主体仍在）· A' 判别力对照 · B 计数不泄漏 · C content 不泄漏 · D 反向防一刀切 · E 两读面语义一致
# 执行：直接跑；退出码 0=全绿
# 验证方式：全部 PASS；真造两实例（private 写 / internal 读，session 分属 sess_A/sess_B）
# 不适用条件：**(c2) 本件不做** —— profile 的**锚点/指针面**未加闸，因 `_identity_ref`(self_state.py:344) 无读者身份参数、
#   无法区分自我调用与外部调用；属**独立设计问题**（建议单开 issue）。
# ⚠️ **可判性边界（不许改弱）**：本腿**不能判**「**被过滤的主体在别处是否仍可被推断**」—— 若返回体的 nodes 总数/统计量
#   随被过滤主体变化，低权读者可由**差分**推断其存在（**侧信道的残差**）。与 C2/C5/C7 同族：
#   看见「过滤在场」，看不见「有无差分残留」。
# ⚠️ **三处缺口形状不同（不照抄正文的「均未接 _readable」）**：
#   (a) `positions` —— **完全无闸**（遍历索引全量，从未调 `_readable`）；
#   (b) `infer_position` —— **闸在但计数漏**（已经由 `cg.get`，正文拿不到；但 `n += 1` 在空节点时仍执行 ⇒ 泄漏的是 `evidence_count`）；
#   (c1) `profile` —— **闸在但 content 面漏**（`cg.get` 后仍把 `content[:400]`/`content[:200]` 收入 anchors/traits）。
# ★关键语义（`_readable` mdcos.py:6364）：private/secret 是**会话绑定档**（仅归属 session 可见）⇒
#   只给 `sensitivity="private"` 而 session 与读者相同 ⇒ **仍可见**（腿 A 会假绿）。故本腿造 会话分属。
from __future__ import annotations

import io, os, shutil, sys, tempfile

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)
from md_cg import identity as ID                       # noqa: E402
from md_cg.mdcos import MdCGSecure                     # noqa: E402
from md_cg.security import Principal                   # noqa: E402

PASS = FAIL = 0
FAILS = []
PRIVATE_BODY = 'SECRET-BODY-OF-BOB-471'


def ok(name, cond, detail=''):
    global PASS, FAIL
    if cond:
        PASS += 1
        print('  PASS ' + name)
    else:
        FAIL += 1
        FAILS.append(name)
        print('  FAIL ' + name + '  ' + str(detail)[:220])


def mk(root, bob_session, bob_sens='private', clr='internal', rd_session='sess_B'):
    wr = Principal(actor='w471', clearance='private', can_write=True, can_admin=False,
                   role='designer', session='sess_A', harness='test-harness')
    w = MdCGSecure(root, principal=wr)
    w.add('n_alice', '# 功能名：共享\n# 正文：alice 的共享节点',
          layer='knowledge', tags=['subject:user:alice'], session='sess_A')
    w.add('n_bob', '# 功能名：私有\n# 正文：' + PRIVATE_BODY,
          layer='knowledge', tags=['subject:user:bob'], session=bob_session,
          sensitivity=bob_sens)
    # ★(c1) 的夹具（Lead 批准）：`profile` 只把**锚点/特征**节点收进 anchors/traits
    #   ⇒ private 节点若只有 `subject:` 标签，两个分支都不进 ⇒ 移除 (c1) 的闸**无可观测效应**
    #   ⇒ 腿 C2 也无从生效。故**另加**一个带 TAG_ANCHOR 的 private 节点。
    #   ★不动 `n_bob`：`infer_position` 显式排除锚点/特征节点（:425）⇒ 保腿 B 读数不受扰。
    w.add('n_bob_anchor', '# 功能名：私有锚点\n# 正文：' + PRIVATE_BODY,
          layer='anchor', tags=['subject:user:bob', ID.TAG_ANCHOR],
          session=bob_session, sensitivity=bob_sens)
    w.flush()
    w.close()
    rd = Principal(actor='r471', clearance=clr, can_write=False, can_admin=False,
                   role='designer', session=rd_session, harness='test-harness')
    return MdCGSecure(root, principal=rd)


sb = tempfile.mkdtemp(prefix='i471_guard_')
try:
    rd1 = mk(os.path.join(sb, 'k1'), 'sess_A')
    ps = [p['subject_id'] for p in ID.positions(rd1)]
    print('  [读数] internal 读者 positions.subject_id = %s' % ps)
    ok('A1 private 主体 user:bob **不得**被 internal 读者枚举', 'user:bob' not in ps, ps)
    ok('A2 **同库内共享档主体 user:alice 仍在**（防「全不返回」也能过）', 'user:alice' in ps, ps)
    ip = ID.infer_position(rd1, 'user:bob')
    ok('B 计数不泄漏：infer_position(user:bob).evidence_count == 0（不含不可见证据）',
       ip.get('evidence_count') == 0, ip)
    pr = ID.profile(rd1, 'user:bob')
    _all = str(pr)
    # ★C 与 C2 **必须并置**：单独一条 C 会给人「content 面已守住」的错觉 ——
    #   实际只守住了「**正文**」那一半，没守住「**node_id 存在性**」那一半。
    ok('C  content 不泄漏（正文面）：profile 不含不可见节点的**正文子串**',
       PRIVATE_BODY not in _all, _all[:180])
    _aids = [a.get('node_id') for a in (pr.get('anchors') or [])]
    _tids = [t.get('node_id') for t in (pr.get('traits') or [])]
    # ★断言对象必须是**全部** bob 的不可见节点（`n_bob` 与 `n_bob_anchor` 两个）——
    #   我上一版只断言了 `'n_bob'`，而 (c1) 移除后追加的是 `n_bob_anchor` ⇒ 判据打偏、假绿。
    ok('C2 存在性不泄漏（node_id 面）：profile 的 anchors/traits **不含任何不可见 bob 节点的 node_id**',
       not [x for x in (_aids + _tids) if isinstance(x, str) and x.startswith('n_bob')],
       {'anchors': _aids, 'traits': _tids})
    ok('E 两读面语义一致：reader.get(private) 为空 ∧ positions 不含该主体 **同时成立**',
       (not rd1.get('n_bob')) and ('user:bob' not in ps),
       {'get': bool(rd1.get('n_bob')), 'in_positions': 'user:bob' in ps})
    wr2 = Principal(actor='w471b', clearance='private', can_write=True, can_admin=False,
                    role='designer', session='sess_A', harness='test-harness')
    hr = MdCGSecure(os.path.join(sb, 'k1'), principal=wr2)
    ps2 = [p['subject_id'] for p in ID.positions(hr)]
    ok('D1 反向（防一刀切·positions 面）：private+sess_A 读者 **必须仍在** positions 里看到 user:bob',
       'user:bob' in ps2, {'positions': ps2})
    # ★判据面说明（Lead 确认）：**本腿测的是「可见性过滤」，不是「解密能力」**。
    #   `sensitivity=private` 档在盘上可能是加密的（ENCRYPTED_LEVELS），而第二实例的构造
    #   （照抄 test_issue52 的 `MdCGSecure(root, principal=...)`）不传密钥材料 => 解不开 => content 空。
    #   ⇒ content 面**改用共享档（internal）节点验**：可见性过滤成立时它**必须**可取到；
    #     private 节点的 content 能否取到**受加密面限制，本腿不判**。
    pr2 = ID.profile(hr, 'user:alice')
    ok('D2 反向（content 面不因密级一刀切）：共享档主体的 profile 在 private 读者下**必须非空**',
       bool(str(pr2).strip()) and pr2.get('traits') is not None, {'prof_keys': sorted(pr2)})
    hr.close()
    rd1.close()
    # ★A' 的正确对照：必须让 bob 的 sensitivity=internal（clearance 站得住），
    #   否则 bob 是被「clearance 不足」挡掉的，与会话绑定无关（我上一版造错在此）。
    # ★对照必须**把 clearance 固定住**：`internal` 档是**跨会话共享档**（_readable:6309 原文：
    #   「public / internal = 跨会话共享档——任何通过 clearance 的会话可见」）⇒ 用 internal 档**验不出会话绑定**
    #   （我上一版正是错在此：期望「internal+会话不同 => 被挡」，与设计相反）。
    #   ⇒ 要单独验「会话绑定那一维」，须用 **private 档节点 + clearance=private 的读者**，只改读者 session。
    rd3 = mk(os.path.join(sb, 'k3'), 'sess_A', clr='private', rd_session='sess_B')
    ps3 = [p['subject_id'] for p in ID.positions(rd3)]
    print('  [读数·对照1] clearance=private + 读者 session=sess_B（≠bob 的 sess_A）positions = %s' % ps3)
    ok("A'-1 ★clearance 站得住、**仅会话不同** => 仅因**会话绑定**被挡（不在 positions）",
       'user:bob' not in ps3, {'positions': ps3})
    rd3.close()
    rd4 = mk(os.path.join(sb, 'k4'), 'sess_A', clr='private', rd_session='sess_A')
    ps4 = [p['subject_id'] for p in ID.positions(rd4)]
    print('  [读数·对照2] clearance=private + 读者 session=sess_A（=bob 的会话）positions = %s' % ps4)
    ok("A'-2 ★判别力对照：同一 clearance 下只改读者 session => 判据**转红**（bob 出现）",
       'user:bob' in ps4,
       {'positions': ps4, '含义': '排除「clearance 顺带挡掉」，证明**会话绑定那一维独立起作用**'})
    rd4.close()
finally:
    shutil.rmtree(sb, ignore_errors=True)

print('')
print('断言总数 %d（PASS %d / FAIL %d）' % (PASS + FAIL, PASS, FAIL))
if FAILS:
    print('FAILED:')
    for f in FAILS:
        print('   - ' + f)
sys.exit(1 if FAILS else 0)