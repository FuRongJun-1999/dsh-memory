# -*- coding: utf-8 -*-
"""spatial_qa.py · 3D 时空问答（第五阶段·3D 轨迹接入感知记忆）
多帧双目 → 3D 轨迹 → 灵枢记忆（[3D时空事件] spatial3d 标签）→ 3D 时空问答：
  「球往哪飞了？」→ x+；「飞多快？」→ 0.2单位/帧；「飞了多远？」→ 位移；「轨迹直吗？」→ 一致性
零 LLM 确定性——看见（3D）→ 记住（灵枢）→ 时空问答（3D）。
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')
try:
    from spacetime_3d import (synth_moving_stereo_frames, frame_scene_graphs,
                              track_3d, motion_3d)
except ImportError:
    from .spacetime_3d import (synth_moving_stereo_frames, frame_scene_graphs,
                               track_3d, motion_3d)


def see_3d_and_remember(agent, stereo_seq, label):
    """看见→记住（3D）：多帧双目 → 3D 轨迹 → 灵枢记忆（spatial3d 标签）
    返回 (motion, node)：3D 运动原语 + 灵枢记忆节点"""
    traj = track_3d(frame_scene_graphs(stereo_seq))
    motion = motion_3d(traj)
    if not motion.get("ok"):
        motion = {"ok": True, "direction": ["静止"], "speed": 0.0,
                  "displacement": [0, 0, 0], "consistency": 0.0}
    direction = motion["direction"][0]
    start = traj[0] if traj else {"x": 0, "y": 0, "z": 0}
    end = traj[-1] if traj else start
    disp_len = float((sum(c * c for c in motion["displacement"])) ** 0.5)
    parts = [f"[3D时空事件] {label}"]
    parts.append(f"方向={direction} 速度={motion['speed']}单位/帧")
    parts.append(f"位移={round(disp_len, 2)} 一致性={motion['consistency']}")
    parts.append(f"起点=({start['x']},{start['y']},{start['z']}) "
                 f"终点=({end['x']},{end['y']},{end['z']})")
    if direction == "静止":
        parts.append("静止")
    content = " ".join(parts)
    node = agent.remember(content, importance=0.8,
                          tags=["spatial3d", "perception", label])
    return motion, node


def recall_3d(agent, query, limit=3):
    """召回 3D 时空记忆（灵枢组合联想）"""
    try:
        return agent.recall(query, limit=limit)
    except Exception:
        return []


def ask_3d(agent, question):
    """3D 时空问答：问题类型识别 → 召回 spatial3d 记忆 → 白箱回答
    类型：方向/速度/距离/轨迹/静止"""
    qtype = _classify_3d(question)
    if qtype is None:
        return {"ok": False, "reply": "（非 3D 时空问题——不属感知通道）", "type": None}
    hits = recall_3d(agent, question, limit=3)
    if not hits:
        return {"ok": False, "reply": "（3D 时空记忆中没有相关事件——还没看见什么）",
                "type": qtype}
    node, score = hits[0]
    content = node.content or ""
    reply = _answer_3d(qtype, content)
    return {"ok": True, "reply": reply, "type": qtype,
            "source": content[:60], "score": round(score, 3)}


def answer_3d_from_content(qtype, content):
    """从 3D 记忆内容直接回答（真实库时间线模式：内容来自 lingshu_timeline
    近因召回，而非 agent.recall 模糊召回——绕开学科卡淹没）"""
    return _answer_3d(qtype, content)


def timeline_3d_answer(question, timeline_events, limit=6):
    """真实库模式 3D 问答：问题类型识别 → 时间线近因召回（倒序）→
    按 spatial3d 标签过滤 → 取最近事件 → 内容解析回答
    timeline_events: lingshu_timeline 输出（[{id, content, tags, ...}]）"""
    qtype = _classify_3d(question)
    if qtype is None:
        return {"ok": False, "reply": "（非 3D 时空问题——不属感知通道）", "type": None}
    for ev in timeline_events[:limit]:
        tags = ev.get("tags") or []
        if "spatial3d" not in tags:
            continue
        content = ev.get("content") or ""
        if "3D时空事件" not in content:
            continue
        reply = _answer_3d(qtype, content)
        return {"ok": True, "reply": reply, "type": qtype,
                "source": content[:60], "node": ev.get("id")}
    return {"ok": False, "reply": "（时间线近因召回中无 spatial3d 事件）", "type": qtype}


def _classify_3d(q):
    """3D 问题类型识别（白箱确定性关键词）"""
    if any(w in q for w in ("方向", "往哪", "怎么动", "向哪")):
        return "方向"
    if any(w in q for w in ("速度", "多快", "快慢", "每秒")):
        return "速度"
    if any(w in q for w in ("多远", "位移", "飞了", "走了", "距离")):
        return "距离"
    if any(w in q for w in ("直吗", "轨迹", "直线", "拐弯")):
        return "轨迹"
    if any(w in q for w in ("静止", "动了没", "有没有动", "在动吗")):
        return "静止"
    return None


def _answer_3d(qtype, content):
    """按类型从 3D 记忆内容组装白箱回答"""
    def grab(key):
        i = content.find(key)
        return content[i:i + 20] if i >= 0 else ""
    if qtype == "方向":
        for d in ("x+", "x-", "z+", "z-"):
            if f"方向={d}" in content:
                return f"刚才看到的是沿 {d} 方向移动（3D 空间主轴判定）。"
        if "静止" in content:
            return "刚才那个是静止的（3D 轨迹无位移）。"
        return f"根据 3D 时空记忆：{grab('方向=')}"
    if qtype == "速度":
        return f"它的{grab('速度=')}——3D 轨迹跨帧追踪测得（单位/帧）。"
    if qtype == "距离":
        return f"它总共{grab('位移=')}——3D 轨迹起终点直线距离。"
    if qtype == "轨迹":
        return f"轨迹{grab('一致性=')}——一致性接近 1 说明直线运动。"
    if qtype == "静止":
        if "静止" in content:
            return "不，那个是静止的（3D 轨迹位移为 0）。"
        return "不，它在动（3D 轨迹有方向/速度记录）。"
    return content[:60]


def verify_3d_remembered(agent, node, motion):
    """3D 记忆自校验：灵枢记忆节点与 3D 运动原语一致性（无幻觉）"""
    n = agent.engine.store.get_node(node.id)
    if not n:
        return False, "节点不存在"
    content = n.content or ""
    ok = True
    direction = motion["direction"][0]
    if f"方向={direction}" not in content:
        ok = False
    if direction != "静止" and f"速度={motion['speed']}" not in content:
        ok = False
    return ok, content


if __name__ == "__main__":
    print("=== 3D 时空问答：看见(3D)→记住(灵枢)→问答（零 LLM）===\n")
    import sys as _sys, os
    _sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), 'aeis'))
    from aeis_core.api import Agent
    a = Agent(identity="spatial3d-test", db_path=":memory:")

    # 看见右移球 + 静止背景
    seq = synth_moving_stereo_frames(frames=10, speed_px=2, direction="right")
    motion, node = see_3d_and_remember(a, seq, "球")
    seq_s = synth_moving_stereo_frames(frames=6, speed_px=0, direction="right")
    motion_s, node_s = see_3d_and_remember(a, seq_s, "背景")
    print("① 看见并记住（3D 轨迹写入灵枢记忆）：")
    print(f"   球: {node.content[:70]}")
    print(f"   背景: {node_s.content[:60]}")

    print("\n② 3D 时空问答：")
    for q in ["刚才那个球往哪飞了？", "球飞多快？", "球飞了多远？",
              "球的轨迹直吗？", "背景在动吗？"]:
        r = ask_3d(a, q)
        mark = "✔" if r.get("ok") else "✘"
        print(f"  [{mark}] Q: {q}")
        print(f"     A: {r.get('reply', '')}")

    print("\n③ 记忆自校验：")
    ok1, c1 = verify_3d_remembered(a, node, motion)
    print(f"   球: {'✔ 一致（无幻觉）' if ok1 else '✘ ' + c1[:40]}")
    ok2, c2 = verify_3d_remembered(a, node_s, motion_s)
    print(f"   背景: {'✔ 一致（静止）' if ok2 else '✘ ' + c2[:40]}")

    ok_all = ok1 and ok2 and all(ask_3d(a, q).get("ok") for q in
                                 ["球往哪飞了？", "球飞多快？", "球飞了多远？",
                                  "球的轨迹直吗？", "背景在动吗？"])
    print(f"\n=== 判定 ===\n3D 时空问答白箱命中: {'✔ 成立（3D 轨迹进记忆+问答）' if ok_all else '✘'}")
