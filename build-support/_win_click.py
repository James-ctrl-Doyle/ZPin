r"""真实点击（SetCursorPos + mouse_event）的公共实现 + **遮挡守卫**。

⚠ 为什么需要它：真实点击打的是"屏幕该坐标处**最上层**的窗口"——
目标窗口若被别的窗口挡住，点击会送进遮挡者，目标进程**收不到任何消息**。
而 `GetWindowRect` 对遮挡窗口照样返回正确坐标（它只管几何），于是表现为
"窗口明明在、点下去没反应、配置纹丝不动"，极容易被误判成程序 bug。
（2026-10-08 ZPin 图标设置回归偶发失败的真因就是这个：设置窗口被挡在后面。）

两种点击：
  * `click_via_message(hwnd, x, y)` —— **推荐**：发消息，不碰光标、不会被遮挡，
    后台窗口照样生效（Ling 的控件是纯消息驱动的）。
  * `real_click(x, y, expect_pid=...)` —— 真实输入（SetCursorPos + mouse_event），
    只在必须走真实输入时用；带遮挡守卫，被挡住就明确返回 False。

    from _win_click import click_via_message, real_click
    click_via_message(win_hwnd, x, y)                     # 首选
    if not real_click(x, y, expect_pid=proc.pid):         # 需要真实输入时
        print('!! 目标窗口被遮挡'); return 1

守卫做的事：`WindowFromPoint` 查该点最上层窗口属于谁；不是目标进程就先把目标进程
的可见顶层窗口 `SetWindowPos(HWND_TOP)` 抬到最前（`SWP_NOACTIVATE`，不激活、不改
尺寸位置），再查一次；仍然不是 → 返回 False，由调用方明确报"被遮挡"，别让它伪装成断言失败。
"""
import ctypes
import time
from ctypes import wintypes

user32 = ctypes.WinDLL('user32', use_last_error=True)
user32.WindowFromPoint.restype = wintypes.HWND
user32.WindowFromPoint.argtypes = [wintypes.POINT]
user32.SetWindowPos.restype = wintypes.BOOL

SWP_NOSIZE, SWP_NOMOVE, SWP_NOACTIVATE = 0x0001, 0x0002, 0x0010
HWND_TOP = 0
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004

_EnumProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


def window_of_point(x, y):
    """返回 (hwnd, pid)：该屏幕坐标处最上层窗口及其进程 id。"""
    h = user32.WindowFromPoint(wintypes.POINT(int(x), int(y)))
    pid = wintypes.DWORD()
    if h:
        user32.GetWindowThreadProcessId(h, ctypes.byref(pid))
    return h, pid.value


def popups_of(pid):
    """该进程所有**可见**顶层窗口（含自绘的弹框）。"""
    out = []

    def cb(w, _):
        p = wintypes.DWORD()
        user32.GetWindowThreadProcessId(w, ctypes.byref(p))
        if p.value == pid and user32.IsWindowVisible(w):
            out.append(w)
        return 1

    user32.EnumWindows(_EnumProc(cb), 0)
    return out


def ensure_clickable(x, y, pid):
    """确保 (x,y) 处最上层窗口属于 pid；不是就把该进程的窗口抬到最前再确认一次。"""
    _h, owner = window_of_point(x, y)
    if owner == pid:
        return True
    for w in popups_of(pid):
        user32.SetWindowPos(w, HWND_TOP, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
    time.sleep(0.35)
    _h, owner = window_of_point(x, y)
    return owner == pid


def describe(hwnd):
    """给一句人话：遮挡者是谁（类名 + 标题）。"""
    if not hwnd:
        return '（空窗口）'
    cls = ctypes.create_unicode_buffer(128)
    user32.GetClassNameW(hwnd, cls, 128)
    ti = ctypes.create_unicode_buffer(256)
    user32.GetWindowTextW(hwnd, ti, 256)
    return '%s「%s」' % (cls.value, ti.value) if ti.value else cls.value


WM_MOUSEMOVE, WM_LBUTTONDOWN, WM_LBUTTONUP = 0x0200, 0x0201, 0x0202


def click_via_message(hwnd, x, y, settle=0.5):
    """用消息点击（屏幕坐标 (x,y)）：**不碰光标、也不会被遮挡**。

    Ling 的按钮是纯消息驱动的（`WM_LBUTTONDOWN/UP` → onMouseDown/onUp，
    onClick 在抬起时触发），后台窗口照样生效 —— 所以比 SetCursorPos+mouse_event
    更适合自动化：既不会因为目标窗口被别的窗口挡住而"点不动"，也不会打扰用户。

    ⚠ `WM_LBUTTONDOWN/UP`/`WM_MOUSEMOVE` 的 lParam 是**物理客户区坐标**（不是屏幕、
      也不是逻辑坐标）—— 这里自动 ScreenToClient 换算。
    """
    pt = wintypes.POINT(int(x), int(y))
    if not user32.ScreenToClient(hwnd, ctypes.byref(pt)):
        return False
    lp = ((pt.y & 0xFFFF) << 16) | (pt.x & 0xFFFF)
    user32.SendMessageW(hwnd, WM_MOUSEMOVE, 0, lp)
    time.sleep(0.05)
    user32.SendMessageW(hwnd, WM_LBUTTONDOWN, 1, lp)
    time.sleep(0.08)
    user32.SendMessageW(hwnd, WM_LBUTTONUP, 0, lp)
    time.sleep(settle)
    return True


def real_click(x, y, settle=0.6, expect_pid=None):
    """真实点击。(x,y) 是屏幕坐标；expect_pid 给了就先做遮挡守卫。

    返回 False = 被遮挡、点击没送出去（调用方应据此明确报错，别当成断言失败）。
    """
    if expect_pid is not None and not ensure_clickable(x, y, expect_pid):
        h, owner = window_of_point(x, y)
        print('!! (%.0f, %.0f) 处最上层是 %s（pid=%s），不是目标 pid=%s —— '
              '目标窗口被它挡住了，点击送不进去（把它挪开或最小化再跑）'
              % (x, y, describe(h), owner, expect_pid))
        return False
    user32.SetCursorPos(int(x), int(y))
    time.sleep(0.2)
    user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    time.sleep(0.08)
    user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
    time.sleep(settle)
    return True
