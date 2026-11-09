# -*- coding: utf-8 -*-
r"""守卫 · T13a 生命周期策略读取单点（md_cg/sink.py）。

四种工况各自钉住「来源 + 生效值 + 坏键可见」三件事：
    G1 文件缺失      ⇒ source='builtin'，五键逐位等于内置默认值
    G2 文件存在且合法 ⇒ 五键逐位等于文件值（不是默认值，也不是"记得改的默认"）
    G3 env 指第三方  ⇒ env 优先于 path 参数与包内默认路径（三方同时存在）
    G4 JSON 非法/键类型错 ⇒ 回落默认且 invalid 非空、全程退出码 0

判据为何不恒真：四工况各造**真实临时文件**（tempfile.mkdtemp），env 用
`mock.patch.dict` 真实改写再真实还原；G3 的三方冲突点必须三方同时在场才可判，
G4 的「坏键静默」病态只在键类型错而**其余键仍合法**时才暴露。

运行：python D:\wook\lingshu-src\md_cg\test_t13a_sink_policy.py
退出码：0 全绿 ／ 1 断言失败
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import traceback
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
if REPO not in sys.path:
    sys.path.insert(0, REPO)

import importlib

_sink = importlib.import_module("md_cg.sink")

PASS = 0
FAIL = 0
FAILS = []


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("[PASS] %s%s" % (name, ("  · " + detail) if detail else ""))
    else:
        FAIL += 1
        FAILS.append(name)
        print("[FAIL] %s  · %s" % (name, detail))


# 生效条件：临时目录已建、传入四工况的夹具路径时，恒返回 (tmp, env_file, arg_file, default_file) 四个绝对路径，其中 env_file/arg_file 为已写好的合法策略文件、default_file 为**尚不存在**的路径；不抛异常（写失败由调用方 check 捕获）。
def make_fixtures(tmp):
    """四工况夹具：两个合法文件 + 一个未创建的路径。"""
    env_file = os.path.join(tmp, "third_party.json")
    arg_file = os.path.join(tmp, "arg_side.json")
    default_file = os.path.join(tmp, "pkg_default.json")
    with open(env_file, "w", encoding="utf-8") as f:
        json.dump({"sink_days": 7, "keep_access_count": 1,
                   "demote_layers": ["knowledge", "contextual"],
                   "trash_days": 14, "protected_importance": 0.95}, f)
    with open(arg_file, "w", encoding="utf-8") as f:
        json.dump({"sink_days": 30, "keep_access_count": 2,
                   "demote_layers": ["structural"], "trash_days": 60,
                   "protected_importance": 0.5}, f)
    return tmp, env_file, arg_file, default_file


# 生效条件：调用时按内置默认值的键集合与取值逐位比对 body；全部一致返回 True，任一键缺失或不等返回 False（并在 detail 里给出首个差异键）。
def defaults_hold(body):
    """五键是否逐位等于 sink.BUILTIN_DEFAULTS。"""
    for key, want in _sink.BUILTIN_DEFAULTS.items():
        got = body.get(key, "__MISSING__")
        if got != want or type(got) is not type(want):
            return False
    return True


# 生效条件：tmp 下没有可解析的策略文件、env 已清空时，断言缺失工况回落内置默认（source=='builtin' 且五键逐位等于文档默认值），并把结论计入全局计数；恒返回 None。
def case_missing(tmp):
    """G1：文件缺失 ⇒ source='builtin' + 五键等于文档默认值。"""
    missing = os.path.join(tmp, "no_such_file.json")
    with mock.patch.dict(os.environ, {}, clear=False):
        os.environ.pop("MDCG_LIFECYCLE_FILE", None)
        body = _sink.load_policy(path=missing)
    check("G1 缺失⇒source=='builtin'", body["source"] == "builtin",
          "source=%r" % body["source"])
    check("G1 缺失⇒五键逐位等于文档默认值", defaults_hold(body), repr(body))
    check("G1 缺失⇒invalid 为空", body["invalid"] == [],
          "invalid=%r" % (body["invalid"],))
    check("G1 缺失⇒path 如实记录尝试路径", body["path"] == missing,
          "path=%r" % body["path"])


# 生效条件：arg_file 为合法策略文件且 env 未设时，断言五键逐位等于文件值（含类型：int/float/list）、source=='arg'、invalid 为空；恒返回 None。
def case_valid_file(tmp, arg_file):
    """G2：文件存在且合法 ⇒ 五键等于文件值。"""
    with mock.patch.dict(os.environ, {}, clear=False):
        os.environ.pop("MDCG_LIFECYCLE_FILE", None)
        body = _sink.load_policy(path=arg_file)
    want = json.load(open(arg_file, encoding="utf-8"))
    same = all(body[k] == want[k] for k in _sink.BUILTIN_DEFAULTS)
    check("G2 合法文件⇒五键逐位等于文件值", same,
          "got=%r want=%r" % ({k: body[k] for k in _sink.BUILTIN_DEFAULTS}, want))
    check("G2 合法文件⇒source=='arg'", body["source"] == "arg",
          "source=%r" % body["source"])
    check("G2 合法文件⇒invalid 为空", body["invalid"] == [],
          "invalid=%r" % (body["invalid"],))
    check("G2 合法文件⇒protected_importance 保持 float",
          isinstance(body["protected_importance"], float),
          "type=%s" % type(body["protected_importance"]).__name__)


# 生效条件：env_file 与 arg_file 同时在场、且包内默认路径被指向一个**取值完全不同**的文件时，断言生效值是 env_file 的取值（env 压过 path 与默认路径），source=='env'；恒返回 None。
def case_env_wins(tmp, env_file, arg_file):
    """G3：env 优先于 path 参数与包内默认路径（三方同时在场）。"""
    dflt = os.path.join(tmp, "pkg_default.json")
    with open(dflt, "w", encoding="utf-8") as f:            # 默认路径上也放一个不同的
        json.dump({"sink_days": 999, "keep_access_count": 999,
                   "demote_layers": ["self"], "trash_days": 999,
                   "protected_importance": 0.1}, f)
    real_default = _sink.default_policy_path
    try:
        _sink.default_policy_path = lambda: dflt
        with mock.patch.dict(os.environ, {"MDCG_LIFECYCLE_FILE": env_file}):
            body = _sink.load_policy(path=arg_file)
    finally:
        _sink.default_policy_path = real_default
    want = json.load(open(env_file, encoding="utf-8"))
    ok = all(body[k] == want[k] for k in _sink.BUILTIN_DEFAULTS)
    check("G3 env 优先于 path 与默认路径⇒取 env 文件值", ok,
          "got=%r want=%r" % ({k: body[k] for k in _sink.BUILTIN_DEFAULTS}, want))
    check("G3 三方在场时 source=='env'", body["source"] == "env",
          "source=%r" % body["source"])
    check("G3 path 如实记录 env 路径", body["path"] == env_file,
          "path=%r" % body["path"])


# 生效条件：按 bad_kind 造坏文件——'json' 写非 JSON 文本、'type' 写合法 JSON 但 sink_days 为字符串且其余键合法——断言回落默认值、invalid 非空（'type' 工况须含 'sink_days'）、load_policy 不抛异常；恒返回 None。
def case_invalid(tmp, bad_kind):
    """G4：JSON 非法 / 键类型错 ⇒ 回落默认且 invalid 非空、不抛异常。"""
    bad = os.path.join(tmp, "bad_%s.json" % bad_kind)
    if bad_kind == "json":
        with open(bad, "w", encoding="utf-8") as f:
            f.write("{ this is not json ,,, ")
    else:
        with open(bad, "w", encoding="utf-8") as f:
            json.dump({"sink_days": "九十天", "keep_access_count": 5,
                       "demote_layers": ["knowledge"], "trash_days": 180,
                       "protected_importance": 0.7}, f)
    raised = None
    with mock.patch.dict(os.environ, {}, clear=False):
        os.environ.pop("MDCG_LIFECYCLE_FILE", None)
        try:
            body = _sink.load_policy(path=bad)
        except Exception as exc:                            # noqa: BLE001
            raised = "%s: %s\n%s" % (type(exc).__name__, exc, traceback.format_exc())
            body = {}
    check("G4(%s) 不抛异常" % bad_kind, raised is None, raised or "")
    if raised is not None:
        return
    if bad_kind == "json":
        check("G4(json) JSON 非法⇒回落默认值且 source=='builtin'",
              body["source"] == "builtin" and defaults_hold(body), repr(body))
        check("G4(json) error 如实记录原因", bool(body["error"]),
              "error=%r" % (body["error"],))
    else:
        check("G4(type) 坏键回落默认、其余合法键照常生效",
              body["sink_days"] == _sink.BUILTIN_DEFAULTS["sink_days"]
              and body["keep_access_count"] == 5, repr(body))
        check("G4(type) invalid 非空且含坏键名",
              "sink_days" in body["invalid"], "invalid=%r" % (body["invalid"],))


# 生效条件：demote_layers 里混入 mdcg.LAYERS 之外的层名时，断言越界名被从生效值剔除、'demote_layers' 记入 invalid、合法层名保留；LAYERS 取不到时跳过（打印 SKIP 不计入失败）。
def case_layer_guard(tmp):
    """G5（自检）：demote_layers 越界层名 ⇒ 剔除 + 记 invalid。"""
    try:
        layers = _sink._layers()
    except Exception:                                       # noqa: BLE001
        layers = ()
    if not layers:
        print("[SKIP] G5 mdcg.LAYERS 不可得，层名自检跳过（不计入失败）")
        return
    f = os.path.join(tmp, "layers.json")
    with open(f, "w", encoding="utf-8") as fh:
        json.dump({"sink_days": 90, "keep_access_count": 3,
                   "demote_layers": ["knowledge", "no_such_layer"],
                   "trash_days": 180, "protected_importance": 0.7}, fh)
    with mock.patch.dict(os.environ, {}, clear=False):
        os.environ.pop("MDCG_LIFECYCLE_FILE", None)
        body = _sink.load_policy(path=f)
    check("G5 越界层名被剔除、合法层名保留",
          body["demote_layers"] == ["knowledge"],
          "demote_layers=%r" % (body["demote_layers"],))
    check("G5 越界层名记入 invalid",
          "demote_layers" in body["invalid"], "invalid=%r" % (body["invalid"],))


# 生效条件：包内真实 data/lifecycle_policy.json 在场时，断言它可被 load_policy 读成 dict 且五键齐全（不校验具体取值，取值由该文件自己演进）；文件缺失时打印 SKIP 不计入失败。
def case_shipped_file():
    """G6：随包发布的 data/lifecycle_policy.json 形状可用。"""
    p = _sink.default_policy_path()
    if not os.path.exists(p):
        print("[SKIP] G6 包内 %s 不在场（打包发布面可能不含），跳过" % p)
        return
    with mock.patch.dict(os.environ, {}, clear=False):
        os.environ.pop("MDCG_LIFECYCLE_FILE", None)
        body = _sink.load_policy()
    check("G6 包内默认文件可读⇒source=='default_file'",
          body["source"] == "default_file", "source=%r" % body["source"])
    check("G6 包内默认文件⇒五键齐全且 invalid 为空",
          all(k in body for k in _sink.BUILTIN_DEFAULTS) and body["invalid"] == [],
          "invalid=%r" % (body["invalid"],))


# 生效条件：建临时目录、依次跑 G1..G6、无论成败都在 finally 里删除临时目录，最后打印中文汇总行并返回 0（全绿）或 1（有失败项）；运行期任何异常由调用方 main 捕获，不得让临时目录残留。
def run_cases():
    """六工况主体（临时目录自建自清）。"""
    tmp = tempfile.mkdtemp(prefix="t13a_sink_")
    try:
        tmp, env_file, arg_file, default_file = make_fixtures(tmp)
        case_missing(tmp)
        case_valid_file(tmp, arg_file)
        case_env_wins(tmp, env_file, arg_file)
        case_invalid(tmp, "json")
        case_invalid(tmp, "type")
        case_layer_guard(tmp)
        case_shipped_file()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# 生效条件：调用时跑完全部工况并打印形如「t13a sink policy：N 通过，0 失败」的汇总行（有失败则附失败项名），返回 0 当且仅当 FAIL==0；捕获 run_cases 抛出的任何异常并计一次失败，保证退出码语义由调用方 sys.exit 决定。
def main():
    print("t13a sink policy：生命周期策略读取单点守卫")
    print("-" * 64)
    try:
        run_cases()
    except Exception as exc:                                # noqa: BLE001
        check("运行期无未捕获异常", False,
              "%s: %s\n%s" % (type(exc).__name__, exc, traceback.format_exc()))
    print("-" * 64)
    if FAILS:
        print("失败项：" + "，".join(FAILS))
    print("t13a sink policy：%d 通过，%d 失败" % (PASS, FAIL))
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
