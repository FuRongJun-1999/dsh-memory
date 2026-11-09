# -*- coding: utf-8 -*-
"""work_log —— 流水类内容（episodic）的准入判据

判什么：这条节点是不是**可追溯的流水记录**（网关三元组、日卡、索引切片），
而不是语义结论。流水记录不要求 CCG 六要素（它没有「功能/子功能/执行」这种结构），
但它必须满足两件事：正文非空、且能定位到来源（有来源标记或时间戳）。

为什么单独设一个 kind，而不是复用 work_done：
  work_done 的验收器是 condaccept（V1 条件空间 / V2 证据 / V4 同槽冲突），
  要求四维条件空间；流水卡按定义没有条件空间，塞进 work_done 会 100% 打回。
  而 text 的验收器要求六要素，同样不适用。未知 kind 会被判 BLINDSPOT 且 kind 不落 fm。

导入方向：本模块**不在顶层 import audit**（audit 在文件尾部反过来 import 本模块来
注册验收器，顶层互导会撞 partially initialized module）。_verdict 只在调用时惰性取。
"""
CONTENT_KIND = "work_log"
ACCEPT, REJECT = "ACCEPT", "REJECT"

_SOURCE_HINTS = ("来源", "依据", "出处", "node_id", "session", "http", "gateway",
                 "mn_", "dst_", "idx_", "slf_", "sess_")


def _verdict(state, kind, evidence, detail=None):
    from .audit import _verdict as _v
    return _v(state, kind, evidence, detail)


def verify_payload(payload, ctx=None):
    text = str((payload or {}).get("content") or "")
    if not text.strip():
        return _verdict(REJECT, CONTENT_KIND, "空流水：正文为空")
    low = text.lower()
    marked = any(h.lower() in low for h in _SOURCE_HINTS)
    if not marked:
        return _verdict(REJECT, CONTENT_KIND,
                        "流水缺来源标记：正文里找不到来源/出处/node_id 等可定位信息")
    return _verdict(ACCEPT, CONTENT_KIND,
                    "流水记录：非空且有来源标记（不要求 CCG 六要素，属设计豁免）")
