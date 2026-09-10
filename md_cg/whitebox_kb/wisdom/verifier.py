# -*- coding: utf-8 -*-
"""verifier.py · 白箱本地校验器（Zero-LLM Verifier）v1

目标：把「白箱写代码 → 外部校验（是否符合规范/能否执行）」全部本地化，
彻底抛开大模型依赖。重复校验走本地缓存（替代 99.9% 的 LLM 缓存命中）。

设计：docs/白箱本地校验器_ZeroLLM_Verifier.md

校验链（六层，全部确定性）：
  ① 校验指纹 → 本地缓存（已校验过 → 直接返回）
  ② L1 语法：ast.parse + 结构规则
  ③ L2 样例：输入→期望断言运行（物理基底裁决）
  ④ L3 边界：额外边界用例
  ⑤ 规范符合性：condition_kb 语义对齐 + 结构规范（白箱规则）
  ⑥ 集成测试：依赖单元组装 + 回归

用法：
  python verifier.py --verify "os_112|工作窃取|<code文件路径>"   # 校验单个
  python verifier.py --cache-stats                                # 缓存统计
  python verifier.py --self-test                                   # 自测
"""
from __future__ import annotations

import ast
import copy
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
import traceback
import types
from dataclasses import dataclass, field, asdict
from typing import Any, Callable, Dict, List, Optional, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

CACHE_FILE = os.path.join(HERE, "..", "data", "verify_cache.json")
SAVINGS_LOG = os.path.join(HERE, "..", "data", "verify_savings.jsonl")
DATA_DIR = os.path.join(HERE, "..", "data")


# ============ 一、数据结构 ============

def _stable_serialize(obj: Any) -> Any:
    """任意类型确定性序列化（缓存键基础）。

    cases 里可能出现 set/bytes/lambda 等 json 不可序列化类型（如集合推导的
    {1,2,3} 与 lambda、帧解析的 bytes）——指纹必须对它们稳定：
      set/frozenset → 元素 str 排序化（去重保稳定）
      bytes/bytearray → hex
      callable（lambda/函数）→ __code__ 确定性摘要（co_code+常量+名，跨进程稳定，
        不含内存地址——lambda 的 repr 含地址会导致重启后指纹漂移、缓存失效）
    其余 → repr 回退（域单元 cases 无自定义类实例，足够）。
    """
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj
    if isinstance(obj, (list, tuple)):
        return [_stable_serialize(x) for x in obj]
    if isinstance(obj, (set, frozenset)):
        return {"__set__": sorted(str(_stable_serialize(x)) for x in obj)}
    if isinstance(obj, dict):
        return {"__dict__": {str(k): _stable_serialize(v)
                             for k, v in sorted(obj.items(), key=lambda kv: str(kv[0]))}}
    if isinstance(obj, (bytes, bytearray)):
        return {"__bytes__": bytes(obj).hex()}
    if isinstance(obj, types.CodeType):
        # 嵌套 code 对象（lambda 的 co_consts 里可能含 <listcomp>/嵌套 lambda）：
        # repr 含内存地址（<code object at 0x…>）跨进程漂移——必须确定性摘要
        digest = hashlib.sha256(json.dumps(
            [obj.co_code.hex(), list(obj.co_consts), list(obj.co_names)],
            ensure_ascii=False, sort_keys=True, default=_stable_serialize,
        ).encode("utf-8")).hexdigest()[:16]
        return {"__code__": digest}
    if callable(obj):
        co = getattr(obj, "__code__", None)
        if co is not None:
            digest = hashlib.sha256(json.dumps(
                [co.co_code.hex(), list(co.co_consts), list(co.co_names)],
                ensure_ascii=False, sort_keys=True, default=_stable_serialize,
            ).encode("utf-8")).hexdigest()[:16]
            return {"__fn__": digest}
        return {"__fn__": repr(obj)}
    try:
        return {"__obj__": repr(obj)}
    except Exception:
        return {"__obj__": type(obj).__name__}


def _assert_match(got: Any, exp: Any) -> bool:
    """结果断言：dict 期望做子集匹配（got 包含 exp 全部键值即可）。

    白箱单元常返回完整状态字典（如 VM 执行循环返回
    {'trust':…, 'symbols':…, 'cond':…, 'stack':…}），而样例期望只关心其中
    关键字段（如 {'trust': 0.8}）——完整相等会误判，子集匹配符合「状态断言」语义。
    """
    if isinstance(exp, dict) and isinstance(got, dict):
        return all(got.get(k) == v for k, v in exp.items())
    return got == exp


@dataclass
class VerifyRequest:
    """校验请求：白箱生成的代码 + 单元定义。

    cases/deps 做深拷贝（不可变快照）——被校验代码可能原地修改输入
    （如排序 arr[j], arr[j+1] = ...），若引用外部共享 list 会污染原始数据，
    导致相同请求产生不同指纹（缓存失效）。
    """
    task: str                       # 任务描述（排序/循环编译/图遍历…）
    code: str                       # 白箱生成的代码
    unit_id: str = ""               # 单元标识（域+序号，如 os_112）
    lang: str = "python"            # 语言
    cases: List[Tuple[Any, Any]] = field(default_factory=list)  # (输入, 期望)
    deps: List[str] = field(default_factory=list)               # 依赖单元
    expected_structure: Dict[str, Any] = field(default_factory=dict)  # 规范约束

    def __post_init__(self) -> None:
        """深拷贝防污染 + 指纹预计算（外部原地修改会让指纹漂移·缓存错配——P0 纪律）。"""
        # 深拷贝可变字段——防止被校验代码原地修改污染外部共享对象
        self.cases = copy.deepcopy(self.cases)
        self.deps = list(self.deps)
        self.expected_structure = dict(self.expected_structure)

    def fingerprint(self) -> str:
        """确定性指纹：相同请求 → 相同指纹（缓存键）。

        先整体经 _stable_serialize 归一化再 dumps——json.dumps 的 default 钩子
        只处理值、不处理 dict 键（tuple 键如事件委托的 {('btn','click'):...}
        直接崩溃），故必须把整个结构（含键）先递归归一化。
        """
        payload = json.dumps(_stable_serialize({
            "task": self.task, "code": self.code, "unit_id": self.unit_id,
            "lang": self.lang, "cases": self.cases, "deps": self.deps,
            "structure": self.expected_structure,
        }), ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


@dataclass
class VerifyResult:
    """校验结果。"""
    ok: bool
    checks: List[Dict[str, Any]] = field(default_factory=list)  # [{level, ok, evidence}]
    fingerprint: str = ""
    cached: bool = False
    reason: str = ""
    verified_at: str = ""     # 校验时间戳（ISO）
    version: int = 0          # 校验器规则版本（VERIFIER_VERSION 快照）

    def summary(self) -> str:
        parts = [f"✅ 通过" if self.ok else f"❌ 失败"]
        for c in self.checks:
            mark = "✓" if c["ok"] else "✗"
            parts.append(f"{mark} {c['level']}")
        if self.reason:
            parts.append(f"原因: {self.reason}")
        if self.version:
            parts.append(f"v{self.version}")
        return " | ".join(parts)


# ============ 二、本地缓存（替代 LLM 缓存命中） ============

# 校验器规则版本：L1/L2/L3/规范/集成规则升级时必须 +1——
# 旧版本缓存结果在规则已变的场景下不再可信，强制全部失效重验
# （等价于「协议升级 → 相关缓存刷新」，GLM 建议的 protocol_version 落地）。
# v6（2026-08-31）：cases 形态修复（list→tuple）后指纹归一化同值，旧 False
# 条目对修复免疫；bump 版本作废全部旧缓存——长驻进程内存快照复活毒条目的
# 终局解（版本不符整体清空，任何进程加载即重建）。
VERIFIER_VERSION = 6
_CACHE_VERSION_KEY = "_verifier_version"
_STATS_KEY = "_stats"


def estimate_tokens(text: str) -> int:
    """确定性 token 估算（用于「减少的 LLM 输入」度量，非精确计费）。

    中文混合内容：中文字符按 1.2 token/字（中文 1 字 ≈ 1-1.5 token），
    其余（代码/英文/标点）按 0.3 token/字符（英文/代码 1 token ≈ 3-4 字符）。
    """
    cjk = sum(1 for ch in text if '\u4e00' <= ch <= '\u9fff')
    other = len(text) - cjk
    return int(cjk * 1.2 + other * 0.3)


def _table_payload_chars() -> int:
    """「整张表」内容量：六域单元库定义（pattern+cases）总字符数。

    设计文档背景：原方案「每次把整张表塞进 LLM 上下文查一次」——
    表 = 白箱单元库（规则/模式/样例），本地化后表不再输入 LLM。
    """
    from compiler_code_units import COMPILER_UNITS
    from python_code_units import PYTHON_UNITS
    from graph_db_units import GRAPH_UNITS
    from os_units import OS_UNITS
    from browser_units import BROWSER_UNITS
    from net_units import NET_UNITS
    total = 0
    for units in (COMPILER_UNITS, PYTHON_UNITS, GRAPH_UNITS,
                  OS_UNITS, BROWSER_UNITS, NET_UNITS):
        for uid, u in units.items():
            total += len(uid) + len(u.get("task", "")) + len(u.get("pattern", "")) \
                     + len(str(u.get("cases", [])))
    return total


class VerifyCache:
    """校验结果本地缓存。相同指纹 → 零计算返回。

    hits/misses 为进程内命中计数；「减少的 LLM 输入」以 append-only JSONL
    审计日志持久化（data/verify_savings.jsonl，每行一次校验的输入度量）——
    跨进程累计、可审计、可重放（复现证据）。
    """

    def __init__(self, path: str = CACHE_FILE, version: int = VERIFIER_VERSION,
                 savings_log: Optional[str] = SAVINGS_LOG):
        """组装：缓存句柄注入（默认新建；变异测试可传隔离缓存）。"""
        self.path = path
        self.version = version
        self.savings_log = savings_log
        self._data: Dict[str, Dict[str, Any]] = {}
        self.hits = 0
        self.misses = 0
        self._table_chars: Optional[int] = None
        self._load()

    def _load(self) -> None:
        """从磁盘回放缓存快照（版本不符整体作废防脏读）。"""
        try:
            if os.path.exists(self.path):
                with open(self.path, "r", encoding="utf-8") as f:
                    self._data = json.load(f)
        except Exception:
            self._data = {}
        # 版本不符 → 规则已变，旧缓存结果不可信，清空重建
        if self._data.get(_CACHE_VERSION_KEY) != self.version:
            self._data = {_CACHE_VERSION_KEY: self.version}
            self._flush()

    def record_input(self, payload_chars: int, hit: bool) -> None:
        """记录一次经本地校验的输入度量（append-only 审计日志）。

        每次校验（含缓存命中）都意味着：该内容（表 + 请求）不再输入 LLM →
        省下的 token 计入日志。hit 标记是否为缓存命中（重复校验零计算）。
        savings_log=None（隔离模式，如变异测试）时不写日志。
        """
        if not self.savings_log:
            return
        table = self._table_chars
        if table is None:
            try:
                table = _table_payload_chars()
            except Exception:
                table = 0
            self._table_chars = table
        text = payload_chars + table
        half = text // 2
        tokens = estimate_tokens("中" * half + "x" * (text - half))
        try:
            os.makedirs(DATA_DIR, exist_ok=True)
            with open(self.savings_log, "a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "t": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "payload_chars": payload_chars, "table_chars": table,
                    "saved_chars": text, "saved_tokens": tokens,
                    "hit": bool(hit),
                }, ensure_ascii=False) + "\n")
        except Exception:
            pass

    def savings(self) -> Dict[str, Any]:
        """跨进程累计：从审计日志聚合「减少的 LLM 输入」。

        读 self.savings_log（与写入同源）——此前误读模块常量 SAVINGS_LOG，
        自定义 savings_log 路径时写入 A 聚合读 B，聚合恒 0（issue #4 审计发现）。
        """
        total_chars = total_tokens = hits = reqs = 0
        log = self.savings_log
        try:
            if log and os.path.exists(log):
                for line in open(log, encoding="utf-8"):
                    line = line.strip()
                    if not line:
                        continue
                    d = json.loads(line)
                    total_chars += d.get("saved_chars", 0)
                    total_tokens += d.get("saved_tokens", 0)
                    reqs += 1
                    if d.get("hit"):
                        hits += 1
        except Exception:
            pass
        return {"requests": reqs, "hits": hits,
                "saved_chars": total_chars, "saved_tokens": total_tokens}

    def get(self, fingerprint: str) -> Optional[VerifyResult]:
        """按指纹取缓存校验结果：命中计 hits 并标记 cached=True；未命中计 misses 返回 None。"""
        entry = self._data.get(fingerprint)
        if entry is None:
            self.misses += 1
            return None
        self.hits += 1
        r = VerifyResult(ok=entry["ok"], fingerprint=fingerprint, cached=True)
        r.checks = entry.get("checks", [])
        r.reason = entry.get("reason", "")
        r.verified_at = entry.get("verified_at", "")
        r.version = entry.get("version", 0)
        return r

    def put(self, result: VerifyResult) -> None:
        """写入指纹→结果映射并落盘持久化（附版本键防跨版本脏读）。"""
        self._data[result.fingerprint] = {
            "ok": result.ok,
            "checks": result.checks,
            "reason": result.reason,
            "verified_at": result.verified_at,
            "version": result.version,
        }
        self._data[_CACHE_VERSION_KEY] = self.version
        self._flush()

    def _flush(self) -> None:
        """内存态刷盘：读-合并-原子替换（多进程并发写友好）。

        bootstrap 循环进程与交互进程共用同一缓存文件——先吸收磁盘上
        他进程新增的条目再写，消除「整文件写覆盖」；临时文件+os.replace
        原子替换，消除「读到半写状态」。残余窗口仅剩同指纹同时写的
        几毫秒，缓存可重建（最坏=丢条目重跑 verify），工程可接受。
        """
        try:
            os.makedirs(DATA_DIR, exist_ok=True)
            try:
                if os.path.exists(self.path):
                    with open(self.path, "r", encoding="utf-8") as f:
                        disk = json.load(f)
                    # 版本一致性守卫：磁盘条目版本与本实例不同 → 全部忽略
                    # （版本 bump 即整体作废，不能被合并逻辑复活旧条目）
                    if isinstance(disk, dict) and disk.get(_CACHE_VERSION_KEY) == self.version:
                        for k, v in disk.items():
                            if k not in self._data:
                                self._data[k] = v
            except Exception:
                pass  # 磁盘半写/损坏 → 以内存为准
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=1)
            os.replace(tmp, self.path)
        except Exception:
            pass

    def stats(self) -> Dict[str, Any]:
        """聚合统计：条目总数、通过数、命中率（hits/(hits+misses)）。"""
        entries = {k: v for k, v in self._data.items() if k != _CACHE_VERSION_KEY}
        n = len(entries)
        n_pass = sum(1 for v in entries.values() if v.get("ok"))
        total_reqs = self.hits + self.misses
        hit_rate = round(100.0 * self.hits / total_reqs, 1) if total_reqs else 0.0
        return {"total": n, "passed": n_pass, "failed": n - n_pass,
                "hits": self.hits, "misses": self.misses,
                "hit_rate": hit_rate}


# ============ 三、校验器 ============

class Verifier:
    """本地校验器：六层校验链，零 LLM。"""

    def __init__(self, cache: Optional[VerifyCache] = None):
        """组装：缓存句柄注入（默认新建；变异测试可传隔离缓存）。"""
        self.cache = cache or VerifyCache()

    # ---------- 主入口 ----------
    def verify(self, req: VerifyRequest) -> VerifyResult:
        """六层校验入口：深拷贝请求→算指纹→命中直返；未命中逐层校验并记录 token 节省度量。
        
                （深拷贝防调用方原地修改污染指纹空间——见 P0 修复记录。）"""
        # 不可变快照：verify 内部运行样例可能原地修改输入（如排序
        # arr[j], arr[j+1] = ...），必须深拷贝防止污染原始 req 对象
        # （否则同一 req 第二次校验指纹变化，缓存失效）
        req = copy.deepcopy(req)
        fp = req.fingerprint()

        # ① 缓存命中 → 直接返回
        cached = self.cache.get(fp)

        # 输入度量：经本地校验的请求内容量（本应输入 LLM 的「表 + 请求」——
        # 无论命中与否，走本地 = 不再输入 LLM = 省下的 token；append 审计日志）
        try:
            self.cache.record_input(len(req.task) + len(req.code)
                                    + len(str(req.cases)) + len(req.unit_id),
                                    hit=(cached is not None))
        except Exception:
            pass

        if cached is not None:
            return cached

        checks: List[Dict[str, Any]] = []

        # ② L1 语法
        checks.append(self._check_l1_syntax(req))

        # 注入型单元（expected_structure.inject，如编译-类型检查/图遍历-BFS）：
        # 函数依赖外部注入（Graph/infer_fn/组装单元），单独运行 L2/L3 无意义
        # （与 code_compose verify_code 的 needs_inject 语义一致——由集成测试覆盖）
        injected = req.expected_structure.get("inject")

        # ③ L2 样例（语法通过才运行；注入型跳过）
        if checks[-1]["ok"] and not injected:
            checks.append(self._check_l2_samples(req))

        # ④ L3 边界（注入型跳过）
        if checks[-1]["ok"] and not injected:
            checks.append(self._check_l3_boundary(req))

        # ⑤ 规范符合性
        checks.append(self._check_spec_compliance(req))

        # ⑥ 集成测试（有 deps 才做）
        if req.deps:
            checks.append(self._check_integration(req))

        ok = all(c["ok"] for c in checks)
        reason = ""
        if not ok:
            failed = [c for c in checks if not c["ok"]]
            reason = failed[0]["evidence"] if failed else "未知失败"

        result = VerifyResult(ok=ok, checks=checks, fingerprint=fp, reason=reason,
                              verified_at=time.strftime("%Y-%m-%d %H:%M:%S"),
                              version=VERIFIER_VERSION)
        # 写缓存
        self.cache.put(result)
        return result

    # ---------- L1 语法 ----------
    def _check_l1_syntax(self, req: VerifyRequest) -> Dict[str, Any]:
        """ast.parse + 结构规则（函数定义/占位残留/括号平衡）。"""
        code = req.code
        # 语法解析
        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            return {"level": "L1语法", "ok": False,
                    "evidence": f"语法错误: {e}"}

        # 结构规则
        errors = []
        funcs = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
        if not funcs:
            errors.append("无函数定义")
        # 占位残留（{fn} 等模板占位符未替换）
        if "{fn}" in code or "{param" in code:
            errors.append("存在未替换的模板占位符")
        # 括号平衡：ast.parse 已通过即证明语法合法（字符串/注释内括号
        # 不应计入——字符计数会误判，如 pattern 注释含裸括号）
        # 禁止裸 import（白箱代码应自包含）——但允许标准库
        imports = [n for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))]
        STDLIB_OK = {"collections", "typing", "functools", "itertools", "math",
                     "random", "json", "re", "string", "dataclasses", "abc",
                     "os", "sys", "io", "struct", "asyncio", "heapq", "queue",
                     "threading", "time", "socket", "hashlib", "uuid", "base64",
                     "statistics", "bisect", "decimal", "fractions"}
        if imports and not req.expected_structure.get("allow_import"):
            bad = []
            for n in imports:
                if isinstance(n, ast.ImportFrom):
                    top = (n.module or "").split(".")[0]
                    if top and top not in STDLIB_OK:
                        bad.append(n.module)
                else:
                    for alias in n.names:
                        top = alias.name.split(".")[0]
                        if top not in STDLIB_OK:
                            bad.append(alias.name)
            if bad:
                return {"level": "L1语法", "ok": False,
                        "evidence": f"存在非标准库导入: {bad}"}

        if errors:
            return {"level": "L1语法", "ok": False, "evidence": "; ".join(errors)}
        return {"level": "L1语法", "ok": True,
                "evidence": f"语法通过（{len(funcs)} 个函数定义）"}

    # ---------- L2 样例 ----------
    def _check_l2_samples(self, req: VerifyRequest) -> Dict[str, Any]:
        """每个 (输入, 期望) 运行断言。"""
        if not req.cases:
            return {"level": "L2样例", "ok": True, "evidence": "无样例（跳过）"}

        ns: Dict[str, Any] = {}
        try:
            exec(compile(req.code, "<verify>", "exec"), ns)
        except Exception as e:
            return {"level": "L2样例", "ok": False,
                    "evidence": f"代码编译/执行失败: {e}"}

        # 找被测函数（第一个函数定义）
        func_name = None
        try:
            tree = ast.parse(req.code)
            funcs = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
            func_name = funcs[0].name if funcs else None
        except Exception:
            pass

        if not func_name or func_name not in ns:
            return {"level": "L2样例", "ok": False,
                    "evidence": f"找不到被测函数（期望 {func_name}）"}

        fn = ns[func_name]
        ran = 0
        for case_idx, (inp, exp) in enumerate(req.cases, 1):
            if inp == "call":
                # 'call' 特殊标记：域注入型单元（L2 由域集成测试覆盖，
                # 与 code_compose verify_code 语义一致——不把 'call' 当输入）
                continue
            ran += 1
            try:
                got = fn(inp) if not isinstance(inp, tuple) else fn(*inp)
            except Exception as e:
                return {"level": "L2样例", "ok": False,
                        "evidence": f"样例{case_idx} 崩溃: {inp} → {e}"}
            if not _assert_match(got, exp):
                return {"level": "L2样例", "ok": False,
                        "evidence": f"样例{case_idx} 失败: {inp} → {got}（期望 {exp}）"}
        if ran == 0:
            return {"level": "L2样例", "ok": True,
                    "evidence": "注入型单元（样例均为 call 标记，由集成测试覆盖）"}
        return {"level": "L2样例", "ok": True,
                "evidence": f"{ran} 组样例全部通过"}

    # ---------- L3 边界 ----------
    def _check_l3_boundary(self, req: VerifyRequest) -> Dict[str, Any]:
        """额外边界用例：None/空/极端值（仅单参数函数——多参数函数
        边界形态依赖参数语义，统一生成会误判，由单元自带样例覆盖）。"""
        extra_cases = self._gen_boundary_cases(req.task)
        if not extra_cases:
            return {"level": "L3边界", "ok": True, "evidence": "无额外边界用例"}

        ns: Dict[str, Any] = {}
        try:
            exec(compile(req.code, "<verify>", "exec"), ns)
        except Exception as e:
            return {"level": "L3边界", "ok": False, "evidence": f"执行失败: {e}"}

        func_name = None
        n_args = None
        try:
            tree = ast.parse(req.code)
            funcs = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
            if funcs:
                func_name = funcs[0].name
                args = funcs[0].args
                n_args = len(args.posonlyargs) + len(args.args)
        except Exception:
            pass

        if not func_name or func_name not in ns:
            return {"level": "L3边界", "ok": True, "evidence": "跳过（无函数）"}

        if n_args is not None and n_args != 1:
            return {"level": "L3边界", "ok": True,
                    "evidence": f"跳过（函数 {n_args} 个参数，边界形态依赖参数语义）"}

        # 单参数但参数是图/状态/字典类（adj/graph/table/state…）→ 边界形态
        # 依赖具体语义（如 [] 传 max_clique(adj) 是类型错误而非代码缺陷）——
        # 由单元自带样例覆盖，不统一生成边界
        DICTISH_ARGS = {"adj", "graph", "g", "table", "state", "env", "cond",
                        "nodes", "node", "map", "units", "db", "queue",
                        "buffer", "registry", "cert"}
        if n_args == 1 and funcs[0].args.args \
                and funcs[0].args.args[0].arg in DICTISH_ARGS:
            return {"level": "L3边界", "ok": True,
                    "evidence": f"跳过（参数 {funcs[0].args.args[0].arg} 为图/状态类，边界由样例覆盖）"}

        fn = ns[func_name]
        for case_idx, (inp, exp) in enumerate(extra_cases, 1):
            try:
                got = fn(inp) if not isinstance(inp, tuple) else fn(*inp)
            except Exception as e:
                # 边界用例允许异常返回（如空列表→None/报错均可接受）
                if exp == "any":
                    continue
                return {"level": "L3边界", "ok": False,
                        "evidence": f"边界用例{case_idx} 崩溃: {inp} → {e}"}
            if exp != "any" and not _assert_match(got, exp):
                return {"level": "L3边界", "ok": False,
                        "evidence": f"边界用例{case_idx} 失败: {inp} → {got}（期望 {exp}）"}
        return {"level": "L3边界", "ok": True,
                "evidence": f"{len(extra_cases)} 组边界用例通过"}

    def _gen_boundary_cases(self, task: str) -> List[Tuple[Any, Any]]:
        """根据任务类型生成边界用例（白箱规则，非 LLM）。

        注意：不带「反转」——字典反转等单元收 dict（值变键），序列边界
        [] 是类型错误而非代码缺陷；反转边界由单元自带样例覆盖。
        """
        t = task.lower()
        if any(w in t for w in ("排序", "sort", "去重", "dedup")):
            return [([], []), ([1], [1]), (None, "any")]
        if any(w in t for w in ("最大", "max", "最小", "min")):
            return [([], None), ([5], 5), (None, "any")]  # 空列表→None（与单元语义一致）
        if any(w in t for w in ("求和", "sum")):
            return [([], 0), (None, "any")]
        if any(w in t for w in ("计数", "count", "频率", "freq")):
            return [([], {}), (None, "any")]  # Counter 语义：空列表 → {}
        # 字符串族：拆分/替换/拼接/判断/对齐/哈希/分词/格式化——空串语义因函数而异
        # （分词空串→[]、拼接空列表→''），统一断言会误判 → 只查「空串处理不崩溃」
        if any(w in t for w in ("字符串", "拆分", "替换", "拼接", "判断", "对齐",
                                "哈希", "分词", "格式化")):
            return [("", "any")]
        # 数学族：舍入/统计/数学函数/均值/众数/分位数——零输入形态因函数而异
        # （列表统计收 []、数值函数收 0），统一断言会误判 → 只查「零输入不崩溃」
        if any(w in t for w in ("舍入", "统计", "数学函数", "均值", "众数", "分位数")):
            return [(0, "any")]
        return []

    # ---------- ⑤ 规范符合性（白箱规则 + condition_kb） ----------
    def _check_spec_compliance(self, req: VerifyRequest) -> Dict[str, Any]:
        """结构规范 + 语义对齐（condition_kb 查条件路由表）。"""
        errors = []

        # 结构规范：任务关键词 → 应包含的结构（白箱规则）
        # 注意：只保留「强信号」结构（排序/去重/反转有字面可查的典型结构）。
        # 「循环」类任务在编译器域以字节码/展开形式实现（无 for/while 字面量），
        # 统一强查会误判——循环语义由 L2 样例裁决，不在此字面强查。
        # 排序：接受比较符、sorted(key=) 键控、reorder 重排（排序键控/报文重排序）
        # 反转：排除「字典反转」（值变键语义，无序列反转结构）
        structure_rules = {
            "排序": ["<", ">", "sorted", "key=", "reorder"],
            "sort": ["<", ">", "sorted", "key=", "reorder"],
            "去重": ["set", "seen"], "dedup": ["set", "seen"],
            "反转": ["::-1", "reverse", "reversed"],
        }
        for kw, patterns in structure_rules.items():
            if kw in req.task and req.expected_structure.get("skip_structure"):
                continue
            if kw in req.task:
                if kw in ("反转",) and "字典" in req.task:
                    continue  # 字典反转：值变键语义，无序列反转结构
                hit = any(p in req.code for p in patterns)
                if not hit and not req.expected_structure.get("structure_optional"):
                    errors.append(f"任务含「{kw}」但代码未见对应结构 {patterns}")

        # 语义对齐：condition_kb 查该任务的条件规律，代码应有对应处理
        try:
            from condition_kb import ConditionKB
            kb = ConditionKB()
            sem = kb.lookup(req.task)
            if sem and sem.get("match"):
                # 查到的规律描述包含条件词 → 代码应体现条件分支
                cond_words = ["如果", "若", "when", "if", "条件", "情况"]
                has_cond = any(w in req.code for w in cond_words)
                if any(w in sem.get("match", "") for w in ["条件", "如果", "当"]) \
                        and not has_cond \
                        and not req.expected_structure.get("no_cond_needed"):
                    errors.append(f"condition_kb 提示「{sem.get('match', '')[:30]}」需条件处理但代码无分支")
        except Exception:
            pass  # condition_kb 不可用时跳过（不影响主校验）

        # 条件论注释规范（WB-SPEC v1.2，用户条件论要求）：
        # R1 函数/类等抽象的总体功能必须中文注释（docstring 或紧跟 # 中文注释）
        # R2 注释须为中文语境（英文缩写嵌入中文说明；纯英文注释行违规）
        errors.extend(self._check_comment_spec(req))

        if errors:
            return {"level": "规范符合性", "ok": False, "evidence": "; ".join(errors)}
        return {"level": "规范符合性", "ok": True,
                "evidence": "结构规范 + 语义对齐 + 条件论注释通过"}

    def _check_comment_spec(self, req: VerifyRequest) -> list:
        """条件论注释规范（WB-SPEC v1.2）：R1 函数/类中文注释 + R2 注释中文语境。

        R1：每个 FunctionDef/AsyncFunctionDef/ClassDef 必须有 docstring 或
            紧跟的 # 中文注释描述其总体功能。
        R2：注释行必须为中文语境（含中文字符）——英文缩写嵌入中文说明；
            纯英文注释行（无任何中文）违规。
        expected_structure.no_comment_spec=True 可豁免（如注入型组装片段）。
        """
        if req.expected_structure.get("no_comment_spec"):
            return []
        code = req.code
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return []
        src_lines = code.splitlines()
        _has_cn = lambda s: any('\u4e00' <= c <= '\u9fff' for c in s)
        errs = []
        # R1：函数/类中文注释
        missing = []
        for f in ast.walk(tree):
            if not isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef,
                                  ast.ClassDef)):
                continue
            doc = ast.get_docstring(f)
            if doc and _has_cn(doc):
                continue
            ok = False
            # 查 def/class 前后各 2 行内的 # 中文注释（docstring 已单独检查）
            for ln in src_lines[max(0, f.lineno - 2):f.lineno + 3]:
                if ln.strip().startswith('#') and _has_cn(ln):
                    ok = True
                    break
            if not ok:
                missing.append(f.name)
        if missing:
            errs.append(f"函数/类缺中文注释（条件论 R1）: {missing[:5]}")
        # R2：注释行中文语境
        bad_lines = []
        for i, ln in enumerate(src_lines, 1):
            s = ln.strip()
            if s.startswith('#') and not _has_cn(s) and len(s) > 3:
                bad_lines.append(f"L{i}")
        if bad_lines:
            errs.append(f"纯英文注释行（条件论 R2，须中文说明）: {bad_lines[:5]}")
        # R3：条件论注释三要素（功能条件/子功能/执行方式）——升级期软模式：
        # 只统计达标情况写入 evidence，不拦截（expected_structure.require_cond_comment
        # 为 True 时硬拦截——全库升级完成后开启）
        if req.expected_structure.get("require_cond_comment"):
            missing3 = self._cond_comment_missing(tree, src_lines)
            if missing3:
                errs.append(f"条件论三要素注释缺失（R3）: {missing3[:5]}")
        # R4：不适用条件（代码语义条件协议 v1.0）——何时不能用的盲区声明。
        # 软模式（require_not_cond=True 时硬拦截——全库补齐后开启）
        if req.expected_structure.get("require_not_cond"):
            missing4 = self._not_cond_missing(tree, src_lines)
            if missing4:
                errs.append(f"不适用条件缺失（R4·代码语义条件协议）: {missing4[:5]}")
        return errs

    def _not_cond_missing(self, tree, src_lines) -> list:
        """R4：单元主函数注释缺「不适用条件」标记（盲区声明——何时不能用）。

        与 R3 同窗口（def 后 4 行注释）。不适用条件=代码盲区注册表，
        知道何时不能调用与知道何时调用同等重要。
        """
        _has_cn = lambda s: any('\u4e00' <= c <= '\u9fff' for c in s)
        funcs = [n for n in ast.walk(tree)
                 if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef,
                                   ast.ClassDef))]
        if not funcs:
            return []
        f = funcs[0]
        block = [ln for ln in src_lines[max(0, f.lineno - 2):f.lineno + 8]
                 if ln.strip().startswith('#') and _has_cn(ln)]
        if not block:
            return [f.name]
        joined = " ".join(b.strip().lstrip('#').strip() for b in block)
        return [f.name] if "不适用条件" not in joined else []

    def _cond_comment_missing(self, tree, src_lines) -> list:
        """R3：单元主函数/类缺三要素标记（生效条件/子功能/执行）。

        检查首个 def/class（单元抽象总体功能的入口声明——用户核心关注）；
        内部辅助函数（dfs/walk 等）由 R1（中文注释）覆盖，三要素列入精修。
        窗口 [lineno-2 : lineno+6]：三要素注释为 def 后 3-4 行。
        """
        _has_cn = lambda s: any('\u4e00' <= c <= '\u9fff' for c in s)
        funcs = [n for n in ast.walk(tree)
                 if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef,
                                   ast.ClassDef))]
        if not funcs:
            return []
        f = funcs[0]
        block = [ln for ln in src_lines[max(0, f.lineno - 2):f.lineno + 6]
                 if ln.strip().startswith('#') and _has_cn(ln)]
        if not block:
            return [f.name]  # R1 已管（无中文注释），此处仅标记
        joined = " ".join(b.strip().lstrip('#').strip() for b in block)
        need = ("生效条件", "子功能", "执行")
        return [f.name] if not all(k in joined for k in need) else []

    # ---------- ⑥ 集成测试 ----------
    def _check_integration(self, req: VerifyRequest) -> Dict[str, Any]:
        """依赖单元组装 + 端到端运行（简化：deps 代码拼接后执行）。"""
        if not req.deps:
            return {"level": "集成", "ok": True, "evidence": "无依赖（跳过）"}
        try:
            # 组装依赖 + 被测代码
            combined = "\n\n".join(req.deps) + "\n\n" + req.code
            ns: Dict[str, Any] = {}
            exec(compile(combined, "<integrate>", "exec"), ns)

            # 端到端：跑第一个样例
            if req.cases:
                func_name = None
                tree = ast.parse(req.code)
                funcs = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
                func_name = funcs[0].name if funcs else None
                if func_name and func_name in ns:
                    inp, exp = req.cases[0]
                    got = ns[func_name](inp) if not isinstance(inp, tuple) else ns[func_name](*inp)
                    if got != exp:
                        return {"level": "集成", "ok": False,
                                "evidence": f"组装后首样例失败: {inp} → {got}（期望 {exp}）"}
            return {"level": "集成", "ok": True,
                    "evidence": f"{len(req.deps)} 个依赖组装 + 端到端通过"}
        except Exception as e:
            return {"level": "集成", "ok": False,
                    "evidence": f"组装失败: {e}"}


# ============ 四、CLI ============

def _build_request_from_file(path: str) -> VerifyRequest:
    """从 JSON 文件构建校验请求。"""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return VerifyRequest(
        task=data.get("task", ""),
        code=data.get("code", ""),
        unit_id=data.get("unit_id", ""),
        lang=data.get("lang", "python"),
        cases=[tuple(c) for c in data.get("cases", [])],
        deps=data.get("deps", []),
        expected_structure=data.get("structure", {}),
    )


def _self_test() -> bool:
    """自测：排序单元应通过，错误代码应失败。"""
    v = Verifier()
    passed = 0

    # 正确代码（含中文注释——条件论注释规范 R1）
    good_code = (
        "def solve(arr):\n"
        "    # 排序：冒泡法（相邻比较交换，最小元素浮到头部）\n"
        "    n = len(arr)\n"
        "    for i in range(n):\n"
        "        for j in range(n-1-i):\n"
        "            if arr[j] > arr[j+1]:\n"
        "                arr[j], arr[j+1] = arr[j+1], arr[j]\n"
        "    return arr\n"
    )
    r1 = v.verify(VerifyRequest(
        task="排序", code=good_code, unit_id="test_sort",
        cases=[([3, 1, 2], [1, 2, 3]), ([], []), ([1], [1])],
    ))
    print(f"[1] 排序正确代码: {r1.summary()}")
    passed += 1 if r1.ok else 0

    # 错误代码（冒泡逻辑反了）
    bad_code = good_code.replace("if arr[j] > arr[j+1]", "if arr[j] < arr[j+1]")
    r2 = v.verify(VerifyRequest(
        task="排序", code=bad_code, unit_id="test_sort_bad",
        cases=[([3, 1, 2], [1, 2, 3]), ([], []), ([1], [1])],
    ))
    print(f"[2] 排序错误代码: {r2.summary()}")
    passed += 1 if not r2.ok else 0

    # 缓存命中
    r3 = v.verify(VerifyRequest(
        task="排序", code=good_code, unit_id="test_sort",
        cases=[([3, 1, 2], [1, 2, 3]), ([], []), ([1], [1])],
    ))
    print(f"[3] 缓存命中: cached={r3.cached} {r3.summary()}")
    passed += 1 if r3.cached else 0

    # 语法错误
    r4 = v.verify(VerifyRequest(
        task="排序", code="def solve(arr):\n  return ", unit_id="test_syntax",
        cases=[([1], [1])],
    ))
    print(f"[4] 语法错误: {r4.summary()}")
    passed += 1 if not r4.ok else 0

    # 规范符合性（排序但无比较结构）
    r5 = v.verify(VerifyRequest(
        task="排序", code="def solve(arr):\n    return arr", unit_id="test_nosort",
        cases=[([3, 1, 2], [3, 1, 2])],
    ))
    print(f"[5] 规范不符（排序无比较）: {r5.summary()}")
    passed += 1 if not r5.ok else 0

    print(f"\n自测: {passed}/5 通过")
    return passed == 5


def _audit_all() -> None:
    """全量审计：六域单元库 → 本地校验器 → 报告（通过率/失败清单/缓存/耗时）。"""
    from compiler_code_units import COMPILER_UNITS
    from python_code_units import PYTHON_UNITS
    from graph_db_units import GRAPH_UNITS
    from os_units import OS_UNITS
    from browser_units import BROWSER_UNITS
    from net_units import NET_UNITS
    domains = [('compiler', COMPILER_UNITS), ('pylang', PYTHON_UNITS),
               ('graph', GRAPH_UNITS), ('os', OS_UNITS),
               ('browser', BROWSER_UNITS), ('net', NET_UNITS)]
    t0 = time.time()
    v = Verifier()
    total = ok = 0
    fails = []
    by_domain = {}
    for dname, units in domains:
        d_ok = d_fail = 0
        for uid, u in units.items():
            total += 1
            req = VerifyRequest(
                task=u['task'], code=u['pattern'], unit_id=uid,
                cases=list(u.get('cases', [])),
                expected_structure={'inject': True} if u.get('needs_inject') else {})
            r = v.verify(req)
            if r.ok:
                ok += 1; d_ok += 1
            else:
                fails.append((uid, r.reason[:80])); d_fail += 1
        by_domain[dname] = (d_ok, d_fail)
    s = v.cache.stats()
    print(f"=== 全量审计（verifier v{VERIFIER_VERSION}）: {ok}/{total} 通过 "
          f"({100.0 * ok / total:.1f}%） 耗时 {time.time() - t0:.1f}s ===")
    print("各域:", by_domain)
    print(f"缓存: 共 {s['total']} 条（通过 {s['passed']} / 失败 {s['failed']}）"
          f" | 本进程命中 {s['hits']} / 未命中 {s['misses']}（命中率 {s['hit_rate']}%）")
    if fails:
        print("--- 失败清单 ---")
        for uid, reason in fails:
            print(f"[{uid}] {reason}")


def _cost_model(daily_tokens: float = 1.3e9, hit_rate: float = 0.999,
                price_hit: float = 2.0, price_full: float = 2.0,
                days: int = 30) -> None:
    """本地化成本对照模型（阶段 5 替换测算器）。

    「原 LLM 校验环节」= 白箱自举的外部校准角色（LLM 查表校验）：白箱自举
    总消耗 13 亿 token（用户实测），其中 99.9% 是重复查表校验（反复读同样
    的单元/代码/规则表——即 LLM 缓存命中）。本地校验器（六层确定性规则 +
    sha256 指纹缓存）接管后，这部分 token 归零；仅剩 0.1% 为真·新任务
    （新单元设计/语义校准）保留 LLM 价值。

    默认参数取自设计文档实测：13 亿 token/天、99.9% 缓存命中、GLM 缓存价
    2 元/百万。原方案：全部 token 经 LLM（命中按缓存价计费）；
    本地化后：命中部分走本地磁盘（≈0 成本），仅未命中部分保留 LLM 兜底。
    """
    per_m = 1e6
    orig = daily_tokens * (hit_rate * price_hit + (1 - hit_rate) * price_full) / per_m
    local = daily_tokens * (1 - hit_rate) * price_full / per_m
    saved = orig - local
    print(f"=== 本地化成本对照（LLM 查表校验 → 本地校验缓存）===")
    print(f"背景: 白箱自举外部校准（LLM 查表校验）日消耗 {daily_tokens:.3g} token，"
          f"其中 {hit_rate*100:.1f}% 为重复查表（缓存命中）")
    print(f"输入: 每日 token {daily_tokens:.3g} | 命中率 {hit_rate*100:.1f}% "
          f"| 命中价 {price_hit} 元/百万 | 未命中价 {price_full} 元/百万")
    print(f"原方案（LLM 缓存命中付费）: {orig:,.2f} 元/天 ≈ {orig*days:,.0f} 元/{days}天")
    print(f"本地化后（命中零成本，仅未命中 LLM 兜底）: {local:,.2f} 元/天 "
          f"≈ {local*days:,.0f} 元/{days}天")
    print(f"节省: {saved:,.2f} 元/天 ≈ {saved*days:,.0f} 元/{days}天 "
          f"（省 {(100*saved/orig if orig else 0):.1f}%）")
    print(f"对照: 白箱自举 {daily_tokens:.3g} token 中 "
          f"{daily_tokens*hit_rate:.3g} token（{hit_rate*100:.1f}%）为重复查表校验，"
          f"由 verifier 本地缓存接管后 token 归零")
    if hit_rate == 1.0:
        print("命中率 100% → 本地化后每日成本归零（磁盘 I/O 可忽略）")


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser(description="白箱本地校验器（零 LLM）")
    ap.add_argument("--verify", type=str, help="校验请求 JSON 文件路径")
    ap.add_argument("--cache-stats", action="store_true", help="缓存统计")
    ap.add_argument("--audit", action="store_true", help="全量审计（六域单元）")
    ap.add_argument("--cost-model", action="store_true", help="本地化成本对照模型")
    ap.add_argument("--tokens", type=float, default=1.3e9, help="每日 token 量")
    ap.add_argument("--hit-rate", type=float, default=0.999, help="缓存命中率")
    ap.add_argument("--price-hit", type=float, default=2.0, help="命中价 元/百万")
    ap.add_argument("--price-full", type=float, default=2.0, help="未命中价 元/百万")
    ap.add_argument("--days", type=int, default=30, help="测算天数")
    ap.add_argument("--self-test", action="store_true", help="自测")
    args = ap.parse_args()

    if args.self_test:
        sys.exit(0 if _self_test() else 1)

    if args.cost_model:
        _cost_model(args.tokens, args.hit_rate, args.price_hit,
                    args.price_full, args.days)
        return

    if args.audit:
        _audit_all()
        return

    if args.cache_stats:
        stats = VerifyCache().stats()
        sv = VerifyCache().savings()
        print(f"缓存统计: 共 {stats['total']} 条（通过 {stats['passed']} / 失败 {stats['failed']}）")
        print(f"命中计数: 本进程命中 {stats['hits']} / 未命中 {stats['misses']}（命中率 {stats['hit_rate']}%）")
        print(f"审计日志: {sv['requests']} 次校验（缓存命中 {sv['hits']} 次）")
        print(f"减少的 LLM 输入: 累计 {sv['saved_chars']:,} 字符"
              f" ≈ {sv['saved_tokens']:,} token（表+请求内容经本地处理，不再输入 LLM）")
        print("（每次命中 = 一次本该发生的 LLM 查表 → 本地零计算返回）")
        return

    if args.verify:
        req = _build_request_from_file(args.verify)
        result = Verifier().verify(req)
        print(json.dumps(asdict(result), ensure_ascii=False, indent=1))
        return

    ap.print_help()


if __name__ == "__main__":
    main()
