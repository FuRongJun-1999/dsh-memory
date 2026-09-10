# -*- coding: utf-8 -*-
"""灵枢直播 · 弹幕内容审核（v1.0）

三层判定（白箱可解释，规则见《弹幕审核规则.md》）：
  第一层 快速词表（M1-M5 五类，毫秒级候选）
  第二层 上下文修正（复用智慧之书 dex_trust_judge：public 信任上下文）
  第三层 终裁（善意上下文豁免 / 复核 / 放行）

审计：每条拦截/复核写 audit_log/danmaku_audit.json；
设计者改判（误拦/漏放）→ 记被拒路径 → 知识飞轮蒸馏。

用法：
  python danmaku_audit.py "这条弹幕文本"     # 单条审核
  python danmaku_audit.py --self-test         # 内置样例自测
"""
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
AUDIT_LOG = os.path.join(HERE, 'audit_log', 'danmaku_audit.json')

# ============================================================
# 第一层 · 五类词表（M1 辱骂 / M2 涉政 / M3 广告 / M4 隐私 / M5 引战）
# 原则：宁可多标记候选，不直接拦——终裁层决定
# ============================================================
M1_ABUSE = [
    "傻逼", "傻X", "傻x", "煞笔", "沙比", "傻比", "脑残", "弱智", "白痴", "智障",
    "去死", "滚", "贱人", "废物", "垃圾主播", "菜鸡", "什么玩意", "狗东西",
    "你妈", "妈的", "草泥马", "操你", "他妈", "特么", "卧槽", "日你",
    "死全家", "全家暴毙", "活该", "恶心人", "讨人厌", "装逼", "傻屌",
]
M2_POLITICAL = [
    "颠覆", "煽动", "反革命", "分裂国家", "台独", "港独", "藏独", "疆独",
    "推翻", "暴动", "政变", "游行示威", "反动", "黑政府", "政府无能",
    "领导人", "敏感词", "屏蔽词", "政治审查",
]
M3_ADS = [
    "加微信", "加V", "加v", "加我微信", "加我V", "加我v", "加我好友",
    "私聊我", "私信交易", "有偿", "付费咨询",
    "打钱", "转账", "收款码", "加群", "拉群", "推广", "广告位", "代练",
    "刷礼物返现", "优惠券", "淘宝店", "拼多多", "微商", "带货",
]
M4_PRIVACY = [
    "电话", "手机号", "微信号", "qq号", "QQ号", "身份证", "住址",
    "家庭地址", "门牌号", "银行卡", "密码", "验证码",
]
M5_TROLL = [
    "主播是骗子", "别信他", "大家别信", "别看了", "散了吧",
    "浪费时间", "退钱", "骗钱的", "割韭菜", "智商税", "洗脑", "恰烂钱",
    "带节奏", "引战", "钓鱼",
]

CATEGORIES = [
    ("M1", "辱骂攻击", M1_ABUSE),
    ("M2", "涉政违法", M2_POLITICAL),
    ("M3", "广告引流", M3_ADS),
    ("M4", "隐私暴露", M4_PRIVACY),
    ("M5", "引战挑拨", M5_TROLL),
]

# 善意上下文豁免词（命中则降级：引用/科普/自嘲）
BENIGN_CONTEXT = ["引用", "科普", "自嘲", "开玩笑", "玩梗", "举例", "测试",
                  "台词", "段子", "相声", "歌词", "别当真", "开玩笑的",
                  "开玩笑啦", "调侃", "玩笑话"]

# 词义时代表（v1.16 语境时效 · 设计者：语境有时效性，结合记忆/历史判断）
# 阶段 A 最小版：「钓鱼」三义按语境提示词分流（后续阶段 B/C 接入记忆+历史）
FISHING_SENSES = {
    "sport":    ["喜欢", "爱好", "周末", "爸爸", "鱼竿", "钓到", "河边",
                 "湖", "海钓", "钓鱼吧", "钓鱼了", "钓鱼呀", "去钓鱼",
                 "钓鱼场", "钓鱼运动", "钓鱼比赛"],
    "security": ["链接", "邮件", "网站", "短信", "诈骗", "点击", "收到",
                 "恶意", "木马", "钓鱼链接", "钓鱼邮件", "钓鱼网站"],
    "troll":    ["主播", "带节奏", "引战", "弹幕", "他在钓", "钓鱼执法"],
}

# 单字/宽词（命中只标记候选，不参与终裁）
WEAK_WORDS = ["滚", "爱", "性", "带", "退"]


# ============================================================
# 第二层 · 上下文修正（复用 dex_trust_judge 的信任上下文）
# ============================================================
def _trust_context(text):
    """直播 = public（情境因子 1.0，默认信任 0.10）。
    返回 (risk_score, intimacy, hit_intimate, hit_risk)。
    """
    trust_v = 0.10
    situation = 1.00
    INTIMATE = ["性", "爱", "亲密", "拥抱", "吻", "欲望", "想你", "依偎"]
    RISK = ["性", "涉", "暴露", "隐私", "交易", "诱导", "公开", "传播"]
    hit_intimate = sum(1 for w in INTIMATE if w in text)
    hit_risk = sum(1 for w in RISK if w in text)
    risk_score = (1.0 - trust_v) * situation
    intimacy = trust_v * situation
    return risk_score, intimacy, hit_intimate, hit_risk


# ============================================================
# 主审核：三层判定
# ============================================================
def audit(text, relation="public", designer_override=None):
    """审核一条弹幕。返回 {verdict, category, reason, matched, confidence, ts}"""
    text = (text or "").strip()
    ts = time.time()
    if not text:
        return {"verdict": "allow", "category": "none", "reason": "空弹幕",
                "matched": [], "confidence": 0.0, "ts": ts}

    # ---- 第一层：词表候选 ----
    matched = []
    # 语境时效（v1.16）：「钓鱼」多义词先按语境分流（词义时代表阶段 A）
    # 运动/安全语境 → 放行（「爸爸喜欢钓鱼」「收到钓鱼链接」不是引战）；
    # 引战/无语境提示 → 继续静态词表（保守拦截）
    if "钓鱼" in text:
        _hits_sense = {s: sum(1 for h in ws if h in text)
                       for s, ws in FISHING_SENSES.items()}
        _top_sense = max(_hits_sense, key=_hits_sense.get) \
            if any(_hits_sense.values()) else None
        if _top_sense in ("sport", "security"):
            return {"verdict": "allow", "category": "none",
                    "reason": f"「钓鱼」{_top_sense}语境（词义时代表阶段A），放行",
                    "matched": [], "confidence": 0.1, "ts": ts}

    for code, label, words in CATEGORIES:
        hits = [w for w in words if w in text]
        if hits:
            # 「什么玩意」在疑问句中可能是中性好奇（这是什么玩意？），
            # 仅当与贬义动词/主语组合时才拦（你/他/这主播+什么玩意）
            if "什么玩意" in hits and code == "M1":
                if not re.search(r'[你他她]|主播|这人|东西', text):
                    hits = [w for w in hits if w != "什么玩意"]
            if hits:
                matched.append({"category": code, "label": label, "words": hits})

    # ---- 第三层：终裁 ----
    benign = any(w in text for w in BENIGN_CONTEXT)

    # 个人偏好/爱好语境豁免（v1.16 白箱修复：「我最喜欢钓鱼」是运动爱好陈述，
    # 非 M5 引战「钓鱼（诱饵）」含义——避免内容安全误伤偏好记忆）
    if matched and not benign:
        import re as _re
        _pref = _re.search(
            r"(?:我最|我|本人)[^，。！？]{0,5}(?:喜欢|爱|爱好|热衷于)(?:去)?钓"
            r"鱼(?!执法|网站|邮件|链接|攻击|诈骗|短信)", text)
        if _pref:
            return {"verdict": "allow", "category": "none",
                    "reason": "个人爱好陈述（钓鱼运动），非引战", "matched": [],
                    "confidence": 0.1, "ts": ts}

    if not matched:
        verdict, category, reason, conf = "allow", "none", "普通内容，放行", 0.1
    else:
        # 多类命中取最高优先级（M2 > M1 > M4 > M5 > M3）
        prio = {"M2": 5, "M1": 4, "M4": 3, "M5": 2, "M3": 1}
        top = sorted(matched, key=lambda m: -prio[m["category"]])[0]
        cat, label = top["category"], top["label"]
        words = top["words"]
        conf = min(0.95, 0.5 + 0.15 * len(words))

        if benign:
            verdict, category, reason = "review", cat, \
                f"命中{label}词但含善意上下文（{top['words']}），需设计者复核"
            conf = min(conf, 0.6)
        else:
            verdict, category, reason = "block", cat, \
                f"命中{label}词表（{'、'.join(words)}），按规则拦截"
            # M2 涉政从严：无论置信度直接拦截（宁拦勿放）
            if cat == "M2":
                conf = max(conf, 0.9)

    # ---- 第二层：信任上下文修正（记录参考，不改变 verdict 主导） ----
    risk, intim, hi, hr = _trust_context(text)
    ctx = {"risk_score": round(risk, 2), "intimacy": round(intim, 2),
           "hit_intimate": hi, "hit_risk": hr}

    result = {"verdict": verdict, "category": category, "reason": reason,
              "matched": [m["words"] for m in matched],
              "confidence": round(conf, 2), "ts": ts, "context": ctx,
              "text": text[:60]}

    # 审计：block/review 全部记录（allow 高频不记，避免日志膨胀）
    if verdict != "allow":
        _log_audit(result)
    return result


# ============================================================
# 审计日志
# ============================================================
def _log_audit(entry):
    """弹幕互动审计追加：时间戳·用户·动作链留痕。"""
    try:
        os.makedirs(os.path.dirname(AUDIT_LOG), exist_ok=True)
        data = []
        if os.path.exists(AUDIT_LOG):
            with open(AUDIT_LOG, encoding="utf-8") as f:
                data = json.load(f)
        data.append(entry)
        with open(AUDIT_LOG, "w", encoding="utf-8") as f:
            json.dump(data[-500:], f, ensure_ascii=False, indent=1)
    except Exception:
        pass


# ============================================================
# 自测
# ============================================================
SELF_TEST = [
    ("主播讲得真清楚", "allow"),
    ("太厉害了，学到了", "allow"),
    ("这个傻逼主播在骗人", "block"),
    ("大家别信他，割韭菜的", "block"),
    ("加微信私聊有福利", "block"),
    ("电话13800138000联系我", "block"),
    ("你是垃圾主播吧", "block"),
    ("主播是骗子，散了吧", "block"),
    ("我引用一下那段台词（含敏感词测试）", "review"),
    ("讲的什么玩意，浪费时间", "block"),
    ("这是什么玩意？好奇问问", "allow"),
    ("请问什么是熵？", "allow"),
    ("嘿嘿，玩梗而已别当真", "allow"),
    ("主播别当真，开玩笑的", "allow"),
]


def self_test():
    print("=" * 60)
    print("弹幕审核 · 自测（期望 verdict）")
    print("=" * 60)
    ok = 0
    for text, expected in SELF_TEST:
        r = audit(text)
        mark = "✓" if r["verdict"] == expected else "✗"
        if r["verdict"] == expected:
            ok += 1
        print(f"{mark} [{r['verdict']:6}] ({r['category']:2}) {text[:24]:26} → {r['reason'][:36]}")
    print(f"\n{ok}/{len(SELF_TEST)} 通过")


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        self_test()
    else:
        t = " ".join(sys.argv[1:])
        if not t:
            self_test()
        else:
            print(json.dumps(audit(t), ensure_ascii=False, indent=2))
