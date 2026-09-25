r"""设置页（通用设置）布局自检 —— 整页各行加起来不能撑破可用高度。

窗口高 560、内容区 padding 上 40 + 下 20，各行累加超过可用高度的话，
最后一行会被裁掉或者压到关闭按钮底下。

做法：开设置页 → 截图存下来（人眼可复核）→ 再用 GetWindowRect 断言窗口尺寸仍是
680x560，并按下面的 ROWS 表核对最后一行的位置落在可视区域内。

⚠ 2026-09-22 两处更新：
  1. 行序改了 —— 管理员模式从最后一行挪到"开机自启"下面（其余依次下移）。
     ⚠ **显示顺序由 WinSettingCommon 构造函数的调用顺序决定**，不是 init*Ctrls
       的定义顺序；改那边就要同步这里的 ROWS 表和 ROW_Y 那几个常量。
  2. 管理员那块只剩一句提示了 —— setting.adminRestartTip 那行早先已删掉
     （用户嫌提示文案堆太多），ROWS 表里还留着它，会把总高度多算 20px（偏保守，
     所以一直没暴露）。现在按实际的一句算。
"""
import ctypes
import os
import subprocess
import sys
import time
from ctypes import wintypes

import _pylibs  # noqa: F401  —— 把 ext/build/.pylibs（Pillow）挂进 sys.path

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    pass

user32 = ctypes.WinDLL('user32', use_last_error=True)
gdi32 = ctypes.windll.gdi32
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
SHOT = os.path.join(LOG_DIR, 'setting_page.png')

WM_APP = 0x8000
TRAY_MSG = WM_APP + 100
WM_RBUTTONDOWN = 0x0204
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
HWND_MESSAGE = -3

# 整页各行高度累加（逻辑像素）：内容区从 y=40 开始，每行 39 + 分隔线 1；
# 带提示的行再 +20。顺序必须跟 WinSettingCommon 构造函数的调用顺序一致。
ROWS = [('autoStart', 39), ('autoStartBorder', 1),
        ('admin', 39), ('adminTip', 20), ('adminBorder', 1),
        ('gameMode', 39), ('gameModeTip', 20), ('gameModeBorder', 1),
        ('lang', 39), ('langBorder', 1),
        ('border', 39), ('borderBorder', 1),
        ('saveDir', 39), ('saveDirBorder', 1),
        ('quickSave', 39), ('quickSaveTip', 20), ('quickSaveBorder', 1),
        ('history', 39), ('historyBorder', 1),
        ('iconStyle', 39), ('iconStyleBorder', 1)]   # ← 2026-09-26 新增（最后一行）

EnumProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
MARGIN_L, MARGIN_T, MARGIN_R, MARGIN_B = 20.0, 40.0, 20.0, 20.0


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


def real_click(x, y, settle=0.6):
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


def open_setting_via_tray(pid, msgwnd):
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


def shot_window(hwnd, path=None):
    """把窗口**自身**渲染成 png。

    ⚠ 用 PrintWindow(hwnd, hdc, 2)，参数 2 = PW_RENDERFULLCONTENT：
      - 不加这个参数，D2D 渲染的窗口会得到一片空白；
      - 更关键的是**不要**改回 ImageGrab.grab()/BitBlt 桌面那一套 —— 那是抓屏幕，
        设置窗口若不在预期位置、或者上面压着别的窗口，截到的就是用户的浏览器、
        聊天记录，而且会被存成 png 留在磁盘上。（2026-09-25 之前这个脚本就是这么干的。）
    """
    from PIL import Image
    path = path or SHOT
    r = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    w, h = r.right - r.left, r.bottom - r.top
    hdc = user32.GetWindowDC(hwnd)
    mem = gdi32.CreateCompatibleDC(hdc)
    bmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
    old = gdi32.SelectObject(mem, bmp)
    user32.PrintWindow(hwnd, mem, 2)

    class BMIH(ctypes.Structure):
        _fields_ = [('biSize', wintypes.DWORD), ('biWidth', ctypes.c_long),
                    ('biHeight', ctypes.c_long), ('biPlanes', wintypes.WORD),
                    ('biBitCount', wintypes.WORD), ('biCompression', wintypes.DWORD),
                    ('biSizeImage', wintypes.DWORD), ('biXPelsPerMeter', ctypes.c_long),
                    ('biYPelsPerMeter', ctypes.c_long), ('biClrUsed', wintypes.DWORD),
                    ('biClrImportant', wintypes.DWORD)]

    bi = BMIH()
    bi.biSize = ctypes.sizeof(BMIH)
    bi.biWidth, bi.biHeight = w, -h        # 负数 = 自上而下，与 PIL 的行序一致
    bi.biPlanes, bi.biBitCount = 1, 32
    bi.biCompression = 0                   # BI_RGB
    buf = ctypes.create_string_buffer(w * h * 4)
    gdi32.GetDIBits(mem, bmp, 0, h, buf, ctypes.byref(bi), 0)

    Image.frombuffer('RGB', (w, h), buf, 'raw', 'BGRX', 0, 1).save(path)

    gdi32.SelectObject(mem, old)
    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(mem)
    user32.ReleaseDC(hwnd, hdc)
    return path


def main():
    with open(PORTABLE_CFG, 'w', encoding='utf-16') as f:
        f.write('{"common":{"autoStart":false,"language":"zh-CN","borderWidth":0},'
                '"shortcutKey":{"cap":"F1","pin":"F3"}}')
    ok = True
    proc = subprocess.Popen([EXE])
    try:
        time.sleep(3.5)
        msgwnd = find_msg_window(proc.pid)
        win = open_setting_via_tray(proc.pid, msgwnd) if msgwnd else None
        if not win:
            print('!! 没能打开设置窗口')
            return 1
        L, T, W, H = win['rect']
        dpi = user32.GetDpiForWindow(win['hwnd']) / 96.0
        print('设置窗口 rect=(%d,%d,%d,%d) dpi=%.2f' % (L, T, W, H, dpi))
        print('逻辑尺寸 %.1f x %.1f（期望 680 x 560）' % (W / dpi, H / dpi))
        if abs(H / dpi - 560) > 2 or abs(W / dpi - 680) > 2:
            print('!! 窗口尺寸不是 680x560')
            ok = False

        used = sum(h for _, h in ROWS)
        avail = 560 - MARGIN_T - MARGIN_B
        print('内容区各行合计 %.0f，可用高度 %.0f' % (used, avail))
        if used > avail:
            print('!! 内容高度超出 %.0fpx，最后一行会被压掉' % (used - avail))
            ok = False
        else:
            print('✔ 还余 %.0fpx' % (avail - used))

        # 管理员这一段的纵向范围（逻辑坐标 -> 屏幕坐标），确认它没掉到底部内边距外
        y = MARGIN_T
        for name, h in ROWS:
            if name == 'admin':
                break
            y += h
        top = T + (y - MARGIN_T) * dpi + MARGIN_T * dpi  # 相对 body 顶端
        top = T + y * dpi
        bottom = T + (y + 39 + 20) * dpi     # 行(39) + 那一句提示(20)
        print('管理员模式这一段 y=%.0f..%.0f（窗口底边 y=%d）' % (top, bottom, T + H))
        if bottom > T + H - MARGIN_B * dpi:
            print('!! 这段落到了底部内边距之外')
            ok = False

        try:
            os.makedirs(LOG_DIR, exist_ok=True)
            shot_window(win['hwnd'])
            print('（已存图 ext/build/logs/setting_page.png —— 整页，且只含窗口自身）')
        except Exception as e:
            print('（截图失败：%s）' % e)
    finally:
        for p in pids_of(PROC_NAME):
            h = k32.OpenProcess(1, False, p)
            if h:
                k32.TerminateProcess(h, 0)
        time.sleep(0.5)
    print()
    print('=>', '通过：设置页高度够用、管理员这一段完整可见' if ok else '**未通过**')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
