"""日记看板：把心跳台账 + 我的日记，渲染成一页 Markdown（可 diff、可长期留档）。

用法：
    python -X utf8 scripts/intent_board.py --root <库根>            # 打到屏幕
    python -X utf8 scripts/intent_board.py --root <库根> --write    # 写 docs/日记看板.md

为什么不是网页（2026-11-19 与使用者商定）：网页要开、要维护、会失效；
Markdown 能进 Git、能 diff、能被检索，也谁都能读。

两条判据（都是踩出来的）：
  ① 「它在动」不等于「它在往前走」——看末 N 条的换题率，不看总条数。
  ② 心跳戳会撒谎——戳里的 pid 可能早已退出（残留戳），
     所以必须核对写者是否存活；昨天那个跑了 9 天的僵尸守护就是这样藏住的。
"""
import io
import json
import os
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

OUT_REL = os.path.join("docs", "日记看板.md")


def _root(argv):
    """库根：--root 显式优先，其次仓库统一解析（不在文件里写死本机路径）。"""
    if "--root" in argv:
        i = argv.index("--root")
        if i + 1 < len(argv):
            return argv[i + 1]
    try:
        from md_cg.datapath import mdcg_root
        return mdcg_root()
    except Exception:  # noqa: BLE001
        return os.environ.get("MDCG_ROOT") or "."


def _alive(pid):
    """写者是否还活着（跨平台，只读探测，不改任何状态）。"""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return None
    if pid <= 0:
        return None
    try:
        if os.name == "nt":
            import ctypes
            h = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED
            if not h:
                return False
            ctypes.windll.kernel32.CloseHandle(h)
            return True
        os.kill(pid, 0)
        return True
    except Exception:  # noqa: BLE001
        return False


def _read_jsonl(p):
    out = []
    try:
        with io.open(p, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except Exception:  # noqa: BLE001
                    continue
    except OSError:
        return []
    return out


def _stamp(root):
    for base in (os.path.join(root, "sustain"), os.path.expanduser("~/.mdcg/sustain")):
        p = os.path.join(base, "heartbeat.md_cg.stamp")
        if os.path.isfile(p):
            try:
                with io.open(p, encoding="utf-8") as f:
                    return json.load(f)
            except Exception:  # noqa: BLE001
                return None
    return None


def _rotation(records):
    """末尾连续同一节点多少次（>2 视为卡住）。"""
    if not records:
        return 0, None
    tail, last = 0, None
    for r in reversed(records):
        nid = r.get("node_id")
        if last is None:
            last, tail = nid, 1
        elif nid == last:
            tail += 1
        else:
            break
    return tail, last


def _diary(root, limit=40):
    """标签含「日记」的节点（读索引筛，再逐个取正文首行）。"""
    out = []
    try:
        from md_cg.mdcos import MdCGOS
        g = MdCGOS(root, actor="board")
        idx = (getattr(g, "index", {}) or {}).get("nodes") or {}
    except Exception:  # noqa: BLE001
        return out
    for nid, e in idx.items():
        if "日记" not in ((e or {}).get("tags") or []):
            continue
        content = ""
        try:
            content = str((g.get(nid) or {}).get("content") or "")
        except Exception:  # noqa: BLE001
            pass
        head = ""
        for line in content.splitlines():
            if line.strip():
                head = line.strip().lstrip("#").strip()[:56]
                break
        created = float((e or {}).get("created_at") or 0)
        out.append({"id": nid,
                    "date": time.strftime("%Y-%m-%d %H:%M", time.localtime(created)) if created else "—",
                    "head": head})
    out.sort(key=lambda x: x["date"], reverse=True)
    return out[:limit]


def render(root, now=None):
    now = now or time.time()
    records = _read_jsonl(os.path.join(root, "_intent.jsonl"))
    attempts = {}
    for r in records:
        nid = str(r.get("node_id") or "")
        if nid:
            attempts[nid] = attempts.get(nid, 0) + 1
    stamp = _stamp(root) or {}
    ts = float(stamp.get("ts") or 0)
    age = max(0.0, now - ts) if ts else None
    alive = _alive(stamp.get("pid")) if stamp else None
    tail, tail_node = _rotation(records)
    lines = []
    A = lines.append
    A("# 日记看板")
    A("")
    A("> 本页由 `scripts/intent_board.py` 生成，**勿手改**（下次生成会覆盖）。")
    A("> 生成于 %s" % time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now)))
    A("")
    A("## 一、心跳")
    A("")
    if stamp:
        done = stamp.get("last_tick_done") or {}
        err = stamp.get("last_tick_error")
        A("| 项 | 值 |")
        A("|---|---|")
        A("| pid | `%s` |" % stamp.get("pid"))
        A("| 写者存活 | %s |" % {True: "是", False: "**否（戳是残留！）**", None: "未知"}[alive])
        A("| 最近一跳 | %s |" % stamp.get("iso"))
        A("| 距今 | %s |" % ("—" if age is None else "%.0f 秒" % age))
        A("| 最近动作 | %s · %s |" % (done.get("name") or "—", "ok" if done.get("ok") else "无记录"))
        A("| 最近错误 | %s |" % ("无" if not err else "%s：%s" % (err.get("name"), err.get("error"))))
        A("")
        if alive is False:
            A("**⚠ 戳的写者已退出。** 读到的时间不代表循环在跑——先确认真正的服务进程有没有起来。")
            A("")
        if age is not None and age > 1200:
            A("**⚠ 心跳滞后超过 20 分钟**（正常节律 10 分钟）——先查循环是否还在跑。")
            A("")
    else:
        A("未找到心跳戳（`heartbeat.md_cg.stamp`）——循环可能没起来。")
        A("")
    A("## 二、它在动，还是在往前走")
    A("")
    A("| 指标 | 值 | 判读 |")
    A("|---|---|---|")
    A("| 台账条数 | %d | 起身次数 |" % len(records))
    A("| 不同节点数 | %d | 越多越在往前走 |" % len(attempts))
    A("| 末尾连续同一题 | %d 次 | %s |" % (tail, "⚠ 卡住了" if tail > 2 else "健康"))
    window = records[-10:]
    if len(window) >= 4:
        ratio = len(set(str(r.get("node_id") or "") for r in window)) / len(window)
        A("| 近期换题率（末 %d 条） | %.0f%% | %s |"
          % (len(window), ratio * 100,
             "低于 30%，多半在原地踩" if ratio < 0.3 else "正常（在换题）"))
    A("")
    if tail > 2 and tail_node:
        A("> 连续 %d 次都是 `%s`——这正是 2026-11-19 修掉的毛病（只比 last_access ⇒ 无限重复）。" % (tail, tail_node))
        A("> 若再次出现，先看 `md_cg/intent_tick.py` 的 `pick()` 是否按尝试次数轮转。")
        A("")
    A("## 三、待办推进")
    A("")
    A("| 节点 | 被捡起 |")
    A("|---|---|")
    for nid, n in sorted(attempts.items(), key=lambda kv: -kv[1])[:12]:
        A("| `%s` | %d 次 |" % (nid, n))
    A("")
    A("## 四、日记目录")
    A("")
    entries = _diary(root)
    if not entries:
        A("（还没有日记——心跳捡到题之后，需要有人在前面想一遍并写下来。）")
    else:
        A("| 日期 | 节点 | 第一行 |")
        A("|---|---|---|")
        for e in entries:
            A("| %s | `%s` | %s |" % (e["date"], e["id"], e["head"]))
    A("")
    A("---")
    A("")
    A("重新生成：`python -X utf8 scripts/intent_board.py --root <库根> --write`")
    return "\n".join(lines)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    root = _root(argv)
    text = render(root)
    if "--write" in argv:
        out = os.path.join(REPO, OUT_REL)
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with io.open(out, "w", encoding="utf-8", newline="\n") as f:
            f.write(text + "\n")
        print("已写入 %s" % OUT_REL)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())