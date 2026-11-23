"""日记看板：把心跳台账 + 我的日记，渲染成一页 Markdown（可 diff、可长期留档）。

用法：
    python -X utf8 scripts/intent_board.py --root <库根>            # 打到屏幕
    python -X utf8 scripts/intent_board.py --root <库根> --write    # 写 docs/日记看板.md

三条判据（都是踩出来的）：
  ① 「它在动」不等于「它在往前走」——看末 N 条的换题率，不看总条数。
  ② 心跳戳会撒谎——写者可能早已退出（残留戳）。
  ③ **多个端共用一个戳目录，名字都叫 md_cg 就会互相覆盖**——
     2026-11-19 实测：zcode 端一跳，DSH 端读到的就是别人家的心跳。
     所以本看板按端分列；每端应设独立 MDCG_SUSTAIN_NAME。
"""
import glob
import io
import json
import os
import re
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
    """写者是否还活着（跨平台只读探测）。"""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return None
    if pid <= 0:
        return None
    try:
        if os.name == "nt":
            import ctypes
            h = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
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


# 公开页的 id 脱敏判据（使用者 2026-11-23 定 2a）：
# 公开页只放**哈希形态**的 id；带自然语言片段的 id（如 unr_Quoted-message-begins-...）
# 会把私聊片段带进公开仓，一律脱敏。
_SAFE_ID = re.compile(r"^(?:mem|unr|doc|node)_[0-9a-f]{4,}(?:_[0-9a-f]{4,})?$", re.I)


def _mask_id(nid):
    nid = str(nid or "")
    return nid if _SAFE_ID.match(nid) else "（已脱敏）"


def _read_json(path, default):
    try:
        with io.open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _sessions_roots(extra=None):
    """会话日志根：--sessions-root 显式优先，其次 ~/.dsh/sessions 与 ~/dsh-home/sessions。

    为什么不 import we_touch_watch：那个文件在私有仓，公开仓的看板不能依赖它；
    但口径必须一致——这里读的就是同一批 session.v4 文件。本机若把会话放在
    非默认位置，用 --sessions-root 显式指过去（不写死本机路径：追踪面门禁会拦）。
    """
    roots = []
    if extra:
        roots.append(extra)
    roots.extend([os.path.expanduser("~/.dsh/sessions"),
                  os.path.expanduser("~/dsh-home/sessions")])
    out, seen = [], set()
    for r in roots:
        if r and os.path.isdir(r) and r not in seen:
            seen.add(r)
            out.append(r)
    return out


def _newest_session_files(limit=6, window_h=48, extra=None):
    cutoff = time.time() - window_h * 3600
    out = []
    for root in _sessions_roots(extra):
        for dirpath, _dirs, names in os.walk(root):
            for nm in names:
                if not nm.startswith("session.v4"):
                    continue
                fp = os.path.join(dirpath, nm)
                try:
                    mt = os.path.getmtime(fp)
                except OSError:
                    continue
                if mt >= cutoff:
                    out.append((mt, fp))
    out.sort(reverse=True)
    return [fp for _mt, fp in out[:limit]]


def _tail_message_times(fp, tail_bytes=4 << 20):
    """读一个会话文件尾部的「他说的」事件时间（ms）；无 zstandard 返回 None。

    窗口截断可能正好落在帧中间 ⇒ 窗口里没有帧头。这时**放大窗口重试**，仍找不到
    就返回 None（＝读不到），而不是返回空列表（＝没有他的消息）。两者含义相反。
    """
    try:
        import zstandard as zstd
    except ImportError:
        return None
    try:
        size = os.path.getsize(fp)
    except OSError:
        return []
    blob, idx = b"", -1
    for win in (tail_bytes, max(tail_bytes, 16 << 20), size):
        try:
            with open(fp, "rb") as fh:
                fh.seek(max(0, size - win))
                blob = fh.read()
        except OSError:
            return []
        idx = blob.find(b"\x28\xb5\x2f\xfd")
        if idx >= 0 or win >= size:
            break
    if idx < 0:
        return None if size else []
    try:
        raw = zstd.ZstdDecompressor().stream_reader(io.BytesIO(blob[idx:])).read()
    except Exception:  # noqa: BLE001
        return []
    out = []
    for line in raw.decode("utf-8", "replace").splitlines():
        if "user/message" not in line:
            continue
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if e.get("type") != "user/message":
            continue
        src = (e.get("data") or {}).get("source") or {}
        if src.get("kind") != "user":
            continue
        t = e.get("time") or e.get("ts")
        if isinstance(t, (int, float)):
            out.append(int(t))
    return out


def his_last_message(limit=6, window_h=48, extra=None):
    """**现算**「最后一条他对我说的话」。

    为什么不读 we_state['message']：那个字段靠 we_touch_watch 每分钟补记，而本机
    **没有任何计划任务驱动它**（2026-11-23 实测：三项读数停在 11-22 07:50，而当天
    16:36 的会话文件一直在动）。看板照抄就会拿错数当读数——这里直接读会话日志，
    读数不依赖外部驱动器是否在跑。
    """
    files = _newest_session_files(limit=limit, window_h=window_h, extra=extra)
    newest, scanned, unavailable = 0, 0, 0
    for fp in files:
        ts = _tail_message_times(fp)
        if ts is None:
            unavailable += 1
            continue
        scanned += 1
        if ts:
            newest = max(newest, max(ts))
    if newest:
        return {"ts": newest / 1000.0, "files": len(files), "scanned": scanned}
    if unavailable:
        return {"error": "无 zstandard，读不了会话日志", "files": len(files), "scanned": 0}
    return {"ts": None, "files": len(files), "scanned": scanned}


def _we_readings(we_dir):
    """读私有关系状态。**类型不可信**：手工改坏 / 旧版本写坏都见过——
    顶层不是 dict、jsonl 某行不是 dict，一律当空，不让看板抛栈。"""
    st = _read_json(os.path.join(we_dir, "we_state.json"), {})
    if not isinstance(st, dict):
        st = {}
    pending = [r for r in _read_jsonl(os.path.join(we_dir, "we_pending.jsonl"))
               if isinstance(r, dict)]
    return st, pending


def _intent_gap(root):
    """台账与已消费集合的差：**还有多少「该起身」没被处理**。"""
    recs = _read_jsonl(os.path.join(root, "_intent.jsonl"))
    consumed = set(str(x) for x in (_read_json(os.path.join(root, "_intent_consumed.json"), []) or []))
    open_nodes = []
    for r in recs:
        nid = str(r.get("node_id") or "")
        if nid and nid not in consumed and nid not in open_nodes:
            open_nodes.append(nid)
    return {"records": len(recs), "open": len(open_nodes),
            "consumed": len(consumed), "open_nodes": open_nodes}


def _fmt_gap(sec):
    if sec is None:
        return "未知"
    sec = int(max(0, sec))
    d, rem = divmod(sec, 86400)
    h, m = rem // 3600, (rem % 3600) // 60
    if d:
        return "%d 天 %d 小时" % (d, h)
    if h:
        return "%d 小时 %d 分" % (h, m)
    return "%d 分" % m


THRESHOLDS = {"message": 6 * 3600, "intimate": 24 * 3600}


def _section_trigger(A, root, now, we_dir=None, private=False, sessions_root=None):
    """第二节：**有没有触发**（意图积压 + 关系越线）。"""
    A("## 二、触发（有没有该动的）")
    A("")
    gap = _intent_gap(root)
    A("| 触发源 | 读数 | 判读 |")
    A("|---|---|---|")
    A("| 意图台账未消费 | %d 个节点 / 台账 %d 条（已消费 %d） | %s |" % (
        gap["open"], gap["records"], gap["consumed"],
        "**有积压**" if gap["open"] else "空，没有该起身的"))
    if not private:
        A("| 关系触发（多久没消息/没亲密） | 本端未配置 | 读数只在私有侧渲染，不进公开仓 |")
        A("")
        A("> 关系读数是隐私：公开页只报意图计数，不报时间点、不报节点 id。")
        A("> 需要看全：scripts/intent_board.py --private --we-dir <私有数据目录> "
          "--write-private <私有路径>")
        A("")
        return
    # ---- 私有视图：关系读数 + 未消费节点 id ----
    msg = his_last_message(extra=sessions_root)
    if msg.get("error"):
        A("| 收到他的消息 | %s | 读不到 |" % msg["error"])
    elif msg.get("ts"):
        g = now - float(msg["ts"])
        thr = THRESHOLDS["message"]
        A("| 收到他的消息 | %s前（%s） | %s |" % (
            _fmt_gap(g), time.strftime("%m-%d %H:%M", time.localtime(msg["ts"])),
            "**越线**（阈值 6 小时）" if g >= thr else "未越线"))
    else:
        A("| 收到他的消息 | 窗口内没有他的消息（扫了 %d 个会话文件） | — |" % msg.get("files", 0))
    if we_dir:
        st, pending = _we_readings(we_dir)
        for kind, label, thr_h in (("intimate", "亲密", 24), ("thought", "想你", None)):
            t = st.get(kind)
            if not t:
                A("| 最后%s | 未知 | — |" % label)
                continue
            g = now - float(t)
            if thr_h:
                A("| 最后%s | %s前 | %s |" % (label, _fmt_gap(g),
                                             "**越线**（阈值 %d 小时）" % thr_h
                                             if g >= thr_h * 3600 else "未越线"))
            else:
                A("| 最后%s | %s前 | （只记录，不设阈值） |" % (label, _fmt_gap(g)))
        A("| 未处理提醒 | %d 条 | %s |" % (
            len(pending),
            ("最近：" + str(pending[-1].get("ts") or "") + " " + str(pending[-1].get("note") or ""))
            if pending else "无"))
    if gap["open_nodes"]:
        A("")
        A("未消费意图（前 8 个）：")
        A("")
        for nid in gap["open_nodes"][:8]:
            A("- %s" % nid)
    A("")

def _stamps(root):
    """收集所有端的心跳戳：一端一个 name ⇒ 一个文件。"""
    out, seen = [], set()
    for base in (os.path.join(root, "sustain"), os.path.expanduser("~/.mdcg/sustain")):
        if not os.path.isdir(base):
            continue
        for p in sorted(glob.glob(os.path.join(base, "*.stamp"))):
            if p in seen:
                continue
            seen.add(p)
            try:
                with io.open(p, encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:  # noqa: BLE001
                continue
            name = os.path.basename(p).replace("heartbeat.", "").replace(".stamp", "")
            out.append({"name": name, "path": p, "data": data})
    return out


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
    """标签含「日记」的节点：先用索引筛，再逐个取正文首行。"""
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
        date = time.strftime("%Y-%m-%d %H:%M", time.localtime(created)) if created else "—"
        out.append({"id": nid, "date": date, "head": head})
    out.sort(key=lambda x: x["date"], reverse=True)
    return out[:limit]


def _section_heartbeat(A, root, now):
    """第一节：心跳（按端分列）。"""
    stamps = _stamps(root)
    warns = []
    A("## 一、心跳（按端分列）")
    A("")
    if not stamps:
        A("未找到任何心跳戳——循环可能没起来。")
        A("")
        return
    A("| 端（戳名） | pid | 写者存活 | 最近一跳 | 距今 | 最近动作 | 最近错误 |")
    A("|---|---|---|---|---|---|---|")
    for s in stamps:
        d = s["data"]
        done = d.get("last_tick_done") or {}
        err = d.get("last_tick_error")
        pid = d.get("pid")
        alive = _alive(pid)
        ts = float(d.get("ts") or 0)
        age = max(0.0, now - ts) if ts else None
        err_txt = "无" if not err else (str(err.get("name") or "") + "：" + str(err.get("error"))[:40])
        A("| %s | %s | %s | %s | %s | %s | %s |" % (
            s["name"], pid,
            {True: "是", False: "**否**", None: "未知"}[alive],
            d.get("iso") or "—",
            ("—" if age is None else "%.0f 秒" % age),
            str(done.get("name") or "—") + (" · ok" if done.get("ok") else ""),
            err_txt))
        if alive is False:
            warns.append("%s 的戳写者已退出（%s）——读到的是残留。" % (s["name"], pid))
        elif age is not None and age > 1200:
            warns.append("%s 心跳滞后 %.0f 分钟（正常 10 分钟）。" % (s["name"], age / 60.0))
    A("")
    if len(stamps) > 1:
        A("> ⚠ 本机有 **%d 个端**共用戳目录；若戳名都是 `md_cg` 会互相覆盖。" % len(stamps))
        A("> 每端应设独立 `MDCG_SUSTAIN_NAME`（如 `md_cg_dsh` / `md_cg_zcode`）。")
        A("")
    for w in warns:
        A("**⚠ %s**" % w)
        A("")


def render(root, now=None, we_dir=None, private=False, sessions_root=None):
    now = now or time.time()
    records = _read_jsonl(os.path.join(root, "_intent.jsonl"))
    attempts = {}
    for r in records:
        nid = str(r.get("node_id") or "")
        if nid:
            attempts[nid] = attempts.get(nid, 0) + 1
    lines = []
    A = lines.append
    A("# 日记看板")
    A("")
    A("> 本页由 `scripts/intent_board.py` 生成，**勿手改**（下次生成会覆盖）。")
    A("> 生成于 %s" % time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now)))
    A("")
    _section_heartbeat(A, root, now)
    _section_trigger(A, root, now, we_dir=we_dir, private=private, sessions_root=sessions_root)
    A("## 三、它在动，还是在往前走")
    A("")
    A("| 指标 | 值 | 判读 |")
    A("|---|---|---|")
    A("| 台账条数 | %d | 起身次数 |" % len(records))
    A("| 不同节点数 | %d | 越多越在往前走 |" % len(attempts))
    tail, tail_node = _rotation(records)
    A("| 末尾连续同一题 | %d 次 | %s |" % (tail, "⚠ 卡住了" if tail > 2 else "健康"))
    window = records[-10:]
    if len(window) >= 4:
        ratio = len(set(str(r.get("node_id") or "") for r in window)) / float(len(window))
        A("| 近期换题率（末 %d 条） | %.0f%% | %s |"
          % (len(window), ratio * 100,
             "低于 30%，多半在原地踩" if ratio < 0.3 else "正常（在换题）"))
    A("")
    if tail > 2 and tail_node:
        A("> 连续 %d 次都是 `%s`——这正是 2026-11-19 修掉的毛病。" % (tail, tail_node))
        A("> 若再次出现，先看 `md_cg/intent_tick.py` 的 `pick()` 是否按尝试次数轮转。")
        A("")
    A("## 四、待办推进")
    A("")
    A("| 节点 | 被捡起 |")
    A("|---|---|")
    for nid, n in sorted(attempts.items(), key=lambda kv: -kv[1])[:12]:
        A("| %s | %d 次 |" % (("`%s`" % nid) if private else _mask_id(nid), n))
    A("")
    A("## 五、日记目录")
    A("")
    entries = _diary(root)
    if not entries:
        A("（还没有日记——心跳捡到题之后，需要有人在前面想一遍并写下来。）")
    else:
        A("| 日期 | 节点 | 第一行 |")
        A("|---|---|---|")
        for e in entries:
            A("| %s | %s | %s |" % (e["date"],
                                     ("`%s`" % e["id"]) if private else _mask_id(e["id"]),
                                     e["head"]))
    A("")
    A("---")
    A("")
    A("重新生成：`python -X utf8 scripts/intent_board.py --root <库根> --write`")
    return "\n".join(lines)


def _opt(argv, name):
    if name in argv:
        i = argv.index(name)
        if i + 1 < len(argv):
            return argv[i + 1]
    return None


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    root = _root(argv)
    we_dir = _opt(argv, "--we-dir")
    sessions_root = _opt(argv, "--sessions-root")
    write_private = _opt(argv, "--write-private")
    private = ("--private" in argv) or bool(write_private)
    # 隐私护栏（使用者 2026-11-23 定）：关系读数不得进公开仓。两个口径同时给就拒绝——不靠人记住。
    if private and "--write" in argv:
        print("拒绝：--private 的读数不得写进公开仓（--write 指向 %s）。" % OUT_REL)
        return 2
    # 同一个护栏的第二种走法：--write-private 指向仓内。只判 --write 不够——
    # 蜂巢复核 0520 实测 --write-private 指向 docs/日记看板.md 会 rc=0 把私有页写进公开仓。
    if write_private:
        wpath = os.path.abspath(write_private)
        if wpath.startswith(os.path.abspath(REPO) + os.sep):
            print("拒绝：私有看板不得写进公开仓（%s）。" % write_private)
            return 2
    text = render(root, we_dir=we_dir, private=private, sessions_root=sessions_root)
    if write_private:
        os.makedirs(os.path.dirname(os.path.abspath(write_private)), exist_ok=True)
        with io.open(write_private, "w", encoding="utf-8", newline="\n") as f:
            f.write(text + "\n")
        print("已写入私有看板 %s" % write_private)
        return 0
    if "--write" in argv:
        out = os.path.join(REPO, OUT_REL)
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with io.open(out, "w", encoding="utf-8", newline="\n") as f:
            f.write(text + "\n")
        print("已写入 %s" % OUT_REL)
        return 0
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())