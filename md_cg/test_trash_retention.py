# -*- coding: utf-8 -*-
"""trash 保留期清扫守卫（R-541，2026-11-10）。

背景：`forget` 把节点正文搬进 `trash/` 并写 `_deletions.jsonl`，正文副本按
「保留 7 天后自动清」（用户 2026-10-31 定；`MDCG_TRASH_KEEP_DAYS` 可调、
负数 = 永不清理）真删，动作写成无载荷 `_purge.jsonl`。但 `trashbin.sweep`
在接入前**全树零调用** ⇒ 策略静默失效、`trash/` 无界增长、已遗忘节点的
正文本永久留在盘上、`_purge.jsonl` 一次也没产生过。

契约（本文件即其守卫）：

  【1】`trashbin.sweep` 三态：超期 ⇒ purged + `_purge.jsonl` 一条（无载荷：
      只有 id/字节数/时间/墓碑哈希，一个正文字节都不写）；未超期 ⇒
      kept_recent 且文件仍在；`keep_days < 0` ⇒ skipped 且零删除。
  【2】`dry_run=True` ⇒ 只报 candidates、不删文件、不写 `_purge.jsonl`。
  【3】**接线**：`SustainLoop._tick_tidy` 真调 sweep —— `auto_tidy=True` 时
      真删（`trash_dry_run=False`）；`auto_tidy=False` 时只盘点
      （`trash_dry_run=True`，文件仍在）。两处读数都记进 `last_tidy`。
  【4】sweep 抛异常只降级为 `trash_ok=False`，不中断 tidy（不拖垮整档）。

运行：python -m md_cg.test_trash_retention
"""
from __future__ import annotations

import io
import json
import os
import shutil
import tempfile
import time

from . import sustain as S
from . import trashbin as T

PASSED = FAILED = 0


def ok(cond, name):
    global PASSED, FAILED
    if cond:
        PASSED += 1
        print("  [PASS] " + name)
    else:
        FAILED += 1
        print("  [FAIL] " + name)


def _mk_root(tmp, age_days, name="gone1", body="正文-A"):
    """造一个含 trash/<id>.md + `_deletions.jsonl` 的库根；age_days 为删除时刻距今。"""
    root = os.path.join(tmp, "lib-%s" % name)
    os.makedirs(os.path.join(root, "trash"), exist_ok=True)
    with io.open(os.path.join(root, "trash", name + ".md"), "w",
                 encoding="utf-8", newline="\n") as f:
        f.write("---\nid: %s\n---\n%s\n" % (name, body))
    rec = {"t": time.time() - age_days * 86400.0, "id": name,
           "hash": "deadbeefdeadbeef", "op": "forget"}
    with io.open(os.path.join(root, T.DELETIONS_LOG), "a",
                 encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return root


def _purge_lines(root):
    p = os.path.join(root, T.PURGE_LOG)
    if not os.path.isfile(p):
        return []
    with io.open(p, encoding="utf-8") as f:
        return [json.loads(x) for x in f.read().splitlines() if x.strip()]


class _FakeCG:
    def __init__(self, root):
        self.root = root


def _tick(root, auto_tidy):
    """起一个真 SustainLoop 跑一次 _tick_tidy；writelimit 那一腿打桩（本测只看 trash 段）。"""
    from . import writelimit
    orig = writelimit.tidy_contextual

    def _stub(cg, apply=True, actor=None):
        return {"t": time.time(), "scanned": 0, "groups": 0, "members": 0,
                "applied_count": 0}

    writelimit.tidy_contextual = _stub
    try:
        loop = S.SustainLoop(_FakeCG(root), name="t_trash", auto_tidy=auto_tidy,
                             auto_sleep=False, auto_scrub=False, auto_evolve=False)
        loop._tick_tidy()
        return dict(loop.last_tidy or {})
    finally:
        writelimit.tidy_contextual = orig


def main():
    tmp = tempfile.mkdtemp(prefix="trashret_")
    try:
        print("[1] sweep 三态")
        old = _mk_root(tmp, age_days=30.0, name="old1")
        rep = T.sweep(old, dry_run=False)
        ok(rep["purged"] == ["old1"], "G1a 超期 ⇒ 进 purged")
        ok(not os.path.exists(os.path.join(old, "trash", "old1.md")),
           "G1b 超期 ⇒ 正文副本已删")
        pl = _purge_lines(old)
        ok(len(pl) == 1 and pl[0]["id"] == "old1", "G1c `_purge.jsonl` 落一条")
        ok(set(pl[0]) == {"t", "id", "bytes", "keep_days", "deleted_at",
                          "tombstone", "reason"}, "G1d 台账无载荷（字段集固定，无正文字段）")
        ok(pl[0]["tombstone"] == "deadbeefdeadbeef", "G1e 墓碑哈希随台账留存")

        young = _mk_root(tmp, age_days=1.0, name="young1")
        rep = T.sweep(young, dry_run=False)
        ok(rep["kept_recent"] == 1 and rep["purged"] == [], "G2a 未超期 ⇒ kept_recent")
        ok(os.path.isfile(os.path.join(young, "trash", "young1.md")), "G2b 未超期 ⇒ 文件仍在")

        never = _mk_root(tmp, age_days=99.0, name="never1")
        rep = T.sweep(never, keep_days=-1, dry_run=False)
        ok(rep["skipped"] and rep["purged"] == [], "G3a keep_days<0 ⇒ skipped")
        ok(os.path.isfile(os.path.join(never, "trash", "never1.md")), "G3b 永不清理 ⇒ 文件仍在")

        print("[2] dry_run 只盘点")
        dry = _mk_root(tmp, age_days=30.0, name="dry1")
        rep = T.sweep(dry, dry_run=True)
        ok(rep["candidates"] == ["dry1"] and rep["purged"] == [], "G4a dry_run ⇒ 只报 candidates")
        ok(os.path.isfile(os.path.join(dry, "trash", "dry1.md")), "G4b dry_run ⇒ 不删")
        ok(_purge_lines(dry) == [], "G4c dry_run ⇒ 不写 `_purge.jsonl`")

        print("[3] 接线：SustainLoop._tick_tidy 真调 sweep")
        w_on = _mk_root(tmp, age_days=30.0, name="wire_on")
        rec = _tick(w_on, auto_tidy=True)
        ok(rec.get("trash_dry_run") is False, "G5a auto_tidy=True ⇒ 非 dry_run")
        ok(rec.get("trash_purged") == 1, "G5b auto_tidy=True ⇒ 真删 1 件（接线成立）")
        ok(not os.path.exists(os.path.join(w_on, "trash", "wire_on.md")), "G5c 文件已删")
        ok(len(_purge_lines(w_on)) == 1, "G5d `_purge.jsonl` 已产生（此前恒空）")

        w_off = _mk_root(tmp, age_days=30.0, name="wire_off")
        rec = _tick(w_off, auto_tidy=False)
        ok(rec.get("trash_dry_run") is True and rec.get("trash_purged") == 0,
           "G6a auto_tidy=False ⇒ 只盘点、purged=0")
        ok(os.path.isfile(os.path.join(w_off, "trash", "wire_off.md")),
           "G6b auto_tidy=False ⇒ 文件仍在")

        print("[4] sweep 异常只降级不中断")
        boom = _mk_root(tmp, age_days=30.0, name="boom1")
        orig = T.sweep
        T.sweep = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
        try:
            rec = _tick(boom, auto_tidy=True)
        finally:
            T.sweep = orig
        ok(rec.get("trash_ok") is False, "G7a sweep 抛异常 ⇒ trash_ok=False")
        ok("t" in rec and "scanned" in rec, "G7b tidy 其余读数照常落账（档未被打断）")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\ntest_trash_retention: %d 通过 / %d 失败" % (PASSED, FAILED))
    return 0 if FAILED == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
