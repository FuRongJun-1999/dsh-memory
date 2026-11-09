"""Native task-result facts and reusable experience candidates.

Design reference: Tencent-Hunyuan/Hy-Memory, coding/{types,writer,fact_reconciler}.py
at fba347ad8d04eefbc51a466fa4cbd7d4e1936109. This is an independent implementation
using Lingshu's Markdown truth source, permissions and qualification rules.

The caller extracts drafts; this module never calls a model. A record keeps one
session result, including blocked/failed results, and zero or more experiences.
Recording evidence does not verify its claims. Facts are immutable; replacing a
fact is explicit, scoped to the same task and subject, and preserves history.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import os
import re

from . import audit, crypto, security, tasks
from .fsutil import FileLock
from .mdcg import expand_query_terms

FACT_TAG = "task-memory:fact"
EXPERIENCE_TAG = "task-memory:experience"
FIELD = "task_memory"
OUTCOMES = ("succeeded", "failed", "blocked", "partial")
PAYLOAD_MARKER = "\n\n<!-- task-memory-payload:v1 -->\n```json\n"
PAYLOAD_END = "\n```\n"


def _text(value, field, *, required=True, limit=2000):
    """Accept strings only; fail before writing on missing or oversized data."""
    if not isinstance(value, str) or (required and not value.strip()):
        raise ValueError(f"{field} must be a {'nonempty ' if required else ''}string")
    if len(value) > limit:
        raise ValueError(f"{field} exceeds {limit} characters; store a source reference")
    return value.strip() if required else value


def _strings(value, field, maximum):
    if not isinstance(value, list) or len(value) > maximum:
        raise ValueError(f"{field} must be a list with at most {maximum} entries")
    return tuple(_text(item, field, limit=1000) for item in value)


def _object(value, field, allowed):
    if not isinstance(value, dict) or set(value) - set(allowed):
        raise ValueError(f"{field} must be an object containing only {sorted(allowed)}")
    return value


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _id(prefix, value):
    return prefix + hashlib.sha256(_json(value).encode("utf-8")).hexdigest()[:32]


def _metadata(payload):
    # Frontmatter is plaintext even on private nodes. Keep narrative data in the
    # body so the native sealing hook protects facts, details and experiences.
    return {"format": 1, "kind": payload["kind"], "task_id": payload["task_id"],
            "payload_sha256": hashlib.sha256(_json(payload).encode("utf-8")).hexdigest()}


def _stored_content(content, payload):
    return content + PAYLOAD_MARKER + _json(payload) + PAYLOAD_END


def _protected_content(cg, nid, content, sensitivity):
    if not crypto.is_encrypted_level(sensitivity):
        return content
    # Seal before add() derives plaintext routing metadata from CCG lines.
    sealed = cg._seal_content(nid, content, sensitivity)
    if not crypto.is_encrypted(sealed):
        raise ValueError("private task memory requires the native encryption writer")
    return sealed


def _memory(rec):
    meta = rec["frontmatter"].get(FIELD)
    content = rec.get("content") or ""
    if not isinstance(meta, dict) or meta.get("format") != 1:
        raise ValueError("task memory payload is unavailable")
    head, separator, tail = content.rpartition(PAYLOAD_MARKER)
    if not separator or not tail.endswith(PAYLOAD_END):
        raise ValueError("task memory payload is unavailable")
    try:
        data = json.loads(tail[:-len(PAYLOAD_END)])
    except (ValueError, TypeError) as exc:
        raise ValueError("task memory payload is unavailable") from exc
    if not isinstance(data, dict) or _metadata(data) != meta:
        raise ValueError("task memory payload does not match its routing metadata")
    return data


def _admit(cg, content, sensitivity):
    """Reuse the existing admission policy, including all persisted metadata."""
    rules, _source, error = audit.resolve_rulebook()
    if error is not None:
        raise ValueError("task-memory write policy unavailable")
    verdict = audit.audit("text", {"content": content, "sensitivity": sensitivity},
                          {"cg": cg, "principal": getattr(cg, "principal", None), "rules": rules})
    if verdict["state"] != audit.ACCEPT:
        raise ValueError(f"task-memory admission rejected ({verdict['state']})")


@dataclass(frozen=True)
class TaskFactDraft:
    statement: str
    subject: str
    outcome: str
    details: str = ""
    files: tuple[str, ...] = ()
    supersedes: str = ""


@dataclass(frozen=True)
class ExperienceDraft:
    task: str
    solution: str
    conditions: str
    boundary: str
    verification: str
    search_keys: tuple[str, ...] = ()


def parse_drafts(memory):
    """Validate the whole batch before any write; ownership never comes from a draft."""
    data = _object(memory, "memory", {"record_id", "fact", "experiences"})
    record_id = _text(data.get("record_id"), "record_id", limit=128)
    fact = _object(data.get("fact"), "fact", TaskFactDraft.__dataclass_fields__)
    outcome = _text(fact.get("outcome"), "fact.outcome")
    if outcome not in OUTCOMES:
        raise ValueError(f"fact.outcome must be one of {OUTCOMES}")
    draft = TaskFactDraft(
        statement=_text(fact.get("statement"), "fact.statement"),
        subject=_text(fact.get("subject"), "fact.subject", limit=256),
        outcome=outcome,
        details=_text(fact.get("details", ""), "fact.details", required=False, limit=65536),
        files=_strings(fact.get("files", []), "fact.files", 128),
        supersedes=_text(fact.get("supersedes", ""), "fact.supersedes", required=False, limit=128),
    )
    raw = data.get("experiences", [])
    if not isinstance(raw, list) or len(raw) > 20:
        raise ValueError("experiences must be a list with at most 20 entries")
    experiences = []
    for item in raw:
        exp = _object(item, "experience", ExperienceDraft.__dataclass_fields__)
        values = {key: _text(exp.get(key), f"experience.{key}", limit=12000)
                  for key in ("task", "solution", "conditions", "boundary", "verification")}
        values["search_keys"] = _strings(exp.get("search_keys", []), "search_keys", 5)
        experiences.append(ExperienceDraft(**values))
    return record_id, draft, tuple(experiences)


def _task(cg, name):
    principal = getattr(cg, "principal", None)
    if principal is not None:
        principal.require_op("task")
    nid = tasks.task_node_id(_text(name, "task", limit=128))
    rec = cg.get(nid) if nid else None
    if not rec or not security.visible_to(cg, rec["frontmatter"]):
        raise ValueError("task is unavailable")
    fm = rec["frontmatter"]
    if fm.get("layer") != "structural" or tasks.TASK_TAG not in (fm.get("tags") or []):
        raise ValueError("task is unavailable")
    return nid, fm


def _existing(cg, nid, payload):
    rec = cg.get(nid)
    if rec is None:
        if nid in cg.index.get("nodes", {}):
            raise ValueError("memory identity is unavailable")
        return None
    if _json(_memory(rec)) != _json(payload):
        raise ValueError("record_id already names different content; use a new record_id")
    return rec


def _fact_content(task_id, draft):
    return "\n".join([
        f"# 功能名：任务会话结果 {task_id}",
        f"# 生效条件：任务 {task_id} 的历史回溯",
        f"# 子功能：{draft.subject}",
        f"# 执行：{draft.statement}",
        "# 验证方式：会话报告，尚未独立核验",
        "# 不适用条件：不能以记录存在代替独立验证或执行授权",
        "", "## 原始记录", draft.details,
    ])


def _experience_content(draft):
    return "\n".join([
        f"# 功能名：{draft.task}",
        f"# 生效条件：{draft.conditions}",
        "# 子功能：" + "；".join(draft.search_keys or (draft.task,)),
        f"# 执行：{draft.solution}",
        f"# 验证方式：待核验：{draft.verification}",
        f"# 不适用条件：{draft.boundary}",
    ])


def record(cg, task, memory):
    """Persist a fact first; independently fill experience candidates on retries.

    This is not a multi-node transaction. A candidate write failure is returned
    explicitly while the committed fact remains available. Repeating the same
    record_id/content repairs missing candidates without duplicating nodes.
    """
    record_id, fact, experiences = parse_drafts(memory)
    task_id, task_fm = _task(cg, task)
    sensitivity = task_fm.get("sensitivity") or security.DEFAULT_SENSITIVITY
    principal = getattr(cg, "principal", None)
    if principal is not None:
        principal.require_layer_write("contextual", sensitivity)
    fact_id = _id("tmf_", [task_id, record_id])
    exp_items = [(_id("tme_", [task_id, asdict(exp)]), exp) for exp in experiences]
    exp_items = list({nid: exp for nid, exp in exp_items}.items())
    payload = json.loads(_json({"kind": "fact", "task_id": task_id,
                               "record_id": record_id, "fact": asdict(fact),
                               "experience_ids": [nid for nid, _ in exp_items]}))
    with FileLock(os.path.join(cg.root, "_task_memory.lock")):
        # Check every identity before the first write. Explicit links never merge
        # different tasks/subjects merely because their wording is similar.
        previous = _existing(cg, fact_id, payload)
        if fact.supersedes:
            old = cg.get(fact.supersedes)
            old_data = _memory(old) if old else {}
            if (fact.supersedes == fact_id or old_data.get("kind") != "fact"
                    or old_data.get("task_id") != task_id
                    or old_data.get("fact", {}).get("subject") != fact.subject):
                raise ValueError("supersedes must reference a visible fact of the same task and subject")
            if not security.visible_to(cg, old["frontmatter"]):
                raise ValueError("supersedes is unavailable")
            if old["frontmatter"].get("sensitivity", sensitivity) != sensitivity:
                raise ValueError("supersedes cannot change the evidence sensitivity")
        exp_payloads = {nid: json.loads(_json({"kind": "experience", "task_id": task_id,
                                              "experience": asdict(exp)}))
                        for nid, exp in exp_items}
        existing = {nid: _existing(cg, nid, exp_payloads[nid]) for nid, _ in exp_items}
        if previous is None:
            fact_content = _stored_content(_fact_content(task_id, fact), payload)
            _admit(cg, fact_content, sensitivity)
            cg.add(fact_id, _protected_content(cg, fact_id, fact_content, sensitivity), layer="contextual",
                   tags=[FACT_TAG, f"task:{task_id}"], importance=0.5, confidence=0.5,
                   role="assistant", sensitivity=sensitivity, verification_state="unverified",
                   derived_from=[task_id] + ([fact.supersedes] if fact.supersedes else []),
                   **{FIELD: _metadata(payload)})
        written, reused, errors = [], [], []
        for nid, exp in exp_items:
            if existing[nid] is not None:
                reused.append(nid)
                continue
            try:
                exp_content = _stored_content(_experience_content(exp), exp_payloads[nid])
                _admit(cg, exp_content, sensitivity)
                cg.add(nid, _protected_content(cg, nid, exp_content, sensitivity), layer="knowledge",
                       tags=[EXPERIENCE_TAG, f"task:{task_id}"], importance=0.6,
                       confidence=0.5, role="assistant", sensitivity=sensitivity,
                       verification_state="unverified", derived_from=[fact_id],
                       depends_on=[fact_id],
                       **{FIELD: _metadata(exp_payloads[nid])})
                written.append(nid)
            except Exception as exc:
                errors.append({"id": nid, "error": type(exc).__name__, "reason": str(exc)})
        cg.flush()
    return {"ok": not errors, "committed": True, "partial": bool(errors),
            "fact_id": fact_id, "fact_reused": previous is not None,
            "experience_ids": written + reused, "written": written, "reused": reused,
            "errors": errors, "verification_state": "unverified"}


def get(cg, node_id):
    """Read one complete original record through the same permission gates."""
    principal = getattr(cg, "principal", None)
    if principal is not None:
        principal.require_op("task")
    rec = cg.get(_text(node_id, "node_id", limit=128))
    if not rec or not security.visible_to(cg, rec["frontmatter"]):
        raise ValueError("task memory is unavailable")
    data = _memory(rec)
    if data.get("kind") not in ("fact", "experience"):
        raise ValueError("task memory is unavailable")
    _task(cg, data.get("task_id"))
    return {"ok": True, "id": node_id, "memory": data,
            "verification_state": rec["frontmatter"].get("verification_state", "unverified")}


def recall(cg, task, *, query="", limit=5, include_history=False):
    """Task-scoped lexical recall with separate budgets and original-record refs.

    Scope, visibility, supersession and qualification are resolved before Top-K.
    Details stay in the source record; get() returns them without summarization.
    """
    if isinstance(limit, bool) or not isinstance(limit, int) or not 0 <= limit <= 100:
        raise ValueError("limit must be an integer between 0 and 100")
    if not isinstance(include_history, bool) or not isinstance(query, str):
        raise ValueError("include_history must be boolean and query must be a string")
    task_id, _ = _task(cg, task)
    facts, experiences = [], []
    for nid, entry in list(cg.index.get("nodes", {}).items()):
        tags = set(entry.get("tags") or [])
        if f"task:{task_id}" not in tags:
            continue
        if not tags.intersection((FACT_TAG, EXPERIENCE_TAG)):
            continue
        rec = cg.get(nid)
        if not rec or not security.visible_to(cg, rec["frontmatter"]):
            continue
        data = _memory(rec)
        if data.get("task_id") != task_id:
            continue
        item = {"id": nid, "data": data, "fm": rec["frontmatter"], "rec": rec}
        if data.get("kind") == "fact":
            facts.append(item)
        elif data.get("kind") == "experience":
            experiences.append(item)
    superseded = {item["data"]["fact"].get("supersedes") for item in facts}
    terms = {term.casefold() for term in expand_query_terms(query)} if query.strip() else set()
    buckets = {"facts": [], "experiences": []}
    for kind, items in (("facts", facts), ("experiences", experiences)):
        for item in items:
            data, fm, nid = item["data"], item["fm"], item["id"]
            if kind == "facts":
                if not include_history and nid in superseded:
                    continue
                value = dict(data["fact"])
                details = value.pop("details", "")
                search_text = " ".join([value["statement"], value["subject"], *value["files"]])
                value.update(details_ref=nid, detail_chars=len(details),
                             record_id=data["record_id"], experience_ids=data["experience_ids"],
                             superseded=nid in superseded)
            else:
                value = dict(data["experience"])
                search_text = " ".join([value["task"], value["solution"], value["conditions"],
                                        value["boundary"], *value["search_keys"]])
                qualification_rec = item["rec"]
                if crypto.is_encrypted_level(fm.get("sensitivity")):
                    # Reconstruct the native boundary field only after an authorized
                    # decrypt; private phrases must not enter plaintext FM/index.
                    boundary = [re.sub(r"[.．…\s，,；;、]+$", "", part).strip()
                                for part in re.split(r"[；;]", value["boundary"]) if part.strip()]
                    qualification_rec = {**qualification_rec, "frontmatter": {
                        **fm, "non_applicable_conditions": boundary}}
                qualification = cg.judge_qualification(qualification_rec, query or value["conditions"])
                if qualification.get("state") == "REJECT":
                    continue
                value["qualification"] = qualification
                value["source_fact_ids"] = [f["id"] for f in facts
                                            if nid in f["data"].get("experience_ids", [])]
            score = sum(term in search_text.casefold() for term in terms)
            if terms and not score:
                continue
            value.update(id=nid, score=score,
                         verification_state=fm.get("verification_state", "unverified"))
            buckets[kind].append((score, fm.get("created_at") or 0, nid, value))
    result = {"ok": True, "task_id": task_id, "readonly": True}
    for kind, items in buckets.items():
        items.sort(key=lambda row: (-row[0], -float(row[1]), row[2]))
        result[kind] = [row[3] for row in items[:limit]]
        result[f"{kind}_total"] = len(items)
        result[f"{kind}_truncated"] = len(items) > limit
    return result
