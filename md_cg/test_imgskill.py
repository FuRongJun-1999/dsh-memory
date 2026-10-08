# -*- coding: utf-8 -*-
r"""图像 Skill（`md_cg/imgskill.py`）守卫 · 契约真源 `docs/eval/图像Skill_接口契约_设计_v0.1.md` §五/§六/§九。

断言面（G1–G7 **＋ X 面（新增 9 op）**，逐条**能红**并附**定点变异自证**：注入退化 →
恰好打中预期红项、不连坐）：

  * **G1 同输入幂等**（§九-#6 像素级门）——同输入同参两次 → **逐像素相等**
    （读回比对；**不比字节**——位级不是门，字节读数只作信息项打印）。
  * **G2 中文路径可用**（§3.5 + 摸底稿 A3）——中文目录名 + 中文文件名跑 resize+convert 全链。
  * **G3 错误态可判别**（§3.3）——造 4 类必需样例（`E_NOINPUT`／`E_BAD_PARAM`／
    `E_PATH_OUT_OF_SCOPE`／`E_TOOL_MISSING`）＋ 4 类追加（`E_DECODE`／`E_UNSUPPORTED_OP`／
    `E_LEVEL_DOWNGRADE`／`E_UNSUPPORTED_FORMAT`），断言**指定错误码**（不靠消息文本）。
    （本批起 `crop` 已实现 → 该项的 `E_UNSUPPORTED_OP` 例改用仍在范围外的 `extract`，
    断言强度不变。）
  * **G4 审计字段齐**（§4.1）——成功/失败各落一行，公共字段逐项在场（缺点名清单）。
  * **G5 结构断言**（§六-G5）——① 模块 import 面零 `md_cg` 依赖、且不含 judge/trust/writepipe；
    ③ 产物落点必须在调用方给的沙箱根之内。
  * **G6 禁裸 convert 硬门**（§六-G6 + §3.5）——AST 扫 `imgskill.py`：不得以裸 `convert`
    为 argv[0]／不得 `shutil.which("convert")`／不得 `shell=True`；守卫源码自身不被误判。
  * **G7 fail-closed**（§九-#8 + §六-G7）——未给沙箱根／越界路径／等级降级 → 一律拒绝，
    **禁静默放行**（不得返回 `ok=true`）。
  * **X-验收（§五 逐行判据）**——新增的 9 个 op 各按契约 §五 的验收栏判：
    `thumbnail` 最长边 == `max_edge`（缩/放两向）；`crop` 尺寸 == 裁窗**且内容对应**；
    `rotate` 90 倍数尺寸对调 + **正角=顺时针**（像素级）+ 非直角外接矩形（±3px 容差，
    两后端取值本有差异）+ 空白填白；`flip`/`flop` 与源同尺寸 + 镜像像素级断言 +
    两 op 结果不同；`adjust`/`blur`/`sharpen` 参数入台账 + 同参幂等 + 效果方向
    （亮度单调/模糊变平滑/锐化像素变化）；`composite` 尺寸同 base + `gravity` 落位
    逐像素 + `opacity=0.5` 半透明叠合；`mask` alpha 通道存在**且逐像素对 mask 灰度**。
    （判据一律**以落盘产物为准**，并核对出参 `meta` 与之一致。）
  * **X-台账**——9 op 的台账 `params` 必等于**归一入参**（默认值补齐/别名解析后）。
  * **X-幂等**——同 `idempotency_key` 同参 → 复用已存产物（`reused_from` 在场）+ 像素恒等。
  * **X-中文路径**——9 op 全链（源/over/mask/产物全为中文名）逐个跑通。
  * **X-错误态**——新 op 的 27 例坏参数 → 指定错误码（含 `mask.mode="mul"` → `E_UNSUPPORTED_OP`、
    `mask` 写面收窄 → `E_UNSUPPORTED_FORMAT`）。
  * **X-范围**——`E_UNSUPPORTED_OP` **收窄**：13 个已实现 op 必不返回它；范围外集
    （`extract`/`export`/L1 类/L2 类/未知 op）必返回它；`OPS_IMPL` 与实现表 `_OPS` 一致。
  * **Y-暴露面 / 结构防悬空（契约 §十二）**——`Y1`：以**子进程**跑真 CLI
    （`python -X utf8 -m md_cg.imgskill ...`）——`--help` 列全部已实现 op；`inspect`
    rc=0、出参键面齐、读数与库 `run()` **逐项一致**且**落审计台账**（证明 CLI 与库
    是**同一条**实现路径，不是第二份逻辑）；`resize`/`convert` 产物落盘尺寸/格式对；
    未给 `--root` → fail-closed（rc=1、`E_BAD_PARAM`）；`_CLI_OPS`/`OPS_IMPL`/子命令
    三处 op 面一致。`Y2`：**结构防悬空**——`__main__` 入口锚点须恰好 1 处；真件判据为
    绿；**摘掉入口的变异件必须转红**（同形先例：`test_curiosity_budget.py` C6、
    `test_gain_gate.py` 的生产路径断言）。

断言计数：G1–G7 18 条（**未减弱**）＋ X 面 21 条 ＋ Y 面 4 条 = **43 条**
（`--` 见末行 `N passed`）。

边界：测试与实验一律落 `tempfile` 沙箱，**不写任何在役库**；本件不改 `md_cg/` 生产逻辑。
后端无关：`imgskill` 走自动路由（`magick` 优先、Pillow 兜底）。若要压 `magick` 面，
在环境里显式给 `IMGSKILL_MAGICK=<magick 可执行体全路径>` 再跑本件——本件内**不写本机绝对路径字面量**。

运行：`python -m md_cg.test_imgskill`（退出码 0 全绿 / 1 有红）；两条后端路径都要跑绿
（默认 = PATH 无 magick → Pillow 兜底且降级留痕；`IMGSKILL_MAGICK` 注入 → magick）。
"""
from __future__ import annotations

import ast
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
from contextlib import contextmanager

from PIL import Image

from . import imgskill as S

PASS = FAIL = 0
FAILS = []
READINGS = []
_ROOTS = []

#: §4.1 公共字段（每次操作必落）
AUDIT_KEYS = ("audit_id", "op", "level", "input_path", "input_sha256",
              "output_path", "output_sha256", "params", "tool_version", "env",
              "ts", "caller", "ok", "error_code")


def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        FAILS.append(label)
        print(f"  FAIL {label}")


def reading(k, v):
    READINGS.append((k, v))


@contextmanager
def _env(**kw):
    old = {k: os.environ.get(k) for k in kw}
    for k, v in kw.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    try:
        yield
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


# ---------------------------------------------------------------- 夹具

def mk_root(prefix="imgskill_g_"):
    r = tempfile.mkdtemp(prefix=prefix)
    _ROOTS.append(r)
    return r


def mk_src(root, rel, size=(40, 30), color=(12, 200, 40)):
    """造确定性源图（渐变 + 定色），写进沙箱根内。"""
    p = os.path.join(root, rel)
    d = os.path.dirname(p)
    if d:
        os.makedirs(d, exist_ok=True)
    im = Image.new("RGB", size)
    px = im.load()
    for y in range(size[1]):
        for x in range(size[0]):
            px[x, y] = ((color[0] + x * 3) % 256, (color[1] + y * 5) % 256,
                        (color[2] + (x + y) * 2) % 256)
    im.save(p)
    return p


def abspath(root, rel):
    return os.path.join(root, (rel or "").replace("/", os.sep))


def pixels(path):
    return Image.open(path).convert("RGB").tobytes()


def under(child, root):
    cn, rn = os.path.normcase(os.path.realpath(child)), os.path.normcase(os.path.realpath(root))
    try:
        return os.path.commonpath([cn, rn]) == rn
    except ValueError:
        return False


def code_of(r):
    return (r.get("error") or {}).get("code")


# ---------------------------------------------------------------- G1 幂等

def g1_idempotent(impl):
    """同输入同参 → 像素相等（位级只作读数）。"""
    fails = []
    root = mk_root()
    mk_src(root, "in/p.png", (40, 30))
    req = {"op": "resize", "src": "in/p.png", "dst": "o/a.png",
           "params": {"width": 20, "height": 15, "filter": "lanczos"},
           "sandbox_root": root, "caller": "g1"}
    r1 = impl(req)
    if not r1.get("ok"):
        return ["G1 首次运行失败"]
    px1 = pixels(abspath(root, r1["artifact_path"]))
    b1 = open(abspath(root, r1["artifact_path"]), "rb").read()
    r2 = impl(req)                      # 同 req 再跑一次（覆盖同名产物）
    if not r2.get("ok"):
        return ["G1 二次运行失败"]
    px2 = pixels(abspath(root, r2["artifact_path"]))
    b2 = open(abspath(root, r2["artifact_path"]), "rb").read()
    if px1 != px2:
        fails.append("G1 同输入同参两次像素不等")
    if impl is S.run:                       # 读数只记真件（变异件不污染读数）
        reading("G1 resize 像素级幂等", px1 == px2)
        reading("G1 resize 位级（信息项，非门）", b1 == b2)
    # convert 同口径
    reqc = {"op": "convert", "src": "in/p.png", "dst": "o/a.webp",
            "params": {"format": "webp"}, "sandbox_root": root, "caller": "g1"}
    c1 = impl(reqc)
    c2 = impl(reqc)
    if not (c1.get("ok") and c2.get("ok")):
        fails.append("G1 convert 两次运行失败")
    elif pixels(abspath(root, c1["artifact_path"])) != pixels(abspath(root, c2["artifact_path"])):
        fails.append("G1 convert 同输入同参两次像素不等")
    return fails


# ---------------------------------------------------------------- G2 中文路径

def g2_cjk_path(impl):
    fails = []
    root = mk_root()
    mk_src(root, os.path.join("中文目录", "看板图.png"), (48, 32))
    r = impl({"op": "resize", "src": "中文目录/看板图.png",
              "dst": "中文输出/结果_缩略.webp",
              "params": {"width": 24, "height": 16, "filter": "lanczos"},
              "sandbox_root": root, "caller": "g2"})
    if not r.get("ok"):
        return [f"G2 中文路径 resize 失败（{code_of(r)}）"]
    p = abspath(root, r["artifact_path"])
    if not os.path.isfile(p):
        fails.append("G2 中文产物未落盘")
    else:
        try:
            im = Image.open(p)
            im.load()
            if im.size != (24, 16):
                fails.append("G2 中文产物尺寸不符")
        except Exception as e:
            fails.append(f"G2 中文产物不可回读（{e!r}）")
    r2 = impl({"op": "convert", "src": "中文目录/看板图.png",
               "dst": "中文输出/转格式.png", "params": {"format": "png"},
               "sandbox_root": root, "caller": "g2"})
    if not r2.get("ok"):
        fails.append(f"G2 中文路径 convert 失败（{code_of(r2)}）")
    elif r2["meta"]["format"] != "PNG":
        fails.append("G2 中文路径 convert 格式不符")
    return fails


# ---------------------------------------------------------------- G3 错误态

def g3_error_codes(impl):
    """8 类触发样例 → 指定错误码（必需 4 + 追加 4）。"""
    fails = []
    root = mk_root()
    mk_src(root, "in/a.png", (16, 16))
    with open(os.path.join(root, "in", "bad.png"), "w", encoding="utf-8") as f:
        f.write("not an image at all")
    base = {"op": "resize", "src": "in/a.png", "dst": "o/a.png",
            "params": {"width": 8, "height": 8}, "sandbox_root": root, "caller": "g3"}
    cases = [
        ("E_NOINPUT", dict(base, src="in/missing.png"), None),
        ("E_BAD_PARAM", dict(base, params={"width": 0, "height": 8}), None),
        ("E_PATH_OUT_OF_SCOPE", dict(base, src="../escape.png"), None),
        ("E_TOOL_MISSING", dict(base), {"IMGSKILL_BACKEND": "magick",
                                        "IMGSKILL_MAGICK": os.path.join(root, "no_such_magick.exe")}),
        ("E_DECODE", dict(base, op="inspect", src="in/bad.png", params={}), None),
        # 本批起 `crop` 已实现 → 本项改用仍在范围外的 `extract`（断言强度不变）
        ("E_UNSUPPORTED_OP", dict(base, op="extract", params={}), None),
        ("E_LEVEL_DOWNGRADE", dict(base, op="generate", params={},
                                   declared_level="L0"), None),
        ("E_UNSUPPORTED_FORMAT", {"op": "convert", "src": "in/a.png",
                                  "dst": "o/x.tga", "params": {"format": "tga"},
                                  "sandbox_root": root, "caller": "g3"}, None),
    ]
    for want, req, env in cases:
        if env:
            with _env(**env):
                r = impl(req)
        else:
            r = impl(req)
        if r.get("ok") is not False:
            fails.append(f"G3 {want} 未拒绝（ok={r.get('ok')!r}）")
        elif code_of(r) != want:
            fails.append(f"G3 {want} 码不符（实得 {code_of(r)!r}）")
    # 失败也须落审计（§四「每次操作」）
    led = S.read_audit(root)
    if not any(a.get("ok") is False and a.get("error_code") for a in led):
        fails.append("G3 失败操作未落审计（error_code 缺失）")
    return fails


# ---------------------------------------------------------------- G4 审计字段

def g4_audit_fields(impl):
    fails = []
    root = mk_root()
    mk_src(root, "in/a.png", (16, 16))
    r = impl({"op": "resize", "src": "in/a.png", "dst": "o/a.png",
              "params": {"width": 8, "height": 8}, "sandbox_root": root, "caller": "g4"})
    if not r.get("ok"):
        return ["G4 前置运行失败"]
    if not os.path.isfile(S.audit_path(root)):
        return ["G4 台账未落盘"]
    if not under(S.audit_path(root), root):
        fails.append("G4 台账越出沙箱根")
    rec = S.read_audit(root)[-1]
    missing = [k for k in AUDIT_KEYS if k not in rec]
    if missing:
        fails.append("G4 缺字段: " + ",".join(missing))
    else:
        if rec.get("ok") is not True:
            fails.append("G4 成功记录 ok 字段不为 True")
        if rec.get("level") != "L0":
            fails.append("G4 level 不等于派生等级 L0")
        if rec.get("op") != "resize":
            fails.append("G4 op 字段不符")
        if len(str(rec.get("input_sha256") or "")) != 64:
            fails.append("G4 input_sha256 非 hex64")
        if rec.get("output_path") != r["artifact_path"]:
            fails.append("G4 output_path 与出参不一致")
    return fails


# ---------------------------------------------------------------- G5 结构断言

_SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "imgskill.py")

#: 禁止出现在 L1 import 面的模块（§六-G5①；本仓资格/信任/写入面）
_FORBIDDEN = ("judge", "trust", "writepipe")
#: 规则字面量拼接构造（防守卫自身被误判；沿 check_local_paths.py 做法）
_BARE_CONVERT = ("con" + "vert", "con" + "vert.exe")


def _src_text():
    with open(_SRC, "r", encoding="utf-8") as f:
        return f.read()


def check_import_face(src_text):
    """返回违规清单：① 任何 md_cg 相对 import（level>0）；② 叶子名命中禁用面。"""
    viol = []
    for n in ast.walk(ast.parse(src_text)):
        if isinstance(n, ast.ImportFrom):
            if n.level and n.level > 0:
                viol.append(f"相对 import @L{n.lineno}: .{n.module or ''}")
            for a in n.names:
                leaf = a.name.split(".")[-1].lower()
                if leaf in _FORBIDDEN:
                    viol.append(f"禁用模块导入 @L{n.lineno}: {a.name}")
        elif isinstance(n, ast.Import):
            for a in n.names:
                leaf = a.name.split(".")[-1].lower()
                if leaf in _FORBIDDEN:
                    viol.append(f"禁用模块导入 @L{n.lineno}: {a.name}")
    return viol


def check_no_bare_convert(src_text):
    """禁裸 convert 硬门（§六-G6）：argv[0]／`which` 面／`shell=True` 三条判据。

    **已知边界**（有意，非缺陷）：判据认的是 AST 里的**字面量常量**，故
    `"con" + "vert"` 这类**拼接式规避**不判。这与本仓既有约定一致——规则字面量本身
    就用拼接构造（见 `_BARE_CONVERT`），若判据也去折叠拼接，反而会把守卫自身判红；
    本门的对象是「顺手写成裸 `convert`」这一现实错法（`["convert", ...]`），
    不是有意规避者。
    """
    viol = []
    for n in ast.walk(ast.parse(src_text)):
        if isinstance(n, (ast.List, ast.Tuple)) and n.elts:
            e0 = n.elts[0]
            if isinstance(e0, ast.Constant) and isinstance(e0.value, str):
                if os.path.basename(e0.value).lower() in _BARE_CONVERT:
                    viol.append(f"argv[0] 裸 convert @L{e0.lineno}: {e0.value!r}")
        if isinstance(n, ast.Call):
            fn = n.func
            fname = (fn.attr if isinstance(fn, ast.Attribute)
                     else (fn.id if isinstance(fn, ast.Name) else ""))
            if fname == "which" and n.args:
                a = n.args[0]
                if isinstance(a, ast.Constant) and isinstance(a.value, str) \
                        and a.value.lower() in _BARE_CONVERT:
                    viol.append(f"which 裸 convert @L{a.lineno}")
            if fname in ("run", "call", "check_call", "check_output", "Popen"):
                for k in n.keywords:
                    if k.arg == "shell" and isinstance(k.value, ast.Constant) \
                            and k.value.value is True:
                        viol.append(f"subprocess shell=True @L{n.lineno}")
    return viol


def g5_in_root(impl):
    """③ 产物落点必须在调用方给的沙箱根内。"""
    root = mk_root()
    mk_src(root, "in/a.png", (16, 16))
    r = impl({"op": "resize", "src": "in/a.png", "dst": "o/a.png",
              "params": {"width": 8, "height": 8}, "sandbox_root": root, "caller": "g5"})
    if not r.get("ok"):
        return ["G5③ 前置运行失败"]
    ap = r["artifact_path"] or ""
    full = ap if os.path.isabs(ap) else os.path.join(root, ap.replace("/", os.sep))
    return [] if under(full, root) else ["G5③ 产物越出沙箱根"]


# ---------------------------------------------------------------- G7 fail-closed

def g7_fail_closed(impl):
    fails = []
    root = mk_root()
    mk_src(root, "in/a.png", (16, 16))
    base = {"op": "resize", "src": "in/a.png", "dst": "o/a.png",
            "params": {"width": 8, "height": 8}, "caller": "g7"}
    # a) 未给沙箱根（§九-#8：不设隐式默认根）
    r = impl(dict(base))
    if r.get("ok"):
        fails.append("G7 未给沙箱根却 ok=true（静默放行）")
    elif code_of(r) not in ("E_BAD_PARAM", "E_PATH_OUT_OF_SCOPE"):
        fails.append(f"G7 未给根错误码不符（{code_of(r)!r}）")
    # b) 越界路径（`..` 与绝对路径）
    # issue #84.2（2026-10-09 DSH 端）：越界样例按平台构造——原写死 Windows
    # 绝对路径，在 POSIX 上 C:/Windows/win.ini **不是绝对路径**，该腿语义随平台
    # 漂移（可能假绿）。../ 相对越界腿保留（跨平台语义一致）。
    _abs_out = "C:/Windows/win.ini" if os.name == "nt" else "/etc/hosts"
    for bad in ("../escape.png", _abs_out):
        r = impl(dict(base, src=bad, sandbox_root=root))
        if r.get("ok"):
            fails.append(f"G7 越界 src={bad} 却 ok=true")
        elif code_of(r) != "E_PATH_OUT_OF_SCOPE":
            fails.append(f"G7 越界 src={bad} 码不符（{code_of(r)!r}）")
    r = impl(dict(base, src="in/a.png", dst="../../out.png", sandbox_root=root))
    if r.get("ok") or code_of(r) != "E_PATH_OUT_OF_SCOPE":
        fails.append("G7 越界 dst 未拒（E_PATH_OUT_OF_SCOPE）")
    # c) 沙箱根不可用（不存在 → 不隐式创建）
    r = impl(dict(base, sandbox_root=os.path.join(root, "no_such_dir")))
    if r.get("ok"):
        fails.append("G7 沙箱根不存在却 ok=true")
    # d) 等级降级（declared_level 低于派生 → 拒绝）
    r = impl({"op": "generate", "src": "in/a.png", "params": {},
              "sandbox_root": root, "caller": "g7", "declared_level": "L0"})
    if r.get("ok") or code_of(r) != "E_LEVEL_DOWNGRADE":
        fails.append("G7 等级降级未拒（E_LEVEL_DOWNGRADE）")
    # e) dst 覆盖 src（§九-#7 fail-closed）
    r = impl(dict(base, src="in/a.png", dst="in/a.png", sandbox_root=root))
    if r.get("ok"):
        fails.append("G7 dst 覆盖 src 却 ok=true")
    return fails


# ---------------------------------------------------------------- 新增 op：夹具与判据
#
# 契约 §五 表内除 inspect/resize/convert 的 9 个 op（thumbnail/crop/rotate/flip/flop/
# adjust/blur/sharpen/composite/mask）逐行判据在此验收；每件的失败串**定点唯一**，
# 供下面的「定点变异自证」精确打靶。

OV_COLOR = (255, 0, 0)          # composite 的 over 恒用纯色 → 合成位置可机械断言


def mk_over(root, rel, size=(10, 10), color=OV_COLOR):
    """造纯色 over（合成位置可断言）。"""
    p = os.path.join(root, rel)
    d = os.path.dirname(p)
    if d:
        os.makedirs(d, exist_ok=True)
    Image.new("RGB", size, color).save(p)
    return p


def mk_mask(root, rel, size=(40, 30), pattern=(255, 200, 128, 0, 32)):
    """造确定性灰度 mask（逐列循环取值，便于逐像素核对 alpha）。"""
    p = os.path.join(root, rel)
    d = os.path.dirname(p)
    if d:
        os.makedirs(d, exist_ok=True)
    im = Image.new("L", size)
    px = im.load()
    for y in range(size[1]):
        for x in range(size[0]):
            px[x, y] = pattern[x % len(pattern)]
    im.save(p)
    return p


def mk_rgba(root, rel, size=(40, 30), alpha=180):
    """造带 alpha 的源（判「alpha 源」下 imgskill 不动 alpha／输出 mode 随 base）。"""
    p = os.path.join(root, rel)
    d = os.path.dirname(p)
    if d:
        os.makedirs(d, exist_ok=True)
    im = Image.new("RGBA", size)
    px = im.load()
    for y in range(size[1]):
        for x in range(size[0]):
            px[x, y] = ((12 + x * 3) % 256, (200 + y * 5) % 256,
                        (40 + (x + y) * 2) % 256, alpha)
    im.save(p)
    return p


def mk_checker(root, rel, size=(40, 30), cell=2):
    """造高频棋盘源（模糊/锐化的「效果」判据最灵敏）。"""
    p = os.path.join(root, rel)
    d = os.path.dirname(p)
    if d:
        os.makedirs(d, exist_ok=True)
    im = Image.new("L", size)
    px = im.load()
    for y in range(size[1]):
        for x in range(size[0]):
            px[x, y] = 245 if ((x // cell + y // cell) % 2) else 10
    im.save(p)
    return p


def fixture(root):
    """标准夹具：梯度源 + 纯色 over + 灰度 mask + 越界 over + 尺寸不符 mask。"""
    mk_src(root, "in/p.png", (40, 30))
    mk_over(root, "in/ov.png", (10, 10))
    mk_mask(root, "in/mk.png", (40, 30))
    mk_over(root, "in/big.png", (50, 50))
    mk_mask(root, "in/small_mask.png", (20, 20))
    return root


def rgbof(path):
    return Image.open(path).convert("RGB").tobytes()


def repo(path):
    return Image.open(path).convert("RGBA").tobytes()


def rough(path):
    """相邻像素差绝对值之和（模糊降、锐化升）。"""
    im = Image.open(path).convert("L")
    px = im.load()
    w, h = im.size
    return sum(abs(px[x + 1, y] - px[x, y]) for y in range(h) for x in range(w - 1))


def _run(impl, root, op, params, dst, src="in/p.png", **kw):
    req = {"op": op, "src": src, "dst": dst, "params": params,
           "sandbox_root": root, "caller": "xa"}
    req.update(kw)
    return impl(req)


def xa_thumbnail(impl):
    """判据：最长边 == max_edge（保持纵横比）——缩、放两个方向都判。"""
    root = fixture(mk_root())
    fails = []
    for edge, want in ((20, (20, 15)), (60, (60, 45))):
        r = _run(impl, root, "thumbnail", {"max_edge": edge}, f"o/t{edge}.png")
        if not r.get("ok"):
            fails.append(f"X-thumbnail max_edge={edge} 非 ok（{code_of(r)}）")
            continue
        got = Image.open(abspath(root, r["artifact_path"])).size   # 以**落盘产物**为准
        if got != want:
            fails.append(f"X-thumbnail 落盘产物最长边 != max_edge（max_edge={edge} 实得 {got}）")
        if (r["meta"]["width"], r["meta"]["height"]) != want:
            fails.append(f"X-thumbnail 出参 meta 与目标不符（max_edge={edge}）")
        if r["meta"]["format"] != "PNG":
            fails.append("X-thumbnail 格式不是同后缀派生（PNG）")
    if impl is S.run:
        reading("X-thumbnail 40x30 max_edge=20", "20x15（判据：最长边==max_edge）")
    return fails


def xa_crop(impl):
    """判据：产物尺寸 == 裁窗（并逐像素核对裁的是哪一块）。"""
    root = fixture(mk_root())
    r = _run(impl, root, "crop", {"x": 3, "y": 5, "width": 10, "height": 8}, "o/c.png")
    if not r.get("ok"):
        return [f"X-crop 非 ok（{code_of(r)}）"]
    fails = []
    if (r["meta"]["width"], r["meta"]["height"]) != (10, 8):
        fails.append(f"X-crop 尺寸 != 裁窗（实得 {r['meta']['width']}x{r['meta']['height']}）")
    want = Image.open(os.path.join(root, "in", "p.png")).convert("RGB").crop((3, 5, 13, 13))
    if rgbof(abspath(root, r["artifact_path"])) != want.tobytes():
        fails.append("X-crop 裁窗内容与源不对应")
    return fails


def xa_rotate(impl):
    """判据：90 倍数时尺寸对调；非直角按外接矩形（两后端取值本有差异 → 容差 3px）。"""
    root = fixture(mk_root())
    sp = os.path.join(root, "in", "p.png")
    base = Image.open(sp).convert("RGB")
    fails = []
    for deg, rot in ((90, -90), (180, 180), (-90, 90)):
        r = _run(impl, root, "rotate", {"degrees": deg}, f"o/r{deg}.png")
        if not r.get("ok"):
            fails.append(f"X-rotate {deg} 非 ok（{code_of(r)}）")
            continue
        want = base.rotate(rot, expand=True)
        if (r["meta"]["width"], r["meta"]["height"]) != want.size:
            fails.append(f"X-rotate {deg} 尺寸不对调（实得 {r['meta']['width']}x{r['meta']['height']}）")
        elif rgbof(abspath(root, r["artifact_path"])) != want.tobytes():
            fails.append(f"X-rotate {deg} 像素与「正角=顺时针」不符")
    # 非直角：外接矩形（容差 3px）
    for deg in (45, 30):
        r = _run(impl, root, "rotate", {"degrees": deg}, f"o/rn{deg}.png")
        if not r.get("ok"):
            fails.append(f"X-rotate {deg} 非 ok（{code_of(r)}）")
            continue
        c = abs(math.cos(math.radians(deg)))
        sn = abs(math.sin(math.radians(deg)))
        a = (40 * c + 30 * sn, 40 * sn + 30 * c)
        got = (r["meta"]["width"], r["meta"]["height"])
        if abs(got[0] - a[0]) > 3 or abs(got[1] - a[1]) > 3:
            fails.append(f"X-rotate {deg} 偏离外接矩形超容差（解析 {a[0]:.2f} 实得 {got}）")
        if impl is S.run and deg == 45:
            reading("X-rotate 45° 尺寸（magick 52x52 / Pillow 50x50；解析 49.50）", got)
            if Image.open(abspath(root, r["artifact_path"])).convert("RGB").getpixel((0, 0)) != (255, 255, 255):
                fails.append("X-rotate 非直角空白处不是白（背景口径漂移）")
    return fails


def xa_mirror(impl):
    """判据：与源同尺寸 + 镜像像素可断言（flip 与 flop 是两个不同 op）。"""
    root = fixture(mk_root())
    sp = os.path.join(root, "in", "p.png")
    base = Image.open(sp).convert("RGB")
    fails = []
    for op, tr, zh in (("flip", Image.Transpose.FLIP_TOP_BOTTOM, "上下"),
                       ("flop", Image.Transpose.FLIP_LEFT_RIGHT, "左右")):
        r = _run(impl, root, op, {}, f"o/{op}.png")
        if not r.get("ok"):
            fails.append(f"X-mirror {op} 非 ok（{code_of(r)}）")
            continue
        if (r["meta"]["width"], r["meta"]["height"]) != base.size:
            fails.append(f"X-mirror {op} 尺寸与源不同")
        elif rgbof(abspath(root, r["artifact_path"])) != base.transpose(tr).tobytes():
            fails.append(f"X-mirror {op} 像素非{zh}镜像")
    # 两个 op 必须给出不同结果（源自身非对称）
    a, b = abspath(root, "o/flip.png"), abspath(root, "o/flop.png")
    if os.path.isfile(a) and os.path.isfile(b) and rgbof(a) == rgbof(b):
        fails.append("X-mirror flip 与 flop 结果相同（两 op 未分离）")
    # axis 选填：同轴确认值可用
    r = _run(impl, root, "flip", {"axis": "vertical"}, "o/flip_ax.png")
    if not r.get("ok"):
        fails.append(f"X-mirror flip axis=vertical 应可用（{code_of(r)}）")
    return fails


def xa_adjust(impl):
    """判据：参数入台账 + 同参幂等（效果：亮度正负方向单调；尺寸不变）。"""
    root = fixture(mk_root())
    sp = os.path.join(root, "in", "p.png")
    base = Image.open(sp).convert("L")
    m0 = sum(base.tobytes()) / float(len(base.tobytes()))
    fails = []
    means = {}
    for b in (40, -40):
        r = _run(impl, root, "adjust", {"brightness": b, "contrast": 10, "gamma": 1.0},
                 f"o/a{b}.png")
        if not r.get("ok"):
            fails.append(f"X-adjust brightness={b} 非 ok（{code_of(r)}）")
            continue
        if (r["meta"]["width"], r["meta"]["height"]) != base.size:
            fails.append(f"X-adjust brightness={b} 尺寸变了")
        im = Image.open(abspath(root, r["artifact_path"])).convert("L")
        means[b] = sum(im.tobytes()) / float(len(im.tobytes()))
    if len(means) == 2:
        if not (means[40] > m0 > means[-40]):
            fails.append(f"X-adjust 亮度效果非单调（+40={means[40]:.1f} 源={m0:.1f} -40={means[-40]:.1f}）")
        if impl is S.run:
            reading("X-adjust 亮度均值 源/+40/-40", f"{m0:.1f}/{means[40]:.1f}/{means[-40]:.1f}")
    # gamma 单参亦可（单独入台账）
    r = _run(impl, root, "adjust", {"gamma": 2.0}, "o/ag.png")
    if not r.get("ok"):
        fails.append(f"X-adjust gamma 单参非 ok（{code_of(r)}）")
    return fails


def xa_blur(impl):
    """判据：参数入台账 + 同参幂等（效果：尺寸不变、像素变化、变平滑）。"""
    root = fixture(mk_root())
    mk_checker(root, "in/hf.png")
    r = _run(impl, root, "blur", {"sigma": 2}, "o/b.png", src="in/hf.png")
    if not r.get("ok"):
        return [f"X-blur 非 ok（{code_of(r)}）"]
    fails = []
    if (r["meta"]["width"], r["meta"]["height"]) != (40, 30):
        fails.append("X-blur 尺寸变了")
    if rgbof(abspath(root, r["artifact_path"])) == rgbof(os.path.join(root, "in", "hf.png")):
        fails.append("X-blur 像素与源相同（未生效）")
    if not rough(abspath(root, r["artifact_path"])) < rough(os.path.join(root, "in", "hf.png")):
        fails.append("X-blur 未变平滑（相邻差未降）")
    return fails


def xa_sharpen(impl):
    """判据：参数入台账 + 同参幂等（效果：尺寸不变、像素变化）。"""
    root = fixture(mk_root())
    mk_checker(root, "in/hf.png")
    r = _run(impl, root, "sharpen", {"sigma": 2}, "o/s.png", src="in/hf.png")
    if not r.get("ok"):
        return [f"X-sharpen 非 ok（{code_of(r)}）"]
    fails = []
    if (r["meta"]["width"], r["meta"]["height"]) != (40, 30):
        fails.append("X-sharpen 尺寸变了")
    if rgbof(abspath(root, r["artifact_path"])) == rgbof(os.path.join(root, "in", "hf.png")):
        fails.append("X-sharpen 像素与源相同（未生效）")
    return fails


def xa_composite(impl):
    """判据：尺寸同 base；合成位置入台账（此处按 gravity 逐像素核对落位）。"""
    root = fixture(mk_root())
    fails = []
    pos = {"northwest": (0, 0), "center": (15, 10), "southeast": (30, 20)}
    for g, (gx, gy) in pos.items():
        r = _run(impl, root, "composite",
                 {"over_path": "in/ov.png", "gravity": g, "opacity": 1.0}, f"o/k_{g}.png")
        if not r.get("ok"):
            fails.append(f"X-composite gravity={g} 非 ok（{code_of(r)}）")
            continue
        if (r["meta"]["width"], r["meta"]["height"]) != (40, 30):
            fails.append(f"X-composite gravity={g} 尺寸不等于 base")
            continue
        im = Image.open(abspath(root, r["artifact_path"])).convert("RGB")
        want_rect = [(x, y) for y in range(gy, gy + 10) for x in range(gx, gx + 10)]
        got = {(x, y) for y in range(im.size[1]) for x in range(im.size[0])
               if im.getpixel((x, y)) == OV_COLOR}
        if got != set(want_rect):
            fails.append(f"X-composite gravity={g} 落位不符（over 应在 {(gx, gy)} 起 10x10）")
    # opacity 0.5：应是 base 与 over 的近似均值（容差 3），且与不透明结果不同
    r = _run(impl, root, "composite",
             {"over_path": "in/ov.png", "gravity": "center", "opacity": 0.5}, "o/k50.png")
    if not r.get("ok"):
        fails.append(f"X-composite opacity=0.5 非 ok（{code_of(r)}）")
    else:
        base = Image.open(os.path.join(root, "in", "p.png")).convert("RGB")
        im = Image.open(abspath(root, r["artifact_path"])).convert("RGB")
        worst = 0
        for x in range(15, 25):
            for y in range(10, 20):
                bs = base.getpixel((x, y))
                got = im.getpixel((x, y))
                worst = max(worst, max(abs(got[i] - (bs[i] + OV_COLOR[i]) // 2) for i in range(3)))
        if worst > 3:
            fails.append(f"X-composite opacity=0.5 非半透明叠合（最大通道差 {worst}）")
        if impl is S.run:
            reading("X-composite opacity=0.5 相对解析均值的最大通道差", worst)
    # alpha 源：输出须随 base 保留 alpha，叠合处为 over 实色、其余保留 base alpha
    root2 = fixture(mk_root())
    mk_rgba(root2, "in/rgba.png", (40, 30), alpha=180)
    r = _run(impl, root2, "composite",
             {"over_path": "in/ov.png", "gravity": "center", "opacity": 1.0},
             "o/ka.png", src="in/rgba.png")
    if not r.get("ok"):
        fails.append(f"X-composite alpha 源非 ok（{code_of(r)}）")
    else:
        im = Image.open(abspath(root2, r["artifact_path"])).convert("RGBA")
        if "A" not in Image.open(abspath(root2, r["artifact_path"])).getbands():
            fails.append("X-composite alpha 源输出丢了 alpha 通道")
        elif im.getpixel((20, 15))[:3] != OV_COLOR or im.getpixel((0, 0))[3] != 180:
            fails.append("X-composite alpha 源叠合/保留 alpha 不符"
                         f"（叠合处 {im.getpixel((20, 15))}，域外 alpha {im.getpixel((0, 0))[3]}）")
    return fails


def xa_mask(impl):
    """判据：alpha 通道存在且可读回（并逐像素核对 alpha == mask 灰度）。"""
    root = fixture(mk_root())
    r = _run(impl, root, "mask", {"mask_path": "in/mk.png", "mode": "set"}, "o/m.png")
    if not r.get("ok"):
        return [f"X-mask 非 ok（{code_of(r)}）"]
    ap = abspath(root, r["artifact_path"])
    if "A" not in Image.open(ap).getbands():
        return ["X-mask 产物无 alpha 通道"]           # 短路：无 alpha 则值核对无意义
    fails = []
    base = Image.open(os.path.join(root, "in", "p.png")).convert("RGBA")
    base.putalpha(Image.open(os.path.join(root, "in", "mk.png")).convert("L"))
    if repo(ap) != base.tobytes():
        fails.append("X-mask alpha/像素与 mask 灰度不符")
    r2 = _run(impl, root, "mask", {"mask_path": "in/mk.png"}, "o/m2.png")
    if not r2.get("ok") or "A" not in Image.open(abspath(root, r2["artifact_path"])).getbands():
        fails.append("X-mask mode 缺省（set）非 ok 或无 alpha")
    # alpha 源：原有 alpha 被 mask 覆盖（不叠加），像素仍须逐项对得上
    root2 = fixture(mk_root())
    mk_rgba(root2, "in/rgba.png", (40, 30), alpha=180)
    r3 = _run(impl, root2, "mask", {"mask_path": "in/mk.png"}, "o/m3.png", src="in/rgba.png")
    if not r3.get("ok"):
        fails.append(f"X-mask（alpha 源）非 ok（{code_of(r3)}）")
    else:
        want = Image.open(os.path.join(root2, "in", "rgba.png")).convert("RGBA")
        want.putalpha(Image.open(os.path.join(root2, "in", "mk.png")).convert("L"))
        if repo(abspath(root2, r3["artifact_path"])) != want.tobytes():
            fails.append("X-mask（alpha 源）alpha 与 mask 灰度不符")
    return fails


# ---------------------------------------------------------------- 新增 op：台账/幂等/中文路径

#: (op, params, dst, 台账里应记的**归一参数**)——第 4 项即「参数入台账」的判据本身
LEDGER_CASES = (
    ("thumbnail", {"max_edge": 20}, "o/l_t.png", {"max_edge": 20}),
    ("crop", {"x": 3, "y": 5, "width": 10, "height": 8}, "o/l_c.png",
     {"x": 3, "y": 5, "width": 10, "height": 8}),
    ("rotate", {"degrees": 90}, "o/l_r.png", {"degrees": 90.0}),
    ("flip", {}, "o/l_f.png", {}),
    ("flop", {"axis": "horizontal"}, "o/l_fl.png", {"axis": "horizontal"}),
    ("adjust", {"brightness": 20}, "o/l_a.png",
     {"brightness": 20, "contrast": 0, "gamma": 1.0}),
    ("blur", {"sigma": 2}, "o/l_b.png", {"sigma": 2.0}),
    ("sharpen", {"sigma": 2}, "o/l_s.png", {"sigma": 2.0}),
    ("composite", {"over_path": "in/ov.png", "gravity": "southeast", "opacity": 1.0},
     "o/l_k.png", {"over_path": "in/ov.png", "gravity": "southeast", "opacity": 1.0}),
    ("mask", {"mask_path": "in/mk.png"}, "o/l_m.png",
     {"mask_path": "in/mk.png", "mode": "set"}),
)


def xb_ledger_params(impl):
    """② 参数入台账：新 op 每次成功的台账 params 必等于归一入参。"""
    root = fixture(mk_root())
    fails = []
    for op, params, dst, want in LEDGER_CASES:
        r = _run(impl, root, op, params, dst)
        if not r.get("ok"):
            fails.append(f"X-台账 {op} 前置运行失败（{code_of(r)}）")
            continue
        rec = S.read_audit(root)[-1]
        if rec.get("params") != want:
            fails.append(f"X-台账 params 与入参不符（{op}：实得 {rec.get('params')!r}）")
        elif rec.get("output_path") != r["artifact_path"] \
                or len(str(rec.get("input_sha256") or "")) != 64:
            fails.append(f"X-台账 input/output 字段不符（{op}）")
    return fails


def xc_idem(impl):
    """② 同参幂等：同 key 同参 → 复用已存产物（且像素恒等）。"""
    root = fixture(mk_root())
    fails = []
    for op, params, dst, _want in LEDGER_CASES:
        kw = {"idempotency_key": f"k_{op}"}
        r1 = _run(impl, root, op, params, dst, **kw)
        r2 = _run(impl, root, op, params, dst, **kw)
        if not (r1.get("ok") and r2.get("ok")):
            fails.append(f"X-幂等 {op} 两次运行失败")
            continue
        if not os.path.isfile(abspath(root, r1["artifact_path"])):
            fails.append(f"X-幂等 {op} 产物未落盘")
            continue
        if rgbof(abspath(root, r1["artifact_path"])) != rgbof(abspath(root, r2["artifact_path"])):
            fails.append(f"X-幂等 {op} 同输入同参两次像素不等")
        if not S.read_audit(root)[-1].get("reused_from"):
            fails.append(f"X-幂等 {op} 同 key 未复用已存产物")
    return fails


def xd_cjk_new_ops(impl):
    """③ 中文路径：新 op 至少各过一遍（源/over/mask/产物全在中文目录内）。"""
    root = mk_root()
    mk_src(root, os.path.join("中文目录", "看板图.png"), (40, 30))
    mk_over(root, os.path.join("中文目录", "水印块.png"), (10, 10))
    mk_mask(root, os.path.join("中文目录", "遮罩.png"), (40, 30))
    cjk_params = {
        "thumbnail": {"max_edge": 20},
        "crop": {"x": 1, "y": 2, "width": 8, "height": 6},
        "rotate": {"degrees": 90},
        "flip": {},
        "flop": {},
        "adjust": {"brightness": 10},
        "blur": {"sigma": 1.5},
        "sharpen": {"sigma": 1.5},
        "composite": {"over_path": "中文目录/水印块.png", "gravity": "northwest"},
        "mask": {"mask_path": "中文目录/遮罩.png"},
    }
    fails = []
    for op, params in cjk_params.items():
        dst = f"中文输出/结果_{op}.png"
        r = _run(impl, root, op, params, dst, src="中文目录/看板图.png")
        if not r.get("ok"):
            fails.append(f"X-中文路径 {op} 失败（{code_of(r)}）")
            continue
        if not os.path.isfile(abspath(root, r["artifact_path"])):
            fails.append(f"X-中文路径 {op} 产物未落盘")
    return fails


def xe_errors(impl):
    """④ 错误态：新 op 的坏参数 → 指定错误码（不靠消息文本）。"""
    root = fixture(mk_root())
    base = {"src": "in/p.png", "params": {}, "sandbox_root": root, "caller": "xe"}
    cases = (
        ("E_BAD_PARAM", dict(base, op="thumbnail", params={"max_edge": 0}, dst="o/e1.png")),
        ("E_BAD_PARAM", dict(base, op="thumbnail", params={"max_edge": "20"}, dst="o/e2.png")),
        ("E_BAD_PARAM", dict(base, op="crop", params={"x": 0, "y": 0, "width": 0, "height": 8}, dst="o/e3.png")),
        ("E_BAD_PARAM", dict(base, op="crop", params={"x": 35, "y": 0, "width": 10, "height": 8}, dst="o/e4.png")),
        ("E_BAD_PARAM", dict(base, op="crop", params={"x": -1, "y": 0, "width": 8, "height": 8}, dst="o/e5.png")),
        ("E_BAD_PARAM", dict(base, op="rotate", params={"degrees": "90"}, dst="o/e6.png")),
        ("E_BAD_PARAM", dict(base, op="rotate", params={}, dst="o/e7.png")),
        ("E_BAD_PARAM", dict(base, op="flip", params={"axis": "horizontal"}, dst="o/e8.png")),
        ("E_BAD_PARAM", dict(base, op="flop", params={"axis": "vertical"}, dst="o/e9.png")),
        ("E_BAD_PARAM", dict(base, op="adjust", params={}, dst="o/e10.png")),
        ("E_BAD_PARAM", dict(base, op="adjust", params={"brightness": 200}, dst="o/e11.png")),
        ("E_BAD_PARAM", dict(base, op="adjust", params={"gamma": 0}, dst="o/e12.png")),
        ("E_BAD_PARAM", dict(base, op="blur", params={"sigma": 0}, dst="o/e13.png")),
        ("E_BAD_PARAM", dict(base, op="blur", params={}, dst="o/e14.png")),
        ("E_BAD_PARAM", dict(base, op="sharpen", params={"sigma": -1}, dst="o/e15.png")),
        ("E_BAD_PARAM", dict(base, op="composite", params={}, dst="o/e16.png")),
        ("E_BAD_PARAM", dict(base, op="composite", params={"over_path": "in/big.png"}, dst="o/e17.png")),
        ("E_BAD_PARAM", dict(base, op="composite", params={"over_path": "in/ov.png", "gravity": "middle"}, dst="o/e18.png")),
        ("E_BAD_PARAM", dict(base, op="composite", params={"over_path": "in/ov.png", "opacity": 2}, dst="o/e19.png")),
        ("E_NOINPUT", dict(base, op="composite", params={"over_path": "in/none.png"}, dst="o/e20.png")),
        ("E_PATH_OUT_OF_SCOPE", dict(base, op="composite", params={"over_path": "../esc.png"}, dst="o/e21.png")),
        ("E_BAD_PARAM", dict(base, op="mask", params={"mask_path": "in/small_mask.png"}, dst="o/e22.png")),
        ("E_BAD_PARAM", dict(base, op="mask", params={"mask_path": "in/mk.png", "mode": "bogus"}, dst="o/e23.png")),
        ("E_UNSUPPORTED_OP", dict(base, op="mask", params={"mask_path": "in/mk.png", "mode": "mul"}, dst="o/e24.png")),
        ("E_UNSUPPORTED_FORMAT", dict(base, op="mask", params={"mask_path": "in/mk.png"}, dst="o/e25.jpg")),
        ("E_NOINPUT", dict(base, op="mask", params={"mask_path": "in/none.png"}, dst="o/e26.png")),
        ("E_PATH_OUT_OF_SCOPE", dict(base, op="mask", params={"mask_path": "../esc.png"}, dst="o/e27.png")),
    )
    fails = []
    for want, req in cases:
        r = impl(req)
        if r.get("ok") is not False:
            fails.append(f"X-错误态 {req['op']} {want} 未拒绝（ok={r.get('ok')!r}）")
        elif code_of(r) != want:
            fails.append(f"X-错误态 {req['op']} {want} 码不符（实得 {code_of(r)!r}）")
    return fails


def xf_scope(impl):
    """`E_UNSUPPORTED_OP` 收窄：只对真正未实现者返回（已实现者一律不返回它）。"""
    root = fixture(mk_root())
    fails = []
    impl_ops = {
        "inspect": ({}, "o/z_i.png"), "resize": ({"width": 8}, "o/z_z.png"),
        "convert": ({"format": "png"}, "o/z_c.png"), "thumbnail": ({"max_edge": 20}, "o/z_t.png"),
        "crop": ({"x": 0, "y": 0, "width": 8, "height": 8}, "o/z_p.png"),
        "rotate": ({"degrees": 90}, "o/z_r.png"), "flip": ({}, "o/z_f.png"),
        "flop": ({}, "o/z_l.png"), "adjust": ({"gamma": 2.0}, "o/z_a.png"),
        "blur": ({"sigma": 1}, "o/z_b.png"), "sharpen": ({"sigma": 1}, "o/z_s.png"),
        "composite": ({"over_path": "in/ov.png"}, "o/z_k.png"),
        "mask": ({"mask_path": "in/mk.png"}, "o/z_m.png"),
    }
    if set(impl_ops) != set(S.OPS_IMPL):
        fails.append(f"X-范围 已实现集与守卫覆盖不一致（{sorted(set(impl_ops) ^ set(S.OPS_IMPL))}）")
    try:
        from . import imgskill as _S
        if set(_S._OPS) != set(_S.OPS_IMPL):
            fails.append("X-范围 实现表 _OPS 与 OPS_IMPL 不一致")
    except Exception as e:                                  # pragma: no cover
        fails.append(f"X-范围 实现表自检失败（{e!r}）")
    if set(S.OPS_OUT_OF_SCOPE) & set(S.OPS_IMPL):
        fails.append("X-范围 范围外集与已实现集相交")
    for op, (params, dst) in impl_ops.items():
        r = _run(impl, root, op, params, dst)
        if r.get("ok") is False and code_of(r) == "E_UNSUPPORTED_OP":
            fails.append(f"X-范围 已实现 op {op} 仍返回 E_UNSUPPORTED_OP")
    for op in ("extract", "export", "ocr", "bg_remove", "detect",
               "generate", "i2i", "不存在的op"):
        r = _run(impl, root, op, {}, "o/z_out.png")
        if r.get("ok") is not False or code_of(r) != "E_UNSUPPORTED_OP":
            fails.append(f"X-范围 范围外 op {op} 未返回 E_UNSUPPORTED_OP（{code_of(r)!r}）")
    return fails


# ---------------------------------------------------------------- 定点变异件

def d_nonidem(req):
    """G1 退化：偶数次调用后往产物里塞噪声（非幂等）。"""
    r = S.run(req)
    d_nonidem.n = getattr(d_nonidem, "n", 0) + 1
    if r.get("ok") and r.get("artifact_path") and d_nonidem.n % 2 == 0:
        p = abspath(req["sandbox_root"], r["artifact_path"])
        im = Image.open(p).convert("RGB")
        px = im.load()
        px[0, 0] = tuple((c + 9) % 256 for c in px[0, 0])
        im.save(p)
    return r


def d_ascii_only(req):
    """G2 退化：路径含非 ASCII 即拒（中文路径不可用）。"""
    for k in ("src", "dst"):
        v = req.get(k)
        if isinstance(v, str) and any(ord(c) > 127 for c in v):
            return {"ok": False, "artifact_path": None, "asset": None, "meta": None,
                    "audit_id": None, "backend": None,
                    "error": {"code": "E_BAD_PARAM", "message": "ascii only",
                              "detail": None}}
    return S.run(req)


def d_blank_noinput(req):
    """G3 退化：E_NOINPUT 时把错误码抹成 None（不可判别）。"""
    r = S.run(req)
    if r.get("error") and r["error"].get("code") == "E_NOINPUT":
        r["error"]["code"] = None
    return r


def d_drop_env(req):
    """G4 退化：台账末行抹掉公共字段 env。"""
    r = S.run(req)
    p = S.audit_path(req["sandbox_root"])
    with open(p, "r", encoding="utf-8") as f:
        lines = [ln for ln in f.read().splitlines() if ln.strip()]
    rec = json.loads(lines[-1])
    rec.pop("env", None)
    lines[-1] = json.dumps(rec, ensure_ascii=False, sort_keys=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return r


def d_outside(req):
    """G5③ 退化：产物路径报成沙箱根之外。"""
    r = S.run(req)
    if r.get("ok"):
        r["artifact_path"] = os.path.abspath(
            os.path.join(os.path.dirname(req["sandbox_root"]), "escaped.png"))
    return r


def d_implicit_root(req):
    """G7 退化：未给沙箱根时静默顶一个隐式根（静默放行）。"""
    if not req.get("sandbox_root"):
        req = dict(req, sandbox_root=tempfile.gettempdir())
    return S.run(req)


def prove(gname, fn, degraded, expected):
    """定点变异自证：退化件跑出**恰好**预期红项（不连坐）。"""
    got = set(fn(degraded))
    ok(got == set(expected),
       f"{gname} 定点变异自证：注入退化 → 恰好打中 {sorted(expected)}（实得 {sorted(got)}）")


# ---------------------------------------------------------------- 新增 op 的定点变异件
#
# 每件只对**一个** op/参数组合退化，使新增判据的失败串**定点唯一**——证明新断言是
# 「能红」的判据而非空转（与 G1–G7 的 prove 同款做法）。

def d_thumb_noop(req):
    """X-thumbnail 退化：max_edge=20 的产物写成源图整幅（最长边不再是 max_edge）。"""
    r = S.run(req)
    if r.get("ok") and req.get("op") == "thumbnail" \
            and (req.get("params") or {}).get("max_edge") == 20:
        shutil.copyfile(abspath(req["sandbox_root"], req["src"]),
                        abspath(req["sandbox_root"], r["artifact_path"]))
    return r


def d_crop_offset(req):
    """X-crop 退化：裁错窗口（尺寸对、内容错）→ 只打中内容条。"""
    r = S.run(req)
    if r.get("ok") and req.get("op") == "crop":
        p = req["params"]
        x, y, w, h = p["x"], p["y"], p["width"], p["height"]
        Image.open(abspath(req["sandbox_root"], req["src"])).convert("RGB") \
            .crop((x + 1, y + 1, x + 1 + w, y + 1 + h)) \
            .save(abspath(req["sandbox_root"], r["artifact_path"]))
    return r


def d_rot_ccw(req):
    """X-rotate 退化：把 +90 做成**逆时针**（方向漂移）→ 只打中方向条。"""
    r = S.run(req)
    if r.get("ok") and req.get("op") == "rotate" \
            and (req.get("params") or {}).get("degrees") == 90:
        Image.open(abspath(req["sandbox_root"], req["src"])).convert("RGB") \
            .rotate(90, expand=True, fillcolor=(255, 255, 255)) \
            .save(abspath(req["sandbox_root"], r["artifact_path"]))
    return r


def d_flip_as_flop(req):
    """X-mirror 退化：flip 写成左右镜像（两 op 未分离）→ 只打中 flip 的像素条。"""
    r = S.run(req)
    if r.get("ok") and req.get("op") == "flip":
        p = abspath(req["sandbox_root"], r["artifact_path"])
        Image.open(p).transpose(Image.Transpose.FLIP_LEFT_RIGHT).save(p)
    return r


def d_ledger_param_thumb(req):
    """X-台账 退化：thumbnail 的台账 params 抹成空（同参幂等的比对键随之失效）。"""
    r = S.run(req)
    if r.get("ok") and req.get("op") == "thumbnail":
        p = S.audit_path(req["sandbox_root"])
        with open(p, "r", encoding="utf-8") as f:
            lines = [ln for ln in f.read().splitlines() if ln.strip()]
        if lines:
            rec = json.loads(lines[-1])
            rec["params"] = {}
            lines[-1] = json.dumps(rec, ensure_ascii=False, sort_keys=True)
            with open(p, "w", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
    return r


def d_mask_rgb(req):
    """X-mask 退化：产物抹掉 alpha（存成 RGB）→ 只打中「无 alpha 通道」条。"""
    r = S.run(req)
    if r.get("ok") and req.get("op") == "mask":
        p = abspath(req["sandbox_root"], r["artifact_path"])
        Image.open(p).convert("RGB").save(p)
    return r


def d_no_reuse(req):
    """X-幂等 退化：抹掉 rotate 的 idempotency_key（复用永不命中）→ 只打中复用条。"""
    if req.get("op") == "rotate":
        req = dict(req, idempotency_key=None)
    return S.run(req)


# ---------------------------------------------------------------- Y CLI 暴露面
#
# **结构防悬空**：CLI 入口必须**真能走到 impl**（`run()`），且**摘掉入口必须转红**。
# 同形先例：`test_curiosity_budget.py` C6（生产入口真走到预算门）、`test_gain_gate.py`
# 的生产路径断言。判据一律以**子进程跑真 CLI**（`-m md_cg.imgskill`）为准——不靠同进程
# 内 `cli_main()`，否则「入口命令真的可跑」这条根本没被打到。

_CLI_MAIN = ("-m", "md_cg.imgskill")
#: `__main__` 入口钩子锚点（须在源码里**恰好** 1 处；缺/重 → 判红）
_CLI_ENTRY_ANCHOR = 'if __name__ == "__main__":'
#: `run()` 出参的键面（CLI 出参须逐项在场）
_CLI_FIELDS = ("ok", "artifact_path", "asset", "meta", "audit_id", "backend", "error")
#: 仓根（`_SRC` == `<仓根>/md_cg/imgskill.py`）——Y1i 用它显式指定子进程 cwd
_CLI_REPO = os.path.dirname(os.path.dirname(_SRC))
#: 仓根相对路径、且在仓内**确实存在**——Y1i① 用它判「路径根锚定而非 cwd 锚定」
_CLI_REPO_REL = "md_cg/imgskill.py"


def _cli_src_text():
    with open(_SRC, "r", encoding="utf-8") as f:
        return f.read()


def _cli_probe(inv, *args, env=None, cwd=None):
    """子进程跑 CLI，返回 `(rc, 出参 dict|None, stdout, stderr)`。

    `inv` = `("-m", "md_cg.imgskill")`（真件）或 `("<变异件路径>",)`（变异件以脚本跑）。
    子进程统一 argv 列表 + 显式 UTF-8（纪律 15；不拼 shell 串）。
    `cwd` 缺省 `None` = 继承；**显式给**时用于「路径是否按 cwd 解析」类判据（Y1i）。
    """
    e = dict(os.environ)
    e["PYTHONUTF8"] = "1"
    if env:
        e.update(env)
    cp = subprocess.run([sys.executable, "-X", "utf8"] + list(inv) + list(args),
                        shell=False, capture_output=True, encoding="utf-8",
                        errors="replace", timeout=180, env=e, cwd=cwd)
    obj = None
    lines = [ln for ln in (cp.stdout or "").strip().splitlines() if ln.strip()]
    if lines:
        try:
            obj = json.loads(lines[-1])
        except ValueError:
            obj = None
    return cp.returncode, obj, (cp.stdout or ""), (cp.stderr or "")


def _cli_ok(rc, obj):
    """CLI 判据谓词（真件与变异件**共用**，故可作定点变异的打靶对象）。

    判据：rc==0 且 stdout 是可解析 JSON 且出参键面齐且 `ok=true`。
    """
    return (rc == 0 and isinstance(obj, dict)
            and set(_CLI_FIELDS) <= set(obj) and obj.get("ok") is True)


def _cli_subcommands():
    """CLI 已注册的子命令名集（从解析器结构读，不硬编码）。"""
    for a in S.build_parser()._actions:
        if a.__class__.__name__ == "_SubParsersAction":
            return set(a.choices)
    return set()


def ya_cli_reaches_impl(_impl):
    """Y1 暴露面落地：`--help` 列 op；inspect/resize/convert 子进程真跑到 `run()`。"""
    fails = []
    root = mk_root()
    mk_src(root, "in/p.png", (40, 30))

    # Y1a `--help` 列全部已实现 op 且 rc=0
    rc, _obj, out, err = _cli_probe(_CLI_MAIN, "--help")
    if rc != 0 or not out.strip():
        fails.append(f"Y1 CLI --help 非 rc=0 或无输出（rc={rc}；{err.strip()[:120]}）")
    else:
        miss = [op for op in S.OPS_IMPL if op not in out]
        if miss:
            fails.append(f"Y1 CLI --help 未列 op：{miss}")

    # Y1b/Y1c inspect：rc=0、字段齐、且读数与库调用**逐项一致**（同一实现路径的证据）
    lib = S.run({"op": "inspect", "src": "in/p.png", "sandbox_root": root,
                 "caller": "y-lib"})
    n_before = len(S.read_audit(root))
    rc, obj, out, err = _cli_probe(_CLI_MAIN, "inspect", "in/p.png", "--root", root)
    if not _cli_ok(rc, obj):
        fails.append(f"Y1 CLI inspect 子进程未过判据（rc={rc}；{err.strip()[:120]}）")
    else:
        if not isinstance(obj.get("meta"), dict) \
                or {"format", "width", "height", "sha256"} - set(obj["meta"]):
            fails.append(f"Y1 CLI inspect meta 字段不齐（{obj.get('meta')!r}）")
        elif obj["meta"] != lib.get("meta"):
            fails.append("Y1 CLI inspect 读数与库 run() 不一致（疑两条实现路径）")
        if len(S.read_audit(root)) != n_before + 1:
            fails.append("Y1 CLI inspect 未落审计台账（子进程未走 run()）")

    # Y1d resize：产物落盘且尺寸 == 参数要求（width=20 → 20x15 保持纵横比）
    rc, obj, out, err = _cli_probe(_CLI_MAIN, "resize", "in/p.png",
                                   "--width", "20", "--dst", "o/cli_r.png",
                                   "--root", root)
    if not _cli_ok(rc, obj):
        fails.append(f"Y1 CLI resize 子进程未过判据（rc={rc}；{err.strip()[:120]}）")
    elif Image.open(abspath(root, obj["artifact_path"])).size != (20, 15):
        fails.append(f"Y1 CLI resize 产物尺寸不符（{obj['artifact_path']}）")

    # Y1e convert：产物格式 == WEBP
    rc, obj, out, err = _cli_probe(_CLI_MAIN, "convert", "in/p.png",
                                   "--format", "webp", "--dst", "o/cli_c.webp",
                                   "--root", root)
    if not _cli_ok(rc, obj):
        fails.append(f"Y1 CLI convert 子进程未过判据（rc={rc}；{err.strip()[:120]}）")
    elif (obj.get("meta") or {}).get("format") != "WEBP":
        fails.append(f"Y1 CLI convert 格式不符（{(obj.get('meta') or {}).get('format')!r}）")

    # Y1f 未给 --root：fail-closed（rc=1、E_BAD_PARAM）——CLI 没绕开 run() 的判据
    rc, obj, out, err = _cli_probe(_CLI_MAIN, "inspect", "in/p.png")
    code = (obj or {}).get("error", {}).get("code") if isinstance(obj, dict) else None
    if rc != 1 or not isinstance(obj, dict) or obj.get("ok") is not False \
            or code != S.E_BAD_PARAM:
        fails.append(f"Y1 CLI 未给 --root 未 fail-closed（rc={rc}；code={code!r}）")

    # Y1g op 面三处一致：_CLI_OPS 键集 == OPS_IMPL == 解析器子命令集
    if set(S._CLI_OPS) != set(S.OPS_IMPL) or _cli_subcommands() != set(S.OPS_IMPL):
        fails.append("Y1 CLI op 面与 OPS_IMPL 不一致"
                     f"（_CLI_OPS={sorted(S._CLI_OPS)} 子命令={sorted(_cli_subcommands())}）")

    # Y1h 范围外 op **在 CLI 上**走用法错 rc=2（库面 run() 才是 E_UNSUPPORTED_OP）。
    #     该差异契约 §12.2 显式登记——此处用测试钉住，防「登记了却无人测」的漂移。
    oos = S.OPS_OUT_OF_SCOPE[0]
    rc, obj, out, err = _cli_probe(_CLI_MAIN, oos, "in/p.png", "--root", root)
    if rc != 2:
        fails.append(f"Y1 CLI 范围外 op（{oos}）未走 argparse 用法错 rc=2（rc={rc}）"
                     "——§12.2 登记的差异未钉住")

    # Y1i 路径口径（编排侧亲跑暴露，已写进 --help 与契约 §12.6）：路径一律相对沙箱根解析。
    #     ① 仓内**确实存在**的仓根相对路径（子进程 cwd = 仓根，故它按 cwd 真能找到）→ 仍须
    #        `E_NOINPUT`——这正是「根锚定、非 cwd 锚定」的可判形态；若日后有人给解析加 cwd
    #        兜底（破坏 §九-#8），此例会变成能找到文件而转红。
    #     ② 根外绝对路径 → `E_PATH_OUT_OF_SCOPE`（越界闸在先）。
    rc, obj, out, err = _cli_probe(_CLI_MAIN, "inspect", _CLI_REPO_REL,
                                   "--root", root, cwd=_CLI_REPO)
    c1 = ((obj or {}).get("error") or {}).get("code")
    if rc != 1 or c1 != S.E_NOINPUT:
        fails.append(f"Y1 CLI 仓根相对路径未按「根」解析（rc={rc}；code={c1!r}，"
                     "期望 E_NOINPUT——路径须根锚定、不得 cwd 兜底）")
    rc, obj, out, err = _cli_probe(_CLI_MAIN, "inspect", _SRC, "--root", root)
    c2 = ((obj or {}).get("error") or {}).get("code")
    if rc != 1 or c2 != S.E_PATH_OUT_OF_SCOPE:
        fails.append(f"Y1 CLI 根外绝对路径未越界拒绝（rc={rc}；code={c2!r}，"
                     "期望 E_PATH_OUT_OF_SCOPE）")
    return fails


def _write_mutant_no_entry():
    """把 `imgskill.py` 的 `__main__` 入口块**摘掉**，写成一个自足临时模块。

    该模块零 `md_cg` 相对 import（G5① 已断言），故可直接以脚本跑——「入口被摘」= 跑
    起来不再产生任何 CLI 行为（无出参），正是「悬空」的形态。
    """
    lines = _cli_src_text().splitlines(keepends=True)
    idx = [i for i, ln in enumerate(lines) if ln.strip().startswith(_CLI_ENTRY_ANCHOR)]
    d = tempfile.mkdtemp(prefix="imgskill_mut_")
    _ROOTS.append(d)
    p = os.path.join(d, "imgskill_noentry.py")
    with open(p, "w", encoding="utf-8") as f:
        f.write("".join(lines[:idx[0]] if idx else lines))
    return p, len(idx)


def yb_entry_off_red():
    """Y2 结构防悬空：锚点在位 + 真件为绿 + **摘掉入口恰好转红**（定点变异自证）。"""
    root = mk_root()
    mk_src(root, "in/p.png", (40, 30))
    mutant, n_anchor = _write_mutant_no_entry()
    ok(n_anchor == 1, f"Y2 结构锚点：`{_CLI_ENTRY_ANCHOR}` 在 imgskill.py 恰好 1 处"
                      f"（实得 {n_anchor}）")
    real = _cli_ok(*_cli_probe(_CLI_MAIN, "inspect", "in/p.png",
                               "--root", root)[:2])
    ok(real, "Y2 真件 CLI（入口在位）判据为绿")
    got = _cli_ok(*_cli_probe((mutant,), "inspect", "in/p.png",
                              "--root", root)[:2])
    ok((not got) and real,
       f"Y2 结构防悬空变异：摘掉 `__main__` 入口 → CLI 判据转红（真件绿={real} "
       f"变异件绿={got}）——同一判据，入口摘掉即失判")


# ---------------------------------------------------------------- 主流程

def main():
    b = S.resolve_backend()
    reading("后端路由", b[0])
    reading("后端版本", b[2])
    reading("降级留痕", b[3])
    real = S.run

    # ---------- G1 ----------
    f = g1_idempotent(real)
    ok(not f, f"G1 幂等（像素级门）：同输入同参 → 逐像素相等 [{f}]")
    prove("G1", g1_idempotent, d_nonidem, {"G1 同输入同参两次像素不等"})

    # ---------- G2 ----------
    f = g2_cjk_path(real)
    ok(not f, f"G2 中文路径（目录+文件名）resize/convert 全链可用 [{f}]")
    prove("G2", g2_cjk_path, d_ascii_only,
          {"G2 中文路径 resize 失败（E_BAD_PARAM）"})

    # ---------- G3 ----------
    f = g3_error_codes(real)
    ok(not f, f"G3 错误态可判别：8 类 → 指定错误码（必需 4 类已含）[{f}]")
    prove("G3", g3_error_codes, d_blank_noinput,
          {"G3 E_NOINPUT 码不符（实得 None）"})

    # ---------- G4 ----------
    f = g4_audit_fields(real)
    ok(not f, f"G4 审计字段齐（§4.1 全在场）[{f}]")
    prove("G4", g4_audit_fields, d_drop_env, {"G4 缺字段: env"})

    # ---------- G5 ----------
    src = _src_text()
    vi = check_import_face(src)
    ok(not vi, f"G5① imgskill 源码 import 面零 md_cg 依赖、不含 judge/trust/writepipe [{vi}]")
    # 附加读数（**非门**，据实报）：运行期模块图的禁用面来自**包 `__init__.py`**
    # 的连带（`mdcg→…→trust`），不是 imgskill 自身的 import——本仓任一同族模块皆然。
    forb = sorted(m for m in sys.modules
                  if m.startswith("md_cg") and m.rsplit(".", 1)[-1].lower() in _FORBIDDEN)
    reading("G5① 运行期连带载入的禁用面（来自包 __init__，非 imgskill import）", forb)
    vb = check_no_bare_convert(src)
    ok(not vb, f"G5①/G6 imgskill 源码无裸 convert／无 shell=True [{vb}]")
    # G6 守卫源码自身不被误判（负样例零命中）
    guard_src = open(os.path.abspath(__file__), "r", encoding="utf-8").read()
    ok(not check_no_bare_convert(guard_src),
       "G6 自检：守卫源码自身不被误判（负样例零命中）")
    f = g5_in_root(real)
    ok(not f, f"G5③ 产物落点必在调用方给的沙箱根内 [{f}]")
    prove("G5③", g5_in_root, d_outside, {"G5③ 产物越出沙箱根"})
    # 定点变异（源码面）：注入 `from . import trust` → 恰好打中预期红项
    mutated_import = src + "\nfrom . import trust\n"
    hits = check_import_face(mutated_import)
    ok(len(hits) == 2 and any("相对 import" in h for h in hits)
       and any("trust" in h for h in hits),
       f"G5① 定点变异自证：注入 `from . import trust` → 恰好打中 2 项（相对 import + 禁用模块）；"
       f"实得 {hits}")

    # ---------- G6 ----------
    # 定点变异（源码面）：注入裸 convert argv[0] → 恰好打中
    bad_line = 'subprocess.run(["' + _BARE_CONVERT[0] + '", a, b])'
    mut = src + "\n" + bad_line + "\n"
    hits = check_no_bare_convert(mut)
    ok(len(hits) == 1 and hits[0].startswith("argv[0] 裸 convert"),
       f"G6 定点变异自证：注入裸 convert argv[0] → 恰好打中 1 项（实得 {hits}）")
    # 正样例：合法 magick 调用不得被误判
    good_line = 'subprocess.run([exe, "-strip", dst])'
    ok(not check_no_bare_convert(good_line + "\n"),
       "G6 正样例：`[exe, \"-strip\", dst]` 不被误判")

    # ---------- G7 ----------
    f = g7_fail_closed(real)
    ok(not f, f"G7 fail-closed：未给根／越界／等级降级／覆 src → 一律拒绝 [{f}]")
    prove("G7", g7_fail_closed, d_implicit_root,
          {"G7 未给根错误码不符（'E_NOINPUT'）"})

    # ---------- X 新增 9 op：逐行验收判据（§五） ----------
    f = xa_thumbnail(real)
    ok(not f, f"X-thumbnail 验收：最长边 == max_edge（缩/放两向、纵横比保持）[{f}]")
    prove("X-thumbnail", xa_thumbnail, d_thumb_noop,
          {"X-thumbnail 落盘产物最长边 != max_edge（max_edge=20 实得 (40, 30)）"})

    f = xa_crop(real)
    ok(not f, f"X-crop 验收：产物尺寸 == 裁窗 且内容对应 [{f}]")
    prove("X-crop", xa_crop, d_crop_offset, {"X-crop 裁窗内容与源不对应"})

    f = xa_rotate(real)
    ok(not f, f"X-rotate 验收：90 倍数尺寸对调 + 正角顺时针 + 非直角外接矩形 [{f}]")
    prove("X-rotate", xa_rotate, d_rot_ccw, {"X-rotate 90 像素与「正角=顺时针」不符"})

    f = xa_mirror(real)
    ok(not f, f"X-mirror 验收：flip/flop 与源同尺寸且镜像像素可断言 [{f}]")
    prove("X-mirror", xa_mirror, d_flip_as_flop, {"X-mirror flip 像素非上下镜像"})

    f = xa_adjust(real)
    ok(not f, f"X-adjust 验收：参数入台账 + 同参幂等（亮度方向单调）[{f}]")

    f = xa_blur(real)
    ok(not f, f"X-blur 验收：参数入台账 + 同参幂等（变平滑）[{f}]")

    f = xa_sharpen(real)
    ok(not f, f"X-sharpen 验收：参数入台账 + 同参幂等（像素变化）[{f}]")

    f = xa_composite(real)
    ok(not f, f"X-composite 验收：尺寸同 base + 合成位置（gravity 落位/半透明）[{f}]")

    f = xa_mask(real)
    ok(not f, f"X-mask 验收：alpha 通道存在且可读回（逐像素对 mask）[{f}]")
    prove("X-mask", xa_mask, d_mask_rgb, {"X-mask 产物无 alpha 通道"})

    # ---------- X 台账参数 / 同参幂等 ----------
    f = xb_ledger_params(real)
    ok(not f, f"X-台账 参数入台账：9 op 的 params 归一值逐项在场 [{f}]")
    prove("X-台账", xb_ledger_params, d_ledger_param_thumb,
          {"X-台账 params 与入参不符（thumbnail：实得 {}）"})

    f = xc_idem(real)
    ok(not f, f"X-幂等 同参幂等：同 key 复用已存产物 + 像素恒等 [{f}]")
    prove("X-幂等", xc_idem, d_no_reuse, {"X-幂等 rotate 同 key 未复用已存产物"})

    # ---------- X 中文路径 ----------
    f = xd_cjk_new_ops(real)
    ok(not f, f"X-中文路径：9 op 全链（源/over/mask/产物均中文名）可用 [{f}]")

    # ---------- X 错误态 ----------
    f = xe_errors(real)
    ok(not f, f"X-错误态：新 op 坏参数 → 指定错误码（27 例）[{f}]")

    # ---------- X 范围收窄 ----------
    f = xf_scope(real)
    ok(not f, f"X-范围 E_UNSUPPORTED_OP 收窄：只对真正未实现者返回 [{f}]")

    # ---------- Y CLI 暴露面（结构防悬空） ----------
    f = ya_cli_reaches_impl(real)
    ok(not f, f"Y1 CLI 暴露面：子进程跑 -m md_cg.imgskill 真走到 run()"
              f"（inspect/resize/convert 落盘读数齐）[{f}]")
    yb_entry_off_red()

    print(f"\nimgskill: {PASS} passed, {FAIL} failed")
    for k, v in READINGS:
        print(f"  [读数] {k}: {v}")
    if FAILS:
        for x in FAILS:
            print(f"  - {x}")
    return 1 if FAIL else 0


def _cleanup():
    for r in _ROOTS:
        shutil.rmtree(r, ignore_errors=True)


if __name__ == "__main__":
    try:
        rc = main()
    finally:
        _cleanup()
    raise SystemExit(rc)
