#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""「执行任务不弹终端」的可复验探针（工作纪律第 5 条：修复须可回放）。

判据（Windows）：本进程的 `GetConsoleWindow()` 所指窗口是否 `IsWindowVisible`。

经蜂巢派发本脚本时，它跑在「serve（DETACHED，自身无控制台）→ 执行器 → 本进程」链内：
  * 执行器 spawn 若**未**设 `CREATE_NO_WINDOW`，Windows 会为它新建**可见**控制台，
    本进程继承后报告 `VISIBLE=True`（即使用者看到的「弹终端」）；
  * 设了则该链一路无窗口，报告 `HWND=0 VISIBLE=False`。

复验（须先 `python hive/serve_start.py` 拉起 serve）：
    echo {"model":"cmd","user_prompt":"probe","command":["python",
          "<repo>/hive/test_console_window.py","--expect-hidden"]} | hive.exe submit -
  期望：result 内 `VISIBLE= False`，脚本退出码 0。

离线自检（在**有控制台**的终端里跑，期望 VISIBLE=True，用于确认探针本身可判窗口）：
    python hive/test_console_window.py

退出码：0 正常（或非 Windows SKIP）；3 = --expect-hidden 下**仍检测到可见控制台窗口**（缺陷复现）。
非 Windows：SKIP（unix 不存在「弹终端」这一形态）。
"""
import os
import sys


def main() -> int:
    expect_hidden = "--expect-hidden" in sys.argv[1:]
    if os.name != "nt":
        print("SKIP：非 Windows（unix 不存在「弹终端」形态）")
        return 0
    import ctypes
    k = ctypes.windll.kernel32
    u = ctypes.windll.user32
    # HWND 是指针：不显式声明 restype/argtypes 时 64 位下按 c_int 截断会误判
    k.GetConsoleWindow.restype = ctypes.c_void_p
    u.IsWindowVisible.argtypes = [ctypes.c_void_p]
    u.IsWindowVisible.restype = ctypes.c_bool

    hwnd = k.GetConsoleWindow() or 0
    visible = bool(hwnd) and bool(u.IsWindowVisible(hwnd))
    print("PID=", os.getpid(), "HWND=", hwnd, "VISIBLE=", visible)
    if expect_hidden and visible:
        print("FAIL：期望无可见控制台窗口，实得「有」——弹终端缺陷复现")
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
