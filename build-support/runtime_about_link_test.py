r"""设置-关于：项目链接可点、且点了真的会打开浏览器。

原来的 bug：那个按钮宽度写死 120px，而链接文字是 41 个字符 —— 文字被裁掉，
用户看到的就是"这一项坏了 / 点不了"（其实点击回调一直是好的，只是看不见可点的东西）。

验证两件事：
  1. 链接文字**完整画出来了**（从窗口位图上量蓝色像素的横向范围，和按钮尺寸比对）
  2. 点它 → 起了浏览器进程（对比点击前后的进程快照，新出现浏览器/或已有浏览器新开窗口）
     顺带把"关于"这一页截下来存图，人眼可复核

⚠ 点链接会把浏览器拉到前台，会挡住被测窗口 —— 所以**先截图、后点击**。
"""
import ctypes
import os
import subprocess
import sys
import time
from ctypes import wintypes

import _pylibs  # noqa: F401  —— 把 build/.pylibs（Pillow）挂进 sys.path

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    pass

user32 = ctypes.WinDLL('user32', use_last_error=True)
k32 = ctypes.windll.kernel32

PROC_NAME = 'ZPin.build.exe'
_HERE = os.path.dirname(os.path.abspath(__file__))
_BUILD = os.path.normpath(os.path.join(_HERE, '..', 'build'))
EXE = os.environ.get('SC_EXE') or os.path.join(_BUILD, 'bin', 'x64', 'Release', PROC_NAME)
EXE_DIR = os.path.dirname(EXE)
PORTABLE_CFG = os.path.join(EXE_DIR, 'config.json')
import _cfg_guard
_cfg_guard.install(PORTABLE_CFG)

LOG_DIR = os.path.join(_BUILD, 'logs')
SHOT = os.path.join(LOG_DIR, 'setting_about.png')
LINK_TEXT = 'github.com/James-ctrl-Doyle/ZPin'

WM_APP = 0x8000
TRAY_MSG = WM_APP + 100
WM_RBUTTONDOWN = 0x0204
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
HWND_MESSAGE = -3

# "关于"页的布局（逻辑像素）：菜单宽 160，内容区 padding 左 40 上 40；
# 版本行 39 + 分隔 1，项目行在它下面 —— 行中心 = 40 + 40 + 20
ABOUT_ROW_Y = 100.5

BROWSERS = ('chrome.exe', 'msedge.exe', 'firefox.exe', 'brave.exe', 'opera.exe')

EnumProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


def windows_of(pid, visible=True):
    out = []

    def cb(h, _):
        p = wintypes.DWORD()
        user32.GetWindowThreadProcessId(h, ctypes.byref(p))
        if p.value == pid and (not visible or user32.IsWindowVisible(h)):
            cls = ctypes.create_unicode_buffer(128)
            user32.GetClassNameW(h, cls, 128)
            title = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(h, title, 256)
            r = wintypes.RECT()
            user32.GetWindowRect(h, ctypes.byref(r))
            out.append({'hwnd': h, 'cls': cls.value, 'title': title.value,
                        'rect': (r.left, r.top, r.right - r.left, r.bottom - r.top)})
        return True

    user32.EnumWindows(EnumProc(cb), 0)
    return out


def find_msg_window(pid):
    prev = None
    while True:
        h = user32.FindWindowExW(wintypes.HWND(HWND_MESSAGE), prev, 'STATIC', None)
        if not h:
            return None
        prev = h
        p = wintypes.DWORD()
        user32.GetWindowThreadProcessId(h, ctypes.byref(p))
        if p.value == pid:
            return h


def real_click(x, y, settle=0.8):
    user32.SetCursorPos(int(x), int(y))
    time.sleep(0.2)
    user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    time.sleep(0.08)
    user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
    time.sleep(settle)


def pids_of(name):
    class PE(ctypes.Structure):
        _fields_ = [('dwSize', ctypes.c_ulong), ('cntUsage', ctypes.c_ulong), ('pid', ctypes.c_ulong),
                    ('h0', ctypes.c_void_p), ('m0', ctypes.c_ulong), ('cntThreads', ctypes.c_ulong),
                    ('parent', ctypes.c_ulong), ('pri', ctypes.c_long), ('flags', ctypes.c_ulong),
                    ('name', ctypes.c_char * 260)]
    snap = k32.CreateToolhelp32Snapshot(2, 0)
    e = PE()
    e.dwSize = ctypes.sizeof(PE)
    out = []
    if k32.Process32First(snap, ctypes.byref(e)):
        while True:
            if e.name.decode('gbk', 'replace') == name:
                out.append(e.pid)
            if not k32.Process32Next(snap, ctypes.byref(e)):
                break
    k32.CloseHandle(snap)
    return out


def all_names():
    """当前所有进程名（小写集合）。用来判断点击后有没有新进程冒出来。"""
    class PE(ctypes.Structure):
        _fields_ = [('dwSize', ctypes.c_ulong), ('cntUsage', ctypes.c_ulong), ('pid', ctypes.c_ulong),
                    ('h0', ctypes.c_void_p), ('m0', ctypes.c_ulong), ('cntThreads', ctypes.c_ulong),
                    ('parent', ctypes.c_ulong), ('pri', ctypes.c_long), ('flags', ctypes.c_ulong),
                    ('name', ctypes.c_char * 260)]
    snap = k32.CreateToolhelp32Snapshot(2, 0)
    e = PE()
    e.dwSize = ctypes.sizeof(PE)
    out = set()
    if k32.Process32First(snap, ctypes.byref(e)):
        while True:
            out.add(e.name.decode('gbk', 'replace').lower())
            if not k32.Process32Next(snap, ctypes.byref(e)):
                break
    k32.CloseHandle(snap)
    return out


def browser_pids():
    out = set()
    for b in BROWSERS:
        out |= set(pids_of(b))
    return out


def click_tray_menu(pid):
    """托盘右键 → 菜单第一项（通用设置）。菜单窗口类名 #32768。"""
    msgwnd = find_msg_window(pid)
    if not msgwnd:
        return None
    user32.SetCursorPos(900, 620)
    time.sleep(0.4)
    user32.PostMessageW(msgwnd, TRAY_MSG, 0, WM_RBUTTONDOWN)
    time.sleep(1.2)
    menu = [w for w in windows_of(pid, visible=False) if w['cls'] == '#32768']
    if not menu:
        return None
    r = menu[0]['rect']
    real_click(r[0] + 30, r[1] + 12, settle=1.0)
    for _ in range(12):
        s = [w for w in windows_of(pid) if w['cls'] == 'Ling'
             and 400 < w['rect'][2] < 1200 and w['rect'][3] > 300]
        if s:
            return s[0]
        time.sleep(0.4)
    return None


def click_menu(win, index):
    """点左侧菜单第 index 项（0 通用 / 1 快捷键 / 2 关于）。每项高 40，从 y=40 开始。"""
    L, T, W, H = win['rect']
    dpi = user32.GetDpiForWindow(win['hwnd']) / 96.0
    real_click(L + 80 * dpi, T + (40 + index * 40 + 20) * dpi, settle=1.2)


def measure_link(win):
    """从窗口位图上量那串蓝色（0x597ef7）链接文字的横向范围。

    只统计内容区（跳过左侧 160pt 宽的菜单，它选中项的底色也是同一个蓝），
    返回 (左, 右, 像素数, 图像)。这是"文字有没有画出来、有没有溢出"的硬证据。
    """
    try:
        from PIL import ImageGrab
    except Exception as e:
        return None, None, None, 'no PIL: %s' % e
    L, T, W, H = win['rect']
    dpi = user32.GetDpiForWindow(win['hwnd']) / 96.0
    top = T + (40 + 40) * dpi          # 内容区顶端
    im = ImageGrab.grab(bbox=(L, int(top), L + W, int(top + 120 * dpi)))
    im = im.convert('RGB')
    px = im.load()
    x0 = int(180 * dpi)                # 菜单宽 160，留点余量
    xs = []
    for y in range(im.height):
        for x in range(x0, im.width):
            r, g, b = px[x, y]
            # 0x597ef7 = (89,126,247)，容差放宽抗锯齿
            if abs(r - 89) < 40 and abs(g - 126) < 40 and abs(b - 247) < 40:
                xs.append(x)
    if not xs:
        return 0, 0, 0, im
    return min(xs), max(xs), len(xs), im


def main():
    with open(PORTABLE_CFG, 'w', encoding='utf-16') as f:
        f.write('{"common":{"autoStart":false,"language":"zh-CN","borderWidth":0},'
                '"shortcutKey":{"cap":"F1","pin":"F3"}}')
    os.makedirs(LOG_DIR, exist_ok=True)
    ok = True
    proc = subprocess.Popen([EXE])
    try:
        time.sleep(3.5)
        win = click_tray_menu(proc.pid)
        if not win:
            print('!! 没能打开设置窗口')
            return 1
        click_menu(win, 2)
        time.sleep(1.0)
        print('关于页已打开')

        # ---- 1. 文字有没有完整画出来、有没有溢出内容区 ----
        L, T, W, H = win['rect']
        x_lo, x_hi, count_px, im_or_err = measure_link(win)
        dpi = user32.GetDpiForWindow(win['hwnd']) / 96.0
        if x_lo is None:
            print('（量不了：%s）' % im_or_err)
        else:
            print('链接文字：x %d..%d（跨度 %d px，共 %d 像素，dpi=%.2f）'
                  % (x_lo, x_hi, x_hi - x_lo + 1, count_px, dpi))
            # ⚠ 内容区的右内边距是 20，不是 40 —— WinSetting 里那句是
            #   setPadding(20.f, 40.f, 20.f, 40.f)，参数顺序是 (left, top, right, bottom)。
            #   一开始按 40 算，得出"文字溢出 23px"的假故障，白折腾了一轮
            limit = L + W - 20 * dpi
            print('内容区右边界 x=%.0f（窗口右边 %d - 右内边距 20pt）' % (limit, L + W))
            if x_hi > limit + 2:
                print('!! 文字溢出内容区 %.0fpx' % (x_hi - limit))
                ok = False
            elif x_hi - x_lo + 1 < 160 * dpi:
                print('!! 文字跨度太小，八成被裁着')
                ok = False
            else:
                print('✔ 文字完整可见且没溢出内容区')

        if hasattr(im_or_err, 'save'):
            try:
                im_or_err.save(SHOT)
                print('（已存图 build/logs/setting_about.png）')
            except Exception as e:
                print('（存图失败：%s）' % e)

        # ---- 2. 点它，应该起浏览器 ----
        before_browsers = browser_pids()
        before_all = all_names()
        # 按钮右对齐：右内边距 40pt；按钮现在由内容撑开，右边缘就贴在 40pt 内边距上
        x = L + (680 - 40 - 30) * dpi
        y = T + ABOUT_ROW_Y * dpi
        print('点链接 (%d,%d)' % (x, y))
        real_click(x, y, settle=3.0)

        after_browsers = browser_pids()
        after_all = all_names()
        new_browsers = after_browsers - before_browsers
        new_procs = {n for n in (after_all - before_all) if n in BROWSERS}
        if new_browsers or new_procs:
            print('✔ 浏览器被拉起来了：新增进程 %s'
                  % (sorted(new_procs) or sorted('%d' % p for p in new_browsers)))
        else:
            # 浏览器本来就在跑、通过已有实例开新标签页的话不会有新进程 —— 那种情况下
            # 只能靠"注册表里默认浏览器的命令行"间接判断，这里退一步提示人工看一眼
            print('!! 没看到新的浏览器进程（浏览器已在运行时可能只是开了个新标签页，')
            print('   请人工确认浏览器里是否新开了 github.com/James-ctrl-Doyle/ZPin）')
            ok = False
    finally:
        for p in pids_of(PROC_NAME):
            h = k32.OpenProcess(1, False, p)
            if h:
                k32.TerminateProcess(h, 0)
        time.sleep(0.5)
    print()
    print('=>', '通过：关于页的项目链接文字完整、点击能打开' if ok else '**未通过**')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
