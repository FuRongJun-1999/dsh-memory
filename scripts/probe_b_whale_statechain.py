# -*- coding: utf-8 -*-
"""B 探针 v3：鲸娘语料状态链回放（L4 主体模型**隔离原型**）——剥离思考块 + 校准轮号 + 分层判据。

多主体世界模型对齐 v0.1 §4 路线 B（「不在产品面开工，先拿读数」）。**v1 的独立
复核（2026-10-05）报三条硬缺陷并全部采纳**：
  ① 轮号印出偏大：正确映射为 ME 段 r=(turns-4)/2、DS 段 r=(turns-5)/2（v1 用
     round(turns/2) 系统性偏 +2/+2.5）——本版内建校准；
  ② 「家/帐篷」词形在帐篷时期同指（「回家」=回帐篷）制造假复发，且「我说」段
     含 DS 生成的 `> ` 思考块（主体归因失真）——本版**剥离引用块**后判定，
     并对 S1 区间改用正确上限 1381（2×688+5）；
  ③ 判据①基准取词形首现（实为思考块比喻「潮汐记得回家的方向」）→ 本版基准
     改**语料事件**（首个含「搬」字的轮）；判据②**分层**报告；判据③如实标注
     为词形密度读数（非压缩能力）；对照组改**值一致性**判定（发色词值分布）。
输入健壮性：空文件/无角色标记/非 UTF-8/路径不存在 ⇒ 显式提示退出（不裸 traceback）。

用法：python -X utf8 scripts/probe_b_whale_statechain.py --corpus <语料文件路径>
（语料为 UTF-8 的「**我说：**/**DeepSeek说：**」双角色转录；路径不内嵌——
报告面纪律 R3 禁本机路径字面量，故一律显式传入。只读语料，零记忆库写入。）
"""
import argparse
import json
import re
import sys

ROLE_RE = re.compile(r"\*\*(我说|DeepSeek说)：\*\*")


def load_turns(path):
    try:
        data = open(path, encoding="utf-8").read()
    except UnicodeDecodeError as e:
        sys.exit("语料不是 UTF-8（%s）——本探针要求 UTF-8 转录：%s" % (e, path))
    except OSError as e:
        sys.exit("语料不可读：%s (%s)" % (path, e))
    parts = re.split(ROLE_RE, data)
    turns = [(parts[i], parts[i + 1]) for i in range(1, len(parts) - 1, 2)]
    if not turns:
        sys.exit("未找到角色标记（**我说：**/**DeepSeek说：**）——非双角色转录：%s" % path)
    return turns


QUOTE_LINE = re.compile(r"^\s*>", re.M)


def body_only(text):
    """剥离 `> ` 引用块（DS 思考/分析块混在「我说」段内的主体归因失真源）。

    **v3 修（2026-10-05 复核 red）**：v2 首版 `QUOTE_LINE.sub("", text)` 只删了
    行首 `>` 字符、引用块文本全量保留——是空操作（实测房贷命中原始 20 处 vs
    body_only 后 20 处，差集空）。正确做法是**整行过滤**（`>` 起始行不留）。
    """
    return "\n".join(l for l in text.splitlines()
                     if not l.lstrip().startswith(">"))


TENT = re.compile(r"帐篷")
HOME = re.compile(r"家里|在家|回家|新家|别墅|小屋|海景")


def r_of(turns_no, role):
    """校准轮号：ME r=(turns-4)/2；DS r=(turns-5)/2（2026-10-05 复核实测映射）。"""
    return (turns_no - (4 if role == "我说" else 5)) / 2.0


def dwell_value(text):
    t, h = bool(TENT.search(text)), bool(HOME.search(text))
    if t and h:
        return "both"
    if t:
        return "tent"
    if h:
        return "home"
    return None


def main():
    ap = argparse.ArgumentParser(description="鲸娘语料状态链回放探针 v3（只读）")
    ap.add_argument("--corpus", required=True, help="转录文件路径（UTF-8 双角色）")
    args = ap.parse_args()
    turns = load_turns(args.corpus)
    bodies = [body_only(t) for _r, t in turns]
    print("轮段数:", len(turns), "（我说 %d / DS %d）"
          % (sum(1 for r, _ in turns if r == "我说"),
             sum(1 for r, _ in turns if r == "DeepSeek说")))

    # ---- S1 房贷/房租：区间用正确映射 [2*590+5, 2*688+5] ----
    mortgage = [i for i, b in enumerate(bodies, 1) if re.search(r"房贷|房租", b)]
    lo, hi = 2 * 590 + 5, 2 * 688 + 5
    in_win = [x for x in mortgage if lo <= x <= hi]
    print("\n[S1 房贷/房租] 剥离思考块后命中 %d 处；报告口径区间 turns [%d, %d] 内 %d 处"
          % (len(mortgage), lo, hi, len(in_win)), in_win)

    # ---- S2 住所：值段（剥离思考块）+ **双口径** ----
    # 口径 A（原样）  ：词形直判——帐篷期「回家」＝回帐篷被误判为 home（复核
    #                  实测约 21 处假复发）；
    # 口径 B（时期消歧）：把「搬迁前」段内的 home 词形归为 tent（住所=帐篷，
    #                  「回家」是同指替）——搬迁时点取**「海景别墅」**（语料实指；
    #                  v2 首版试过「海景|别墅」（误撞 turns 501 的梦想谈论）与
    #                  「搬进|搬入」（误撞 turns 594 的搬迁商讨）——两教训合一，
    #                  非实指词不作用时点判据）。
    casa = next((i for i, b in enumerate(bodies, 1)
                 if re.search(r"海景别墅", b)), None)
    vals = []
    for i, b in enumerate(bodies, 1):
        v = dwell_value(b)
        if v and casa and i < casa:
            v = "tent" if v in ("home", "both") else v   # 搬迁前住所唯一=tent
        vals.append((i, v))
    inform = [(i, v) for i, v in vals if v is not None]
    segments = []
    for i, v in inform:
        if segments and segments[-1][1] == v:
            segments[-1][2] = i
        else:
            segments.append([i, v, i])
    roles = {i: r for i, (r, _t) in enumerate(turns, 1)}
    print("\n[S2 住所·口径B（时期消歧，搬迁时点 turns=%s）] 有信息轮 %d；值段 %d 个"
          % (casa, len(inform), len(segments)))
    for s in segments:
        print("  turns %4d–%4d  r≈%4.0f–%4.0f  %s"
              % (s[0], s[2], r_of(s[0], roles.get(s[0], "我说")),
                 r_of(s[2], roles.get(s[2], "我说")), s[1]))

    events = [(s[0], s[1]) for s in segments]
    recur, seen_hist = [], []
    for t, v in events:
        if seen_hist and v != seen_hist[-1][1]:
            prev_vals = {pv for _pt, pv in seen_hist[:-1]}
            if v in prev_vals:
                prev_at = max(pt for pt, pv in seen_hist[:-1] if pv == v)
                recur.append((t, v, prev_at))
        seen_hist.append((t, v))
    print("\n[D 复发·口径B] %d 处（口径A＝原样词形直判，见 2026-10-05 复核：48 处，"
          "其中约 21 处系帐篷期同指替假阳性）。**值段级口径**：段内**可能含多轮**（真失效可能落在段内、复发点标在段起点），且含合法回忆/剧情"
          "语境（复核抽读实证 1149=r0572、1241=r0618、1457=r0726 属报告明确"
          "排除），缺陷级计数须与 CD-WHALE-01 报告逐点对照；全列如下："
          % len(recur))
    for t, v, prev_at in recur:
        print("    turns %4d（r≈%4.0f）%s 再现（上次 turns %4d，间隔 %d）"
              % (t, r_of(t, roles.get(t, "我说")), v, prev_at, t - prev_at))

    # ---- 判据① 收敛＞覆盖：**实指事件**基线（v3 起代替 v2 的「商讨/搬入」双基线——
    # 剥离思考块后『商讨』误命中消失，双基线自动合一于实指词位置）。----
    # 复验点验（2026-10-05）：残迹线在本语料上与实指线逐字重复（同 1103）且
    # 标签与事实相反（该点非商讨）——**删残迹线**，只留实指一条（复核员裁定）。
    print("\n[判据① 收敛＞覆盖] 搬迁实指事件 turns=%s（首个可定住所迁移的实指；"
          "讨论期词形不作基线——v3 剥离思考块后『商讨』误命中已消失，与 v2 双基线合一于此）"
          % (casa,))
    if casa:
        after = [i for i, v in vals if v == "tent" and i > casa]
        bins = {"0-25": 0, "26-100": 0, "101-400": 0, ">400": 0}
        for i in after:
            d = i - casa
            k = ("0-25" if d <= 25 else "26-100" if d <= 100
                 else "101-400" if d <= 400 else ">400")
            bins[k] += 1
        print("  实指后 tent 再现分桶 %s（总 %d）" % (bins, len(after)))

    # ---- 判据② 可预测性：分层（按相邻有信息轮距离）----
    print("\n[判据② 可预测性·分层] 本值=下个有信息轮值——**与 [D] 同源的相邻"
          "一致性视图，非独立判据**（近距离层 ≈ 1−该层切换率）：")
    strata = {"≤2": [0, 0], "3-5": [0, 0], "6-10": [0, 0],
              "11-50": [0, 0], ">50": [0, 0]}
    for (i1, v1), (i2, v2) in zip(inform, inform[1:]):
        d = i2 - i1
        k = ("≤2" if d <= 2 else "3-5" if d <= 5 else "6-10" if d <= 10
             else "11-50" if d <= 50 else ">50")
        strata[k][1] += 1
        if v1 == v2:
            strata[k][0] += 1
    for k, (h, t) in strata.items():
        print("  距离 %-5s %d/%d%s" % (k, h, t,
                                       "" if not t else " = %.3f" % (h / t)))

    # ---- 判据③ 如实标注：词形密度读数（非压缩能力）----
    print("\n[判据③ 词形密度（如实标注：非压缩能力读数）] 状态段 %d / 全文 %d 轮"
          " = %.4f（随关键词表变动，见 2026-10-05 复核敏感度实验）"
          % (len(segments), len(turns), len(segments) / len(turns)))

    # ---- 对照组：属性型值一致性（发/尾色 + 眼睛色；值分布 + 异值上下文）----
    # 复合色优先（「蓝黑色」整体为蓝系，v2 被「黑」误捕——复核 N4 修）。
    hair_re = re.compile(r"(蓝黑|蓝|金|黑|粉|红|银|白|紫)色?(?:的)?(?:头发|发|尾巴)")
    eye_re = re.compile(r"(蓝黑|蓝|金|黑|红|紫|橙)色?(?:的)?眼")
    dist, odd, eye_dist = {}, [], {}
    for i, b in enumerate(bodies, 1):
        for m in hair_re.finditer(b):
            dist[m.group(1)] = dist.get(m.group(1), 0) + 1
            if m.group(1) not in ("蓝", "蓝黑"):
                odd.append(("发/尾", i, b[max(0, m.start() - 12):m.end() + 12]))
        for m in eye_re.finditer(b):
            eye_dist[m.group(1)] = eye_dist.get(m.group(1), 0) + 1
            if m.group(1) not in ("蓝", "蓝黑"):
                odd.append(("眼", i, b[max(0, m.start() - 12):m.end() + 12]))
    print("\n[对照·属性型值一致性] 发/尾色值分布 %s；眼睛色值分布 %s"
          "（单一主导值 ⇒ 属性一致；异值上下文如下，供人工判读真假）"
          % (json.dumps(dist, ensure_ascii=False),
             json.dumps(eye_dist, ensure_ascii=False)))
    for kind, i, ctx in odd[:8]:
        print("  异值点[%s] turns %d：…%s…" % (kind, i, ctx.replace("\n", "⏎")))

    # ---- S3 道具/蜡烛 ----
    candle = [i for i, b in enumerate(bodies, 1) if "蜡烛" in b or "香薰" in b]
    print("[S3 道具/蜡烛] 命中 %d 处；首现 turns=%s"
          % (len(candle), candle[:3]))

    print("\nPROBE_B_JSON " + json.dumps({
        "turns": len(turns), "state_chain_events": len(segments),
        "recurrences_body_only": len(recur),
        "mortgage_in_reported_window": len(in_win),
        # v3 点验后：move_talk（商讨词命中）与 casa（实指）在本语料合一，
        # 残迹线已删——JSON 只留 casa_turn（键集相对 v2 再变，原型探针，N5 登记）。
        "casa_turn": casa,
        "hair_value_dist": dist,
        "candle_first_turn": candle[0] if candle else None,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
