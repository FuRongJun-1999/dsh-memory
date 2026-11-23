# -*- coding: utf-8 -*-
"""安全与回归守卫（Refs #1009, #1010）：SEC-01 / SEC-02 / SEC-03 / BUG-12 / BUG-13。

# 功能名：test_issue1009_1010_fixes —— 热层密级与可见性 / 心跳外钩加固 / 私密域缓存与布尔解析 / 时间意图正则 / 测试跑道默认写闸
# 生效条件：改动 hottier.py / sustain.py / mcp_server.py / run_tests.py 后
# 子功能：
#   ① SEC-01：热层 build 跳过加密、restricted 及未知密级节点（不落明文），search/browse/relation 强制可见性与私密域隔离、带过滤绕过热层
#   ② SEC-02：_tick_hook.json 配置优先（<root> 内常规 .py 免设 MDCG_TICK_HOOK 放行；目录外含兄弟目录前缀需 MDCG_TICK_HOOK 目录/文件授权）；拒 -c 标志注入/穿越/非常规/非 .py；所有拒绝与执行失败均记入 last_tick_hook_error（绝不静默）；子进程剥离密钥 env
#   ③ SEC-03：include_private="false" 不放行 域:私密；mdcg_search 热缓存二次命中不泄 域:私密；cg(op=route) 与理论快速通道同样剔除 域:私密
#   ④ BUG-12：_time_intent_boost 正确匹配 2026-11-17 / 2026年11月 等真实日期
#   ⑤ BUG-13：md_cg/run_tests.py::_test_env() 缺省注入 MDCG_WRITE_GATE=warn 且尊重显式设置
# 执行：python -X utf8 -m md_cg.test_issue1009_1010_fixes
# 验证方式：全程隔离临时目录，正反对照均绿退出 0，任一失败退出 1
# 不适用条件：不触碰宿主 ~/.dsh 或 ~/.mdcg
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from . import hottier, mcp_server as M, run_tests as RT, sustain
from .mdcos import MdCGSecure
from .security import Principal

_PASS = 0
_FAIL = []


def _chk(cond: bool, label: str, detail="") -> None:
    global _PASS
    if cond:
        _PASS += 1
        print("  PASS " + label)
    else:
        _FAIL.append(label)
        print("  FAIL " + label + ("  · " + str(detail)[:220] if detail else ""))


def _test_sec01_hottier(tmp: str) -> None:
    print("\n== [SEC-01] 热层加密明文泄露与未授权 guest 绕过守卫 ==")
    root = os.path.join(tmp, "sec01_root")
    owner = Principal(tenant="default", actor="owner", role="designer",
                      clearance="secret", can_write=True, can_admin=True,
                      session="sess_owner")
    guest = Principal(tenant="default", actor="guest", role="guest",
                      clearance="internal", can_write=False, can_admin=False,
                      session="sess_guest")
    cg_owner = MdCGSecure(root, principal=owner)
    cg_guest = None
    try:
        cg_owner.add("sec_node_1", "TOPSECRET_CANARY_9981 SECOND_TOKEN_4422 机密正文",
                     layer="self", sensitivity="secret", importance=0.95)
        cg_owner.add("priv_node_1", "PRIVATE_CANARY_7731 SECOND_PRIV_2211 隐私正文",
                     layer="self", sensitivity="private", importance=0.9)
        cg_owner.add("rest_node_1", "RESTRICTED_CANARY_6611 SECOND_REST_3311 受限正文",
                     layer="self", sensitivity="restricted", importance=0.9)
        cg_owner.add("unk_sens_1", "UNKNOWN_SENS_CANARY_3311 未知密级正文",
                     layer="self", sensitivity="internal", importance=0.9)
        cg_owner.add("priv_dom_1", "PRIVDOMAIN_CANARY_5511 SECOND_DOM_4411 私密域正文",
                     layer="self", sensitivity="internal", importance=0.9,
                     tags=[M.PRIVATE_DOMAIN_TAG])
        cg_owner.add("pub_node_1", "PUBLIC_HOT_CANARY_1111 SECOND_PUB_2222 公开热层",
                     layer="self", sensitivity="internal", importance=0.9)
        cg_owner.flush()
        # 模拟索引里出现未知密级字符串：fail-closed 跳过
        cg_owner.index["nodes"]["unk_sens_1"]["sensitivity"] = "topsecret_unknown_tier"

        # 确认盘上确实是密文而非明文
        sec_path = os.path.join(root, cg_owner.index["nodes"]["sec_node_1"]["path"])
        raw_sec = open(sec_path, encoding="utf-8").read()
        _chk("TOPSECRET_CANARY_9981" not in raw_sec, "SEC-01a 原节点文件已加密（无明文）")

        meta = hottier.build(cg_owner)
        hot_dir = os.path.join(root, hottier.HOT_DIR)
        nodes_txt = open(os.path.join(hot_dir, hottier.NODES_FILE), encoding="utf-8").read()
        postings_txt = open(os.path.join(hot_dir, hottier.POSTINGS_FILE), encoding="utf-8").read()
        leftover_tmps = [f for f in os.listdir(hot_dir) if ".tmp" in f]

        _chk("TOPSECRET_CANARY_9981" not in nodes_txt and "TOPSECRET_CANARY_9981" not in postings_txt,
             "SEC-01b secret 明文不落 _hot/hot_nodes.json 或 hot_postings.json")
        _chk("PRIVATE_CANARY_7731" not in nodes_txt
             and "RESTRICTED_CANARY_6611" not in nodes_txt
             and "UNKNOWN_SENS_CANARY_3311" not in nodes_txt,
             "SEC-01c private / restricted / 未知密级明文均 fail-closed 不落 _hot/")
        _chk(meta.get("skipped_sensitive", 0) >= 4 and meta.get("skipped_layer", -1) >= 0,
             "SEC-01d meta 如实计数 skipped_sensitive 且 skipped_layer 非负", meta)
        _chk("pub_node_1" in json.loads(nodes_txt), "SEC-01e 公开/内部节点正常进入热层")
        _chk(not leftover_tmps, "SEC-01f 原子写无残留 .tmp 文件", leftover_tmps)

        # 纵深防御：即使盘上残留旧版未清理的 _hot/ 条目（含 secret 明文），guest 也绝不可读
        cg_guest = MdCGSecure(root, principal=guest)
        _chk("sec_node_1" in cg_guest.index["nodes"] and "pub_node_1" in cg_guest.index["nodes"],
             "SEC-01pre guest 已加载完整索引（真正触发 node_visible 密级校验）")
        poisoned_nodes = json.loads(nodes_txt)
        poisoned_nodes["sec_node_1"] = {
            "id": "sec_node_1", "layer": "self", "importance": 0.99, "t": time.time(),
            "session": "sess_owner", "preview": "TOPSECRET_CANARY_9981 SECOND_TOKEN_4422",
            "content_hash": "",
        }
        poisoned_postings = json.loads(postings_txt)
        for tok in hottier.tokens("TOPSECRET_CANARY_9981 SECOND_TOKEN_4422"):
            poisoned_postings.setdefault(tok, []).append("sec_node_1")
        hottier._write_json(os.path.join(hot_dir, hottier.NODES_FILE), poisoned_nodes)
        hottier._write_json(os.path.join(hot_dir, hottier.POSTINGS_FILE), poisoned_postings)

        old_inc = os.environ.pop("MDCG_INCLUDE_PRIVATE", None)
        try:
            hs = hottier.search(cg_guest, "TOPSECRET_CANARY_9981 SECOND_TOKEN_4422", k=5)
            _chk(not [i for i in hs.get("items", []) if i.get("id") == "sec_node_1"],
                 "SEC-01g hottier.search 拦截 guest 读取投毒/旧版 secret 条目", hs)

            r_match = M.call_tool(cg_guest, "cg", {
                "op": "read", "query": "TOPSECRET_CANARY_9981 SECOND_TOKEN_4422", "k": 5})
            _chk("TOPSECRET_CANARY_9981" not in json.dumps(r_match, ensure_ascii=False),
                 "SEC-01h cg(op=read) match 模式不向 guest 泄露 secret", r_match)

            r_browse = M.call_tool(cg_guest, "cg", {
                "op": "read", "query": "nonexistent_xyz_999", "scope": "hot", "k": 10})
            b_ids = [i.get("id") for i in (r_browse.get("items") or [])]
            _chk("sec_node_1" not in b_ids and "priv_dom_1" not in b_ids and "pub_node_1" in b_ids,
                 "SEC-01i scope=hot 浏览模式屏蔽 secret 与 域:私密、保留公开节点", b_ids)

            r_pdom = M.call_tool(cg_guest, "cg", {
                "op": "read", "query": "PRIVDOMAIN_CANARY_5511 SECOND_DOM_4411", "k": 5})
            _chk("PRIVDOMAIN_CANARY_5511" not in json.dumps(r_pdom, ensure_ascii=False),
                 "SEC-01j 热层 match 模式不泄露 域:私密 节点", r_pdom)

            r_rel = M.call_tool(cg_guest, "stg", {
                "op": "relation", "scope": "hot", "a": "sec_node_1", "b": "pub_node_1"})
            _chk("TOPSECRET_CANARY_9981" not in json.dumps(r_rel, ensure_ascii=False),
                 "SEC-01k stg(op=relation, scope=hot) 不向 guest 泄露 secret 预览", r_rel)

            # 带 layer 过滤时绕过热层优先（不把 self 层 pub_node_1 误当作 knowledge 返回）
            r_layer = M.call_tool(cg_guest, "cg", {
                "op": "read", "query": "PUBLIC_HOT_CANARY_1111 SECOND_PUB_2222",
                "layer": "knowledge", "k": 5})
            _chk(r_layer.get("source") != "hot"
                 and not any((x.get("node") or x).get("id") == "pub_node_1"
                             for x in (r_layer.get("results") or r_layer.get("items") or [])),
                 "SEC-01l 带 layer 过滤时绕过热层优先", r_layer)

            # 带 include_tags 过滤时同样绕过热层优先
            r_tags = M.call_tool(cg_guest, "cg", {
                "op": "read", "query": "PUBLIC_HOT_CANARY_1111 SECOND_PUB_2222",
                "include_tags": ["nonexistent_tag_xyz"], "k": 5})
            _chk(r_tags.get("source") != "hot"
                 and not any((x.get("node") or x).get("id") == "pub_node_1"
                             for x in (r_tags.get("results") or r_tags.get("items") or [])),
                 "SEC-01m 带 include_tags 过滤时绕过热层优先", r_tags)
        finally:
            if old_inc is not None:
                os.environ["MDCG_INCLUDE_PRIVATE"] = old_inc
    finally:
        cg_owner.close()
        if cg_guest is not None:
            cg_guest.close()


def _test_sec02_sustain_tick_hook(tmp: str) -> None:
    print("\n== [SEC-02] sustain 心跳外钩加固守卫 ==")
    root = os.path.join(tmp, "sec02_root")
    cg = MdCGSecure(root)
    lp = sustain.SustainLoop(cg, name="sec02_test")

    hook_dir = os.path.join(tmp, "hooks")
    os.makedirs(hook_dir, exist_ok=True)
    sibling_dir = root + "_evil"
    os.makedirs(sibling_dir, exist_ok=True)
    sibling_py = os.path.join(sibling_dir, "sib.py")
    with open(sibling_py, "w", encoding="utf-8") as f:
        f.write("print('sibling')\n")

    evil_marker = os.path.join(tmp, "evil_ran.txt")
    evil_py = os.path.join(hook_dir, "evil.py")
    with open(evil_py, "w", encoding="utf-8") as f:
        f.write("import pathlib; pathlib.Path(%r).write_text('EVIL', encoding='utf-8')\n" % evil_marker)

    good_out = os.path.join(tmp, "good_env.json")
    good_py = os.path.join(hook_dir, "good.py")
    with open(good_py, "w", encoding="utf-8") as f:
        f.write(
            "import json, os, sys\n"
            "with open(%r, 'w', encoding='utf-8') as fh:\n"
            "    json.dump({'argv': sys.argv[1:], 'env_keys': sorted(os.environ.keys())}, fh)\n"
            % good_out
        )
    root_hook_out = os.path.join(tmp, "root_hook_env.json")
    root_hook_py = os.path.join(root, "local_hook.py")
    with open(root_hook_py, "w", encoding="utf-8") as f:
        f.write(
            "import json, os, sys\n"
            "with open(%r, 'w', encoding='utf-8') as fh:\n"
            "    json.dump({'argv': sys.argv[1:], 'env_keys': sorted(os.environ.keys())}, fh)\n"
            % root_hook_out
        )
    fail_hook_py = os.path.join(root, "fail_hook.py")
    with open(fail_hook_py, "w", encoding="utf-8") as f:
        f.write("import sys\nsys.stderr.write('hook boom\\n')\nsys.exit(2)\n")
    dir_as_py = os.path.join(root, "dir_hook.py")
    os.makedirs(dir_as_py, exist_ok=True)
    non_py = os.path.join(hook_dir, "not_script.txt")
    with open(non_py, "w", encoding="utf-8") as f:
        f.write("print('nope')\n")

    saved = {k: os.environ.get(k) for k in (
        "MDCG_TICK_HOOK", "MDCG_MASTER_KEY", "MDCG_TOKEN", "MDCG_ADMIN_TOKEN")}
    try:
        cfg_path = os.path.join(root, "_tick_hook.json")
        os.environ["MDCG_MASTER_KEY"] = "f" * 64
        os.environ["MDCG_TOKEN"] = "tok_should_not_leak"
        os.environ["MDCG_ADMIN_TOKEN"] = "adm_should_not_leak"

        # 0. 无 MDCG_TICK_HOOK 时，<root> 内的合法常规 .py 经 _tick_hook.json 放行执行，且剥离密钥 env
        os.environ.pop("MDCG_TICK_HOOK", None)
        with open(cfg_path, "w", encoding="utf-8") as f:
            json.dump({"path": root_hook_py, "enabled": True}, f)
        lp._hook_cfg_cache = None
        lp.last_tick_hook_error = None
        _chk(bool(lp._tick_hook_path()), "SEC-02a0 无 MDCG_TICK_HOOK 时允许 <cg.root> 内合法 .py 配置外钩")
        lp._run_tick_hook("beat")
        _chk(os.path.exists(root_hook_out), "SEC-02a1 <cg.root> 内配置外钩无需 env 正常执行")
        if os.path.exists(root_hook_out):
            rrec = json.load(open(root_hook_out, encoding="utf-8"))
            rkeys_u = {k.upper() for k in rrec.get("env_keys", [])}
            _chk(rrec.get("argv") == ["--tick", "beat"],
                 "SEC-02a2 <cg.root> 内配置外钩参数 --tick beat 正确", rrec.get("argv"))
            _chk(not (rkeys_u & {"MDCG_MASTER_KEY", "MDCG_TOKEN", "MDCG_ADMIN_TOKEN"}),
                 "SEC-02a3 <cg.root> 内配置外钩子进程剥离 MDCG_MASTER_KEY / TOKEN / ADMIN_TOKEN",
                 sorted(rkeys_u & {"MDCG_MASTER_KEY", "MDCG_TOKEN", "MDCG_ADMIN_TOKEN"}))
        _chk(lp.last_tick_hook_error is None,
             "SEC-02a4 合法配置外钩成功执行后不误写 last_tick_hook_error", lp.last_tick_hook_error)

        # 1. 无 MDCG_TICK_HOOK 时，_tick_hook.json 指向 <root> 外的 .py（含兄弟前缀 <root>_evil）必须被拒绝且非静默
        os.environ.pop("MDCG_TICK_HOOK", None)
        with open(cfg_path, "w", encoding="utf-8") as f:
            json.dump({"path": evil_py, "enabled": True}, f)
        lp._hook_cfg_cache = None
        lp.last_tick_hook_error = None
        _chk(lp._tick_hook_path() == "", "SEC-02a 未设 MDCG_TICK_HOOK 时拒绝指向 <cg.root> 外的 _tick_hook.json")
        lp._run_tick_hook("beat")
        _chk(not os.path.exists(evil_marker), "SEC-02b 投毒 _tick_hook.json 未被执行")
        err_out = lp.last_tick_hook_error
        _chk(isinstance(err_out, dict)
             and err_out.get("reason") == "outside_allowed_roots"
             and evil_py in str(err_out.get("error") or "")
             and lp.status().get("last_tick_hook_error") == err_out,
             "SEC-02b2 目录外拒绝非静默：记录类名/原因/路径到 last_tick_hook_error 并透出 status()",
             err_out)

        with open(cfg_path, "w", encoding="utf-8") as f:
            json.dump({"path": sibling_py, "enabled": True}, f)
        lp._hook_cfg_cache = None
        lp.last_tick_hook_error = None
        _chk(lp._tick_hook_path() == ""
             and (lp.last_tick_hook_error or {}).get("reason") == "outside_allowed_roots",
             "SEC-02b3 拒绝兄弟目录前缀碰撞（<root>_evil）并记入 last_tick_hook_error",
             lp.last_tick_hook_error)

        # 2. 内联 -c 标志注入必须被拒绝且记入 last_tick_hook_error（配置与 env 两条路均测）
        inline_payload = "-cimport pathlib;pathlib.Path(%r).write_text('C_INJECT')#" % evil_marker
        with open(cfg_path, "w", encoding="utf-8") as f:
            json.dump({"path": inline_payload, "enabled": True}, f)
        lp._hook_cfg_cache = None
        lp.last_tick_hook_error = None
        _chk(lp._tick_hook_path() == "", "SEC-02c 拒绝配置内 -c 内联标志注入")
        lp._run_tick_hook("beat")
        _chk(not os.path.exists(evil_marker), "SEC-02d -c 注入未产生任何执行")
        _chk(isinstance(lp.last_tick_hook_error, dict)
             and lp.last_tick_hook_error.get("reason") == "flag_injection"
             and "-c" in str(lp.last_tick_hook_error.get("error") or ""),
             "SEC-02d2 -c 注入拒绝非静默：记入 last_tick_hook_error", lp.last_tick_hook_error)

        os.remove(cfg_path)
        lp._hook_cfg_cache = None
        os.environ["MDCG_TICK_HOOK"] = inline_payload
        lp.last_tick_hook_error = None
        _chk(lp._tick_hook_path() == ""
             and isinstance(lp.last_tick_hook_error, dict)
             and lp.last_tick_hook_error.get("reason") == "flag_injection",
             "SEC-02d3 拒绝 env 中 -c 内联标志注入并记入 last_tick_hook_error", lp.last_tick_hook_error)

        # 3. 非 .py 文件、路径穿越、非常规文件（目录同名 .py）均被拒绝且非静默
        os.environ["MDCG_TICK_HOOK"] = non_py
        lp.last_tick_hook_error = None
        _chk(lp._tick_hook_path() == ""
             and (lp.last_tick_hook_error or {}).get("reason") == "not_py_file",
             "SEC-02e 拒绝非 .py 文件并记入 last_tick_hook_error", lp.last_tick_hook_error)
        os.environ["MDCG_TICK_HOOK"] = os.path.join(hook_dir, "..", "hooks", "good.py")
        lp.last_tick_hook_error = None
        _chk(lp._tick_hook_path() == ""
             and (lp.last_tick_hook_error or {}).get("reason") == "path_traversal",
             "SEC-02f 拒绝包含 '..' 的穿越路径并记入 last_tick_hook_error", lp.last_tick_hook_error)
        os.environ.pop("MDCG_TICK_HOOK", None)
        with open(cfg_path, "w", encoding="utf-8") as f:
            json.dump({"path": dir_as_py, "enabled": True}, f)
        lp._hook_cfg_cache = None
        lp.last_tick_hook_error = None
        _chk(lp._tick_hook_path() == ""
             and (lp.last_tick_hook_error or {}).get("reason") == "not_regular_file",
             "SEC-02f2 拒绝非常规文件（目录同名 .py）并记入 last_tick_hook_error", lp.last_tick_hook_error)

        # 4. MDCG_TICK_HOOK 指向受信任 good.py 时，_tick_hook.json 不能劫持到同目录的 evil.py
        os.environ["MDCG_TICK_HOOK"] = good_py
        with open(cfg_path, "w", encoding="utf-8") as f:
            json.dump({"path": evil_py, "enabled": True}, f)
        lp._hook_cfg_cache = None
        lp.last_tick_hook_error = None
        _chk(lp._tick_hook_path() == "", "SEC-02g _tick_hook.json 无法将受信任文件劫持至他处")
        lp._run_tick_hook("beat")
        _chk(not os.path.exists(evil_marker)
             and (lp.last_tick_hook_error or {}).get("reason") == "outside_allowed_roots",
             "SEC-02h 劫持脚本未被执行且记入 last_tick_hook_error", lp.last_tick_hook_error)

        # 4b. MDCG_TICK_HOOK 指向受信任目录时，_tick_hook.json 指向该目录内合法 .py 放行
        os.environ["MDCG_TICK_HOOK"] = hook_dir
        with open(cfg_path, "w", encoding="utf-8") as f:
            json.dump({"path": good_py, "enabled": True}, f)
        lp._hook_cfg_cache = None
        _chk(bool(lp._tick_hook_path()), "SEC-02h2 MDCG_TICK_HOOK 为目录时放行该目录内配置外钩")

        # 5. enabled=false 可动态暂停（不算拒绝错误）
        with open(cfg_path, "w", encoding="utf-8") as f:
            json.dump({"path": good_py, "enabled": False}, f)
        lp._hook_cfg_cache = None
        lp.last_tick_hook_error = None
        _chk(lp._tick_hook_path() == "" and lp.last_tick_hook_error is None,
             "SEC-02i _tick_hook.json enabled=false 正常暂停且不记错", lp.last_tick_hook_error)

        # 6. env 兜底：无配置文件时 MDCG_TICK_HOOK 合法外钩正常执行，且敏感环境变量被剥离
        os.remove(cfg_path)
        lp._hook_cfg_cache = None
        os.environ["MDCG_TICK_HOOK"] = good_py
        _chk(bool(lp._tick_hook_path()), "SEC-02j 合法 MDCG_TICK_HOOK 兜底通过校验")
        lp._run_tick_hook("beat")
        _chk(os.path.exists(good_out), "SEC-02k 合法 .py 外钩成功执行")
        if os.path.exists(good_out):
            rec = json.load(open(good_out, encoding="utf-8"))
            keys_u = {k.upper() for k in rec.get("env_keys", [])}
            _chk(rec.get("argv") == ["--tick", "beat"], "SEC-02l 参数传递正确", rec.get("argv"))
            _chk(not (keys_u & {"MDCG_MASTER_KEY", "MDCG_TOKEN", "MDCG_ADMIN_TOKEN"}),
                 "SEC-02m 子进程已剥离 MDCG_MASTER_KEY / MDCG_TOKEN / MDCG_ADMIN_TOKEN",
                 sorted(keys_u & {"MDCG_MASTER_KEY", "MDCG_TOKEN", "MDCG_ADMIN_TOKEN"}))

        # 7. 合法外钩执行返回非零退出码时，不中断心跳且记入 last_tick_hook_error
        os.environ.pop("MDCG_TICK_HOOK", None)
        with open(cfg_path, "w", encoding="utf-8") as f:
            json.dump({"path": fail_hook_py, "enabled": True}, f)
        lp._hook_cfg_cache = None
        lp.last_tick_hook_error = None
        lp._run_tick_hook("heal")
        _chk(isinstance(lp.last_tick_hook_error, dict)
             and lp.last_tick_hook_error.get("reason") == "nonzero_exit"
             and "rc=2" in str(lp.last_tick_hook_error.get("error") or "")
             and "hook boom" in str(lp.last_tick_hook_error.get("error") or ""),
             "SEC-02n 外钩非零退出非静默：记入 last_tick_hook_error", lp.last_tick_hook_error)
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        cg.close()


def _test_sec03_private_domain_cache_and_flag(tmp: str) -> None:
    print("\n== [SEC-03] 私密域 HotCache 泄漏、route/theory 通道与 include_private='false' 守卫 ==")
    root = os.path.join(tmp, "sec03_root")
    saved_hc = os.environ.get("MDCG_HOTCACHE")
    saved_inc = os.environ.pop("MDCG_INCLUDE_PRIVATE", None)
    os.environ["MDCG_HOTCACHE"] = "1"
    cg = MdCGSecure(root)
    try:
        cg.add("priv_dom_cache_1", "SECCACHE_TOKEN_8811 私密内容",
               layer="knowledge", tags=[M.PRIVATE_DOMAIN_TAG])
        cg.add("normal_cache_1", "SECCACHE_TOKEN_8811 公开内容",
               layer="knowledge", tags=["公开"])
        cg.add("theory_priv_1", "智能系统定义 私密理论笔记",
               layer="knowledge", tags=["理论真源", M.PRIVATE_DOMAIN_TAG],
               aliases=["智能系统定义"])
        cg.add("theory_pub_1", "智能系统定义 公开理论真源",
               layer="knowledge", tags=["理论真源"],
               aliases=["智能系统定义"])
        cg.flush()

        r1 = M.call_tool(cg, "mdcg_search", {"query": "SECCACHE_TOKEN_8811", "k": 5})
        ids1 = [x["node"]["id"] for x in (r1.get("results") or [])]
        _chk(ids1 == ["normal_cache_1"] and (r1.get("meta") or {}).get("private_domain_excluded") == 1,
             "SEC-03a 首次 mdcg_search 剔除 域:私密 并记数", (ids1, r1.get("meta")))

        # 第二次同参走 HotCache 命中：绝不可泄露 域:私密，且与首次一致
        hc = getattr(cg, "_hotcache_tool", None)
        hits_before = hc.stats()["query_hits"] if hc else 0
        r2 = M.call_tool(cg, "mdcg_search", {"query": "SECCACHE_TOKEN_8811", "k": 5})
        hits_after = hc.stats()["query_hits"] if hc else 0
        ids2 = [x["node"]["id"] for x in (r2.get("results") or [])]
        _chk(hits_after > hits_before and ids2 == ["normal_cache_1"],
             "SEC-03b 二次命中 HotCache 仍不泄露 域:私密", (hits_before, hits_after, ids2))
        _chk(r1.get("results") == r2.get("results"), "SEC-03c 缓存命中与未命中返回形状一致")

        # 字符串 "false" 必须按假处理（修复 bool("false") == True）
        r_str_false = M.call_tool(cg, "mdcg_search", {
            "query": "SECCACHE_TOKEN_8811", "k": 5, "include_private": "false"})
        ids_sf = [x["node"]["id"] for x in (r_str_false.get("results") or [])]
        _chk(ids_sf == ["normal_cache_1"], "SEC-03d include_private='false' 不泄露 域:私密", ids_sf)

        # 显式 include_private=True 可放行且不污染默认缓存键
        r_inc = M.call_tool(cg, "mdcg_search", {
            "query": "SECCACHE_TOKEN_8811", "k": 5, "include_private": True})
        ids_inc = sorted(x["node"]["id"] for x in (r_inc.get("results") or []))
        _chk(ids_inc == ["normal_cache_1", "priv_dom_cache_1"],
             "SEC-03e include_private=True 显式放行（不同缓存键）", ids_inc)

        r_after = M.call_tool(cg, "mdcg_search", {"query": "SECCACHE_TOKEN_8811", "k": 5})
        ids_after = [x["node"]["id"] for x in (r_after.get("results") or [])]
        _chk(ids_after == ["normal_cache_1"],
             "SEC-03f 放行查询不污染缺省缓存（后续缺省查询仍剔除 域:私密）", ids_after)

        # cg(op="route") 同样剔除 域:私密，且遵守 include_private
        rt_def = M.call_tool(cg, "cg", {"op": "route", "intent": "SECCACHE_TOKEN_8811", "k": 5})
        rt_ids = [x.get("id") for x in (rt_def.get("knowledge") or [])]
        _chk("priv_dom_cache_1" not in rt_ids and "normal_cache_1" in rt_ids
             and (rt_def.get("meta") or {}).get("private_domain_excluded") == 1,
             "SEC-03g cg(op=route) 缺省剔除 域:私密 并记数", (rt_ids, rt_def.get("meta")))
        rt_sf = M.call_tool(cg, "cg", {
            "op": "route", "intent": "SECCACHE_TOKEN_8811", "k": 5, "include_private": "false"})
        _chk("priv_dom_cache_1" not in [x.get("id") for x in (rt_sf.get("knowledge") or [])],
             "SEC-03h cg(op=route, include_private='false') 不泄露 域:私密")
        rt_inc = M.call_tool(cg, "cg", {
            "op": "route", "intent": "SECCACHE_TOKEN_8811", "k": 5, "include_private": True})
        _chk("priv_dom_cache_1" in [x.get("id") for x in (rt_inc.get("knowledge") or [])],
             "SEC-03i cg(op=route, include_private=True) 显式放行 域:私密")

        # cg(op="read") 理论快速通道同样经 _final_out 剔除 域:私密
        th_def = M.call_tool(cg, "cg", {"op": "read", "query": "智能系统定义", "hot_first": False})
        th_ids = [x["node"]["id"] for x in (th_def.get("results") or [])]
        _chk(((th_def.get("meta") or {}).get("theory_route") or {}).get("fast_path") is True
             and "theory_priv_1" not in th_ids and "theory_pub_1" in th_ids,
             "SEC-03j cg(op=read) 理论快速通道缺省剔除 域:私密", (th_ids, th_def.get("meta")))
        th_inc = M.call_tool(cg, "cg", {
            "op": "read", "query": "智能系统定义", "hot_first": False, "include_private": True})
        th_inc_ids = [x["node"]["id"] for x in (th_inc.get("results") or [])]
        _chk("theory_priv_1" in th_inc_ids and "theory_pub_1" in th_inc_ids,
             "SEC-03k cg(op=read) 理论快速通道在 include_private=True 时放行", th_inc_ids)
    finally:
        if saved_hc is None:
            os.environ.pop("MDCG_HOTCACHE", None)
        else:
            os.environ["MDCG_HOTCACHE"] = saved_hc
        if saved_inc is not None:
            os.environ["MDCG_INCLUDE_PRIVATE"] = saved_inc
        cg.close()


def _test_bug12_time_intent_boost() -> None:
    print("\n== [BUG-12] _time_intent_boost 日期正则修复守卫 ==")
    n_dated = ({"id": "d1", "content": "我们在 2026-11-17 立下合作约定", "frontmatter": {}}, 1.0, {})
    n_cn_date = ({"id": "d2", "content": "事件记录于 2026年11月 完成", "frontmatter": {}}, 1.0, {})
    n_plain = ({"id": "p1", "content": "普通说明文字不含任何日期", "frontmatter": {}}, 1.0, {})
    res, boosted = M._time_intent_boost([n_plain, n_dated, n_cn_date], "什么时候立的约定")
    scores = {item[0]["id"]: item[1] for item in res}
    _chk(boosted >= 2 and scores["d1"] >= 1.4 and scores["d2"] >= 1.4 and scores["p1"] == 1.0,
         "BUG-12a 真实日期 2026-11-17 / 2026年11月 获得 +0.4 加权", (boosted, scores))
    _chk(res[0][0]["id"] in ("d1", "d2"), "BUG-12b 含日期条目排在无日期条目之前", [x[0]["id"] for x in res])


def _test_bug13_run_tests_write_gate_default() -> None:
    print("\n== [BUG-13] md_cg/run_tests.py::_test_env() 默认 MDCG_WRITE_GATE=warn 守卫 ==")
    saved_wg = os.environ.pop("MDCG_WRITE_GATE", None)
    saved_th = os.environ.get("MDCG_TICK_HOOK")
    try:
        os.environ["MDCG_TICK_HOOK"] = "dummy_hook.py"
        env_def = RT._test_env()
        _chk(env_def.get("MDCG_WRITE_GATE") == "warn",
             "BUG-13a 未设 MDCG_WRITE_GATE 时 _test_env() 缺省注入 warn", env_def.get("MDCG_WRITE_GATE"))
        _chk("MDCG_TICK_HOOK" not in env_def,
             "BUG-13b _test_env() 保留上游 MDCG_TICK_HOOK 剔除行为")

        os.environ["MDCG_WRITE_GATE"] = "enforce"
        env_exp = RT._test_env()
        _chk(env_exp.get("MDCG_WRITE_GATE") == "enforce",
             "BUG-13c 显式设置 MDCG_WRITE_GATE=enforce 时不被覆写", env_exp.get("MDCG_WRITE_GATE"))
    finally:
        if saved_wg is None:
            os.environ.pop("MDCG_WRITE_GATE", None)
        else:
            os.environ["MDCG_WRITE_GATE"] = saved_wg
        if saved_th is None:
            os.environ.pop("MDCG_TICK_HOOK", None)
        else:
            os.environ["MDCG_TICK_HOOK"] = saved_th


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="mdcg_iss1009_1010_")
    saved_env = {k: os.environ.get(k) for k in (
        "MDCG_AUX_ROOT", "MDCG_STATE_ROOT", "MDCG_MASTER_KEY",
        "MDCG_WRITE_GATE", "MDCG_SESSION", "DSH_SESSION_ID", "DSH_SESSION")}
    os.environ["MDCG_AUX_ROOT"] = os.path.join(tmp, "aux_sidecar")
    os.environ["MDCG_STATE_ROOT"] = os.path.join(tmp, "state_sidecar")
    os.environ["MDCG_MASTER_KEY"] = "1" * 64
    os.environ["MDCG_WRITE_GATE"] = "warn"
    for _k in ("MDCG_SESSION", "DSH_SESSION_ID", "DSH_SESSION"):
        os.environ.pop(_k, None)
    try:
        _test_sec01_hottier(tmp)
        _test_sec02_sustain_tick_hook(tmp)
        _test_sec03_private_domain_cache_and_flag(tmp)
        _test_bug12_time_intent_boost()
        _test_bug13_run_tests_write_gate_default()
    finally:
        for k, v in saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(tmp, ignore_errors=True)
    print("\n" + "=" * 64)
    print("issue #1009/#1010 守卫：%d 通过 / %d 失败" % (_PASS, len(_FAIL)))
    if _FAIL:
        print("失败项：" + ", ".join(_FAIL))
    print("=" * 64)
    return 0 if not _FAIL else 1


if __name__ == "__main__":
    sys.exit(main())
