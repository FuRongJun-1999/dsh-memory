"""结构层任务实体 —— structural 层正式业务写入口（2026-09-16）。

使用者裁定（按既有记忆分层，三层分工）：

    任务                       → structural 层（与「协议/自我/信任」同级；
                                 跨会话稳定、不可遗忘——`DEMOTE_CONFIDENCE`
                                 的降级面只覆盖 knowledge 层）
    执行任务的中间信息          → contextual 层（不落库，由 AI 上下文自理）
    任务知识 / 外部参考 / 交接文档 → knowledge 层（被验证的重要信息，按需调用；
                                 节点 tags 记 `task:<slug>` 实现反向关联）

消除 AI 失忆四症状：

    ① 忘记已实现的工程 → `session_tasks()` 供 `session_recall` 装配
                        「进行中 + 近期完成」，新会话开机即见
    ② 计划与实际不符   → `plan_add()` 累积「计划变更」节，偏差可追溯
    ③ 缺核验           → 状态迁 `done` 时「结果」节必填（缺一不收，
                        对齐 `branches.BRANCH_MARKS` 的同款闸）
    ④ 换表述即新任务   → 身份判据 ＝ 语义命名 slug（**刻意不用内容哈希**）；
                        `find_similar()` 只提示疑似同族，不自动合并

为什么身份不用内容哈希：`add_goal` 的 `goal_<sha1(text)>` 正是第 ④ 点的病根——
同一目标换个说法就变成新 goal、重复开工。任务名是使用者给的稳定标识，
重复登记必须更新原卡而不是再开一张。

与 goals 的关系：**不双写**。goals 是「检索定向槽」（谁该被检索到），任务是
「工程台账」（做到哪一步、结果是什么）——语义不同，双写必漂移（既有实证：
覆盖写会让库正文回退首版）。会话装配面各自成段。

与 branches 同哲学：库层函数收 `cg`；写盘走 `cg.add`（`require_layer_write`
权限闸自动生效，库层不绕闸）；生命周期事件走 `cg._audit`（不新造日志格式，
审计失败绝不阻断主流程）。

正文格式 ＝ CCG 六要素 ＋ 三节（计划 / 计划变更 / 结果）：

    # 功能名：<任务名>
    # 生效条件：<任务适用范围；填「无条件」则豁免资格判定中的正条件确认>
    # 子功能：<任务目标>
    # 执行：<状态>｜<进度说明>
    # 验证方式：<验收判据>
    # 不适用条件：<边界>

    ## 计划
    ## 计划变更
    ## 结果
"""
from __future__ import annotations

import re
import time

TASK_STATUSES = ("active", "blocked", "done", "dropped")

#: 状态中文投影（只用于正文可读性，机械判据始终用英文值）
STATUS_ZH = {"active": "进行中", "blocked": "受阻", "done": "完成", "dropped": "放弃"}

#: 任务节点统一标签（第一个是身份标记，第二个是任务族标记）
TASK_TAG = "task"
TASK_PREFIX = "task_"

#: ≥0.7 会被 protect 自动打「不可遗忘」标记——即「任务结果必须得到维护」的
#: 架构层保障：普通 forget 搬不走它，只有显式解保护才动得了。
DEFAULT_IMPORTANCE = 0.8

#: 正文节名
SEC_PLAN = "计划"
SEC_CHANGE = "计划变更"
SEC_RESULT = "结果"

#: 语义 slug 守卫——首字符须为中文/字母/数字，其后允许 `_ . -`，总长 ≤64。
#: 与 `branches._BRANCH_RE` 同风格（防路径穿越与非法文件名），但放宽到 Unicode：
#: 任务名多为中文，缩到 ASCII 会逼使用者起英文别名，反而制造第二个身份。
_SLUG_RE = re.compile(r"^[0-9A-Za-z\u4e00-\u9fff][0-9A-Za-z\u4e00-\u9fff_.-]{0,63}$")
_ILLEGAL_RE = re.compile(r"[^0-9A-Za-z\u4e00-\u9fff_.-]+")

# ---------------------------------------------------------------- 命名与解析

# 生效条件：name 为 None/空串或 strip 后为空时返回空串，否则把 `/`、`\`、`..` 及 _ILLEGAL_RE 命中字符折叠为 `-`、压缩连续 `-` 并去首尾 `-.` 后取前 64 字符再去首尾 `-.` 返回；
def slugify(name: str) -> str:
    """任务名 → 语义 slug（稳定标识；同 slug 即同任务）。

    只做「可安全落文件名」的归一：路径分隔符与非法字符折叠为 `-`，连续 `-`
    压成一个。**不做语义改写**（不翻译、不去停用词）——slug 是对外可见的
    身份，擅自改写会让使用者按原名检索时对不上号。
    """
    s = (name or "").strip()
    if not s:
        return ""
    s = s.replace("/", "-").replace("\\", "-").replace("..", "-")
    s = _ILLEGAL_RE.sub("-", s)
    s = re.sub(r"-{2,}", "-", s).strip("-.")
    return s[:64].strip("-.")


# 生效条件：name（`name or ""` 后 strip）先剥掉已有的 TASK_PREFIX 再 slugify，结果非空且被 _SLUG_RE.match 命中时返回 TASK_PREFIX + slug；name 为假值或归一化后为空、不匹配时返回 ""。
def task_node_id(name: str) -> str:
    """任务名或节点 id → 规范节点 id（`task_<slug>`）。非法名返回空串。"""
    s = (name or "").strip()
    if s.startswith(TASK_PREFIX):
        s = s[len(TASK_PREFIX):]
    slug = slugify(s)
    if not slug or not _SLUG_RE.match(slug):
        return ""
    return TASK_PREFIX + slug


# 生效条件：v 为 None 或 str(v).strip() 为 "" 时返回 False，否则返回 True。
def _has(v) -> bool:
    """「本次调用是否提供了该字段」——空串/None 一律视为未提供（不静默清空）。"""
    return v is not None and str(v).strip() != ""


# 生效条件：无必需形参且无模块级常量约束，恒返回 time.strftime("%Y-%m-%d %H:%M") 的当前时间文本。
def _today() -> str:
    return time.strftime("%Y-%m-%d %H:%M")


# 生效条件：content（`content or ""` 后 splitlines）中有某行 strip 后以 `# ` + field + `：` 开头时，返回该行该前缀之后的去空白内容；content 为假值或无此匹配行时返回 ""。
def _field_line(content: str, field: str) -> str:
    """从正文抽 `# <字段>：` 行的值（与 `mdcos._ccg_field` 同源口径，
    本模块不反向 import mdcos，避免包内循环依赖）。"""
    pre = "# " + field + "："
    for line in (content or "").splitlines():
        s = line.strip()
        if s.startswith(pre):
            return s[len(pre):].strip()
    return ""


# 生效条件：(content or "") 的行中 strip 后以 "## " 开头者成为节名 s[3:].strip() 并切换当前节，其余行累入当前节，返回各节内容以 "\n" join 后 strip 的字典；无任何标题行时仅返回 {"__body__": 全篇 strip}；content 为 None/空串时返回 {"__body__": ""}。
def sections(content: str) -> dict:
    """正文 → `{节名: 节内容}`；无标题部分归入 `__body__`。"""
    out: dict = {"__body__": []}
    cur = "__body__"
    for line in (content or "").splitlines():
        s = line.strip()
        if s.startswith("## "):
            cur = s[3:].strip()
            out.setdefault(cur, [])
            continue
        out.setdefault(cur, []).append(line)
    return {k: "\n".join(v).strip() for k, v in out.items()}


# 生效条件：t = (text or "").strip()，t 为 ""/"（无）"/"（未填）" 时返回 ""，否则 len(t) <= n（默认 200）时返回 t，超出时返回 t[:n].rstrip() + "…"。
def _brief(text: str, n: int = 200) -> str:
    t = (text or "").strip()
    if t in ("", "（无）", "（未填）"):
        return ""
    return t if len(t) <= n else t[:n].rstrip() + "…"


# 生效条件：以 (old_text or "").strip() 为 base（base 为「（无）」或「（未填）」时置空），_has(change) 判定为假时返回 base or "（无）"，为真时拼出 `- [今日] change.strip()`，base 非空返回 base+"\n"+该行再 strip，base 为空只返回该行；
def _append_change(old_text: str, change: str) -> str:
    """「计划变更」节追加一行（累积式，不覆盖历史）。"""
    base = (old_text or "").strip()
    if base in ("（无）", "（未填）"):
        base = ""
    if not _has(change):
        return base or "（无）"
    line = "- [%s] %s" % (_today(), str(change).strip())
    return (base + "\n" + line).strip() if base else line


# 生效条件：name 为必需形参（`name or ""` 后 strip 填 `# 功能名：` 行）；condition、goal、acceptance、boundary、plan、changes、result 各经 _has 判定，未提供时分别落「无条件」「（未填：任务目标待补）」「other」「任务转 done/dropped 终态后不再作为进行中任务参与装配」「（未填）」「（无）」与空串；status 经 STATUS_ZH.get(status, status) 映射、未命中时原样输出，note 经 _has 为真时以 `｜` 拼在执行行后。
def render(name: str, *, condition: str = "", goal: str = "", status: str = "active",
           note: str = "", acceptance: str = "", boundary: str = "",
           plan: str = "", changes: str = "", result: str = "") -> str:
    """按 CCG 六要素 + 三节渲染任务正文。"""
    exec_line = STATUS_ZH.get(status, status)
    if _has(note):
        exec_line = exec_line + "｜" + str(note).strip()
    return "\n".join([
        "# 功能名：%s" % (name or "").strip(),
        "# 生效条件：%s" % (condition.strip() if _has(condition) else "无条件"),
        "# 子功能：%s" % (goal.strip() if _has(goal) else "（未填：任务目标待补）"),
        "# 执行：%s" % exec_line,
        "# 验证方式：%s" % (acceptance.strip() if _has(acceptance) else "other"),
        "# 不适用条件：%s" % (boundary.strip() if _has(boundary)
                              else "任务转 done/dropped 终态后不再作为进行中任务参与装配"),
        "",
        "## %s" % SEC_PLAN,
        (plan.strip() if _has(plan) else "（未填）"),
        "",
        "## %s" % SEC_CHANGE,
        (changes.strip() if _has(changes) else "（无）"),
        "",
        "## %s" % SEC_RESULT,
        (result.strip() if _has(result) else ""),
        "",
    ])


# ---------------------------------------------------------------- 读写

# 生效条件：nid 为假值（None/空串）时返回 None；否则 cg.get(nid) 命中且其 frontmatter.layer == "structural"、TASK_TAG 在 frontmatter.tags（`or []`）中时，返回 {id, fm, content, path, sec}（sec 为 sections(content)）；记录缺失或层/标签不符时返回 None。
def _read_task(cg, nid: str):
    """读回任务卡；层或标签不符一律视为不存在（防串号：别的节点占用了同 id）。"""
    if not nid:
        return None
    rec = cg.get(nid)
    if not rec:
        return None
    fm = rec.get("frontmatter") or {}
    if fm.get("layer") != "structural" or TASK_TAG not in (fm.get("tags") or []):
        return None
    content = rec.get("content") or ""
    return {"id": nid, "fm": fm, "content": content,
            "path": rec.get("path"), "sec": sections(content)}


# 生效条件：以 layer="structural"、tags=list(tags)、importance=float(importance)、override=True、task_name=name、task_status=status、task_updated_at=time.time()、actor=actor or "task" 等构成 kw，extra 为真值时经 kw.update(extra) 追加覆盖，随后调用 cg.add(nid, content, **kw) 并返回其结果；
def _write(cg, nid: str, name: str, content: str, status: str, tags,
           importance: float, actor, extra: dict = None):
    """唯一写盘点——走 `cg.add`（权限闸 / 归属注入全部复用既有链路）。

    `override=True` 的含义：任务更新是**系统自身的幂等更新**（同 slug 即同任务），
    显式声明该意图后，若节点已带 `protected`/`self_state` 标记，protect 会走
    「旧版本快照 + 审计留痕」的放行分支而不是静默改写——任务台账天然获得版本快照。
    """
    kw = dict(layer="structural", tags=list(tags), importance=float(importance),
              confidence=1.0, verification_basis="other",
              override=True, consistency=False,
              task_name=name, task_status=status,
              task_updated_at=time.time(), actor=actor or "task")
    if extra:
        kw.update(extra)
    return cg.add(nid, content, **kw)


# 生效条件：cg 具有 _audit 属性（getattr(cg, "_audit", None) 非 None）时以 (op, nid, **meta) 调用它，且其中抛出的任何异常被吞掉；cg 无该属性时不调用，两种路径均不返回内容。
def _audit(cg, op: str, nid: str, **meta) -> None:
    """生命周期留痕；审计失败绝不阻断主流程（与 branches._audit 同哲学）。"""
    a = getattr(cg, "_audit", None)
    if a is None:
        return
    try:
        a(op, nid, **meta)
    except Exception:                                   # noqa: BLE001
        pass


# 生效条件：_read_task(cg, nid) 命中任务卡时返回摘要条目——id 取 rec['id']，name 取 fm.task_name 或（缺失/假值时）rec['id']，status 取 fm.task_status 或 "active"，plan/changes/result 取对应节的 _brief 摘要（缺节回落 ""），并带 created_at/updated_at/path；未命中时返回 None。
def _entry(cg, nid: str):
    """节点 id → 对外任务条目（摘要形态；全字段查 `get_task`）。"""
    rec = _read_task(cg, nid)
    if not rec:
        return None
    fm, sec = rec["fm"], rec["sec"]
    return {"id": rec["id"],
            "name": fm.get("task_name") or rec["id"],
            "status": fm.get("task_status") or "active",
            "plan": _brief(sec.get(SEC_PLAN, "")),
            "changes": _brief(sec.get(SEC_CHANGE, "")),
            "result": _brief(sec.get(SEC_RESULT, "")),
            "created_at": fm.get("task_created_at"),
            "updated_at": fm.get("task_updated_at"),
            "path": rec["path"]}


# ---------------------------------------------------------------- 写操作

# 生效条件：slugify(name) 为空串或不匹配 _SLUG_RE 时返回 {'ok': False, 含 slug 的非法名 error}；否则 st = str(status if _has(status) else (旧卡 task_status or "active")).strip().lower()，st 不在 TASK_STATUSES 时返回未知状态错误，st == "done" 且合并后结果节 _has(new_res) 为假时返回「转 done 必须填结果」拒收，其余情况渲染写入并返回按 old 是否为 None 区分新建/更新的 out。
def upsert(cg, name: str, *, plan: str = None, status: str = None,
           result: str = None, condition: str = None, goal: str = None,
           acceptance: str = None, boundary: str = None, change: str = None,
           note: str = None, tags=None, importance: float = None,
           actor: str = None) -> dict:
    """登记或更新一张任务卡（同 slug 即同任务；重复登记不新建卡）。

    未提供的字段**沿用旧值**（不静默清空）；`status="done"` 且合并后「结果」节
    仍为空 → 拒收，盘上内容不变。

    :param note: 进度说明，落 `# 执行：` 行（`｜` 之后）。
    :param change: 本次发现的新问题/计划偏差，追加到「计划变更」节。
    """
    slug = slugify(name)
    if not slug or not _SLUG_RE.match(slug):
        return {"ok": False,
                "error": "任务名非法（slug=%r）；要求：中文/字母/数字起头，"
                         "仅含中文/字母/数字/_ . -，长度 ≤64" % (slug,)}

    nid = TASK_PREFIX + slug
    old = _read_task(cg, nid)
    prev_fm = old["fm"] if old else {}
    prev = old["sec"] if old else {}

    display = (name or "").strip() or prev_fm.get("task_name") or slug
    st = str(status if _has(status) else (prev_fm.get("task_status") or "active")).strip().lower()
    if st not in TASK_STATUSES:
        return {"ok": False, "node_id": nid,
                "error": "未知任务状态：%r（可选 %s）" % (st, list(TASK_STATUSES))}

    # 未提供 → 沿用旧值（结果与计划绝不被静默清空）
    new_plan = plan if _has(plan) else prev.get(SEC_PLAN, "")
    new_res = result if _has(result) else prev.get(SEC_RESULT, "")
    new_cond = condition if _has(condition) else _field_line(old["content"], "生效条件") if old else ""
    new_goal = goal if _has(goal) else _field_line(old["content"], "子功能") if old else ""
    new_acc = acceptance if _has(acceptance) else _field_line(old["content"], "验证方式") if old else ""
    new_bnd = boundary if _has(boundary) else _field_line(old["content"], "不适用条件") if old else ""
    new_note = note if _has(note) else _exec_note(old["content"]) if old else ""
    new_changes = _append_change(prev.get(SEC_CHANGE, ""), change)

    if st == "done" and not _has(new_res):
        return {"ok": False, "node_id": nid,
                "error": "任务转 done 必须填写「结果」——结果不可缺失（缺一不收）",
                "hint": "补 result 后重试；盘上内容未变更"}

    content = render(display, condition=new_cond, goal=new_goal, status=st,
                     note=new_note, acceptance=new_acc, boundary=new_bnd,
                     plan=new_plan, changes=new_changes, result=new_res)
    tg = list(dict.fromkeys([TASK_TAG, "%s:%s" % (TASK_TAG, slug)]
                            + [str(t) for t in (tags or []) if str(t).strip()]))
    imp = DEFAULT_IMPORTANCE if importance is None else float(importance)
    created = prev_fm.get("task_created_at") or time.time()
    _write(cg, nid, display, content, st, tg, imp, actor,
           extra={"task_created_at": created, "task_slug": slug})
    _audit(cg, "task_open" if old is None else "task_update", nid,
           status=st, slug=slug, name=display)
    out = {"ok": True, "node_id": nid, "name": display, "status": st,
           "created": old is None,
           "result_present": _has(new_res),
           "hint": "新建任务卡" if old is None else "已更新原卡（同 slug 即同任务）"}
    if slug != (name or "").strip():
        # 身份被归一化了就必须说出来——否则调用方按原名去找会找不到卡
        out["slug_normalized"] = slug
    return out


# 生效条件：content 中 `# 执行：` 行的值含 "｜" 时返回第一个 "｜" 之后去空白的内容；content 为假值、无该行或该行值不含 "｜" 时返回 ""。
def _exec_note(content: str) -> str:
    """从 `# 执行：` 行取 `｜` 之后的进度说明。"""
    val = _field_line(content, "执行")
    return val.split("｜", 1)[1].strip() if "｜" in val else ""


# 生效条件：node_id 经 task_node_id 得到非空 nid 且 _read_task 命中该卡时，以旧卡 task_name（缺失/假值回落 nid）、status、result、note、actor 转调 upsert 并返回其结果；node_id 非法时返回 ok=False「非法任务标识」，卡不存在时返回 ok=False「任务不存在」。
def set_status(cg, node_id: str, status: str, *, result: str = None,
               note: str = None, actor: str = None) -> dict:
    """任务状态迁移（进行中/受阻/完成/放弃）。迁 done 且无结果 → 拒收。"""
    nid = task_node_id(node_id)
    if not nid:
        return {"ok": False, "error": "非法任务标识：%r" % (node_id,)}
    old = _read_task(cg, nid)
    if not old:
        return {"ok": False, "node_id": nid, "error": "任务不存在：%s" % nid}
    return upsert(cg, old["fm"].get("task_name") or nid, status=status,
                  result=result, note=note, actor=actor)


# 生效条件：change 经 _has 判定为已提供、且 node_id 经 task_node_id 非空、_read_task 命中该卡时，以旧卡 task_name（缺失/假值回落 nid）与 change、actor 转调 upsert；change 为 None/空串/纯空白时返回 ok=False「计划变更内容为空」，node_id 非法或卡不存在时返回 ok=False 对应错误。
def plan_add(cg, node_id: str, change: str, *, actor: str = None) -> dict:
    """计划变更追加——执行中发现的错误/新问题/偏差，累积进「计划变更」节。"""
    if not _has(change):
        return {"ok": False, "error": "计划变更内容为空"}
    nid = task_node_id(node_id)
    if not nid:
        return {"ok": False, "error": "非法任务标识：%r" % (node_id,)}
    old = _read_task(cg, nid)
    if not old:
        return {"ok": False, "node_id": nid, "error": "任务不存在：%s" % nid}
    return upsert(cg, old["fm"].get("task_name") or nid, change=change, actor=actor)


# ---------------------------------------------------------------- 读操作

# 生效条件：node_id 经 task_node_id 得到的 nid 对应一张 _read_task 命中的任务卡时返回 ok=True 的全字段（condition/goal/acceptance/boundary 由 _field_line 抽取、note 由 _exec_note 抽取、plan/changes/result 取节原文不截断、tags 取 fm.tags 或 []）；否则返回 ok=False，error 中的标识取 nid 或原 node_id。
def get_task(cg, node_id: str) -> dict:
    """单卡全字段读回（计划/变更/结果不截断）。"""
    nid = task_node_id(node_id)
    rec = _read_task(cg, nid)
    if not rec:
        return {"ok": False, "error": "任务不存在：%s" % (nid or node_id)}
    fm, sec = rec["fm"], rec["sec"]
    return {"ok": True, "id": rec["id"], "name": fm.get("task_name") or rec["id"],
            "status": fm.get("task_status") or "active",
            "condition": _field_line(rec["content"], "生效条件"),
            "goal": _field_line(rec["content"], "子功能"),
            "note": _exec_note(rec["content"]),
            "acceptance": _field_line(rec["content"], "验证方式"),
            "boundary": _field_line(rec["content"], "不适用条件"),
            "plan": sec.get(SEC_PLAN, ""),
            "changes": sec.get(SEC_CHANGE, ""),
            "result": sec.get(SEC_RESULT, ""),
            "tags": list(fm.get("tags") or []),
            "created_at": fm.get("task_created_at"),
            "updated_at": fm.get("task_updated_at"),
            "path": rec["path"]}


# 生效条件：status 经 `str(status or "").strip().lower()` 为非空且不在 TASK_STATUSES 时返回 ok=False 未知状态；否则收集 cg.index["nodes"] 中各 _entry 可读任务、按 updated_at 倒序，status 非空时再按该状态过滤，total 为过滤后截断前的条数，limit 为真值时取前 max(int(limit), 1) 条——limit 为 None、0 或空串（假值）时不截断而返回全量 filtered 列表。
def list_tasks(cg, status: str = None, limit: int = None) -> dict:
    """任务清单（按 updated_at 倒序）；status 可选 active/blocked/done/dropped。"""
    st = str(status or "").strip().lower() or None
    if st and st not in TASK_STATUSES:
        return {"ok": False, "error": "未知任务状态：%r（可选 %s）" % (st, list(TASK_STATUSES))}
    items = []
    for nid in list((cg.index.get("nodes") or {}).keys()):
        t = _entry(cg, nid)
        if t:
            items.append(t)
    items.sort(key=lambda x: -(x.get("updated_at") or 0))
    if st:
        items = [t for t in items if t["status"] == st]
    total = len(items)
    if limit:
        items = items[:max(int(limit), 1)]
    return {"ok": True, "count": len(items), "total": total, "tasks": items}


# 生效条件：遍历 cg.index["nodes"]，把 _entry 可读且 status 为 active/blocked 的归入 active、status 为 done 的归入 done，各自按 updated_at 倒序；返回 active[:max(int(active_limit), 0)] 与 done[:max(int(done_limit), 0)]（active_limit/done_limit 传 0 或负数时对应列表为空）以及两组截断前的 active_total/done_total。
def session_tasks(cg, active_limit: int = 5, done_limit: int = 5) -> dict:
    """会话装配用：进行中（active/blocked）+ 近期完成（done，按 updated_at 倒序）。

    这是第 ① 点（忘记已实现的工程）的机制解：上下文装配面在会话开始时把
    「还没做完的」与「刚做完的」一起带出来，agent 不必先想到去查。
    """
    active, done = [], []
    for nid in list((cg.index.get("nodes") or {}).keys()):
        t = _entry(cg, nid)
        if not t:
            continue
        if t["status"] in ("active", "blocked"):
            active.append(t)
        elif t["status"] == "done":
            done.append(t)
    # 终键 id：同 updated_at 并列时定序，否则顺序回落到 cg.index["nodes"]
    # 的物理序（增量路径=写入序，重建路径=nid 序）。
    key = lambda x: (-(x.get("updated_at") or 0),         # noqa: E731
                     str(x.get("id") or ""))
    active.sort(key=key)
    done.sort(key=key)
    return {"ok": True,
            "active": active[:max(int(active_limit), 0)],
            "done": done[:max(int(done_limit), 0)],
            "active_total": len(active), "done_total": len(done)}


# 生效条件：name 经 task_node_id 得 nid，exists 为同 id 任务卡是否被 _read_task 命中；k 经 `int(k or 5)` 再 max(…, 1)（k 为 None/0/空串回落 5，负数取 1）得到 kk，cg.search 抛异常时按无结果处理，只保留元素长度 ≥3、frontmatter.tags 含 TASK_TAG 且 node.id != nid 的条目，返回 out[:kk] 与 note。
def find_similar(cg, name: str, k: int = 5) -> dict:
    """同族任务提示（**只提示，不自动合并**——是否同一任务由调用方裁决）。

    身份判据是命名而非相似度：这里只回答「已经有一张同名的卡吗」与
    「还有哪些卡看起来像」。相似度只能产生候选，不能授予「同一任务」的资格。
    """
    nid = task_node_id(name)
    exact = _read_task(cg, nid) is not None
    kk = max(int(k or 5), 1)
    res = []
    try:
        res, _meta = cg.search(name, layer="structural", k=kk + (1 if exact else 0),
                               record=False)
    except Exception:                                    # noqa: BLE001
        res = []
    out = []
    for item in res or []:
        if not (isinstance(item, (tuple, list)) and len(item) >= 3):
            continue
        node, score, qual = item[0], item[1], item[2]
        fm = (node.get("frontmatter") or {}) if isinstance(node, dict) else {}
        if TASK_TAG not in (fm.get("tags") or []):
            continue
        if node.get("id") == nid:
            continue
        out.append({"id": node.get("id"),
                    "name": fm.get("task_name") or node.get("id"),
                    "status": fm.get("task_status"),
                    "score": round(float(score), 4),
                    "qualification": (qual or {}).get("state") if isinstance(qual, dict) else None})
    return {"ok": True, "node_id": nid, "exists": exact, "similar": out[:kk],
            "note": "仅提示疑似同族任务，不自动合并——终裁权在调用方"}