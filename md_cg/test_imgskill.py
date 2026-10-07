# -*- coding: utf-8 -*-
r"""图像 Skill（`md_cg/imgskill.py`）守卫 · 契约真源 `docs/eval/图像Skill_接口契约_设计_v0.1.md` §六 + §九。

断言面（G1–G7，逐条**能红**并附**定点变异自证**：注入退化 → 恰好打中预期红项、不连坐）：

  * **G1 同输入幂等**（§九-#6 像素级门）——同输入同参两次 → **逐像素相等**
    （读回比对；**不比字节**——位级不是门，字节读数只作信息项打印）。
  * **G2 中文路径可用**（§3.5 + 摸底稿 A3）——中文目录名 + 中文文件名跑 resize+convert 全链。
  * **G3 错误态可判别**（§3.3）——造 4 类必需样例（`E_NOINPUT`／`E_BAD_PARAM`／
    `E_PATH_OUT_OF_SCOPE`／`E_TOOL_MISSING`）＋ 4 类追加（`E_DECODE`／`E_UNSUPPORTED_OP`／
    `E_LEVEL_DOWNGRADE`／`E_UNSUPPORTED_FORMAT`），断言**指定错误码**（不靠消息文本）。
  * **G4 审计字段齐**（§4.1）——成功/失败各落一行，公共字段逐项在场（缺点名清单）。
  * **G5 结构断言**（§六-G5）——① 模块 import 面零 `md_cg` 依赖、且不含 judge/trust/writepipe；
    ③ 产物落点必须在调用方给的沙箱根之内。
  * **G6 禁裸 convert 硬门**（§六-G6 + §3.5）——AST 扫 `imgskill.py`：不得以裸 `convert`
    为 argv[0]／不得 `shutil.which("convert")`／不得 `shell=True`；守卫源码自身不被误判。
  * **G7 fail-closed**（§九-#8 + §六-G7）——未给沙箱根／越界路径／等级降级 → 一律拒绝，
    **禁静默放行**（不得返回 `ok=true`）。

边界：测试与实验一律落 `tempfile` 沙箱，**不写任何在役库**；本件不改 `md_cg/` 生产逻辑。
后端无关：`imgskill` 走自动路由（`magick` 优先、Pillow 兜底）。若要压 `magick` 面，
在环境里显式给 `IMGSKILL_MAGICK=<magick 可执行体全路径>` 再跑本件——本件内**不写本机绝对路径字面量**。

运行：`python -m md_cg.test_imgskill`（退出码 0 全绿 / 1 有红）。
"""
from __future__ import annotations

import ast
import json
import os
import shutil
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
        ("E_UNSUPPORTED_OP", dict(base, op="crop", params={}), None),
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
    for bad in ("../escape.png", "C:/Windows/win.ini"):
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
