# -*- coding: utf-8 -*-
"""bootstrap_loop.py · 白箱自举后台循环 v3（长期任务执行体·双通道）

v3 迁移（2026-09-10，三仓分离后）：
  - 归属：协议仓 `CommonTrustProtocol/tools/` → **灵枢大脑 `dsh-memory/scripts/`**
    （作用对象 wisdom 齿轮已随大脑仓，循环应与其同仓）。
  - 路径：`WISDOM = ROOT/aeis/wisdom`（已随三仓分离删除）→
    `BRAIN/md_cg/whitebox_kb/wisdom`。
  - 数据根：不再硬编码 `ROOT/aeis/data/*`，统一走 `md_cg/datapath.py`
    解析（env `MDCG_ROOT` > `paths.json`（用户级，旧包内兼容读）> 用户级状态根
    `data/`，即 `~/.dsh/.dsh-memory/data`——不再落插件包内，包内数据会被
    pnpm 更新连目录删掉）。运行态落 `<数据根>/bootstrap/`。

通道 A：路由缺口扫描 → triggers 补丁 → 验证 → 固化（零 LLM·确定性）
通道 B：LLM 初稿（deepseek/glm）→ verifier 六层校验 → 测试 → 固化
四机制安全闭环：selfmod 快照/审计/裁决 在每次固化前强制执行。

用法：
  python scripts/bootstrap_loop.py --once --channel-b     # 单轮含 LLM 通道
  python scripts/bootstrap_loop.py --once                # 单轮仅通道 A
  python scripts/bootstrap_loop.py --interval 600 --channel-b   # 长期跑
日志：<数据根>/bootstrap/bootstrap_log.jsonl
"""
from __future__ import annotations

import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
BRAIN = os.path.dirname(HERE)                      # 灵枢大脑仓根
WISDOM = os.path.join(BRAIN, "md_cg", "whitebox_kb", "wisdom")

sys.path.insert(0, WISDOM)
sys.path.insert(0, HERE)
sys.path.append(os.path.join(BRAIN, "md_cg"))      # 供顶层 import datapath

# 数据根解析（记忆写入路径可配置·默认用户级状态根 data/；解析器缺失时的
# 兜底分支保留旧「仓内 data/」口径——那是本脚本自带的最后兜底，非解析默认）
try:
    import datapath as _dp
except Exception:                                   # 兜底：解析器缺失时不高挂
    class _dp:                                      # type: ignore
        @staticmethod
# 生效条件：调用即返回 os.path.join(BRAIN, "data")，结果只取决于模块级常量 BRAIN，不接收参数。
        def data_root() -> str:
            return os.path.join(BRAIN, "data")

        @staticmethod
# 生效条件：以 name 拼出 os.path.join(BRAIN, "data", name)，该路径 os.path.isfile 为真时返回该路径，否则返回 None。
        def find_existing(name: str):
            p = os.path.join(BRAIN, "data", name)
            return p if os.path.isfile(p) else None

STATE = os.path.join(_dp.data_root(), "bootstrap")
os.makedirs(STATE, exist_ok=True)
LOG = os.path.join(STATE, "bootstrap_log.jsonl")


# 生效条件：evt 为 dict 时（含空 dict）先写入 evt["ts"]，再以 ensure_ascii=False 序列化追加一行到 LOG。
def log_event(evt: dict) -> None:
    evt["ts"] = time.strftime("%Y-%m-%d %H:%M:%S")
    # P2-13: rotate LOG when > 10MB (batch 31)
    try:
        if os.path.getsize(LOG) > 10485760:
            os.replace(LOG, LOG + ".rotated")
    except OSError:
        pass
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(evt, ensure_ascii=False) + "\n")


# ==================== 通道 A：路由缺口扫描（零 LLM） ====================
# 生效条件：limit_units 为真值且已遍历单元计数 count > limit_units 时提前返回当前 gaps，limit_units 为 None 或 0 时不限流；遍历每个 DOMAIN_UNITS 域单元时 domain_route 抛异常记 error 项、返回 unit != uid 或 ok 假值记 got 项，全遍历后返回 gaps。
def scan_route_gaps(limit_units: int | None = None) -> list:
    from code_compose import domain_route, DOMAIN_UNITS

    gaps = []
    domains = list(DOMAIN_UNITS.keys())
    count = 0
    for dom in domains:
        for uid, unit in DOMAIN_UNITS[dom].items():
            count += 1
            if limit_units and count > limit_units:
                return gaps
            triggers = [t for t in (unit.get("triggers") or []) if len(t) >= 2]
            probe = "写一个{}单元（{}）".format(
                uid, triggers[0] if triggers else unit.get("task", ""))
            try:
                r = domain_route(probe)
            except Exception:
                gaps.append({"domain": dom, "unit": uid, "probe": probe, "error": "exc"})
                continue
            if r.get("unit") != uid or not r.get("ok"):
                # GAP_DEBUG=1：gap 判定现场落盘（r 全量+环境快照）——
                # 「循环进程 gap=1 vs 交互进程同代码 True」非确定性排查取证点
                if os.environ.get("GAP_DEBUG"):
                    try:
                        json.dump({
                            "probe": probe, "result": r,
                            "pid": os.getpid(),
                            "sys_executable": sys.executable,
                            "code_compose_file": getattr(__import__("code_compose"), "__file__", "?"),
                            "cases_shape": type(unit.get("cases", [None])[0][0]).__name__ if unit.get("cases") else "?",
                            "env": {k: v for k, v in os.environ.items()
                                    if k.startswith(("PYTHON", "AEIS", "SYSTEMROOT", "PATH="))},
                        }, open(os.path.join(STATE, "gap_debug.json"), "w",
                                encoding="utf-8"), ensure_ascii=False, indent=1, default=str)
                    except Exception:
                        pass
                gaps.append({"domain": dom, "unit": uid, "probe": probe,
                             "got": r.get("unit") or r.get("reason", "?")})
    return gaps


# 生效条件：gap["unit"] 按 "-" 切分后存在长度 >= 2 的片段时返回 {domain, unit, add_triggers=前 3 个片段}，无此类片段时返回 None。
def build_trigger_patch(gap):
    uid = gap["unit"]
    parts = [p for p in uid.split("-") if len(p) >= 2]
    if not parts:
        return None
    return {"domain": gap["domain"], "unit": uid, "add_triggers": parts[:3]}


# 生效条件：DOMAIN_UNITS.get(patch["domain"], {}).get(patch["unit"]) 取到的单元为 None 时返回 False；取到单元时把 patch["add_triggers"] 中长度 >= 2 且不在现 triggers 集合的项追加（无新项不修改 triggers），两种情况均返回 True。
def apply_patch(patch):
    from code_compose import DOMAIN_UNITS
    unit = DOMAIN_UNITS.get(patch["domain"], {}).get(patch["unit"])
    if unit is None:
        return False
    cur = set(unit.get("triggers") or [])
    new = [t for t in patch["add_triggers"] if t not in cur and len(t) >= 2]
    if not new:
        return True
    unit["triggers"] = (unit.get("triggers") or []) + new
    return True


# 生效条件：patch["unit"] 作为 uid 拼出 "写一个{uid}单元" 探针调用 domain_route，返回 domain_route 结果的 unit == patch["unit"] 且 ok 为真值的布尔与。
def verify_patch(patch):
    from code_compose import domain_route
    uid = patch["unit"]
    probe = "写一个{}单元".format(uid)
    r = domain_route(probe)
    return r.get("unit") == uid and r.get("ok")


# 生效条件：patches 中某 patch 的 domain 命中 files 六键之一、对应 os.path.exists(path) 为真、且 path 内容正则搜到 `"uid": {` 行且其后 600 字符块内无 "triggers" 时才插入 triggers 行并让 changed 自增，否则跳过；返回 changed。
def persist_triggers(patches):
    import re
    files = {
        "graph": os.path.join(WISDOM, "graph_db_units.py"),
        "compiler": os.path.join(WISDOM, "compiler_code_units.py"),
        "pylang": os.path.join(WISDOM, "python_code_units.py"),
        "os": os.path.join(WISDOM, "os_units.py"),
        "browser": os.path.join(WISDOM, "browser_units.py"),
        "net": os.path.join(WISDOM, "net_units.py"),
    }
    changed = 0
    for p in patches:
        dom, uid, triggers = p["domain"], p["unit"], p["add_triggers"]
        path = files.get(dom)
        if not path or not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as f:
            src = f.read()
        pat_uid = re.compile(r'(\n(\s*)"' + re.escape(uid) + r'": \{\n)')
        m = pat_uid.search(src)
        if not m:
            continue
        block = src[m.end(1):m.end(1) + 600]
        if '"triggers"' in block:
            continue
        ind = m.group(2)
        trig_json = json.dumps(triggers, ensure_ascii=False)
        src = src[:m.end(1)] + ind + '    "triggers": ' + trig_json + ',\n' + src[m.end(1):]
        _tmp = path + ".tmp"
        with open(_tmp, "w", encoding="utf-8") as f:
            f.write(src)
        # P2-14: atomic replace - concurrent instances never see a
        # half-written source file (batch 31).
        os.replace(_tmp, path)
        changed += 1
    return changed


# ==================== 通道 B：LLM 初稿 → verifier → 固化 ====================
# ---- P1-7（批次 26）：LLM 产出代码的 AST 沙箱 ------------------------------
# 危险名 denylist（配合 __builtins__ 收窄双层防御）：
#   执行/IO 面：eval exec compile open __import__ breakpoint input
#   反射面：globals locals vars getattr setattr delattr（内省逃逸链入口）
#   进程面：exit quit（干扰循环宿主）
_GEN_BANNED_NAMES = frozenset({
    "eval", "exec", "compile", "open", "__import__", "breakpoint", "input",
    "globals", "locals", "vars", "getattr", "setattr", "delattr",
    "exit", "quit", "memoryview", "super",
})
# 自举生成物的合法计算面（排序/查找/字符串处理足够）；len/range 等纯函数
_GEN_SAFE_BUILTINS = {name: getattr(__import__("builtins"), name)
                      for name in (
                          "abs", "all", "any", "bool", "bytes", "chr", "dict",
                          "divmod", "enumerate", "filter", "float", "frozenset",
                          "hash", "hex", "int", "isinstance", "len", "list",
                          "map", "max", "min", "oct", "ord", "pow", "range",
                          "repr", "reversed", "round", "set", "slice", "sorted",
                          "str", "sum", "tuple", "zip", "True", "False", "None",
                          "ArithmeticError", "IndexError", "KeyError",
                          "TypeError", "ValueError", "ZeroDivisionError")}


# 生效条件：code 为 LLM 返回或 channel_b_queue.json 产出的 Python 源码文本；ast.parse 失败抛原语法异常，ast.walk 命中 Import/ImportFrom 节点、Name.id 属 _GEN_BANNED_NAMES、Attribute.attr 以下划线双端包夹或属 ("system","popen") 任一即抛 ValueError（不执行）；全部通过则以 {"__builtins__": _GEN_SAFE_BUILTINS} 为命名空间 exec 编译产物并返回该 ns（其中含源码定义的函数）。
def _safe_exec_gen(code: str) -> dict:
    """LLM 产出代码的受限 exec：AST denylist + 内建收窄（P1-7，批次 26）。

    拒绝（ValueError，不执行）：
      · import 面——Import / ImportFrom 节点（禁 os/subprocess 前置）；
      · 危险内建名调用——_GEN_BANNED_NAMES（执行/IO/反射/进程面）；
      · 反射逃逸链——dunder 属性访问（__class__/__globals__/__subclasses__…）
        与 os.system/popen 类敏感属性；
      · Lambda/推导式中的同名调用同样被 walk 覆盖（AST 全遍历）。
    执行命名空间 `__builtins__` 收窄到纯计算内建——即使 denylist 漏项，
    ns 里也没有 open/import 可拿。
    """
    import ast
    tree = ast.parse(code)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            raise ValueError(f"沙箱拒绝 import（行 {getattr(node, 'lineno', '?')}）"
                             "——自举产出应为纯函数，无需依赖")
        if isinstance(node, ast.Name) and node.id in _GEN_BANNED_NAMES:
            raise ValueError(f"沙箱拒绝受限名 {node.id}"
                             f"（行 {getattr(node, 'lineno', '?')}）")
        if isinstance(node, ast.Attribute):
            if node.attr.startswith("__") or node.attr in ("system", "popen"):
                raise ValueError(f"沙箱拒绝受限属性 .{node.attr}"
                                 f"（行 {getattr(node, 'lineno', '?')}）"
                                 "——反射逃逸链入口")
    ns = {"__builtins__": _GEN_SAFE_BUILTINS}
    exec(compile(code, "<gen>", "exec"), ns)   # noqa: S102——沙箱内（见上）
    return ns



def run_channel_b(llm_generate=None, max_tasks=5):
    """通道 B v2：从队列文件读取初稿（由 GLM-5.3-Flash 在对话轮次中批量
    产出到 channel_b_queue.json）→ verifier 校验 → 固化到 verified_units。

    如果队列文件不存在或为空且 llm_generate 可用 → 调 LLM API 生成。
    """
    from verifier import Verifier


    queue_path = os.path.join(STATE, "channel_b_queue.json")
    out_path = os.path.join(STATE, "channel_b_verified_units.json")
    # 批次 35：初始化必须是 dict——空串形态在产物文件不存在时首次固化即
    # TypeError（verified[key]=... 对 str 赋值）。此缺陷因 run_channel_b
    # 长期无测试覆盖而潜伏（V21 报告流程建议 2 的全链路冒烟首跑即暴露）。
    verified = {}
    if os.path.exists(out_path):
        with open(out_path, encoding="utf-8") as f:
            verified = json.load(f)
    stats = {"generated": 0, "passed": 0, "failed": 0, "source": "queue"}

    queue = []
    if os.path.exists(queue_path):
        with open(queue_path, encoding="utf-8") as f:
            qd = json.load(f)
        queue = [t for t in qd.get("pending", [])
                 if t.get("status") not in ("verified", "failed")]

    if not queue and llm_generate:
        stats["source"] = "llm_api"
        # LLM API 通道（需要 key）。2026-08-28 修复：无 cases 的生成条目
        # 无法物理验证却会写回 pending 永久占位（not cases: continue）——
        # 卡死队列且顶掉人工条目。必须有 cases 才入队。
        for task_desc in ["堆排序", "二分查找", "快速排序"]:
            r = llm_generate(f"实现 {task_desc}")
            if r.get("ok") and r.get("cases"):
                queue.append({"task": task_desc, "code": r["code"],
                              "cases": r["cases"]})

    v = Verifier()
    for item in queue[:max_tasks]:
        task = item.get("task", "")
        code = item.get("code", "")
        cases = item.get("cases", [])
        # cases 格式：[[inp, exp], ...]——每个 case 是 [input, expected] 对
        if not code or not cases:
            continue
        stats["generated"] += 1

        # verifier 校验
        import re as _re
        fn_m = _re.search(r"def (\w+)\(", code)
        fname = fn_m.group(1) if fn_m else None
        if not fname:
            stats["failed"] += 1
            # 批次 35：前置拒绝路径也必须标 failed——否则条目永久占位
            # 反复重试（与 2026-08-28 卡队列缺陷同型；冒烟守卫暴露）
            item["status"] = "failed"
            continue

        # 物理验证：exec + cases
        # P1-7（批次 26，外部审查报告）：code 来自 LLM 返回 / channel_b_queue.json
        # （模型可控输入），直接 exec = 以循环进程身份执行任意 Python。改为
        # AST 白名单沙箱（报告建议 2）：自举循环的合法产出 = 纯算术/逻辑
        # 函数（排序/查找等算法题），不需要 import 与 IO——denylist 拒绝
        # import 面、危险内建与反射逃逸链，命中即 ValueError 不执行。
        try:
            ns = _safe_exec_gen(code)
        except Exception:
            stats["failed"] += 1
            item["status"] = "failed"     # 批次 35：防卡队列（同上）
            # 批次 35：沙箱拒绝（import 面/危险内建/反射逃逸）的产出单独
            # 留痕——恶意/坏产出是最该进拒绝日志的类别（与 cases 未过同款）
            _rej = os.path.join(STATE, "channel_b_drafts", "rejected_log.json")
            os.makedirs(os.path.dirname(_rej), exist_ok=True)
            _rej_list = []
            if os.path.exists(_rej):
                with open(_rej, encoding="utf-8") as f:
                    _rej_list = json.load(f)
            _rej_list.append({"task": task, "layer": "queue_sandbox",
                              "why": "AST 沙箱拒绝（import 面/危险内建/"
                                     "反射逃逸链）",
                              "ts": time.strftime("%Y-%m-%d %H:%M")})
            with open(_rej, "w", encoding="utf-8") as f:
                json.dump(_rej_list, f, ensure_ascii=False, indent=1)
            continue
        if fname not in ns or not callable(ns[fname]):
            stats["failed"] += 1
            item["status"] = "failed"     # 批次 35：防卡队列（同上）
            continue
        fn = ns[fname]
        all_pass = True
        for case in cases:
            inp_raw, exp = case[0], case[1]
            import inspect as _insp
            try:
                _np = len(_insp.signature(fn).parameters) if callable(fn) else 1
                _declared = item.get("nargs")
                # 展开判定：签名 >1 参数自动展开；单参函数但生成侧标注
                # nargs>1（如 arr 类参数）也展开——字符串单参不被误展开
                if (_np > 1 or (_declared is not None and _declared > 1)) \
                        and isinstance(inp_raw, (list, tuple)):
                    got = fn(*inp_raw)
                elif isinstance(inp_raw, list) and _np == 1 and _declared == 1:
                    got = fn(*inp_raw)
                else:
                    got = fn(inp_raw)
                if got != exp:
                    all_pass = False
                    break
            except Exception:
                all_pass = False
                break
        if all_pass:
            key = "task:" + task
            verified[key] = {"task": task, "code": code, "ok": True,
                             "fingerprint": __import__("hashlib").sha256(
                                 code.encode()).hexdigest()[:16],
                             "ts": time.strftime("%Y-%m-%d %H:%M")}
            stats["passed"] += 1
            item["status"] = "verified"
        else:
            stats["failed"] += 1
            item["status"] = "failed"
            _rej = os.path.join(STATE, "channel_b_drafts", "rejected_log.json")
            os.makedirs(os.path.dirname(_rej), exist_ok=True)
            _rej_list = ""
            if os.path.exists(_rej):
                with open(_rej, encoding="utf-8") as f:
                    _rej_list = json.load(f)
            _rej_list.append({"task": task, "layer": "queue_verifier",
                              "why": "cases 物理验证未过",
                              "ts": time.strftime("%Y-%m-%d %H:%M")})
            with open(_rej, "w", encoding="utf-8") as f:
                json.dump(_rej_list, f, ensure_ascii=False, indent=1)

    if queue:
        qd = {"_comment": "自举产物队列（已完成项标记 verified）",
              "_instructions": "bootstrap_loop 自动消化",
              "pending": queue}
        with open(queue_path, "w", encoding="utf-8") as f:
            json.dump(qd, f, ensure_ascii=False, indent=1)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(verified, f, ensure_ascii=False, indent=1)
    return stats


# 生效条件：channel_b 为假值时只走通道 A——scan_route_gaps() 的 gaps 非空则取前 max_patches 个构建含 add_triggers 的补丁，apply_patch 为假或 verify_patch 为假计入 patches_failed、verify_patch 为真计入 patches_verified，persisted 非空才 persist_triggers(patches)；channel_b 为真值时额外 import llm_channel 并以 max_tasks=3 调 run_channel_b，其异常写入 result["channel_b"]["error"]；随后 log_event 并返回 result。
def run_once(channel_b=False, max_patches=20):
    result = {"gaps": 0, "patches_applied": 0, "patches_verified": 0,
              "patches_failed": 0, "persisted_files": 0}

    # ① 通道 A：路由缺口扫描与 triggers 补丁
    gaps = scan_route_gaps()
    result["gaps"] = len(gaps)
    if gaps:
        patches = []
        for g in gaps[:max_patches]:
            p = build_trigger_patch(g)
            if p and p["add_triggers"]:
                patches.append(p)
        persisted = []
        for p in patches:
            if not apply_patch(p):
                result["patches_failed"] += 1
                continue
            if verify_patch(p):
                result["patches_verified"] += 1
                persisted.append(p)
            else:
                result["patches_failed"] += 1
        if persisted:
            result["persisted_files"] = persist_triggers(patches)

    # ② 通道 B：LLM 初稿 → verifier → 固化
    if channel_b:
        try:
            from llm_channel import generate_code
            rb = run_channel_b(generate_code, max_tasks=3)
            result["channel_b"] = rb
        except Exception as e:
            result["channel_b"] = {"error": str(e)[:80]}

    log_event({"round": "bootstrap_v2", **result})
    return result


# 生效条件：_dp.find_existing("verify_cache.json") 返回 None 时只记 status=skipped 并返回；否则读取该 json 的固定键 "a866f668bd6f4a1c048e16f684df69bf" 条目，记录 a866_ok、checks 中是否含 "缓存命中"、非 "_" 前缀键数量；读取或处理抛异常记 error 后返回。
def gap_watch() -> None:
    """GAP_DEBUG 诊断：自报本进程视角的配对信任指纹状态——
    区分「本进程写的 False」vs「他进程写回」。

    v3：校验缓存位置不再硬编码 `ROOT/aeis/data/verify_cache.json`，
    改由 datapath 在数据根/插件仓/归档区中查找；找不到只记 skipped。
    """
    try:
        vc = _dp.find_existing("verify_cache.json")
        if not vc:
            log_event({"round": "gap_watch", "status": "skipped",
                       "why": "verify_cache.json 未在数据根/插件仓/归档区找到",
                       "ts": time.strftime("%Y-%m-%d %H:%M:%S")})
            return
        with open(vc, encoding="utf-8") as f:
            _d = json.load(f)
        _ent = _d.get("a866f668bd6f4a1c048e16f684df69bf")
        log_event({"round": "gap_watch", "pid": os.getpid(),
                   "src": vc,
                   "a866_ok": (_ent or {}).get("ok"),
                   "a866_cached": "缓存命中" in json.dumps((_ent or {}).get("checks", []), ensure_ascii=False),
                   "cache_entries": len([k for k in _d if not k.startswith("_")]),
                   "ts": time.strftime("%Y-%m-%d %H:%M:%S")})
    except Exception as _e:
        log_event({"round": "gap_watch", "error": str(_e)[:100],
                   "ts": time.strftime("%Y-%m-%d %H:%M:%S")})


def csre_freshness(last_kp_fp):
    """CSRE 索引新鲜度（T7 · 2026-08-28）：kp 卡指纹变化才重建，
    快照过期会让 L1 词向量对新知识卡零向量。返回新的指纹。

    v3：数据库位置改为 WISDOM（随大脑仓），并在 DB 缺失时明确 skipped。
    """
    try:
        import sqlite3 as _sq
        import hashlib as _hl
        db_path = os.path.join(WISDOM, "wisdom-book-cloud.db")
        if not os.path.isfile(db_path):
            log_event({"round": "csre_rebuild_error", "status": "skipped",
                       "why": "wisdom-book-cloud.db 缺失: %s" % db_path,
                       "ts": time.strftime("%Y-%m-%d %H:%M:%S")})
            return last_kp_fp
        conn = _sq.connect(db_path)
        kp_cnt, kp_max = conn.execute(
            "SELECT COUNT(*), COALESCE(MAX(created_at), 0) FROM nodes "
            "WHERE tags LIKE '%knowledge_point%'").fetchone()
        conn.close()
        kp_fp = _hl.sha256(f"{kp_cnt}:{kp_max}".encode()).hexdigest()[:12]
        if kp_fp != last_kp_fp:
            if last_kp_fp is not None:
                from csre import Csre
                _c = Csre(db_path)
                _st = _c.build_index()
                _c.save_index()
                log_event({"round": "csre_rebuild",
                           "units": _st.get("units"),
                           "vocab": _st.get("vocab"),
                           "ts": time.strftime("%Y-%m-%d %H:%M:%S")})
            return kp_fp
    except Exception as e:
        log_event({"round": "csre_rebuild_error", "error": str(e)[:200],
                   "ts": time.strftime("%Y-%m-%d %H:%M:%S")})
    return last_kp_fp


# 生效条件：argparse 从命令行取 --interval（默认 600）、--channel-b、--once 后，--once 为真时只调一次 run_once(channel_b=args.channel_b)，并在环境变量 GAP_DEBUG 为非空真值时调 gap_watch() 后返回；未给 --once 时进入无限循环：每轮 run_once(channel_b=args.channel_b)（异常记 loop_error 后继续），GAP_DEBUG 为非空真值时才 gap_watch()，随后无条件执行 csre_freshness(last_kp_fp)，再按 --interval 睡眠。
def main():
    """长期循环：--interval 秒一轮 run_once，异常留痕不中断。

    （2026-08-28 修复：函数体曾截断为残行 `im`——重启进程 NameError
     短命退出且静默；本轮补全并加轮次异常留痕。）
    v3：补上文档承诺但从未实现的 `--once` 单轮模式（守护/人工验证用）。
    """
    import argparse
    import time as _time

    ap = argparse.ArgumentParser(description="白箱自举后台循环 v3")
    ap.add_argument("--interval", type=int, default=600)
    ap.add_argument("--channel-b", action="store_true")
    ap.add_argument("--once", action="store_true", help="只跑一轮后退出")
    args = ap.parse_args()

    log_event({"round": "loop_start", "interval": args.interval,
               "channel_b": args.channel_b, "once": args.once,
               "pid": os.getpid(), "here": HERE, "wisdom": WISDOM,
               "state": STATE, "data_root": _dp.data_root(),
               "ts": _time.strftime("%Y-%m-%d %H:%M:%S")})

    if args.once:
        run_once(channel_b=args.channel_b)
        if os.environ.get("GAP_DEBUG"):
            gap_watch()
        return

    last_kp_fp = None
    while True:
        try:
            run_once(channel_b=args.channel_b)
        except Exception as e:
            log_event({"round": "loop_error", "error": str(e)[:200],
                       "ts": _time.strftime("%Y-%m-%d %H:%M:%S")})
        if os.environ.get("GAP_DEBUG"):
            gap_watch()
        last_kp_fp = csre_freshness(last_kp_fp)
        _time.sleep(args.interval)


if __name__ == "__main__":
    main()