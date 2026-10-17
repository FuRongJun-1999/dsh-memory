# -*- coding: utf-8 -*-
"""自动写入限流与同构聚合（流水污染治理：写入侧前置 + 读侧整理）。

背景（2026-09-15 污染实测）：某环境 contextual 层 355 个自动写入节点中，
46% 是单日批次流水（「批次247收官记忆」…×163 条同模板），17% 是无结构
mem_* 节点；主动遗忘闸门（forgetting.assess）MERGE 命中率仅 1%——精确
内容签名对「每次只换数字的同模板流水」完全无感。

本模块两层治理（只作用 contextual 层——自动写入落层；knowledge 等
手动纪律写入不受限）：

  写入侧（remember_gated 前置，工程策略独立于三问裁决）：
    1) 同源频率限制：同 (layer, role) 滑动窗口内超量 → DEFER（防灌水；
       原始事件仍在 recent log 时间线，可追溯不丢失）
    2) 同构聚合：短内容模板签名（去数字/URL/长十六进制）命中 →
       并入既有节点（正文追加一行 + merge_count+1，不新增节点）

  读侧（sustain 周期巡检调 tidy_contextual）：
    已落盘的同构组（≥min_group 条）→ 保留最早节点追加成员清单，
    成员降权（importance×0.5，下限 0.1）+ tidy:converged 标记；
    永不删除节点（可逆、可审计），受保护节点跳过。
    幂等（2026-10-13，issue #190）：已被整理过的节点（tags 含 tidy:converged
    或 lifecycle_state=="converged"）不再进组、不再降权、不再重写，因此周期
    巡检第 2 轮起对同一组零落盘；返回 dict 新增键 already_tidied（跳过计数）。

状态持久化 <root>/_writelimit.json（进程重启不失效）；台账是**明文 JSON 的外部输入**，
顶层非 dict / 时间戳非数值 / 未来时间戳三类脏值一律按「该记账不存在」收敛
（issue #354 [P1-9]/[P1-10]/[P1-11]）——不崩、也不把限流窗口永久锁死；
env MDCG_WRITELIMIT=0 整体关闭；importance_hint≥0.7（保护优先语义）
跳过所有限流。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time

from . import lifecycle, protect
from .fsutil import FileLock, atomic_write

STATE_FILE = "_writelimit.json"
RATE_WINDOW = 60.0            # 频率窗口（秒）
RATE_MAX = 8                  # 窗口内同 (layer, role) 最大写入数
CONVERGE_WINDOW = 86400.0     # 同构聚合窗口（秒，24h）
MAX_CONTENT = 200             # 参与同构聚合的内容长度上限（字符）
MIN_SKELETON = 4              # 模板骨架最短长度（防「好的/收到」误聚）
MAX_APPLY = 500               # tidy 单次落盘成员数上限（防一次改爆）
TIDY_TAG = "tidy:converged"   # 成员「已整理定型」标记（唯一真源，issue #190）

_RE_URL = re.compile(r"https?://\S+")
_RE_HEX = re.compile(r"\b[0-9a-fA-F]{12,}\b")
_RE_LONG_NUM = re.compile(r"\d{4,}")
_RE_NUM = re.compile(r"\d+")
_RE_WS = re.compile(r"\s+")
_RE_TITLE = re.compile(r"^\s*#\s*功能名[：:]\s*(.+?)\s*$", re.M)


# 生效条件：读环境变量 MDCG_WRITELIMIT（缺省 "1"），strip 并 lower 后不在 ("0", "false", "no") 中即返回 True——默认开启，仅显式关闭值才停用；
def enabled() -> bool:
    """总开关：env MDCG_WRITELIMIT=0/false/no 时关闭所有限流。"""
    return os.environ.get("MDCG_WRITELIMIT", "1").strip().lower() \
        not in ("0", "false", "no")


# 生效条件：形参 sensitivity 为字符串且 strip/lower 后属于 crypto.ENCRYPTED_LEVELS 时返回 True；
# crypto 导入失败、形参非字符串时返回 False（fail-open：判不了就不改变既有行为——密级判据的唯一
# 单点仍是 security.merge_downgrades，本函数只决定「要不要落签名」）。
def _is_encrypted_level(sensitivity) -> bool:
    """声明密级是否属「加密级」——其正文在盘上是密文（crypto.ENCRYPTED_LEVELS）。

    issue #313：#148 修复建议第 1 条「加密级跳过签名（频率限流照常）」此前**未实现**
    —— check / record_accepted 只把 sensitivity 记进台账（且生产调用方从未传值，
    sens 恒为 null），模板签名 `sk` 照写，于是 `_writelimit.json` 里躺着 private /
    secret 正文的**去数字明文骨架**，而同一内容的节点正文在盘上是密文
    （`<!-- mdcg-enc:v1:…`）。密级越高的内容越不该以明文形式躺进明文台账，故
    加密级一律不落签名；频率限流（步骤 1）不受影响，照常生效。

    不适用条件：本函数只判「该不该落签名」——不判降密级（security.merge_downgrades
    单点）、不判读写权限（security 层）、不评价内容相关性。
    """
    if not isinstance(sensitivity, str):
        return False
    try:
        from .crypto import ENCRYPTED_LEVELS as _EL
    except Exception:                                   # noqa: BLE001
        return False
    return sensitivity.strip().lower() in tuple(_EL)


# 生效条件：形参 content 为假值返回 None；否则 strip 后若 _RE_TITLE 命中且标题骨架 s 非空且 len(s)>=MIN_SKELETON 返回 "t:"+s，否则返回 None；无标题且 len(text)>=MAX_CONTENT 返回 None；无标题且 len(text)<MAX_CONTENT 时全文骨架 s 非空且 len(s)>=MIN_SKELETON 返回 s，否则返回 None；
def template_signature(content: str):
    """同模板流水签名：标题模板优先，其次全文骨架。

    - 带「# 功能名：X」标题行的节点：对标题做去数字骨架（不受正文长度
      限制）——批次报告正文各不相同但标题同模板（「批次N收官记忆」），
      标题是节点身份的最强模板信号
    - 无标题：去 URL/长十六进制/数字后的全文压缩骨架；长文
      （≥MAX_CONTENT）是正经记忆不参与聚合
    - 骨架过短（<MIN_SKELETON）或纯数字 → None（防「好的/收到」误聚）
    """
    if not content:
        return None
    text = content.strip()
    m = _RE_TITLE.search(text)
    if m:
        s = _skeleton(m.group(1))
        return ("t:" + s) if s and len(s) >= MIN_SKELETON else None
    if len(text) >= MAX_CONTENT:
        return None
    s = _skeleton(text)
    return s if s and len(s) >= MIN_SKELETON else None


# 生效条件：形参 text 为任意字符串时，依次清除 URL、长十六进制、长数字、数字与空白后返回 s（空串返回空串）；
def _skeleton(text: str) -> str:
    s = _RE_URL.sub(" ", text)
    s = _RE_HEX.sub(" ", s)
    s = _RE_LONG_NUM.sub(" ", s)
    s = _RE_NUM.sub(" ", s)
    s = _RE_WS.sub("", s)
    return s


# ---------- 状态持久化 ----------

# 生效条件：形参 cg 提供 root 时返回 os.path.join(cg.root, STATE_FILE)；
def _state_path(cg) -> str:
    return os.path.join(cg.root, STATE_FILE)


# 生效条件：形参 cg 使 _state_path(cg) 可读取、json.load 得到 **dict** 且 st.get("sigs")/st.get("rate") 均为 dict 时返回 st；否则（读取或解析抛 OSError/ValueError、顶层不是 dict、或 sigs/rate 任一非 dict）一律返回 {"sigs": {}, "rate": {}}——任何损坏形态都不抛异常；
def _load(cg) -> dict:
    """读台账；任何不可用形态一律回落空台账，**不抛**。

    issue #354 [P1-9]：旧实现先取值再判类型 ⇒ 顶层是 JSON 数组/标量/null（外部
    损坏或伪造）时 AttributeError 直接崩到调用方——限流器崩在**写入路径**上，
    比「限流暂时失效」更坏。现在类型闸在取值**之前**。
    不判「内容可信」（结构合法 ≠ 内容正确，同本仓 T9 边界）：单条记账的类型/
    时间戳收敛由 _window_stamps / _window_stamp 在**消费点**做（#354 P1-10/P1-11）。
    边界（越出 #354 面，归维护者裁）：台账判「不可用」时**静默回落**、不发 stderr——沿用
    既有 OSError/ValueError 约定（本面只承诺「脏值不崩」，不承诺「脏值要喊」）；改告警会动到
    所有依赖该约定的调用方，故本批刻意不碰。
    """
    try:
        with open(_state_path(cg), encoding="utf-8") as f:
            st = json.load(f)
        if (isinstance(st, dict) and isinstance(st.get("sigs"), dict)
                and isinstance(st.get("rate"), dict)):
            return st
    except (OSError, ValueError):
        pass
    return {"sigs": {}, "rate": {}}


# 生效条件：调用方传入 cg 与 st，无任何早退守卫，一经调用即以 json.dumps(st, ensure_ascii=False, sort_keys=True) 在 _state_path(cg) 的 FileLock 内原子写入。
def _save(cg, st: dict) -> None:
    p = _state_path(cg)
    with FileLock(p):
        atomic_write(p, json.dumps(st, ensure_ascii=False, sort_keys=True))


# 生效条件：调用方传入 st、key、now，st 须含 "rate" 键（st["rate"].get(key) 缺该 key 或值不是序列时按空列表处理），对窗口列表按 _window_stamps 做类型收敛 + 双向界定后追加 now，并只回写末尾 RATE_MAX*4 项。
def _push_rate(st: dict, key: str, now: float) -> None:
    win = _window_stamps(st["rate"].get(key), now, RATE_WINDOW)
    win.append(now)
    st["rate"][key] = win[-RATE_MAX * 4:]


# 生效条件：形参 t 为有限数值（bool 除外）且 now - window < t <= now 时返回 float(t)，否则返回 None（不抛）；
def _window_stamp(t, now, window):
    """单值时间戳的类型收敛 + 双向界定（issue #354 [P1-9]/[P1-10]/[P1-11] 同族）。

    台账 _writelimit.json 是**明文 JSON**，可被外部损坏或伪造，而旧判据
    now - t < window 是**单向**的，对三类脏值失守：
      · 非数值元素/字段 → now - t 抛未捕获 TypeError，闸门崩在调用方（P1-11）；
      · **未来**时间戳 → now - t 恒为负、恒满足 < window，窗口被**永久**占满、
        限流**永久锁死**（P1-10：8 个未来戳即把 (layer, role) 永久判 DEFER）；
      · 无穷/NaN → 比较恒真或恒假，窗口不再有界（现以 t != t 与 ±inf 的比较语义
        就地收敛，不引 math 之类的额外模块依赖）。
    故判据改为**双向界定**：时间戳必须落在 (now - window, now] 这一有界区间内。
    bool 虽为 int 子类但语义不是时间戳，一并剔除；不可判的值返回 None（等价于
    「该记账不存在」），由调用方按缺失语义处理——不抛、不静默锁死。
    """
    if isinstance(t, bool) or not isinstance(t, (int, float)):
        return None
    t = float(t)
    if t != t:                       # NaN：与任何值比较都恒假，先剔（不引 math 依赖）
        return None
    if t > now or now - t >= window:  # 双向界定：未来戳剔、窗外旧戳也剔
        return None
    return t


# 生效条件：形参 raw 为 list/tuple 时逐元素按 _window_stamp 收敛后返回新列表（保持原序）；raw 非序列（None/标量/str/dict 等）返回空列表；
def _window_stamps(raw, now, window) -> list:
    """时间戳序列的类型收敛 + 双向界定（判据单点同 _window_stamp）。

    序列本身非 list/tuple（外部把 ratelimit 槽整个写成标量）也归为「无记账」——
    旧实现直接迭代它会 TypeError（#354 P1-11 的相邻形态，rate[key] 非 list）。
    """
    if not isinstance(raw, (list, tuple)):
        return []
    return [v for v in (_window_stamp(t, now, window) for t in raw)
            if v is not None]


# ---------- 写入侧：前置限流 + 同构聚合 ----------

# 生效条件：仅当 layer=="contextual" 且 enabled() 为真、且 importance_hint 为 None 或 float(importance_hint)<0.7（转换抛 TypeError/ValueError 时同样继续）才进入限流，此时 now 为 None 取 time.time()，key 取 f"{layer}:{role or 'user'}"（role 为 None/空串等假值回落 'user'）：同 key 窗口内条数 ≥ RATE_MAX 返回 DEFER；否则 signature 非空且 st["sigs"] 中该签名记录在 CONVERGE_WINDOW 内、nid 有效且 cg.get(rec["nid"]) 存在时，正文 strip 后完全一致返回 DROP、不一致返回 CONVERGE；其余情形返回 None 放行。
def check(cg, content, layer="contextual", role=None, node_id=None,
          importance_hint=None, now=None, sensitivity=None):
    """remember_gated 前置限流。None=放行；否则 {"verdict": DEFER|CONVERGE}。

    - DEFER：同 (layer, role) 滑动窗口内已满 RATE_MAX 条（被拒者也计数，
      防持续灌水每条都重算窗口）
    - CONVERGE：签名命中（CONVERGE_WINDOW 内、目标节点仍在）→ 应并入
      rec["nid"]；签名首见即预占位（nid=node_id），assess 若 DEFER/DROP
      该节点未落盘，下次 cg.get 失效自动重置——自愈
    """
    if layer != "contextual" or not enabled():
        return None
    if importance_hint is not None:
        try:
            if float(importance_hint) >= 0.7:
                return None                     # 保护优先语义：跳过限流
        except (TypeError, ValueError):
            pass
    now = float(now if now is not None else time.time())
    st = _load(cg)
    key = f"{layer}:{role or 'user'}"
    # 1) 同源频率限制
    win = _window_stamps(st["rate"].get(key), now, RATE_WINDOW)
    if len(win) >= RATE_MAX:
        win.append(now)
        st["rate"][key] = win[-RATE_MAX * 4:]
        _save(cg, st)
        return {"verdict": "DEFER", "limiter": "rate", "reason":
                f"ratelimit:{key}:>{RATE_MAX}in{int(RATE_WINDOW)}s"}
    # 2) 同构聚合（加密级跳过签名——见 _is_encrypted_level，issue #313）
    sig = template_signature(content)
    if sig and not _is_encrypted_level(sensitivity):
        rec = st["sigs"].get(sig)
        if not isinstance(rec, dict):
            # 记账被外部损坏（dict 内混入标量/序列）：按「无记录」重占位，不把
            # 崩溃带给调用方——与 _load 的顶层类型闸同一判据面（#354 P1-9 同族）。
            rec = None
        if rec and _window_stamp(rec.get("t"), now, CONVERGE_WINDOW) \
                is not None and rec.get("nid"):
            tgt = cg.get(rec["nid"])
            if tgt:
                if (tgt.get("content") or "").strip() \
                        == (content or "").strip():
                    # 与既有节点正文完全一致：零新信息 → 交回旧闸门语义
                    # DROP（不落库、不追加聚合行、不强化既有）——对齐
                    # forgetting 闸门「确定性内部冗余 → DROP 先于 MERGE」
                    # 纪律；同模板但内容不同才走聚合（那才是流水治理）
                    _push_rate(st, key, now)
                    _save(cg, st)
                    return {"verdict": "DROP", "limiter": "exact_dup",
                            "target": rec["nid"],
                            "reason": f"exact_dup_of:{rec['nid']}"}
                rec["n"] = int(rec.get("n") or 1) + 1
                rec["last"] = now
                st["sigs"][sig] = rec
                _push_rate(st, key, now)
                _save(cg, st)
                return {"verdict": "CONVERGE", "limiter": "converge",
                        "target": rec["nid"], "sig": sig[:40], "n": rec["n"],
                        # issue #148：把两侧密级带出闸门，供审计与上层判据复用
                        # （真正的拒绝判据仍只在 security.merge_downgrades 单点）。
                        "target_sensitivity":
                            (tgt.get("frontmatter") or {}).get("sensitivity"),
                        "incoming_sensitivity": sensitivity,
                        "reason": f"converge:{sig[:40]}#{rec['n']}"}
        st["sigs"][sig] = {"nid": node_id, "t": now, "n":
                           int((rec or {}).get("n") or 1),
                           "sk": sig[:60],
                           "sens": sensitivity}      # issue #148：声明密级随签名记账
    _push_rate(st, key, now)
    _save(cg, st)
    return None


# 生效条件：形参 content 的 template_signature 非空，且 st["sigs"].get(sig) 为 None 或该记录 nid 为假值时，写入 {"nid": node_id, ...} 并保存；否则不写并返回 None；
def record_accepted(cg, node_id, content, now=None, sensitivity=None) -> None:
    """ACCEPT 落盘后确保签名→节点映射存在（check 已预占位，此处兜底）。"""
    sig = template_signature(content)
    # issue #313：加密级不落签名（与 check 同一判据单点）
    if not sig or _is_encrypted_level(sensitivity):
        return
    now = float(now if now is not None else time.time())
    st = _load(cg)
    rec = st["sigs"].get(sig)
    if not isinstance(rec, dict):        # #354 P1-9 同族：坏型按「无记录」处理
        rec = None
    if rec is None or not rec.get("nid"):
        st["sigs"][sig] = {"nid": node_id, "t": now, "n":
                           int((rec or {}).get("n") or 1), "sk": sig[:60],
                           "sens": sensitivity}      # issue #148：声明密级随签名记账
        _save(cg, st)


# 生效条件：cg.get(target) 为假值返回 {"ok": False, "error": "target_missing"}；随后以节点真层/敏感度过 protect.guard_overwrite（层闸 + 保护闸，override 为真时先快照 + 审计）；通过后按 forgetting.aggregate_line（单点）把新正文里目标还没有的行追加为聚合行、fm["merge_count"]=int(fm.get("merge_count") or 0)+1 后 _write_node 落盘（重要性不变），并把 session/actor 归属并列记进 fm（forgetting.note_source）；返回 {"ok": True, "merge_count": 新值, "content_sink": 去向, "source": 归属}。
def converge_into(cg, target: str, content: str, override=False, actor=None,
                  session=None, sensitivity=None) -> dict:
    """同构聚合落库：正文追加一行【聚合】摘要，merge_count+1。

    importance **不变**——流水不该越聚越重要（与 forgetting.reinforce
    的 +0.05 相反）。

    B3（2026-09-30）：追加内容改由 `forgetting.aggregate_line`（**单点**）
    生成——原口径 `" ".join(content.split())[:80]` 会把落在 80 字外的新值
    整体丢掉（P-3 实测：端口 9090 变体在库中 0 次落盘），与「新正文不许被
    静默丢弃」同病；现改为「目标正文还没有的行」逐行追加、不截断，纯重复
    零追加。**不变**的部分：目标节点不变、merge_count+1、importance 不动、
    层闸/保护闸仍在写盘之前。
    H3：`session` 槽把新写入方归属并列落 fm（`forgetting.note_source`）。

    N215（2026-09-28，同族未接线写点）：本函数此前**裸调 `cg._write_node`**
    追加既有节点正文，唯一入口 `mdcos.remember_gated` 的 CONVERGE 分支（:3336）
    全程无 principal 层闸、无保护闸、无快照无审计。`writelimit.check` 的形参层
    判据（:141）只看调用方声明的 layer、签名映射落的是 `node_id`——攻击链：
    先以 `(node_id=<anchor 节点>, layer='contextual')` 预占位签名（该次 `add`
    被保护闸拒，但 `sig→anchor id` 已落盘），再换正文重发 → CONVERGE →
    **anchor 层不可篡改节点被无痕追加聚合行**（可反复追加、merge_count 递增）。
    落盘前统一过 `protect.guard_overwrite`（单点）。
    """
    e = cg.get(target)
    if not e:
        return {"ok": False, "error": "target_missing"}
    fm = dict(e.get("frontmatter") or {})
    protect.guard_overwrite(cg, target, layer=fm.get("layer"),
                            sensitivity=fm.get("sensitivity"),
                            override=override, actor=actor)
    # issue #148（C 组）**落盘前**判降密级：声明密级低于目标节点密级的合并，会把
    # 低密级明文写进高密级节点，而目标 frontmatter 的 sensitivity 不变 ⇒ 明文获得
    # 目标档的可见性（访客可读）。判据走**唯一单点** security.merge_downgrades；
    # 判为降密级即 fail-closed **不写盘**（不追加聚合行、不动 merge_count、不标脏）。
    from .security import merge_downgrades as _merge_downgrades
    if _merge_downgrades(fm.get("sensitivity"), sensitivity):
        return {"ok": False, "error": "merge_downgrade_refused",
                "target": target,
                "target_sensitivity": fm.get("sensitivity"),
                "incoming_sensitivity": sensitivity,
                "detail": "合并会降低该内容的有效密级（incoming 密级**高于**目标节点"
                          "密级 ⇒ 合并后只按目标档可见）——fail-closed 未写盘："
                          "高密级明文不得并入低密级节点。",
                "hint": "如需保留该内容：确认其确为该档后以不高于目标节点密级的声明"
                        "重新写入，或不走 CONVERGE 而新建独立节点（add，保持其声明密级）。"}
    # 延迟导入：forgetting 是聚合行/归属的单点实现（writelimit 不反向被它依赖，
    # 无环）；放函数内避免模块导入期把 md_cg.forgetting 的依赖面（mdcg/bigrams）
    # 拉进本模块的加载链。
    from . import forgetting
    new_body, line, line_no = forgetting.aggregate_line(e.get("content"), content)
    fm["merge_count"] = int(fm.get("merge_count") or 0) + 1
    fm["last_merge_at"] = time.time()
    source = forgetting.note_source(fm, session=session, actor=actor)
    cg._write_node(target, os.path.join(cg.root, e["path"]), fm,
                   new_body if new_body is not None else (e.get("content") or ""),
                   durable=True)
    entry = cg.index["nodes"].get(target)
    if entry is not None:
        entry.update({"merge_count": fm["merge_count"],
                      "last_merge_at": fm["last_merge_at"]})
        if fm.get("merge_sources"):
            entry["merge_sources"] = fm["merge_sources"]
        cg._dirty[target] = entry
    return {"ok": True, "merge_count": fm["merge_count"],
            "content_sink": {
                "node_id": target,
                "action": "appended" if line else "already_covered",
                "line": line, "line_no": line_no,
                "chars": len(new_body if new_body is not None
                             else (e.get("content") or ""))},
            "source": source}


# ---------- 读侧：已落盘同构组的周期整理（sustain 巡检入口）----------

# 生效条件：形参 e 为 cg.get 返回的节点 dict 时，frontmatter["tags"] 含 TIDY_TAG 或 frontmatter[lifecycle.STATE_FIELD]=="converged" 返回 True，否则 False（e 无 frontmatter 也不报错）；
def _already_tidied(e: dict) -> bool:
    """该节点是否已被 tidy 整理过（issue #190 幂等判据）。

    只认既有标记：frontmatter["tags"] 里的 TIDY_TAG（历史存量），或显式状态
    字段 lifecycle.STATE_FIELD == "converged"（② 显式状态机收口后由
    lifecycle.stamp 写入）。不新增字段、不做迁移，所以修复前已落盘的历史
    节点天然被认账；两者都缺（未整理过的新节点）返回 False。
    """
    fm = e.get("frontmatter") or {}
    if TIDY_TAG in (fm.get("tags") or []):
        return True
    return fm.get(lifecycle.STATE_FIELD) == "converged"


# 生效条件：形参 cg 的 index["nodes"] 中 layer=="contextual" 且 cg.get 可取的节点按 template_signature 非空分组，扫描到 scanned>=limit（limit=0 立即 break）为止，成员数≥min_group 的组按成员数降序进入 planned（_already_tidied 为真的节点在扫描阶段即跳过、只计入 out["already_tidied"]）；apply 为真且 planned 非空时，逐组循环且累计 n_ap>=MAX_APPLY 后不再开新组（组内成员仍可继续 n_ap 累加超过），跳过 protected/immutable 成员，保留每组最早节点并追加整理聚合、成员降权，输出 out（out["planned"] 仅取 planned[:20]；apply 假或 planned 空直接返回 out）；
def tidy_contextual(cg, apply=False, min_group=3, actor="sustain_tidy",
                    limit=2000) -> dict:
    """扫描 contextual 层已落盘节点，按模板签名分组并整理。

    对 ≥min_group 的同构组（apply=True 时）：
      · 保留最早节点：正文追加【整理聚合】成员清单段落
      · 成员节点：tags += tidy:converged、importance×0.5（下限 0.1）
    永不删除节点（可逆、可审计）；protected/immutable 成员跳过；
    apply=False 只盘点不动任何节点。

    幂等（issue #190）：已被整理过的节点（tags 含 tidy:converged 或
    lifecycle_state=="converged"）在扫描阶段就跳过——不进组、不再降权、不再
    重写保留节点，所以同一组第 2 轮起 planned 为空、零落盘。返回 dict 新增
    键 already_tidied（本次跳过的已整理节点数），其余键与语义不变。
    """
    groups: dict = {}
    already_tidied = 0
    scanned = 0
    for nid, entry in list(getattr(cg, "index", {})
                           .get("nodes", {}).items()):
        if scanned >= limit:
            break
        if entry.get("layer") != "contextual":
            continue
        e = cg.get(nid)
        if not e:
            continue
        scanned += 1
        if _already_tidied(e):
            already_tidied += 1
            continue
        sig = template_signature(e.get("content") or "")
        if sig:
            groups.setdefault(sig, []).append(e)
    planned = []
    for sig, members in groups.items():
        if len(members) < min_group:
            continue
        members.sort(key=lambda m: (float((m.get("frontmatter") or {})
                                          .get("created_at", 0) or 0),
                                    str(m.get("id") or "")))
        planned.append({"sig": sig[:40], "keep": members[0]["id"],
                        "members": [m["id"] for m in members[1:]]})
    planned.sort(key=lambda p: (-len(p["members"]), str(p.get("sig") or "")))
    out = {"t": time.time(), "actor": actor, "scanned": scanned,
           "groups": len(planned),
           "members": sum(len(p["members"]) for p in planned),
           "already_tidied": already_tidied,
           "apply": bool(apply), "planned": planned[:20], "applied": []}
    if not apply or not planned:
        return out
    n_ap = 0
    for p in planned:
        if n_ap >= MAX_APPLY:
            break
        keep = cg.get(p["keep"])
        if not keep:
            continue
        lines = [f"\n\n# 整理聚合（tidy {time.strftime('%Y-%m-%d')}）："
                 f"同模板成员 {len(p['members'])} 条"]
        # issue #360（2026-10-16 DSH 端）：**整理不看成员密级** ⇒ private 成员解密后
        # 的正文前 48 字被明文追加进组内最早的保留节点（密级沿用保留节点的
        # internal），internal 身份读那条 private 节点得 None、读保留节点却能看到
        # 其内容。判据复用 #148 的唯一单点 security.merge_downgrades（成员档高于
        # 保留档即**跳过、不写摘录、也不降级它**）；与 #359（审核 merge）同根
        # 不同落点。成员档未记录时 merge_downgrades(..., None) 恒 False ⇒ 行为不变。
        from .security import merge_downgrades as _md360
        _ksens = (keep.get("frontmatter") or {}).get("sensitivity")
        for mid in p["members"]:
            m = cg.get(mid)
            if not m:
                continue
            mfm = dict(m.get("frontmatter") or {})
            if mfm.get("protected") or mfm.get("immutable"):
                continue
            if _md360(_ksens, mfm.get("sensitivity")):
                continue
            first = " ".join((m.get("content") or "").split())[:48]
            lines.append(f"- {mid} {first}")
            _demote(cg, m)
            n_ap += 1
        kfm = dict(keep.get("frontmatter") or {})
        # issue #541：keep 是**既有节点**，本函数此前裸调 cg._write_node
        # ⇒ 不判层闸、不判保护闸、不拍快照、不写 _protected_audit.jsonl，
        # 于是 `immutable` / `protected` 节点被**静默覆写且零审计**
        # （实测：immutable keep 正文被改写、新增快照 0、审计 0 行；
        #  而姊妹函数 converge_into 对同一节点正确抛 ProtectionError）。
        #
        # 注意上方 `if mfm.get("protected") or mfm.get("immutable"): continue`
        # 只作用于 **members**（被并入的成员），**不覆盖 keep 本身** ——
        # 保留节点恰是缺闸的那一个。故此处补齐同一单点保护闸，
        # 与 converge_into（:246）同款调用形态（layer/sensitivity 取真值、override=False）。
        #
        # 触发面是**无人值守**的：AUTO_DEFAULTS["auto_tidy"] 缺省 True、
        # DEFAULT_TIDY_INTERVAL=21600（6h），_tick_tidy 无 require_admin。
        protect.guard_overwrite(cg, keep["id"], layer=kfm.get("layer"),
                                sensitivity=kfm.get("sensitivity"),
                                override=False, actor=actor)
        kfm["merge_count"] = int(kfm.get("merge_count")
                                 or 0) + len(p["members"])
        kfm["last_merge_at"] = time.time()
        cg._write_node(keep["id"], os.path.join(cg.root, keep["path"]),
                       kfm, (keep.get("content") or "") + "\n".join(lines),
                       durable=True)
        out["applied"].append({"keep": p["keep"],
                               "converged": len(p["members"])})
    out["applied_count"] = n_ap
    flush = getattr(cg, "flush", None)
    if callable(flush):
        flush()
    return out


# 生效条件：e 提供 "id"/"path"，对其 frontmatter 副本在 tags 不含 TIDY_TAG 时追加该 tag、importance 置 round(max(0.1, float(fm.get("importance",0.5) or 0)*0.5), 3)，经 lifecycle.stamp(fm,"converged",reason=...,actor=actor) 后 _ok 为真时 setdefault(lifecycle.STATE_FIELD,"converged")，随后 cg._write_node 落盘，且 cg.index["nodes"].get(e["id"]) 非 None 时同步 tags/importance/状态字段到索引。
def _demote(cg, e: dict, actor: str = "sustain_tidy") -> None:
    """成员降权：tags += tidy:converged，importance×0.5（下限 0.1）。

    ② 显式状态机收口（2026-09-16）：降权动作同时把生命周期状态推进到
    `converged`——`tidy:converged` **tag 保留为兼容别名**（既有测试与历史数据都
    在读它），但「这节点已定型」从此由 `lifecycle_state` 这一显式字段承载，
    迁移合法性由 `lifecycle.stamp` 单点裁决。状态与 tags/importance 走**同一次
    写盘**（不额外多写一遍文件）。裁决失败（受保护成员，正常路径已被
    `tidy_contextual` 跳过）**不阻断**降权本身：tags/importance 已生效，只是不改
    状态——不假装成功。
    """
    fm = dict(e.get("frontmatter") or {})
    tags = list(fm.get("tags") or [])
    if TIDY_TAG not in tags:
        tags.append(TIDY_TAG)
    fm["tags"] = tags
    fm["importance"] = round(max(0.1, float(fm.get("importance", 0.5)
                                          or 0) * 0.5), 3)
    _ok, _code, _why = lifecycle.stamp(
        fm, "converged", reason="tidy 同构聚合已定型", actor=actor)
    if _ok:
        # 幂等迁移（已是 converged）不会写字段 → 补成显式，索引口径才一致
        fm.setdefault(lifecycle.STATE_FIELD, "converged")
    cg._write_node(e["id"], os.path.join(cg.root, e["path"]), fm,
                   e.get("content") or "")
    entry = cg.index["nodes"].get(e["id"])
    if entry is not None:
        entry.update({"tags": tags, "importance": fm["importance"],
                      lifecycle.STATE_FIELD: fm.get(lifecycle.STATE_FIELD)})
        cg._dirty[e["id"]] = entry


# 生效条件：形参 cg 使 _load(cg) 返回 dict 时，返回 enabled()、st["sigs"] 计数、nid 为真的 live_sigs、st["rate"] 键数与 STATE_FILE 组成的摘要；
def stats(cg) -> dict:
    """限流状态摘要（诊断面）。"""
    st = _load(cg)
    live_sigs = sum(1 for r in st["sigs"].values()
                    if isinstance(r, dict) and r.get("nid"))
    return {"enabled": enabled(), "sigs_tracked": len(st["sigs"]),
            "sigs_live": live_sigs,
            "rate_keys": len(st["rate"]),
            "state_file": STATE_FILE}