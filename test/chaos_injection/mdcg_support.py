# -*- coding: utf-8 -*-
"""mdcg 面 case 公共支撑：临时哑环境 env 注入 + 公共身份工厂。

安全边界（实验员纪律）：所有 MDCG_* 变量一律指到 case 自己的 tmpdir
（harness.Case.tmpdir 产物），MDCG_MASTER_KEY 为哑 hex——绝不触真实令牌库/
真实 serve/真实数据目录。目录名避开 Windows 保留设备名（aux/con/nul 等：
GetFullPathNameW 吞成 \\\\.\\ 设备路径致 NotADirectoryError，md_cg/datapath
.py 同款守卫在案，批次 51）。

调用约定：必须在**任何 md_cg 导入之前**调用 apply_env(d)——tokens.DEFAULT_
TOKEN_DIR / datapath 各根都在 import 时读 env。
"""
import os


def apply_env(d: str) -> None:
    """把全部 MDCG_* 环境变量钉到临时目录 d（幂等；md_cg 导入前调用）。"""
    aux = os.path.join(d, "mdcg_aux")          # 保留设备名规避：不叫 aux
    os.makedirs(aux, exist_ok=True)
    os.environ["MDCG_ROOT"] = os.path.join(d, "cgroot")
    os.environ["MDCG_DATA_ROOT"] = os.path.join(d, "data")
    os.environ["MDCG_AUX_ROOT"] = aux
    os.environ["MDCG_STATE_ROOT"] = os.path.join(d, "state")
    os.environ["MDCG_TOKEN_FILE"] = os.path.join(aux, "_tokens.json")
    os.environ["MDCG_SUSTAIN_DIR"] = os.path.join(d, "sustain")
    os.environ["MDCG_MASTER_KEY"] = "ab" * 32   # 哑主密钥（64 位 hex）


def writer_principal():
    """可写可管的哑身份（designer 权限载体，actor=fi_writer）。"""
    from md_cg.security import Principal
    return Principal(actor="fi_writer", clearance="secret",
                     can_write=True, can_admin=True, role="designer")
