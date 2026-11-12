# -*- coding: utf-8 -*-
"""接口形状（schema）与 golden 例子——把「可复跑」扩到接口面。

外部 issue #5 第 15 条：四个动作只有签名、没有字段表，而「可复跑」是 KPI 之一，
接口的形状本身就是判据的一部分。

设计约束：
* **零外部依赖**（D-005）：不引入 jsonschema，本模块自带极简校验器。
* **文档与实现共用一份**：schema 与 golden 在此定义，文档引用，测试断言。
* **只约束已实现的部分**：Envelope 尚未定型（见 issues #15），标 target_only，
  不假装它已经能通过校验。
"""

import json

__all__ = ["VERDICT", "ENVELOPE", "LEDGER", "GOLDEN", "validate", "main"]

# ---- 极简 schema 描述 ----------------------------------------------------
# 类型标记：str / int / num / bool / list / dict / "nullable:X" / "enum:a|b"
VERDICT = {
    "state": "enum:ACCEPT|REJECT|DEFER|BLINDSPOT",
    "kind": "str",
    "basis": "nullable:str",
    "evidence": "str",
    "detail": {
        "acceptance": "enum:formal_pass|formal_reject|undetermined",
        "verification_state": "enum:unverified|confirmed|weakened|falsified",
    },
}

ENVELOPE = {
    "items": "list",
    "completeness": "bool",
    "hit_count": "nullable:int",
    "snapshot_id": "nullable:str",
    "operation_status": "enum:success|partial|timeout|unavailable|operation_error",
}

LEDGER = {
    "seq": "int",
    "op": "str",
    "node_id": "str",
    "outcome": "str",
}

#: golden 例子：三种裁决各一，外加一个 envelope 目标态样例（标 target_only）
GOLDEN = [
    {"name": "verdict_accept", "schema": "verdict", "target_only": False, "doc": {
        "state": "ACCEPT", "kind": "work_done", "basis": "test",
        "evidence": "形式完备：V1 条件空间齐全、V2 见出处标记、V4 未发现字面同槽冲突",
        "detail": {"acceptance": "formal_pass", "verification_state": "unverified"}}},
    {"name": "verdict_reject", "schema": "verdict", "target_only": False, "doc": {
        "state": "REJECT", "kind": "work_done", "basis": "test",
        "evidence": "V1 未过：条件空间缺 observation_position；请补齐后重新提交",
        "detail": {"acceptance": "formal_reject", "verification_state": "unverified",
                   "return_to": "author", "action": "resubmit_with_condition_space"}}},
    {"name": "verdict_blindspot", "schema": "verdict", "target_only": False, "doc": {
        "state": "BLINDSPOT", "kind": "work_done", "basis": "test",
        "evidence": "V4 无法判定：检索失败；按 I5/I6 不得判通过",
        "detail": {"acceptance": "undetermined", "verification_state": "unverified",
                   "criterion": "V4", "v4_status": "unknown"}}},
    {"name": "envelope_target", "schema": "envelope", "target_only": True, "doc": {
        "items": [], "completeness": True, "hit_count": 0,
        "snapshot_id": "snap-0001", "operation_status": "success"}},
]

_SCHEMAS = {"verdict": VERDICT, "envelope": ENVELOPE, "ledger": LEDGER}


def _check_value(spec, value, path, errs):
    # 顺序要紧：dict 必须在字符串方法之前判——否则顶层 spec（dict）调 startswith 直接崩。
    if isinstance(spec, dict):
        if not isinstance(value, dict):
            errs.append("%s: 期望 dict，实为 %s" % (path, type(value).__name__))
            return
        for k, sub in spec.items():
            if k not in value:
                errs.append("%s.%s: 缺必填字段" % (path, k))
            else:
                _check_value(sub, value[k], "%s.%s" % (path, k), errs)
        return
    if spec.startswith("enum:"):
        allowed = spec[5:].split("|")
        if value not in allowed:
            errs.append("%s: %r 不在枚举 %s 内" % (path, value, allowed))
        return
    if spec.startswith("nullable:"):
        if value is None:
            return
        _check_value(spec[9:], value, path, errs)
        return
    if spec == "str":
        if not isinstance(value, str):
            errs.append("%s: 期望 str，实为 %s" % (path, type(value).__name__))
    elif spec == "int":
        if not isinstance(value, int) or isinstance(value, bool):
            errs.append("%s: 期望 int，实为 %s" % (path, type(value).__name__))
    elif spec == "num":
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            errs.append("%s: 期望 num，实为 %s" % (path, type(value).__name__))
    elif spec == "bool":
        if not isinstance(value, bool):
            errs.append("%s: 期望 bool，实为 %s" % (path, type(value).__name__))
    elif spec == "list":
        if not isinstance(value, list):
            errs.append("%s: 期望 list，实为 %s" % (path, type(value).__name__))
    elif spec == "dict":
        if not isinstance(value, dict):
            errs.append("%s: 期望 dict，实为 %s" % (path, type(value).__name__))
    else:
        errs.append("%s: 未知 spec %r" % (path, spec))


def validate(doc, schema_name):
    """校验 doc 符合指定 schema。返回 (ok, errors)。未知 schema 抛 KeyError。"""
    spec = _SCHEMAS[schema_name]
    errs = []
    _check_value(spec, doc, "$", errs)
    return (not errs), errs


def check_golden():
    """全部非 target_only 的 golden 例子必须过校验。"""
    out = []
    for g in GOLDEN:
        if g.get("target_only"):
            out.append({"name": g["name"], "status": "target_only"})
            continue
        ok, errs = validate(g["doc"], g["schema"])
        out.append({"name": g["name"], "status": "pass" if ok else "fail", "errors": errs})
    return out


def main(argv=None):
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    res = check_golden()
    print(json.dumps(res, ensure_ascii=False, indent=1))
    return 0 if all(r["status"] != "fail" for r in res) else 1


if __name__ == "__main__":
    raise SystemExit(main())
