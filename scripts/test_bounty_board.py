# -*- coding: utf-8 -*-
"""test_bounty_board —— 悬赏板状态机守卫（断言 ＋ 定点变异自证）。

对象：`scripts/bounty_board.py`（**纯逻辑层**——零 IO、零网络，可直接喂夹具）。
设计稿：`docs/plans/悬赏板设计_v0.1.md`；对外规则：`docs/bounty/README.md`。

为什么另立本件：workflow（`.github/workflows/bounty.yml`）只做事件路由，状态机全在
`bounty_board.py`；而悬赏板的**每条校验都是「拒谁于门外」的判据**——判据不设反面
证明就等于没有判据（本仓既有口径：`md_cg/test_w7_redlines.py` 的「注入必红」）。
故本件 = ①逐条正反断言 ＋ ②每条校验一个**定点变异**（把该判据短路 ⇒ 对应断言
**必然转红**且**恰好**转红，多红=断言语义纠缠、少红=判据空转）。

断言组（与 workflow / README 的口径一一对应）：
  [0] 命令解析：只认「命令在最前、行首」的词
  [A] R3 · 入选标记与态（`bounty` 标签在 ∧ 态 ∈ {open, expired}）
  [B] R1 · 无当前持有者
  [C] R2 · 并发认领上限（默认 2，可配）
  [D] R4 · 仅认领人可交付 / 释放
  [E] R5 · 交付必须带链接或证据块
  [F] 生命周期与账本（验收/结算/轮次上限/超时回板/幂等/荣誉榜）
  [G] 离线两模式自证（`--dry-run` 与 `--state` 真跑子进程）

用法：
  python -X utf8 scripts/test_bounty_board.py            # 正向：全断言
  python -X utf8 scripts/test_bounty_board.py --mutate   # 定点变异自证（逐条必红）
  python -X utf8 scripts/test_bounty_board.py --list     # 只列变异表
退出码：0 = 全绿 / 变异逐条恰好命中期望红项；1 = 有断言失败 / 变异未按预期转红；
        2 = ANCHOR-MISS（变异锚点在实现里命中次数 ≠1——实现漂移即硬失败）。
"""
from __future__ import annotations

import inspect
import io
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import bounty_board as bb                                            # noqa: E402

IMPL = os.path.join(HERE, "bounty_board.py")
NOW = bb.parse_ts("2026-10-09T00:00:00Z")
CFG = bb.Config()

PASS = 0
FAIL = 0
FAILS = []


def ok(name, cond, detail=""):
    """逐条记账：`[PASS]` / `[FAIL] name · detail`（同仓 scripts/test_*.py 体例）。"""
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        FAILS.append(name)
        print(f"  [FAIL] {name}" + (f"  · {detail}" if detail else ""))


# 生效条件：给定期望字段缺省时造一个 IssueState 夹具（缺省 = 已入选、开放认领的
# medium 悬赏，作者=维护者）；labels 显式传入时按其构造 includes/has_bounty 两面。
def mk_state(number=101, state="open", holder=None, due=None, rounds=0,
             labels=None, author="FuRongJun-1999", difficulty="difficulty:medium"):
    if labels is None:
        labels = ["bounty", f"bounty:{state}"] + ([difficulty] if difficulty else [])
    return bb.IssueState(number=number, labels=tuple(labels),
                         has_bounty="bounty" in labels, state=state, holder=holder,
                         due_at=due, rounds=rounds, seq=1, difficulty=difficulty,
                         author=author)


# 生效条件：give 为 claim 的附加参数映射时返回该次 /claim 的裁决（actor 缺省 alice）。
def claim(st, actor="alice", active=0, cfg=None):
    return bb.handle_command(st, "/claim", "", "/claim", actor, NOW, cfg or CFG,
                             active_claims=active)


# 生效条件：give 为 deliver 的载荷/正文时返回该次 /deliver 的裁决。
def deliver(st, actor="alice", payload="https://example.com/pull/7", body=None):
    return bb.handle_command(st, "/deliver", payload,
                             body if body is not None else f"/deliver {payload}",
                             actor, NOW, CFG)


# 生效条件：give 为维护者动作参数时返回 /verify 或 /settle 的裁决。
def verify(st, actor="FuRongJun-1999", payload="pass 读数齐全", maint=True):
    return bb.handle_command(st, "/verify", payload, f"/verify {payload}", actor,
                             NOW, CFG, is_maintainer=maint)


def settle(st, actor="FuRongJun-1999", maint=True):
    return bb.handle_command(st, "/settle", "", "/settle", actor, NOW, CFG,
                             is_maintainer=maint)


# ================================================================ [0] 命令解析

def group_parse():
    print("[0] 命令解析：只认「命令在最前、行首」的词")
    c, p = bb.parse_command("/claim")
    ok("A1 行首 /claim 被识别", c == "/claim" and p == "", (c, p))
    c, _p = bb.parse_command("我先看看\n第三行 /claim 一下")
    ok("A2 正文中间出现的命令不认（首行非命令即整条忽略）", c is None, c)
    c, _p = bb.parse_command("claim 我想认领")
    ok("A3 无斜杠的 claim 不认（命令词表为准）", c is None, c)
    c, p = bb.parse_command("/deliver https://example.com/pull/7")
    ok("A4 /deliver 载荷切出", c == "/deliver" and p == "https://example.com/pull/7",
       (c, p))
    c, p = bb.parse_command("   /claim")
    ok("A5 前导空白容忍（行首态）", c == "/claim" and p == "", (c, p))
    c, p = bb.parse_command("/claim：我先占用")
    ok("A6 命令与载荷间无分隔符（`/claim：…`）不认——防近似词误触发",
       c is None and p == "", (c, p))


# ================================================================ [A] R3 标签与态

def group_label_state():
    print("[A] R3 · 入选标记与态（bounty 标签在 ∧ 态 ∈ {open, expired}）")
    st = mk_state(labels=["difficulty:medium"])          # 无 bounty 标签
    d = claim(st)
    ok("B1 无 `bounty` 标签 → 拒", d.ok is False and "bounty" in d.reason, d.reason)
    st = mk_state(state="settled", holder=None)          # 态判据单点（无持有者）
    d = claim(st, actor="bob")
    ok("B2 态为 settled（非 open/expired）→ 拒（不可认领）",
       d.ok is False and "不可认领" in d.reason, d.reason)
    st = mk_state(state="open")
    d = claim(st)
    ok("B3 态为 open → 通过并上锁", d.ok and d.to_state == "claimed"
       and d.holder == "alice", (d.ok, d.to_state, d.holder))
    st = mk_state(state="expired")
    d = claim(st)
    ok("B4 态为 expired → 通过（回板窗口可认领）", d.ok and d.to_state == "claimed",
       (d.ok, d.to_state))
    st = mk_state(labels=["bounty", "difficulty:medium"])   # 有入选标记、无态标签
    d = claim(st)
    ok("B5 有 `bounty` 无态标签 → 按 open 处置（试点口径，README 记载）",
       d.ok and d.from_state == "open", (d.ok, d.from_state))


# ================================================================ [B] R1 无持有者

def group_holder():
    print("[B] R1 · 无当前持有者（标记是权威记录：持有时标签可能仍为 open）")
    # 现场形态：态标签落后（仍 open）但标记里已有持有者 ⇒ 必须被持有者判据拦住。
    st = mk_state(state="open", holder="alice", due="2026-10-12T00:00:00Z")
    d = claim(st, actor="bob")
    ok("C1 已有持有者 → 拒（理由点名持有者与到期）", d.ok is False
       and "已有持有者 @alice" in d.reason, d.reason)
    st = mk_state(state="claimed", holder="alice", due="2026-10-12T00:00:00Z")
    d = claim(st, actor="bob")
    ok("C1b 态与标记一致（claimed）→ 同样拒（持有者判据先于态判据）",
       d.ok is False and "已有持有者 @alice" in d.reason, d.reason)
    st = mk_state(state="open", holder=None)
    d = claim(st, actor="bob")
    ok("C2 无持有者 → 通过", d.ok is True, d.reason)


# ================================================================ [C] R2 并发上限

def group_concurrency():
    print("[C] R2 · 并发认领上限（默认 2）")
    ok("D1 缺省上限 = 2（Config 缺省值即口径真源）", CFG.max_concurrent == 2,
       CFG.max_concurrent)
    st = mk_state(state="open")
    d = claim(st, actor="dave", active=1)
    ok("D2 已持有 1 个（未达上界）→ 通过", d.ok is True, d.reason)
    d = claim(st, actor="dave", active=2)
    ok("D3 已持有 2 个（达上界）→ 拒", d.ok is False and "上限 2" in d.reason,
       d.reason)
    cfg1 = bb.Config(max_concurrent=1)
    d = claim(st, actor="dave", active=1, cfg=cfg1)
    ok("D4 上限可配（=1 且已持有 1）→ 拒", d.ok is False and "上限 1" in d.reason,
       d.reason)


# ================================================================ [D] R4 仅认领人

def group_is_holder():
    print("[D] R4 · 仅认领人可交付 / 释放")
    st = mk_state(state="claimed", holder="alice",
                  due="2026-10-12T00:00:00Z")
    d = deliver(st, actor="bob")
    ok("E1 非持有者 /deliver → 拒", d.ok is False and "仅当前持有者" in d.reason,
       d.reason)
    d = bb.handle_command(st, "/withdraw", "", "/withdraw", "bob", NOW, CFG)
    ok("E2 非持有者 /withdraw → 拒", d.ok is False and "仅当前持有者" in d.reason,
       d.reason)
    d = deliver(st, actor="alice")
    ok("E3 持有者 /deliver → 通过（转 delivered，轮次 +1）",
       d.ok and d.to_state == "delivered" and d.rounds == 1,
       (d.ok, d.to_state, d.rounds))
    d = bb.handle_command(st, "/withdraw", "", "/withdraw", "alice", NOW, CFG)
    ok("E4 持有者 /withdraw → 通过（回板 open，清持有者与到期）",
       d.ok and d.to_state == "open" and d.holder is None and d.due_at is None,
       (d.ok, d.to_state, d.holder))


# ================================================================ [E] R5 交付件

def group_payload():
    print("[E] R5 · 交付必须带链接或证据块")
    st = mk_state(state="claimed", holder="alice")
    d = bb.handle_command(st, "/deliver", "", "/deliver", "alice", NOW, CFG)
    ok("F1 空载荷且无围栏 → 拒", d.ok is False and "必须带链接" in d.reason,
       d.reason)
    d = deliver(st, payload="见附件", body="/deliver 见附件")
    ok("F2 无链接无围栏的说明文字 → 拒", d.ok is False and "必须带链接" in d.reason,
       d.reason)
    d = deliver(st, payload="https://github.com/o/r/pull/7")
    ok("F3 https 链接 → 通过", d.ok is True, d.reason)
    d = deliver(st, payload="http://example.com/evidence")
    ok("F4 http 链接 → 通过", d.ok is True, d.reason)
    d = deliver(st, payload="复现读数如下",
                body="/deliver 复现读数如下\n```\n7 passed in 0.42s\n```")
    ok("F5 载荷无链接但正文带围栏证据块 → 通过", d.ok is True, d.reason)


# ================================================================ [F] 生命周期与账本

def group_lifecycle():
    print("[F] 生命周期与账本（验收 / 结算 / 轮次 / 超时回板 / 幂等 / 荣誉榜）")
    st = mk_state(state="delivered", holder="alice", rounds=1)
    d = verify(st, actor="bob", maint=False)
    ok("G1 非维护者 /verify → 拒", d.ok is False and "仅维护者" in d.reason, d.reason)
    st_open = mk_state(state="open")
    d = verify(st_open)
    ok("G2 态非 delivered 的 /verify → 拒", d.ok is False and "待验收面" in d.reason,
       d.reason)
    d = verify(st)
    ok("G3 维护者 /verify pass → 通过（转 verified）",
       d.ok and d.to_state == "verified", (d.ok, d.to_state))
    d = verify(st, payload="fail 读数不可复跑")
    ok("G4 /verify fail → 回 claimed 返工且记 −5（虚假交付）",
       d.ok and d.to_state == "claimed" and d.delta == bb.SCORE_FAKE_DELIVERY,
       (d.ok, d.to_state, d.delta))
    st_v = mk_state(state="verified", holder="alice", rounds=1)
    d = settle(st_v, actor="bob", maint=False)
    ok("G5 非维护者 /settle → 拒", d.ok is False and "仅维护者" in d.reason, d.reason)
    d = settle(st_open)
    ok("G6 态非 verified 的 /settle → 拒",
       d.ok is False and "不可结算" in d.reason, d.reason)
    d = settle(st_v)
    ok("G7 维护者 /settle → 通过并按 medium 记 +3", d.ok and d.to_state == "settled"
       and d.delta == 3, (d.ok, d.to_state, d.delta))
    st_r3 = mk_state(state="delivered", holder="alice", rounds=3)
    d = deliver(st_r3, actor="alice")
    ok("G8 轮次达上限后再交付 → 拒（最多 3 轮）",
       d.ok is False and "轮次已达上限 3" in d.reason, d.reason)
    st_due = mk_state(state="claimed", holder="carol",
                      due="2026-10-12T09:00:00Z")
    out = bb.sweep([st_due], bb.parse_ts("2026-10-12T09:00:00Z"), CFG)
    ok("G9 超期 claimed → 回板 open 且事件记 −1（负分归属原持有者）",
       len(out) == 1 and out[0].to_state == "open"
       and out[0].delta == bb.SCORE_TIMEOUT
       and out[0].event.get("holder") == "carol"
       and out[0].holder is None,
       (len(out), out[0].to_state if out else None))
    out = bb.sweep([st_due], bb.parse_ts("2026-10-11T00:00:00Z"), CFG)
    ok("G10 未超期 → 不动（sweep 空表）", out == [], out)
    ev = {"ts": "2026-10-09T00:00:00Z", "issue": 1, "action": "settle",
          "actor": "m", "holder": "alice", "delta": 3}
    ev["id"] = bb.event_id(ev)
    led = bb.append_events([], [ev])
    led2 = bb.append_events(led, [dict(ev)])
    ok("G11 账本按 id 幂等（同事件重复投递只入一次）",
       len(led) == 1 and len(led2) == 1, (len(led), len(led2)))
    d_rej = claim(mk_state(state="claimed", holder="alice"), actor="bob")
    led3 = bb.append_events(led, [d_rej.event])
    ok("G12 append-only：拒绝也留痕（delta=0）且不改写既有行",
       len(led3) == 2 and led3[0] == led[0]
       and d_rej.event.get("action") == "reject" and d_rej.event.get("delta") == 0,
       (len(led3), d_rej.event.get("action")))
    board = bb.render_board(led3)
    ok("G13 荣誉榜确定性：同账本两次生成逐字节相同",
       board == bb.render_board(led3), "")
    ok("G14 荣誉榜含贡献者与声誉分（alice +3 ／ bob 0）",
       "@alice | 3" in board and "@bob | 0" in board, board[:200].replace("\n", " | "))
    ok("G15 被拒命令记在**尝试者**头上（bob 计 1 次被拒，不计入持有者 alice）",
       "@bob | 0 | 0 | 0 | 0 | 0 | 1" in board, board.replace("\n", " | ")[:400])


# ================================================================ [G] 离线两模式自证

# 生效条件：argv 为命令行参数列表时以子进程真跑实现脚本（cwd=仓根、UTF-8、超时 300s），
# 返回 CompletedProcess（供断言 rc/stdout/落盘件）。
def run_impl(*argv):
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    return subprocess.run([sys.executable, "-X", "utf8", IMPL, *argv],
                          cwd=REPO, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", env=env, timeout=300)


def group_offline(tmp):
    print("[G] 离线两模式自证（--dry-run ／ --state 真跑子进程）")
    r = run_impl("--dry-run")
    out = r.stdout or ""
    ok("H1 --dry-run 退出码 0（离线演练可一键跑）", r.returncode == 0,
       (r.returncode, (r.stderr or "")[-200:]))
    need = ("open → claimed", "claimed → delivered", "delivered → verified",
            "verified → settled", "claimed → open", "expired")
    ok("H2 演练日志覆盖全部态迁移（claim→deliver→verify→settle ＋ 超时回板）",
       all(x in out for x in need), [x for x in need if x not in out])
    ok("H3 演练日志含账本段与荣誉榜段",
       "---- 账本（" in out and "---- 荣誉榜（由账本机械生成）----" in out, "")
    ok("H4 演练为纯离线（不触网）：日志无 http 请求痕迹",
       "GitHub API" not in out and "网络错误" not in out, "")

    store = os.path.join(tmp, "mirror.json")
    r1 = run_impl("--state", store, "--open-issue", "201", "--labels",
                  "bounty,difficulty:medium", "--author", "FuRongJun-1999")
    r2 = run_impl("--state", store, "--command", "/claim", "--as", "zoe",
                  "--at", "2026-10-09T01:00:00Z")
    r3 = run_impl("--state", store, "--sweep", "--at", "2026-10-12T01:00:00Z")
    r4 = run_impl("--state", store)
    with io.open(store, encoding="utf-8") as fh:
        doc = json.load(fh)
    rec = doc["issues"]["201"]
    ok("H5 --state 三腿全通（建题 / 认领 / 超时回板）",
       r1.returncode == 0 and r2.returncode == 0 and r3.returncode == 0,
       (r1.returncode, r2.returncode, r3.returncode))
    ok("H6 镜像落盘正确：标签回 bounty:open、历史含 claim→expire、账本 2 条",
       "bounty:open" in rec["labels"]
       and [h["action"] for h in rec["history"]] == ["/claim", "/expire"]
       and len(doc["ledger"]) == 2,
       (rec["labels"], [h["action"] for h in rec["history"]], len(doc["ledger"])))
    ok("H7 镜像看板可读（--state 无动作时打印各题一行）",
       r4.returncode == 0 and "#201" in (r4.stdout or ""), (r4.stdout or "")[:120])

    jsonl = os.path.join(tmp, "events.jsonl")
    with io.open(jsonl, "w", encoding="utf-8", newline="\n") as fh:
        for e in doc["ledger"]:
            fh.write(json.dumps(e, ensure_ascii=False) + "\n")
    ledger = os.path.join(tmp, "ledger.json")
    board = os.path.join(tmp, "board.md")
    r5 = run_impl("--ledger-append", jsonl, "--ledger", ledger)
    r6 = run_impl("--board-out", board, "--ledger", ledger)
    with io.open(ledger, encoding="utf-8") as fh:
        ldoc = json.load(fh)
    with io.open(board, encoding="utf-8") as fh:
        btext = fh.read()
    ok("H8 账本收口：--ledger-append 生成带 _schema 的账本（2 条事件）",
       r5.returncode == 0 and ldoc.get("_schema") and len(ldoc["events"]) == 2,
       (r5.returncode, len(ldoc.get("events") or [])))
    r7 = run_impl("--ledger-append", jsonl, "--ledger", ledger)
    with io.open(ledger, encoding="utf-8") as fh:
        ldoc2 = json.load(fh)
    ok("H9 账本收口幂等：重复并入同批 JSONL 不增行",
       r7.returncode == 0 and len(ldoc2["events"]) == 2, len(ldoc2["events"]))
    ok("H10 荣誉榜由账本生成（含贡献者行与计分口径）",
       r6.returncode == 0 and "荣誉榜" in btext and "@zoe | -1" in btext,
       btext[:200].replace("\n", " | "))


# ================================================================ [H] 真模式路由（假客户端，不触网）

class _FakeClient:
    """假 GitHub 客户端：只实现**路由层用到的读面**，把写动作记进 `writes`。

    为什么要有：真模式的写路径原则上只能在 GitHub 上跑，但「路由判据」（PR 评论不处理／
    自带标记不处理／非命令不处理／缺 --apply 不写远端／交付链接读 PR 元数据）**是纯路由
    逻辑**，可用假客户端在本地断言清楚——否则 workflow 那半边的判据只能靠人工看。
    """

    def __init__(self, repo="o/r", comments=(), pr=None, active=0,
                 labels_ready=False):
        self.repo = repo
        self._comments = list(comments)
        self._pr = pr
        self._active = active
        self.labels_ready = labels_ready
        self.writes = []

    def comments(self, n):
        return list(self._comments)

    def pull(self, n):
        return self._pr

    def count_active_claims(self, actor, exclude=None, limit=10):
        return self._active

    def ensure_labels(self, specs):
        self.labels_ready = True
        return []

    def set_labels(self, n, add, remove):
        self.writes.append(("labels", n, tuple(add), tuple(remove)))

    def comment(self, n, body):
        self.writes.append(("comment", n, body))


# 生效条件：payload 为事件体字典、client 为 _FakeClient 时返回 handle_issue_comment 的
# (退出码, 事件列表)，打印面静默（out 给空函数）。
def _route(payload, client, apply=False):
    return bb.handle_issue_comment(payload, bb.Config(), client, apply=apply,
                                   out=lambda *_a: None)


def _issue_payload(body, labels=("bounty", "bounty:open", "difficulty:medium"),
                   number=301, actor="zoe", assoc="NONE", is_pr=False):
    issue = {"number": number, "labels": [{"name": x} for x in labels],
             "user": {"login": "FuRongJun-1999"}}
    if is_pr:
        issue["pull_request"] = {"url": "https://api.github.com/repos/o/r/pulls/9"}
    return {"issue": issue,
            "comment": {"body": body, "user": {"login": actor},
                        "author_association": assoc}}


def group_routing():
    print("[H] 真模式路由（假客户端：PR 评论／自带标记／非命令／计划不写／PR 元数据）")
    code, evs = _route(_issue_payload("/claim", is_pr=True), _FakeClient())
    ok("I1 PR 评论 → 无动作（不写、不产事件）", code == 0 and evs == [], (code, evs))
    marked = "**[悬赏板] 认领成功**\n<!-- bounty:v1 {\"state\":\"claimed\"} -->"
    code, evs = _route(_issue_payload(marked), _FakeClient())
    ok("I2 悬赏板自身留言（含标记）→ 无动作（防自触发循环）",
       code == 0 and evs == [], (code, evs))
    code, evs = _route(_issue_payload("我先看看这个任务，稍后 /claim"), _FakeClient())
    ok("I3 非命令评论 → 无动作", code == 0 and evs == [], (code, evs))
    cli = _FakeClient()
    code, evs = _route(_issue_payload("/claim"), cli, apply=False)
    ok("I4 计划模式（缺 --apply）→ 不写任何远端状态",
       code == 0 and cli.writes == [] and len(evs) == 1, (cli.writes, len(evs)))
    cli = _FakeClient()
    code, evs = _route(_issue_payload("/claim"), cli, apply=True)
    ok("I5 应用模式 → 加标签之一 ＋ 发一条评论（且标签体系就绪）",
       code == 0 and cli.labels_ready is True and len(cli.writes) == 2
       and cli.writes[0][0] == "labels" and cli.writes[1][0] == "comment",
       cli.writes)
    pr = {"title": "fix: 读数可复跑", "state": "open",
          "head": {"sha": "abcdef1234567890"}}
    cli = _FakeClient(comments=["<!-- bounty:v1 {\"state\":\"claimed\","
                                "\"holder\":\"zoe\",\"rounds\":0,\"seq\":1,"
                                "\"due_at\":\"2026-10-12T01:00:00Z\"} -->"], pr=pr)
    url = "https://github.com/o/r/pull/77"
    code, evs = _route(_issue_payload(f"/deliver {url}", actor="zoe"), cli,
                       apply=True)
    ok("I6 交付链接指向本仓 PR → 事件带 PR 元数据（pull-requests: read 那条腿）",
       code == 0 and evs and (evs[0].get("pr") or {}).get("number") == 77
       and (evs[0].get("pr") or {}).get("head_sha") == "abcdef123456",
       evs[0].get("pr") if evs else None)


_GROUPS = (group_parse, group_label_state, group_holder, group_concurrency,
           group_is_holder, group_payload, group_lifecycle, group_routing)


# 生效条件：无必需形参时清账并跑 [0]–[F] 全组（离线子进程组由调用方另跑），返回失败项前缀集合。
def run_suite():
    global PASS, FAIL
    PASS = FAIL = 0
    del FAILS[:]
    for fn in _GROUPS:
        fn()
    return {n.split(" ", 1)[0] for n in FAILS}


# ================================================================ 定点变异（注入判据失效 ⇒ 必红）
# 每条变异 = 把**一条校验**短路（源码级、只改内存里 exec 的副本，不落盘），
# 期望转红的断言项**恰好**等于声明集合：多红 = 断言语义纠缠，少红 = 该判据空转。

_MUTATIONS = (
    ("M0 关命令识别（任意首词当命令）",
     "        if word in COMMANDS:",
     "        if True:  # MUT", {"A2", "A3", "A6", "I3"}),
    ("M1 关 R3 标签判据（无 bounty 标签也放行）",
     "    if not st.has_bounty:",
     "    if False:  # MUT", {"B1"}),
    ("M2 关 R3 态判据（非 open/expired 也放行）",
     "    if st.state not in CLAIMABLE_STATES:",
     "    if False:  # MUT", {"B2"}),
    ("M3 关 R1 无持有者判据（撞锁放行）",
     "    if st.holder:",
     "    if False:  # MUT", {"C1", "C1b"}),
    ("M4 关 R2 并发上限判据（无限并发）",
     "    if active >= cap:",
     "    if False:  # MUT", {"D3", "D4"}),
    ("M5 关 R4 仅认领人判据（他人可交付/释放）",
     "    if st.holder != actor:",
     "    if False:  # MUT", {"E1", "E2"}),
    ("M6 关 R5 链接判据（无据交付放行）",
     "    if _URL_RE.search(payload or \"\"):",
     "    if True:  # MUT", {"F1", "F2"}),
    ("M7 关 R5 证据块判据（围栏交付不再被认）",
     "    if _FENCE_RE.search(body or \"\"):",
     "    if False:  # MUT", {"F5"}),
)


# 生效条件：fn_name 为模块内函数名、old 为唯一锚点、new 为替换文本时，用
# inspect.getsource 取该函数源码，就地 exec 到模块全局（运行中的实现被替换），
# 返回复原函数；锚点命中次数 ≠1 抛 AnchorMiss（调用方记 ANCHOR-MISS）。
class AnchorMiss(Exception):
    pass


def _mut_source(fn_name, old, new):
    orig = getattr(bb, fn_name)
    src = inspect.getsource(orig)
    if src.count(old) != 1:
        raise AnchorMiss(f"{fn_name}: 锚点命中 {src.count(old)} 次（期望 1）：{old!r}")
    exec(compile(src.replace(old, new), f"<bounty-{fn_name}-mut>", "exec"),
         vars(bb))

    def _restore():
        setattr(bb, fn_name, orig)
    return _restore


#: 变异 → 目标函数（锚点落在哪个函数里就变异哪个）。
_MUT_TARGETS = (("M0", "parse_command"), ("M1", "_check_claimable"),
                ("M2", "_check_claimable"), ("M3", "_check_no_holder"),
                ("M4", "_check_concurrency"), ("M5", "_check_is_holder"),
                ("M6", "_check_payload"), ("M7", "_check_payload"))


def _anchor_preflight():
    """锚点自检：任一锚点在当前实现里命中次数 ≠1 → ANCHOR-MISS（退出码 2）。"""
    bad = []
    for (name, _old, _new, _exp), (_mid, fn) in zip(_MUTATIONS, _MUT_TARGETS):
        src = inspect.getsource(getattr(bb, fn))
        if src.count(_old) != 1:
            bad.append((name, src.count(_old)))
    if not bad:
        return 0
    for name, n in bad:
        print(f"  ANCHOR-MISS {name}：锚点命中 {n} 次（期望 1）")
    print("  => 实现已漂移，变异表失效：退出码 2（fail-closed）")
    return 2


def _mutate_mode():
    rc = _anchor_preflight()
    if rc:
        return rc
    print("!! 定点变异自证：逐条短路一条校验，对应断言必须**恰好**转红\n")
    base_red = run_suite()
    print(f"\n  未变异基线：红项 {len(base_red)} "
          f"{'（应为 0）' if not base_red else sorted(base_red)}")
    bad = []
    if base_red:
        bad.append(f"基线即转红：{sorted(base_red)}")
    for (name, old, new, expect), (_mid, fn) in zip(_MUTATIONS, _MUT_TARGETS):
        restore = _mut_source(fn, old, new)
        try:
            red = run_suite()
        except Exception as exc:                                  # noqa: BLE001
            red = {f"<变异体异常:{type(exc).__name__}>"}
        finally:
            restore()
        hit = red == set(expect)
        if not hit:
            bad.append(f"{name}：红项 {sorted(red)} ≠ 期望 {sorted(expect)}")
        print(f"  {'[PASS]' if hit else '[FAIL]'} {name}：红项 {len(red)}"
              f"（期望 {len(expect)}）"
              + ("" if hit else f" 实={sorted(red)} 期={sorted(expect)}"))
    print("\n定点变异：" + ("PASS（逐条恰好命中期望红项）" if not bad
                            else "FAIL —— " + "；".join(bad)))
    return 0 if not bad else 1


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if "--list" in argv:
        for name, _old, _new, exp in _MUTATIONS:
            print(f"  {name:<44} expect_red={len(exp)} {sorted(exp)}")
        return 0
    if "--mutate" in argv:
        return _mutate_mode()

    print("悬赏板状态机守卫（scripts/bounty_board.py · 纯逻辑层断言）")
    print("=" * 74)
    for fn in _GROUPS:
        fn()
    tmp = tempfile.mkdtemp(prefix="bounty_guard_")
    try:
        group_offline(tmp)
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)
    print("=" * 74)
    print(f"通过 {PASS} / 失败 {FAIL}")
    if FAILS:
        print("失败项：" + "，".join(FAILS))
        return 1
    print("ALL OK（反面证明见 --mutate）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
