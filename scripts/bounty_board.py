# -*- coding: utf-8 -*-
"""灵枢悬赏板 · 状态机与 GitHub 路由（MVP · 本地可跑 / 可测 / 可离线演练）。

设计稿：`docs/plans/悬赏板设计_v0.1.md`（v0.1，2026-10-09）。
外壳：`.github/workflows/bounty.yml`（**薄壳**——只做事件路由与调用，业务逻辑全在本文件）。
规则说明（对外）：`docs/bounty/README.md`。账本 / 荣誉榜：`docs/bounty/{ledger.json,board.md}`。

一句话：把公开仓的 issue 池变成可认领的悬赏任务——外部人（或 AI agent）认领 → 交付 →
过我们现成的确定性验收闸 → 记入可追溯的声誉账本（**不涉资金**，结算＝声誉制）。

分层（白箱判据：每一层可单独复核）
---------------------------------------------------------------
① **纯逻辑层**：`parse_command` / `handle_command` / `sweep` / 计分 / 账本 —— 零 IO、
   零网络，入参出参全是数据。离线演练（`--dry-run`）与本地状态文件（`--state`）只跑
   这一层 ⇒ **不需要真网络即可完整演一遍状态迁移**。
② **薄客户端层**：`GitHubClient`（标准库 `urllib`）—— 只做 HTTP 读写；令牌只从
   环境变量读（`BOUNTY_GH_TOKEN` → `GITHUB_TOKEN` → `GH_TOKEN`），**绝不硬编码、
   绝不写盘、绝不进命令行参数**。
③ **路由层**：`main` 按 `--event-file` / `--state` / `--dry-run` / `--ledger-append`
   / `--board-out` 分派。

状态存哪里（关键设计 · 白箱可核）
---------------------------------------------------------------
**issue 线程本身就是状态存储**——每次迁移在评论里落一条机器可读标记（HTML 注释内 JSON）：

    <!-- bounty:v1 {"state":"claimed","holder":"alice","due_at":"…","seq":2,…} -->

标签 `bounty:{open|claimed|delivered|verified|settled|expired|disputed}` 是**人眼视图**
（便于 label 过滤与看板）；标记评论是**权威记录**（取 `seq` 最大一条即可重建：态、
持有者、到期时间、轮次）。超时回板靠标记里的 `due_at`——不依赖任何外部数据库。

命令面（**只认「命令在最前、行首」的词**——正文中间的 `/claim` 不是命令）
---------------------------------------------------------------
| 命令 | 谁用 | 校验（未过即回评说明） |
|---|---|---|
| `/claim` | 认领者 | ①无当前持有者（标记是权威记录，先于态判据）<br>②`bounty` 标签在且在 `open`/`expired` 态 ③本人并发认领数 ≤ `BOUNTY_MAX_CONCURRENT`（默认 2） |
| `/deliver <交付物>` | 认领者 | ①仅本人可交付 ②必带链接（http(s)）或证据块（围栏代码块）<br>③轮次 ≤ `BOUNTY_MAX_ROUNDS`（默认 3） |
| `/withdraw` | 认领者 | 仅本人；主动释放（**不影响声誉**）→ 回板 `open` |
| `/dispute <理由>` | 双方（认领者 / 维护者 / issue 作者） | 必带理由 → `disputed`（留痕，**不扣本金**） |
| `/verify [pass\\|fail] <理由>` | 维护者 | `delivered` 才可验；`fail` ⇒ 记 −5（虚假交付）并回 `claimed` 返工 |
| `/settle` | 维护者 | `verified` 才可结；按 `difficulty:*` 记正分入账本 |

（`/verify`、`/settle` 是设计稿「维护者人审打 `bounty:verified`」与状态机
「`verified` → `settled`」两个动作的**命令化**——设计稿未指定其触发形态，
本文件把维护者动作显式化，供设计者裁定。）

离线两模式（**不需要真网络**）
---------------------------------------------------------------
    # ① 一键演完整生命周期（claim→deliver→verify→settle ＋ 超时回板 ＋ 各拒绝面）
    python -X utf8 scripts/bounty_board.py --dry-run

    # ② 本地状态镜像上逐步演（可反复；时间是显式假时钟）
    python -X utf8 scripts/bounty_board.py --state .tmp/board.json \
        --open-issue 101 --labels bounty,difficulty:medium --author FuRongJun-1999
    python -X utf8 scripts/bounty_board.py --state .tmp/board.json \
        --command "/claim" --as alice --at 2026-10-09T01:00:00Z
    python -X utf8 scripts/bounty_board.py --state .tmp/board.json --sweep \
        --at 2026-10-13T01:00:00Z

真模式（workflow 调用；**缺 `--apply` 时只打印计划，不写任何远端状态**）
---------------------------------------------------------------
    python -X utf8 scripts/bounty_board.py --event-file "$GITHUB_EVENT_PATH" --apply

环境变量（一律不硬编码；令牌只在此读）：
    BOUNTY_GH_TOKEN / GITHUB_TOKEN / GH_TOKEN   令牌（按序回落）
    GITHUB_REPOSITORY                           仓库坐标 owner/repo
    GITHUB_EVENT_NAME                           事件名（缺省按 payload 形态推断）
    BOUNTY_MAX_CONCURRENT / BOUNTY_CLAIM_HOURS / BOUNTY_MAX_ROUNDS / BOUNTY_MAINTAINERS

账本收口（workflow 只持 `issues: write`＋`pull-requests: read`，**无 contents: write**，
故不能自己提交账本——真模式把本批事件写成 JSONL artifact，由维护者本地并入）：

    python -X utf8 scripts/bounty_board.py --ledger-append <events.jsonl>
    python -X utf8 scripts/bounty_board.py --board-out docs/bounty/board.md

退出码：0 = 正常（含「本例无动作」）；1 = 用法错误（未给任何动作）；2 = 环境错误
（真模式缺令牌／仓库坐标／网络失败——fail-closed，绝不静默当作成功）。离线模式恒不触网。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

# ================================================================ 常量面（口径单点）

#: 入选标记（维护者打）——设计稿 §二。
LABEL_GATE = "bounty"
#: 态标签（人眼视图）；`bounty:expired` 在 MVP **不驻留**（超时直接回板 `open`，
#: 只把 `expire` 事件与评论留在痕里）——见 README「超时回板」。
STATE_LABELS = ("bounty:open", "bounty:claimed", "bounty:delivered",
                "bounty:verified", "bounty:settled", "bounty:expired",
                "bounty:disputed")
#: 难度标签 → 结算分（设计稿 §五「建议值，待裁」——改口径只改本表）。
DIFFICULTY_SCORES = {"difficulty:easy": 1, "difficulty:medium": 3,
                     "difficulty:hard": 6, "difficulty:expert": 10}
#: 无难度标签时的兜底分（照 easy 记，并在事件理由里写明）。
SCORE_DEFAULT = 1
#: 负分（设计稿 §五）：虚假交付 / 超时未交付。
SCORE_FAKE_DELIVERY = -5
SCORE_TIMEOUT = -1

#: 命令面（只认「行首第一个词」）。
COMMANDS = ("/claim", "/deliver", "/withdraw", "/dispute", "/verify", "/settle")
#: 可认领态（设计稿 §三：`open`/`expired`——expired = 超时回板前一刻的可认领窗口）。
CLAIMABLE_STATES = ("open", "expired")
#: 可交付态（`delivered` 可再交付 = 返工轮）。
DELIVERABLE_STATES = ("claimed", "delivered")
#: 可主动释放态。
WITHDRAWABLE_STATES = ("claimed", "delivered")
#: 机器可读标记：`<!-- bounty:v1 {...} -->`（JSON 内不会出现 `-->`）。
MARKER_RE = re.compile(r"<!--\s*bounty:v1\s+(\{.*?\})\s*-->", re.DOTALL)
#: 交付物里的链接判据（http/https）。
_URL_RE = re.compile(r"https?://[^\s<>()\[\]`\"']+")
#: 证据块判据：围栏代码块（``` 或 ~~~，行首可有空白）。
_FENCE_RE = re.compile(r"^\s*(?:`{3,}|~{3,})", re.M)
#: 交付链接指向本仓 PR 的形态：`/pull/<n>`。
_PULL_RE = re.compile(r"(?:^|/)pull/(\d+)(?:$|[/?#])")

#: 账本事件的字段 schema（同时写进 `docs/bounty/ledger.json` 的 `_schema`，单一真源）。
LEDGER_SCHEMA = {
    "说明": "灵枢悬赏板 · 声誉账本（append-only 事件流；由 scripts/bounty_board.py "
            "追加，禁手改既有行）",
    "字段": {
        "id": "事件指纹（内容 sha1 前 12 位）——同事件重复投递按 id 幂等去重",
        "ts": "事件时间（UTC ISO8601）",
        "issue": "issue 号",
        "action": "claim|deliver|withdraw|dispute|verify|settle|expire|reject",
        "actor": "触发者登录名（超时回板记 schedule）",
        "from": "迁移前态（bounty:* 的裸值）",
        "to": "迁移后态",
        "holder": "事件涉及的持有者（现场上下文；超时回板记**原**持有者以记负分）",
        "difficulty": "difficulty:* 的裸值（计分依据）",
        "delta": "本事件声誉分增量（结算为正；超时/虚假交付为负）",
        "reason": "判定理由（拒绝原因 / 验收理由）",
        "pr": "交付链接指向本仓 PR 时的元数据（号/标题/态/head sha）",
    },
    "计分": {"easy": 1, "medium": 3, "hard": 6, "expert": 10,
             "虚假交付": SCORE_FAKE_DELIVERY, "超时未交付": SCORE_TIMEOUT},
    "生成": "python -X utf8 scripts/bounty_board.py --ledger-append <events.jsonl>",
}


class BoardError(Exception):
    """环境/输入级错误（fail-closed：调用方据此退 2，绝不静默当作成功）。"""


# ================================================================ 时间与配置


# 生效条件：text 为可被 datetime.fromisoformat 解析的 ISO8601 串（容许结尾 Z、容许无时区）时返回 UTC 时区的 datetime；不可解析时抛 ValueError（调用方决定退码）。
def parse_ts(text) -> datetime:
    """ISO8601（容许结尾 `Z`）→ 带 UTC 时区的 datetime。"""
    s = str(text).strip()
    if s.endswith(("Z", "z")):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# 生效条件：dt 为任意带/不带时区的 datetime 时返回其 UTC 形态的 `YYYY-MM-DDTHH:MM:SSZ` 串；不带时区者按 UTC 解释。
def fmt_ts(dt: datetime) -> str:
    """datetime → UTC ISO8601（`…Z`）——账本与标记的唯一时间写法。"""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# 生效条件：now 为带时区 datetime、text 为可解析 ISO8601 串时返回 now - parse_ts(text) 的 timedelta；text 不可解析时抛 ValueError。
def _age(now: datetime, text: str) -> timedelta:
    return now - parse_ts(text)


@dataclass(frozen=True)
class Config:
    """运行口径（代码里只有缺省值；实际取值由环境变量覆盖，见 `from_env`）。"""

    max_concurrent: int = 2      # 同一认领人并发认领上限（设计稿 §七 待裁项 #3 → 缺省 2）
    claim_hours: int = 72        # 认领期（设计稿 §二：72h 超时回板）
    max_rounds: int = 3          # 交付轮次上限（设计稿 §四 防作弊：最多 3 轮修改）
    maintainers: tuple = ("FuRongJun-1999",)   # 维护者名单（/verify /settle 的授权面）

    # 生效条件：env 为 None 时读 os.environ，否则读传入映射；返回按 BOUNTY_* 覆盖缺省后的 Config；数值项解析失败时抛 BoardError（不静默回落缺省）。
    @classmethod
    def from_env(cls, env=None) -> "Config":
        env = os.environ if env is None else env
        kw = {}
        for key, name in (("BOUNTY_MAX_CONCURRENT", "max_concurrent"),
                          ("BOUNTY_CLAIM_HOURS", "claim_hours"),
                          ("BOUNTY_MAX_ROUNDS", "max_rounds")):
            raw = (env.get(key) or "").strip()
            if raw:
                try:
                    kw[name] = int(raw)
                except ValueError:
                    raise BoardError(f"环境变量 {key}={raw!r} 不是整数")
        raw_m = (env.get("BOUNTY_MAINTAINERS") or "").strip()
        if raw_m:
            kw["maintainers"] = tuple(x.strip() for x in raw_m.split(",") if x.strip())
        return cls(**kw)


# ================================================================ 命令解析


# 生效条件：body 为任意评论文本时返回 (命令, 载荷)——取**首个非空行**，行首（允许前导空白）第一个词必须恰是 COMMANDS 之一；正文中间/引用块（`>` 开头）里出现的命令返回 (None, "")（只认「命令在最前、行首」）。
def parse_command(body):
    """只认「命令在最前、行首」的评论 → (命令, 载荷)；非命令返回 (None, "")。"""
    for line in (body or "").splitlines():
        if not line.strip():
            continue
        head = line.lstrip()
        word, _sep, rest = head.partition(" ")
        if "\t" in word:                       # 制表符分隔同空格口径
            word, _sep, rest = head.partition("\t")
        if word in COMMANDS:
            return word, rest.strip()
        return None, ""
    return None, ""


# ================================================================ 状态与裁决的数据面


@dataclass(frozen=True)
class IssueState:
    """一条悬赏的当前状态（从「标签视图 ＋ 评论流」重建；权威面 = 最新标记）。"""

    number: int
    labels: tuple = ()
    has_bounty: bool = False
    state: str = "open"
    holder: str | None = None
    due_at: str | None = None
    rounds: int = 0
    seq: int = 0
    difficulty: str = ""
    author: str | None = None


@dataclass(frozen=True)
class Decision:
    """一条命令的一次裁决（纯数据：通过/拒绝、迁移目标、评论体、账本事件）。"""

    ok: bool
    action: str = ""
    reason: str = ""
    issue: int = 0
    from_state: str = ""
    to_state: str = ""
    holder: str | None = None
    due_at: str | None = None
    rounds: int = 0
    labels_add: tuple = ()
    labels_remove: tuple = ()
    comment: str = ""
    delta: int = 0
    event: dict = field(default_factory=dict)


def _seq(rec: dict) -> int:
    try:
        return int(rec.get("seq") or 0)
    except (TypeError, ValueError):
        return 0


# 生效条件：comments 为评论正文可迭代（含 None/坏 JSON）时返回「seq 最大且带 state 字段」的标记字典；无任何合格标记时返回 None（坏 JSON 一律跳过，不抛）。
def latest_marker(comments):
    """评论流 → 最新的状态标记（权威记录）；无则 None。"""
    best = None
    for body in comments or ():
        for m in MARKER_RE.finditer(body or ""):
            try:
                rec = json.loads(m.group(1))
            except ValueError:
                continue
            if isinstance(rec, dict) and rec.get("state"):
                if best is None or _seq(rec) >= _seq(best):
                    best = rec
    return best


# 生效条件：number 为 issue 号、labels 为标签可迭代、comments 为评论正文可迭代时返回重建的 IssueState——态取「最新标记 > 态标签 > （有 bounty 标签则 open）」；author 给定时写入。
def build_state(number, labels, comments, author=None) -> IssueState:
    """「标签视图 ＋ 评论流」→ IssueState（态优先级：标记 > 标签 > 默认 open）。"""
    labels = tuple(labels or ())
    marker = latest_marker(comments) or {}
    label_state = next((lbl.split(":", 1)[1] for lbl in labels if lbl in STATE_LABELS), "")
    has_bounty = LABEL_GATE in labels
    state = marker.get("state") or label_state or ("open" if has_bounty else "")
    difficulty = next((lbl for lbl in labels if lbl.startswith("difficulty:")), "")
    return IssueState(
        number=int(number), labels=labels, has_bounty=has_bounty, state=state or "",
        holder=marker.get("holder") or None, due_at=marker.get("due_at") or None,
        rounds=int(marker.get("rounds") or 0), seq=_seq(marker),
        difficulty=difficulty, author=author)


# 生效条件：labels 为标签可迭代、target 为裸态名时返回 (要加的标签, 要删的标签)——删光其余态标签，加目标态标签；target 为空串时只删不加。
def label_patch(labels, target):
    """态迁移的标签补丁：(add, remove)。"""
    cur = tuple(labels or ())
    add = (f"bounty:{target}",) if target else ()
    remove = tuple(lbl for lbl in cur if lbl in STATE_LABELS and lbl != f"bounty:{target}")
    return add, remove


# ================================================================ 校验面（每条判据 = 一个可定点变异的函数）


# 生效条件：st 的标签面与态面给定时返回 (是否通过, 理由)——`bounty` 标签必须在 ∧ 态 ∈ {open, expired}；否则拒绝并把当前态写进理由。
def _check_claimable(st: IssueState):
    """R3：入选标记 `bounty` 在 ∧ 态为 open/expired（设计稿 §三 `/claim` 校验）。"""
    if not st.has_bounty:
        return False, ("本 issue 没有 `bounty` 标签——它不是悬赏任务"
                       "（维护者打 `bounty` 标签后即可认领）")
    if st.state not in CLAIMABLE_STATES:
        return False, (f"当前态 `bounty:{st.state}` 不可认领"
                       f"（仅 {'/'.join(CLAIMABLE_STATES)} 可认领）")
    return True, ""


# 生效条件：st 带 holder 时返回 (False, 理由含持有者与到期)，holder 为空/None 时返回 (True, "")。
def _check_no_holder(st: IssueState):
    """R1：无当前持有者（有 ⇒ 拒——防两人同时上锁）。"""
    if st.holder:
        return False, (f"已有持有者 @{st.holder}"
                       f"（到期 {st.due_at or '未知'}）——先等其交付或超时回板")
    return True, ""


# 生效条件：active 为 actor 当前并发认领数（整数）、cap 为上界整数时返回 (active < cap, 理由)；达到/超过上界即拒。
def _check_concurrency(active, actor, cap):
    """R2：同一认领人并发认领数 ≤ 上限（默认 2）。"""
    if active >= cap:
        return False, (f"@{actor} 当前并发认领 {active} 个，已达上限 {cap}"
                       f"（交付或释放其中任一后可再认领）")
    return True, ""


# 生效条件：st 的 holder 与 actor 给定时返回 (st.holder == actor, 理由)——非持有者一律拒；holder 为空时理由写作「（无）」。
def _check_is_holder(st: IssueState, actor):
    """R4：仅认领人可交付/释放。"""
    if st.holder != actor:
        return False, ("仅当前持有者可执行该命令"
                       f"（当前持有者：@{st.holder or '（无）'}）")
    return True, ""


# 生效条件：payload 为命令载荷串、body 为整条评论正文时返回 (是否合格, 理由)——载荷含 http(s) 链接 或 评论含围栏代码块（证据块）即合格；两者皆无即拒。
def _check_payload(payload, body):
    """R5：交付必须带「链接」或「证据块」（分析/复现类走证据块）。"""
    if _URL_RE.search(payload or ""):
        return True, ""
    if _FENCE_RE.search(body or ""):
        return True, ""
    return False, ("交付必须带链接（`http(s)://…`，如 PR 地址）或证据块"
                   "（围栏内贴可复跑读数）")


# ================================================================ 评论模板（固定形态：人读在前、机器标记在末行）


def _marker(payload: dict) -> str:
    """状态标记行（HTML 注释内 JSON；权威记录的唯一写法）。"""
    body = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))
    return f"<!-- bounty:v1 {body} -->"


def _comment(title, bullets, marker_payload) -> str:
    """固定模板：标题 + 要点列表 + 末行机器标记。"""
    lines = [f"**[悬赏板] {title}**", ""]
    lines += [f"- {b}" for b in bullets]
    lines += ["", "---", "规则与验收口径见 `docs/bounty/README.md`。",
              _marker(marker_payload)]
    return "\n".join(lines)


# 生效条件：action 为命令名、actor 为登录名、reason 为拒绝理由、now 为带时区 datetime、code 为机器可读拒绝码时返回固定模板评论（末行标记 action=reject，**不带 state** 以免污染权威记录）。
def reject_comment(action, actor, reason, now, code) -> str:
    bullets = [f"命令：`{action}`", f"原因：{reason}"]
    marker = {"action": "reject", "cmd": action, "actor": actor, "code": code,
              "ts": fmt_ts(now)}
    return _comment("本次操作未通过", bullets, marker)


# ================================================================ 纯逻辑裁决面

#: 通过态迁移的评论标题（`action` 去斜杠后查表）。
_TITLES = {"claim": "认领成功", "deliver": "交付已登记", "withdraw": "已释放认领",
           "dispute": "已进入争议", "verify": "验收裁决", "settle": "已结算",
           "expire": "超时回板"}


def _decide(st, action, reason, now, actor, code) -> Decision:
    """拒绝裁决的统一构造（态不变；事件 action=reject 留痕，delta=0）。"""
    ev = {"ts": fmt_ts(now), "issue": st.number, "action": "reject", "actor": actor,
          "from": st.state, "to": st.state, "holder": st.holder,
          "difficulty": st.difficulty.split(":", 1)[-1] if st.difficulty else "",
          "delta": 0, "reason": f"{code}：{reason}"}
    ev["id"] = event_id(ev)
    return Decision(ok=False, action=action, reason=reason, issue=st.number,
                    from_state=st.state, to_state=st.state, holder=st.holder,
                    due_at=st.due_at, rounds=st.rounds,
                    comment=reject_comment(action, actor, reason, now, code),
                    delta=0, event=ev)


# 生效条件：st 与迁移参数给定时返回通过裁决——态迁移、标签补丁、固定模板评论、账本事件（delta 按参数；*_holder 缺省同 holder，超时回板时二者分叉：标记不带持有者、事件记原持有者以便记负分）。
def _accept(st, action, now, actor, to_state, holder, due_at, rounds, reason,
            bullets, marker_extra=None, delta=0, event_holder=None,
            event_actor=None) -> Decision:
    """通过裁决的统一构造。"""
    add, remove = label_patch(st.labels, to_state)
    marker = {"state": to_state, "holder": holder, "due_at": due_at,
              "rounds": rounds, "seq": st.seq + 1, "ts": fmt_ts(now),
              "actor": actor, "action": action.lstrip("/")}
    ev = {"ts": fmt_ts(now), "issue": st.number, "action": action.lstrip("/"),
          "actor": event_actor or actor, "from": st.state, "to": to_state,
          "holder": st.holder if event_holder is None else event_holder,
          "difficulty": st.difficulty.split(":", 1)[-1] if st.difficulty else "",
          "delta": delta, "reason": reason}
    if marker_extra:
        ev.update({k: v for k, v in marker_extra.items() if k == "pr"})
    ev["id"] = event_id(ev)
    return Decision(ok=True, action=action, reason=reason, issue=st.number,
                    from_state=st.state, to_state=to_state, holder=holder,
                    due_at=due_at, rounds=rounds, labels_add=add,
                    labels_remove=remove,
                    comment=_comment(_TITLES.get(action.lstrip("/"), "状态已更新"),
                                     bullets, marker),
                    delta=delta, event=ev)


# 生效条件：st 为 IssueState、cmd 为 COMMANDS 之一、actor 为非空登录名、now 为带时区 datetime、cfg 为 Config、active_claims 为 actor 当前并发认领数（不含本 issue）时返回一个 Decision——**纯逻辑，零 IO/零网络**；is_maintainer 只影响 /verify 与 /settle；pr_meta 只写进账本事件。
def handle_command(st: IssueState, cmd, payload, body, actor, now, cfg: Config,
                   is_maintainer=False, active_claims=0, pr_meta=None) -> Decision:
    """一条命令 → 一次裁决（纯函数：可直接喂夹具单测）。"""
    if cmd == "/claim":
        return _do_claim(st, actor, now, cfg, active_claims)
    if cmd == "/deliver":
        return _do_deliver(st, payload, body, actor, now, cfg, pr_meta)
    if cmd == "/withdraw":
        return _do_withdraw(st, actor, now, cfg)
    if cmd == "/dispute":
        return _do_dispute(st, payload, actor, now, is_maintainer)
    if cmd == "/verify":
        return _do_verify(st, payload, actor, now, cfg, is_maintainer)
    if cmd == "/settle":
        return _do_settle(st, actor, now, cfg, is_maintainer)
    return _decide(st, cmd or "", f"未知命令 {cmd!r}", now, actor, "unknown_command")


# 生效条件：st 为 IssueState、actor/now/cfg 齐全、active_claims 为整数时返回裁决——三项校验（无持有者 / 标签与态 / 并发上限）依序短路；全过则上锁并记到期时间（now + claim_hours）。持有者判据在态判据**之前**：标记是权威记录，标签可能落后（现场形态：态标签仍为 open 而标记里已有持有者）。
def _do_claim(st, actor, now, cfg, active_claims):
    ok_holder, why_holder = _check_no_holder(st)
    if not ok_holder:
        return _decide(st, "/claim", why_holder, now, actor, "holder_exists")
    ok_label, why_label = _check_claimable(st)
    if not ok_label:
        return _decide(st, "/claim", why_label, now, actor, "state_not_claimable")
    ok_conc, why_conc = _check_concurrency(active_claims, actor, cfg.max_concurrent)
    if not ok_conc:
        return _decide(st, "/claim", why_conc, now, actor, "concurrency_limit")
    due = fmt_ts(now + timedelta(hours=cfg.claim_hours))
    bullets = [f"持有者：@{actor}",
               f"到期：{due}（逾期自动回板 `bounty:open` 并记 {SCORE_TIMEOUT} 分）",
               "交付：评论 `/deliver <PR 链接或证据块>`；放弃：`/withdraw`"]
    return _accept(st, "/claim", now, actor, "claimed", actor, due, 0,
                   f"@{actor} 认领，锁至 {due}", bullets)


# 生效条件：st 为 IssueState、payload 为命令载荷、body 为整条评论正文、actor/now/cfg 齐全时返回裁决——校验依序「仅本人可交付 → 态可交付 → 带链接或证据块 → 轮次 ≤ max_rounds」；全过则转 delivered 并记 pr_meta（若交付链接指向本仓 PR）。
def _do_deliver(st, payload, body, actor, now, cfg, pr_meta):
    ok_holder, why_holder = _check_is_holder(st, actor)
    if not ok_holder:
        return _decide(st, "/deliver", why_holder, now, actor, "not_holder")
    if st.state not in DELIVERABLE_STATES:
        return _decide(st, "/deliver",
                       f"当前态 `bounty:{st.state}` 不可交付（先 `/claim`）",
                       now, actor, "state_not_deliverable")
    ok_pay, why_pay = _check_payload(payload, body)
    if not ok_pay:
        return _decide(st, "/deliver", why_pay, now, actor, "payload_missing")
    rounds = st.rounds + 1
    if rounds > cfg.max_rounds:
        return _decide(st, "/deliver",
                       f"交付轮次已达上限 {cfg.max_rounds}（防作弊：最多 "
                       f"{cfg.max_rounds} 轮修改）——请转 `/dispute` 交我方仲裁",
                       now, actor, "rounds_exceeded")
    shown = (payload or "").strip()
    show = shown if len(shown) <= 200 else shown[:200] + "…"
    bullets = [f"交付者：@{actor}", f"第 {rounds}/{cfg.max_rounds} 轮",
               f"交付物：{show or '（见评论正文的证据块）'}",
               "验收四闸：① CI 全绿 ② 复现读数 ③ 守卫＋定点变异 ④ 维护者人审"]
    return _accept(st, "/deliver", now, actor, "delivered", actor, st.due_at,
                   rounds, f"@{actor} 第 {rounds} 轮交付（{show[:80]}）", bullets,
                   marker_extra={"pr": pr_meta} if pr_meta else None)


# 生效条件：st/actor/now/cfg 齐全时返回裁决——非持有者拒；态不在 withdrawable_states 拒；通过则回板 open（清持有者与到期；声誉不变 delta=0）。
def _do_withdraw(st, actor, now, cfg):
    ok_holder, why_holder = _check_is_holder(st, actor)
    if not ok_holder:
        return _decide(st, "/withdraw", why_holder, now, actor, "not_holder")
    if st.state not in WITHDRAWABLE_STATES:
        return _decide(st, "/withdraw", f"当前态 `bounty:{st.state}` 无需释放",
                       now, actor, "state_not_withdrawable")
    bullets = [f"释放者：@{actor}", "任务已回板 `bounty:open`，任何人可重新认领",
               "主动释放**不影响声誉**"]
    return _accept(st, "/withdraw", now, actor, "open", None, None, st.rounds,
                   f"@{actor} 主动释放认领，任务回板", bullets)


# 生效条件：st/payload/actor/now/is_maintainer 齐全时返回裁决——必带理由（空理由拒）；仅「双方」可提起（认领者 / 维护者 / issue 作者）；通过则转 disputed（delta=0，留痕不扣本金）。
def _do_dispute(st, payload, actor, now, is_maintainer):
    if not (payload or "").strip():
        return _decide(st, "/dispute", "争议必须带理由（`/dispute <理由>`）",
                       now, actor, "dispute_reason_missing")
    party = (actor == st.holder) or is_maintainer or (bool(st.author)
                                                      and actor == st.author)
    if not party:
        return _decide(st, "/dispute",
                       f"仅当事人可提起争议（持有者 @{st.holder or '（无）'} / "
                       f"issue 作者 @{st.author or '（未知）'} / 维护者）",
                       now, actor, "not_party")
    reason = payload.strip()
    bullets = [f"提起者：@{actor}", f"理由：{reason}",
               "已转 `bounty:disputed`：由我方仲裁并留痕（记录在案，不扣本金）"]
    return _accept(st, "/dispute", now, actor, "disputed", st.holder, st.due_at,
                   st.rounds, f"@{actor} 提起争议：{reason}", bullets)


# 生效条件：st/payload/actor/now/cfg 齐全且 is_maintainer 为真时返回裁决——非维护者拒；态非 delivered 拒；判定词取载荷首词（pass/fail，缺省 pass），fail 记 −5 并回 claimed 返工、pass 转 verified。
def _do_verify(st, payload, actor, now, cfg, is_maintainer):
    if not is_maintainer:
        return _decide(st, "/verify", "仅维护者可裁决验收（人审闸）", now, actor,
                       "not_maintainer")
    if st.state != "delivered":
        return _decide(st, "/verify", f"当前态 `bounty:{st.state}` 不在待验收面",
                       now, actor, "state_not_verifiable")
    text = (payload or "").strip()
    head, _sep, rest = text.partition(" ")
    if head.lower() in ("pass", "fail"):
        verdict, reason = head.lower(), rest.strip()
    else:
        verdict, reason = "pass", text
    if verdict == "fail":
        bullets = [f"裁决者：@{actor}",
                   f"判定：**不通过**（记 {SCORE_FAKE_DELIVERY} 分）",
                   f"理由：{reason or '（未写理由）'}",
                   f"已退回 `bounty:claimed` 返工（轮次照计，上限 {cfg.max_rounds} "
                   "轮）；如属不可调和争议请 `/dispute`"]
        return _accept(st, "/verify", now, actor, "claimed", st.holder, st.due_at,
                       st.rounds, f"验收不通过：{reason or '（未写理由）'}", bullets,
                       delta=SCORE_FAKE_DELIVERY)
    bullets = [f"裁决者：@{actor}", "判定：**通过**（四闸逐道可查）",
               f"理由：{reason or '（未写理由）'}",
               "待结算：维护者 `/settle` 按 `difficulty:*` 记入账本"]
    return _accept(st, "/verify", now, actor, "verified", st.holder, st.due_at,
                   st.rounds, f"验收通过：{reason or '（未写理由）'}", bullets)


# 生效条件：st/actor/now/cfg 齐全且 is_maintainer 为真时返回裁决——非维护者拒；态非 verified 拒；通过则转 settled 并按 difficulty:* 记正分（缺标签时按 SCORE_DEFAULT 记并在理由里写明）。
def _do_settle(st, actor, now, cfg, is_maintainer):
    if not is_maintainer:
        return _decide(st, "/settle", "仅维护者可结算", now, actor, "not_maintainer")
    if st.state != "verified":
        return _decide(st, "/settle",
                       f"当前态 `bounty:{st.state}` 不可结算（须先过验收 "
                       "`bounty:verified`）", now, actor, "state_not_settleable")
    score = DIFFICULTY_SCORES.get(st.difficulty, SCORE_DEFAULT)
    diff = st.difficulty.split(":", 1)[-1] if st.difficulty else ""
    note = f"{diff}" if diff else f"无 difficulty 标签（按 {SCORE_DEFAULT} 分记）"
    bullets = [f"结算者：@{actor}",
               f"入账：@{st.holder or '（无）'} **+{score} 分**（{note}）",
               "账本 append-only：`docs/bounty/ledger.json`"]
    return _accept(st, "/settle", now, actor, "settled", st.holder, st.due_at,
                   st.rounds, f"结算 {score} 分（{note}）", bullets, delta=score)


# 生效条件：states 为 IssueState 可迭代、now 为带时区 datetime、cfg 为 Config 时返回 Decision 列表——逐条判「态为 claimed ∧ 有 due_at ∧ now ≥ due ⇒ 超时回板 open（记 SCORE_TIMEOUT，负分归属原持有者）」；未超期/无到期/非 claimed 一律不动。
def sweep(states, now: datetime, cfg: Config):
    """超时回收（`schedule` 每 6 小时调用）：`bounty:claimed` 且到期未交付 → 回板。"""
    out = []
    for st in states:
        if st.state != "claimed" or not st.due_at:
            continue
        try:
            due = parse_ts(st.due_at)
        except ValueError:
            continue
        if now < due:
            continue
        held = f"@{st.holder}" if st.holder else "（无持有者）"
        try:
            waited = _age(now, st.due_at)
        except ValueError:
            waited = "未知"
        bullets = [f"原持有者：{held}",
                   f"到期时间：{st.due_at}（已超期 {waited}）",
                   f"处置：自动回板 `bounty:open`（记 {SCORE_TIMEOUT} 分，"
                   "任何人可重新认领）"]
        out.append(_accept(st, "/expire", now, "schedule", "open", None, None, 0,
                           f"{held} 认领超时未交付，自动回板", bullets,
                           delta=SCORE_TIMEOUT, event_holder=st.holder))
    return out


# ================================================================ 账本与荣誉榜（纯函数）


# 生效条件：ev 为事件字典时返回稳定 id（`evt_` + 剔除 id 后内容 sha1 前 12 位——同内容重复投递即同 id）。
def event_id(ev: dict) -> str:
    """事件指纹（内容寻址；同一事件重复投递按 id 幂等去重）。"""
    body = {k: v for k, v in (ev or {}).items() if k != "id"}
    blob = json.dumps(body, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))
    return "evt_" + hashlib.sha1(blob.encode("utf-8")).hexdigest()[:12]


# 生效条件：events 为既有事件列表、new 为待追加事件可迭代时返回「既有 + 未见过的新事件」——append-only，且按 id 幂等（重复投递不重复入账）；既有行永不改写。
def append_events(events, new):
    """append-only 追加（按 id 幂等）。"""
    seen = {e.get("id") for e in events or []}
    added = [e for e in (new or []) if e.get("id") and e.get("id") not in seen]
    return list(events or []) + added


# 生效条件：events 为账本事件列表时返回 {登录名: 视图字典}——视图含 score（分）、settled/delivered/timeouts/disputes/rejects 计数与 first/last 活动时间；归属取 holder（缺省 actor），delta 缺失按 0。
def score_board(events):
    """账本 → 声誉视图（每人头一行；计分只认 delta 与 action）。"""
    view = {}
    for ev in events or []:
        # 归属：一般取 holder（干活的人）；**被拒命令**取 actor（尝试者——
        # 刷单/重复认领检测的口径）；超时回板的 holder 记原持有者（见 sweep）。
        if ev.get("action") == "reject":
            who = ev.get("actor") or ""
        else:
            who = ev.get("holder") or ev.get("actor") or ""
        if not who:
            continue
        row = view.setdefault(who, {"login": who, "score": 0, "settled": 0,
                                    "delivered": 0, "timeouts": 0,
                                    "disputes": 0, "rejects": 0,
                                    "first": "", "last": ""})
        row["score"] += int(ev.get("delta") or 0)
        act = ev.get("action")
        if act == "settle":
            row["settled"] += 1
        elif act == "deliver":
            row["delivered"] += 1
        elif act == "expire":
            row["timeouts"] += 1
        elif act == "dispute":
            row["disputes"] += 1
        elif act == "reject":
            row["rejects"] += 1
        ts = ev.get("ts") or ""
        if ts and (not row["first"] or ts < row["first"]):
            row["first"] = ts
        if ts and ts > row["last"]:
            row["last"] = ts
    return view


# 生效条件：events 为账本事件列表时返回荣誉榜 markdown 全文（确定性：同一账本 ⇒ 逐字节同一文本）；空账本返回「暂无入账」形态；不写生成时刻（防生成件无谓翻滚）。
def render_board(events) -> str:
    """账本 → 荣誉榜 markdown（`docs/bounty/board.md` 的生成器）。"""
    events = list(events or [])
    rows = sorted(score_board(events).values(),
                  key=lambda r: (-r["score"], r["login"]))
    until = max((e.get("ts") or "" for e in events), default="")
    lines = [
        "# 灵枢悬赏板 · 荣誉榜",
        "",
        "> 本页由 `scripts/bounty_board.py --board-out docs/bounty/board.md` 从",
        "> `docs/bounty/ledger.json`（append-only 事件流）**机械生成**——勿手改，"
        "手改会在下一次生成时被覆盖。",
        f"> 账本事件数：{len(events)}" + (f" ｜ 统计截至：{until}" if until else ""),
        "",
        "计分口径（设计稿 §五 建议值，待设计者裁定）：easy 1 / medium 3 / hard 6 / "
        "expert 10；虚假交付 −5；超时未交付 −1；主动释放与争议提起不扣分"
        "（争议败诉记录在案、不扣本金）。",
        "",
    ]
    if not rows:
        lines += ["## 当前榜面", "",
                  "（暂无入账事件——账本为空；第一条 `/settle` 落账后本表自动出现。）",
                  ""]
    else:
        lines += ["## 当前榜面", "",
                  "| 贡献者 | 声誉分 | 已结算 | 已交付 | 超时回板 | 争议 | 被拒命令 "
                  "| 首次活动 | 最近活动 |",
                  "|---|---|---|---|---|---|---|---|---|"]
        for r in rows:
            lines.append(
                f"| @{r['login']} | {r['score']} | {r['settled']} | "
                f"{r['delivered']} | {r['timeouts']} | {r['disputes']} | "
                f"{r['rejects']} | {r['first'] or '—'} | {r['last'] or '—'} |")
        lines.append("")
    lines += ["## 账本", "",
              "事件流真源：`docs/bounty/ledger.json`（append-only、id 幂等；"
              "写入命令见 `docs/bounty/README.md`「账本收口」）。",
              "",
              "---",
              "",
              "本页与账本由 `scripts/bounty_board.py` 生成；"
              "状态机与命令面见 `docs/bounty/README.md`。",
              ""]
    return "\n".join(lines)


# 生效条件：path 为账本 JSON 路径时返回 events 列表（文件不存在 → []；坏 JSON/结构不符抛 BoardError）。
def load_ledger(path):
    """读账本 JSON → events 列表。"""
    if not os.path.isfile(path):
        return []
    try:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
    except ValueError as exc:
        raise BoardError(f"账本不是合法 JSON：{path}（{exc}）")
    if isinstance(doc, list):
        return doc
    if isinstance(doc, dict) and isinstance(doc.get("events"), list):
        return doc["events"]
    raise BoardError(f"账本结构不符（须为 {{'events': [...]}}）：{path}")


# 生效条件：path 与 events 给定时写账本（带 LEDGER_SCHEMA 外壳、events 保持 append 序）并返回路径；父目录按需创建。
def write_ledger(path, events):
    """写账本（带 `_schema` 的固定外壳；events 保持 append 序）。"""
    doc = {"_schema": LEDGER_SCHEMA, "events": list(events or [])}
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    return path


# 生效条件：path 为 JSONL 路径时返回事件列表（空行跳过；坏行抛 BoardError，不静默吞）。
def read_jsonl(path):
    """读 JSONL（每行一个事件）→ 事件列表。"""
    out = []
    with open(path, encoding="utf-8") as fh:
        for i, line in enumerate(fh, 1):
            if not line.strip():
                continue
            try:
                out.append(json.loads(line))
            except ValueError as exc:
                raise BoardError(f"JSONL 第 {i} 行不是合法 JSON：{exc}")
    return out


# 生效条件：path 与 events 给定时写 JSONL（一行一事件）并返回路径；父目录按需创建。
def write_jsonl(path, events):
    """事件列表 → JSONL（供 workflow 落 artifact）。"""
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        for ev in events or []:
            fh.write(json.dumps(ev, ensure_ascii=False, sort_keys=True) + "\n")
    return path


# ================================================================ 薄 GitHub 客户端（标准库 urllib；令牌只从环境变量读）


# 生效条件：env 为 None 时读 os.environ，否则读传入映射；按 BOUNTY_GH_TOKEN → GITHUB_TOKEN → GH_TOKEN 序返回首个非空令牌，全缺返回空串。
def token_from_env(env=None):
    """令牌按序回落读取；全缺返回空串（真模式随后 fail-closed 退 2）。"""
    env = os.environ if env is None else env
    for key in ("BOUNTY_GH_TOKEN", "GITHUB_TOKEN", "GH_TOKEN"):
        val = (env.get(key) or "").strip()
        if val:
            return val
    return ""


class GitHubClient:
    """极薄 REST 客户端：只做悬赏板需要的读写。

    安全面：令牌进 header（`Authorization: Bearer …`），**绝不落盘、绝不进日志、
    绝不进命令行参数**；`User-Agent` 固定；错误一律抛 `BoardError`（fail-closed）。
    """

    # 生效条件：repo 为 "owner/name" 形态、token 可为空串（只读公共面时）时构造客户端；api_base 缺省 GitHub 公网端点，timeout 为秒。
    def __init__(self, repo, token, api_base="https://api.github.com", timeout=30):
        if not repo or "/" not in repo:
            raise BoardError(f"仓库坐标不合法：{repo!r}（须为 owner/repo）")
        self.repo = repo
        self.token = token or ""
        self.api_base = api_base.rstrip("/")
        self.timeout = timeout
        #: 标签体系是否已就绪（首次要改标签时幂等建一次；同进程只建一次）。
        self.labels_ready = False

    # 生效条件：method/path 给定时发起一次 REST 调用并返回解析后的 JSON（空体 → {}）；HTTP 状态在 allow 内返回 None；其余 HTTP/网络错误抛 BoardError。
    def _req(self, method, path, payload=None, allow=()):
        data = None
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(self.api_base + path, data=data, method=method)
        req.add_header("Accept", "application/vnd.github+json")
        req.add_header("X-GitHub-Api-Version", "2022-11-28")
        req.add_header("User-Agent", "lingshu-bounty-board")
        if data is not None:
            req.add_header("Content-Type", "application/json")
        if self.token:
            req.add_header("Authorization", "Bearer " + self.token)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            if exc.code in allow:
                return None
            detail = ""
            try:
                detail = exc.read().decode("utf-8", "replace")[:300]
            except Exception:                                       # noqa: BLE001
                pass
            raise BoardError(f"GitHub API {method} {path} → HTTP {exc.code}：{detail}")
        except OSError as exc:
            raise BoardError(f"GitHub API {method} {path} → 网络错误：{exc}")
        return json.loads(raw) if raw.strip() else {}

    # 生效条件：n 为 issue 号时返回 issue 字典（标签/作者/标题等）。
    def issue(self, n):
        return self._req("GET", f"/repos/{self.repo}/issues/{int(n)}")

    # 生效条件：n 为 issue 号时返回该 issue 全部评论正文列表（per_page=100 分页，最多 10 页 = 1000 条；达上限即截断，调用方按「评论面未全量」处置）。
    def comments(self, n):
        out = []
        for page in range(1, 11):
            chunk = self._req(
                "GET", f"/repos/{self.repo}/issues/{int(n)}/comments"
                       f"?per_page=100&page={page}")
            if not chunk:
                break
            out += [c.get("body") or "" for c in chunk]
            if len(chunk) < 100:
                break
        return out

    # 生效条件：label 为标签名、limit 为页数上界时返回「打开且带该标签」的 issue 字典列表（分页抓取；PR 不计入）。
    def issues_with_label(self, label, limit=10):
        out = []
        for page in range(1, int(limit) + 1):
            chunk = self._req(
                "GET", f"/repos/{self.repo}/issues?state=open"
                       f"&labels={urllib.parse.quote(label, safe='')}"
                       f"&per_page=100&page={page}")
            if not chunk:
                break
            out += [it for it in chunk if "pull_request" not in it]
            if len(chunk) < 100:
                break
        return out

    # 生效条件：n 为 PR 号时返回 PR 元数据字典；该号不是 PR（HTTP 404）时返回 None（调用方按「非本仓 PR」处置）。
    def pull(self, n):
        return self._req("GET", f"/repos/{self.repo}/pulls/{int(n)}", allow=(404,))

    # 生效条件：n 与 body 给定时发一条 issue 评论，返回评论字典。
    def comment(self, n, body):
        return self._req("POST", f"/repos/{self.repo}/issues/{int(n)}/comments",
                         {"body": body})

    # 生效条件：n、add（标签名可迭代）、remove（同上）给定时加/删标签（空列表即跳过该侧）；返回 None。
    def set_labels(self, n, add, remove):
        add = [x for x in (add or ()) if x]
        if add:
            self._req("POST", f"/repos/{self.repo}/issues/{int(n)}/labels",
                      {"labels": add})
        for name in (remove or ()):
            if name:
                self._req("DELETE", f"/repos/{self.repo}/issues/{int(n)}/labels/"
                                    + urllib.parse.quote(name, safe=""),
                          allow=(404,))
        return None

    # 生效条件：specs 为 (名称, 颜色, 描述) 可迭代时逐个幂等创建标签（已存在 = HTTP 422 静默跳过）；返回「实际新建」的名称列表。
    def ensure_labels(self, specs):
        created = []
        for name, color, desc in specs:
            res = self._req("POST", f"/repos/{self.repo}/labels",
                            {"name": name, "color": color, "description": desc},
                            allow=(422,))
            if res:
                created.append(name)
        return created

    # 生效条件：actor 为非空登录名、exclude 为当前 issue 号（可为 None）时返回「actor 打开且态为 claimed/delivered 的 issue 数」（并发上限判据的唯一取数面）；抓取面受 limit 页约束。
    def count_active_claims(self, actor, exclude=None, limit=10):
        n = 0
        for label in ("bounty:claimed", "bounty:delivered"):
            for it in self.issues_with_label(label, limit=limit):
                if exclude is not None and int(it.get("number", -1)) == int(exclude):
                    continue
                labels = [l.get("name") for l in it.get("labels") or []]
                st = build_state(it.get("number"), labels,
                                 self.comments(it.get("number")),
                                 author=(it.get("user") or {}).get("login"))
                if st.holder == actor and st.state in ("claimed", "delivered"):
                    n += 1
        return n


#: 标签体系（设计稿 §二；`ensure_labels` 的输入——幂等创建用）。
LABEL_SPECS = (
    (LABEL_GATE, "0e8a16", "悬赏板：入选任务标记（维护者打）"),
    ("bounty:open", "c2e0c6", "悬赏板：开放认领"),
    ("bounty:claimed", "fbca04", "悬赏板：已被认领（72h 未交付自动回板）"),
    ("bounty:delivered", "1d76db", "悬赏板：已交付，待验收（四闸）"),
    ("bounty:verified", "5319e7", "悬赏板：验收通过，待结算"),
    ("bounty:settled", "0e8a16", "悬赏板：已结算（计入声誉账本）"),
    ("bounty:expired", "d4c5f9", "悬赏板：超时回板（MVP 不驻留，仅内部态）"),
    ("bounty:disputed", "b60205", "悬赏板：争议中（我方仲裁留痕）"),
    ("difficulty:easy", "ededed", "悬赏难度：easy（1 分）"),
    ("difficulty:medium", "ededed", "悬赏难度：medium（3 分）"),
    ("difficulty:hard", "ededed", "悬赏难度：hard（6 分）"),
    ("difficulty:expert", "ededed", "悬赏难度：expert（10 分）"),
)


# 生效条件：payload 为评论文本、repo 为 "owner/repo" 时返回本仓 PR 号（int）或 None——只认指向本仓 `…/<repo>/pull/<n>` 的链接（非本仓链接一律 None，不越权解读）。
def extract_pr_number(payload, repo):
    """交付载荷 → 本仓 PR 号（非本仓链接返回 None）。"""
    if not payload or not repo or "/" not in repo:
        return None
    owner, name = repo.split("/", 1)
    for m in re.finditer(r"https?://[^\s<>()\[\]`\"']+", payload):
        seg = m.group(0).split("github.com/", 1)
        if len(seg) != 2:
            continue
        if not seg[1].lower().startswith(f"{owner.lower()}/{name.lower()}/"):
            continue
        pm = _PULL_RE.search(seg[1])
        if pm:
            return int(pm.group(1))
    return None


# ================================================================ 离线状态镜像（--state：本地文件即世界）

STORE_NOTE = ("离线状态镜像（仅本地演练/测试用）——公开面真源是 issue 线程本身"
              "（标签视图 ＋ 评论里的 bounty:v1 标记）；本文件用同一套纯逻辑跑迁移，"
              "无需真网络。")


# 生效条件：path 为状态镜像路径时返回镜像字典（不存在 → 新空镜像；不隐式写盘）；坏 JSON 抛 BoardError。
def load_store(path):
    """读离线状态镜像。"""
    if not os.path.isfile(path):
        return {"_note": STORE_NOTE, "issues": {}, "ledger": []}
    try:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
    except ValueError as exc:
        raise BoardError(f"状态文件不是合法 JSON：{path}（{exc}）")
    doc.setdefault("issues", {})
    doc.setdefault("ledger", [])
    return doc


# 生效条件：path 与 store 给定时写离线状态镜像（UTF-8 + LF）；父目录按需创建。
def save_store(path, store):
    """写离线状态镜像。"""
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(store, fh, ensure_ascii=False, indent=2, sort_keys=True)
        fh.write("\n")
    return path


# 生效条件：store 为状态镜像、number 为 issue 号时返回其 IssueState（缺记录返回 None）。
def store_state(store, number):
    rec = (store.get("issues") or {}).get(str(int(number)))
    if not rec:
        return None
    return build_state(number, rec.get("labels") or (), rec.get("markers") or (),
                       author=rec.get("author"))


# 生效条件：store 与 number 给定时在镜像里建/重置该 issue（标签缺 `bounty` 自动补首位）。
def store_open_issue(store, number, labels, author=None):
    labels = list(labels or [])
    if LABEL_GATE not in labels:
        labels.insert(0, LABEL_GATE)
    store.setdefault("issues", {})[str(int(number))] = {
        "number": int(number), "labels": labels, "author": author,
        "markers": [], "history": []}
    return store


# 生效条件：store 中 actor 处于 claimed/delivered 态的 issue 数（不含 exclude）——离线模式下并发上限的唯一取数面。
def store_active_claims(store, actor, exclude=None):
    n = 0
    for key, rec in (store.get("issues") or {}).items():
        if exclude is not None and str(int(exclude)) == str(key):
            continue
        st = build_state(key, rec.get("labels") or (), rec.get("markers") or (),
                         author=rec.get("author"))
        if st.holder == actor and st.state in ("claimed", "delivered"):
            n += 1
    return n


# 生效条件：store/decision 给定时把裁决落进镜像——通过：切态标签、追加标记与历史；拒绝：只追历史；两者都按 id 幂等追加账本事件（返回是否真的入账）；issue 不在镜像时返回 False。
def store_apply(store, dec: Decision):
    rec = (store.get("issues") or {}).get(str(dec.issue))
    if rec is None:
        return False
    rec.setdefault("markers", [])
    rec.setdefault("history", [])
    if dec.ok:
        for lbl in dec.labels_remove:
            if lbl in rec["labels"]:
                rec["labels"].remove(lbl)
        for lbl in dec.labels_add:
            if lbl not in rec["labels"]:
                rec["labels"].append(lbl)
        rec["markers"].append(
            "<!-- bounty:v1 " + json.dumps(
                {"state": dec.to_state, "holder": dec.holder,
                 "due_at": dec.due_at, "rounds": dec.rounds,
                 "seq": len(rec["markers"]) + 1, "ts": dec.event.get("ts"),
                 "actor": dec.event.get("actor"),
                 "action": dec.event.get("action")},
                ensure_ascii=False, sort_keys=True,
                separators=(",", ":")) + " -->")
    rec["history"].append({"ts": dec.event.get("ts"), "action": dec.action,
                           "actor": dec.event.get("actor"), "ok": dec.ok,
                           "from": dec.from_state, "to": dec.to_state,
                           "reason": dec.reason})
    before = len(store.get("ledger") or [])
    store["ledger"] = append_events(store.get("ledger") or [], [dec.event])
    return len(store["ledger"]) > before


# ================================================================ 离线演练（--dry-run：一键演完整生命周期）


# 生效条件：out 为可调用打印面时跑完固定脚本的完整生命周期（场景 A 全链 / B 超时回板 / C 并发上限与释放 / D 虚假交付与争议）并打印过程、账本与荣誉榜；固定假时钟、不触网、不写盘；恒返回 0。
def run_rehearsal(out=print) -> int:
    """离线全生命周期演练（固定假时钟；不触网、不写盘）→ 退出码 0。"""
    cfg = Config()
    store = {"_note": STORE_NOTE, "issues": {}, "ledger": []}
    cover = []
    clock = [0]
    t0 = parse_ts("2026-10-09T00:00:00Z")

    def hh(hour):
        return fmt_ts(t0 + timedelta(hours=hour))

    def publish(issue, difficulty, author="FuRongJun-1999"):
        store_open_issue(store, issue, ["bounty", "bounty:open", difficulty],
                         author=author)
        out(f"[{clock[0]:>2}] {hh(clock[0])}  #{issue}  维护者发布："
            f"`bounty` + `bounty:open` + `{difficulty}`（author @{author}）")

    def step(issue, actor, body, maintainer=False, show=True):
        cmd, payload = parse_command(body)
        now = parse_ts(hh(clock[0]))
        st = store_state(store, issue)
        dec = handle_command(st, cmd, payload, body, actor, now, cfg,
                             is_maintainer=maintainer,
                             active_claims=store_active_claims(store, actor, issue))
        store_apply(store, dec)
        if dec.ok:
            cover.append(dec.to_state)
        trans = (f"{dec.from_state} → {dec.to_state}" if dec.ok
                 else f"{dec.from_state}（不变）")
        out(f"[{clock[0]:>2}] {hh(clock[0])}  #{issue}  @{actor} `{cmd}` → "
            f"{'通过' if dec.ok else '拒绝'} ｜ {trans} ｜ {dec.reason}")
        if show:
            out(_indent("评论（原文）：" + dec.comment, "       "))
        return dec

    out("=== 灵枢悬赏板 · 离线演练（无网络 / 不写盘；固定假时钟）===")
    out(f"缺省口径：并发上限 {cfg.max_concurrent} ／ 认领期 {cfg.claim_hours}h ／ "
        f"轮次上限 {cfg.max_rounds} ／ 维护者 {','.join(cfg.maintainers)}")
    out("")
    out("---- 场景 A：完整生命周期（claim→deliver→verify→settle）＋ 拒绝面 ----")
    publish(101, "difficulty:medium")
    clock[0] = 1
    step(101, "alice", "/claim")
    clock[0] = 2
    step(101, "bob", "/claim")
    clock[0] = 3
    step(101, "alice", "/deliver 见附件")
    clock[0] = 4
    step(101, "alice",
         "/deliver https://github.com/FuRongJun-1999/dsh-memory/pull/77")
    clock[0] = 5
    step(101, "bob", "/verify pass 我看行")
    clock[0] = 6
    step(101, "FuRongJun-1999", "/verify pass CI 全绿＋复现读数＋守卫变异自证",
         maintainer=True)
    clock[0] = 7
    step(101, "FuRongJun-1999", "/settle", maintainer=True)

    out("")
    out("---- 场景 B：超时回板（认领 72h 未交付）----")
    clock[0] = 8
    publish(102, "difficulty:easy")
    clock[0] = 9
    step(102, "carol", "/claim", show=False)
    clock[0] = 9 + 72
    decs = sweep([store_state(store, 102)], parse_ts(hh(clock[0])), cfg)
    for dec in decs:
        store_apply(store, dec)
        cover.append(dec.to_state)
        out(f"[{clock[0]:>2}] {hh(clock[0])}  #102  schedule 每 6h 扫描 → 回板 ｜ "
            f"{dec.from_state} → {dec.to_state} ｜ {dec.reason}"
            f"（记 {dec.delta} 分）")
        out(_indent("评论（原文）：" + dec.comment, "       "))

    out("")
    out("---- 场景 C：并发上限（≤2）与主动释放 ----")
    for num in (103, 104):
        clock[0] += 1
        publish(num, "difficulty:hard")
        step(num, "dave", "/claim", show=False)
    clock[0] += 1
    publish(105, "difficulty:hard")
    step(105, "dave", "/claim")
    clock[0] += 1
    publish(106, "difficulty:medium")
    step(106, "erin", "/claim", show=False)
    clock[0] += 1
    step(106, "erin", "/withdraw")

    out("")
    out("---- 场景 D：验收不通过（虚假交付 −5）/ 返工 / 争议 ----")
    clock[0] += 1
    publish(107, "difficulty:medium")
    step(107, "frank", "/claim", show=False)
    clock[0] += 1
    step(107, "frank",
         "/deliver https://github.com/FuRongJun-1999/dsh-memory/pull/88", show=False)
    clock[0] += 1
    step(107, "FuRongJun-1999", "/verify fail 读数不可复跑，属虚假交付",
         maintainer=True)
    clock[0] += 1
    step(107, "frank",
         "/deliver 复现读数（证据块）：\n```\n7 passed in 0.42s\n```", show=False)
    clock[0] += 1
    step(107, "frank", "/dispute 我对第三条判据有异议，请仲裁")

    events = store["ledger"]
    out("")
    out(f"---- 账本（{len(events)} 条事件；append-only、id 幂等）----")
    for ev in events:
        delta = f"{ev.get('delta'):+d}" if ev.get("delta") else " 0"
        out(f"  {ev.get('ts')}  #{ev.get('issue')}  {ev.get('action'):<8} "
            f"@{ev.get('actor'):<16} {ev.get('from')} → {ev.get('to'):<9} "
            f"delta={delta}  id={ev.get('id')}")
    out("")
    out("---- 荣誉榜（由账本机械生成）----")
    out(_indent(render_board(events).rstrip()))
    out("")
    out("---- 覆盖态清单 ----")
    out("  " + " → ".join(dict.fromkeys(
        [c for c in cover if c] + ["expired（超时回板前的可认领窗口，MVP 不驻留）"])))
    out("")
    out("[OK] 离线演练走完：认领 → 交付 → 验收 → 结算 ＋ 超时回板 ＋ 拒绝面"
        "（重复认领 / 无据交付 / 非维护者裁决 / 并发上限）")
    return 0


# 生效条件：text 为任意字符串、prefix 为行前缀时返回逐行加前缀的串（空串 → 空串）。
def _indent(text, prefix="      "):
    return "\n".join(prefix + ln for ln in (text or "").splitlines())


# ================================================================ 真模式：issue_comment / schedule 路由


# 生效条件：payload 为事件体字典时返回事件名（含 comment+issue → issue_comment；含 schedule → schedule）；形态不符返回空串（调用方按「无动作」处置）。
def infer_event_name(payload):
    """按 payload 形态推断事件名（本地演练/手工触发可不设 GITHUB_EVENT_NAME）。"""
    if isinstance(payload, dict):
        if "comment" in payload and "issue" in payload:
            return "issue_comment"
        if "schedule" in payload:
            return "schedule"
    return ""


# 生效条件：override 非空 或 env 的 GITHUB_REPOSITORY 非空时返回 owner/repo 串；两者皆空抛 BoardError（fail-closed）。
def repo_from_env(env=None, override=""):
    env = os.environ if env is None else env
    repo = (override or env.get("GITHUB_REPOSITORY") or "").strip()
    if not repo:
        raise BoardError("缺仓库坐标：设 GITHUB_REPOSITORY=owner/repo 或传 --repo")
    return repo


# 生效条件：client 为 GitHubClient、states 与 decisions 等长、apply 为布尔时，把每对 (issue, 裁决) 打到远端（apply=False 只打印计划）；返回本批事件列表。
def apply_live(client, states, decisions, apply=False, out=print):
    """把裁决打到远端（`apply=False` 只打印计划）；返回本批事件列表。"""
    events = []
    for st, dec in zip(states, decisions):
        events.append(dec.event)
        out(f"{'APPLY ' if apply else 'PLAN  '}#{st.number} {dec.from_state} → "
            f"{dec.to_state} ｜ {dec.reason}")
        if apply:
            if not client.labels_ready:
                # 首跑幂等建标签体系（同 repro-bot 的 `gh label create --force` 形态）：
                # 缺标签时加标签会被 GitHub 拒（422），故在第一次真写前补一次。
                made = client.ensure_labels(LABEL_SPECS)
                client.labels_ready = True
                if made:
                    out(f"（首跑建标签 {len(made)} 个：{', '.join(made)}）")
            client.set_labels(st.number, dec.labels_add, dec.labels_remove)
            client.comment(st.number, dec.comment)
    return events


# 生效条件：payload 为 issue_comment 事件体、cfg 为 Config、client 为 GitHubClient 时处理一条评论命令并返回 (退出码, 事件列表)——PR 评论/自带标记的评论/非命令评论一律无动作；维护者面 = 名单 ∨ author_association ∈ {OWNER,MEMBER,COLLABORATOR}。
def handle_issue_comment(payload, cfg: Config, client, apply=False, out=print):
    issue = payload.get("issue") or {}
    comment = payload.get("comment") or {}
    if issue.get("pull_request"):
        out("PR 评论不在悬赏板面内 → 无动作")
        return 0, []
    body = comment.get("body") or ""
    if MARKER_RE.search(body):
        out("本评论是悬赏板自身留言（含 bounty:v1 标记）→ 无动作")
        return 0, []
    cmd, cmd_payload = parse_command(body)
    if not cmd:
        out("非命令评论（命令须在行首最前）→ 无动作")
        return 0, []
    number = int(issue.get("number") or 0)
    actor = ((comment.get("user") or {}).get("login") or "").strip()
    if not number or not actor:
        raise BoardError("事件体缺 issue.number 或 comment.user.login")
    labels = [l.get("name") for l in issue.get("labels") or []]
    st = build_state(number, labels, client.comments(number),
                     author=(issue.get("user") or {}).get("login"))
    assoc = (comment.get("author_association") or "").upper()
    is_maint = (actor in cfg.maintainers
                or assoc in ("OWNER", "MEMBER", "COLLABORATOR"))
    pr_meta = None
    if cmd == "/deliver":
        prn = extract_pr_number(cmd_payload, client.repo)
        if prn:
            pr = client.pull(prn)
            if pr:
                pr_meta = {"number": prn, "title": (pr.get("title") or "")[:120],
                           "state": pr.get("state") or "",
                           "head_sha": ((pr.get("head") or {}).get("sha") or "")[:12]}
    active = client.count_active_claims(actor, exclude=number)
    dec = handle_command(st, cmd, cmd_payload, body, actor,
                         datetime.now(timezone.utc), cfg, is_maintainer=is_maint,
                         active_claims=active, pr_meta=pr_meta)
    out(f"命令 `{cmd}` · 触发者 @{actor} · 维护者={is_maint} · 并发认领={active} · "
        f"当前态 bounty:{st.state or '（无）'}")
    events = apply_live(client, [st], [dec], apply=apply, out=out)
    return 0, events


# 生效条件：cfg 为 Config、client 为 GitHubClient、now 为带时区 datetime（缺省取当前）时扫描 `bounty:claimed` 全部 issue 并对其超期者回板，返回 (退出码, 事件列表)。
def handle_sweep_live(cfg: Config, client, apply=False, out=print, now=None):
    now = now or datetime.now(timezone.utc)
    items = client.issues_with_label("bounty:claimed")
    states = []
    for it in items:
        labels = [l.get("name") for l in it.get("labels") or []]
        states.append(build_state(it.get("number"), labels,
                                  client.comments(it.get("number")),
                                  author=(it.get("user") or {}).get("login")))
    due = sweep(states, now, cfg)
    if not due:
        out(f"扫描 `bounty:claimed` {len(states)} 条：无超期 → 无动作")
        return 0, []
    out(f"扫描 `bounty:claimed` {len(states)} 条：超期 {len(due)} 条 → 回板")
    by_number = {st.number: st for st in states}
    events = apply_live(client, [by_number[d.issue] for d in due], due,
                        apply=apply, out=out)
    return 0, events


# ================================================================ 命令行入口


# 生效条件：argv 为命令行参数列表（None = sys.argv[1:]）时执行对应动作并返回退出码——0 正常 / 1 未给动作（打印帮助）/ 2 环境或输入错误（BoardError）。
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="灵枢悬赏板 · 状态机与 GitHub 路由（MVP；离线可完整演练）")
    ap.add_argument("--dry-run", action="store_true",
                    help="离线演练：一键跑完整生命周期（不触网、不写盘）")
    ap.add_argument("--state", default="", help="离线状态镜像 JSON（本地演练）")
    ap.add_argument("--open-issue", type=int, default=0,
                    help="在离线镜像里建 issue（配 --labels/--author）")
    ap.add_argument("--labels", default="", help="逗号分隔标签（配 --open-issue）")
    ap.add_argument("--author", default="", help="issue 作者（配 --open-issue）")
    ap.add_argument("--issue", type=int, default=0,
                    help="离线命令的目标 issue 号（缺省 = 镜像里最大号）")
    ap.add_argument("--command", default="", help="离线执行一条命令，如 '/claim'")
    ap.add_argument("--as", dest="as_user", default="", help="命令执行者登录名")
    ap.add_argument("--at", default="", help="假时钟 ISO8601（缺省 = 现在）")
    ap.add_argument("--maintainer", action="store_true",
                    help="离线模式下把 --as 视作维护者（/verify /settle）")
    ap.add_argument("--sweep", action="store_true",
                    help="离线超时回收（配 --state；真模式见 --sweep-live）")
    ap.add_argument("--sweep-live", action="store_true",
                    help="真模式超时回收（schedule / 手工触发）")
    ap.add_argument("--event-file", default="", help="真模式：事件 payload JSON 路径")
    ap.add_argument("--repo", default="", help="仓库坐标（缺省读 GITHUB_REPOSITORY）")
    ap.add_argument("--apply", action="store_true",
                    help="真模式：真的写（缺省只打印计划，不写任何远端状态）")
    ap.add_argument("--ledger", default="docs/bounty/ledger.json",
                    help="账本 JSON 路径（--ledger-append / --board-out 用）")
    ap.add_argument("--ledger-append", default="",
                    help="把 JSONL 事件并入账本（本地收口；幂等）")
    ap.add_argument("--ledger-out", default="",
                    help="真模式：把本批事件写成 JSONL（供 workflow 落 artifact）")
    ap.add_argument("--board-out", default="",
                    help="从账本生成荣誉榜 markdown（写盘）")
    args = ap.parse_args(argv)

    try:
        cfg = Config.from_env()
        if args.dry_run:
            return run_rehearsal()

        if args.ledger_append:
            events = read_jsonl(args.ledger_append)
            merged = append_events(load_ledger(args.ledger), events)
            write_ledger(args.ledger, merged)
            print(f"账本并入：读入 {len(events)} 条 → 账本现 {len(merged)} 条 → "
                  f"{args.ledger}")
            return 0

        if args.board_out:
            events = load_ledger(args.ledger)
            text = render_board(events)
            parent = os.path.dirname(os.path.abspath(args.board_out))
            if parent:
                os.makedirs(parent, exist_ok=True)
            with open(args.board_out, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(text)
            print(f"荣誉榜已生成：{args.board_out}（账本 {len(events)} 条事件）")
            return 0

        if args.state:
            store = load_store(args.state)
            now = parse_ts(args.at) if args.at else datetime.now(timezone.utc)
            if args.open_issue:
                store_open_issue(
                    store, args.open_issue,
                    [x.strip() for x in args.labels.split(",") if x.strip()],
                    author=args.author or None)
                save_store(args.state, store)
                st = store_state(store, args.open_issue)
                print(f"已建 #{st.number}：labels={list(st.labels)} 态={st.state} "
                      f"（镜像已写 {args.state}）")
                return 0
            if args.command:
                if not args.as_user:
                    raise BoardError("离线命令模式须给 --as <登录名>")
                num = args.issue or max(
                    (int(k) for k in (store.get("issues") or {})), default=0)
                st = store_state(store, num)
                if st is None:
                    raise BoardError(f"镜像里没有 issue #{num}——先 --open-issue")
                cmd, payload = parse_command(args.command)
                if not cmd:
                    raise BoardError(f"不是命令（命令须在行首最前）：{args.command!r}")
                dec = handle_command(
                    st, cmd, payload, args.command, args.as_user, now, cfg,
                    is_maintainer=(args.maintainer or args.as_user in cfg.maintainers),
                    active_claims=store_active_claims(store, args.as_user, num))
                store_apply(store, dec)
                save_store(args.state, store)
                print(f"#{dec.issue} `{dec.action}` @{args.as_user} → "
                      f"{'通过' if dec.ok else '拒绝'} ｜ "
                      f"{dec.from_state} → {dec.to_state} ｜ {dec.reason}")
                print(_indent(dec.comment, "  "))
                return 0
            if args.sweep:
                states = [store_state(store, k)
                          for k in sorted(store.get("issues") or {}, key=int)]
                decs = sweep([s for s in states if s], now, cfg)
                for dec in decs:
                    store_apply(store, dec)
                save_store(args.state, store)
                print(f"离线扫描：{len(decs)} 条超期回板（镜像已写 {args.state}）")
                for dec in decs:
                    print(_indent(dec.comment, "  "))
                return 0
            for k in sorted(store.get("issues") or {}, key=int):
                st = store_state(store, k)
                print(f"#{st.number} 态={st.state:<10} "
                      f"持有者={st.holder or '—':<12} 到期={st.due_at or '—'} "
                      f"轮次={st.rounds} 标签={','.join(st.labels)}")
            print(f"（镜像账本 {len(store.get('ledger') or [])} 条事件）")
            return 0

        if args.event_file:
            try:
                with open(args.event_file, encoding="utf-8") as fh:
                    payload = json.load(fh)
            except (OSError, ValueError) as exc:
                raise BoardError(f"事件 payload 读取失败：{args.event_file}（{exc}）")
            name = ((os.environ.get("GITHUB_EVENT_NAME") or "").strip()
                    or infer_event_name(payload))
            repo = repo_from_env(override=args.repo)
            token = token_from_env()
            if not token:
                raise BoardError("真模式缺令牌：设 BOUNTY_GH_TOKEN（或 GITHUB_TOKEN）"
                                 "——令牌只从环境变量读，绝不硬编码")
            client = GitHubClient(repo, token)
            if name == "issue_comment":
                code, events = handle_issue_comment(payload, cfg, client,
                                                    apply=args.apply)
            elif name in ("schedule", "workflow_dispatch"):
                code, events = handle_sweep_live(cfg, client, apply=args.apply)
            else:
                print(f"未识别的事件（{name or '未知'}）→ 无动作")
                code, events = 0, []
            if args.ledger_out and events:
                write_jsonl(args.ledger_out, events)
                print(f"本批事件 {len(events)} 条 → {args.ledger_out}")
            return code

        if args.sweep_live:
            repo = repo_from_env(override=args.repo)
            token = token_from_env()
            if not token:
                raise BoardError("真模式缺令牌：设 BOUNTY_GH_TOKEN（或 GITHUB_TOKEN）")
            client = GitHubClient(repo, token)
            code, events = handle_sweep_live(cfg, client, apply=args.apply)
            if args.ledger_out and events:
                write_jsonl(args.ledger_out, events)
            return code

        ap.print_help()
        return 1
    except BoardError as exc:
        print(f"[错误] {exc}", file=sys.stderr)
        return 2
    except ValueError as exc:
        print(f"[错误] 输入不可解析：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
