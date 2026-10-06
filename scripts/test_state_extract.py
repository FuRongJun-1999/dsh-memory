#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_state_extract —— 会话轮状态抽取（保守版）守卫。

契约（`scripts/state_extract.py` 文件头）：只抽**用户轮**、仅两条高精度规则
（地点·所在迁移 / 情感·偏好）、值剥句尾语气词、同值去重、全程带
`[auto] session=… turn=…` 证据与 `actor=state_extract`、缺省开（`MDCG_STATE_EXTRACT=0`
可关）。本次演示的噪声族（"在看"无「住」词形、计划族不做、助手轮不抽）逐条钉住。

隔离：MDCG_* env 全清 + temp root；结束恢复。运行：python -X utf8 -m scripts.test_state_extract
（scripts/test_*.py 自动进 run_tests 全量套件）。
"""
from __future__ import annotations

import importlib.util
import os
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
_saved = {}
_ok = 0
_fail = []


def check(name, cond, detail=""):
    global _ok
    if cond:
        _ok += 1
        print("[ok] " + name)
    else:
        _fail.append(name)
        print("[FAIL] %s  · %s" % (name, str(detail)[:240]))


def _sandbox():
    for k in list(os.environ):
        if k.startswith("MDCG_"):
            _saved[k] = os.environ.pop(k)
    root = tempfile.mkdtemp(prefix="mdcg_sex_")
    os.environ["MDCG_ROOT"] = root
    os.environ["MDCG_STATE_ROOT"] = os.path.join(root, "state")
    # 末段勿用 Windows 保留设备名（aux 会被 datapath 守卫按 issue #57 拒绝）
    os.environ["MDCG_AUX_ROOT"] = os.path.join(root, "aux-root")
    return root


def _restore():
    for k in list(os.environ):
        if k.startswith("MDCG_"):
            os.environ.pop(k, None)
    for k, v in _saved.items():
        os.environ[k] = v


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


root = _sandbox()
try:
    sys.path.insert(0, str(REPO))
    se = _load("state_extract", HERE / "state_extract.py")
    sync = _load("sync_zcode_session", HERE / "sync_zcode_session.py")
    from md_cg.mdcos import MdCGOS
    from md_cg import state_events as _se
    cg = MdCGOS(root)

    # S1 地点迁移 + 值剥尾
    n1 = se.extract_and_record(cg, "s1", 1, "user", "我搬到青岛了，这边海风很舒服")
    evs = _se.read(cg)
    check("S1 地点迁移命中且值剥句尾语气词（青岛，非「青岛了」）",
          n1 == 1 and evs and evs[-1]["slot"] == "地点·所在"
          and evs[-1]["new"] == "青岛", evs)

    # S2/S3 偏好两向
    n2 = se.extract_and_record(cg, "s1", 2, "user", "我最喜欢海边的日落")
    n3 = se.extract_and_record(cg, "s1", 3, "user", "我讨厌潮湿的天气")
    evs = _se.read(cg)
    check("S2 正向偏好命中（值=海边的日落）",
          n2 == 1 and any(e["slot"] == "情感·偏好" and e["new"] == "海边的日落"
                          for e in evs), evs)
    check("S3 负向偏好显式前缀（不喜欢：）",
          n3 == 1 and any(e["new"] == "不喜欢：潮湿的天气" for e in evs), evs)

    # S4 噪声族逐条不命中（防误伤）
    noise = [("user", "我在看代码，晚点再说"),      # 「在」单字不入式
             ("user", "我明天要加个功能"),          # 计划族 v1 不做
             ("user", "我喜欢这个方案，先按它做"),   # ——命中偏好=真偏好（允许）
             ("assistant", "我搬到火星了"),         # 助手轮不抽
             ("user", "我住在这里三年了吧")]        # 「住在这里」会命中——见下断言口径
    checks = []
    for role, text in noise[:4]:
        checks.append((role, text, se.extract_turn(text, role)))
    check("S4a 噪声族：「在看不抽」「计划不抽」「助手轮不抽」三族 0 命中；"
          "「喜欢这个方案」属真偏好（记录无误——白名单命中不算噪声）",
          checks[0][2] == [] and checks[1][2] == [] and checks[3][2] == []
          and len(checks[2][2]) == 1, checks)
    hit5 = se.extract_turn(noise[4][1], noise[4][0])
    check("S4b 边界如实：「住在这里」类会命中（词形=住在+值）——已知边界，"
          "归用户裁决是否收窄", len(hit5) == 1, hit5)

    # S5 去重：同值二次 0；变值 1 且 old=前值
    n_dup = se.extract_and_record(cg, "s1", 4, "user", "我搬到青岛了，果然还是这里好")
    n_move = se.extract_and_record(cg, "s1", 5, "user", "我已经搬到了大理")
    evs = _se.read(cg)
    loc = [e for e in evs if e["slot"] == "地点·所在"]
    check("S5a 同值去重（二次搬家同目的地 0 条）", n_dup == 0, n_dup)
    check("S5b 变值成链条（old=青岛→new=大理）",
          n_move == 1 and len(loc) == 2 and loc[-1]["old"] == "青岛"
          and loc[-1]["new"] == "大理", loc)

    # S6 证据与 actor（可追溯与可甄别）
    last = evs[-1]
    check("S6 证据格式 [auto] session=… turn=… 且 actor=state_extract（可整体甄别/清理）",
          str(last.get("evidence", "")).startswith("[auto] session=s1 turn=5")
          and last.get("actor") == "state_extract", last)

    # S7 开关：缺省开，=0 关
    os.environ.pop("MDCG_STATE_EXTRACT", None)
    d_on = se.enabled()
    os.environ["MDCG_STATE_EXTRACT"] = "0"
    d_off = se.enabled()
    os.environ.pop("MDCG_STATE_EXTRACT", None)
    check("S7 开关缺省开、=0 关（使用者裁定口径）", d_on is True and d_off is False,
          (d_on, d_off))

    # S8 链路接线：sync 单点可装载同一模块；sync 源码内联调用 extract_and_record
    src = (HERE / "sync_zcode_session.py").read_text(encoding="utf-8")
    loaded = sync._load_state_extract()
    check("S8 链路接线（每轮写入链第二步）：sync 单点装载同一件 + 源码内联调用在场",
          Path(loaded.__file__).resolve() == (HERE / "state_extract.py").resolve()
          and "extract_and_record" in src and "_load_state_extract" in src,
          getattr(loaded, "__file__", None))
finally:
    _restore()
    shutil.rmtree(root, ignore_errors=True)

print("=" * 58)
print("test_state_extract: %d 通过 / %d 失败" % (_ok, len(_fail)))
if _fail:
    print("失败项：" + "、".join(_fail))
raise SystemExit(1 if _fail else 0)
