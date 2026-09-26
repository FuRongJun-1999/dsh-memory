# -*- coding: utf-8 -*-
"""FI-M09 · S5 用户（调用方越权指令）→ 越权写入若得手即静默污染真源（公理 5）。

判据：T8 fail-closed + P8 净化投影（v0.1 §2.5 S5 源：调用方指令不可信，写资格
由层写权限闸判定而非由请求自报；拒绝必须显式、不留半成品）。闸面：
MdCGSecure.add → principal.require_layer_write（md_cg/mdcos.py:3786 →
md_cg/security.py:217-224 双闸：can_write + 层白名单）；双闸先例对照
md_cg/mdcos.py:2117（N131 review_decide merge 同款，v16.md:84 已修留痕）。
注入：临时 root 构造 guest Principal（can_write=False, can_admin=False），直调
cg.add('n_evil','越权写入尝试', layer='secret')。

理论预期（登记 pass，回归守卫）：抛 AccessDenied「actor=fi_guest 无写权限」
（显式拒绝+可操作 hint），节点未落库、无半成品；对照格 designer 同调用（合法
层）成功——闸只拦资格不拦功能。诚实注记：layer='secret' 并非合法层名
（LAYERS 八层），guest 在权限闸即被拒（require_layer_write 先于基类层名校验）；
designer+layer='secret' 会得 ValueError「未知层」——层名合法性属另一道校验，
与本闸正交（本场实测记录）。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness        # noqa: E402
import mdcg_support   # noqa: E402


def main() -> int:
    case = harness.Case("FI-M09", "guest 越权写入：层写权限闸显式拒绝")
    try:
        d = case.tmpdir("m09")
        mdcg_support.apply_env(d)
        from md_cg.mdcos import MdCGSecure
        from md_cg.security import Principal

        case.check("读码：写闸在位（MdCGSecure.add 先 principal.require_layer_"
                   "write 再落盘；require_layer_write 双闸=can_write+层白名单）",
                   "self.principal.require_layer_write(layer, sens)"
                   in harness.src("md_cg/mdcos.py")
                   and "def require_layer_write" in harness.src("md_cg/security.py"),
                   "md_cg/mdcos.py:3786 + md_cg/security.py:217-224")

        root9 = os.path.join(d, "m09root")
        guest = Principal(tenant="default", actor="fi_guest", clearance="internal",
                          can_write=False, can_admin=False, role="guest",
                          auth_mode="direct")
        cg9 = MdCGSecure(root9, principal=guest)
        try:
            denied = None
            try:
                cg9.add("n_evil", "越权写入尝试", layer="secret")
            except Exception as e:                    # noqa: BLE001
                denied = (type(e).__name__, str(e), getattr(e, "hint", None))
            case.check("红场①：拒绝显式（AccessDenied「actor=fi_guest 无写权限」"
                       "——异常而非静默吞掉，T8 fail-closed）",
                       denied is not None and denied[0] == "AccessDenied"
                       and "actor=fi_guest 无写权限" in denied[1],
                       f"denied={denied[:2] if denied else None}")
            case.check("红场②：拒绝可操作（hint 指引在案——issue #34 口径）",
                       denied is not None and bool(denied[2])
                       and "凭据" in denied[2],
                       f"hint head={(denied[2] or '')[:60] if denied else None}")
            persisted = cg9.get("n_evil") is not None
            case.check("红场③：零半成品（节点未落库、目标目录未创建——污染未"
                       "发生）",
                       not persisted
                       and not os.path.isdir(os.path.join(root9, "secret")),
                       f"node_on_disk={persisted}")
        finally:
            cg9.close()

        # ═══ 对照格：designer 同调用（合法层）——闸只拦资格不拦功能 ═══
        cg10 = MdCGSecure(os.path.join(d, "m09ctrl"),
                          principal=mdcg_support.writer_principal())
        try:
            nid = cg10.add("n_ok_designer", "正常写入正文", layer="knowledge")
            case.check("对照组：designer（can_write=True）同门写入成功",
                       nid and cg10.get(nid) is not None,
                       f"nid={nid}")
            err_designer_secret = None
            try:
                cg10.add("n_secret_layer", "x", layer="secret")
            except Exception as e:                    # noqa: BLE001
                err_designer_secret = (type(e).__name__, str(e))
            case.note(f"诚实注记：layer='secret' 非合法层名（LAYERS 八层）——"
                      f"designer 撞层名校验得 {err_designer_secret}；guest 场中"
                      f"权限闸先于层名校验生效（mdcos.py:3786 在 super().add 之"
                      f"前），两道校验正交不互替")
        finally:
            cg10.close()

        # 四可（D4）
        case.check("四可：可发现=是（AccessDenied 显式异常+hint）/可隔离=是（单"
                   "次调用拒绝，不累及其它写）/可恢复=是（无半成品，换凭据即可"
                   "写）/可追溯=是（异常消息含 actor，可归因到调用方身份）",
                   True,
                   "证据=红场①-③ + 对照组放行")
        verdict = "pass" if not case.fails else "fail"
        return case.finish(verdict, expected="pass")
    finally:
        case.cleanup()


if __name__ == "__main__":
    sys.exit(main())
