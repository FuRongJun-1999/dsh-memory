# -*- coding: utf-8 -*-
"""md_cg · 设备驱动（记忆 OS #3）：把外部会话流接进认知图

设计：
  Source（事件源）—— 把某种外部存储解析成统一事件流：
      {"t": epoch 秒, "seq": 序号, "role": ..., "text": ..., "session": ..., "cwd": ...}

  ⚠ **单位纪律（issue #23）**：`t` 一律 **epoch 秒**，与图内 `created_at` /
  `condition_space.time_window` / `trust.parse_time` 同口径。外部源里的 13 位毫秒
  （DSH 的 `time` 字段、通用 JSONL 的毫秒戳）在**源适配层**经 `trust.epoch_seconds`
  归一后即不外溢——否则 `condition_space.time_window` 会落毫秒，把
  `stg(op=timeline)` 的倒序头部整片占满并顶掉 auto-recall。

  Ingestor（摄取器）—— 增量 watermark + 去重 + 写节点 + 自动 fix-pair 挖掘。

内置源：
  · JsonlSource        —— 通用 JSONL（每行一个事件对象）
  · DSHSessionSource   —— DeepSeek Harness 会话（~/.dsh/sessions/**/session.jsonl[.zstd]）
                          zstd 为**可选**依赖：缺失时优雅降级（跳过 .zstd 文件并告警）

默认敏感度：会话内容是私有记忆 → sensitivity="private"（避免落入公开根）。

零第三方依赖（zstd 为可选增强）。
"""
from __future__ import annotations

import glob
import json
import os
import time

from . import trust
from .security import DEFAULT_SENSITIVITY

# 会话事件的默认落层与敏感度
SESSION_LAYER = "contextual"
SESSION_SENSITIVITY = "private"


# --------------------------------------------------------------------------
# 事件源
# --------------------------------------------------------------------------

# 生效条件：无必填构造形参，类常量 name="source" 即实例默认；仅当子类覆写 events() 时才产出事件，基类 events() 恒抛 NotImplementedError。
class Source:
    """事件源基类。"""

    name = "source"

# 生效条件：任何调用都直接 raise NotImplementedError（基类占位，无其它分支）。
    def events(self):
        raise NotImplementedError

# 生效条件：无前置；返回类常量 self.name（基类为 "source"），作为 watermark 的稳定标识，不含路径与运行期状态；
    def key(self):
        """源的稳定标识（用于 watermark）。"""
        return self.name


# 生效条件：required 形参 path 总被存入 self.path；可选形参 name 为假值（None/空串）时 self.name 回落到 "jsonl:"+os.path.basename(path)，为真值时用 name 本身，t_key/role_key/text_key/default_role 原样存入属性。
class JsonlSource(Source):
    """通用 JSONL 会话源。

    每行是事件对象；字段映射可配置：
      t_key      —— 时间戳字段（默认 "time"，也接受 ISO 字符串）
      role_key   —— 角色字段（默认 "role"）
      text_key   —— 文本字段（默认 "text"）
    """

# 生效条件：传入 path；name 为假值（None/空串）时回落为 "jsonl:"+os.path.basename(path)，t_key/role_key/text_key/default_role 原样存为属性（默认值 "time"/"role"/"text"/"user"）。
    def __init__(self, path: str, name: str = None, t_key="time", role_key="role",
                 text_key="text", default_role="user"):
        self.path = path
        self.name = name or ("jsonl:" + os.path.basename(path))
        self.t_key, self.role_key, self.text_key = t_key, role_key, text_key
        self.default_role = default_role

# 生效条件：无前置；返回 self.name（构造时已回落为 "jsonl:"+basename(path)），只随构造参数变化、不随文件内容变化；
    def key(self):
        return self.name

# 生效条件：o.get(self.t_key) 经 float 可转数值时返回 trust.epoch_seconds(该值)（秒值原样、13 位毫秒 /1000 归一到**秒**）；float 抛 TypeError/ValueError 且 v 为字符串时按 v[:19] 与 "%Y-%m-%dT%H:%M:%S" 解析，成功返回 mktime（**秒**）、抛 ValueError 返回 0.0；键缺失/None/其它不可转类型返回 0.0。
    def _ts(self, o):
        v = o.get(self.t_key)
        try:
            return trust.epoch_seconds(float(v)) or 0.0
        except (TypeError, ValueError):
            pass
        if isinstance(v, str):
            try:
                return time.mktime(time.strptime(v[:19], "%Y-%m-%dT%H:%M:%S"))
            except ValueError:
                return 0.0
        return 0.0

# 生效条件：os.path.exists(self.path) 为真时逐行产出，空行、json.loads 抛 ValueError、o.get(self.text_key) 为假的行被跳过，产出项为 t=self._ts(o)、seq=o.get("seq", i)、role=o.get(self.role_key) or self.default_role、text=str(text)、session/cwd 取 o 同名键；path 不存在时直接 return 不产出。
    def events(self):
        if not os.path.exists(self.path):
            return
        with open(self.path, encoding="utf-8", errors="replace") as f:
            for i, line in enumerate(f):
                line = line.strip()
                if not line:
                    continue
                try:
                    o = json.loads(line)
                except ValueError:
                    continue
                text = o.get(self.text_key)
                if not text:
                    continue
                yield {"t": self._ts(o), "seq": o.get("seq", i),
                       "role": o.get(self.role_key) or self.default_role,
                       "text": str(text), "session": o.get("session"),
                       "cwd": o.get("cwd")}


# 生效条件：path 指向的内容可读且 zstandard 可导入时返回 StringIO(raw.decode("utf-8", errors="replace"))；ImportError 时返回 None。
def _zstd_reader(path):
    """返回可读的文本迭代器；zstd 不可用返回 None。"""
    import io
    try:
        import zstandard as zstd
    except ImportError:
        return None
    with open(path, "rb") as f:
        raw = zstd.ZstdDecompressor().stream_reader(f).read()
    return io.StringIO(raw.decode("utf-8", errors="replace"))


# 生效条件：required 形参 path 总被存入 self.path，可选形参 include_reasoning 原样存入，self.name 恒为 "dsh:"+os.path.basename(os.path.dirname(path))（与 include_reasoning 取值无关）。
class DSHSessionSource(Source):
    """DeepSeek Harness 会话源。

    事件映射：
      user/message      → role=user
      assistant/message → role=assistant（只取 content[].text，reasoning 默认丢弃）
      tool/call         → role=command（"name(args)" 形式）
      tool/result       → role=tool-output
    """

# 生效条件：传入 path 即成立，include_reasoning 原样存为属性（默认 False），name 固定为 "dsh:"+os.path.basename(os.path.dirname(path))。
    def __init__(self, path: str, include_reasoning: bool = False):
        self.path = path
        self.include_reasoning = include_reasoning
        self.name = "dsh:" + os.path.basename(os.path.dirname(path))

# 生效条件：无前置；返回 self.name（构造时固定为 "dsh:"+basename(dirname(path))），与 include_reasoning 取值无关；
    def key(self):
        return self.name

    @staticmethod
# 生效条件：可选形参 root 为假值（None/空串）时改用默认目录 os.path.join(expanduser("~"),".dsh","sessions")，否则用传入 root；对 root 下递归 glob 到的 session.jsonl 与 session.jsonl.zstd 逐条 os.stat（抛 OSError 的条目跳过），按 (-st_size, path) 升序键排序（两处 glob 均无命中时为空列表），可选形参 limit 为假值（None/0）时返回全部 rows，否则返回 rows[:limit]；每行为 (path, size, mtime) 三元组。
    def discover_detailed(root: str = None, limit: int = None):
        """候选会话 → `[(path, size, mtime), ...]`（**排序唯一真源**，`discover` 复用）。

        排序：会话**文件体积**降序 → `path` 升序（确定性终键）。
        **刻意不按最近活动排序**——这正是 `source='auto'` 可能选中很久以前会话的
        原因；把 size/mtime 一并透出，让「为什么选它」在返回体里可辨
        （issue #23 附带建议：先让依据可见，是否换策略另议）。
        """
        root = root or os.path.join(os.path.expanduser("~"), ".dsh", "sessions")
        files = glob.glob(os.path.join(root, "**", "session.jsonl"), recursive=True)
        files += glob.glob(os.path.join(root, "**", "session.jsonl.zstd"), recursive=True)
        rows = []
        for p in files:
            try:
                st = os.stat(p)
            except OSError:
                continue          # 竞态删除：跳过而非整体失败
            rows.append((p, st.st_size, st.st_mtime))
        rows.sort(key=lambda r: (-r[1], r[0]))
        return rows[:limit] if limit else rows

    @staticmethod
# 生效条件：可选形参 root/limit 原样转交 discover_detailed，返回其结果的 path 列（同为体积降序、同确定性终键），limit 为假值时返回全部。
    def discover(root: str = None, limit: int = None):
        """候选会话路径（体积降序）——`discover_detailed` 的路径投影。"""
        return [p for p, _s, _m in DSHSessionSource.discover_detailed(root, limit)]

# 生效条件：self.path 以 ".zstd" 结尾时经 _zstd_reader 逐行产出（其返回 None 时 raise RuntimeError），否则以 utf-8/errors=replace 打开 self.path 逐行产出。
    def _lines(self):
        if self.path.endswith(".zstd"):
            fh = _zstd_reader(self.path)
            if fh is None:
                raise RuntimeError("zstd 不可用（pip install zstandard），跳过该会话")
            try:
                yield from fh
            finally:
                fh.close()
        else:
            with open(self.path, encoding="utf-8", errors="replace") as f:
                yield from f

    @staticmethod
# 生效条件：required 形参 content 为 str 时原样返回 content；为 list 时收集其中 str 元素及 type 属于 ("text","input-text") 且 text 为真值的 dict 元素（取 str(c["text"])），以 "\n" 连接返回（无可收集元素时为空串 ""）；既非 str 也非 list 时返回 ""。
    def _text_of(content):
        """content 可能是 [{type,text}] 或字符串。"""
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for c in content:
                if isinstance(c, dict):
                    if c.get("type") in ("text", "input-text") and c.get("text"):
                        parts.append(str(c["text"]))
                elif isinstance(c, str):
                    parts.append(c)
            return "\n".join(parts)
        return ""

# 生效条件：逐行解析后按 o.get("type") 分派——"session" 只更新 sess/cwd 不产出；"user/message" 产出 role=user 与 _text_of(data.get("content"))；"assistant/message" 产出 role=assistant 与 _text_of(msg.get("content"))，include_reasoning 为真时再把 content 中 type=="reasoning" 且有 text 的项追加 "\n[reasoning] "+str(c["text"])；"tool/call" 产出 role=command 与 f"{name}({arguments or ''})"；"tool/result" 产出 role=tool-output，仅当 inner[0] 为 dict 时 text=_text_of(inner[0].get("content"))；其它 type 或 ev 中 text 为空的事件不产出。
    def events(self):
        sess = None
        cwd = None
        for line in self._lines():
            line = line.strip()
            if not line:
                continue
            try:
                o = json.loads(line)
            except ValueError:
                continue
            t = o.get("type")
            data = o.get("data") or {}
            if t == "session":
                sess, cwd = o.get("id"), o.get("cwd")
                continue
            ev = {"t": trust.epoch_seconds(float(o.get("time") or 0)) or 0.0,
                  "seq": o.get("seq"),
                  "session": sess, "cwd": cwd}
            if t == "user/message":
                ev["role"], ev["text"] = "user", self._text_of(data.get("content"))
            elif t == "assistant/message":
                msg = data.get("message") or {}
                ev["role"] = "assistant"
                ev["text"] = self._text_of(msg.get("content"))
                if self.include_reasoning:
                    for c in (msg.get("content") or []):
                        if isinstance(c, dict) and c.get("type") == "reasoning" \
                                and c.get("text"):
                            ev["text"] = (ev["text"] or "") + "\n[reasoning] " + str(c["text"])
            elif t == "tool/call":
                ev["role"] = "command"
                ev["text"] = f"{data.get('name')}({data.get('arguments') or ''})"
            elif t == "tool/result":
                msg = data.get("message") or {}
                inner = msg.get("content") or []
                txt = ""
                if inner and isinstance(inner[0], dict):
                    txt = self._text_of(inner[0].get("content"))
                ev["role"], ev["text"] = "tool-output", txt
            else:
                continue
            if ev.get("text"):
                yield ev


# --------------------------------------------------------------------------
# 蜂巢任务事件源（M6：hive/jobs → contextual，D:\2_ai 蜂巢记忆架构设计.md §5）
# --------------------------------------------------------------------------

class HiveJobsSource(Source):
    """蜂巢任务事件源。

    事件映射（设计稿 §5.3）：
      start            → role=user，任务开始（task 摘要）
      tool             → **跳过**（防流水账爆炸；tool_trace 已在 result 有摘要）
      handoff          → role=assistant，续跑卡
      error            → role=assistant，「任务失败(job=…)：…」（fix-pair 前件）
      final            → role=assistant，content 头
      result.json 终态 → **权威确认事件**（progress 可能因强杀缺失 final）：
                          done → 「任务完成(job=…)」；error/timeout/killed → 「任务失败(job=…)」

    排序：job_id 名升序 = 时间升序（job.rs 命名保证 h<unix_ms>_<pid>），
    跨 job 全序成立；seq 由本源按枚举顺序递增（ingest 去重键 = (session, seq)）。
    解析失败的行/条目计入 self.skipped，不终杀批次。
    """

    name = "hive_jobs"

    def __init__(self, root: str, error_sensitivity: str = "private"):
        self.root = os.path.abspath(root)
        self.skipped = 0
        # §5.5「error:true 建议 private」——默认 private；调用方 clearance 不足时
        # 可显式降级 error_sensitivity="internal"（显式权衡：接受失败细节入 internal，
        # 换取误差归因原料不丢）。能否落盘由写入者 clearance 裁决（写隔离）。
        self.error_sensitivity = error_sensitivity

    def key(self):
        """多仓/多池隔离：root 参与键（watermark 按源路径各自推进）。"""
        return f"hive_jobs:{self.root}"

    def _jobs(self):
        try:
            return sorted(d for d in os.listdir(self.root)
                          if d.startswith("h")
                          and os.path.isdir(os.path.join(self.root, d)))
        except OSError:
            return []

    def _read_json(self, path):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            self.skipped += 1
            return None

    def events(self):
        seq = 0
        for job_id in self._jobs():
            jdir = os.path.join(self.root, job_id)
            sess = f"hive:{job_id}"
            spec = self._read_json(os.path.join(jdir, "spec.json")) or {}
            task = str(spec.get("user_prompt") or "")[:200]

            has_final = False
            prog = os.path.join(jdir, "progress.jsonl")
            if os.path.isfile(prog):
                try:
                    fh = open(prog, encoding="utf-8", errors="replace")
                except OSError:
                    fh = None
                if fh is not None:
                    with fh:
                        for line in fh:
                            line = line.strip()
                            if not line:
                                continue
                            try:
                                o = json.loads(line)
                            except ValueError:
                                self.skipped += 1
                                continue
                            kind = o.get("kind")
                            t = trust.epoch_seconds(float(o.get("ts") or 0)) or 0.0
                            if kind == "start":
                                seq += 1
                                yield {"t": t, "seq": seq, "session": sess,
                                       "role": "user",
                                       "text": f"任务开始(job={job_id})：{task}"}
                            elif kind == "handoff":
                                seq += 1
                                has_final = True
                                yield {"t": t, "seq": seq, "session": sess,
                                       "role": "assistant",
                                       "text": f"续跑卡(job={job_id})："
                                               f"{str(o.get('summary') or '')[:400]}"}
                            elif kind == "error":
                                seq += 1
                                ev = {"t": t, "seq": seq, "session": sess,
                                      "role": "assistant",
                                      "text": f"任务失败(job={job_id})："
                                              f"{str(o.get('error') or '')[:300]}"}
                                if self.error_sensitivity:
                                    ev["sensitivity"] = self.error_sensitivity
                                yield ev
                            elif kind == "final":
                                seq += 1
                                has_final = True
                                yield {"t": t, "seq": seq, "session": sess,
                                       "role": "assistant",
                                       "text": str(o.get("content_head") or "")[:400]}
                            # tool / budget_stop / force_final / 其它 → 纯跳过
                            # （§5.3 原设计为聚合计数，实现从简——终态由 result.json
                            #   权威确认承载，无需逐条累计；防流水账爆炸目标不变。
                            #   注释曾照抄设计稿口径称「仅聚合计数」，与实现漂移，
                            #   zcode 外评抓出，2026-09-23 修正）

            # result.json 终态权威确认（progress 可能因强杀缺失 final）
            res = self._read_json(os.path.join(jdir, "result.json")) or {}
            state = "done" if res.get("ok") is True else \
                ("error" if res.get("ok") is False else None)
            if state is None:
                continue
            t = trust.epoch_seconds(float(res.get("finished_ts") or 0)) or 0.0
            head = str(res.get("content") or "")[:300]
            err = str(res.get("error") or "")[:300]
            seq += 1
            if state == "done":
                # 前缀独立成行：content 的行首结构（命令行等）不被破坏，
                # 保证 mine_fix_pairs 的 _FIX_RE 行首启发式仍能命中修复证据
                yield {"t": t, "seq": seq, "session": sess, "role": "assistant",
                       "text": f"任务完成(job={job_id})：\n{head}"}
            else:
                tag = "超时强杀" if st_err_is_timeout(err) else "失败"
                ev = {"t": t, "seq": seq, "session": sess, "role": "assistant",
                      "text": f"任务{tag}(job={job_id})：{err or head}"
                              + ("" if has_final else "（progress 缺 final，"
                                                      "本条为 result 终态补位）")}
                if self.error_sensitivity:
                    ev["sensitivity"] = self.error_sensitivity
                yield ev


def st_err_is_timeout(err: str) -> bool:
    return "超时" in (err or "")


# --------------------------------------------------------------------------
# 摄取器
# --------------------------------------------------------------------------

# 生效条件：required 形参 cg 总被存入并以其 cg.root 拼出 self.path=os.path.join(cg.root,"_sources.json")；layer/sensitivity 原样存入，未传时取模块级常量 SESSION_LAYER、SESSION_SENSITIVITY 作为默认值。
class Ingestor:
    """增量摄取：watermark + 去重 + 写节点 + 自动 fix-pair 挖掘。

    watermark 文件：<root>/_sources.json
        {source_key: {"t": 最后时间戳(epoch 秒), "seq": 最后序号, "count": 已摄取条数}}

    存量水位兼容：**旧版写入的是毫秒**，读回时经 `trust.epoch_seconds` 归一到秒，
    故升级后无需清 `_sources.json` 重建（否则 `ev["t"] < last_t` 恒真 → 新事件全被跳过）。
    """

# 生效条件：传入带 root 的 cg 即成立，layer/sensitivity 默认 SESSION_LAYER/SESSION_SENSITIVITY 并原样存为属性，路径为 os.path.join(cg.root, "_sources.json")。
    def __init__(self, cg, layer: str = SESSION_LAYER,
                 sensitivity: str = SESSION_SENSITIVITY):
        self.cg = cg
        self.layer = layer
        self.sensitivity = sensitivity
        self.path = os.path.join(cg.root, "_sources.json")

    # ---- watermark ----

# 生效条件：self.path 存在、json.load 成功且结果为 dict 时返回该 dict；path 不存在、抛 ValueError/OSError 或结果非 dict 时返回 {"schema": 1, "sources": {}}。
    def _load(self):
        if os.path.exists(self.path):
            try:
                with open(self.path, encoding="utf-8") as f:
                    d = json.load(f)
                if isinstance(d, dict):
                    return d
            except (ValueError, OSError):
                pass
        return {"schema": 1, "sources": {}}

# 生效条件：传入 d 时以 ensure_ascii=False/indent=1 写入 self.path+".tmp"，再 os.replace 覆盖 self.path。
    def _save(self, d):
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.path)

# 生效条件：key 命中 self._load()["sources"] 时返回其值，缺 key 时返回 {}（_load 结果缺 "sources" 键则抛 KeyError）。
    def watermark(self, key: str):
        return self._load()["sources"].get(key, {})

# 生效条件：调用即返回 dict(self._load()["sources"]) 的浅拷贝（_load 结果缺 "sources" 键则抛 KeyError）。
    def watermarks(self):
        return dict(self._load()["sources"])

    # ---- 摄取 ----

# 生效条件：对必需形参 source，先按 watermark(source.key()) 跳过 t<last_t（wm 的 "t" 为假值时视作 0）及 t==last_t 且 last_seq 非 None 且 ev["seq"] 为 int 且 <= last_seq 的事件、并按 (session, seq) 去重，max_events 为真值（非 0/None）时取满即停；dry_run 为假时逐条 cg.add（nid 已在 cg.index["nodes"] 中则跳过，cg.add 抛异常则 denied+=1、记 last_error 并继续），denied 与 last_error 同时成立时补 last_error/hint 与 denied_events 明细，mine_fix_pairs 为真且 new_events 非空且非 dry_run 时以 as_proposals=True 调 mine_fix_pairs（自动产物走审核队列）并结果附 fix_pairs，new_events 非空且非 dry_run 时以末事件写回水位（count 累加 written），最后返回 result。
    def ingest(self, source, mine_fix_pairs: bool = False, max_events: int = None,
               dry_run: bool = False):
        """摄取一个源的新事件。返回统计。

        去重键：(session, seq) —— 同一事件不重复入库。
        增量：只处理 (t, seq) 大于 watermark 的事件。
        mine_fix_pairs 默认 False（先落账后挖矿——§5.5 系统纪律化，
        zcode 外评 break#2：默认 True 曾使 file/jsonl/mdcg_ingest 三入口
        绕过审核队列直写 knowledge 层）；显式开启时产物走 propose 队列。
        """
        key = source.key()
        wm = self.watermark(key)
        # 水位单位归一：**存量水位是毫秒**（旧版 `_ts` 产出），不归一会让
        # `ev["t"] < last_t` 恒真 → 升级后新事件被整片误判为「已处理」而跳过。
        last_t, last_seq = trust.epoch_seconds(float(wm.get("t") or 0)) or 0.0, \
            wm.get("seq")
        new_events, seen = [], set()
        denied_events = []               # 被拒事件明细（session/seq/原因）——可观测可重放
        for ev in source.events():
            if ev.get("t", 0) < last_t:
                continue
            if ev.get("t", 0) == last_t and last_seq is not None \
                    and isinstance(ev.get("seq"), int) and ev["seq"] <= last_seq:
                continue
            dedup = (ev.get("session"), ev.get("seq"))
            if dedup in seen:
                continue
            seen.add(dedup)
            new_events.append(ev)
            if max_events and len(new_events) >= max_events:
                break

        written, ids, denied = 0, [], 0
        if not dry_run:
            for ev in new_events:
                nid = "src_%s_%s" % (_sig(key)[:6], _sig(
                    f"{ev.get('session')}:{ev.get('seq')}")[:10])
                if nid in self.cg.index["nodes"]:
                    continue          # 幂等
                body = ("# 功能名：会话事件\n"
                        f"# 生效条件：检索「{str(ev.get('text'))[:20]}」\n"
                        "# 子功能：记录会话事件\n"
                        f"# 执行：{str(ev.get('text'))[:80]}\n"
                        "# 验证方式：data（会话原始记录）\n"
                        "# 不适用条件：其它会话\n\n"
                        f"{ev.get('text')}\n")
                try:
                    self.cg.add(nid, body, layer=self.layer, role=ev.get("role"),
                                tags=["session", key],
                                # 事件级密级覆盖（M6 §5.5）：error 事件建议 private
                                # （失败细节可能含路径/配置），缺省回落源级默认
                                sensitivity=ev.get("sensitivity") or self.sensitivity,
                                verification_basis="data",
                                condition_space={"observation_position": key,
                                                 "observation_tool": "会话流",
                                                 "time_window": [ev.get("t") or 0,
                                                                 ev.get("t") or 0]})
                except Exception as exc:   # noqa: BLE001 —— 权限/层错误不中断整批
                    denied += 1
                    # 诚实化（M6）：denied 事件虽被水位跳过，但明细必须可见——
                    # 静默丢失会吞掉误差归因闭环的原料（error 事件恰是原料）
                    denied_events.append({
                        "session": ev.get("session"), "seq": ev.get("seq"),
                        "error": str(exc)[:150]})
                    self.last_error = f"{type(exc).__name__}: {exc}"
                    continue
                ids.append(nid)
                written += 1

        result = {"source": key, "new_events": len(new_events), "written": written,
                  "denied": denied, "ids": ids, "dry_run": dry_run,
                  "sensitivity": self.sensitivity}
        if denied_events:
            result["denied_events"] = denied_events
        if denied and getattr(self, "last_error", None):
            result["last_error"] = self.last_error
            result["hint"] = ("会话内容默认 sensitivity=private；"
                              "调用方需 MDCG_CLEARANCE=private 才能写入")
        # 自动 fix-pair 挖掘（对标 deja-vu：错误→修复）——as_proposals=True：
        # 自动管线产物走审核队列，绝不直写 knowledge 层（§5.5 系统纪律）
        if mine_fix_pairs and new_events and not dry_run:
            result["fix_pairs"] = self.cg.mine_fix_pairs(
                [{"role": e.get("role"), "text": e.get("text")}
                 for e in new_events], as_proposals=True)

        if new_events and not dry_run:
            d = self._load()
            last = new_events[-1]
            d["sources"][key] = {
                "t": last.get("t") or last_t,
                "seq": last.get("seq"),
                "count": (wm.get("count") or 0) + written,
                "updated_at": time.time(),
                "path": getattr(source, "path", None),
            }
            self._save(d)
        return result


# 生效条件：text 为 None 或假值时按 "" 参与 sha1；n 默认 12，返回 hexdigest 前 n 位（n=0 得空串）。
def _sig(text: str, n: int = 12) -> str:
    import hashlib
    return hashlib.sha1((text or "").encode("utf-8")).hexdigest()[:n]


# --------------------------------------------------------------------------
# 摄取分派（P0 · ingest op）：按扩展名选摄取方式，单一入口吃多种文件
# --------------------------------------------------------------------------
#
# 三条摄取链：
#   session —— 会话流（.jsonl）：走 Ingestor（watermark + 去重 + fix-pair）
#   doc     —— 文档（.md/.txt/...）：走 docindex.extract + refindex.add_items
#   code    —— 代码（.py/.ts/...）：走 codeindex.extract + refindex.add_items
#
# 设计要点：
#   - 注册表 INGEST_REGISTRY 是唯一真源：新增后缀只改这里。
#   - dir 动作分链处理：目录里 doc / code / jsonl 混放时各链互不干扰。
#   - 幂等：沿用 refindex.Ledger（size+mtime 水位）与 Ingestor watermark。
#   - 预演：dry_run=True 只统计、不写入（对应计划「可预演」要求）。

INGEST_ACTIONS = ("file", "dir", "jsonl", "stat", "hive")

INGEST_REGISTRY = {
    # 会话流
    ".jsonl": "session", ".ndjson": "session",
    # 文档
    ".md": "doc", ".markdown": "doc", ".txt": "doc", ".rst": "doc",
    ".html": "doc", ".htm": "doc",
    # 代码
    ".py": "code", ".js": "code", ".mjs": "code", ".ts": "code",
    ".tsx": "code", ".jsx": "code", ".go": "code", ".rs": "code",
    ".java": "code", ".kt": "code", ".swift": "code", ".rb": "code",
    ".php": "code", ".cs": "code", ".cpp": "code", ".cc": "code",
    ".c": "code", ".h": "code", ".hpp": "code",
}


# 生效条件：path 为 None 或空串时 splitext 得 "" 且未登记 → 返回 None；扩展名（小写）存在于 INGEST_REGISTRY 时返回其 kind。
def dispatch_of(path: str):
    """按扩展名返回摄取方式（session / doc / code）；未登记返回 None。"""
    return INGEST_REGISTRY.get(os.path.splitext(path or "")[1].lower())


# 生效条件：required 形参 cg 总被存入；可选形参 sensitivity 为假值（None/空串）时内部 Ingestor 的 sensitivity 回落模块级常量 SESSION_SENSITIVITY，为真值时用传入的 sensitivity。
class FileDispatcher:
    """单一入口吃多种文件：按扩展名分派到会话流 / 文档 / 代码三条摄取链。"""

# 生效条件：传入 cg 即成立，sensitivity 为假值（None/空串）时所用 Ingestor 回落 SESSION_SENSITIVITY，否则用传入值。
    def __init__(self, cg, sensitivity=None):
        self.cg = cg
        # 会话链默认 sensitivity=private；调用方可显式覆盖（测试/受限环境）
        self.ingestor = Ingestor(cg, sensitivity=sensitivity or SESSION_SENSITIVITY)

    # ---- stat：看水位与支持面 ----

# 生效条件：from . import refindex 与 refindex.Ledger(self.cg.root).stat() 均不抛异常时返回该 stat 结果，抛任何异常时返回 {}。
    def _ledger_stat(self):
        try:
            from . import refindex
            return refindex.Ledger(self.cg.root).stat()
        except Exception:                                  # noqa: BLE001
            return {}

# 生效条件：调用即返回由 INGEST_REGISTRY 按 kind 分组并排序后的 extensions、list(INGEST_ACTIONS)、self.ingestor.watermarks()、self._ledger_stat() 与固定 note。
    def stat(self):
        kinds = {}
        for ext, kind in INGEST_REGISTRY.items():
            kinds.setdefault(kind, []).append(ext)
        return {"ok": True, "kind": "stat", "actions": list(INGEST_ACTIONS),
                "extensions": {k: sorted(v) for k, v in sorted(kinds.items())},
                "watermarks": self.ingestor.watermarks(),
                "ledger": self._ledger_stat(),
                "note": ("注册表是唯一真源：新增后缀只改 INGEST_REGISTRY。"
                         "watermarks=会话流水位；ledger=文档/代码文件水位。")}

    # ---- 单文件 ----

# 生效条件：dispatch_of(path) 为 None 时返回 ok=False 的「不支持的后缀」结果；path 不是文件时返回 ok=False 的「文件不存在」结果；kind=="session" 时转 ingest_jsonl(path, dry_run=dry_run)（layer/sensitivity 不参与）；其它 kind 转 _ingest_doc_or_code(path, kind, layer=layer, sensitivity=sensitivity, dry_run=dry_run)。
    def ingest_file(self, path, layer=None, sensitivity=None, dry_run=False):
        kind = dispatch_of(path)
        if kind is None:
            ext = os.path.splitext(path or "")[1] or "(无后缀)"
            return {"ok": False, "path": path, "error": f"不支持的后缀：{ext}",
                    "supported": sorted(INGEST_REGISTRY)}
        if not os.path.isfile(path):
            return {"ok": False, "path": path, "error": "文件不存在"}
        if kind == "session":
            return self.ingest_jsonl(path, dry_run=dry_run)
        return self._ingest_doc_or_code(path, kind, layer=layer,
                                         sensitivity=sensitivity, dry_run=dry_run)

# 生效条件：kind=="code" 用 codeindex 否则用 docindex；mod.extract 抛 ValueError 时返回 ok=False 的「抽取失败」；dry_run 为真时只返回 items 计数与前 20 个 node_id 不写盘；否则经 refindex.add_items（kind 为 code_ref/doc_ref）写入并返回 indexed、ids[:20] 与 sensitivity。
    def _ingest_doc_or_code(self, path, kind, layer=None, sensitivity=None,
                            dry_run=False):
        from . import codeindex, docindex, refindex
        mod = codeindex if kind == "code" else docindex
        rel = os.path.basename(path)
        with open(path, encoding="utf-8", errors="replace") as f:
            src = f.read()
        try:
            items = mod.extract(src, path=rel,
                                suffix=os.path.splitext(path)[1].lower())
        except ValueError as exc:
            return {"ok": False, "path": path, "error": f"抽取失败：{exc}"}
        items = items or []
        if dry_run:
            return {"ok": True, "dry_run": True, "kind": kind, "path": path,
                    "items": len(items),
                    "ids": [mod.node_id(i) for i in items[:20]],
                    "note": "预演：只抽取计数，未写盘"}
        ref_kind = "code_ref" if kind == "code" else "doc_ref"
        ids, sens = refindex.add_items(
            self.cg, items, kind=ref_kind,
            root=os.path.dirname(path) or ".", layer=layer,
            sensitivity=sensitivity)
        return {"ok": True, "kind": kind, "path": path, "items": len(items),
                "indexed": len(ids), "ids": ids[:20], "sensitivity": sens}

    # ---- 目录 ----

# 生效条件：调用即 os.walk(root) 统计每个文件名经 dispatch_of 得到的 kind（无匹配记 "unsupported"）并返回 dry_run 预演计数结果。
    def _dry_dir(self, root):
        counts = {}
        for _dp, _dn, fns in os.walk(root):
            for name in fns:
                k = dispatch_of(name) or "unsupported"
                counts[k] = counts.get(k, 0) + 1
        return {"ok": True, "dry_run": True, "kind": "dir", "root": root,
                "counts": counts,
                "note": "预演：仅统计各链文件数，未做任何写入"}

# 生效条件：root 非目录时返回 ok=False 的「目录不存在」；dry_run 为真时返回 _dry_dir(root)；否则对 doc_ref/code_ref 两链各以 patterns/max_files/max_items/incremental/ledger 调 refindex.index_dir 与 add_items，并把 root 下 **/*.jsonl 前 max_files 个逐个 ingest_jsonl 后返回 out。
    def ingest_dir(self, root, layer=None, sensitivity=None, patterns=None,
                   max_files=500, max_items=2000, incremental=False,
                   dry_run=False):
        from . import refindex
        if not os.path.isdir(root):
            return {"ok": False, "error": f"目录不存在：{root}"}
        if dry_run:
            return self._dry_dir(root)
        ledger = refindex.Ledger(self.cg.root)
        out = {"ok": True, "kind": "dir", "root": root, "chains": {}}
        for ref_kind, key in (("doc_ref", "doc"), ("code_ref", "code")):
            items, errors, stats = refindex.index_dir(
                root, kind=ref_kind, patterns=patterns, max_files=max_files,
                max_items=max_items, incremental=incremental, ledger=ledger)
            ids, sens = refindex.add_items(self.cg, items, kind=ref_kind,
                                           root=root, layer=layer,
                                           sensitivity=sensitivity)
            out["chains"][key] = {
                "indexed": len(ids), "errors": len(errors),
                "files": stats.get("files"), "truncated": stats.get("truncated"),
                "skipped_unchanged": stats.get("skipped_unchanged", 0),
                "skipped_suffixes": stats.get("skipped_suffixes", []),
                "sensitivity": sens}
        # 会话流（.jsonl）逐个增量摄取
        jsons = sorted(glob.glob(os.path.join(root, "**", "*.jsonl"),
                                 recursive=True))[:max_files]
        ses = []
        for p in jsons:
            r = self.ingest_jsonl(p)
            ses.append({"path": p, "written": r.get("written", 0),
                        "new_events": r.get("new_events", 0)})
        out["chains"]["session"] = {"files": len(jsons), "results": ses}
        return out

    # ---- 会话流 ----

    @staticmethod
# 生效条件：required 形参 path 能被 open(...,encoding="utf-8",errors="replace") 打开时读前 50000 字符，head 含 '"user/message"'、'"assistant/message"'、'"tool/call"' 任一标记则返回 DSHSessionSource(path)，否则返回 JsonlSource(path)；打开抛 OSError 时直接返回 JsonlSource(path)。
    def _auto_source(path):
        """通用 JSONL vs DSH 会话：按内容探测，避免调用方选错源类型。"""
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                head = f.read(50000)
        except OSError:
            return JsonlSource(path)
        for marker in ('"user/message"', '"assistant/message"', '"tool/call"'):
            if marker in head:
                return DSHSessionSource(path)
        return JsonlSource(path)

# 生效条件：path 不是文件时返回 ok=False 的「文件不存在」；否则经 _auto_source(path) 选源后调 self.ingestor.ingest(src, dry_run=dry_run, max_events=max_events)，并补上 ok=True/kind/path/source_class 后返回。
    def ingest_jsonl(self, path, dry_run=False, max_events=None):
        if not os.path.isfile(path):
            return {"ok": False, "error": f"文件不存在：{path}"}
        src = self._auto_source(path)
        res = self.ingestor.ingest(src, dry_run=dry_run, max_events=max_events)
        res.update({"ok": True, "kind": "session", "path": path,
                    "source_class": type(src).__name__})
        return res


# 生效条件：cg 必填；action 为 None/空串时 (action or "stat") 归为 stat；file/jsonl 缺 path 返回 ok=False；dir 的 max_files/max_items 走 int(x or 500)/int(x or 2000)，传 0 也变 500/2000；未知 action 抛 ValueError。
def run(cg, action: str = "stat", **kw):
    """ingest op 唯一入口。"""
    act = (action or "stat").strip().lower()
    d = FileDispatcher(cg, sensitivity=kw.get("sensitivity"))
    if act == "stat":
        return d.stat()
    if act == "file":
        p = kw.get("path")
        if not p:
            return {"ok": False, "error": "file 动作需要 path"}
        return d.ingest_file(p, layer=kw.get("layer"),
                             sensitivity=kw.get("sensitivity"),
                             dry_run=bool(kw.get("dry_run")))
    if act == "dir":
        p = kw.get("path") or cg.root
        return d.ingest_dir(p, layer=kw.get("layer"),
                            sensitivity=kw.get("sensitivity"),
                            patterns=kw.get("patterns"),
                            max_files=int(kw.get("max_files") or 500),
                            max_items=int(kw.get("max_items") or 2000),
                            incremental=bool(kw.get("incremental")),
                            dry_run=bool(kw.get("dry_run")))
    if act == "jsonl":
        p = kw.get("path")
        if not p:
            return {"ok": False, "error": "jsonl 动作需要 path"}
        return d.ingest_jsonl(p, dry_run=bool(kw.get("dry_run")),
                              max_events=kw.get("max_events"))
    if act == "hive":
        # M6：蜂巢任务事件源（hive/jobs → contextual）。root 解析链：显式 path >
        # env MDCG_HIVE_JOBS > 报错指引（fail-closed，不猜仓库布局）。
        # §5.5 硬纪律：mine_fix_pairs=False（先落账后挖矿——自动挖掘产物直写
        # knowledge 层违反双轨制，实测 0→2 污染）；默认密级 internal，
        # error 事件由源层 per-event 覆写 private（失败细节可能含路径/配置）。
        root = kw.get("path") or os.environ.get("MDCG_HIVE_JOBS")
        if not root:
            return {"ok": False, "error": (
                "hive 动作需要 path（hive/jobs 目录），或设 env MDCG_HIVE_JOBS——"
                "不猜测仓库布局（fail-closed）")}
        src = HiveJobsSource(root, error_sensitivity=kw.get("error_sensitivity")
                             if kw.get("error_sensitivity") is not None else "private")
        rep = Ingestor(cg, layer=kw.get("layer") or "contextual",
                       sensitivity=kw.get("sensitivity") or "internal"
                       ).ingest(src, mine_fix_pairs=False,
                                max_events=kw.get("max_events"),
                                dry_run=bool(kw.get("dry_run")))
        rep["source"] = src.key()
        rep["skipped"] = src.skipped
        return rep
    raise ValueError(f"未知 ingest action：{action!r}（允许 {INGEST_ACTIONS}）")