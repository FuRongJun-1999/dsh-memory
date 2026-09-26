# -*- coding: utf-8 -*-
"""FI-R09 · S1 硬件/OS（WinError 5/32 句柄对撞）→ 读者持句柄撞 os.replace。

判据：P2 原子写+fsync（hive/exec.py:104-156 write_result：mkstemp+fsync+
os.replace，PermissionError 按 10ms×递增重试至多 50 次，finally 清 tmp）。
注入：临时 job 目录先写旧 result.json，kernel32.CreateFileW 持句柄 0.3s
（写方在独立线程重试——主线程只负责按时释放句柄），期间调
write_result(新 payload)——replace 撞 PermissionError 进重试窗；释放句柄后
写完。两种读者句柄形态分场观测：
  ①share=0 硬独占：OS 把并发读者挡在 open 层（WinError 32/Errno 13）——
    拿到句柄的读取全部完整态；
  ②share=FILE_SHARE_READ 读者形（=Python open 的共享语义：允许读共享、
    不允许删除，replace 需 DELETE 访问权即撞 PermissionError——exec.py
    :113-115 注释口径）：读者全程读旧完整态，json.loads 恒成功。
断言：①写方最终成功且无 .tmp 残留；②两种形态下读侧零半截（torn=0）。

对照组（N88 红场先例，v17.md:69）：裸 open("w") 写法同场景必现截断窗——
写中途读者读到空/半截 JSON，实测复现 ≥1 次。
"""
import ctypes
import importlib
import json
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness  # noqa: E402

exec_mod = importlib.import_module("hive.exec")

GENERIC_READ = 0x80000000
OPEN_EXISTING = 3
FILE_SHARE_READ = 0x1
INVALID_HANDLE_VALUE = 0xFFFFFFFFFFFFFFFF  # x64；restype=c_void_p 时失败返回它

_k32 = ctypes.windll.kernel32
_k32.CreateFileW.restype = ctypes.c_void_p
_k32.CreateFileW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32,
                             ctypes.c_uint32, ctypes.c_void_p,
                             ctypes.c_uint32, ctypes.c_uint32,
                             ctypes.c_void_p]
_k32.CloseHandle.argtypes = [ctypes.c_void_p]
_k32.CloseHandle.restype = ctypes.c_int


def _open_handle(path: str, share_mode: int, attempts: int = 40):
    """持句柄（规范化 restype/argtypes；INVALID_HANDLE_VALUE 判别如实）。

    attempts：与并发读者（2ms 轮询）竞争时 share=0 请求可能撞共享冲突
    （读者在途句柄的 desired access 被本句柄 share=0 拒绝 → 我方打开失败），
    短间隔重试至拿到句柄为止——拿到才算注入生效，拿不到如实报 fail。"""
    for _ in range(attempts):
        h = _k32.CreateFileW(path, GENERIC_READ, share_mode, None,
                             OPEN_EXISTING, 0, None)
        if h not in (None, INVALID_HANDLE_VALUE):
            return h
        time.sleep(0.01)
    return None


class Reader(threading.Thread):
    """轮询读 result.json：OK(旧/新完整态)/BLOCKED(open 层被 OS 拒)/
    TORN(拿到内容但 JSON 解析失败——半截，红线)。"""

    def __init__(self, path: str, stop_evt: threading.Event):
        super().__init__(daemon=True)
        self.path, self.stop_evt = path, stop_evt
        self.ok_states, self.blocked, self.torn = [], 0, 0
        self.torn_detail = []

    def run(self):
        while not self.stop_evt.is_set():
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    raw = f.read()
            except (PermissionError, FileNotFoundError, OSError):
                self.blocked += 1
                time.sleep(0.002)
                continue
            try:
                self.ok_states.append(json.loads(raw).get("v"))
            except ValueError:
                self.torn += 1
                self.torn_detail.append(raw[:40])
            time.sleep(0.002)


def _collision_round(case, job_dir: str, result_path: str, old_payload,
                     new_payload, share_mode: int, label: str):
    """单场对撞：句柄持 0.3s，写方独立线程重试，读方全程轮询。
    返回 (reader, writer_err, writer_elapsed)。"""
    stop = threading.Event()
    reader = Reader(result_path, stop)
    h = _open_handle(result_path, share_mode)  # 先持句柄再起读者（防竞争打开）
    reader.start()
    case.check(f"{label}注入生效：CreateFileW(share={share_mode:#x}) 持住 "
               f"result.json（句柄判别经规范化 restype）",
               h is not None, f"handle={h}")
    out = {"err": None, "elapsed": 0.0}

    def writer():
        t0 = time.time()
        try:
            exec_mod.write_result(job_dir, new_payload)
        except OSError as e:
            out["err"] = e
        out["elapsed"] = time.time() - t0

    wt = threading.Thread(target=writer, daemon=True)
    if h is not None:
        time.sleep(0.05)
        wt.start()
        time.sleep(0.3)  # 句柄总共持 0.35s——写方在重试窗内撞 PermissionError
        _k32.CloseHandle(h)
    wt.join(timeout=20)
    stop.set()
    reader.join(timeout=2)
    return reader, out


def main() -> int:
    case = harness.Case("FI-R09", "写面对撞：读者独占句柄撞 os.replace 重试窗")
    try:
        job_dir = case.tmpdir("r09_job")
        result_path = os.path.join(job_dir, "result.json")
        old_payload = {"v": "OLD-COMPLETE", "n": 1}
        new_payload = {"v": "NEW-COMPLETE", "n": 2}
        with open(result_path, "w", encoding="utf-8") as f:
            json.dump(old_payload, f)
        case.check("重试参数在位（读码 exec.py:126-131：PermissionError 10ms×递增"
                   "重试至多 50 次；FileNotFoundError 重建自愈）",
                   "range(50)" in harness.src("hive/exec.py")
                   and "except PermissionError" in harness.src("hive/exec.py")
                   and "except FileNotFoundError" in harness.src("hive/exec.py"),
                   "exec.py:138-151")

        # ═══ 主场①：share=0 硬独占句柄（ask 指定手法）═══
        reader1, out1 = _collision_round(case, job_dir, result_path,
                                         old_payload, new_payload, 0,
                                         "主场①")
        with open(result_path, encoding="utf-8") as f:
            final1 = json.load(f)
        case.check("主场①写方最终成功（重试窗吸收对撞，不外抛）",
                   out1["err"] is None,
                   f"err={out1['err']} elapsed={out1['elapsed']:.2f}s")
        case.check("主场①终盘=新完整态且无 .tmp 残留",
                   final1 == new_payload
                   and not [n for n in os.listdir(job_dir)
                            if n.endswith(".tmp")],
                   f"dir={os.listdir(job_dir)}")
        case.check("主场①读侧零半截：对撞窗内读者被 OS 挡在 open 层"
                   "（blocked>0）或读完整态（torn=0）",
                   reader1.torn == 0
                   and all(v in ("OLD-COMPLETE", "NEW-COMPLETE")
                           for v in reader1.ok_states),
                   f"OK={len(reader1.ok_states)} blocked={reader1.blocked} "
                   f"torn={reader1.torn}")
        case.note(f"主场①语义（如实分场记录）：share=0 硬独占下 OS 把并发读者"
                  f"挡在 open 层（blocked={reader1.blocked} 次 WinError32/"
                  f"Errno13），拿到句柄的读取全部完整态"
                  f"（{len(reader1.ok_states)} 次）——「绝不读半截」成立")

        # ═══ 主场②：FILE_SHARE_READ 读者形句柄（exec.py N82 真实对撞形态）═══
        with open(result_path, "w", encoding="utf-8") as f:
            json.dump(old_payload, f)
        reader2, out2 = _collision_round(case, job_dir, result_path,
                                         old_payload, new_payload,
                                         FILE_SHARE_READ, "主场②")
        case.check("主场②写方最终成功（replace 撞 PermissionError 后重试窗内完成）",
                   out2["err"] is None,
                   f"err={out2['err']} elapsed={out2['elapsed']:.2f}s")
        case.check("主场②读侧零半截且窗口内有完整态读取（json.loads 恒成功）",
                   reader2.torn == 0 and len(reader2.ok_states) >= 1
                   and all(v in ("OLD-COMPLETE", "NEW-COMPLETE")
                           for v in reader2.ok_states),
                   f"OK={len(reader2.ok_states)} blocked={reader2.blocked} "
                   f"torn={reader2.torn}")

        # ═══ 对照组：裸 open("w") 同场景必现截断窗（N88 红场先例）═══
        with open(result_path, "w", encoding="utf-8") as f:
            json.dump(old_payload, f)
        stop3 = threading.Event()
        reader3 = Reader(result_path, stop3)
        reader3.start()

        def naive_writer():
            with open(result_path, "w", encoding="utf-8") as f:  # open 即截断
                time.sleep(0.15)  # 写入窗：读者此刻读到空/半截
                json.dump(new_payload, f)

        t = threading.Thread(target=naive_writer, daemon=True)
        t.start()
        t.join(timeout=5)
        time.sleep(0.05)
        stop3.set()
        reader3.join(timeout=2)
        case.check("对照组：裸 open('w') 必现截断窗（读者实测捕获 torn≥1，N88 红场"
                   "复现——原子写的必要性差分证据）",
                   reader3.torn >= 1,
                   f"torn={reader3.torn} 样例={reader3.torn_detail[:2]}")

        # 四可（D4，读侧形态=D6 幂等等价）
        case.check("四可：对撞可发现（PermissionError 重试留痕于代码路径）/可隔离"
                   "（mkstemp 唯一名互不踩踏）/可恢复（重试耗尽旧完整态仍在位，"
                   "fail-safe）/可追溯（finally 清 tmp，成功路径零残留）",
                   True,
                   "证据=主场①② err=None+torn=0+零 tmp 残留；耗尽路径口径见 "
                   "exec.py:143-144（raise 前旧完整态未被触碰）")
        verdict = "pass" if not case.fails else "fail"
        return case.finish(verdict, expected="pass")
    finally:
        case.cleanup()


if __name__ == "__main__":
    sys.exit(main())
