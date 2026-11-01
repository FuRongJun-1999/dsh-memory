# -*- coding: utf-8 -*-
# 功能名：session5_resolve 守卫（A2 路线：灵枢自读 DSH 会话文件算 s5）
# 生效条件：python -X utf8 -m md_cg.test_session5_resolve；被测面＝md_cg/session5.py 的
#           resolve_sessions_root / locate_session_file / read_session_file / session5_resolve
# 子功能：
#   A. 路径三级解析：显式传参优先；全不存在返回 None；**绝不硬编码绝对路径**
#   B. uuid 定位：`session-<uuid>` → glob；非法/空 id 有明确原因；未命中给原因
#   C. 读会话文件：**流式解压**（多 frame 必须全读到）；**首帧单次解压只得到 1 行**（钉住这点）；
#      系统注入（`<system-reminder>` 等）**必须被过滤**，取首条真 user 消息
#   D. 全链：cwd+createdAt+首句 → 合法 s5；头不全/无真消息/无文件 → None + 具体原因
#   E. 真实目录（若存在）抽样跑；**不存在则 SKIP 不红**（CI 环境无 DSH 会话目录）
# 执行：纯函数级断言 + 自造 zstd fixture（不依赖 DSH 真实目录）
# 验证方式：全部 PASS exit 0；每条注明「怎么让它红」
# 不适用条件：不测 DSH 侧是否真能产出该格式（那是 DSH 的事）；不测并存量的 sess_xxxx 迁移
"""为什么需要它：

使用者实测：DSH 会话 uid **不稳定**（启动脚本按目录 mtime 猜会话，而新版只更新目录内文件
不更新目录 mtime ⇒ 身份滞留旧会话）；而**会话的第一句话不变**。
故由 (harness, unit, workspace, 创建时间, 首条 user 消息) 确定性推导 s5。

本守卫钉住三个**实测踩出来的**细节：
  ① 会话文件是**多 frame zstd**——一次性 `decompress()` 只得到首帧（73KB 只解出 1 行）；
  ② 子代理会话首条 user/message 是 `<system-reminder>...` —— 不过滤会让不同会话算出同一 s5；
  ③ 路径**不得硬编码**——靠 DSH_HOME 等环境探测，换机不需改代码。
"""
import importlib.util
import json
import os
import shutil
import sys
import tempfile

from . import session5 as s5

_PASS = []
_FAIL = []
_SKIP = []


def ok(cond, msg, extra=""):
    (_PASS if cond else _FAIL).append(msg)
    print(("  PASS " if cond else "  FAIL ") + msg + (("  <- " + str(extra)) if (extra and not cond) else ""))


def skip(msg):
    _SKIP.append(msg)
    print("  SKIP " + msg)


def _zstd():
    try:
        import zstandard
        return zstandard
    except Exception:
        return None


def _make_session_file(root, workspace_slug, session_uuid, hdr, msgs, multi_frame=True):
    """自造一个会话文件（可多 frame），返回路径。"""
    z = _zstd()
    d = os.path.join(root, workspace_slug, "session-" + session_uuid)
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, "session.v4.jsonl.zstd")
    lines = [json.dumps(hdr, ensure_ascii=False)]
    for m in msgs:
        lines.append(json.dumps(m, ensure_ascii=False))
    payload = "\n".join(lines) + "\n"
    if multi_frame:
        # 逐行各压一个 frame —— 复现真实形态（一次性 decompress 只得首帧）
        blob = b"".join(z.ZstdCompressor().compress((l + "\n").encode("utf-8"))
                        for l in lines)
    else:
        blob = z.ZstdCompressor().compress(payload.encode("utf-8"))
    with open(p, "wb") as f:
        f.write(blob)
    return p


def _user_msg(seq, text):
    return {"type": "user/message", "seq": seq,
            "data": {"content": [{"type": "text", "text": text}], "role": "user"}}


def a_root_resolve(tmp):
    print("\n== A 路径三级解析（怎么让它红：把探测改成硬编码绝对路径 -> A2 红）")
    ok(s5.resolve_sessions_root(tmp) == os.path.abspath(tmp),
       "A1 显式传参优先返回该目录", s5.resolve_sessions_root(tmp))
    bogus = os.path.join(tmp, "no-such-dir")
    ok(s5.resolve_sessions_root(bogus) is None,
       "A2 显式传一个不存在的目录 -> None（不回落别处）", s5.resolve_sessions_root(bogus))
    old = os.environ.pop("DSH_HOME", None)
    old2 = os.environ.pop("MDCG_SESSIONS_ROOT", None)
    try:
        got = s5.resolve_sessions_root()
        ok(got is None or os.path.isdir(got),
           "A3 无任何线索时不抛、且只在目录真存在时返回", got)
    finally:
        if old is not None:
            os.environ["DSH_HOME"] = old
        if old2 is not None:
            os.environ["MDCG_SESSIONS_ROOT"] = old2


def b_locate(tmp):
    print("\n== B uuid 定位（怎么让它红：把 uuid 校验去掉 -> B2 红）")
    # 本组用 _make_session_file 造 fixture ⇒ **依赖 zstandard**。
    # CI 裸环境没装它（实测 CI 就红在这里：AttributeError on None.ZstdCompressor）。
    # 与 C/D 组同口径：缺依赖就 SKIP，不假红。
    if _zstd() is None:
        skip("B 缺 zstandard，跳过 uuid 定位断言（本组需造会话文件 fixture）")
        return
    uuid = "11111111-2222-3333-4444-555555555555"
    hdr = {"type": "session", "version": 4, "id": "session-" + uuid,
           "createdAt": 1700000000000, "cwd": "D:\\proj\\demo"}
    p = _make_session_file(tmp, "--D-proj-demo--", uuid, hdr,
                           [_user_msg(1, "第一句话")])
    got, why = s5.locate_session_file("session-" + uuid, sessions_root=tmp)
    ok(got and os.path.abspath(got) == os.path.abspath(p),
       "B1 合法 uuid 能定位到文件", (got, why))
    got2, why2 = s5.locate_session_file("not-a-uuid", sessions_root=tmp)
    ok(got2 is None and why2 == "not_uuid_form",
       "B2 非 uuid 形态 -> None + not_uuid_form（不瞎 glob）", (got2, why2))
    got3, why3 = s5.locate_session_file("", sessions_root=tmp)
    ok(got3 is None and why3 == "empty_session_id",
       "B3 空 id -> None + empty_session_id", (got3, why3))
    got4, why4 = s5.locate_session_file("session-99999999-9999-9999-9999-999999999999",
                                        sessions_root=tmp)
    ok(got4 is None and why4 == "session_file_not_found",
       "B4 未命中 -> None + session_file_not_found", (got4, why4))


def c_read_multi_frame(tmp):
    print("\n== C 流式解压 + 系统注入过滤（怎么让它红：换成一次性 decompress -> C1 红）")
    if _zstd() is None:
        skip("C 缺 zstandard，跳过解压相关断言")
        return
    uuid = "22222222-3333-4444-5555-666666666666"
    hdr = {"type": "session", "version": 4, "id": "session-" + uuid,
           "createdAt": 1700000000000, "cwd": "D:\\proj\\demo"}
    msgs = [
        _user_msg(1, "<system-reminder>\nYou are teammate \"x\".\nDo not answer."),
        _user_msg(2, "这才是用户说的第一句"),
        _user_msg(3, "第二句"),
    ]
    p = _make_session_file(tmp, "--D-proj-demo--", uuid, hdr, msgs, multi_frame=True)
    h, first, why = s5.read_session_file(p)
    ok(h is not None and h.get("cwd") == "D:\\proj\\demo",
       "C1 多 frame 全读到（会话头可见；一次性解压只得首帧会红）", (h, why))
    ok(first == "这才是用户说的第一句",
       "C2 过滤系统注入，取首条真 user 消息", first)
    # 反证：单 frame 也要能读
    uuid2 = "33333333-4444-5555-6666-777777777777"
    hdr2 = dict(hdr, id="session-" + uuid2)
    p2 = _make_session_file(tmp, "--D-proj-demo--", uuid2, hdr2,
                            [_user_msg(1, "单帧首句")], multi_frame=False)
    h2, f2, _ = s5.read_session_file(p2)
    ok(h2 is not None and f2 == "单帧首句", "C3 单 frame 也能读", f2)


def d_full_chain(tmp):
    print("\n== D 全链 + 降级（怎么让它红：把 created_at 检查删掉 -> D3 红）")
    if _zstd() is None:
        skip("D 缺 zstandard，跳过全链断言")
        return
    uuid = "44444444-5555-6666-7777-888888888888"
    hdr = {"type": "session", "version": 4, "id": "session-" + uuid,
           "createdAt": 1700000000000, "cwd": "D:\\proj\\demo"}
    _make_session_file(tmp, "--D-proj-demo--", uuid, hdr, [_user_msg(1, "全链首句")])
    reason = {}
    sid = s5.session5_resolve("session-" + uuid, sessions_root=tmp, reason_out=reason)
    ok(sid is not None and s5.is_session5(sid),
       "D1 全链产出合法 s5", (sid, reason))
    ok(sid is not None and "D_4_ai" not in sid and "D_proj_demo" in sid,
       "D2 workspace slug 取自会话头 cwd", sid)
    # 正常路径 reason 必须为空
    ok(reason.get("reason") is None, "D3 成功时 reason.reason 为 None（不误报降级）", reason)
    # 降级：文件不存在
    r2 = {}
    s2 = s5.session5_resolve("session-aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                             sessions_root=tmp, reason_out=r2)
    ok(s2 is None and r2.get("reason") == "session_file_not_found",
       "D4 无文件 -> None + 具体原因（不静默）", r2)
    # 降级：头缺 cwd
    uuid3 = "55555555-6666-7777-8888-999999999999"
    hdr3 = {"type": "session", "version": 4, "id": "session-" + uuid3,
            "createdAt": 1700000000000}   # 无 cwd
    _make_session_file(tmp, "--D-x--", uuid3, hdr3, [_user_msg(1, "有首句但无 cwd")])
    r3 = {}
    s3 = s5.session5_resolve("session-" + uuid3, sessions_root=tmp, reason_out=r3)
    ok(s3 is None and r3.get("reason") == "header_incomplete",
       "D5 头缺 cwd -> None + header_incomplete", r3)
    # 降级：全是系统注入
    uuid4 = "66666666-7777-8888-9999-aaaaaaaaaaaa"
    hdr4 = dict(hdr, id="session-" + uuid4)
    _make_session_file(tmp, "--D-proj-demo--", uuid4, hdr4,
                       [_user_msg(1, "<system-reminder>only inject</system-reminder>")])
    r4 = {}
    s4 = s5.session5_resolve("session-" + uuid4, sessions_root=tmp, reason_out=r4)
    ok(s4 is None and r4.get("reason") == "no_real_user_message",
       "D6 只有系统注入 -> None + no_real_user_message（不拿注入当首句）", r4)


def e_real_dir():
    print("\n== E 真实目录抽样（不存在则 SKIP）")
    if _zstd() is None:
        skip("E 缺 zstandard")
        return
    root = s5.resolve_sessions_root()
    if not root:
        skip("E 本机无 DSH 会话目录（resolve_sessions_root -> None）")
        return
    import glob as _g
    files = _g.glob(os.path.join(root, "*", "session-*", "session.v4.jsonl.zstd"))
    if not files:
        skip("E 会话目录下无文件")
        return
    good = 0
    sample = files[:10]
    for f in sample:
        sid_dir = f.replace("\\", "/").split("/")[-2]
        if s5.session5_resolve(sid_dir, sessions_root=root):
            good += 1
    ok(good >= max(1, len(sample) - 2),
       "E1 真实会话抽样多数能算出 s5（%d/%d）" % (good, len(sample)), (good, len(sample)))


def main():
    if sys.stdout.encoding and sys.stdout.encoding.lower().startswith("cp"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    tmp = tempfile.mkdtemp(prefix="s5res-")
    try:
        a_root_resolve(tmp)
        b_locate(tmp)
        c_read_multi_frame(tmp)
        d_full_chain(tmp)
        e_real_dir()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print()
    print("session5_resolve 守卫：%d 通过 / %d 失败 / %d 跳过"
          % (len(_PASS), len(_FAIL), len(_SKIP)))
    if _FAIL:
        for f in _FAIL:
            print("  -", f)
    return 0 if not _FAIL else 1


if __name__ == "__main__":
    sys.exit(main())