# -*- coding: utf-8 -*-
"""显式授权闸：一类动作**默认关闭**，需「本人原话 + 带名字的口令」才开；
开有过期、可随时撤回、**注入/引用内容一律不可触发**。

为什么要有它（设计来历）：
  默认关闭的东西，一旦没有明确的开启条件，它就不是门而是墙——
  「任何条件都开不了」和「谁都能开」是同一种失真。

三层（与纪律第 4 条同构：取证、不猜测、留痕）：
  ① 硬闸：开关，不是分数；不可被次数、时长、亲密度抬高
  ② 判据：三条件同时满足才开（见 match_trigger），缺一不开、且**明说没开**
  ③ 留痕：开关事件落 jsonl，**只记发生与时刻，不记内容**

不做什么：
  · 不判断「谁在说话」——这件事模块做不到，只能由调用方声明 `source`，
    未声明（或非 'user'）一律拒开（fail-closed）。**这是本模块最重要的一条边界**：
    口令最容易被记忆注入 / 引用 / 转述撞开，而模块自己识别不了，所以宁可不认。
  · 不表达、不生成任何内容；它只是闸。

口令存哪：`<root>/_gates.json`（私有，不进公开仓）。
"""
from __future__ import annotations

import io
import json
import math
import os
import re
import time

from . import fsutil as _fsutil

GATES_FILE = '_gates.json'
GATE_LOG = '_gates.jsonl'
DEFAULT_TTL = 1800.0          # 开一次 30 分钟，超时自理


def _path(root, name):
    return os.path.join(str(root), name)


def load_specs(root):
    """读私有口令表；缺失/损坏一律返回空（⇒ 任何闸都开不了，fail-closed）。"""
    try:
        with io.open(_path(root, GATES_FILE), encoding='utf-8') as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _norm(s):
    return re.sub(r'\s+', '', str(s or ''))


def match_trigger(text, spec):
    """判据：三条件同时满足才返回 (True, 说明)，否则 (False, 缺哪条)。

    spec = {'must_contain': [...], 'any_of': [...], 'exclude': [...]}
      · must_contain  全部出现（如名字）
      · any_of        至少一个（如表达欲望而不是爱意）
      · exclude       一个都不许出现（如仅表爱意的词）
    """
    t = _norm(text)
    if not t:
        return False, '空文本'
    for k in (spec.get('exclude') or []):
        if _norm(k) and _norm(k) in t:
            return False, '含排除词：%s' % k
    miss = [k for k in (spec.get('must_contain') or []) if _norm(k) and _norm(k) not in t]
    if miss:
        return False, '缺：%s' % '、'.join(miss)
    anyof = [k for k in (spec.get('any_of') or []) if _norm(k) and _norm(k) in t]
    if not anyof:
        return False, '缺欲望表达'
    return True, 'ok'


def _finite_float(val):
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        return None
    f = float(val)
    return f if math.isfinite(f) else None


def is_quoted(text):
    """粗判：引用/转述/代码块/不可信记忆标记形态。
    宁可误判成引用（不开），也不误开。"""
    t = str(text or '').strip()
    if not t:
        return True
    if 'untrusted-memory' in t.lower():
        return True
    lines = [l for l in t.splitlines() if l.strip()]
    if lines and (all(l.lstrip().startswith(('>', '|')) for l in lines)
                  or any(l.lstrip().startswith('>') for l in lines)):
        return True
    if '```' in t or '~~~' in t:
        return True
    for m in ('据说', '他说', '她说', '引用', '转载', '转述', '原文是'):
        if m in t[:40]:
            return True
    return False


def _read_state(root):
    try:
        with io.open(_path(root, '_gate_state.json'), encoding='utf-8') as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_state(root, d):
    p = _path(root, '_gate_state.json')
    _fsutil.atomic_write(p, json.dumps(d, ensure_ascii=False, indent=2))
    try:
        os.chmod(p, 0o600)
    except OSError:
        pass


def _log(root, row):
    with io.open(_path(root, GATE_LOG), 'a', encoding='utf-8', newline=chr(10)) as f:
        f.write(json.dumps(row, ensure_ascii=False) + chr(10))


def _active_window(rec, now):
    """解析 (opened, ttl, left)；任何非有限/非正/未来时钟回落 None（fail-closed）。"""
    if not isinstance(rec, dict):
        return None
    now_f = _finite_float(time.time() if now is None else now)
    opened = _finite_float(rec.get('opened_at'))
    ttl = _finite_float(rec.get('ttl'))
    if now_f is None or opened is None or ttl is None or ttl <= 0.0:
        return None
    elapsed = now_f - opened
    if not math.isfinite(elapsed) or elapsed < 0.0 or elapsed >= ttl:
        return None
    return opened, ttl, ttl - elapsed


def open_gate(root, name, text, source='', ttl=DEFAULT_TTL, now=None):
    """尝试开闸。返回 {'ok':bool,'reason':str}；**永不抛**。

    source 必须显式等于 'user'（调用方对「这是本人当轮原话」负责）；
    其它一切取值（memory / quote / relay / 空）一律拒开。
    """
    now_f = _finite_float(time.time() if now is None else now)
    if now_f is None:
        return {'ok': False, 'reason': '非法时钟值（now 须为有限数值）'}
    ttl_f = _finite_float(ttl)
    if ttl_f is None or ttl_f <= 0.0:
        return {'ok': False, 'reason': '非法 ttl（须为正有限秒数）：%r' % (ttl,)}
    spec = load_specs(root).get(str(name))
    if not isinstance(spec, dict) or not spec:
        return {'ok': False, 'reason': '未配置该闸（fail-closed）'}
    if str(source or '') != 'user':
        return {'ok': False, 'reason': '来源不是本人原话：%r' % (source,)}
    if is_quoted(text):
        return {'ok': False, 'reason': '引用/转述形态，不触发'}
    try:
        ok, why = match_trigger(text, spec)
    except Exception as exc:
        return {'ok': False, 'reason': '闸配置损坏：%s' % (type(exc).__name__,)}
    if not ok:
        return {'ok': False, 'reason': why}
    try:
        st = _read_state(root)
        st[str(name)] = {'opened_at': now_f, 'ttl': ttl_f}
        _write_state(root, st)
        _log(root, {'t': round(now_f, 1), 'gate': str(name), 'event': 'open', 'ttl': ttl_f, 'source': 'user'})
    except OSError as exc:
        return {'ok': False, 'reason': '状态落盘失败：%s' % (type(exc).__name__,)}
    return {'ok': True, 'reason': '已开', 'ttl': ttl_f}


STAMP_MARK = '开闸依据：'


# 生效条件：闸开着返回一行证据文本（以 STAMP_MARK 开头）；没开返回 None。
# 为什么是"留痕"不是"拦截"：代码拦不住一次直写，但能要求每次私密写入带上开闸证据，
# 事后由 we_time 审计核对——**没证据的私密节点可被发现**，这才是可追责的形态。
def stamp(root, name, now=None):
    now_f = _finite_float(time.time() if now is None else now)
    if now_f is None:
        return None
    rec = _read_state(root).get(str(name))
    win = _active_window(rec, now_f)
    if win is None:
        return None
    opened, ttl, _left = win
    try:
        return '%s%s / ttl %ds / at %s' % (
            STAMP_MARK, time.strftime('%Y-%m-%d %H:%M', time.localtime(opened)),
            int(ttl), time.strftime('%Y-%m-%d %H:%M', time.localtime(now_f)))
    except (OSError, OverflowError, ValueError):
        return None


# 生效条件：闸开着返回 True；否则抛 GateClosed。给"必须硬拦"的调用点用。
class GateClosed(RuntimeError):
    pass


def require(root, name, now=None):
    if not stamp(root, name, now):
        raise GateClosed('闸未开：%s（先用 open_gate 开，或走 close_gate 复核）' % name)
    return True


def close_gate(root, name, reason='', now=None):
    now_f = _finite_float(time.time() if now is None else now)
    if now_f is None:
        now_f = time.time()
    st = _read_state(root)
    if str(name) in st:
        st.pop(str(name), None)
        _write_state(root, st)
    _log(root, {'t': round(now_f, 1), 'gate': str(name), 'event': 'close', 'reason': str(reason)[:60]})
    return {'ok': True}


def is_open(root, name, now=None):
    rec = _read_state(root).get(str(name))
    return _active_window(rec, now) is not None


def state(root, now=None):
    """读数：只给「开没开 + 还剩多久」，**不回显口令**。"""
    now_f = _finite_float(time.time() if now is None else now)
    out = {}
    st = _read_state(root)
    for name in load_specs(root):
        rec = st.get(name)
        win = _active_window(rec, now_f) if now_f is not None else None
        if win is not None:
            out[name] = {'open': True, 'left_s': round(max(0.0, win[2]), 1)}
        else:
            out[name] = {'open': False, 'left_s': 0.0}
    return out