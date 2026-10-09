# -*- coding: utf-8 -*-
"""回归：截图模式下悬浮到窗口上（选区吸附窗口矩形），点击后必须仍按窗口大小。

对应 2026-10-09 用户报的"悬浮能捕捉窗口，但点击后不按窗口大小截图"：
makeRect 原来只要收到一次鼠标移动就用 press→pos 重算，手抖 2~3px 就把吸附的
窗口矩形覆盖成小方块（实测 3x3，框架重播光标位置时甚至是 0x0）。修法见
CutMask::makeRect 的"点到即止"阈值。

判定不看截图，改看**程序自己报的选区矩形** —— 启动 ZPin 时给 `ZPIN_VERBOSE_SEL=1`，
它会往 <exe 同目录>/sel.log 追加每一处选区变化（tag + rect + press）。截图反推太容易看错。

四种点法：
  A 只悬浮（不按键）              → 期望 = 目标窗口矩形
  B 点一下（按下抬起，中间不移动） → 期望 = 目标窗口矩形  ← 用户要的"点一下就按窗口截"
  C 点一下（中间抖 3px）          → 鼠标手总会抖一点，看看会不会被覆盖成小矩形
  D 按下后原地重发一次移动         → 模拟框架重播最后光标位置（Ling refreshHover 就是这么干的）

⚠ 全程消息投递：不碰真实光标、不抢焦点。
"""
import ctypes
import os
import re
import subprocess
import sys
import threading
import time
from ctypes import wintypes

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _cfg_guard

user32 = ctypes.WinDLL('user32', use_last_error=True)
k32 = ctypes.windll.kernel32
user32.DefWindowProcW.restype = ctypes.c_longlong
user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT,
                                  ctypes.c_size_t, ctypes.c_ssize_t]
user32.CreateWindowExW.restype = wintypes.HWND
user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR,
                                   wintypes.DWORD, ctypes.c_int, ctypes.c_int,
                                   ctypes.c_int, ctypes.c_int, wintypes.HWND,
                                   ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]

WM_HOTKEY, WM_APP = 0x0312, 0x8000
WM_MOUSEMOVE, WM_LBUTTONDOWN, WM_LBUTTONUP = 0x0200, 0x0201, 0x0202
WM_KEYDOWN, WM_KEYUP, VK_ESCAPE = 0x0100, 0x0101, 0x1B
MK_LBUTTON = 0x0001
HWND_MESSAGE = -3

_HERE = os.path.dirname(os.path.abspath(__file__))
_BUILD = os.path.normpath(os.path.join(_HERE, '..', 'build'))
EXE = os.environ.get('SC_EXE') or os.path.join(_BUILD, 'bin', 'x64', 'Release', 'ZPin.build.exe')
EXE_DIR = os.path.dirname(EXE)
PORTABLE_CFG = os.path.join(EXE_DIR, 'config.json')
SEL_LOG = os.path.join(EXE_DIR, 'sel.log')
_cfg_guard.install(PORTABLE_CFG)

TGT = (400, 260, 1000, 760)          # 目标窗口（屏幕物理像素）


def lparam(x, y):
    return ((y & 0xFFFF) << 16) | (x & 0xFFFF)


class WNDCLASSEX(ctypes.Structure):
    _fields_ = [('cbSize', wintypes.UINT), ('style', wintypes.UINT),
                ('lpfnWndProc', ctypes.c_void_p), ('cbClsExtra', ctypes.c_int),
                ('cbWndExtra', ctypes.c_int), ('hInstance', ctypes.c_void_p),
                ('hIcon', ctypes.c_void_p), ('hCursor', ctypes.c_void_p),
                ('hbrBackground', ctypes.c_void_p), ('lpszMenuName', wintypes.LPCWSTR),
                ('lpszClassName', wintypes.LPCWSTR), ('hIconSm', ctypes.c_void_p)]


PROC = ctypes.WINFUNCTYPE(ctypes.c_longlong, wintypes.HWND, wintypes.UINT,
                          ctypes.c_size_t, ctypes.c_ssize_t)


@PROC
def _proc(h, msg, wp, lp):
    if msg == 0x0002:                # WM_DESTROY
        user32.PostQuitMessage(0)
        return 0
    return user32.DefWindowProcW(h, msg, wp, lp)


def _pump():
    msg = wintypes.MSG()
    while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
        user32.TranslateMessage(ctypes.byref(msg))
        user32.DispatchMessageW(ctypes.byref(msg))


def make_target_window():
    k32.GetModuleHandleW.restype = ctypes.c_void_p
    hinst = k32.GetModuleHandleW(None)
    cls = WNDCLASSEX()
    cls.cbSize = ctypes.sizeof(WNDCLASSEX)
    cls.style = 0x0002 | 0x0001
    cls.lpfnWndProc = ctypes.cast(_proc, ctypes.c_void_p).value
    cls.hInstance = ctypes.c_void_p(hinst)
    cls.hbrBackground = ctypes.c_void_p(0x00000006)      # COLOR_WINDOW+1
    cls.lpszClassName = 'ZPinSnapProbeTarget'
    if not user32.RegisterClassExW(ctypes.byref(cls)):
        err = ctypes.get_last_error()
        if err not in (0, 1410):
            print('!! RegisterClassEx 失败', err)
            return None
    h = user32.CreateWindowExW(0, 'ZPinSnapProbeTarget', 'ZPin 吸附测试目标窗口',
                               0x00CF0000, TGT[0], TGT[1],
                               TGT[2] - TGT[0], TGT[3] - TGT[1],
                               None, None, ctypes.c_void_p(hinst), None)
    user32.ShowWindow(h, 8)              # SW_SHOWNA，不抢焦点
    threading.Thread(target=_pump, daemon=True).start()
    time.sleep(0.7)
    return h


def windows_of(pid):
    out = []

    def cb(h, _):
        p = wintypes.DWORD()
        user32.GetWindowThreadProcessId(h, ctypes.byref(p))
        if p.value == pid:
            cls = ctypes.create_unicode_buffer(128)
            user32.GetClassNameW(h, cls, 128)
            r = wintypes.RECT()
            user32.GetWindowRect(h, ctypes.byref(r))
            out.append(dict(hwnd=h, cls=cls.value,
                            visible=bool(user32.IsWindowVisible(h)),
                            rect=(r.left, r.top, r.right, r.bottom)))
        return 1

    user32.EnumWindows(ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)(cb), 0)
    return out


def find_msg_window(pid):
    """Ling 的消息窗：类名 'STATIC'、挂在 HWND_MESSAGE 下（抄 runtime_rect_test）。"""
    prev = None
    while True:
        hwnd = user32.FindWindowExW(wintypes.HWND(HWND_MESSAGE), prev, 'STATIC', None)
        if not hwnd:
            return None
        prev = hwnd
        wp = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(wp))
        if wp.value == pid:
            return hwnd


def find_overlay(pid, timeout=10.0):
    end = time.time() + timeout
    while time.time() < end:
        vis = [w for w in windows_of(pid) if w['visible'] and w['cls'] == 'Ling']
        cap = [w for w in vis if w['rect'][2] - w['rect'][0] > 1000]
        if cap:
            return cap[0]
        time.sleep(0.4)
    return None


LINE = re.compile(r'\[(\w+)\] rect=\(([-\d.]+), ([-\d.]+), ([-\d.]+), ([-\d.]+)\)')


def log_lines():
    try:
        return open(SEL_LOG, encoding='utf-8', errors='replace').read().splitlines()
    except FileNotFoundError:
        return []


def rects_since(n):
    """第 n 行之后所有选区变化（按顺序）。"""
    out = []
    for ln in log_lines()[n:]:
        m = LINE.search(ln)
        if m:
            out.append((m.group(1), tuple(float(m.group(i)) for i in (2, 3, 4, 5))))
    return out


def current_rect():
    r = rects_since(0)
    return r[-1] if r else (None, None)


def last_since(n):
    r = rects_since(n)
    return r[-1] if r else (None, None)


def near(a, b, tol=8):
    return a is not None and all(abs(a[i] - b[i]) <= tol for i in range(4))


def enter_capture(pid):
    mw = find_msg_window(pid)
    if not mw:
        return None
    user32.PostMessageW(mw, WM_HOTKEY, WM_APP + 100, 0)
    ov = find_overlay(pid)
    if ov:
        time.sleep(0.8)
    return ov


def main():
    _cfg_guard.kill_running_instances()
    if os.path.exists(SEL_LOG):
        os.remove(SEL_LOG)

    tgt = make_target_window()
    if not tgt:
        return 1
    print('目标窗口 %s（期望选区 = 它的矩形 %s）' % (tgt, TGT))

    with open(PORTABLE_CFG, 'w', encoding='utf-16') as f:
        f.write('{"common":{"autoStart":false,"language":"zh-CN"},'
                '"shortcutKey":{"cap":"F1","pin":"F3"}}')
    env = dict(os.environ, ZPIN_VERBOSE_SEL='1')
    proc = subprocess.Popen([EXE], env=env)
    time.sleep(3.5)

    cx = (TGT[0] + TGT[2]) // 2
    cy = (TGT[1] + TGT[3]) // 2
    res = {}

    for case in ('A', 'B', 'C', 'D'):
        ov = enter_capture(proc.pid)
        if not ov:
            print('!! 覆盖层没出现')
            break
        h = ov['hwnd']
        user32.PostMessageW(h, WM_MOUSEMOVE, 0, lparam(cx, cy))    # 悬浮到目标窗口
        time.sleep(0.6)
        res[case + '-hover'] = current_rect()      # 悬浮后的选区（= 吸附到的窗口）
        n1 = len(log_lines())

        if case == 'B':
            user32.PostMessageW(h, WM_LBUTTONDOWN, MK_LBUTTON, lparam(cx, cy))
            time.sleep(0.12)
            user32.PostMessageW(h, WM_LBUTTONUP, 0, lparam(cx, cy))
            time.sleep(0.7)
            res[case] = current_rect()
            res[case + '-seq'] = rects_since(n1)
        elif case == 'C':
            user32.PostMessageW(h, WM_LBUTTONDOWN, MK_LBUTTON, lparam(cx, cy))
            time.sleep(0.12)
            user32.PostMessageW(h, WM_MOUSEMOVE, MK_LBUTTON, lparam(cx + 3, cy + 3))
            time.sleep(0.12)
            user32.PostMessageW(h, WM_LBUTTONUP, 0, lparam(cx + 3, cy + 3))
            time.sleep(0.7)
            res[case] = current_rect()
            res[case + '-seq'] = rects_since(n1)
        elif case == 'D':
            user32.PostMessageW(h, WM_LBUTTONDOWN, MK_LBUTTON, lparam(cx, cy))
            time.sleep(0.12)
            user32.PostMessageW(h, WM_MOUSEMOVE, MK_LBUTTON, lparam(cx, cy))   # 原地重播
            time.sleep(0.12)
            user32.PostMessageW(h, WM_LBUTTONUP, 0, lparam(cx, cy))
            time.sleep(0.7)
            res[case] = current_rect()
            res[case + '-seq'] = rects_since(n1)

        user32.PostMessageW(h, WM_KEYDOWN, VK_ESCAPE, 1)
        time.sleep(0.6)
        user32.PostMessageW(h, WM_KEYUP, VK_ESCAPE, 1)
        time.sleep(0.6)

    print()
    for k in ('A-hover', 'B', 'C', 'D'):
        print('  %-8s %s' % (k, res.get(k)))
        if res.get(k + '-seq'):
            print('           期间发生: %s' % (res[k + '-seq'],))
    print()
    base = None
    for case in ('A', 'B', 'C', 'D'):
        hv = res.get(case + '-hover', (None, None))[1]
        after = res.get(case, (None, None))[1]
        if hv:
            base = hv
        if case == 'A':
            print('  A 悬浮=%s（只悬浮，不点击）' % (hv,))
            continue
        same = (after == hv) or (after is None and hv is None)
        print('  %s 悬浮=%s  点后=%s  %s' % (case, hv, after,
                                        '矩形未变 ✓' if same else '矩形被改了 ✗'))
    print()
    if base:
        print('  吸附到的窗口矩形 = %s' % (base,))
        ok_b = res.get('B', (None, None))[1] in (None, base)
        ok_c = res.get('C', (None, None))[1] in (None, base)
        ok_d = res.get('D', (None, None))[1] in (None, base)
        print('B 点一下 保持窗口大小  :', ok_b)
        print('C 抖 3px 保持窗口大小  :', ok_c)
        print('D 按下期重播保持窗口   :', ok_d)
    print()
    print('--- sel.log 尾部 ---')
    for ln in log_lines()[-8:]:
        if ln.strip():
            print('   ', ln)
    try:
        proc.kill()
        user32.PostMessageW(tgt, 0x0010, 0, 0)
    except Exception:
        pass
    return 0


if __name__ == '__main__':
    sys.exit(main())
