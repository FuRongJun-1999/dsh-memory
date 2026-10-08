# -*- coding: utf-8 -*-
"""守卫：md_cg MCP server 的**入口自保证 OpenBLAS 线程数**（2026-10-05 返修）

病灶（本机取证，2026-10-05）：numpy（md_cg 可选依赖，经 whitebox_kb 系列模块
加载）在**导入期**由 OpenBLAS 按线程数（默认 = 核数）申请每线程缓冲——32 核机
实测单进程 ``import numpy`` 的全机提交内存增量 **0.73 GiB**。启动链上的代校验
（``verify_delegations`` → 导入含 numpy 的目标模块）把这笔分配带到**服务应答
之前**：机器提交内存吃紧、或**多进程同启**（并行测试套件 / 多会话并存）时，
OpenBLAS 重试 10 次后放弃并 ``exit(1)``——进程在 initialize 应答前死亡，桥侧
只见「握手失败 / 插件激活失败」（TS 套件实测失败用例的子进程 stderr 逐字为
``OpenBLAS error: Memory allocation still failed after 10 retries``）。

修法（本件守门）：``md_cg/mcp_server.py`` **模块级**（早于 main 的代校验，即
numpy 的首个导入点之前）在未设/空白时置 ``OPENBLAS_NUM_THREADS=1``——实测单
进程提交增量 0.73 → 0.013 GiB，12 个并发 ``import numpy`` 由 4~9/12 失败（两轮
独立读数，随机器提交内存压力波动）转为 0/12（两轮）；单线程对现有数值面无已观测
的性能意义（⚠ 未做基准实测，见 mcp_server.py 入口块注释）。

断言（红基线 = 去掉该入口块；HEAD worktree 实测：G1/G3/G4/G6a/G6b 转红；
G2 两侧皆绿＝独立于入口块的口径锚；G5 为压力依赖，本轮未触发红）：
  G1 缺省：子进程 import md_cg.mcp_server 后 env 值 = "1"（进程自保证）
  G2 显式设值优先：预置 "4" → 保持 "4"（不覆盖部署方调优）
  G3 空白视为未设：预置 "   " → 归一 "1"（仓库口径：空白视为未设置）
  G4 时序：import 完成后 numpy 尚未加载（模块级早于 main 的代校验）；随后同
     进程 import numpy 成功——自保证早于首个 numpy 导入生效
  G5 实弹并发：6 个并发子进程各走「import mcp_server + verify_delegations」
     全部成功（本套件红案的收敛形态：并行下子进程启动不得死于 OpenBLAS）
  G6 站点锚（AST）：入口块是**模块体顶层**的赋值语句且行号早于该文件首个模块级
     `def`（须早于一切模块级 I/O 的既有锚口径，与 test_utf8_boot_guard 的
     ANCHOR ⑤ 同款；防未来把保证挪进函数/挪到文件尾）

定点变异自证（本守卫做不了运行期反证——保证是 import 期一次性副作用，故按
仓内惯例在**临时物化副本**上做，绝不改工作树；本机实测读数记录于此）：
  取 md_cg 树副本、删掉入口块后跑 G1/G4/G5 同款子进程：
    G1 → env 值为 None（红）；G5 → 6 并发在提交内存吃紧时出现 OpenBLAS 失败
    （同机同压力量级实测：不导入 mcp_server 的同形并发 12 个默认 9/12 败）。
  本守卫自带 G1~G6 判据不含变异装置（保持套件轻量）；上表为一次性变异取证。

运行：python -X utf8 -m md_cg.test_boot_openblas_guard
"""
from __future__ import annotations

import ast
import os
import shutil
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PASS = FAIL = 0
FAILS = []
# issue #84.1（2026-10-09 DSH 端）：显式跳过计数——无 numpy 的解释器上 G4 不判红，
# 但必须在汇总行明示「跳过 1」，不许静默放绿（对齐 #84 口径）。
SKIPPED = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  OK   {name}")
    else:
        FAIL += 1
        FAILS.append(name)
        print(f"  FAIL {name}  {detail}")


# 生效条件：本解释器可导入 numpy 时返回 True，否则 False；恒不抛。
def _numpy_available():
    """issue #84.1：numpy 是 md_cg 的**可选**依赖，而 G4 断言「import numpy 成功」。
    无 numpy 的解释器（如本机 MDCG_PYTHON 3.13.12）上该断言恒红——那是环境缺失，
    不是缺陷回归。故显式 SKIP 并在汇总行计入跳过，而非静默放绿。"""
    try:
        import numpy  # noqa: F401
        return True
    except Exception:
        return False


# 生效条件：总是返回一份「清掉 OPENBLAS_NUM_THREADS、锚定本仓 PYTHONPATH、隔离
# 记忆根到 tmp 之下」的子进程 env（extra 最后覆盖，供 G2/G3 预置取值）。
def _child_env(tmp, extra=None):
    env = dict(os.environ)
    env.pop("OPENBLAS_NUM_THREADS", None)
    env["PYTHONPATH"] = REPO
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    # 防御性隔离：本守卫只 import 模块与跑代校验（纯读），但仍把记忆根钉在
    # 临时面——绝不因未来代码路径变化回落到真实 ~/.mdcg。
    env.setdefault("MDCG_ROOT", os.path.join(tmp, "cgroot"))
    env.setdefault("MDCG_AUX_ROOT", os.path.join(tmp, "auxroot"))
    env.setdefault("MDCG_STATE_ROOT", os.path.join(tmp, "state"))
    env.setdefault("MDCG_DATA_ROOT", os.path.join(tmp, "data"))
    if extra:
        env.update(extra)
    return env


# 生效条件：code 在子解释器中执行（cwd=仓根、argv 列表、显式 UTF-8），返回
# (returncode, stdout 去尾空白, stderr 末 400 字符)。
def _run_child(code, env, timeout=180):
    r = subprocess.run([sys.executable, "-c", code], cwd=REPO, env=env,
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=timeout, shell=False)
    return r.returncode, (r.stdout or "").strip(), (r.stderr or "")[-400:]


_G1_CODE = "import os\nimport md_cg.mcp_server\nprint(os.environ.get('OPENBLAS_NUM_THREADS'))\n"

_G4_CODE = ("import os\nimport sys\nimport md_cg.mcp_server\n"
            "pre = 'numpy' in sys.modules\n"
            "import numpy\n"
            "print(os.environ.get('OPENBLAS_NUM_THREADS'), pre)\n")

# 收敛形态：与 TS 套件受害路径同构——「服务启动期：导入模块 → 代校验导入 numpy」。
_G5_CODE = ("import md_cg.mcp_server\n"
            "from md_cg import generation\n"
            "r = generation.verify_delegations()\n"
            "print('OK', r['ok'])\n")


# 生效条件：能读到被守卫源码与 G6 需要的两处行号时返回 (module_body 首个
# def 行号, 入口块行号)；入口块（模块体顶层的 os.environ["OPENBLAS_NUM_THREADS"]
# 赋值所在 If）不存在时返回 (def 行号, None)。
def _entry_block_lines():
    ap = os.path.join(REPO, "md_cg", "mcp_server.py")
    with open(ap, encoding="utf-8") as fh:
        tree = ast.parse(fh.read(), filename="md_cg/mcp_server.py")
    defs = [n.lineno for n in tree.body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    first_def = min(defs) if defs else None
    block = None
    for node in tree.body:                          # 只认模块体顶层（函数内不算）
        if not isinstance(node, ast.If):
            continue
        for sub in node.body:
            if not (isinstance(sub, ast.Assign) and sub.targets):
                continue
            tgt = sub.targets[0]
            if (isinstance(tgt, ast.Subscript)
                    and isinstance(tgt.value, ast.Attribute)
                    and tgt.value.attr == "environ"
                    and isinstance(tgt.slice, ast.Constant)
                    and tgt.slice.value == "OPENBLAS_NUM_THREADS"):
                block = node.lineno
    return first_def, block


def main():
    tmp = tempfile.mkdtemp(prefix="mdcg_openblas_guard_")
    try:
        print("== G1~G3 env 口径（进程自保证 / 显式优先 / 空白归一）==")
        rc, out, err = _run_child(_G1_CODE, _child_env(tmp))
        check("G1 缺省：import md_cg.mcp_server 后 OPENBLAS_NUM_THREADS=1",
              rc == 0 and out == "1", f"rc={rc} out={out!r} err={err!r}")

        rc, out, err = _run_child(_G1_CODE, _child_env(
            tmp, {"OPENBLAS_NUM_THREADS": "4"}))
        check("G2 显式设值优先：预置 4 → 保持 4（不覆盖部署方调优）",
              rc == 0 and out == "4", f"rc={rc} out={out!r} err={err!r}")

        rc, out, err = _run_child(_G1_CODE, _child_env(
            tmp, {"OPENBLAS_NUM_THREADS": "   "}))
        check("G3 空白视为未设：预置空白 → 归一为 1",
              rc == 0 and out == "1", f"rc={rc} out={out!r} err={err!r}")

        print("== G4 时序：自保证早于首个 numpy 导入，且 numpy 随后可导入 ==")
        if _numpy_available():
            rc, out, err = _run_child(_G4_CODE, _child_env(tmp))
            check("G4 import mcp_server 后 numpy 未加载；numpy 导入成功且值=1",
                  rc == 0 and out == "1 False", f"rc={rc} out={out!r} err={err!r}")
        else:
            global SKIPPED
            SKIPPED += 1
            print("  SKIP G4 本解释器无 numpy（ModuleNotFoundError）——按 issue #84 口径"
                  "显式跳过，不静默放绿；该腿需在有 numpy 的解释器上复跑")

        print("== G5 实弹并发：6 个「启动期（import + 代校验）」子进程全部成功 ==")
        env5 = _child_env(tmp)
        procs = [subprocess.Popen([sys.executable, "-c", _G5_CODE], cwd=REPO,
                                  env=env5, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE)
                 for _ in range(6)]
        bad = []
        for i, p in enumerate(procs):
            o, e = p.communicate(timeout=300)
            o = (o or b"").decode("utf-8", "replace")
            e = (e or b"").decode("utf-8", "replace")
            if p.returncode != 0 or "OK True" not in o:
                bad.append("child%d rc=%s out=%r err=%r" % (i, p.returncode,
                                                            o[-120:], e[-320:]))
        check("G5 6 个并发启动期子进程全部成功（无 OpenBLAS 分配失败）",
              not bad, "；".join(bad)[:600])

        print("== G6 站点锚（AST）：入口块在模块体顶层且早于首个模块级 def ==")
        first_def, block = _entry_block_lines()
        check("G6a 入口块存在且为模块体顶层语句（函数内不算）",
              block is not None,
              "md_cg/mcp_server.py 模块体未见 os.environ['OPENBLAS_NUM_THREADS'] 赋值")
        check("G6b 入口块早于首个模块级 def（不晚于一切模块级 I/O 的既有锚口径）",
              block is not None and first_def is not None and block < first_def,
              f"入口块行={block} 首个 def 行={first_def}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n" + "=" * 64)
    print(f"PASS={PASS}  FAIL={FAIL}  跳过={SKIPPED}")
    if FAILS:
        print("失败项：" + "；".join(FAILS))
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
