# -*- coding: utf-8 -*-
# DEPRECATED(shim): 迁移过渡层，下个次版本移除
"""`md_cg/audit` · 迁移过渡 shim（薄壳，**零业务逻辑**）。

真源已迁至 `md_cg/govern/audit.py`（2026-11-11「结构归位」第一阶段：治理模块从
根目录搬进治理层，`git mv` 保留历史）。**新代码请直接 import 新位置**：

    from md_cg.govern.audit import ...    # 推荐
    from md_cg.audit import ...          # 过渡期仍可用（本 shim）

为什么留 shim：`from . import audit` 的调用点散布在根目录（mcp_server /
writepipe / mdcg / mdcos / sustain / subgraph …），一次性改调用点与第二阶段
「拆巨型单体」正面相撞。shim 让「搬家」与「改调用点」解耦，下个次版本随
第二阶段一并移除。

**为什么不是一行 `from .govern.audit import *`**：星号导入**复制名字、不绑定
模块**。既有调用点里存在 `audit.default_policy_path = ...`（测试注入真源定位）
与 `audit.VERIFIERS[k] = fn`（注册表写入）这类**重新绑定/改写**——星号导入会把
它们钉在 shim 局部，真源看不到 ⇒ 注入静默失效（实测：`test_issue43` 的
`_dfl_policy` 注入失默后写入面被判 `policy_unavailable`，7 红）。本 shim 改用
PEP 562 模块级 `__getattr__` **现场取真源属性**，并对「往 shim 上重新绑定真源
已有名」**fail-loud**，不静默。

不变量（由 `md_cg/iface/_verify.py` 的 shim 台账断言钉住）：
- 本文件**不得**含业务逻辑（只有导入、转发与 `__all__`）；
- `md_cg.audit.X is md_cg.govern.audit.X`（同一对象，不复制）。
"""

from __future__ import annotations

import md_cg.govern.audit as _src

#: **元属性必须显式绑定成真源的**：模块的 `__doc__` / `__all__` 是模块自身
#: 字典里的项（PEP 562 的 `__getattr__` 对「已存在的键」根本不触发），若不覆盖，
#: `from md_cg.x import` 后读 `x.__doc__` 拿到的是本 shim 的说明。面向真源的
#: docstring 判据（如 `test_issue190` 的「模块 docstring 写明幂等口径」）因此
#: 会**恒红**。这两行把语义恢复成「模块对象就是真源的门面」。
__doc__ = _src.__doc__
__all__ = list(_src.__all__)

_REBIND_GUARD = (
    "md_cg.audit 是迁移过渡 shim（DEPRECATED），真源在 md_cg.govern.audit。"
    "对 shim 属性赋值/删除**不会**影响真源（旧写法 `md_cg.audit.x = ...` 会静默"
    "失效）。请改为 `md_cg.govern.audit.x = ...`。")


def __getattr__(name):          # PEP 562：属性转发，真实读取落在真源上
    try:
        return getattr(_src, name)
    except AttributeError:
        raise AttributeError(
            "module 'md_cg.audit' has no attribute %r（真源 md_cg.govern.audit"
            " 也没有）" % (name,)) from None


def __dir__():
    return sorted(set(globals()) | set(dir(_src)))


def __setattr__(name, value):   # 已存在的真源名：必须显式写 md_cg.govern.audit
    if hasattr(_src, name):
        raise RuntimeError(_REBIND_GUARD)
    _src.__dict__[name] = value          # 新增名同时落真源与 shim（与旧 `from . import` 同语义）
    globals()[name] = value


def __delattr__(name):
    raise RuntimeError(_REBIND_GUARD)
