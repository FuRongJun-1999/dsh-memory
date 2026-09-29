# -*- coding: utf-8 -*-
"""用户级注入件验收：`~/.zcode/AGENTS.md` 是否真的进了 ZCode 的注入面（2026-09-28 立）。

为什么要机械验收：该件是**指针**（指向 <repo>/zcode/AGENTS.md 的纪律本体），它的全部价值
都在「被注入」这一件事上；而「被注入」在本机无法靠肉眼确认——只能查 ZCode 自己写的
rollout 载荷（`~/.zcode/cli/rollout/model-io-*.jsonl`，每次请求一条，含 system 块与 messages）。

判据（关键在角色面，不在字面）：
  · 注入的上下文（system-reminder / 记忆索引 / 指令件）落**user 角色**消息；
    而模型自己的命令回显、思考、工具结果落 assistant / tool 角色。
    故「同一串出现在哪个角色」就是「注入 vs 自产」的判别器——否则会把 agent 自己读文件
    留下的痕迹误判成注入（本判据第一版就踩过这个坑）。
  · 对照组：`~/.zcode/cli/memories/.../MEMORY.md` 的索引头（已知会被注入）。若对照都没命中，
    说明本次取样或宿主行为变了，本工具的结论不可采信（只读判定须自证有效，不是照抄结论）。

三种退出：0 = 已注入（用户级件的独特行命中 user 角色）；1 = 未注入（对照命中、本件未命中）；
2 = 无法裁决（对照未命中，或会话起点早于该件 mtime——注入面若为会话起始一次性构建，
    本会话本就不该含它，此时须在新会话重跑）。**不打印任何哨兵正文**（只报行号与长度）。

生效条件：本机存在 `~/.zcode/cli/rollout/model-io-*.jsonl`（ZCode 端会话载荷）；缺目录/缺载荷
即退出 2 并说明。不适用于非 ZCode 端（DSH / CodeBuddy 的注入面各不相同，须各自立判据）。
运行：`python -X utf8 scripts/verify_injection_zcode_user.py [--session sess_xxx]`
"""
from __future__ import annotations

import argparse
import datetime
import glob
import io
import json
import os
import re
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

HOME = os.path.expanduser("~")
USER_FILE = os.path.join(HOME, ".zcode", "AGENTS.md")
ROLLOUT_DIR = os.path.join(HOME, ".zcode", "cli", "rollout")
# 对照件（已知进注入面）：记忆索引头 —— 它出现在 user 角色消息里是「注入生效」的既有事实
CTRL = os.path.join(HOME, ".zcode", "cli", "memories")
MIN_SENTINEL = 24  # 哨兵最短长度：太短会与普通文本偶然相撞


def sentinels(text: str) -> list[str]:
    """取该件的独特行做哨兵：长且含非 ASCII 的行优先（不易与别处文本偶然相同）。"""
    out = []
    for line in text.splitlines():
        s = line.strip()
        if len(s) < MIN_SENTINEL:
            continue
        if s.startswith("#") or s.startswith(">") or s.startswith("-"):
            out.append(s)
    out.sort(key=len, reverse=True)
    return out[:6]


def load_rollouts(session: str | None):
    pat = os.path.join(ROLLOUT_DIR, "model-io-%s.jsonl" % session) if session \
        else os.path.join(ROLLOUT_DIR, "model-io-*.jsonl")
    files = sorted(glob.glob(pat), key=os.path.getmtime)
    return files


def started_ms(d) -> int | None:
    """取该条载荷的会话起点（毫秒）。

    形态分派（2026-09-28 修缺陷）：本机宿主写的 `startedAt` 是 **ISO8601 字符串**
    （如 `'2026-09-28T14:45:46.169Z'`），而早期实现用 `re.search(r"\\d{10,}")` 从串里
    抠数字——ISO 串最长的连续数字只有 3–4 位 ⇒ 恒失配 ⇒ `earliest` 恒 None ⇒
    「不可裁」分支（`earliest < mtime`）**永不可达**：在「该件创建前就已开始的会话」里
    会给出假阴性「未注入」并打印一句从未核验过的断言。实测 416/416 条均为 ISO 形、
    旧逻辑命中 0 条（定点验证：ISO 样本→None，epoch 形样本→正确毫秒）。
    故：纯数字（epoch 秒/毫秒按位数判档）→ 直取；ISO8601（含 Z / 偏移 / 无时区）→
    `fromisoformat`（无时区者按本机时区解释）；其余 → None（不可裁，不猜）。
    """
    ts = d.get("startedAt")
    if isinstance(ts, bool):  # bool 是 int 子类，先挡掉
        return None
    if isinstance(ts, (int, float)):
        v = int(ts)
        return v * 1000 if v < 10_000_000_000 else v
    if not isinstance(ts, str):
        return None
    s = ts.strip()
    if not s:
        return None
    if re.fullmatch(r"\d{10,}", s):
        v = int(s)
        return v * 1000 if v < 10_000_000_000 else v
    try:
        dt = datetime.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.astimezone()
    return int(dt.timestamp() * 1000)


def main() -> int:
    ap = argparse.ArgumentParser(description="用户级注入件验收（~/.zcode/AGENTS.md）")
    ap.add_argument("--session", help="只查该会话（sess_xxx）；缺省查 rollout 目录全部")
    args = ap.parse_args()

    if not os.path.isfile(USER_FILE):
        print("退出 2：用户级件不存在：%s" % USER_FILE)
        return 2
    text = io.open(USER_FILE, encoding="utf-8", errors="replace").read()
    sents = sentinels(text)
    if not sents:
        print("退出 2：该件没有够长的独特行可作哨兵（长度阈值 %d）" % MIN_SENTINEL)
        return 2
    files = load_rollouts(args.session)
    if not files:
        print("退出 2：未找到 rollout 载荷（%s）——本机未跑过 ZCode 会话？" % ROLLOUT_DIR)
        return 2

    ctrl_ok = 0
    s_user = s_other = 0
    lines = 0
    per_file = []          # [(名字, 条目, 对照, user 命中, 其它命中, 起点 ms)]
    for path in files:
        f_ctrl = f_user = f_other = f_lines = 0
        f_start = None
        with io.open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                lines += 1
                f_lines += 1
                try:
                    d = json.loads(line)
                except Exception:  # noqa: BLE001
                    continue
                ts = started_ms(d)
                if ts and (f_start is None or ts < f_start):
                    f_start = ts
                for m in ((d.get("request") or {}).get("messages")) or []:
                    c = m.get("content")
                    txt = c if isinstance(c, str) else json.dumps(c, ensure_ascii=False)
                    is_user = m.get("role") == "user"
                    if "Memory Index" in txt and is_user:
                        ctrl_ok += 1
                        f_ctrl += 1
                    for s in sents:
                        if s in txt:
                            if is_user:
                                s_user += 1
                                f_user += 1
                            else:
                                s_other += 1
                                f_other += 1
                            break
        per_file.append((os.path.basename(path), f_lines, f_ctrl, f_user, f_other, f_start))

    mtime = int(os.path.getmtime(USER_FILE) * 1000)
    print("载荷文件 = %d 个，条目 = %d" % (len(files), lines))
    print("本件 mtime = %s（判据基准：起点晚于它才算可裁）"
          % time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(mtime / 1000)))
    print("对照（MEMORY 索引，user 角色命中）= %d  -> %s"
          % (ctrl_ok, "有效" if ctrl_ok else "取样失效"))
    print("本件哨兵：user 角色命中 = %d，其它角色 = %d（其它角色 = agent 自读自产，非注入）"
          % (s_user, s_other))
    print("--- 逐会话裁决（不可裁也逐条打印，避免「一个早会话压掉其余决定性证据」）---")
    verdicts = []
    for name, n, f_ctrl, f_user, f_other, f_start in per_file:
        if f_user:
            v = "已注入"
        elif not f_ctrl:
            v = "不可裁（该会话对照未命中，取样不成立）"
        elif f_start is None:
            v = "不可裁（该会话无可用起点时间）"
        elif f_start < mtime:
            v = "不可裁（起点早于本件 mtime——注入面若为会话起始一次性构建，本就不含它）"
        else:
            v = "未注入（起点晚于 mtime 且对照有效）"
        verdicts.append(v)
        print("  %-46s 条目=%-4d 对照=%-3d user=%-3d 其它=%-3d 起点=%s → %s"
              % (name[:46], n, f_ctrl, f_user, f_other,
                 time.strftime("%m-%d %H:%M:%S", time.localtime(f_start / 1000)) if f_start else "?",
                 v))

    if any(v == "已注入" for v in verdicts):
        print("退出 0：已注入（至少一个会话的 user 角色注入面含本件）")
        return 0
    if not ctrl_ok:
        print("退出 2：全部会话对照未命中——本次取样不成立，结论不可采信（勿据此判「未注入」）")
        return 2
    if any(v.startswith("未注入") for v in verdicts):
        print("退出 1：未注入——至少一个「起点晚于 mtime 且对照有效」的会话里零 user 命中")
        return 1
    print("退出 2：不可裁——无任何会话满足可裁条件（起点均早于本件 mtime）。请开新会话后重跑。")
    return 2


if __name__ == "__main__":
    sys.exit(main())
