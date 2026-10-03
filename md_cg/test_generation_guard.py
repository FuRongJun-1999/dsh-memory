# -*- coding: utf-8 -*-
"""守卫：代校验单点（`md_cg/generation.py`）与它的两处接线

用法（仓根直跑，退出码 0 ＝ 全绿）：

    python -X utf8 -m md_cg.test_generation_guard

守的是「长驻 MCP 进程跨代混合快照」这条已定因缺陷的处置（使用者裁定方案 b：
把「升级后须重启长驻 MCP 进程」写成运维前提 + 加一道代校验）。五项：

  一 全绿：`verify_delegations()` 对**当前树**（逐字节临时副本）必须通过，
     并打印扫到的委托项数与目标模块数。
  二 定点变异自证：在临时副本里把 `md_cg/mdcg.py` 的 `mint_auto_id` 定义改名，
     `verify_delegations()` 必须抛 `GenerationError` 且消息**逐字点名**目标子模块
     与名字（证明它不是「恒绿的摆设」）。
  三 判别力自证：临时副本里改一个源文件后 `is_stale()` 必须 True，恢复后必须 False
     （证明指纹认内容不认 mtime）。
  四 AST 断言：`mcp_server.py` 里 `generation.verify_delegations(` 的调用**不在
     模块顶层**——只在函数体内（顶层调用会与函数内延迟导入的避环设计冲突）。
  五 键集对拍：对临时 root 上的 `cg(op=info)` 真调一次 MCP 服务，响应必须含
     code_generation / disk_generation / stale_on_disk / restart_required / hint
     五个新键，且**既有键集合**与读码钉住的 19 键（18 既有 + issue #53-B 扩键
     bucket_scope）逐字一致。

安全边界：一切在 `tempfile.mkdtemp()` 临时目录内进行（md_cg 树是复制出来的副本），
绝不写工作区、绝不写任何在役记忆库、绝不起用真 root 的常驻服务、绝不重启/终止
任何在跑的进程——本守卫只**新起**短命子进程（argv 列表 + shell=False + UTF-8）。
"""
from __future__ import annotations

import ast
import json
import os
import shutil
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:                # 保证 `import md_cg.*` 能定位到当前树的包
    sys.path.insert(0, REPO)

# 钉住的 cg(op=info) 既有键集合（在临时 root 上实跑一次服务所读）：
# 18 键为 2026-09-30 接线前读码名单；bucket_scope 为 issue #53-B（2026-10-03）
# 的**有意扩键**（分桶读数覆盖面自述，纯增量、与既有键无冲突，与代校验五键
# 同构的扩键流程）——名单同步至此；其后任何未声明的漂移仍被 extra/lost 两向抓出。
PINNED_INFO_KEYS = frozenset({
    "action_source", "audit_kinds", "buckets", "bucket_scope", "ccg_by_layer",
    "ccg_contract", "external_verifiers", "links", "neg_memory_counts", "ok",
    "os", "reason", "security", "surface", "theory", "tools", "total_nodes",
    "whoami", "write_policy",
})

NEW_INFO_KEYS = ("code_generation", "disk_generation", "stale_on_disk",
                 "restart_required", "hint")

_FAILED = []


def _ok(tag, text):
    print("[PASS] %s —— %s" % (tag, text))


def _fail(tag, text):
    _FAILED.append(tag)
    print("[FAIL] %s —— %s" % (tag, text))


def _child_env(root):
    """子进程环境：显式 UTF-8 + 全临时 root（绝不碰在役库）。"""
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONPATH"] = root
    env["MDCG_ROOT"] = os.path.join(root, "_guard_mem")
    env["MDCG_AUX_ROOT"] = os.path.join(root, "_guard_aux")
    env["DSH_HOME"] = root
    env.pop("MDCG_TOKEN", None)
    return env


def _run(args, cwd, env, timeout=600):
    """argv 列表 + shell=False + capture_output 的显式 UTF-8 调用（第 15 条）。"""
    return subprocess.run(args, cwd=cwd, env=env, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", shell=False,
                          timeout=timeout)


def _copy_tree(dst_root):
    """把当前树的 md_cg 复制成临时副本，返回副本包目录。

    连仓根一级模块（`utf8_boot.py`——md_cg 各入口在文件 I/O 前用它自保证 UTF-8）
    一并复制：否则副本里 `import md_cg.mcp_server` 会因缺 utf8_boot 而失败，把
    指向它的延迟导入统统降级成「非致命不可用」，副本就不再忠实于当前树。
    """
    shutil.copytree(os.path.join(REPO, "md_cg"),
                    os.path.join(dst_root, "md_cg"),
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for name in os.listdir(REPO):
        if name.endswith(".py"):
            shutil.copy2(os.path.join(REPO, name), os.path.join(dst_root, name))
    return os.path.join(dst_root, "md_cg")


_VERIFY_SNIPPET = (
    "import json\n"
    "from md_cg import generation as g\n"
    "r = g.verify_delegations()\n"
    "print(json.dumps({'ok': r['ok'], 'delegations': r['delegations'],\n"
    "                  'target_modules': r['target_modules'],\n"
    "                  'resolved': r['resolved'],\n"
    "                  'scanned_files': r['scanned_files'],\n"
    "                  'unavailable': len(r['unavailable']),\n"
    "                  'generation': g.STARTUP_FINGERPRINT[:12]}, ensure_ascii=False))\n"
)

_MUTATION_SNIPPET = (
    "import json, sys\n"
    "from md_cg import generation as g\n"
    "try:\n"
    "    g.verify_delegations()\n"
    "except g.GenerationError as e:\n"
    "    print(json.dumps({'raised': 'GenerationError', 'msg': str(e)},\n"
    "                     ensure_ascii=False))\n"
    "except Exception as e:\n"
    "    print(json.dumps({'raised': type(e).__name__, 'msg': str(e)},\n"
    "                     ensure_ascii=False))\n"
    "else:\n"
    "    print(json.dumps({'raised': None}, ensure_ascii=False))\n"
)

_STALE_SNIPPET = (
    "import io, json, os\n"
    "from md_cg import generation as g\n"
    "target = os.path.join(os.path.dirname(g.__file__), 'fsutil.py')\n"
    "raw = io.open(target, encoding='utf-8').read()\n"
    "clean = g.is_stale()\n"
    "io.open(target, 'w', encoding='utf-8', newline='').write(raw + '\\n# 守卫临时改动\\n')\n"
    "modified = g.is_stale()\n"
    "io.open(target, 'w', encoding='utf-8', newline='').write(raw)\n"
    "restored = g.is_stale()\n"
    "print(json.dumps({'clean': clean, 'modified': modified,\n"
    "                  'restored': restored, 'fp': g.fingerprint()[:12]},\n"
    "                 ensure_ascii=False))\n"
)


# 一 + 二 + 三：临时副本上的三项自证
def check_verify_and_mutation(tmp):
    print("\n== 一 全绿（当前树的临时副本）+ 二 定点变异 + 三 判别力 ==")
    _copy_tree(tmp)
    env = _child_env(tmp)

    real = _run([sys.executable, "-X", "utf8", "-c", _VERIFY_SNIPPET], tmp, env)
    if real.returncode != 0:
        _fail("一·全绿", "子进程退出码 %s：%s" % (real.returncode,
                                                (real.stderr or "")[-500:]))
        return
    data = json.loads(real.stdout.strip().splitlines()[-1])
    print("     扫描文件 %d 个 / 委托项 %d 项 / 目标模块 %d 个 / 已解析 %d 项 / "
          "可选缺失 %d 项 / 副本代 %s"
          % (data["scanned_files"], data["delegations"], data["target_modules"],
             data["resolved"], data["unavailable"], data["generation"]))
    if not data["ok"]:
        _fail("一·全绿", "verify_delegations() 在副本上未通过")
        return

    # 副本与当前树同形自证：现树的指纹（本进程内只读计算）必须等于副本自报的代
    from md_cg import generation as _real_gen           # 只读：只算哈希
    real_fp = _real_gen.fingerprint()[:12]
    if real_fp != data["generation"]:
        _fail("一·全绿", "副本代 %s 与当前树代 %s 不同——副本不忠实，结论不成立"
              % (data["generation"], real_fp))
        return
    _ok("一·全绿", "verify_delegations() 通过，且副本与当前树同代 %s" % real_fp)

    # 二：定点变异——改名 mdcg.py 里的 mint_auto_id 定义
    mdcg_path = os.path.join(tmp, "md_cg", "mdcg.py")
    with open(mdcg_path, encoding="utf-8") as fh:
        original = fh.read()
    mutated = original.replace("def mint_auto_id(", "def mint_auto_id_renamed(", 1)
    if mutated == original:
        _fail("二·定点变异", "定位不到 def mint_auto_id( ——变异未生效，本条不成立")
        return
    with open(mdcg_path, "w", encoding="utf-8", newline="") as fh:
        fh.write(mutated)
    try:
        mut = _run([sys.executable, "-X", "utf8", "-c", _MUTATION_SNIPPET], tmp, env)
    finally:
        with open(mdcg_path, "w", encoding="utf-8", newline="") as fh:
            fh.write(original)
    if mut.returncode != 0:
        _fail("二·定点变异", "子进程退出码 %s：%s" % (mut.returncode,
                                                    (mut.stderr or "")[-500:]))
        return
    got = json.loads(mut.stdout.strip().splitlines()[-1])
    if got.get("raised") != "GenerationError":
        _fail("二·定点变异", "期望 GenerationError，实得 %r" % (got.get("raised"),))
        return
    msg = got.get("msg") or ""
    if "md_cg.mdcg" not in msg or "mint_auto_id" not in msg:
        _fail("二·定点变异", "异常消息未逐字点名子模块/名字：%r" % msg[:400])
        return
    print("     异常消息首行：%s" % msg.splitlines()[0])
    _ok("二·定点变异", "去掉 mint_auto_id 定义后抛出 GenerationError，消息点名 "
                       "md_cg.mdcg + mint_auto_id")

    # 三：判别力——同一进程内改盘 → is_stale True；恢复 → False
    st = _run([sys.executable, "-X", "utf8", "-c", _STALE_SNIPPET], tmp, env)
    if st.returncode != 0:
        _fail("三·判别力", "子进程退出码 %s：%s" % (st.returncode,
                                                  (st.stderr or "")[-500:]))
        return
    s = json.loads(st.stdout.strip().splitlines()[-1])
    if (s["clean"], s["modified"], s["restored"]) != (False, True, False):
        _fail("三·判别力", "期望 (False, True, False)，实得 %r"
              % ((s["clean"], s["modified"], s["restored"]),))
        return
    if s["fp"] != real_fp:
        _fail("三·判别力", "恢复后指纹 %s ≠ 原代 %s（恢复不彻底）" % (s["fp"], real_fp))
        return
    _ok("三·判别力", "改一个源文件后 is_stale()=True，恢复后 False（代 %s 复原）"
        % s["fp"])


# 四：AST 断言——verify_delegations 的调用不在 mcp_server.py 的模块顶层
def check_call_site_not_toplevel():
    print("\n== 四 AST 断言：调用点不在模块顶层 ==")
    path = os.path.join(REPO, "md_cg", "mcp_server.py")
    with open(path, encoding="utf-8") as fh:
        tree = ast.parse(fh.read(), path)

    found = []          # (lineno, depth, 是否在 main 内)

    class _V(ast.NodeVisitor):
        def __init__(self):
            self.depth = 0
            self.func = []

        def _fn(self, node):
            self.depth += 1
            self.func.append(node.name)
            self.generic_visit(node)
            self.func.pop()
            self.depth -= 1

        visit_FunctionDef = _fn
        visit_AsyncFunctionDef = _fn

        def visit_Call(self, node):
            f = node.func
            if isinstance(f, ast.Attribute) and f.attr == "verify_delegations":
                found.append((node.lineno, self.depth,
                              self.func[-1] if self.func else None))
            self.generic_visit(node)

    _V().visit(tree)
    if not found:
        _fail("四·调用点", "mcp_server.py 里找不到 *.verify_delegations(...) 调用"
                           "——接线缺失")
        return
    top = [f for f in found if f[1] == 0]
    if top:
        _fail("四·调用点", "存在模块顶层调用（第 %s 行）——会与函数内延迟导入的"
                           "避环设计冲突" % ", ".join(str(t[0]) for t in top))
        return
    _ok("四·调用点", "%d 处调用全在函数体内：%s"
        % (len(found), ", ".join("%s:%d" % (f[2], f[0]) for f in found)))


# 五：键集对拍——对临时 root 上真起的 MCP 服务调 cg(op=info)
def check_info_keys(tmp):
    print("\n== 五 键集对拍：cg(op=info) 真调（临时 root） ==")
    env = _child_env(tmp)
    # 本条要验的是**工作区里这套接线**（不是副本），故包来源显式钉到当前树：
    # 记忆 root / aux / DSH_HOME 仍是临时目录（隔离），只有代码取自当前树。
    env["PYTHONPATH"] = REPO
    lines = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                    "clientInfo": {"name": "generation-guard", "version": "0"}}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
         "params": {"name": "cg", "arguments": {"op": "info"}}},
        {"jsonrpc": "2.0", "id": 3, "method": "shutdown", "params": {}},
    ]
    payload = "\n".join(json.dumps(x, ensure_ascii=False) for x in lines) + "\n"
    r = subprocess.run([sys.executable, "-X", "utf8", "-m", "md_cg.mcp_server"],
                       cwd=REPO, env=env, input=payload, capture_output=True,
                       text=True, encoding="utf-8", errors="replace",
                       shell=False, timeout=600)
    if r.returncode != 0:
        _fail("五·键集", "mcp_server 退出码 %s（代校验接线可能把启动打死了）：%s"
              % (r.returncode, (r.stderr or "")[-700:]))
        return
    info = None
    for line in r.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if obj.get("id") == 2 and "result" in obj:
            info = json.loads(obj["result"]["content"][0]["text"])
    if info is None:
        _fail("五·键集", "没取到 cg(op=info) 响应：stdout=%s" % (r.stdout or "")[:400])
        return
    keys = set(info)
    missing = [k for k in NEW_INFO_KEYS if k not in keys]
    if missing:
        _fail("五·键集", "缺新键：%s" % missing)
        return
    extra = sorted(keys - PINNED_INFO_KEYS - set(NEW_INFO_KEYS))
    lost = sorted(PINNED_INFO_KEYS - keys)
    if extra or lost:
        _fail("五·键集", "既有键集被改动：多出 %s / 丢失 %s" % (extra, lost))
        return
    if info["code_generation"] != info["disk_generation"]:
        _fail("五·键集", "刚起的进程自报跨代：code=%s disk=%s"
              % (info["code_generation"], info["disk_generation"]))
        return
    if info["stale_on_disk"] is not False or info["restart_required"] is not False:
        _fail("五·键集", "刚起的进程 stale_on_disk/restart_required 应为 False，"
                         "实得 %r/%r" % (info["stale_on_disk"],
                                         info["restart_required"]))
        return
    if "重启常驻 MCP 进程" not in (info["hint"] or ""):
        _fail("五·键集", "hint 未含处置指引：%r" % (info["hint"],))
        return
    _ok("五·键集", "五新键齐备、既有 19 键（18 + #53-B 扩键 bucket_scope）一字未动；"
                   "代 %s（code==disk，restart_required=False）"
        % info["code_generation"])


def main():
    print("代校验守卫（generation guard）——临时目录内进行，不碰工作区与在役库")
    tmp = tempfile.mkdtemp(prefix="mdcg_gen_guard_")
    print("临时 root：%s" % tmp)
    try:
        check_verify_and_mutation(tmp)
        check_call_site_not_toplevel()
        check_info_keys(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("")
    if _FAILED:
        print("结果：%d 项红 —— %s" % (len(_FAILED), "、".join(_FAILED)))
        return 1
    print("结果：全绿（0 红）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
