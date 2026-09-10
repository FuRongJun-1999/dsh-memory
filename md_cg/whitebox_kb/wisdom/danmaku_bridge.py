# -*- coding: utf-8 -*-
"""灵枢 × B站直播 · 弹幕桥 v2（bilibili-api-python）

弹幕流 → 灵枢审核（danmaku_audit）→ 放行转 chat → 回答展示。
bilibili-api-python 自动处理 Wbi 签名 + cookie 认证。

凭据：本地 .bili_creds 文件（SESSDATA/BUVID3，gitignore，不写配置库）。
用法：
  python danmaku_bridge.py <room_id> [--demo]
"""
import asyncio
import os
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

RATE_LIMIT_SECONDS = 3.0
_last_by_user = {}
LIVE_SESSION = "live_" + time.strftime("%Y%m%d")
_agent = None

CREDS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".bili_creds")


def _load_creds():
    """加载本地凭据（不存在则返回 None）。"""
    try:
        if os.path.exists(CREDS_FILE):
            d = {}
            with open(CREDS_FILE, encoding="utf-8") as f:
                for line in f:
                    if "=" in line:
                        k, v = line.strip().split("=", 1)
                        d[k] = v
            return d
    except Exception:
        pass
    return None


def _get_agent():
    """懒加载全局 Agent 单例：首次调用才构造灵枢 Agent，避免模块导入期建连接。"""
    global _agent
    if _agent is None:
        from aeis_core.api import Agent
        _agent = Agent(identity="灵枢",
                       db_path=os.environ.get("AEIS_DB", os.path.join("data", "lingshu.db")))
    return _agent


def process_danmaku(text, uname="观众", show_fn=print):
    """审核 → 放行 → chat → 展示。"""
    now = time.time()
    last = _last_by_user.get(uname, 0)
    if now - last < RATE_LIMIT_SECONDS:
        return {"verdict": "rate_limited"}
    _last_by_user[uname] = now

    import danmaku_audit as _da
    audit = _da.audit(text)
    if audit.get("verdict") == "block":
        show_fn(f"[内容安全拦截] {uname}：{text[:20]}…")
        return {"verdict": "block", "category": audit.get("category")}

    try:
        agent = _get_agent()
        r = agent.wisdom_chat(text, session_id=LIVE_SESSION)
        reply = r.get("reply", "")
        show_fn(f"🎯 {uname}：{text}")
        show_fn(f"🌿 灵枢：{reply}")
        return {"verdict": "show", "reply": reply}
    except Exception as e:
        show_fn(f"⚠️ 灵枢处理失败：{e}")
        return {"verdict": "error"}


def run_live(room_id):
    """bilibili-api-python 实时弹幕（自动 Wbi + cookie）。"""
    try:
        from bilibili_api import live, Credential
    except ImportError:
        print("需要 pip install bilibili-api-python")
        return

    creds = _load_creds()
    credential = None
    if creds and creds.get("SESSDATA"):
        credential = Credential(sessdata=creds["SESSDATA"],
                                buvid3=creds.get("BUVID3"))
        print("已加载本地凭据（SESSDATA）")
    else:
        print("无本地凭据——尝试匿名（可能受限）")

    room = live.LiveDanmaku(room_display_id=int(room_id),
                            credential=credential)

    @room.on("DANMU_MSG")
    async def on_danmaku(event):
        data = event["data"]["info"]
        text = data[1]
        uname = data[2][1] if len(data) > 2 else "观众"
        if text and text.strip():
            process_danmaku(text.strip(), uname)

    print(f"连接直播间 {room_id}（弹幕→灵枢审核→回答展示）…")
    try:
        asyncio.run(room.connect())
    except KeyboardInterrupt:
        print("\n已停止")


# ---------------- 模拟测试 ----------------
DEMO_DANMAKU = [
    "主播讲得好！", "这个白箱智能是啥呀？",
    "这个主播是骗子吧", "加微信私聊有福利",
    "为什么水会烧开？", "你好呀！",
    "虽然累，但想学点东西",
]


def run_demo():
    print("=" * 56)
    print(f"弹幕桥模拟（直播 session: {LIVE_SESSION}）")
    print("=" * 56)
    users = ["路人甲", "程序员小王", "吃瓜群众", "路人乙", "神秘观众",
             "潜水员", "热心网友"]
    for i, d in enumerate(DEMO_DANMAKU):
        process_danmaku(d, uname=users[i % len(users)])
        time.sleep(0.5)


if __name__ == "__main__":
    if "--demo" in sys.argv:
        run_demo()
    elif len(sys.argv) >= 2:
        run_live(sys.argv[1])
    else:
        print("用法: python danmaku_bridge.py <room_id> [--demo]")
