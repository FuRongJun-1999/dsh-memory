# -*- coding: utf-8 -*-
"""灵枢蜂巢 · 默认 LLM 执行器（零第三方依赖，Python 标准库）。

契约（与 hive/src/exec.rs 头注释一致）：
    入参   argv[1] = job 目录
    读     spec.json（model / system_prompt / user_prompt / context_files /
             timeout_s / max_tokens / temperature / thinking / reasoning_effort /
             context_budget_tokens / tools / max_tool_rounds / ...）
    写     result.json —— 成功与 API 错误都写，error 字段区分：
             {"ok": true, "content": "...", "usage": {...}, "model": "...",
              "tool_trace": [...],                       # 仅 spec.tools 时存在
              "finished_ts": ..., "duration_s": ...}
             {"ok": false, "error": "...", ...}
           log.txt —— 详细日志（stdout/stderr 保持安静，不污染 serve 控制台）
    退出码 0 成功 / 2 规格错 / 3 API 错误

API：OpenAI 兼容 chat/completions（GLM 同形）。
env：HIVE_API_KEY（必填，缺失即 fail）、
     HIVE_API_BASE（默认 https://open.bigmodel.cn/api/paas/v4）、
     MDCG_ROOT（lingshu_cg 工具的认知图根；缺省该工具返回配置缺失错误）、
     MDCG_HOME（md_cg 包所在仓根；缺省=执行器父目录，同仓分发零配置）、
     HIVE_WEB_SEARCH（web_search 后端：zhipu[默认] | duckduckgo）、
     HIVE_WEB_SEARCH_BASE（zhipu 搜索端点 base，缺省智谱官方
       https://open.bigmodel.cn/api/paas/v4——与 HIVE_API_BASE 解耦，
       后者常为 LLM 中转网关、无 web_search 路由）、
     HIVE_WEB_SEARCH_KEY（搜索密钥，缺省回落 HIVE_API_KEY）。

工具面（agent loop）：spec.tools 白名单启用，缺省 = 无工具 = 单发调用
（行为与历史版本逐位一致）。启用后按 OpenAI function calling 循环：
模型回 tool_calls → 执行器执行 → tool 消息回喂 → 循环至终答或达
max_tool_rounds（默认 5，随后发一次不带 tools 的请求强制终答）。
  lingshu_cg  灵枢认知图（op=route|read|write 白名单）；权限硬编码 recorder
              （can_admin=False，spec 无法提权），写入过校验闸门（DEFER 入
              审核队列/REJECT 负记忆是设计行为）；会话隔离 session=hive_job_<id>。
  web_search  网页搜索；zhipu 后端复用 HIVE_API_KEY/HIVE_API_BASE 调
              /web_search 端点，duckduckgo 兜底（零 key，html 抓取）。
  read_file   读本地文件/目录（只读，默认全路径开放）；文本给行窗分页
              （offset/limit，首行行号=offset），目录给条目清单，图像/二进制
              只给类型+字节数不返回正文。部署侧可用 HIVE_READ_ROOTS 收窄
              可读根（未设置=放开）。
读写不对称（2026-09-19 裁定，勿对称化）：**读放开、写严格**——读错只损失
一次召回（可重试、tool_trace 可回放路径），写错污染长期记忆（不可逆、会
传播给后续检索）。故执行器只增只读工具，写路径唯一 = lingshu_cg op=write
（recorder 令牌 + 校验闸门）。
每轮工具调用记入 result.json 的 tool_trace（审计可回放）；工具结果回喂前
截断（TOOL_MSG_MAX_CHARS），防上下文爆炸。

HTTPS 之所以在这里而不是 rust：TLS 无第三方库在纯 std rust 不可行（D-005）；
Python urllib 走系统证书，零依赖达成。执行器是可替换子进程——换 curl /
其它 SDK 宿主时，保持「读 spec.json、写 result.json」契约即可。

上下文拼接：context_files 逐个读入，以
    <context path="...">
    ...文件全文...
    </context>
块追加在 user_prompt 之前（AI 侧归一由调用方在 spec 里完成，执行器不加工）。
图像/二进制文件不读内容（Pi⑦④ 护栏）：零依赖探尺寸，只登记块 + 计入预算
（图像按 IMAGE_EST_TOKENS/张），避免二进制乱码污染上下文。

进展面（v0.4 §5.3 满上下文换人续跑）：exec 在自己 job 目录追加 progress.jsonl
（start/tool/final/handoff/error 五类条目，含步骤、完成项、中间结果摘要、证据、
时间戳）。worker 零 git 依赖——进展只写自家 job 目录，由主代理 snapshot 纳白名单。

达预算不 fail：每轮估算累计上下文（messages + 图像折算），超预算默认**交回**
（写进展卡 + result.need_continue=true + completed=false，退出码 0），由主代理
按需 spawn 新 job 续跑（不自动续跑）；spec.context_strict=true 时保持旧 fail fast。
工具结果超 TOOL_MSG_MAX_CHARS 时全量落盘 job 目录（tool_<round>_<seq>.json）+
回喂消息保尾（Pi⑦③，对齐 exec_cmd._dump_step/_render）。
"""
from __future__ import annotations

import json
import os
import re
import sys
import tempfile
import time
import traceback
import urllib.error
import urllib.request

DEFAULT_API_BASE = "https://open.bigmodel.cn/api/paas/v4"

# P2-17（批次 30）：响应体读取字节上限——异常/恶意网关返回超大响应
# 不再能撑爆内存（resp.read(N) 最多读 N 字节，截断 JSON 会在解析层失败）。
RESP_MAX_BYTES = 8 * 1024 * 1024
CONTEXT_TEXT_MAX = 256 * 1024

EXIT_OK, EXIT_SPEC, EXIT_API = 0, 2, 3


# 生效条件：当 job_dir 与 msg 传入时，向 job_dir/log.txt 追加带 time.strftime('%H:%M:%S') 前缀的 msg 行；若 open/write 抛 OSError 或 TypeError，则把同一行写到 sys.stderr；
def log(job_dir: str, msg: str) -> None:
    """写 job 日志。日志是观测面——写失败降级到 stderr，绝不打断任务。"""
    line = f"[{time.strftime('%H:%M:%S')}] {msg}\n"
    try:
        with open(os.path.join(job_dir, "log.txt"), "a", encoding="utf-8") as f:
            f.write(line)
    except (OSError, TypeError):
        sys.stderr.write(line)


# 生效条件：当 job_dir 与 payload 传入后，env HIVE_RESULT_ANCHOR 去空白非真时 payload["result_anchor"] = 该值（P11 批次53 执行器契约：serve 对锚预期任务注入此 env，执行器原样回写，值本身由 serve 侧 HMAC 校验——本处不做任何密码学运算）；随后 tempfile.mkstemp(prefix="result.json.", suffix=".tmp", dir=job_dir) 建唯一临时文件并 UTF-8 写入 json.dump(payload, ensure_ascii=False)+flush+fsync，再 os.replace 到 job_dir/result.json；Windows 上 replace 撞读者瞬态句柄（WinError 5/PermissionError）时按 10ms×递增重试至多 50 次（约 12.5s）；replace 撞 FileNotFoundError（tmp 被瞬态消费/清理）时重建唯一名重写后重试；任一重试耗尽才向外抛；finally 里 best-effort 清理仍存在的 tmp；成功路径不残留任何 .tmp；
def write_result(job_dir: str, payload: dict) -> None:
    """tmp + fsync + rename 原子替换（并发读者不读到截断空窗口）。

    P11 结果完整性锚回写（批次53）：serve 对锚预期任务（status 带 result_nonce）
    经 env HIVE_RESULT_ANCHOR 注入预期锚；本执行器原样回写 payload.result_anchor，
    终态判据面（rust classify_result）据此采信 done。env 缺省（旧格式任务/直跑）
    时不写该字段——产物格式向后兼容。诚实边界：只透传不计算（锚的秘密性归
    serve 侧密钥，执行器侧无法也不必复算）。

    v2 N6：旧实现 open("w") 先截断再写——rust serve 超时/kill 强杀落在写入
    窗口内即留半截文件，且**先毁旧完整结果**（重投第二次执行同路径）；读者
    （rust 轮询 / hive_mcp._result_view / orch._card / wm snapshot）读到截断
    JSON 会把成功任务读成 error 终态。原子替换保证 result.json 任意时刻
    要么是旧完整态、要么是新完整态。

    Windows 适配（exec_cmd 读者是 rust FILE_SHARE_DELETE 无此问题；本执行器
    读者面含 Python open，replace 会撞瞬态句柄 WinError 5）：短睡重试，重试
    耗尽才抛——失败时旧完整结果仍在位，优于截断（fail-safe）。

    v10 N82 止血（2026-09-25，动态复现三次成立）：固定共享临时名
    p + ".tmp" 在 rust 重投双执行者并发跑同一 job 时对撞——一者 replace
    抢先消费共享 tmp，另一者 FileNotFoundError 外逃，main 顶层兜底再以
    ok=false 覆写对撞写者的成功终态。mkstemp 唯一临时名（同目录保证 rename
    原子性，随机后缀天然防共享名对撞；同 md_cg/fsutil.atomic_write 模板）；
    FileNotFoundError 并入重试面（扑空时重建唯一名重写再试，不外逃）；
    finally 清理残留 tmp（成功路径零残留，对齐 K1 口径）。
    """
    p = os.path.join(job_dir, "result.json")

    # P11 锚回写（批次53）：env 注入即透传（见头注「诚实边界」）
    _anchor = (os.environ.get("HIVE_RESULT_ANCHOR") or "").strip()
    if _anchor:
        payload["result_anchor"] = _anchor

    def _mk_and_dump():
        fd, tmp = tempfile.mkstemp(prefix="result.json.", suffix=".tmp",
                                   dir=job_dir)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        return tmp

    tmp = _mk_and_dump()
    try:
        for attempt in range(50):
            try:
                os.replace(tmp, p)
                return
            except PermissionError:
                if attempt == 49:
                    raise
                time.sleep(0.01 * (attempt + 1))
            except FileNotFoundError:
                # tmp 被瞬态消费/清理（对撞残留形态）：重建唯一名重写再试，
                # 不让偶发扑空外逃成顶层兜底覆写（fail-closed 前的自愈面）。
                if attempt == 49:
                    raise
                tmp = _mk_and_dump()
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


# 生效条件：当 job_dir 与 payload 传入时，先尝试读 job_dir/result.json——存在且可解析为 dict 且 ok 为 True（成功终态在位）时不动它，log(job_dir,...) 留痕「成功终态在位，兜底 error 改写被拒」并返回 False；文件缺失/不可解析/ok 非真时走 write_result 写入 payload 并返回 True；
def write_error_result(job_dir: str, payload: dict) -> bool:
    """main 兜底专用：error 终态不得覆写已成功终态（重投对撞保护，v10 N82）。

    攻击形态（动态复现）：rust 对无产物 job 重投使两个执行者并发跑同一
    job——落败者异常外逃进顶层 except，若照旧 write_result 会把对撞写者
    已落地的成功终态改写成 error 终态（成功被记死，数据丢失面）。本守卫
    在写 error 前回看现态：成功终态在位即拒写（log 诚实留痕）；error→
    error 更新不受限。退出码语义不变（本进程照实返回失败码）。
    """
    p = os.path.join(job_dir, "result.json")
    try:
        with open(p, encoding="utf-8") as f:
            prev = json.load(f)
    except (OSError, ValueError):
        prev = None
    if isinstance(prev, dict) and prev.get("ok") is True:
        log(job_dir, "成功终态已在位，兜底 error 改写被拒（重投对撞保护，"
                     "v10 N82）——本进程失败不影响已落地终态")
        return False
    write_result(job_dir, payload)
    return True


# 生效条件：root/cg/out 传入时，out 非 dict 或 ok/committed 非双真 → 原样返回（入队/负记忆/失败形态不经回读）；committed=true 时取 out["id"] 对应索引条目的 path 拼盘面路径，文件存在则 out 附 readback="ok" 原样返回，条目缺失或文件不存在 → 返回 ok=False、readback="missing"、「回读不一致」error（不冒充成功）；
def _write_readback(root: str, cg, out: dict) -> dict:
    """M3.1 工具层写后回读（2026-09-23 批次7）。

    write 响应 committed=true = 声称节点已落盘——盘面必须真有对应文件。
    设计依据：写后回读是 9·12（3 个 mdcg 实例并发回写，apply 留痕 7590
    vs 盘面 ~1036）的检测手段；本函数把「模型按提示词自觉回读」升级为
    「工具面结构拦截」——提示词纪律可被绕过，返回值门不可绕。
    验证资格：回读只读盘，不改任何状态——它无资格改写，只有资格证伪。
    """
    if not (isinstance(out, dict) and out.get("ok") and out.get("committed")):
        return out                 # DEFER 入队 / REJECT / 失败：无落盘声称，不拦
    nid = out.get("id")
    nodes = (getattr(cg, "index", None) or {}).get("nodes") or {}
    e = nodes.get(nid) if isinstance(nodes, dict) else None
    fpath = os.path.join(root, e["path"]) if e and e.get("path") else None
    if not fpath or not os.path.isfile(fpath):
        return {"ok": False, "id": nid, "readback": "missing", "error": (
            "回读不一致：write 声称已落盘（committed=true），但盘面无对应节点"
            "文件——拒绝冒充成功（M3.1 工具层防线，9·12 多写者病灶；"
            "请重试或上报，勿把本次当成功继续下游）")}
    out["readback"] = "ok"
    return out


# 生效条件：当 job_dir 传入时，以 UTF-8 打开 job_dir/spec.json 并返回 json.load(f) 的结果；打开/解析异常向上传播；
def read_spec(job_dir: str) -> dict:
    with open(os.path.join(job_dir, "spec.json"), encoding="utf-8") as f:
        return json.load(f)


# 生效条件：当 job_dir 为真且 os.path.isdir(job_dir) 为真时，entry 补默认 ts=round(time.time(),3) 后以 JSON 行追加到 job_dir/PROGRESS_FILE，写入 OSError 时只调用 log 不终杀；job_dir 为假值或不是目录时直接 no-op 返回；
def progress(job_dir: str | None, **entry) -> None:
    """追加一条进展（v0.4 §5.3：worker 只写自家 job 目录，零 git 依赖）。

    进展面是观测/交接通道——写失败只记 log，不终杀任务（诚实降级）。
    非真实目录（如单测传 job_id 字面量）直接 no-op，不污染工作区。
    """
    if not job_dir or not os.path.isdir(job_dir):
        return
    entry.setdefault("ts", round(time.time(), 3))
    try:
        with open(os.path.join(job_dir, PROGRESS_FILE), "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError as e:
        log(job_dir, f"进展写入失败（不阻塞任务）: {e}")


# 生效条件：当 head 以 _IMG_MAGIC 中某项开头时返回 'image:<fmt>'；否则 head[:4]==b'RIFF' 且 head[8:12]==b'WEBP' 返回 'image:webp'；否则 head 含 b'\x00' 返回 'binary'，不含返回 'text'；
def sniff_kind(head: bytes) -> str:
    """按魔数判类型：image:<fmt> | binary | text（零依赖，只吃文件头）。"""
    for magic, fmt in _IMG_MAGIC:
        if head.startswith(magic):
            return "image:" + fmt
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image:webp"
    return "binary" if b"\x00" in head else "text"


# 生效条件：当 path 传入并打开读前 32 字节 head 后，若 head 以 PNG 魔数开头则 seek16 读 8 字节，长度 8 返回大端 (宽,高) 否则 (None,None)；若 head[:3]==b'GIF' 则 seek6 读 4 字节，长度 4 返回小端 (宽,高) 否则 (None,None)；若 head[:2]==b'BM' 则 seek18 读 8 字节，长度 8 返回小端有符号绝对值 (宽,高) 否则 (None,None)；若 head[:4]==b'RIFF' 且 head[8:12]==b'WEBP' 则返回 _webp_size(f)；若 head[:2]==b'\xff\xd8' 则返回 _jpeg_size(f)；其余返回 (None,None)；
def image_size(path: str) -> tuple:
    """零依赖读图像尺寸 (w, h)；未知格式返回 (None, None)（诚实，不猜）。

    覆盖 PNG(IHDR) / JPEG(SOFn) / GIF / BMP / WEBP(VP8X·VP8 ·VP8L)。
    """
    with open(path, "rb") as f:
        head = f.read(32)
        if head.startswith(b"\x89PNG\r\n\x1a\n"):
            f.seek(16)
            b = f.read(8)
            if len(b) == 8:
                return int.from_bytes(b[:4], "big"), int.from_bytes(b[4:8], "big")
            return None, None
        if head[:3] in (b"GIF",):
            f.seek(6)
            b = f.read(4)
            if len(b) == 4:
                return (int.from_bytes(b[:2], "little"),
                        int.from_bytes(b[2:4], "little"))
            return None, None
        if head[:2] == b"BM":
            f.seek(18)
            b = f.read(8)
            if len(b) == 8:
                return (abs(int.from_bytes(b[:4], "little", signed=True)),
                        abs(int.from_bytes(b[4:8], "little", signed=True)))
            return None, None
        if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
            return _webp_size(f)
        if head[:2] == b"\xff\xd8":
            return _jpeg_size(f)
    return None, None


# 生效条件：当 f 可读且从偏移 2 起扫描段时，段码为 0xD8/0xD9/0xD0–0xD7 则继续扫描；遇 EOF/标记字节读不到/段长字段不足 2 字节/SOFn 段体不足 5 字节/非 SOFn 分支 seg<2 均返回 (None, None)；命中 SOFn（0xC0–0xCF 排除 0xC4/0xC8/0xCC）且读满 5 字节则返回 (body[3:5] 大端、body[1:3] 大端)；其余非 SOFn 段按 seg-2 继续 seek；
def _jpeg_size(f) -> tuple:
    """JPEG：扫段找 SOFn（C0–CF 去掉 C4/C8/CC），段内 精度1/高2/宽2。"""
    f.seek(2)
    while True:
        b = f.read(1)
        while b and b != b"\xff":
            b = f.read(1)
        if not b:
            return None, None
        m = f.read(1)
        while m == b"\xff":     # 填充字节
            m = f.read(1)
        if not m:
            return None, None
        code = m[0]
        if code in (0xD8, 0xD9) or 0xD0 <= code <= 0xD7:
            continue
        ln = f.read(2)
        if len(ln) < 2:
            return None, None
        seg = int.from_bytes(ln, "big")
        if 0xC0 <= code <= 0xCF and code not in (0xC4, 0xC8, 0xCC):
            body = f.read(5)
            if len(body) < 5:
                return None, None
            return (int.from_bytes(body[3:5], "big"),
                    int.from_bytes(body[1:3], "big"))
        if seg < 2:
            return None, None
        f.seek(seg - 2, os.SEEK_CUR)


# 生效条件：当 f 传入时，从偏移 12 读 4 字节 fmt：fmt==b'VP8X' 则 seek24 读 6 字节，长度 6 返回 (小端 b[:3]+1, 小端 b[3:6]+1)；fmt==b'VP8 ' 则 seek26 读 4 字节，长度 4 返回 (小端 b[:2]&0x3FFF, 小端 b[2:4]&0x3FFF)；fmt==b'VP8L' 则 seek21 读 4 字节，长度 4 返回 ((v&0x3FFF)+1, ((v>>14)&0x3FFF)+1)；其余或长度不足返回 (None,None)；
def _webp_size(f) -> tuple:
    """WEBP：VP8X / VP8 （有损）/ VP8L（无损）三形态；其它返回未知。"""
    f.seek(12)
    fmt = f.read(4)
    if fmt == b"VP8X":
        f.seek(24)
        b = f.read(6)
        if len(b) == 6:
            return (int.from_bytes(b[:3], "little") + 1,
                    int.from_bytes(b[3:6], "little") + 1)
    elif fmt == b"VP8 ":
        f.seek(26)
        b = f.read(4)
        if len(b) == 4:
            return (int.from_bytes(b[:2], "little") & 0x3FFF,
                    int.from_bytes(b[2:4], "little") & 0x3FFF)
    elif fmt == b"VP8L":
        f.seek(21)
        b = f.read(4)
        if len(b) == 4:
            v = int.from_bytes(b, "little")
            return (v & 0x3FFF) + 1, ((v >> 14) & 0x3FFF) + 1
    return None, None


# 生效条件：当 spec 与 job_dir 传入时，若 spec['system_prompt_from'] 去空白非空，则以 ref 绝对路径或 spec['workdir'] or os.getcwd() 拼接路径读取，读取 OSError 抛 SpecError，成功返回 (text.strip(), 'file:'+ref) 并 log job_dir；否则返回 (spec['system_prompt'] or '' 去空白, 'literal' 若该文本非空否则 'none')；
def resolve_system_prompt(spec: dict, job_dir: str) -> tuple:
    """系统提示词真源（Pi⑦⑥）：声明 system_prompt_from 则**每次执行重建**。

    取证结论：hive 每次 spawn 都由调用方重建 system_prompt（spec.json 是任务
    证据而非 Pi 所指「持久化会话状态」），故默认路径结构性已满足「不持久化」；
    唯一偏差窗口是 rust 侧 claimed 重投（崩溃恢复）复用旧 spec——声明 from 后
    该窗口也走真源重建。缺文件 fail-closed（SpecError）：明确失败优于静默用旧
    提示词。→ (prompt, source 标签)
    """
    ref = str(spec.get("system_prompt_from") or "").strip()
    if ref:
        path = ref if os.path.isabs(ref) else os.path.join(
            spec.get("workdir") or os.getcwd(), ref)
        try:
            with open(path, encoding="utf-8") as f:
                text = f.read()
        except OSError as e:
            raise SpecError(
                f"system_prompt_from 读取失败（fail-closed，不回落旧提示词）: "
                f"{path}: {e}")
        log(job_dir, f"系统提示词重建自 {path}（{len(text)} 字符）")
        return text.strip(), f"file:{ref}"
    literal = (spec.get("system_prompt") or "").strip()
    return literal, ("literal" if literal else "none")


# 生效条件：当传入 rel/path/job_dir/meta 时，先对 os.path.realpath(path) 调 _sensitive_read，命中敏感凭据（目录段/文件名/前缀族/.env 族/密钥扩展）则 meta["notes"] 追加并 log(job_dir,...)，返回 skipped="敏感凭据拒读" 标注块（不读正文、不拒整个 spawn）；未命中且 path 可被 open("rb") 读取首 BINARY_SNIFF_BYTES 字节并用 sniff_kind 分类时，text 分支用 utf-8 errors=replace 读全文并返回文本 context；image: 前缀分支取 image_size(path) 的 w/h（w/h 均为真才显示尺寸并可能 oversize，否则显示“尺寸未知”且 width/height 用“?”），累加 meta["images"]/["image_tokens"]、向 meta["notes"] 追加并 log(job_dir,...)，返回带 w/h/oversize 的图像 context；其余分支累加 meta["binaries"]、log(job_dir,...) 并返回不读正文的二进制 context；
def _context_block(rel: str, path: str, job_dir: str, meta: dict) -> str:
    """单个 context 块：文本读全文；图像/二进制只登记（Pi⑦④）。"""
    # P2-22 止血（v8 N69 / v10 / 2026-09-25 三次成立）：context_files 通道
    # 原先零检查——read_file 的四道防线（scope 白名单 / HIVE_READ_ROOTS /
    # _sensitive_read / PII 脱敏）在本通道不生效，编排者经 spawn 传
    # context_files=[私钥/.env 路径] 即可让全文随 user 消息发往
    # HIVE_API_BASE 外部网关。复用 tool_read_file 同款 _sensitive_read
    # （realpath 规范化后匹配）：命中不拒整个 spawn（其余块照常拼装），
    # 只把该文件替换为 skipped 标注块——诚实留痕可审计。
    why = _sensitive_read(os.path.realpath(path))
    if why:
        note = f"context {rel} 敏感凭据拒读跳过（{why}）——全文不进 LLM 上下文"
        meta["notes"].append(note)
        log(job_dir, "上下文块 " + note)
        return (f'<context path="{rel}" skipped="敏感凭据拒读">\n'
                f"（{why}——凭据类文件不进 LLM 上下文，本块已跳过；"
                "如有合法需要请走部署管理员显式通道。）\n</context>")
    with open(path, "rb") as f:
        head = f.read(BINARY_SNIFF_BYTES)
    kind = sniff_kind(head)
    size = os.path.getsize(path)
    if kind == "text":
        # P2-8（批次 31）：读入内存前查大小——超大文本截断到
        # CONTEXT_TEXT_MAX（防 OOM；呈现量仍由预算机制收紧）。
        with open(path, encoding="utf-8", errors="replace") as f:
            content = f.read(CONTEXT_TEXT_MAX)
        note = ("\n<!-- truncated: > CONTEXT_TEXT_MAX -->"
                if size > CONTEXT_TEXT_MAX else "")
        return f'<context path="{rel}">\n{content}{note}\n</context>'
    if kind.startswith("image:"):
        w, h = image_size(path)
        dim = f"{w}x{h}" if w and h else "尺寸未知"
        oversize = bool(w and h and max(w, h) > IMAGE_MAX_DIM)
        meta["images"] += 1
        meta["image_tokens"] += IMAGE_EST_TOKENS
        note = (f"图像 {rel} {dim} bytes={size} 折算 {IMAGE_EST_TOKENS} tokens"
                + ("（超单边上限，需先压缩）" if oversize else "（未压缩）"))
        meta["notes"].append(note)
        log(job_dir, "上下文块 " + note)
        advice = (
            f"当前 {dim} 超过单边上限 {IMAGE_MAX_DIM}px——请先压缩后再提交；"
            "本执行器零依赖，不自动缩放。"
            if oversize else
            "尺寸在上限内（未压缩）；像素级分析请交由多模态模型/工具链处理。")
        return (
            f'<context path="{rel}" kind="image" format="{kind.split(":")[1]}" '
            f'width="{w or "?"}" height="{h or "?"}" bytes="{size}" '
            f'compressed="false" oversize="{str(oversize).lower()}" '
            f'est_tokens="{IMAGE_EST_TOKENS}">\n'
            f"（执行器不读图像内容（Pi⑦④ 护栏）：单张按 {IMAGE_EST_TOKENS} tokens "
            f"计入预算。{advice}）\n</context>")
    meta["binaries"] += 1
    log(job_dir, f"上下文块 二进制 {rel} bytes={size}（不读入正文）")
    return (f'<context path="{rel}" kind="binary" bytes="{size}">\n'
            "（二进制文件不读入正文，避免乱码污染上下文；"
            "如需内容请先转文本或改走工具通道。）\n</context>")


# 生效条件：当 spec 与 job_dir 传入时，以 spec.get('user_prompt','') 为基，base=spec.get('workdir') or os.getcwd()，对 spec.get('context_files') or [] 每个 rel 解析路径并调 _context_block，OSError 时替换为 error 块并 log，meta['contexts'] 计数；有 ctx_blocks 时 prompt=块拼接+'\n\n'+user_prompt，否则仅 user_prompt；resolve_system_prompt 返回 sys_prompt 非空则加 system 消息，最后加 user 消息并返回 (messages, meta)；
def build_messages(spec: dict, job_dir: str) -> tuple:
    """→ (messages, meta)；meta 记上下文块统计与图像预算折算（Pi⑦④）。

    meta 键：contexts / images / image_tokens / binaries / notes /
    system_prompt_source。
    """
    user_prompt = spec.get("user_prompt", "")
    ctx_blocks = []
    meta = {"contexts": 0, "images": 0, "image_tokens": 0, "binaries": 0,
            "notes": []}
    base = spec.get("workdir") or os.getcwd()
    for rel in spec.get("context_files") or []:
        path = rel if os.path.isabs(rel) else os.path.join(base, rel)
        try:
            block = _context_block(rel, path, job_dir, meta)
        except OSError as e:
            log(job_dir, f"context 读取失败 {path}: {e}")
            block = f'<context path="{rel}" error="读取失败: {e}"></context>'
        ctx_blocks.append(block)
        meta["contexts"] += 1
    prompt = ("\n\n".join(ctx_blocks) + "\n\n" + user_prompt) if ctx_blocks else user_prompt
    messages = []
    sys_prompt, src = resolve_system_prompt(spec, job_dir)
    meta["system_prompt_source"] = src
    if sys_prompt:
        messages.append({"role": "system", "content": sys_prompt})
    messages.append({"role": "user", "content": prompt})
    return messages, meta


_CJK_RANGES = (
    (0x4E00, 0x9FFF),  # CJK 统一表意
    (0x3400, 0x4DBF),  # 扩展 A
    (0xF900, 0xFAFF),  # 兼容表意
    (0x3000, 0x303F),  # CJK 标点
    (0xFF00, 0xFFEF),  # 全角形式
)


# 生效条件：当 text 为假值（空串）返回 0；否则逐字符按 _CJK_RANGES 统计 cjk 与 other，返回 cjk+(other+3)//4；
def est_tokens(text: str) -> int:
    """保守 token 估算——**偏高估**：宁可提前拦截，不放行超限输入白跑 API。

    CJK 1 字 ≈ 1 token（DeepSeek 中文实际约 1.6 字/token，此处高估约 60%），
    其余字符 4 个 ≈ 1 token。仅用于预算判断，不是精确计数。
    """
    if not text:
        return 0
    cjk = other = 0
    for ch in text:
        cp = ord(ch)
        if any(lo <= cp <= hi for lo, hi in _CJK_RANGES):
            cjk += 1
        else:
            other += 1
    return cjk + (other + 3) // 4


LINGSHU_OPS_ALLOW = ("route", "read", "write")
VERIFICATION_BASIS_ALLOW = ("compiler", "test", "measurement", "formal_proof",
                            "data", "textbook", "public_kb", "other")
TOOL_MSG_MAX_CHARS = 4000    # 工具结果回喂模型的单条截断（防上下文爆炸）
TOOL_MSG_TAIL_CHARS = 1200   # 截断时保尾长度（Pi⑦③：错误/收尾信息在尾部）
TOOL_DUMP_MAX_CHARS = 200000  # 工具结果**落盘**上限（2026-09-20 v15-3：磁盘面同样封顶）
DEFAULT_MAX_TOOL_ROUNDS = 5

# ------------------------------------------------- 读放开 · 写严格（2026-09-19 裁定）
# 不对称原则（使用者裁定，勿对称化）：**读放开，写严格管理**。
#   读 = read_file 工具：worker 推理中途可动态读本地文件/目录（含清单发现），
#        默认无路径白名单（读放开）；部署侧可用 HIVE_READ_ROOTS 收窄。
#   写 = 唯一写路径是 lingshu_cg op=write，过库层令牌（recorder，不可提权）+
#        校验闸门（DEFER 入审核队列 / REJECT 负记忆）；执行器**不提供任何
#        写工具**——本文件新增工具时不得引入落盘/改状态能力（见 test_exec_tools
#        的「只读面」断言：schema 无任何写参数）。
# 为什么不对称：读错的代价是「一次没读到」——可重试、可回放（tool_trace 记
# 路径）；写错的代价是污染长期记忆——不可逆、会传播给后续所有检索。
READ_MAX_LINES = 2000        # 单次默认读行数（offset/limit 分页续读）
READ_HARD_LINES = 20000      # 单次行数硬上限（模型申请不得超过）
READ_MAX_CHARS = 60000       # 单次默认字符上限（约 1.5 万 tokens）
READ_HARD_CHARS = 400000     # 单次字符硬上限（模型申请不得超过）
READ_DIR_MAX = 300           # 目录清单最多返回条目数（超出截断并标记）
READ_FULL_BYTES = 2000000    # 文件大于此值：不再统计精确行总数（诚实记 None）

# ---------------------------------------------------------------- Pi⑦ 上下文护栏
PROGRESS_FILE = "progress.jsonl"   # 进展卡（v0.4 §5.3 换人续跑的交接面）
BINARY_SNIFF_BYTES = 8192          # 类型嗅探只吃文件头，整文件不进内存
IMAGE_MAX_DIM = 2000               # 图像单边像素上限（超出=需先压缩再提交）
IMAGE_EST_CHARS = 4800             # 单张图像的等价字符数（Pi 口径）
IMAGE_EST_TOKENS = (IMAGE_EST_CHARS + 3) // 4   # 沿用 est_tokens 4:1 折算 = 1200

_IMG_MAGIC = (
    (b"\x89PNG\r\n\x1a\n", "png"),
    (b"\xff\xd8\xff", "jpeg"),
    (b"GIF87a", "gif"),
    (b"GIF89a", "gif"),
    (b"BM", "bmp"),
)


class SpecError(Exception):
    """规格错（fail-closed）：由 main 以 EXIT_SPEC 收口，不静默降级。"""


# 生效条件：给定 model 与 base，已知网关按前缀配对裁决——base 含 api.deepseek.com 须 model 以 deepseek 开头、base 含 bigmodel.cn 须 model 以 glm 开头，错配返回人话描述（含标准出处），未知网关（两者都不含）返回 None 放行；model 为空返回 None（缺 model 由 rust 侧必填校验拦截，不重复报）。
def model_base_mismatch(model: str, base: str) -> str | None:
    """model↔base 配对前置校验（子代理配置标准 v0.5 §1）。

    为什么在执行器而非 API：错配在 API 侧 400（标准 §1 实测）——任务已经过
    调度、claim、spawn 全链路才炸，白烧一次调度并产出一份 error 任务
    （2026-09-23 归因：jobs/12 个 error 中 1 个即此，h1790085459807）。
    左移到执行边界 fail-fast：提交即刻收到人话错误，不触网。
    未知网关刻意放行：配对表只覆盖已知厂商 base，自定义网关不误伤。
    """
    m = (model or "").strip()
    b = (base or "").lower()
    if not m:
        return None
    if "api.deepseek.com" in b and not m.startswith("deepseek"):
        return (f"deepseek base（{base}）不接受模型 {m}（须 deepseek-*）；"
                "智谱模型请配 open.bigmodel.cn base（子代理配置标准 v0.5 §1）")
    if "bigmodel.cn" in b and not m.startswith("glm"):
        return (f"智谱 base（{base}）不接受模型 {m}（须 glm-*）；"
                "deepseek 模型请配 api.deepseek.com base（子代理配置标准 v0.5 §1）")
    return None

LINGSHU_TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "lingshu_cg",
        "description": (
            "灵枢认知图工具（长期记忆）。op=route：按任务意图检索相关记忆与"
            "建议能力，动手前先查；op=read：按 query 读领域知识（或 node_id "
            "定点读单节点全文）；op=write：写入一条记忆（格式：【内容】…"
            "【原因】…【位置】…【验证】…，只记核心修改）。写入过校验闸门："
            "返回 committed=false 且 moved_to=review_queue / rejected 是设计"
            "行为（DEFER 入审核队列待裁决 / 内容未过审核），不是故障，勿重试。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "op": {"type": "string",
                       "enum": list(LINGSHU_OPS_ALLOW)},
                "intent": {"type": "string",
                           "description": "op=route 必填：任务意图关键词"},
                "query": {"type": "string",
                          "description": "op=read 必填（无 node_id 时）：领域关键词"},
                "k": {"type": "integer",
                      "description": "返回条数上限（route 默认 5，read 默认 20）"},
                "node_id": {"type": "string",
                            "description": "op=read 可选：定点读单节点全文"},
                "content": {"type": "string",
                            "description": "op=write 必填：记忆正文"},
                "content_kind": {"type": "string",
                                 "description": "op=write：内容种类，如 work_done/text"},
                "layer": {"type": "string",
                          "description": "op=write：knowledge/procedural/contextual"},
                "tags": {"type": "array", "items": {"type": "string"}},
                "importance": {"type": "number"},
                "verification_basis": {
                    "type": "string",
                    "enum": list(VERIFICATION_BASIS_ALLOW),
                    "description": "op=write：验证基底，缺省由审核闸门判定"},
                "valid_from": {
                    "type": "string",
                    "description": "op=write：双时间轴起点（ISO8601，如 2026-01-01）。"
                                   "不填=现行为（写者声明，系统不代推导）；"
                                   "收口类结论建议填当下"},
                "valid_until": {
                    "type": "string",
                    "description": "op=write：双时间轴终点（ISO8601）。时效性结论"
                                   "（版本号/配额/限时政策类）应填——过期后 validity"
                                   " 过滤不再召回；长期知识不填"},
            },
            "required": ["op"],
        },
    },
}

WEB_SEARCH_TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": "网页搜索：返回与 query 相关的结果列表（标题/链接/摘要）。"
                       "用于查公开事实、时效信息；与 lingshu_cg（私有记忆）互补。",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string",
                          "description": "搜索关键词"},
                "count": {"type": "integer",
                          "description": "结果条数（默认 5，上限 10）"},
            },
            "required": ["query"],
        },
    },
}

READ_FILE_TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "read_file",
        "description": (
            "读本地文件（只读，无副作用，全路径开放）。path 指向文件 → 返回"
            "内容：默认最多 2000 行 / 60000 字符，用 offset/limit 分页续读"
            "（返回的 offset 即首行行号，可直接引用行号）。path 指向目录 → "
            "返回条目清单（名字/类型/字节数），用于发现文件。图像与二进制不"
            "返回正文，只给类型与字节数（诚实，不猜内容）。路径不存在、或"
            "被部署侧 HIVE_READ_ROOTS 白名单拦下时返回 ok=false——照实上报，"
            "**不得编造文件内容**。本工具只读：写走 lingshu_cg op=write。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "文件或目录路径。相对路径基准 = spec.workdir"
                                   "（缺省 = 执行器进程 cwd）"},
                "offset": {"type": "integer",
                           "description": "起始行号，1-based（默认 1）"},
                "limit": {"type": "integer",
                          "description": f"最多读多少行（默认 {READ_MAX_LINES}，"
                                         f"硬上限 {READ_HARD_LINES}）"},
                "max_chars": {"type": "integer",
                              "description": f"字符上限（默认 {READ_MAX_CHARS}，"
                                             f"硬上限 {READ_HARD_CHARS}）"},
            },
            "required": ["path"],
        },
    },
}

TOOL_SCHEMAS = {
    "lingshu_cg": LINGSHU_TOOL_SCHEMA,
    "web_search": WEB_SEARCH_TOOL_SCHEMA,
    "read_file": READ_FILE_TOOL_SCHEMA,
}

# ---------------------------------------------------------------- 插件式扩展口
# 两个注册口，均为**默认零行为变更**（不注册 = 与历史版本逐位一致）：
#   register_tools   追加工具（编排器 orch.py 的 spawn_subtask/poll_subtasks/...）
#   set_principal_factory  替换 lingshu_cg 的身份（默认 recorder 子代理 → 派生
#                    令牌编排器）——权限由库层令牌裁决，本口只换身份不改闸门。
# 为什么不 monkeypatch：工具名过滤与身份构造都是模块内引用，patch 会静默失效；
# 显式注册口是唯一自洽的扩展面（对齐 md_cg/writepipe 的拦截器链精神）。
_EXTRA_TOOLS: dict = {}          # name -> {"schema": dict, "handler": callable}
_PRINCIPAL_FACTORY = None        # (args, job_id) -> Principal
_TOOL_OPS_ALLOW = LINGSHU_OPS_ALLOW   # 工具侧前置白名单（注册身份时可同步收窄）
_CUR_ORCH_JOB = ""               # 父编排任务 id（orch.py spawn 时写入 spec.orch_job；
                                 # main() 读入——M3.2 来源行的「父任务」字段来源）


# 生效条件：当 schemas 为真 dict 时，遍历其 items，将每个 name 经 str() 后以 {'schema': schema, 'handler': handler} 写入 _EXTRA_TOOLS，覆盖同名；schemas 为假值（None/空）时不注册任何工具；
def register_tools(schemas: dict, handler) -> None:
    """追加工具：schemas={name: openai_function_schema}，handler(name,args,job_id,...)->dict。

    同名覆盖既是显式意图（编排器可换掉 lingshu_cg 实现），也是本口唯一冲突面
    ——故此处打印无警告、由调用方自负；run_with_tools 的 spec.tools 白名单
    仍是第二道过滤（模型只能调用 spec 里显式列出的工具）。
    """
    for name, schema in (schemas or {}).items():
        _EXTRA_TOOLS[str(name)] = {"schema": schema, "handler": handler}


# 生效条件：当 fn 传入时赋给 _PRINCIPAL_FACTORY；ops_allow 为真值则 _TOOL_OPS_ALLOW=tuple(ops_allow)，否则（None/空）回落 LINGSHU_OPS_ALLOW；
def set_principal_factory(fn, ops_allow=None) -> None:
    """注入 lingshu_cg 的身份工厂（None 恢复默认 recorder）。

    ops_allow：工具侧前置 op 白名单（None=保持默认 route/read/write）。仅为
    「让模型当场看到越权并自修」的可用性问题，**真正的闸门在库层令牌**——
    伪造本白名单不放行任何库层被拒的操作。
    """
    global _PRINCIPAL_FACTORY, _TOOL_OPS_ALLOW
    _PRINCIPAL_FACTORY = fn
    _TOOL_OPS_ALLOW = tuple(ops_allow) if ops_allow else LINGSHU_OPS_ALLOW


# 生效条件：无 required 形参；返回 dict(TOOL_SCHEMAS) 并用 _EXTRA_TOOLS 中每个 name 的 rec['schema'] 覆盖同名键；
def all_schemas() -> dict:
    """可见工具 schema 全集（内置 + 注册）。"""
    out = dict(TOOL_SCHEMAS)
    for name, rec in _EXTRA_TOOLS.items():
        out[name] = rec["schema"]
    return out


# 生效条件：无 required 形参；当 MDCG_HOME 去空白非空时 home=该值，否则 home=__file__ 的祖父目录；若 home 不在 sys.path 则插入开头，随后导入 md_cg 相关模块并返回 home；
def _md_cg_import():
    """import md_cg（MDCG_HOME 优先，缺省=执行器父目录——同仓分发零配置）。"""
    home = os.environ.get("MDCG_HOME", "").strip()
    if not home:
        home = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if home not in sys.path:
        sys.path.insert(0, home)
    from md_cg.mdcos import MdCGSecure          # noqa: F401  载入即校验
    from md_cg.mcp_server import _cg_dispatch   # noqa: F401
    from md_cg.security import Principal        # noqa: F401
    return home


# 生效条件：当 args["op"]（args.get("op") 或空串）在 _TOOL_OPS_ALLOW 内，且 op != "write" 或 verification_basis 为 None 或在 VERIFICATION_BASIS_ALLOW 内，且 MDCG_ROOT 去空格非空或 mdcg_root 去空格非空（两者皆空返回未配置错误），并成功导入 md_cg 且 _PRINCIPAL_FACTORY 为 None 或 _PRINCIPAL_FACTORY(args, job_id) 返回非 None（返回 None 则 fail-closed 拒绝），则给 principal 无 session 时设 f"hive_job_{job_id}"，经 _cg_dispatch(cg,args) 返回 dict 或包成 {"ok": True, "data": out}；op 不在白名单、write 的 vb 非法、root 空、principal 为 None、或任一异常时返回相应 {"ok": False,...}；
def tool_lingshu_cg(args: dict, job_id: str, mdcg_root: str = None) -> dict:
    """灵枢认知图工具：复用 MCP 面同一 dispatch（op 白名单 route/read/write）。

    权限边界（硬编码，spec 不可改变）：recorder 角色 + can_admin=False——
    子代理写入过校验闸门（DEFER 入审核队列 / REJECT 负记忆），裁决权留给
    设计者（写入者不得自裁自决）。会话隔离：principal.session=hive_job_<id>。
    root 来源：env MDCG_ROOT 优先（serve 级管理员控制），spec.mdcg_root 兜底
    （提交方显式指定——如任务级隔离用临时图）。
    """
    op = (args.get("op") or "").strip()
    if op not in _TOOL_OPS_ALLOW:
        return {"ok": False, "error": f"op={op!r} 未对当前身份开放（允许："
                f"{', '.join(_TOOL_OPS_ALLOW)}）"}
    if op == "write":
        # 防卡队列：非法 verification_basis（自由文本）会在设计者 accept 落盘
        # 时才炸（入队侧不校验）——执行器侧前置拦截，让模型当场修正。
        vb = args.get("verification_basis")
        if vb is not None and vb not in VERIFICATION_BASIS_ALLOW:
            return {"ok": False, "error": f"verification_basis={vb!r} 非法（允许："
                    f"{', '.join(VERIFICATION_BASIS_ALLOW)}）；请修正后重试或省略该参数"}
        # —— M3.2 写通道双轨制（D3 裁决，2026-09-23 批次3）——
        # 仅拦 worker（无身份工厂=默认 recorder 过程性直写）；编排者（注册身份）
        # 的收口写不受限（knowledge 归编排者，M3.1 写后回读已约束）。
        if _PRINCIPAL_FACTORY is None:
            layer = str(args.get("layer") or "").strip()
            if layer != "contextual":
                return {"ok": False, "error": (
                    f"worker 直写仅限 layer=contextual（过程性直写，got {layer!r}）——"
                    "knowledge 等收口写归编排者（双轨制 D3；过程结论由编排者收口固化）")}
            # 冲突留痕不停工：worker 写固定 on_conflict=record（模型不传/传错均覆写）
            args["on_conflict"] = "record"
            # 修改依据来源行（D3）：content 未声明时自动注入，冲突可回溯到具体 job
            content = str(args.get("content") or "")
            if "来源 job=" not in content:
                src = (f"\n# 生效条件：来源 job={job_id}；"
                       f"父任务={_CUR_ORCH_JOB or 'none'}")
                args["content"] = content + src
    root = (os.environ.get("MDCG_ROOT", "").strip() or (mdcg_root or "").strip())
    if not root:
        return {"ok": False, "error": "lingshu_cg 未配置：执行器 env 缺 MDCG_ROOT"
                "（认知图根目录）。部署侧在 serve 环境注入后重启 hive serve。"}
    home = None
    try:
        home = _md_cg_import()
        from md_cg.mdcos import MdCGSecure
        from md_cg.security import Principal
        if _PRINCIPAL_FACTORY is not None:
            # 注册身份（编排器派生令牌）：身份与权限完全由调用方给定，本口
            # 不做任何放大——Principal 字段即库层闸门的输入。工厂返回 None
            # 时 fail-closed，**不降级**为默认子代理身份（静默降级会让
            # 「裁决」权限意图落空且不可见，属第4条明令禁止的静默错执行）。
            principal = _PRINCIPAL_FACTORY(args, job_id)
            if principal is None:
                return {"ok": False, "error": "身份工厂未返回 Principal"
                        "（令牌缺失/不可用/lint 未过）—— fail-closed 拒绝执行"}
        else:
            # 读权限分级（批次 27，表述经使用者 2026-09-24 澄清修正）：子代理
            # 默认密级 internal——可读 public/internal，拒读 private 与 secret。
            # private 的体系语义是**错误处置标记**（错误相关/待排查内容限制向
            # 平级扩散，非个人隐私）——worker 属平级消费方，对错误标记内容
            # 限读正是该标记的目的；错误处置链路（设计者/上级节点/验证单元）
            # 必读不受此限。编排器派生令牌（_PRINCIPAL_FACTORY）不受此默认
            # 影响——身份由调用方给定。
            principal = Principal(actor="hive-worker", clearance="internal",
                                  can_write=True, can_admin=False, role="recorder",
                                  auth_mode="hive-exec")
        if not getattr(principal, "session", None):
            principal.session = f"hive_job_{job_id}"
        cg = MdCGSecure(root, principal=principal)
        from md_cg.mcp_server import _cg_dispatch
        out = _cg_dispatch(cg, args)
        # M3.1 工具层写后回读（批次7）：write 声称已落盘（committed=true）时，
        # 盘面必须真有该节点文件——提示词级回读纪律（9136fa9）可被模型绕过，
        # 结构拦截不依赖自觉（9·12 病灶：内存索引与盘面脱节，落盘率 ~14%）。
        if (isinstance(out, dict) and str(args.get("op") or "") == "write"):
            out = _write_readback(root, cg, out)
        # V21-7（批次 34，外部报告）：认知图是长期记忆主通道（回喂 LLM 频率
        # 最高），返回体此前不过 PII 脱敏（_redact_pii 仅 read_file 单点）——
        # op=read 的节点原文（含手机号等）直接进上下文。返回体递归脱敏：
        # dict/list 逐层下探，字符串值统一过 _redact_pii（与 read_file 同防线，
        # 兑现「设计者与子代理同防线」的既有注释承诺）。
        if isinstance(out, dict):
            out = _redact_deep(out)
        return out if isinstance(out, dict) else {"ok": True, "data": out}
    except Exception as e:  # noqa: BLE001 —— 工具异常回喂模型自修，不终杀任务
        return {"ok": False, "error": f"{type(e).__name__}: {e}",
                "mdcg_home": home}


# 生效条件：当 args["query"]（args.get("query") or ""）去空格非空时，count 取 int(args.get("count") or 5) 后 max(1,min(...,10))（count 缺键/None/0/空串等假值回落 5），backend 取 env HIVE_WEB_SEARCH 去空格小写，为空则取 backend_override 去空格小写，仍为空则 "zhipu"；backend 为 "zhipu" 返回 _ws_zhipu(query,count,backend)，为 "duckduckgo" 返回 _ws_duckduckgo(query,count,backend)，否则返回未知后端错误；query 为空返回 query 必填；HTTPError 返回 HTTP 错误，其他异常返回类名+消息；
def tool_web_search(args: dict, backend_override: str = None) -> dict:
    """网页搜索。zhipu：/web_search 端点（base/key 独立 env，见 _ws_zhipu）；
    duckduckgo：零 key 兜底（html.duckduckgo.com 抓取解析，弱依赖可被墙）。
    后端选择：env HIVE_WEB_SEARCH 优先，spec.web_search_backend 兜底。"""
    query = (args.get("query") or "").strip()
    if not query:
        return {"ok": False, "error": "query 必填"}
    count = max(1, min(int(args.get("count") or 5), 10))
    backend = (os.environ.get("HIVE_WEB_SEARCH", "").strip().lower()
               or (backend_override or "").strip().lower() or "zhipu")
    try:
        if backend == "zhipu":
            return _ws_zhipu(query, count, backend)
        if backend == "duckduckgo":
            return _ws_duckduckgo(query, count, backend)
        return {"ok": False, "error": f"HIVE_WEB_SEARCH={backend!r} 未知后端"
                "（允许：zhipu | duckduckgo）"}
    except urllib.error.HTTPError as e:
        try:
            detail = e.read().decode("utf-8", errors="replace")[:500]
        except Exception:  # noqa: BLE001
            detail = ""
        return {"ok": False, "backend": backend, "error": f"HTTP {e.code}: {detail}"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "backend": backend,
                "error": f"{type(e).__name__}: {e}"}


ZHIPU_SEARCH_BASE = "https://open.bigmodel.cn/api/paas/v4"


# 生效条件：当 query/count/backend 传入时，api_base=HIVE_WEB_SEARCH_BASE 去空白非空否则 ZHIPU_SEARCH_BASE，再去尾斜杠；api_key=HIVE_WEB_SEARCH_KEY 去空白非空否则 HIVE_API_KEY；若 api_key 假值返回 {'ok':False,...,'error':'搜索密钥未设置'}；否则 POST api_base/web_search，timeout=30，解析 search_result 前 count 项并返回 {'ok':True,...,'results':items}；
def _ws_zhipu(query: str, count: int, backend: str) -> dict:
    # 端点与 LLM base 解耦（实测教训：HIVE_API_BASE 常指向 LLM 中转网关，
    # 只代理 chat/completions——锚上去 web_search 必 404）。搜索端点独立：
    # HIVE_WEB_SEARCH_BASE 缺省智谱官方；key 缺省回落执行器密钥。
    api_base = (os.environ.get("HIVE_WEB_SEARCH_BASE", "").strip()
                or ZHIPU_SEARCH_BASE).rstrip("/")
    api_key = (os.environ.get("HIVE_WEB_SEARCH_KEY", "").strip()
               or os.environ.get("HIVE_API_KEY", ""))
    if not api_key:
        return {"ok": False, "backend": backend,
                "error": "搜索密钥未设置（HIVE_WEB_SEARCH_KEY 或 HIVE_API_KEY）"}
    req = urllib.request.Request(
        f"{api_base}/web_search",
        data=json.dumps({"search_engine": "search_std", "search_query": query},
                        ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {api_key}"},
        method="POST")
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read(RESP_MAX_BYTES).decode("utf-8"))
    items = []
    for r in (data.get("search_result") or [])[:count]:
        items.append({"title": (r.get("title") or "")[:200],
                      "url": r.get("link") or r.get("url") or "",
                      "snippet": (r.get("content") or "")[:300],
                      "media": r.get("media") or ""})
    return {"ok": True, "backend": backend, "query": query, "results": items}


_DDG_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) Gecko/20100101 "
           "Firefox/125.0")


# 生效条件：当 query/count/backend 传入时，请求 https://html.duckduckgo.com/html/?q=quote(query)，以 result__a 正则取前 count 个命中，逐个提取 title、uddg 解码后的 url、本结果块内最近 snippet，返回 {'ok':True,'backend':backend,'query':query,'results':items}；请求/解析异常向上传播；
def _ws_duckduckgo(query: str, count: int, backend: str) -> dict:
    import html
    import re
    url = ("https://html.duckduckgo.com/html/?q="
           + urllib.request.quote(query))
    req = urllib.request.Request(url, headers={"User-Agent": _DDG_UA})
    with urllib.request.urlopen(req, timeout=30) as resp:
        page = resp.read(RESP_MAX_BYTES).decode("utf-8", errors="replace")
    a_re = re.compile(
        r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>')
    snip_re = re.compile(
        r'<a[^>]+class="[^"]*result__snippet[^"]*"[^>]*>(.*?)</a>', re.S)
    hits = list(a_re.finditer(page))[:count]
    items = []
    for i, m in enumerate(hits):
        href, title = m.group(1), re.sub(r"<[^>]+>", "", m.group(2))
        # DDG 重定向链接 //duckduckgo.com/l/?uddg=<urlencoded>
        if "uddg=" in href:
            href = urllib.request.unquote(
                href.split("uddg=")[-1].split("&")[0])
        snippet = ""
        nxt = hits[i + 1].start() if i + 1 < len(hits) else len(page)
        sm = snip_re.search(page, m.end(), nxt)  # 摘要归属：本结果块内最近
        if sm:
            snippet = html.unescape(re.sub(r"<[^>]+>", "", sm.group(1)))
        items.append({"title": html.unescape(title)[:200], "url": href,
                      "snippet": snippet[:300], "media": ""})
    return {"ok": True, "backend": backend, "query": query, "results": items}


# 生效条件：当 env HIVE_READ_ROOTS 去空白非空时，按 os.pathsep 切分、每项 expanduser+realpath 后返回非空项 tuple（读被收窄到这些根）；未设置或全空返回空 tuple（= 读放开，默认）；
def read_roots() -> tuple:
    """读路径白名单（部署开关）。未设置 = 读放开（默认，2026-09-19 裁定）。

    只影响 read_file 的可读范围，不影响 lingshu_cg（认知图有自己的 root）。
    空值语义刻意区分「未设置」与「设置为空」：前者放开，后者同样放开——
    要收窄必须给出至少一个真实目录（避免误设空串导致静默全放开又以为锁了）。
    """
    raw = (os.environ.get("HIVE_READ_ROOTS") or "").strip()
    if not raw:
        return ()
    roots = []
    for p in raw.split(os.pathsep):
        p = p.strip()
        if p:
            roots.append(os.path.realpath(os.path.expanduser(p)))
    return tuple(roots)


# 生效条件：当 path 与 root 均为 realpath 规范化绝对路径时，path 等于 root 或以 root + os.sep 开头返回 True，否则 False；
def _under(path: str, root: str) -> bool:
    """路径归属判定（前缀比较，防 /a/bc 被 /a/b 误判）。"""
    return path == root or path.startswith(root.rstrip(os.sep) + os.sep)


# P1-6 增量（批次 26，外部审查报告建议 3）：敏感凭据路径拒读——与「默认放开」
# 的 2026-09-19 使用者裁定**不冲突**（增量黑名单，非改默认）：read_file 的内容
# 会随 tool 消息发往 HIVE_API_BASE 外部网关，SSH 私钥 / 云凭据 / 浏览器
# Cookie 库无论根约束如何都**不该**进上下文。匹配在斜杠归一后做（Windows
# 反斜杠兼容）；目录段整段匹配（防 ~/.sshx 误伤）、文件名前缀/精确匹配。
_SENSITIVE_DIR_SEGMENTS = (".ssh", ".aws", ".gcloud", ".azure", ".kube",
                           ".gnupg", ".docker", ".netrc")
_SENSITIVE_FILE_NAMES = ("id_rsa", "id_ed25519", "id_ecdsa", "id_dsa",
                         ".netrc", ".htpasswd", ".npmrc", ".pypirc",
                         "credentials", "credentials.json",
                         "config.local.json",
                         "cookies.sqlite", "cookies.sqlite-journal")


# 生效条件：real 为 realpath 规范化后的绝对路径；归一斜杠小写后，任一父目录段属 _SENSITIVE_DIR_SEGMENTS、文件名精确命中 _SENSITIVE_FILE_NAMES（含 config.local.json——N141，批次 49）、或命中 V21-8 族匹配（id_rsa/id_ed25519/id_ecdsa/id_dsa/service-account 前缀族、名字含 credential/creds、.env 后缀族——堵「改名/加后缀即免检」缺口，V21 报告 8 类实测样本全覆盖；.token 后缀族——N141 补部署令牌文件 orch.token/designer.token）、或以 credentials/access_tokens 前缀命中、或文件名以 .env 开头/以 .env/.pem/.key/.p12/.pfx/.kdbx/.token 结尾时返回原因说明串，否则返回 None。
def _sensitive_read(real: str) -> str | None:
    """命中敏感路径返回原因说明，安全路径返回 None。"""
    norm = real.replace("\\", "/").lower()
    name = norm.rsplit("/", 1)[-1]
    segments = norm.split("/")
    for seg in segments[:-1]:
        if seg.lower() in _SENSITIVE_DIR_SEGMENTS:
            return f"敏感凭据目录（{seg}/）"
    for cand in _SENSITIVE_FILE_NAMES:
        if name == cand or (cand == "credentials" and name.startswith(
                ("credentials", "access_tokens"))):
            return f"敏感凭据文件（{name}）"
    # V21-8（批次 34，外部报告）：族匹配——精确名黑名单「改名/加后缀即免检」
    # （id_rsa.bak / prod.env / creds.json / aws_credentials /
    # service-account.json 等 8 类实测正文泄露）。目录段思路扩展到文件名：
    # 私钥名前缀族 / 凭据词子串 / .env 后缀族。误伤可走部署管理员显式通道
    # （拒读文案已注明）。
    if name.startswith(("id_rsa", "id_ed25519", "id_ecdsa", "id_dsa",
                        "service-account")) or "credential" in name \
            or "creds" in name:
        return f"敏感凭据文件（{name}）"
    # 密钥文件扩展与 dot-env 家族（.env / .env.local / prod.env / prod.pem…）
    # N141（批次 49，2026-09-26）：后缀族补 .token——部署令牌文件
    # （orch.token / designer.token，orch.py tokens 通道产物）此前放行；
    # 同时精确名补 config.local.json（serve 部署配置，serve_start.py
    # DEFAULT_CONFIG，api_key 所在）——子代理 read_file / 编排者
    # context_files 一句话即可外发外部网关，两者是默认部署的最后一道闸。
    if name.startswith(".env") or name.endswith(
            (".env", ".pem", ".key", ".p12", ".pfx", ".kdbx", ".token")):
        return f"密钥/环境凭据文件（{name}）"
    return None


# 读权限分级（批次 27）：PII 内容脱敏——read_file 的文本内容会随 tool 消息
# 回喂 LLM，「跳过个人敏感信息不入明文」在**内容层**兜底（路径层由
# _sensitive_read 把守）。正则模式集 v1（诚实面：正则脱敏是概率防线非
# 密码学保证，新增类别在此扩展）。
_PII_PATTERNS = (
    # 私钥/证书块（整段吞掉，含头尾行）
    ("私钥块", re.compile(
        r"-----BEGIN [A-Z ]*PRIVATE KEY( BLOCK)?-----.*?-----END [A-Z ]*"
        r"PRIVATE KEY( BLOCK)?-----", re.S)),
    # 通用 API key 样式（OpenAI sk- / GitHub ghp_·gho_ / AWS AKIA / Bearer）
    ("API密钥", re.compile(
        r"\b(?:sk-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9]{20,}|"
        r"AKIA[0-9A-Z]{16}|Bearer\s+[A-Za-z0-9._-]{20,})\b")),
    # 身份证（18 位含校验位 X）——先于手机号（避免 17 位段被手机号误吃）
    ("身份证号", re.compile(r"\b\d{6}(?:19|20)\d{2}"
                           r"(?:0[1-9]|1[0-2])(?:[0-2]\d|3[01])\d{3}[\dXx]\b")),
    # 手机号（大陆号段）
    ("手机号", re.compile(r"\b1[3-9]\d{9}\b")),
    # 邮箱
    ("邮箱", re.compile(
        r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
)


# 生效条件：text 为任意字符串；依次以 _PII_PATTERNS 各模式 sub 为「[已脱敏:{类别}]」并返回处理后文本（无命中时原串返回；多类命中各自替换）。
def _redact_pii(text: str) -> str:
    for label, pat in _PII_PATTERNS:
        text = pat.sub(f"[已脱敏:{label}]", text)
    return text


# 生效条件：o 为任意 JSON 形态（dict/list/str/标量）；dict 逐键、list 逐项递归下探，字符串值经 _redact_pii 替换后按原结构返回；非容器标量原样返回（V21-7：lingshu_cg 返回体的统一脱敏入口）。
def _redact_deep(o):
    if isinstance(o, str):
        return _redact_pii(o)
    if isinstance(o, dict):
        return {k: _redact_deep(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_redact_deep(v) for v in o]
    return o


# 生效条件：job_dir 与 spec 给定时返回 worker 的 read_file 白名单根 tuple——job_dir（工作区，None/空跳过）+ spec.workdir（定制工作目录，与 HIVE 下文基准一致）+ spec.read_roots（额外定制目录列表或单串——单串先包一层 [s] 再归一，支持 ~/ 展开），逐项 realpath 去重去空；全部为空时返回空 tuple（调用方据此拒读——worker 无根即无文件读权限）。
def _worker_scope(job_dir: str | None, spec: dict) -> tuple:
    roots = []
    # 单串包一层（2026-09-25 缺陷修复）：list(s) 会逐字符切分——切出的
    # 单字符 '\\' 经 realpath 归一为**当前盘根**混入 scope_roots，worker
    # 读白名单被意外扩到全盘；且 docstring 声称的「单串」形态完全失效。
    rr = spec.get("read_roots") or []
    if isinstance(rr, str):
        rr = [rr]
    for p in [job_dir, spec.get("workdir")] + list(rr):
        if isinstance(p, str) and p.strip():
            r = os.path.realpath(os.path.expanduser(p.strip()))
            if r not in roots:
                roots.append(r)
    return tuple(roots)


# 生效条件：当 args[key] 可 int() 转换且 > 0 时返回 min(该值, hi)，转换失败（None/空/非数字）或 <= 0 时返回 default；
def _int_arg(args: dict, key: str, default: int, hi: int) -> int:
    """容错读整数参数：非法值回落默认而非抛错（工具面不因参数脏而崩）。"""
    try:
        v = int(args.get(key))
    except (TypeError, ValueError):
        return default
    return default if v <= 0 else min(v, hi)


# 生效条件：当 real 目录可 os.listdir 时返回 {'ok':True,'path','kind':'dir','total','truncated','entries'}，条目按（子目录优先，名字小写序）排序、每项含 name/type/bytes（子目录 bytes=None）、超过 READ_DIR_MAX 截断；listdir/stat 抛 OSError 时返回 {'ok':False,...} 诚实报错（不猜目录内容）；
def _list_dir(real: str) -> dict:
    """目录清单（读放开的一半：先能发现，才谈读得到）。"""
    try:
        names_all = os.listdir(real)
    except OSError as e:
        return {"ok": False, "path": real, "kind": "dir",
                "error": f"{type(e).__name__}: {e}"}
    # P2-7（批次 31）：先截断再 stat——超大目录只 stat 返回的头部条目
    # （total/truncated 仍按全量 listdir 计数，语义不变）。
    names = names_all[:READ_DIR_MAX]
    entries = []
    for n in names:
        full = os.path.join(real, n)
        try:
            is_dir = os.path.isdir(full)
            size = None if is_dir else os.path.getsize(full)
        except OSError:
            is_dir, size = False, None
        entries.append({"name": n, "type": "dir" if is_dir else "file",
                        "bytes": size})
    entries.sort(key=lambda e: (e["type"] != "dir", e["name"].lower()))
    return {"ok": True, "path": real, "kind": "dir",
            "total": len(names_all),
            "truncated": len(names_all) > READ_DIR_MAX,
            "entries": entries[:READ_DIR_MAX]}


# 生效条件：当 path 可 utf-8 errors=replace 打开、offset>=1、limit>=1、max_chars>=1 时，逐行流式读取：从第 offset 行起收集至多 limit 行且累计字符 <= max_chars（触顶时**当前行截到剩余额度内**，单行与多行同口径、可能产出半行）；文件字节数 <= READ_FULL_BYTES 时继续数到 EOF 返回精确 lines_total，超过则提前停并将 lines_total 记 None；返回 (content, lines_total|None, lines_returned, truncated, 替换符个数)；
def _read_text_window(path: str, offset: int, limit: int,
                      max_chars: int, size: int) -> tuple:
    """行窗读取：流式（大文件不进内存），行总数要么精确要么诚实记 None。

    字符上限**硬约束**（2026-09-20 v14 缺陷 A 修复）：单行本身超过
    `max_chars` 时（minified JS / 单行大 JSON / 单行长行语料）截断该行到
    上限内，而不是整行放行。旧实现在这种文件上把 `max_chars`（乃至
    `READ_HARD_CHARS` 这个自称「硬上限、不可协商」的常量）**完全架空**——
    实测 `max_chars=100` 回吐 5,000,000 字符、`limit=1` 亦然，足以撑爆
    调用方（LLM 宿主）上下文。

    **多行同样受该硬上限约束**（2026-09-20 v15-6 口径收敛）：累计触顶时
    **当前行也被截到剩余额度内**，故可能产出**半行**（`max_chars=10` 读
    `L1\\nL2\\nL3\\nL4` 得 `'L1\\nL2\\nL3\\nL'`，`lines_returned=4` 计的是
    「部分行」）。旧 docstring 称「多行文件仍按整行收（行粒度软上限语义不变）」
    **与实现不符**——此处按「保留硬上限行为、改文档」收敛（硬上限是安全侧）。
    """
    out, chars, n, total, exact = [], 0, 0, 0, True
    with open(path, encoding="utf-8", errors="replace") as f:
        for i, line in enumerate(f, 1):
            total = i
            if i < offset:
                continue
            if n < limit and chars < max_chars:
                room = max_chars - chars
                if len(line) > room:        # 单行超限：截断，不整行放行
                    out.append(line[:room])
                    chars += room
                    n += 1
                    continue
                out.append(line)
                chars += len(line)
                n += 1
                continue
            if size > READ_FULL_BYTES:      # 窗口已满且文件超大：不再数行
                exact = False
                break
    content = "".join(out)
    return (content, (total if exact else None), n,
            bool(n >= limit or chars >= max_chars), content.count("\ufffd"))


# 生效条件：当 args 含非空 path 时，以 workdir（缺省 os.getcwd()）为相对基准求 realpath；HIVE_READ_ROOTS 非空且 real 不在任一根下返回 {'ok':False,error,roots}；_sensitive_read(real) 命中敏感凭据路径（P1-6 增量）返回 {'ok':False,error}；real 为目录走 _list_dir；非 isfile 返回 {'ok':False,'error':'路径不存在'}；否则读 BINARY_SNIFF_BYTES 头经 sniff_kind 分类：text 返回行窗正文与分页元数据（含 encoding/replacements，replacements>0 附存疑提示），image:* 另附 image_size 尺寸、binary 只给 bytes，二者 content=None；打开/取尺寸抛 OSError 时返回 {'ok':False,...} 诚实报错；
def tool_read_file(args: dict, workdir: str = None,
                   scope_roots=None) -> dict:
    """读本地文件（只读面）：文本给行窗、目录给清单、图像/二进制给元数据。

    读放开：默认无路径白名单（使用者裁定）；部署可用 HIVE_READ_ROOTS 收窄。
    读权限分级（批次 27）：worker 子代理传 scope_roots（工作区+定制工作
    目录，`_worker_scope` 构造）→ fail-closed 白名单；文本正文统一过
    _redact_pii（个人敏感信息不入明文）。**无任何写参数、不落盘、不改
    状态**——执行器的写路径只有 lingshu_cg。
    """
    p = str(args.get("path") or "").strip()
    if not p:
        return {"ok": False, "error": "path 必填（文件或目录）"}
    base = workdir or os.getcwd()
    real = os.path.realpath(p if os.path.isabs(p) else os.path.join(base, p))
    # 读权限分级（批次 27）：scope_roots 非 None = worker 身份白名单
    # （fail-closed：含空 tuple——无根即拒，不回落 cwd 放开）
    if scope_roots is not None:
        if not any(_under(real, r) for r in scope_roots):
            return {"ok": False, "path": real,
                    "error": "路径超出子代理读权限范围（工作区+定制工作"
                             "目录），拒读（其他会话/越界内容不进上下文）",
                    "scope_roots": list(scope_roots)}
    roots = read_roots()
    if roots and not any(_under(real, r) for r in roots):
        return {"ok": False, "path": real,
                "error": "路径超出 HIVE_READ_ROOTS 白名单，拒读（越界即拒，"
                         "不猜内容）",
                "roots": list(roots)}
    # P1-6 增量（批次 26）：敏感凭据路径拒读——不受根白名单配置影响
    # （内容回喂外部 LLM 网关，凭据类文件无论部署配置都不进上下文）
    why = _sensitive_read(real)
    if why:
        return {"ok": False, "path": real,
                "error": f"敏感路径拒读：{why}——凭据类文件不进 LLM 上下文"
                         "（P1-6 增量；如有合法需要请走部署管理员显式通道）"}
    if os.path.isdir(real):
        return _list_dir(real)
    if not os.path.isfile(real):
        return {"ok": False, "path": real,
                "error": f"路径不存在（不猜内容）: {real}"}
    try:
        size = os.path.getsize(real)
        with open(real, "rb") as f:
            head = f.read(BINARY_SNIFF_BYTES)
    except OSError as e:
        return {"ok": False, "path": real, "error": f"{type(e).__name__}: {e}"}
    kind = sniff_kind(head)
    if kind != "text":
        info = {"ok": True, "path": real, "kind": kind, "bytes": size,
                "content": None,
                "note": "非文本：不返回正文（诚实，不猜内容）。图像要进上下文"
                        "请用 spec.context_files 走图像块（含预算折算）。"}
        if kind.startswith("image:"):
            w, h = image_size(real)
            info["width"], info["height"] = w, h
        return info
    offset = _int_arg(args, "offset", 1, READ_HARD_LINES)
    limit = _int_arg(args, "limit", READ_MAX_LINES, READ_HARD_LINES)
    mchars = _int_arg(args, "max_chars", READ_MAX_CHARS, READ_HARD_CHARS)
    try:
        content, total, n, truncated, bad = _read_text_window(
            real, offset, limit, mchars, size)
    except OSError as e:
        return {"ok": False, "path": real, "error": f"{type(e).__name__}: {e}"}
    # 读权限分级（批次 27）：个人敏感信息不入明文——回喂 LLM 前内容层脱敏
    # （设计者与子代理同防线；命中类别以 [已脱敏:*] 占位，可审计可复原计数）
    redacted = _redact_pii(content)
    out = {"ok": True, "path": real, "kind": "text", "bytes": size,
           "offset": offset, "lines_returned": n, "lines_total": total,
           "truncated": truncated, "encoding": "utf-8(replace)",
           "replacements": bad, "content": redacted}
    if redacted != content:
        out["pii_redacted"] = True
    if bad:
        out["note"] = (f"解码替换 {bad} 处（非 UTF-8 或二进制污染）——按替换处"
                       "标记存疑，勿据此断言原文。")
    return out


# 生效条件：当 name/args_json/job_id 传入时，json.loads(args_json or '{}') 失败返回 ({'ok':False,'error':'工具参数不是合法 JSON: ...'}, '')；否则 name=='lingshu_cg' 调 tool_lingshu_cg(args,job_id,mdcg_root)，name=='web_search' 调 tool_web_search(args,backend_override=ws_backend)，name=='read_file' 调 tool_read_file(args,workdir)，name 在 _EXTRA_TOOLS 中调其 handler(name,args,job_id)（handler 抛异常则兜底 {'ok':False,'error':...} 不上抛），否则返回未知工具错误；随后对 out 设默认 ok='error' not in out，按 results/knowledge 长度生成 brief，返回 (out,brief)；
def execute_tool(name: str, args_json: str, job_id: str,
                 mdcg_root: str = None, ws_backend: str = None,
                 workdir: str = None, read_scope_roots=None) -> tuple:
    """执行一次工具调用，返回 (结果dict, trace简报)。未知工具诚实报错。"""
    try:
        args = json.loads(args_json or "{}")
    except json.JSONDecodeError as e:
        return ({"ok": False, "error": f"工具参数不是合法 JSON: {e}"}, "")
    if name == "lingshu_cg":
        out = tool_lingshu_cg(args, job_id, mdcg_root=mdcg_root)
    elif name == "web_search":
        out = tool_web_search(args, backend_override=ws_backend)
    elif name == "read_file":
        # 读权限分级（批次 27）：read_scope_roots 非 None = worker 白名单
        out = tool_read_file(args, workdir=workdir,
                             scope_roots=read_scope_roots)
    elif name in _EXTRA_TOOLS:
        # 分派兜底（v2 N13，2026-09-25）：外部 handler（如编排面）抛异常曾
        # 穿透 run_with_tools 调用点直达 main 兜底 except，以 EXIT_API 判死
        # 整个 job。工具面契约是「返回 {'ok': False} 而非抛」——这里把契约
        # 机械化：handler 违约回错误结果，不杀 job（与 mcp_server 工具层
        # 兜底同款模板）。
        try:
            out = _EXTRA_TOOLS[name]["handler"](name, args, job_id)
        except Exception as e:  # noqa: BLE001 —— 工具面兜底不杀 job
            out = {"ok": False, "error": f"{type(e).__name__}: {e}"}
    else:
        out = {"ok": False,
               "error": f"未知工具 {name!r}（允许：{', '.join(all_schemas())}）"}
    # 统一 ok 语义：底层 dispatch（route/read）无 ok 键——无 error 即成功，
    # 保证 trace["ok"] 与模型侧自修判断的依据可靠。
    out.setdefault("ok", "error" not in out)
    n = len(out.get("results") or out.get("knowledge") or [])
    brief = ("ok" if out.get("ok") else "error") + f" items={n}"
    return (out, brief)


# 生效条件：当 spec 与 messages 传入时，body 必含 spec['model'] 与 messages；tools 为真值才注入；spec['thinking']、spec['reasoning_effort']、spec['max_tokens'] 为真值才注入；spec['temperature'] is not None（含 0）才注入；返回 body；
def build_body(spec: dict, messages: list, tools: list = None) -> dict:
    """请求体构造：必填 model/messages + 可选参数存在才注入（不送 null/缺省键）。

    thinking 原样透传（DeepSeek V4.1 同形对象，如 {"type": "enabled"}）；
    reasoning_effort 档位已由 rust 侧白名单校验（low|medium|high）；
    tools 仅 agent loop 注入（function calling schema 列表）。
    """
    body: dict = {"model": spec["model"], "messages": messages}
    if tools:
        body["tools"] = tools
    if spec.get("thinking"):
        body["thinking"] = spec["thinking"]
    if spec.get("reasoning_effort"):
        body["reasoning_effort"] = spec["reasoning_effort"]
    if spec.get("max_tokens"):
        body["max_tokens"] = spec["max_tokens"]
    if spec.get("temperature") is not None:
        body["temperature"] = spec["temperature"]
    return body


# 生效条件：当 body 与 timeout 传入时，api_key=os.environ.get('HIVE_API_KEY','')，若假值（未设或空串）抛 RuntimeError('HIVE_API_KEY 未设置...')；否则 api_base=os.environ.get('HIVE_API_BASE', DEFAULT_API_BASE).rstrip('/')，仅缺键时回落 DEFAULT_API_BASE，键存在空串不回落；POST {api_base}/chat/completions 并以 timeout 请求，返回 json.loads(resp.read(RESP_MAX_BYTES).decode('utf-8'))；
def _post_chat(body: dict, timeout: float) -> dict:
    """裸 POST chat/completions，返回原始响应 dict。HTTP 异常向上传播。"""
    api_base = os.environ.get("HIVE_API_BASE", DEFAULT_API_BASE).rstrip("/")
    api_key = os.environ.get("HIVE_API_KEY", "")
    if not api_key:
        raise RuntimeError("HIVE_API_KEY 未设置（执行器环境缺密钥）")
    url = f"{api_base}/chat/completions"
    req = urllib.request.Request(
        url,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read(RESP_MAX_BYTES).decode("utf-8"))


# 生效条件：当 spec 与 messages 传入时，以 build_body(spec,messages) 与 float(spec.get('timeout_s') or 300) 调 _post_chat；返回的 message 为空助手轮（_empty_turn：content 与 tool_calls 双空——含 choices 缺/空、content 空串或 null）时返回 {'_error': '模型返回空助手轮…'}，否则返回 content=message.content or ''、usage=data.get('usage') or {}、model=data.get('model') or spec['model']；
def call_llm(spec: dict, messages: list) -> dict:
    """单发调 chat/completions（无工具历史路径）；返回归一化 result。"""
    data = _post_chat(build_body(spec, messages),
                      float(spec.get("timeout_s") or 300))
    msg = _choice(data).get("message") or {}
    # 空包不得冒充成功（v2 N7，2026-09-25）：网关 200 + 空/缺 choices、
    # content="" 或 null（null 穿透 .get 默认值落 None）都是无效终答——
    # 与工具轮内同款 _empty_turn 判据，回 _error 由 main 写失败 result。
    if _empty_turn(msg):
        return {"_error": "模型返回空助手轮（content 与 tool_calls 双空）"}
    return {
        "content": msg.get("content") or "",
        "usage": data.get("usage") or {},
        "model": data.get("model") or spec["model"],
    }


# 生效条件：当 total 与 u 传入时，u 为真 dict 则遍历其 items，仅 value 为 int/float 时把 total[k]=total.get(k,0)+v；u 为假值（None/空）不修改 total；
def _acc_usage(total: dict, u: dict) -> None:
    for k, v in (u or {}).items():
        if isinstance(v, (int, float)):
            total[k] = total.get(k, 0) + v


# 生效条件：当 data 传入时，返回 (data.get('choices') or [{}])[0]：choices 缺键/空列表/假值时返回 {}，否则返回 choices 的第一个元素；
def _choice(data: dict) -> dict:
    return (data.get("choices") or [{}])[0]


# 生效条件：当 msg 传入时，若 (msg.get('content') or '').strip() 为空且 msg.get('tool_calls') 为假值（None/空列表等）则返回 True，否则 False；
def _empty_turn(msg: dict) -> bool:
    """content 与 tool_calls 双空 = 错误/中止的助手轮（Pi⑦①）。

    这种轮次既不入上下文（空洞 assistant 轮会污染下一轮请求，协议也不接受），
    也不冒充有效终答（否则 result 会是 ok=true + 空 content 的假成功）。
    """
    return not (msg.get("content") or "").strip() and not (msg.get("tool_calls"))


# 生效条件：当 text/job_dir/tag 传入时，若 len(text)<=TOOL_MSG_MAX_CHARS 返回 (text,'')；否则若 job_dir 为真且 os.path.isdir(job_dir) 为真，则尝试把 text 写入 job_dir/tool_{tag}.json，成功 name=该文件名，OSError 则 log 并把 name=''；最终返回 (text[:TOOL_MSG_MAX_CHARS-TOOL_MSG_TAIL_CHARS]+省略说明+text[-TOOL_MSG_TAIL_CHARS:], name)；
def _shrink_tool_text(text: str, job_dir: str | None, tag: str) -> tuple:
    """大输出落盘（受 TOOL_DUMP_MAX_CHARS 上限）+ 回喂消息保尾（Pi⑦③，对齐
    exec_cmd._dump_step/_render）。

    小输出原样返回（历史行为逐位一致）。→ (喂给模型的文本, 落盘文件名或 "")
    """
    if len(text) <= TOOL_MSG_MAX_CHARS:
        return text, ""
    name = ""
    if job_dir and os.path.isdir(job_dir):
        name = f"tool_{tag}.json"
        # 落盘面同样受字符上限约束（2026-09-20 v15-3 修复）：旧实现把原始输出
        # **全量**写盘——回喂面已收紧而磁盘面无天花板（实测落盘 60226 bytes ≈
        # 原始输出），单行 5MB 文件（minified JS / 单行大 JSON）会让 job 目录
        # 持续堆积大文件。上限取 TOOL_DUMP_MAX_CHARS（远高于回喂的
        # TOOL_MSG_MAX_CHARS，保留「回查完整输出」的价值），超出部分截断并标注。
        payload = text
        if len(payload) > TOOL_DUMP_MAX_CHARS:
            payload = (payload[:TOOL_DUMP_MAX_CHARS]
                       + f"\n…（落盘截断：原文 {len(text)} 字符，"
                         f"落盘上限 {TOOL_DUMP_MAX_CHARS}）…\n")
        try:
            with open(os.path.join(job_dir, name), "w", encoding="utf-8") as f:
                f.write(payload)
        except OSError as e:
            log(job_dir, f"工具输出落盘失败: {e}")
            name = ""
    head = text[:TOOL_MSG_MAX_CHARS - TOOL_MSG_TAIL_CHARS]
    tail = text[-TOOL_MSG_TAIL_CHARS:]
    note = (f"\n…（中间省略 {len(text) - TOOL_MSG_MAX_CHARS} 字符；完整输出"
            f"{'见 ' + name if name else '落盘失败（job 目录不可写）'}，"
            f"共 {len(text)} 字符）…\n")
    return head + note + tail, name


# 生效条件：当 spec/job_dir/trace/usage/rnd/est/budget 传入时，基于 trace 中 ok 项生成 digest，调用 progress 写进展卡（仅 job_dir 为真且为目录时该卡才落盘，非目录时 progress no-op），并返回 content=digest、usage、model=spec.get('model')、tool_trace=trace、tool_rounds=rnd、completed=False、need_continue=True 及 handoff 块；
def _handoff(spec: dict, job_dir: str | None, trace: list, usage: dict, rnd: int,
             est: int, budget: int) -> dict:
    """满上下文换人续跑（v0.4 §5.3 落地）：写进展卡 + 标 need_continue 交回。

    不自动续跑（续跑资格由主代理裁决）；completed=false 与 ok=true 并存，
    诚实区分「本次执行正常收口」与「任务已完成」。

    字段词汇契约：进展卡 handoff 条目与 result.json 的 handoff 块**同词**——
    同一事件两个观测面（卡=主代理读的交接面，result=轮询面），字段名分叉会
    让续跑提示词组装读到两套词汇（取证 2026-09-16：卡曾用 budget/无
    auto_continue）。改字段须两面同步；`hive/test_wm_progress.py` 守卫互认。
    """
    done = [f"{t.get('round')}:{t.get('tool')} {t.get('brief')}"
            for t in trace if t.get("ok")]
    digest = (
        f"【交回续跑】上下文达预算阈值：保守估算 {est} tokens > 预算 {budget}。"
        f"本 job 已完成 {rnd} 轮工具调用，未终答。\n"
        f"进展卡：{PROGRESS_FILE}（主代理读它组装续跑提示词）。\n"
        f"已完成：{'; '.join(done[-8:]) or '（无）'}\n"
        "续跑方式：以「同 system_prompt + 上文进展摘要 + 剩余目标」spawn 新 job"
        "（读回同 session 记忆面）；是否续跑由主代理裁决，执行器不自动续跑。")
    progress(job_dir, kind="handoff", round=rnd, est_tokens=est,
             budget_tokens=budget, reason="context_budget", done=done[-20:],
             progress_file=PROGRESS_FILE, auto_continue=False, summary=digest)
    log(job_dir, f"达预算交回（need_continue）est={est} budget={budget} round={rnd}")
    return {
        "content": digest,
        "usage": usage,
        "model": spec.get("model"),
        "tool_trace": trace,
        "tool_rounds": rnd,
        "completed": False,
        "need_continue": True,
        "handoff": {
            "reason": "context_budget",
            "est_tokens": est,
            "budget_tokens": budget,
            "rounds_done": rnd,
            "progress_file": PROGRESS_FILE,
            "auto_continue": False,
        },
    }


# 生效条件：spec/messages/job_id 给定即进入 while rnd <= max_rounds（max_rounds=max(1, int(spec.get("max_tool_rounds") or DEFAULT_MAX_TOOL_ROUNDS))，budget 取 spec.get("context_budget_tokens")）：超预算且 spec.get("context_strict") 为真返回 {"_error": over, "tool_trace": trace}、否则转 _handoff；API 异常或空助手轮返回 {"_error", "tool_trace"}；模型无 tool_calls 返回 content/usage/model/tool_trace；rnd >= max_rounds 仍要求工具则去掉 tools 强制终答（forced_final=True）。
def run_with_tools(spec: dict, messages: list, job_id: str,
                   job_dir: str | None = None, base_tokens: int = 0) -> dict:
    """agent loop：模型回 tool_calls → 执行 → tool 消息回喂 → 循环至终答。

    轮次上限 max_tool_rounds（spec 可配，默认 5）：达到后若模型仍要求工具，
    发一次不带 tools 的请求强制终答（保证 result.content 有值，trace 诚实
    记 _force_final）。API 异常不抛出——以 {"_error","tool_trace"} 返回，
    由 main 写失败 result（trace 不丢，审计可回放）。

    上下文档位：base_tokens=图像等非文本块折算（Pi⑦④）+ messages 文本估算；
    超预算默认交回续跑（见 _handoff），spec.context_strict=true 保持旧 fail fast。
    """
    _vis = all_schemas()
    names = [t for t in (spec.get("tools") or []) if t in _vis]
    schemas = [_vis[t] for t in names]
    max_rounds = max(1, int(spec.get("max_tool_rounds")
                            or DEFAULT_MAX_TOOL_ROUNDS))
    timeout = float(spec.get("timeout_s") or 300)
    budget = spec.get("context_budget_tokens")
    trace, usage_total = [], {}

# 生效条件：无入参，budget 为假值（None/0/空串）时立即返回 (0, "")；否则 total = base_tokens + 对 messages 中 content 为 str 的项累加 est_tokens(content or "")，仅当 total > int(budget) 时返回超预算文案、否则返回空串。
    _est = {"seen": 0, "total": base_tokens}

    def _budget_check() -> tuple:
        # P2-6（批次 31）：增量维护——messages 只增不减，每轮只对新追加的
        # 消息计 token（旧写法每轮全量重算，O(轮数 × 累计字符) 平方级）。
        if not budget:
            return 0, ""
        for m in messages[_est["seen"]:]:
            if isinstance(m.get("content"), str):
                _est["total"] += est_tokens(m.get("content") or "")
            _est["seen"] += 1
        total = _est["total"]
        return total, (
            f"上下文超预算: 保守估算 {total} tokens > 预算 {int(budget)}"
            "（工具轮累积所致；请收窄任务或调大 context_budget_tokens）"
            if total > int(budget) else "")

    rnd = 0
    while rnd <= max_rounds:
        est, over = _budget_check()
        if over:
            if spec.get("context_strict"):
                progress(job_dir, kind="budget_stop", round=rnd, est_tokens=est,
                         budget_tokens=int(budget), strict=True)
                return {"_error": over, "tool_trace": trace}
            return _handoff(spec, job_dir, trace, usage_total, rnd, est,
                            int(budget))
        try:
            data = _post_chat(build_body(spec, messages,
                                         tools=schemas if schemas else None),
                              timeout)
        except Exception as e:  # noqa: BLE001 —— main 统一写失败 result
            return {"_error": _api_err_text(e), "tool_trace": trace}
        _acc_usage(usage_total, data.get("usage") or {})
        msg = _choice(data).get("message") or {}
        if _empty_turn(msg):
            log(job_dir, "助手轮 content/tool_calls 双空 → 不入上下文、不冒充终答"
                         "（Pi⑦①）")
            progress(job_dir, kind="error", round=rnd, where="loop",
                     error="空助手轮（content 与 tool_calls 双空）")
            return {"_error": "模型返回空助手轮（content 与 tool_calls 双空）",
                    "tool_trace": trace}
        calls = msg.get("tool_calls") or []
        if not calls:
            out = {"content": msg.get("content") or "",
                   "usage": usage_total,
                   "model": data.get("model") or spec["model"],
                   "tool_trace": trace}
            if rnd > 0:
                out["tool_rounds"] = rnd
            progress(job_dir, kind="final", round=rnd,
                     content_head=(msg.get("content") or "")[:200],
                     usage_total=(usage_total or {}).get("total_tokens"),
                     tool_rounds=rnd)
            return out
        if rnd >= max_rounds:  # 超轮次仍要求工具 → 强制终答
            # 加固（2026-09-22 实测缺陷）：直接原样重发会让模型继续输出「工具调用
            # 意图文本」（观测：DSML 原文漏进最终 content）。附加一条明确指令，
            # 要求以纯文本收口；不再回灌工具结果。
            messages.append({
                "role": "user",
                "content": ("[系统] 工具调用轮次已用尽，本轮起不再执行任何工具。"
                            "请基于以上已获得的信息直接输出最终文本结论；"
                            "不要再输出任何工具调用语法或调用意图。"),
            })
            try:
                data = _post_chat(build_body(spec, messages, tools=None),
                                  timeout)
            except Exception as e:  # noqa: BLE001
                return {"_error": _api_err_text(e), "tool_trace": trace}
            _acc_usage(usage_total, data.get("usage") or {})
            msg = _choice(data).get("message") or {}
            # 空包不得冒充强制终答（v2 N7 同族第二缺口，2026-09-25）：轮内
            # 有 _empty_turn 防护，本分支曾无——网关故障回空包时任务记
            # forced_final=true + content="" 的假成功，流入下游合并/续跑链。
            if _empty_turn(msg):
                log(job_dir, "强制终答空助手轮 → 不冒充终答（v2 N7）")
                progress(job_dir, kind="error", round=rnd,
                         where="force_final",
                         error="空助手轮（content 与 tool_calls 双空）")
                return {"_error": "强制终答返回空助手轮（content 与 tool_calls 双空）",
                        "tool_trace": trace}
            trace.append({"round": rnd, "tool": "_force_final",
                          "ok": True, "brief": "轮次上限，强制终答"})
            progress(job_dir, kind="force_final", round=rnd,
                     content_head=(msg.get("content") or "")[:200])
            return {"content": msg.get("content") or "",
                    "usage": usage_total,
                    "model": data.get("model") or spec["model"],
                    "tool_trace": trace, "tool_rounds": rnd,
                    "forced_final": True}
        messages.append({"role": "assistant",
                         "content": msg.get("content") or "",
                         "tool_calls": calls})
        for tc in calls:
            fn = tc.get("function") or {}
            out, brief = execute_tool(fn.get("name"), fn.get("arguments"),
                                      job_id,
                                      mdcg_root=spec.get("mdcg_root"),
                                      ws_backend=spec.get("web_search_backend"),
                                      workdir=spec.get("workdir"),
                                      read_scope_roots=_worker_scope(
                                          job_dir, spec))
            full = json.dumps(out, ensure_ascii=False)
            text, spill = _shrink_tool_text(full, job_dir,
                                            f"{rnd}_{len(trace)}")
            rec = {"round": rnd, "tool": fn.get("name"),
                   "args": (fn.get("arguments") or "")[:300],
                   "ok": bool(out.get("ok")), "brief": brief,
                   "result": full[:800]}
            if spill:
                rec["spill"] = spill
            trace.append(rec)
            progress(job_dir, kind="tool", round=rnd, tool=fn.get("name"),
                     ok=bool(out.get("ok")), brief=brief,
                     evidence=full[:200], spill=spill or None)
            messages.append({
                "role": "tool", "tool_call_id": tc.get("id") or "",
                "content": text})
        rnd += 1
    return {"_error": "工具轮次循环异常退出（不应到达）", "tool_trace": trace}


# 生效条件：当 e 传入时，若 isinstance(e, urllib.error.HTTPError) 为真则读取 e.read() 解码前 2000 字符（失败则 detail=''）并返回 f'HTTP {e.code}: {detail or e.reason}'；否则返回 f'{type(e).__name__}: {e}'；
def _api_err_text(e: Exception) -> str:
    if isinstance(e, urllib.error.HTTPError):
        try:
            detail = e.read().decode("utf-8", errors="replace")[:2000]
        except Exception:  # noqa: BLE001
            detail = ""
        return f"HTTP {e.code}: {detail or e.reason}"
    return f"{type(e).__name__}: {e}"


# 生效条件：len(sys.argv) < 2 时打印 usage 并返回 EXIT_SPEC；否则 job_dir 取 sys.argv[1]，spec 读取异常、超 context_budget_tokens、SpecError 均返回 EXIT_SPEC，工具链或单发（含空助手轮）的 _error 或 urllib HTTPError 或其他异常返回 EXIT_API，成功（含无可见 tools 时走 call_llm 且非空助手轮）返回 EXIT_OK；
def main() -> int:
    if len(sys.argv) < 2:
        print("usage: exec.py <job_dir>", file=sys.stderr)
        return EXIT_SPEC
    job_dir = sys.argv[1]
    t0 = time.time()
    try:
        spec = read_spec(job_dir)
    except Exception as e:  # noqa: BLE001 —— 顶层兜底必须写 result
        write_error_result(job_dir, {"ok": False, "error": f"spec 读取失败: {e}"})
        return EXIT_SPEC
    global _CUR_ORCH_JOB
    _CUR_ORCH_JOB = str(spec.get("orch_job") or "").strip()

    try:
        # model↔base 配对前置校验（标准 §1）：错配即刻 SPEC 错，不触网不烧调度
        _mismatch = model_base_mismatch(
            str(spec.get("model") or ""),
            os.environ.get("HIVE_API_BASE", DEFAULT_API_BASE))
        if _mismatch:
            write_error_result(job_dir, {"ok": False, "error": f"model 与 HIVE_API_BASE 错配：{_mismatch}"})
            log(job_dir, f"spec 错（模型错配）: {_mismatch}")
            progress(job_dir, kind="error", error=_mismatch[:300], where="spec")
            return EXIT_SPEC
        messages, ctx_meta = build_messages(spec, job_dir)
        base_tokens = ctx_meta.get("image_tokens", 0)
        budget = spec.get("context_budget_tokens")
        if budget:
            total = base_tokens + sum(est_tokens(m["content"]) for m in messages)
            if total > int(budget):
                msg = (
                    f"上下文超预算: 保守估算 {total} tokens > 预算 {int(budget)}"
                    + (f"（含图像折算 {base_tokens}）" if base_tokens else "")
                    + "（估算偏高估；请分片任务或调大 context_budget_tokens）"
                )
                write_error_result(job_dir, {"ok": False, "error": msg})
                log(job_dir, f"超预算拦截 est={total} budget={budget}")
                progress(job_dir, kind="budget_stop", est_tokens=total,
                         budget_tokens=int(budget), where="spec")
                return EXIT_SPEC
        n_ctx = ctx_meta.get("contexts", 0)
        tool_names = [t for t in (spec.get("tools") or []) if t in all_schemas()]
        job_id = os.path.basename(os.path.normpath(job_dir))
        log(
            job_dir,
            f"开始调用 model={spec.get('model')} ctx={n_ctx}"
            + (f" imgs={ctx_meta['images']}" if ctx_meta["images"] else "")
            + (f" bins={ctx_meta['binaries']}" if ctx_meta["binaries"] else "")
            + (f" base_tokens={base_tokens}" if base_tokens else "")
            + (f" prompt_src={ctx_meta.get('system_prompt_source')}"
               if ctx_meta.get("system_prompt_source") not in (None, "none") else "")
            + (f" effort={spec['reasoning_effort']}" if spec.get("reasoning_effort") else "")
            + (f" budget={budget}" if budget else "")
            + (f" tools={tool_names}" if tool_names else ""),
        )
        progress(job_dir, kind="start", model=spec.get("model"), ctx_files=n_ctx,
                 images=ctx_meta["images"], binaries=ctx_meta["binaries"],
                 image_tokens=base_tokens,
                 system_prompt_source=ctx_meta.get("system_prompt_source"),
                 task=(spec.get("user_prompt") or "")[:200])
        if tool_names:
            out = run_with_tools(spec, messages, job_id, job_dir=job_dir,
                                 base_tokens=base_tokens)
        else:
            out = call_llm(spec, messages)
        if "_error" in out:
            # 统一失败落盘（v2 N7，2026-09-25）：单发空包与工具链失败走同一
            # _error 协议——都写 ok=false + EXIT_API；此前单发路无条件
            # out.update(ok=True)，网关 200+空包曾记成功（content=""）。
            write_error_result(
                job_dir,
                {
                    "ok": False,
                    "error": out["_error"],
                    "tool_trace": out.get("tool_trace") or [],
                    "finished_ts": time.time(),
                    "duration_s": round(time.time() - t0, 2),
                },
            )
            log(job_dir, f"{'工具链' if tool_names else '单发'}失败: "
                         f"{out['_error'][:200]}")
            progress(job_dir, kind="error", error=out["_error"][:300],
                     where="tool_loop" if tool_names else "single_shot")
            return EXIT_API
        out.update(
            {
                "ok": True,
                "finished_ts": time.time(),
                "duration_s": round(time.time() - t0, 2),
            }
        )
        out["system_prompt_source"] = ctx_meta.get("system_prompt_source")
        out["context_meta"] = {k: v for k, v in ctx_meta.items() if k != "notes"}
        write_result(job_dir, out)
        tokens = out.get("usage", {}).get("total_tokens")
        n_tools = len(out.get("tool_trace") or [])
        log(job_dir, f"完成 tokens={tokens}"
            + (f" tool_calls={n_tools}" if n_tools else "")
            + (" 交回续跑(need_continue)" if out.get("need_continue") else ""))
        return EXIT_OK
    except SpecError as e:
        write_error_result(
            job_dir,
            {"ok": False, "error": str(e),
             "finished_ts": time.time(), "duration_s": round(time.time() - t0, 2)},
        )
        log(job_dir, f"规格错: {e}")
        progress(job_dir, kind="error", error=str(e), where="spec")
        return EXIT_SPEC
    except urllib.error.HTTPError as e:
        try:
            detail = e.read().decode("utf-8", errors="replace")[:2000]
        except Exception:  # noqa: BLE001
            detail = ""
        write_error_result(
            job_dir,
            {
                "ok": False,
                "error": f"HTTP {e.code}: {detail or e.reason}",
                "finished_ts": time.time(),
                "duration_s": round(time.time() - t0, 2),
            },
        )
        log(job_dir, f"API HTTP 错误 {e.code}")
        return EXIT_API
    except Exception as e:  # noqa: BLE001
        write_error_result(
            job_dir,
            {
                "ok": False,
                "error": f"{type(e).__name__}: {e}",
                "finished_ts": time.time(),
                "duration_s": round(time.time() - t0, 2),
            },
        )
        log(job_dir, "异常:\n" + traceback.format_exc())
        return EXIT_API


if __name__ == "__main__":
    sys.exit(main())