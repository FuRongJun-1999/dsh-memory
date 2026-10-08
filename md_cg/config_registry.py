# -*- coding: utf-8 -*-
"""统一配置层 · **registry 真源**（草案 v0.1，第一批：只加机制）。

本模块是「可调参数」的**单一登记真源**——只做登记／查询／校验口径，**不是**
运行时取值源：代码里的读取点一个都不动（第一批只加机制、不动语义）。

三层结构（与 `docs/plans/统一配置层_设计_v0.1.md` §1 的分层表逐条对齐）
--------------------------------------------------------------------
        face      进用户配置文件 `~/.mdcg/config.toml`   进 registry 调参序列
        --------  ------------------------------------  --------------------
        ENV(环境面)      否（部署/隔离必需，改了会换库/换身份）   否（仅登记分类）
        TUNE(调参面)     是（阈值/开关/预算/条数/超时）            是
        CALIB(标定面)    是（默认值来源与状态，`status`/`evidence`）是

体例裁决（设计文档 §4 有完整理由）
--------------------------------
**保留既有分区表，不扩成一张总表**：`md_cg/sleep.py::SLEEP_ENV_KEYS/
SLEEP_ENV_DEFAULTS`、`md_cg/sustain.py::AUTO_DEFAULTS/AUTO_ENVS`、
`md_cg/autonomy_modes.py::AUTONOMY_ENV_KEYS/AUTONOMY_ENV_DEFAULTS` 三张表
**继续是各自动读取点的运行时真源**（它们已被守卫机械钉死，物理合并会连带
改读取出口 = 违反「只加机制」）。本模块只做**上位登记 + 一致性守卫**：
registry 里登记的缺省必须 == 分区表的实际值，否则守卫
`md_cg/config_registry_guard.py` 转红。共用的东西是 **schema / 生成器 /
校验器 / 守卫**，不是表本体。

条目来源（两段，都在本文件可查）
------------------------------
① `CURATED_ENTRIES`（**手维**）：三张既有真源表的 12 个键 + 需人工裁定字段
   （`semantic` 语义、跨副本分叉注记）。
② `config_registry_bulk.py`（**生成件**，冻结快照）：由
   `scripts/gen_config_registry.py` 从盘点件 + 源码 AST 逐位复核生成；
   改默认值请改**源码**，守卫会转红。

不适用条件（第一批）
------------------
· 不改任何读取点、不改任何默认值、不动 `md_cg/security.py` 判据。
· 不写 `~/.mdcg/config.toml`（写入口在第二批；本批只给签名与权限矩阵）。
· 未从 AST 定位到字面量缺省的 env，`value` 留 `None`（**不许把盘点文字当
  已验证值填进 value**）——盘点文字只进 `evidence`。
"""
from __future__ import annotations

import ast
import os

from . import autonomy_modes as _autonomy
from . import config_registry_bulk as _bulk
from . import sleep as _sleep
from . import sustain as _sustain

# ---------------------------------------------------------------------------
# §1 字段规格（schema）
# ---------------------------------------------------------------------------

#: 条目字段 → (是否必填, 说明)。任何字段的增删只在此处，生成器/校验器/守卫
#: 都按本表断言（新增字段必须同时改 `entry_from_row`）。
SCHEMA = {
    "key": (True, "稳定唯一 id：`<仓>::<文件或 env>::<符号>`"),
    "name": (True, "人类可读名（env 名 / 源码符号名）"),
    "face": (True, "ENV | TUNE | CALIB（三面分层，与盘点口径同源）"),
    "layer": (True, "env | tune | calib（face 的小写投影，供查询分组）"),
    "kind": (True, "env | const | table"),
    "tunable": (True, "bool：是否真「数值型可调参数」（枚举名/模板串为 False）"),
    "value": (False, "缺省**快照**；定位不到字面量时为 None（不用盘点文字顶替）"),
    "value_repr": (False, "value 的 repr（生成件里的原样字面量）"),
    "value_type": (True, "int|float|bool|str|tuple|list|dict"),
    "domain": (True, "值域/语义描述；env 面为 default_semantic 的取值"),
    "semantic": (False, "env 面有效缺省语义：on|off|unset|fail-open|value|enum|conflict"),
    "env_name": (False, "env 覆盖键（const 面无）"),
    "anchor": (True, "可指认代码锚 {how,file,symbol,key?}——**不写行号**"),
    "status": (True, "uncalibrated | calibrating | calibrated"),
    "evidence": (True, "依据：读数/文档锚/源码复核口径（不许写「看起来合理」）"),
    "since": (True, "哪个版本起生效；未核为 unknown"),
    "notes": (False, "备注（冲突/分叉标记等）"),
    "repo": (True, "dsh-memory-main（第一批只登记本仓；身体仓/私域仓列名不列条目）"),
}

FACES = ("ENV", "TUNE", "CALIB")
LAYERS = ("env", "tune", "calib")
KINDS = ("env", "const", "table")
STATUSES = ("uncalibrated", "calibrating", "calibrated")

#: §1 分层表（机器可读；设计文档同表）——`user_config` = 是否允许出现在
#: 用户配置文件 `~/.mdcg/config.toml` 里。
LAYER_TABLE = (
    {"face": "ENV", "layer": "env", "user_config": False, "tune_sequence": False,
     "why": "部署/隔离必需（根路径/凭据/身份/密级/解释器/写路径白名单）——"
            "改了会换库或换身份，不是「用户可调参数」，只登记分类"},
    {"face": "TUNE", "layer": "tune", "user_config": True, "tune_sequence": True,
     "why": "阈值/开关/预算/条数/超时——用户该能持久化调"},
    {"face": "CALIB", "layer": "calib", "user_config": True, "tune_sequence": True,
     "why": "默认值本身需实验找较优；进配置文件但必须带 status/evidence/since"},
)

#: 参数类别 → 谁能改（写入口权限矩阵；角色名取自 `md_cg/tokens.py::ROLE_SPECS`）。
#: 本批**只登记矩阵**，闸门实现放第二批；`security` 类另需 `evidence` 非空。
PARAM_CLASSES = {
    "deployment": "环境面（ENV）——不进用户配置文件；改它属部署动作",
    "tuning": "调参面（TUNE）——阈值/开关/预算/条数/超时",
    "calibration": "标定面（CALIB）——默认值需实验依据方可改",
    "security": "写路径白名单/密级/令牌类——仅设计者，且需二次确认",
}

#: 谁可写哪一类（`_narrow` 语义：子权限只能收窄）。任何角色改任何参数都
#: **必过值域校验 + 幂等 + 改前备份**（写入口契约见设计文档 §3）。
ROLE_WRITE_MATRIX = {
    "designer": ("tuning", "calibration", "security"),
    "orchestr": (),
    "record": (),
    "reflect": (),
    "verify": (),
    "guest": (),
}

#: 需二次确认（`--confirm`）的类别——与 `security.py` 的判据无关，只约束
#: **配置写入**这一动作。
CLASSES_REQUIRING_CONFIRM = ("security",)

# ---------------------------------------------------------------------------
# §2 registry 条目——① 手维：三张既有真源表（`kind="table"`）
# ---------------------------------------------------------------------------
# 为什么单列这一段：这三张表是**仓内既有体例**，且被守卫机械钉死
# （`md_cg/test_sleep_p1.py` 等）。registry 把它们登记进来以便「一张表看全 +
# 一致性守卫」，但它们的**运行时真源仍是各自模块里的表**（读取点不动）。

_TABLE_SRC = {
    "sleep": (_sleep, "SLEEP_ENV_DEFAULTS", "SLEEP_ENV_KEYS", "md_cg/sleep.py"),
    "sustain": (_sustain, "AUTO_DEFAULTS", "AUTO_ENVS", "md_cg/sustain.py"),
    "autonomy": (_autonomy, "AUTONOMY_ENV_DEFAULTS", "AUTONOMY_ENV_KEYS",
                 "md_cg/autonomy_modes.py"),
}

#: (表, 表内键, 缺省**快照**, semantic, 备注)
#: env 名**从真源表取**（`<表>::<KEYS 符号>[键]`），**本文件不写第二处 env 名
#: 字面量**——既有守卫 `md_cg/test_sleep_p1.py::g8`、`md_cg/test_auto_defaults.py::G3`、
#: `md_cg/test_autonomy_modes.py::g_g` 把这条钉死（全仓 .py 里带引号的
#: 这些 env 名只许出现在各自唯一入口模块）。
_TABLE_ROWS = (
    ("sleep", "sleep", "1", "on", "总开关（\"1\" = 开）"),
    ("sleep", "interval", "3600", "value", "周期（秒）"),
    ("sleep", "window", "23:00-07:00", "enum",
     "睡眠时段（本地时间；留空 = 全时段，支持跨午夜）"),
    ("sleep", "merge", "auto", "enum", "合并策略 auto/ask/never；越界回落 auto"),
    ("sleep", "gitdir", "", "unset", "空 → state_root()/sleep/lib.git"),
    ("sleep", "shadow", "", "unset", "空 → state_root()/sleep/shadow"),
    ("sleep", "scrub_apply", "0", "off",
     "第④步去污染**实改**闸（缺省关：只盘点不落盘）"),
    ("sustain", "auto_heal", True, "on", "自愈档"),
    ("sustain", "auto_scrub", False, "off", "自净档"),
    ("sustain", "auto_evolve", False, "off", "演化档"),
    ("sustain", "auto_tidy", True, "on",
     "整理档；P0-2 裁决值 = 开（对外可见的缺省变更）"),
    ("autonomy", "mode", "confirm", "enum",
     "自治档 plan/confirm/full；缺省 = 变更确认（设计 §〇.2 裁定①）"),
)


def _table_entries():
    out = []
    for tbl, key, val, sem, note in _TABLE_ROWS:
        mod, sym, keysym, f = _TABLE_SRC[tbl]
        env_name = getattr(mod, keysym)[key]        # ← 真源取，不写字面量
        out.append({
            "key": f"dsh-memory-main::{f}::{sym}[{key!r}]",
            "name": env_name,
            "face": "CALIB",
            "layer": "calib",
            "kind": "table",
            "tunable": sem != "enum",
            "value": val,
            "value_repr": repr(val),
            "value_type": type(val).__name__,
            "domain": sem,
            "semantic": sem,
            "env_name": env_name,
            "anchor": {"how": "table_entry", "file": f, "symbol": sym,
                       "key": key, "env_keys_symbol": keysym},
            "status": "uncalibrated",
            "evidence": "既有单一真源表（仓内体例：注记「改缺省只改这里」，"
                        "由守卫机械钉死）——第一批未见标定读数",
            "since": "unknown",
            "notes": note,
            "repo": "dsh-memory-main",
        })
    return tuple(out)


# 手维条目 = 三张既有真源表的键（上层可追加；追加须给齐 SCHEMA 必填字段）
CURATED_ENTRIES = _table_entries()

# ---------------------------------------------------------------------------
# §3 汇总与查询
# ---------------------------------------------------------------------------

_ENTRY_CACHE = None


def entry_from_row(row, fields=None):
    """生成件的元组行 → 条目 dict（字段序 = `config_registry_bulk.ROW_FIELDS`）。"""
    fields = fields or _bulk.ROW_FIELDS
    d = dict(zip(fields, row))
    val = None
    if d.get("value_repr") not in (None, "None"):
        try:
            val = ast.literal_eval(d["value_repr"])
        except Exception:
            val = d["value_repr"]
    files = None
    if d.get("kind") == "env" and d.get("anchor_file"):
        files = [f for f in d["anchor_file"].split(";") if f]
    anchor = {"how": d.get("anchor_how") or "unknown",
              "file": (files[0] if files else (d.get("anchor_file") or "")),
              "files": files,
              "symbol": d.get("anchor_symbol") or None, "key": None}
    return {
        "key": (f"dsh-memory-main::{d['anchor_file']}::{d['anchor_symbol']}"
                if d.get("kind") == "const"
                else f"dsh-memory-main::env::{d['name']}"),
        "name": d["name"],
        "face": d["face"],
        "layer": d["layer"],
        "kind": d["kind"],
        "tunable": bool(d["tunable"]),
        "value": val,
        "value_repr": d.get("value_repr"),
        "value_type": d.get("value_type") or "str",
        "domain": d.get("domain") or "",
        "semantic": d.get("semantic") or None,
        "env_name": d.get("env_name") or None,
        "anchor": anchor,
        "status": d.get("status") or "uncalibrated",
        "evidence": d.get("evidence") or "",
        "since": d.get("since") or "unknown",
        "notes": d.get("notes") or "",
        "repo": "dsh-memory-main",
    }


def entries():
    """全部条目（手维 + 生成件），按 (face, name) 排序；结果缓存。"""
    global _ENTRY_CACHE
    if _ENTRY_CACHE is None:
        bulk = [entry_from_row(r) for r in _bulk.CONST_ROWS]
        bulk += [entry_from_row(r) for r in _bulk.ENV_ROWS]
        _ENTRY_CACHE = list(CURATED_ENTRIES) + bulk
        _ENTRY_CACHE.sort(key=lambda e: (e["face"], e["name"], e["key"]))
    return _ENTRY_CACHE


def by_face(face):
    return [e for e in entries() if e["face"] == face]


def tune_sequence():
    """「调参序列」= TUNE + CALIB 面（环境面只登记分类，不进序列）。"""
    return [e for e in entries() if e["face"] in ("TUNE", "CALIB")]


def env_layer():
    return [e for e in entries() if e["face"] == "ENV"]


def env_catalog():
    """环境面**分类登记**（只登记分类，不对缺省值下判断）。

    与 `env_layer()` 的区别：`env_layer()` 是「已进 registry 条目的环境面项」
    （第一批 8 条，五条真问题相关）；`env_catalog()` 是盘点口径下**全部**环境面
    名字的**分类登记**（90 条，含身体仓 14 条），只为「一张表看全名字」。
    """
    out = []
    for name, kind, repo, domain, notes in _bulk.ENV_CATEGORY_ROWS:
        out.append({"name": name, "kind": kind, "repo": repo,
                    "face": "ENV", "layer": "env", "domain": domain,
                    "notes": notes})
    return out


def get(name_or_key):
    for e in entries():
        if e["name"] == name_or_key or e["key"] == name_or_key:
            return e
    return None


def conflicts():
    """被登记为缺省分叉/跨副本不一致的条目（五条真问题的登记面）。"""
    return [e for e in entries()
            if e.get("semantic") == "conflict" or "分叉" in (e.get("evidence") or "")
            or "分叉" in (e.get("notes") or "")]


def toml_keys():
    """允许进用户配置文件 `~/.mdcg/config.toml` 的键（TUNE/CALIB 面）。"""
    return [e for e in tune_sequence() if e.get("env_name")]


def _counts():
    c = {"total": 0, "by_face": {f: 0 for f in FACES},
         "by_kind": {k: 0 for k in KINDS},
         "tunable": 0, "conflict": 0, "env_category": 0,
         "by_status": {s: 0 for s in STATUSES}}
    for e in entries():
        c["total"] += 1
        c["by_face"][e["face"]] = c["by_face"].get(e["face"], 0) + 1
        c["by_kind"][e["kind"]] = c["by_kind"].get(e["kind"], 0) + 1
        c["by_status"][e["status"]] = c["by_status"].get(e["status"], 0) + 1
        if e["tunable"]:
            c["tunable"] += 1
    c["conflict"] = len(conflicts())
    c["env_category"] = len(_bulk.ENV_CATEGORY_ROWS)
    return c


def catalog():
    """自描述（供文档生成 / 人工核对 / 未来 `cg(op=config)`）。"""
    return {
        "schema_version": "0.1",
        "repo": "dsh-memory-main",
        "layer_table": [dict(r) for r in LAYER_TABLE],
        "param_classes": dict(PARAM_CLASSES),
        "role_write_matrix": {r: list(c) for r, c in ROLE_WRITE_MATRIX.items()},
        "classes_requiring_confirm": list(CLASSES_REQUIRING_CONFIRM),
        "bulk_meta": dict(_bulk.META),
        "counts": _counts(),
        "env_category_count": len(_bulk.ENV_CATEGORY_ROWS),
        "user_config_toml_path": os.path.join("~", ".mdcg", "config.toml"),
        "priority_order": ["显式 CLI/env 覆盖", "用户配置文件",
                           "标定默认（registry）"],
    }
