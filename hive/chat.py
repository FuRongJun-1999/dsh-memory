# -*- coding: utf-8 -*-
"""hive/chat.py —— 群聊协议 v0.1 的最小可跑件（借 QQ 群聊成熟模型）

# 功能名：群聊最小实现——append-only 消息流 ＋ 三级角色 ＋ @ 传唤 ＋ 发言令牌 ＋ 撤回事件
# 生效条件：凡要让「人可对话的团队入口」落成可跑件时；凡要记录团队待决项与状态展示时。
# 子功能：① 群与成员（crew.json，QQ 三级角色：owner/admin/member）
#         ② 消息流（chat.jsonl，**append-only**：不提供任何删除/修改接口）
#         ③ @ 传唤（**必须带 refs**，否则按噪声记账在发起者头上）
#         ④ 发言令牌（显式租约＋到期，与蜂巢 claimed.lock／悬赏站 lease 同构）
#         ⑤ 撤回＝**事件**（不删原文）⑥ PASS 也落盘（否则「没说话」与「没参与」不可区分）
#         ⑦ 令牌**持有者校验**与撤回**原作者判据**（#159：发牌权＝owner/admin；发言须持牌）
# 执行：python -X utf8 hive/chat.py --crew DIR token-issue --from admin --to dev   # 主持人发牌
#       python -X utf8 hive/chat.py --crew DIR post --from dev --text "@qa 核 issue#7" --ref issue:7
#       python -X utf8 hive/chat.py --crew DIR token-release --from dev               # 持有者交还
#       python -X utf8 hive/chat.py --crew DIR read [--since TS] [--limit N]
# 验证方式：hive/test_chat.py（断言 ＋ 定点变异自证）
# 不适用条件：不适用于对外域（那走悬赏站命令面，外部认领者不进群聊）；不适用于当调度面
#            （群聊不下调度指令，唯一出口是 spec.json 走蜂巢）。
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import sys
import time

# ---- 口径单点（改口径只改这里）------------------------------------------------

#: 群成员三级角色（照搬 QQ：群主／管理员／成员）。
ROLES = ("owner", "admin", "member")

#: 主持人（可发放/收回发言令牌、可撤他人消息的管理角色）——照搬 QQ 的群主/管理员。
HOST_ROLES = ("owner", "admin")

#: 消息类型闭集。
KINDS = ("text", "pass", "system", "retract", "token")

#: 发言令牌默认时长（秒）——15 分钟，与「发言一次」同量级。**可调**。
TOKEN_TTL = 15 * 60

#: 消息 id 前缀。
MSG_PREFIX = "msg_"


# ---- 基础 --------------------------------------------------------------------


def _now() -> float:
    return time.time()


def msg_id(rec: dict) -> str:
    """消息指纹＝剔除 id 后内容的 sha1 前 12 位（同内容幂等去重，同账本纪律）。"""
    body = {k: v for k, v in rec.items() if k != "id"}
    blob = json.dumps(body, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return MSG_PREFIX + hashlib.sha1(blob).hexdigest()[:12]


def mentions(text: str):
    """从正文解析 @ 目标（照搬 QQ 的 @ 语义）：返回被 @ 的名单（去重保序）。"""
    out = []
    i = 0
    s = text or ""
    while i < len(s):
        if s[i] == "@":
            j = i + 1
            while j < len(s) and (s[j].isalnum() or s[j] in "_-."):
                j += 1
            name = s[i + 1:j]
            if name and name not in out:
                out.append(name)
            i = j
        else:
            i += 1
    return out


# ---- 群与成员 ----------------------------------------------------------------


def crew_path(crew_dir: str) -> str:
    return os.path.join(crew_dir, "crew.json")


def load_crew(crew_dir: str) -> dict:
    p = crew_path(crew_dir)
    if not os.path.isfile(p):
        return {"id": os.path.basename(os.path.abspath(crew_dir)), "members": {}}
    with io.open(p, encoding="utf-8") as fh:
        return json.load(fh)


def role_of(crew: dict, who: str) -> str:
    return str((crew.get("members") or {}).get(who) or "")


def is_member(crew: dict, who: str) -> bool:
    return role_of(crew, who) in ROLES


# ---- 消息流（append-only）-----------------------------------------------------


def chat_path(crew_dir: str) -> str:
    return os.path.join(crew_dir, "chat.jsonl")


def read_messages(crew_dir: str, since=None, limit=None):
    """读消息流（只读）。since=epoch 秒下界（不含）；limit=最多条数（取最新 N 后按时间正序）。"""
    p = chat_path(crew_dir)
    if not os.path.isfile(p):
        return []
    out = []
    with io.open(p, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            if since is not None and float(rec.get("ts") or 0) <= float(since):
                continue
            out.append(rec)
    if limit is not None and limit >= 0:
        out = out[-int(limit):]
    return out


def _probe_key(rec: dict) -> dict:
    """幂等指纹：恒剔 id；**PASS 另保留 ts**（#159 缺陷④）。

    PASS 是「参与事件」不是「内容」——两条不同时刻的 PASS 是两个参与事实，
    剔 ts 会让第二轮 PASS 被自家去重吃掉（新增行数 0），与「PASS 也要落盘，
    否则『没说话』与『没参与』不可区分」直接冲突。同 ts 的重复调用仍被去重，
    「重试不重复追加」这条幂等本义不变。其余类型维持「剔 id/ts」的账本口径。
    """
    drop = ("id",) if rec.get("kind") == "pass" else ("id", "ts")
    return {k: v for k, v in rec.items() if k not in drop}


def append(crew_dir: str, rec: dict):
    """追加一条消息（**唯一写入口**；无删除/修改接口）。返回落盘记录（含 id）。

    幂等：同内容（指纹见 `_probe_key`）已存在 ⇒ 不重复追加，返回既有记录。
    """
    os.makedirs(crew_dir, exist_ok=True)
    rec = dict(rec)
    rec.setdefault("ts", _now())
    probe = _probe_key(rec)
    for old in read_messages(crew_dir):
        old_probe = _probe_key(old)
        if old_probe == probe:
            return old
    rec["id"] = msg_id(rec)
    p = chat_path(crew_dir)
    with io.open(p, "a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False, sort_keys=True) + "\n")
    return rec


# ---- 发言令牌（显式租约，与 claimed.lock／lease 同构）---------------------------


def token_path(crew_dir: str) -> str:
    return os.path.join(crew_dir, "token.json")


def load_token(crew_dir: str, now=None):
    """读当前令牌；已过期返回 None（**过期即视为无主**，不需显式回收）。"""
    p = token_path(crew_dir)
    if not os.path.isfile(p):
        return None
    try:
        with io.open(p, encoding="utf-8") as fh:
            tok = json.load(fh)
    except Exception:
        return None
    now = _now() if now is None else now
    if float(tok.get("until") or 0) <= now:
        return None
    return tok


def issue_token(crew_dir: str, holder: str, by: str, ttl: int = TOKEN_TTL, now=None):
    """发放发言令牌（**主持人**动作）。已有人持有时返回 (None, 现任持有者)。

    返回 (token, blocking_holder)。

    发牌权判据（#159 缺陷②，群聊协议 v0.1 §三·B「**主持人**发放令牌」）：
    `by` 须为 owner/admin；`holder` 须为群成员（非成员持牌
    只会把牌占死、谁也发不出去）。两种拒因与「被现任持有者挡住」共用第二元，
    按文案区分：持牌冲突回**持有者名**，权限不足回**拒因**。
    """
    now = _now() if now is None else now
    crew = load_crew(crew_dir)
    if role_of(crew, by) not in HOST_ROLES:
        return None, "非主持人（须 owner/admin）：%s" % by
    if not is_member(crew, holder):
        return None, "非群成员不得持牌：%s" % holder
    cur = load_token(crew_dir, now=now)
    if cur is not None:
        return None, cur.get("holder")
    tok = {"holder": holder, "issued_by": by, "issued": now, "until": now + float(ttl),
           "ttl": int(ttl)}
    os.makedirs(crew_dir, exist_ok=True)
    with io.open(token_path(crew_dir), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(tok, ensure_ascii=False, sort_keys=True) + "\n")
    append(crew_dir, {"from": by, "kind": "token",
                      "text": "令牌发给 @" + holder + "（至 " + str(round(tok["until"], 3)) + "）",
                      "refs": ["token:" + holder], "ts": now})
    return tok, None


def release_token(crew_dir: str, by: str, now=None):
    """交还令牌（发言完毕或 PASS 后）。返回是否确实释放。

    交还权判据（#159 缺陷②）：**只有持有者本人**能把牌交回——否则任何成员都能
    替别人收牌（实测：qa 可把 dev 手上的牌收走），令牌互斥形同虚设。
    """
    now = _now() if now is None else now
    cur = load_token(crew_dir, now=now)
    if cur is None:
        return False
    if str(cur.get("holder")) != str(by):
        return False
    try:
        os.remove(token_path(crew_dir))
    except OSError:
        return False
    append(crew_dir, {"from": by, "kind": "token", "text": "令牌交还",
                      "refs": ["token:" + str(cur.get("holder"))], "ts": now})
    return True


# ---- 发言（含 @ 约束与 PASS 落盘）---------------------------------------------


def post(crew_dir: str, sender: str, text: str, refs=None, kind: str = "text", now=None):
    """发言。返回 (ok, rec_or_reason)。

    校验依序：① 发送者须为群成员 ② kind 须在闭集 ③ **须持有发言令牌**
    （#159 缺陷①：原判据只到「成员→kind→@」，令牌只发不查 ⇒ 令牌在他人手上时
    第三方照样发言成功）④ **@ 传唤必须带 refs**（否则按噪声记账在发起者头上：
    记一条 system 事件并拒绝该次发言）。

    令牌闸放在 @ 闸之前：无牌者不是发言者，不该在流里留下噪声事件（防「用噪声
    刷屏」）；且 @ 噪声记账的本义是记**有发言权者**的滥用。
    """
    now = _now() if now is None else now
    refs = list(refs or [])
    crew = load_crew(crew_dir)
    if not is_member(crew, sender):
        return False, "非群成员：%s" % sender
    if kind not in KINDS:
        return False, "未知消息类型：%s" % kind
    tok = load_token(crew_dir, now=now)
    if tok is None or str(tok.get("holder")) != str(sender):
        return False, "未持有发言令牌：%s（现任持有者=%s）" % (
            sender, str((tok or {}).get("holder") or "无"))
    if kind == "text":
        targets = mentions(text)
        if targets and not refs:
            append(crew_dir, {"from": sender, "kind": "system",
                              "text": "噪声传唤被拒（@ " + "、".join(targets) + " 未带待决项）",
                              "refs": ["noise:" + sender], "ts": now})
            return False, "传唤未带 refs（按噪声记账）"
    rec = append(crew_dir, {"from": sender, "kind": kind, "text": text,
                            "refs": refs, "ts": now})
    return True, rec


def do_pass(crew_dir: str, sender: str, now=None):
    """PASS（沉默）——**也要落盘**：否则「没说话」与「没参与」事后不可区分。"""
    now = _now() if now is None else now
    crew = load_crew(crew_dir)
    if not is_member(crew, sender):
        return False, "非群成员：%s" % sender
    rec = append(crew_dir, {"from": sender, "kind": "pass", "text": "",
                            "refs": [], "ts": now})
    return True, rec


def retract(crew_dir: str, sender: str, target_id: str, now=None):
    """撤回＝**记事件，不删原文**（与账本 append-only 铁律一致）。

    撤回权判据（#159 缺陷③）：**本人**可撤自己的消息；**owner/admin**（群主／
    管理员，照搬 QQ 的管理面）可撤他人消息；普通 member 撤他人 → 拒。原判据只查
    「发送者是成员 ＋ 目标存在」，实测 member 可撤 owner 的消息。
    """
    now = _now() if now is None else now
    crew = load_crew(crew_dir)
    if not is_member(crew, sender):
        return False, "非群成员：%s" % sender
    msgs = read_messages(crew_dir)
    hit = next((m for m in msgs if m.get("id") == target_id), None)
    if hit is None:
        return False, "被撤消息不存在：%s" % target_id
    if str(hit.get("from")) != str(sender) and role_of(crew, sender) not in HOST_ROLES:
        return False, "无权撤回他人消息：%s（原作者=%s；仅本人或 owner/admin 可撤）" % (
            sender, hit.get("from"))
    rec = append(crew_dir, {"from": sender, "kind": "retract", "text": "撤回",
                            "refs": ["msg:" + target_id], "ts": now})
    return True, rec


# ---- CLI ---------------------------------------------------------------------


def main(argv=None):
    ap = argparse.ArgumentParser(description="群聊最小实现（append-only）")
    ap.add_argument("--crew", required=True, help="群目录")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("post")
    p.add_argument("--from", dest="sender", required=True)
    p.add_argument("--text", required=True)
    p.add_argument("--ref", action="append", default=[])
    p.add_argument("--kind", default="text")

    r = sub.add_parser("read")
    r.add_argument("--since", type=float, default=None)
    r.add_argument("--limit", type=int, default=None)

    s = sub.add_parser("pass")
    s.add_argument("--from", dest="sender", required=True)

    t = sub.add_parser("retract")
    t.add_argument("--from", dest="sender", required=True)
    t.add_argument("--target", required=True)

    ti = sub.add_parser("token-issue", help="主持人发放发言令牌（须 owner/admin）")
    ti.add_argument("--from", dest="sender", required=True, help="主持人")
    ti.add_argument("--to", dest="holder", required=True, help="持牌成员")
    ti.add_argument("--ttl", type=int, default=TOKEN_TTL)

    tr = sub.add_parser("token-release", help="持有者本人交还令牌")
    tr.add_argument("--from", dest="sender", required=True)

    args = ap.parse_args(argv)
    if args.cmd == "post":
        ok, out = post(args.crew, args.sender, args.text, args.ref, args.kind)
    elif args.cmd == "pass":
        ok, out = do_pass(args.crew, args.sender)
    elif args.cmd == "retract":
        ok, out = retract(args.crew, args.sender, args.target)
    elif args.cmd == "token-issue":
        # 操作路径闭环（#159）：发言须持牌 ⇒ CLI 必须能发牌，否则 CLI 只剩 read 可用。
        tok, why = issue_token(args.crew, args.holder, args.sender, ttl=args.ttl)
        ok, out = tok is not None, (tok if tok is not None else why)
    elif args.cmd == "token-release":
        rel = release_token(args.crew, args.sender)
        ok, out = rel, {"released": rel, "by": args.sender}
    else:
        ok, out = True, read_messages(args.crew, args.since, args.limit)
    if isinstance(out, list):
        for m in out:
            print("%s | %-8s | %-7s | %s" % (round(float(m.get("ts") or 0), 3),
                                             m.get("from"), m.get("kind"), m.get("text")))
    else:
        print(("OK  " if ok else "REJ ") + json.dumps(out, ensure_ascii=False)[:300])
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
