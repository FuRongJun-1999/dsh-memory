#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""工作纪律 · 认知图投影节点同步器与守卫（真源 → 灵枢认知图 structural 节点）

背景（第4条取证）：纪律除「渲染产物」外还有一份**认知图投影**——认知图
`structural/` 下若干 `work-discipline` 节点（frontmatter tags 含 `discipline:N`），
承载「route 命中纪律」的检索面。它们此前是**手工快照**：既不在 render 渲染矩阵内、
也不在 verify 守卫内 —— 改真源后必然陈化。实例（2026-09-16）：真源第16条新增
「写入后读回确认」后，投影节点仍停留旧 `source_sha` 与旧正文；第17条（蜂巢派发）
**根本没有投影节点**。

这与「手写行号必腐化」同构：无守卫的手工件必然漂移。故把该投影并入
「真源 → render / verify」链路：
  - `render_discipline.py --all --write` 顺带同步（认知图 root 可用才做）
  - `verify_discipline.py` 校验一致性（root 不可用则跳过，外部 clone 不误红）

root 解析（三态单点 = resolve_root，A2 使用者裁决 2026-10-05）：`--cg-root` > 环境变量
`MDCG_ROOT`；判据面（本文件 `--check` / verify_discipline.py）**三态一律 fail-closed**
（非 0 退出）——
  · 未提供         → 退出码 2。此前静默 `[SKIP]` 退 0 ⇒ 判据体在全部自动化面从未执行。
  · 提供但不存在   → 退出码 2。此前与「未提供」同分支，文案还误写成「未提供」。
  · 存在但非认知图 → 退出码 2。此前按「空库」报满额 DRIFT 退 1，看不出是**误配**。
唯一豁免在**写向**：render_discipline.py 的「顺带同步」面未提供 root 时不同步
（require_root(allow_missing=True)），使 `render_discipline.py --write` 在任何机器上
可用；误配两态在写向同样 fail-closed（误配不许静默）。
自动化面（package.json gate 链 / .github/workflows/discipline-check.yml /
scripts/verify_linux.sh / scripts/git-hooks/pre-commit）各自用 `--init --write` 在仓内
`.tmp/discipline-cg` 建一个**最小认知图库**（只有 structural/ 层，真源不变即逐字节可重放），
再把该路径显式交给判据面——判据体因此每次都真执行。
**不硬编码本机路径**（第14条：公开仓产物不得含本机绝对路径）。

用法：
    python scripts/discipline_nodes.py --check [--cg-root <root>]
    python scripts/discipline_nodes.py --write [--cg-root <root>]
    python scripts/discipline_nodes.py --write --init --cg-root <root>   # 建最小库（root 不存在则建之、空目录就地建层）
    python scripts/discipline_nodes.py --check --json
退出码：0 一致；1 存在漂移；2 用法错误 / root 缺失或无效（fail-closed）。
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import render_discipline as R  # noqa: E402

NODE_DIR = "structural"
TAG_PREFIX = "discipline:"
BAD_ROOT_PREFIX = "_md_cg_"
DEFAULT_CARRIER = "本机三 harness（codebuddy / zcode / dsh）的会话上下文与灵枢认知图"

_LINE_NAMES = ("功能名", "生效条件", "子功能", "执行", "验证方式", "不适用条件")
_CARRIER_RE = re.compile(r"载体/位置：(.*?)；时间：(.*?)；方法：", re.S)


# ---------------------------------------------------------------- 基础工具

# 生效条件：无入参（惰性 import，cost 只在判定 root 形态时支付）；把仓根补进 sys.path 后返回 md_cg.mdcg 的 LAYERS 元组。
def library_layers():
    """认知图库的层目录单点：复用 md_cg/mdcg.py 的 LAYERS（不在本文件复制第二份字面量）。"""
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if repo not in sys.path:
        sys.path.insert(0, repo)
    from md_cg.mdcg import LAYERS  # noqa: PLC0415 —— 惰性：仅 root 形态判定才付导入成本
    return tuple(LAYERS)


# 生效条件：无入参时直接构造 SystemExit；有入参时先向 stderr 写 "[discipline_nodes] <msg>" 再 raise SystemExit(2)。
def _fail(msg):
    """fail-closed 单点：误配/缺失的文案走 stderr，退出码 2（用法错误口径，与 check 的 1=漂移区分）。"""
    if msg:
        sys.stderr.write("[discipline_nodes] " + msg + "\n")
    raise SystemExit(2)


# 生效条件：当显式参数 explicit 为真值（非空串）时以其为候选 root，为假值（None/空串）时回落到环境变量 MDCG_ROOT，二者均假值则返回 {"state":"missing"}；候选经 expanduser/normpath 归一后 abspath 的 basename 若以小写 "_md_cg_" 开头则 _fail（工具链产物目录，禁止作认知图 root）；路径非目录返回 {"state":"not_found"}，是目录且其下含 LAYERS 任一层目录返回 {"state":"ok"}，否则返回 {"state":"not_library"}（bool 字段 empty 标记该目录是否为空）。
def resolve_root(explicit=None):
    """认知图 root 三态判定（只判定，不建目录、不写盘）。

    返回 {"state", "root", "message", "empty"}：
      ok            root 存在且是认知图库（其下含 LAYERS 任一层目录）
      missing       未提供（--cg-root 与 MDCG_ROOT 均为空）
      not_found     提供了但不存在 / 不是目录
      not_library   存在但非认知图库（无任一 LAYERS 层目录）；empty 标记该目录是否为空

    三态各给**独立文案**（历史缺陷：not_found 与 missing 同分支、文案误写「未提供」）。
    `_md_cg_` 前缀守卫（2026-09-20 补，与 mcp_server 的同名守卫同口径）：该前缀目录是
    md_cg 工具链的**导出/评测产物**（白箱语料 `_md_cg_wisdom_graph`、评测灌库
    `_md_cg_eval_*` 等，只读或可再生语义），禁止作为认知图 root。历史缺陷实例：
    误传 `--cg-root _md_cg_wisdom_graph` → 投影节点被写进禁止目录，且因 `_new_node_fm`
    nid 碰撞被静默覆盖——误配必须响，故 fail-closed 抛出（退出码 2）。
    """
    raw = explicit or os.environ.get("MDCG_ROOT")
    if not raw:
        return {"state": "missing", "root": None, "empty": False,
                "message": "未提供认知图 root（--cg-root / MDCG_ROOT）——投影判据体没有执行面。"
                           "自动化面必须显式提供：先用 "
                           "`python scripts/discipline_nodes.py --write --init --cg-root <dir>` "
                           "建最小库（四自动化面口径），或指向本机认知图库"
                           "（md_cg/datapath.py 的 mdcg_root() 解析：env MDCG_ROOT > "
                           "paths.json > 用户级状态根 data/mdcg）。"}
    root = os.path.normpath(os.path.expanduser(raw))
    base = os.path.basename(os.path.abspath(root)).lower()
    if base.startswith(BAD_ROOT_PREFIX):
        _fail(
            "root 指向 md_cg 工具链产物目录（`%s` 前缀 = 导出/评测快照，"
            "只读或可再生语义），禁止作为认知图 root：\n    %s\n"
            "请指向主认知图目录（本机由 md_cg/datapath.py 的 mdcg_root() 解析："
            "env MDCG_ROOT > paths.json > 用户级状态根 data/mdcg）。"
            % (BAD_ROOT_PREFIX, root))
    if not os.path.isdir(root):
        return {"state": "not_found", "root": root, "empty": False,
                "message": "提供的认知图 root **不存在**（或不是目录）：\n    %s\n"
                           "若是要新建库，请用 `--write --init`（root 不存在时建之），"
                           "否则请修正路径。" % root}
    if not any(os.path.isdir(os.path.join(root, lay)) for lay in library_layers()):
        empty = not os.listdir(root)
        return {"state": "not_library", "root": root, "empty": empty,
                "message": "提供的认知图 root **存在但不是认知图库**（其下无 %s 任一层目录）：\n"
                           "    %s\n"
                           "（%s请指向认知图库根，而不是仓库根/文档目录等其它位置。）"
                           % ("/".join(library_layers()), root,
                              "该目录为空——" if empty else "")}
    return {"state": "ok", "root": root, "empty": False, "message": ""}


# 生效条件：resolve_root 得三态后——ok 返回 root；missing 在 allow_missing 为真时返回 None、为假时 _fail；not_found 在 init 为真时 makedirs(root) 后返回该路径、为假时 _fail；not_library 在 init 为真且该目录为空（empty）时返回该路径、否则 _fail。
def require_root(explicit=None, allow_missing=False, init=False):
    """判据面 / 写面的统一取根：非 ok 一律 fail-closed（stderr 文案 + 退出码 2）。

    allow_missing：**仅**对「未提供」态放行（返回 None）——给 render_discipline.py 的
      「顺带同步」面用（写向不产出判据，且 render --write 必须能在任何机器上跑）；
      误配两态不受此豁免（误配必须响，不许静默）。
    init：允许「建库」——root 不存在则建之、空目录就地建层（这正是四自动化面建
      `.tmp/discipline-cg` 最小库的路径）；**含内容的**非认知图目录仍 fail-closed
      （那是指错地方，不是待建的库）。
    """
    v = resolve_root(explicit)
    if v["state"] == "ok":
        return v["root"]
    if v["state"] == "missing" and allow_missing:
        return None
    if not init:
        _fail(v["message"])
    if v["state"] == "not_found":
        os.makedirs(v["root"], exist_ok=True)
        return v["root"]
    if v["state"] == "not_library" and v["empty"]:
        return v["root"]
    _fail(v["message"])


# 生效条件：对 path 指向的文本，raw 以“---”开头且从第 4 个字符起能找到“\n---”时返回 (fm, body)，否则返回 (None, raw)。
def _read_node(path):
    with io.open(path, encoding="utf-8") as f:
        raw = f.read()
    if not raw.startswith("---"):
        return None, raw
    end = raw.find("\n---", 3)
    if end < 0:
        return None, raw
    fm_text = raw[3:end].lstrip("\n")
    body = raw[end + 4:].lstrip("\n")
    fm = {}
    for line in fm_text.split("\n"):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        fm[k.strip()] = v.strip()
    return fm, body


# 生效条件：对任意 fm_lines，均返回“---\n” + “\n”.join(fm_lines) + “\n---\n”。
def _fm_render(fm_lines):
    return "---\n" + "\n".join(fm_lines) + "\n---\n"


# 生效条件：fm 中 key 对应的原始值为假值（缺键/None/空串等）时返回 {}；为真值且 json.loads 成功且结果为 dict 时返回该 dict；json.loads 抛异常或结果非 dict 时返回 {}。
def _json_field(fm, key):
    raw = fm.get(key)
    if not raw:
        return {}
    try:
        val = json.loads(raw)
    except Exception:  # noqa: BLE001
        return {}
    return val if isinstance(val, dict) else {}


# 生效条件：对任意 s，返回对 str(s) 做连续空白折叠为单空格并 strip 首尾空白后的字符串。
def _norm(s):
    return re.sub(r"\s+", " ", str(s)).strip()


# ---------------------------------------------------------------- 期望形态

# 生效条件：当 n 含“id”键时，以 n、i、sha、source_rel 为输入，按 semantic 缺省回落 n["id"]、conditions.apply 经 R._list_or 处理、execution.how、response.direct、content、negative.reject、node_id=n["id"]、no=i 构造期望字段字典；n 缺“id”时因 n.get("semantic", n["id"]) 与 n["id"] 求值而抛 KeyError。
def expected_fields(n, i, sha, source_rel):
    """该条纪律在投影节点上的『可机械派生』期望值。"""
    cond = n.get("conditions") or {}
    neg = n.get("negative") or {}
    ex = n.get("execution") or {}
    rs = n.get("response") or {}
    return {
        "semantic": str(n.get("semantic", n["id"])).strip(),
        "trigger": R._list_or(cond.get("apply"), "（无前置条件，始终适用）"),
        "how": str(ex.get("how", "")).strip(),
        "direct": str(rs.get("direct", "")).strip(),
        "content": str(n.get("content", "")).strip(),
        "nac": [str(c) for c in (neg.get("reject") or [])],
        "sha": sha,
        "source_rel": source_rel,
        "node_id": n["id"],
        "no": i,
    }


# 生效条件：对含 no、semantic、nac、how、source_rel、node_id、sha、content、trigger、direct 等键的 exp，返回按 exp、carrier、time_txt 拼接的六行列表；其中 exp["nac"] 为空可迭代对象时“不适用条件”行显示“（无）”。
def expected_body(exp, carrier, time_txt):
    """投影节点正文六行（与既有节点同构）。"""
    nac = "；".join(exp["nac"]) or "（无）"
    return [
        "# 功能名：工作纪律第%d条 · %s" % (exp["no"], exp["semantic"]),
        "# 生效条件：载体/位置：%s；时间：%s；方法：%s；约束：真源 = 灵枢大脑库 %s"
        " 节点 %s（SHA256 前16位 %s），本节点是其在认知图中的投影"
        % (carrier, time_txt, exp["how"], exp["source_rel"], exp["node_id"], exp["sha"]),
        "# 子功能：%s" % exp["content"],
        "# 执行：触发（%s）命中即执行「%s」；并在回复中原样输出声明：%s"
        % (exp["trigger"], exp["how"], exp["direct"]),
        "# 验证方式：data（真源 JSON 节点 %s；区间：%s）" % (exp["node_id"], exp["source_rel"]),
        "# 不适用条件：%s" % nac,
    ]


# 生效条件：当 body（或空串）匹配 _CARRIER_RE 时返回捕获的两组；否则 created_at 为真值时按其时间戳格式化为日期、为假值（None/0/空串）时用当前日期，并与 DEFAULT_CARRIER 组合返回“<日期> 起长期有效”。
def _carrier_of(body, created_at):
    m = _CARRIER_RE.search(body or "")
    if m:
        return m.group(1).strip(), m.group(2).strip()
    stamp = datetime.fromtimestamp(float(created_at)).strftime("%Y-%m-%d") \
        if created_at else datetime.now().strftime("%Y-%m-%d")
    return DEFAULT_CARRIER, "%s 起长期有效" % stamp


# ---------------------------------------------------------------- 盘点

# 生效条件：当 root/NODE_DIR 是目录时，扫描该目录下 .md 文件，将 _read_node 得到非空 fm 且 tags 正则中带引号的标签以 TAG_PREFIX 开头处的整数为键，记录 path/fm/body 到返回字典；root/NODE_DIR 不是目录时返回空字典。
def scan_nodes(root):
    """返回 {条号(int): {"path", "raw", "fm", "body"}}（tags 含 discipline:N）。"""
    out = {}
    d = os.path.join(root, NODE_DIR)
    if not os.path.isdir(d):
        return out
    for fn in sorted(os.listdir(d)):
        if not fn.endswith(".md"):
            continue
        path = os.path.join(d, fn)
        fm, body = _read_node(path)
        if not fm:
            continue
        tags = fm.get("tags") or ""
        for t in re.findall(r"[\"']([^\"']+)[\"']", tags):
            if t.startswith(TAG_PREFIX):
                try:
                    out[int(t[len(TAG_PREFIX):])] = {
                        "path": path, "fm": fm, "fm_raw": fm, "body": body}
                except ValueError:
                    pass
    return out


# 生效条件：当 root 不为 None 时，基于 repo 加载真源与矩阵，对每条真源节点在 scan_nodes(root) 结果中检查缺失、source_sha 不等、condition_space.trigger 经 _norm 不等、expected_body 各行经 _norm 不包含于节点正文、fm.id 规范化后为空，任一项成立即记入 drift 并返回 ok=not drift；root 为 None（判据体没有执行面）时返回 skipped=True 且 **ok=False**（fail-closed：skipped 不得计入通过）。
def check_cg_nodes(repo, root, allow_missing=True):
    """守卫：真源 ↔ 认知图投影节点一致性。root 为 None → skipped 且 ok=False（不计通过）。"""
    if root is None:
        return {"skipped": True, "ok": False,
                "reason": "未提供认知图 root（--cg-root / MDCG_ROOT）——投影判据体未执行。"
                          "判据面一律 fail-closed：请显式提供 root"
                          "（四自动化面口径 = `--init --write --cg-root .tmp/discipline-cg`）。",
                "drift": [], "nodes": 0}
    src = R.load_source(repo)
    sha = R.source_sha(repo)
    source_rel = os.path.basename(R.source_path(repo))
    mx = R.load_matrix(repo)
    source_rel = mx["source"]
    nodes = R.nodes_of(src)
    have = scan_nodes(root)

    drift = []
    for i, n in enumerate(nodes, 1):
        exp = expected_fields(n, i, sha, source_rel)
        cur = have.get(i)
        if cur is None:
            drift.append({"no": i, "id": exp["node_id"], "kind": "missing",
                          "detail": "认知图内无 discipline:%d 投影节点" % i})
            continue
        fm, body = cur["fm"], cur["body"]
        cs = _json_field(fm, "condition_space")
        got_sha = str(cs.get("source_sha") or "").strip().strip('"')
        if got_sha != sha:
            drift.append({"no": i, "id": exp["node_id"], "kind": "sha",
                          "detail": "source_sha %s ≠ 当前真源 %s（改真源后未同步）" % (got_sha or "-", sha)})
        if _norm(cs.get("trigger") or "") != _norm(exp["trigger"]):
            drift.append({"no": i, "id": exp["node_id"], "kind": "trigger",
                          "detail": "condition_space.trigger 不一致"})
        carrier, time_txt = _carrier_of(body, fm.get("created_at"))
        for want in expected_body(exp, carrier, time_txt):
            name = want.split("：", 1)[0].lstrip("# ")
            if _norm(want) not in _norm(body):
                drift.append({"no": i, "id": exp["node_id"], "kind": "body:" + name,
                              "detail": "%s 行与真源不一致" % name})
        if _norm(fm.get("id") or "").strip('"') == "":
            drift.append({"no": i, "id": exp["node_id"], "kind": "id", "detail": "节点缺 id"})
    return {"skipped": False, "ok": not drift, "drift": drift,
            "nodes": len(nodes), "source_sha": sha, "scanned": len(have)}


# ---------------------------------------------------------------- 同步

# 生效条件：对给定 path，按 fm_order 顺序逐项取 fm.get(k, "")（缺键为空串）生成 front matter，并写入其与 body_lines 以换行连接并 rstrip 后加换行的内容。
def _write_node(path, fm, fm_order, body_lines):
    lines = []
    for k in fm_order:
        v = fm.get(k, "")
        lines.append("%s: %s" % (k, v))
    with io.open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(_fm_render(lines) + "\n".join(body_lines).rstrip() + "\n")


# 生效条件：当 exp 含 nac、trigger、sha、no 等键时，以 now 与 exp["no"] 计算 nid="mem_%d%03d" % (int(now*1000), exp["no"])，并返回该 nid 与按 exp 内容生成的固定 front matter 行列表。
def _new_node_fm(exp, now):
    nac = json.dumps(exp["nac"], ensure_ascii=False)
    cs = json.dumps({"trigger": exp["trigger"], "harness": "codebuddy|zcode|dsh",
                     "source_sha": exp["sha"],
                     "time_window": [now, now + 3600]}, ensure_ascii=False)
    # nid 必须**逐条唯一**：原实现 `"mem_%d" % int(now*1000)` 的 now 在 sync 循环外
    # 只取一次，同批次「新建」的多条纪律因此共用同一 nid → 后写覆盖前写，
    # 静默只留最后一条（2026-09-20 实测：18 条全进同一个 mem_*.md，17 条丢失）。
    # 尾部 3 位编码条号，故同批次唯一、跨批次靠毫秒位区分。
    nid = "mem_%d%03d" % (int(now * 1000), exp["no"])
    fm = [
        "access_count: 0",
        "condition_space: " + cs,
        "confidence: 0.6",
        "created_at: %s" % now,
        "edges: []",
        "evidence_count: 0",
        'id: "%s"' % nid,
        "importance: 0.85",
        "last_access: 0",
        'layer: "structural"',
        'modality: "text"',
        "negative_evidence: 0",
        "non_applicable_conditions: " + nac,
        "positive_evidence: 0",
        "protected: true",
        'protection_reason: "importance=0.85≥0.7"',
        'sensitivity: "internal"',
        'tags: ["work-discipline", "discipline:%d", "harness:all", "v1.1"]' % exp["no"],
        'verification_basis: "data"',
    ]
    return nid, fm


# 生效条件：当 root 不为 None 时，基于 repo 加载真源并与 scan_nodes(root) 比对：对缺失条号生成 created 记录（write 为真时写新节点），对正文或 source_sha 不一致条号生成 changed 记录（write 为真时写回），返回 changed/created/nodes/source_sha；root 为 None 时返回 skipped。
def sync_cg_nodes(repo, root, write=False):
    """把真源同步进认知图投影节点。write=False 时干跑（只报告差异）。"""
    if root is None:
        return {"skipped": True,
                "reason": "未提供认知图 root（--cg-root / MDCG_ROOT），本次不同步"
                          "（写向豁免；判据面由 verify_discipline 强制 fail-closed）",
                "changed": [], "created": []}
    src = R.load_source(repo)
    sha = R.source_sha(repo)
    mx = R.load_matrix(repo)
    source_rel = mx["source"]
    nodes = R.nodes_of(src)
    have = scan_nodes(root)
    now = datetime.now().timestamp()

    changed, created = [], []
    for i, n in enumerate(nodes, 1):
        exp = expected_fields(n, i, sha, source_rel)
        cur = have.get(i)
        if cur is None:
            nid, fm_lines = _new_node_fm(exp, now)
            carrier, time_txt = DEFAULT_CARRIER, datetime.fromtimestamp(now).strftime("%Y-%m-%d") + " 起长期有效"
            body = expected_body(exp, carrier, time_txt)
            path = os.path.join(root, NODE_DIR, "%s.md" % nid)
            if write:
                os.makedirs(os.path.dirname(path), exist_ok=True)
                order = [l.split(":", 1)[0] for l in fm_lines]
                _write_node(path, dict(zip(order, [l.split(":", 1)[1].strip() for l in fm_lines])),
                            order, body)
            created.append({"no": i, "id": nid, "path": path, "written": bool(write)})
            continue

        fm, body = cur["fm"], cur["body"]
        fm = dict(fm)
        carrier, time_txt = _carrier_of(body, fm.get("created_at"))
        want_body = expected_body(exp, carrier, time_txt)
        fm["condition_space"] = json.dumps(
            {"trigger": exp["trigger"], "harness": "codebuddy|zcode|dsh", "source_sha": sha,
             "time_window": _json_field(fm, "condition_space").get("time_window") or [now, now + 3600]},
            ensure_ascii=False)
        fm["non_applicable_conditions"] = json.dumps(exp["nac"], ensure_ascii=False)

        cur_norm_body = [_norm(l) for l in (body or "").splitlines() if l.strip()]
        same = cur_norm_body == [_norm(l) for l in want_body] and \
            str(_json_field(cur["fm"], "condition_space").get("source_sha") or "") == sha
        if same:
            continue
        order = [k for k in cur["fm"].keys()]
        changed.append({"no": i, "id": str(fm.get("id", "")).strip('"'), "path": cur["path"],
                        "written": bool(write)})
        if write:
            _write_node(cur["path"], fm, order, want_body)
    return {"skipped": False, "changed": changed, "created": created,
            "source_sha": sha, "nodes": len(nodes)}


# 生效条件：argv 为 None 时 argparse 从 sys.argv 解析，否则解析给定 argv；解析出 --write 时以 require_root(args.cg_root, init=args.init) 取根（缺失/误配 fail-closed）并执行 sync_cg_nodes(write=True) 返回 0；否则以 require_root(args.cg_root) 严格取根（三态一律 fail-closed）执行 check_cg_nodes 并按 ok 返回 0/1。
def main(argv=None):
    ap = argparse.ArgumentParser(description="工作纪律认知图投影节点同步器与守卫")
    ap.add_argument("--repo", default=R.REPO_DEFAULT)
    ap.add_argument("--cg-root", default=None,
                    help="认知图 root（缺省读环境变量 MDCG_ROOT）；判据面缺失/无效一律 fail-closed（退出码 2）")
    ap.add_argument("--check", action="store_true", help="校验一致性（默认动作）")
    ap.add_argument("--write", action="store_true", help="同步（写盘）")
    ap.add_argument("--init", action="store_true",
                    help="建库：root 不存在则建之、空目录就地建层（四自动化面用它建判据体的执行面最小库）")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    repo = os.path.abspath(args.repo)

    if args.write:
        root = require_root(args.cg_root, init=args.init)
        rep = sync_cg_nodes(repo, root, write=True)
        if args.json:
            print(json.dumps(rep, ensure_ascii=False, indent=2))
        elif rep.get("skipped"):
            print("[SKIP] " + rep["reason"])
        else:
            print("真源指纹 %s；纪律 %d 条" % (rep["source_sha"], rep["nodes"]))
            for r in rep["created"]:
                print("  [新建] 第%d条 -> %s" % (r["no"], r["path"]))
            for r in rep["changed"]:
                print("  [同步] 第%d条 %s -> %s" % (r["no"], r["id"], r["path"]))
            if not rep["created"] and not rep["changed"]:
                print("  已一致，无需改动")
        return 0

    # 判据面：三态（未提供 / 不存在 / 非认知图）一律 fail-closed，绝不再静默 [SKIP] 退 0。
    root = require_root(args.cg_root)
    res = check_cg_nodes(repo, root)
    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    elif res.get("skipped"):
        print("[SKIP] " + res["reason"])
    else:
        print("真源指纹 %s；纪律 %d 条；认知图扫描到 %d 个投影节点"
              % (res["source_sha"], res["nodes"], res["scanned"]))
        if res["ok"]:
            print("[OK  ] 投影节点与真源一致")
        else:
            for d in res["drift"]:
                print("  [DRIFT] 第%d条 %s: %s" % (d["no"], d["kind"], d["detail"]))
        print("")
        print("结论：%s（漂移 %d 处）" % ("一致" if res["ok"] else "存在漂移", len(res["drift"])))
    return 0 if res.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())