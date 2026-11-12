#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""hive/test_chat.py —— hive/chat.py 的守卫（断言 ＋ 定点变异自证）

# 功能名：群聊最小实现的守卫——逐条断言 ＋ 每条判据一个定点变异
# 生效条件：凡改动 hive/chat.py 后；凡要把群聊用于实际团队记录前。
# 子功能：① 临时群夹具（自造，确定性）② 19 条断言 ③ 14 条定点变异自证
# 执行：python -X utf8 hive/test_chat.py [--mutate]
# 验证方式：基线全绿；变异模式下每条恰好命中声明红项
#
# #159 补的 6 条零覆盖断言（原 12 条只覆盖「协议正常路径」，权限面与 PASS 重复面全空）：
#   C13 非持牌者发言 → 拒且不落盘      （原判据序列「成员→kind→@」无令牌闸）
#   C14 令牌过期后原持有者发言 → 拒    （过期只在 load_token 层测过，未与 post 联测）
#   C15 发牌权：by 非主持人 → 拒        （issue_token 的 by 原样不校验）
#   C16 交还权：非持有者 release → 拒   （release_token 不判 by 是谁）
#   C17 撤回权：member 撤他人 → 拒      （retract 不读原作者）
#   C18 第二轮 PASS 仍落盘              （原 C8 只测第一次，幂等剔 ts 把第二轮吃掉）
# 另加 C19（第 7 条）：CLI 操作路径闭环 token-issue → post → token-release。理由：发言须持牌后
#   CLI 若不能发牌就只剩 read 可用（原 CLI 只有 post/pass/retract/read）⇒ 新增的 CLI 面必须自带
#   端到端断言，否则「新增面零覆盖」在本 issue 里重演一次。
# 不适用条件：不适用于真实群的业务正确性（本守卫只测协议实现逻辑）
"""

import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import types

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "chat.py")
_red = []
_pass = 0
_quiet = False


def ok(name, cond, detail=""):
    global _pass
    if cond:
        _pass += 1
        if not _quiet:
            print("  [PASS] " + name)
    else:
        if not _quiet:
            print("  [FAIL] " + name + ("  · " + str(detail)[:160] if detail else ""))
        _red.append(name.split()[0])


def mkcrew(mod):
    d = tempfile.mkdtemp(prefix="chat_fixture_")
    with io.open(os.path.join(d, "crew.json"), "w", encoding="utf-8") as fh:
        json.dump({"id": "t1", "members": {"boss": "owner", "admin": "admin",
                                           "dev": "member", "qa": "member"}},
                  fh, ensure_ascii=False)
    return d


def run_checks(mod):
    d = mkcrew(mod)
    try:
        # ① append-only：源码里不得出现删除消息的接口
        src = io.open(SRC, encoding="utf-8").read()
        has_del = ("def delete_message" in src) or ("def edit_message" in src)
        ok("C1 append-only：不提供删除/修改消息的接口", not has_del, "")

        # ② @ 解析
        ok("C2 @ 解析：多目标、去重保序",
           mod.mentions("@dev 和 @qa 请看 @dev") == ["dev", "qa"],
           mod.mentions("@dev 和 @qa 请看 @dev"))

        # ③ 成员校验
        bad, why = mod.post(d, "outsider", "hello")
        ok("C3 非群成员发言 → 拒", bad is False and "非群成员" in why, why)

        # ④ kind 闭集
        bad2, why2 = mod.post(d, "dev", "hi", kind="unknown")
        ok("C4 未知消息类型 → 拒", bad2 is False and "未知消息类型" in why2, why2)

        # ⑮ 发牌权：by 须为 owner/admin（#159 缺陷②）
        #     独立群：令牌面断言不污染主流程的令牌态（否则一条判据被短路会级联到 C5/C6/C10）
        d15 = mkcrew(mod)
        try:
            t15a, why15a = mod.issue_token(d15, "qa", "dev")        # by=普通成员
            t15b, why15b = mod.issue_token(d15, "qa", "outsider")   # by=非成员
            ok("C15 发牌权：by 非主持人 → 拒（返回 None ＋ 拒因，不落牌）",
               t15a is None and "非主持人" in why15a and t15b is None
               and "非主持人" in why15b and mod.load_token(d15) is None,
               (why15a, why15b, mod.load_token(d15)))
        finally:
            shutil.rmtree(d15, ignore_errors=True)

        # ⑬ 非持牌者发言 → 拒且不落盘（#159 缺陷①：令牌只发不查）——独立群（无人持牌）
        d13 = mkcrew(mod)
        try:
            n13 = len(mod.read_messages(d13))
            bad13, why13 = mod.post(d13, "dev", "@qa 我先说", refs=["issue:9"])
            n13b = len(mod.read_messages(d13))
            ok("C13 非持牌者发言 → 拒且不落盘（令牌只在持有者手上可用）",
               bad13 is False and "未持有发言令牌" in why13 and n13b == n13,
               (why13, n13, n13b))
        finally:
            shutil.rmtree(d13, ignore_errors=True)

        # ⑭ 令牌过期后原持有者发言 → 拒（过期即无主，与 load_token 同判据）——独立群
        d14 = mkcrew(mod)
        try:
            mod.issue_token(d14, "admin", "admin")
            bad14, why14 = mod.post(d14, "admin", "过期后还想说",
                                    now=mod._now() + mod.TOKEN_TTL + 10)
            ok("C14 令牌过期后原持有者发言 → 拒（过期即无主）",
               bad14 is False and "未持有发言令牌" in why14, why14)
        finally:
            shutil.rmtree(d14, ignore_errors=True)

        # —— 进入「admin 持牌」态：C5/C6 都在持牌态下测（协议要求发言须持牌）——
        mod.issue_token(d, "admin", "admin")

        # ⑤ @ 必须带 refs
        bad3, why3 = mod.post(d, "admin", "@dev 你看一下")
        msgs = mod.read_messages(d)
        noise = [m for m in msgs if m.get("kind") == "system" and "噪声传唤" in str(m.get("text"))]
        ok("C5 @ 未带 refs → 拒 ＋ 按噪声记账在发起者头上",
           bad3 is False and "噪声" in why3 and len(noise) == 1, (why3, len(noise)))

        # ⑥ 带 refs 的 @ 通过
        good, rec = mod.post(d, "admin", "@dev 请核 issue#7", refs=["issue:7"])
        ok("C6 @ 带 refs → 通过且 refs 落盘",
           good is True and rec.get("refs") == ["issue:7"], rec)

        # ⑦ 幂等
        again = mod.append(d, {"from": "admin", "kind": "text", "text": "@dev 请核 issue#7",
                               "refs": ["issue:7"]})
        n_same = len([m for m in mod.read_messages(d)
                      if m.get("text") == "@dev 请核 issue#7"])
        # 类型防御：若前置（C6 通过）已失效，rec 是**拒因字符串**而非记录——此时必须
        # 由断言干净点名，而不是让守卫自己 AttributeError 崩掉（同 test_coldverify_drain 口径）。
        ok("C7 同内容幂等：不重复追加",
           isinstance(rec, dict) and isinstance(again, dict) and n_same == 1
           and again.get("id") == rec.get("id"),
           (n_same, again.get("id"), rec.get("id")))

        # ⑧ PASS 也落盘
        pok, prec = mod.do_pass(d, "qa")
        n_pass = len([m for m in mod.read_messages(d) if m.get("kind") == "pass"])
        ok("C8 PASS 也落盘（否则「没说话」与「没参与」不可区分）",
           pok is True and n_pass == 1 and prec.get("kind") == "pass", n_pass)

        # ⑱ 第二轮 PASS 仍落盘（#159 缺陷④：幂等剔 ts 把第二轮吃掉）——独立群
        #     同 ts 的重复调用仍应去重（保住「重试不重复追加」）——故此处用不同 ts。
        d18 = mkcrew(mod)
        try:
            mod.do_pass(d18, "qa")
            mod.do_pass(d18, "qa", now=mod._now() + 1)
            n18 = len([m for m in mod.read_messages(d18) if m.get("kind") == "pass"])
            ok("C18 第二轮 PASS 仍落盘（幂等不得抵消「参与」记录）", n18 == 2, n18)
        finally:
            shutil.rmtree(d18, ignore_errors=True)

        # ⑯ 交还权：只有持有者本人能交还（#159 缺陷②）——独立群
        d16 = mkcrew(mod)
        try:
            mod.issue_token(d16, "admin", "admin")
            rel16 = mod.release_token(d16, "dev")        # dev 不是持有者（admin 是）
            holder16 = (mod.load_token(d16) or {}).get("holder")
            ok("C16 交还权：非持有者 release → 拒且令牌仍在位",
               rel16 is False and holder16 == "admin", (rel16, holder16))
        finally:
            shutil.rmtree(d16, ignore_errors=True)
        mod.release_token(d, "admin")               # 持有者本人交还主群令牌（腾牌给 C10）

        # ⑨ 撤回＝事件，不删原文（admin 撤**自己**发的那条：撤回权判据的原作者面）
        rec_id = rec.get("id") if isinstance(rec, dict) else "msg_无（C6 未通过）"
        before = len(mod.read_messages(d))
        rok, rrec = mod.retract(d, "admin", rec_id)
        after = mod.read_messages(d)
        still = any(m.get("id") == rec_id for m in after)
        ok("C9 撤回＝事件（原文仍在，审计面无空洞）",
           rok is True and len(after) == before + 1 and still
           and isinstance(rrec, dict) and rrec.get("kind") == "retract"
           and rrec.get("refs") == ["msg:" + rec_id],
           (before, len(after), still))

        # ⑫ 撤回**不存在**的消息 → 拒（存在性判据；M1 变异即针对本判据）
        nok, nwhy = mod.retract(d, "admin", "msg_不存在")
        ok("C12 撤回不存在的消息 → 拒（存在性判据）",
           nok is False and "不存在" in nwhy, nwhy)

        # ⑰ 撤回权：member 撤他人 → 拒；owner/admin 撤他人 → 允许（#159 缺陷③）——独立群
        #     先让 owner 发一条（发言须持牌），再让 qa（member）去撤它。
        d17 = mkcrew(mod)
        try:
            mod.issue_token(d17, "boss", "admin")
            _, boss_rec = mod.post(d17, "boss", "群主公告：issue#7 由我核", refs=["issue:7"])
            mod.release_token(d17, "boss")
            mod.issue_token(d17, "qa", "admin")
            _, qa_rec = mod.post(d17, "qa", "我发一条待撤的", refs=["issue:8"])
            deny17, why17 = mod.retract(d17, "qa", boss_rec["id"])   # 普通成员撤群主
            allow17, _ = mod.retract(d17, "admin", qa_rec["id"])     # 管理员撤他人
            ok("C17 撤回权：member 撤他人消息 → 拒；owner/admin 撤他人 → 允许",
               deny17 is False and "无权撤回" in why17 and allow17 is True, (why17, allow17))
        finally:
            shutil.rmtree(d17, ignore_errors=True)

        # ⑲ CLI 操作路径闭环：token-issue → post → token-release（#159 新增的 CLI 面）
        #     发言须持牌后，CLI 若不能发牌则只剩 read 可用 ⇒ 操作路径必须端到端有断言
        #     （新增面零覆盖正是本 issue 的病根，不得在新面上重演）。
        d19 = mkcrew(mod)
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                rc_ti = mod.main(["--crew", d19, "token-issue", "--from", "admin", "--to", "qa"])
                rc_post = mod.main(["--crew", d19, "post", "--from", "qa", "--text", "CLI 发言"])
                rc_rel = mod.main(["--crew", d19, "token-release", "--from", "qa"])
                rc_post2 = mod.main(["--crew", d19, "post", "--from", "qa", "--text", "交还后再说"])
            ok("C19 CLI 路径闭环：发牌 → 发言 → 交还 →（无牌）再发言被拒",
               rc_ti == 0 and rc_post == 0 and rc_rel == 0 and rc_post2 == 1,
               (rc_ti, rc_post, rc_rel, rc_post2))
        finally:
            shutil.rmtree(d19, ignore_errors=True)

        # ⑩ 令牌互斥
        t1, blk1 = mod.issue_token(d, "dev", "admin")
        t2, blk2 = mod.issue_token(d, "qa", "admin")
        ok("C10 发言令牌互斥：已有人持有时发不出（返回现任持有者）",
           t1 is not None and blk1 is None and t2 is None and blk2 == "dev", (blk1, blk2))

        # ⑪ 令牌过期即无主（不需显式回收）
        future = mod._now() + mod.TOKEN_TTL + 10
        cur_later = mod.load_token(d, now=future)
        t3, blk3 = mod.issue_token(d, "qa", "admin", now=future)
        ok("C11 令牌到期即视为无主（load 返回 None，可重新发放）",
           cur_later is None and t3 is not None and t3.get("holder") == "qa", (cur_later, t3))
    finally:
        shutil.rmtree(d, ignore_errors=True)


_MUTATIONS = (
    ("M1 关撤回的存在性判据（撤不存在的 id 也放行）",
     '    hit = next((m for m in msgs if m.get("id") == target_id), None)',
     '    hit = next((m for m in msgs if m.get("id") == target_id), {"from": sender})  # MUT',
     {"C12"}),
    ("M2 关 @ 必须带 refs 约束",
     "        if targets and not refs:",
     "        if False:  # MUT", {"C5"}),
    ("M3 关令牌互斥（可重复发放）",
     "    if cur is not None:",
     "    if False:  # MUT", {"C10"}),
    # M4 期望含 C14：C14 与 C11 钉的是**同一条**「过期即无主」判据（C11 在
    # load_token 层、C14 在 post 层），关掉该判据两条同时失去依据 ⇒ 恰好红两条。
    ("M4 关令牌到期判定",
     "    if float(tok.get(\"until\") or 0) <= now:",
     "    if False:  # MUT", {"C11", "C14"}),
    # M5 期望含 C18：C8（首轮 PASS 落盘）与 C18（二轮 PASS 落盘）钉的是同一条
    # 「PASS 也要落盘」判据的两个时点，杀掉落盘两条同时失去依据。
    ("M5 PASS 不落盘",
     "    rec = append(crew_dir, {\"from\": sender, \"kind\": \"pass\", \"text\": \"\",",
     "    return True, {}  # MUT" + chr(10) + "    rec = append(crew_dir, {\"from\": sender, \"kind\": \"pass\", \"text\": \"\",", {"C8", "C18"}),
    ("M6 关 kind 闭集校验（任意类型放行）",
     '    if kind not in KINDS:',
     '    if False:  # MUT', {"C4"}),
    ("M7 关幂等（同内容重复追加）",
     "        if old_probe == probe:",
     "        if False:  # MUT", {"C7"}),
    ("M8 关 @ 解析（返回空）",
     "    out = []" + chr(10) + "    i = 0",
     "    return []  # MUT" + chr(10) + "    out = []" + chr(10) + "    i = 0", {"C2", "C5"}),
    # —— #159 新增判据的定点变异（一条判据一个变异）——
    # M9 期望 {C13,C14}：两者都是「发言须持牌」的两个时点（无牌者／过期持有者），
    # 关掉令牌闸后两条同时失去依据。
    # M9 期望含 C19：C19 的末步（交还后再发言应拒）与 C13/C14 钉的是同一条
    # 「发言须持牌」判据，关掉令牌闸三处同时失去依据。
    ("M9 关 post 的令牌持有判据（谁都能说）",
     '    tok = load_token(crew_dir, now=now)' + chr(10)
     + '    if tok is None or str(tok.get("holder")) != str(sender):',
     '    if False:  # MUT', {"C13", "C14", "C19"}),
    ("M10 关发牌权判据（谁都能发牌）",
     "    if role_of(crew, by) not in HOST_ROLES:",
     "    if False:  # MUT", {"C15"}),
    ("M11 关交还权判据（谁都能替人收牌）",
     '    if str(cur.get("holder")) != str(by):',
     "    if False:  # MUT", {"C16"}),
    ("M12 关撤回原作者判据（谁都能撤他人消息）",
     '    if str(hit.get("from")) != str(sender) and role_of(crew, sender) not in HOST_ROLES:',
     "    if False:  # MUT", {"C17"}),
    ("M13 PASS 也剔 ts（幂等吃掉二轮 PASS）",
     '    drop = ("id",) if rec.get("kind") == "pass" else ("id", "ts")',
     '    drop = ("id", "ts")  # MUT', {"C18"}),
    ("M14 CLI 发牌断链（token-issue 不落牌）",
     "        tok, why = issue_token(args.crew, args.holder, args.sender, ttl=args.ttl)",
     '        tok, why = None, "MUT"  # MUT', {"C19"}),
)


def _load(text, name="chat_mut"):
    mod = types.ModuleType(name)
    mod.__file__ = SRC
    exec(compile(text, "<chat-mut>", "exec"), mod.__dict__)
    return mod


def _mutate_mode():
    print("!! 定点变异自证：逐条短路一条判据，对应断言必须**恰好**转红" + chr(10))
    base = io.open(SRC, encoding="utf-8").read()
    bad = []
    for name, old, new, expect in _MUTATIONS:
        if base.count(old) != 1:
            print("  ANCHOR-MISS %s：锚点命中 %d 次" % (name, base.count(old)))
            bad.append(name)
            continue
        global _red, _quiet, _pass
        _red, _quiet, _pass = [], True, 0
        try:
            run_checks(_load(base.replace(old, new)))
        except Exception as e:
            _quiet = False
            print("  [FAIL] %s 运行异常：%s" % (name, str(e)[:120]))
            bad.append(name)
            continue
        _quiet = False
        got = set(_red)
        flag = "PASS" if got == expect else "FAIL"
        print("  [%s] %s：红项 %d（期望 %d）%s" % (flag, name, len(got), len(expect),
              "" if got == expect else " 实=%s 期=%s" % (sorted(got), sorted(expect))))
        if got != expect:
            bad.append(name)
    print()
    if bad:
        print("定点变异：FAIL —— " + "；".join(bad))
        return 1
    print("定点变异：PASS（逐条恰好命中期望红项）")
    return 0


def main(argv):
    global _red          # 必须声明：否则 _red=[] 成为局部变量，汇总恒报「失败 0」
    if "--mutate" in argv:
        return _mutate_mode()
    global _pass
    print("== hive/chat.py 守卫（断言）==")
    _red, _pass = [], 0
    run_checks(_load(io.open(SRC, encoding="utf-8").read(), "chat_base"))
    print("=" * 70)
    if _red:
        print("通过 %d / 失败 %d" % (_pass, len(_red)))
        print("失败项：" + " / ".join(_red))
        return 1
    print("通过 %d / 失败 0" % _pass)
    print("ALL OK（反面证明见 --mutate）")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
