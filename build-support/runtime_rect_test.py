"""验证矩形工具默认是否空心（第 2 项）。

做法：配置里不带 toolPin 段（走代码默认值）→ F1 → 框选 → 选矩形工具 → 画一个矩形
→ 直接抓屏，检查矩形内部像素：
  · 内部是形状颜色（红 #CF1322）→ 填充
  · 内部是选区里透出来的桌面原内容 → 空心
"""
import _pylibs  # noqa: F401  —— 把 build/.pylibs（Pillow）挂进 sys.path
import ctypes
import os
import subprocess
import sys
import time
from ctypes import wintypes

# 先把本进程设成 DPI 感知，否则抓屏拿到的是缩放后的坐标，和覆盖层的物理像素对不上
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    pass

user32 = ctypes.WinDLL('user32', use_last_error=True)

WM_HOTKEY = 0x0312
WM_APP = 0x8000
WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
MK_LBUTTON = 0x0001
HWND_MESSAGE = -3

_HERE = os.path.dirname(os.path.abspath(__file__))
_BUILD = os.path.normpath(os.path.join(_HERE, '..', 'build'))
# 产物路径从脚本自身位置推导（脚本在 <仓库根>/build-support/），换机器/挪目录都不用改。
# 需要指到别的 exe 时用环境变量 SC_EXE
EXE = os.environ.get('SC_EXE') or os.path.join(_BUILD, 'bin', 'x64', 'Release', 'ZPin.build.exe')
EXE_DIR = os.path.dirname(EXE)
PORTABLE_CFG = os.path.join(EXE_DIR, 'config.json')
import _cfg_guard          # 这行文件就是 <exe 同目录>\config.json = 用户真实配置，得护栏
_cfg_guard.install(PORTABLE_CFG)

SEL = (400, 300, 900, 700)
RECT = (450, 350, 700, 550)
SHAPE_COLOR = (0xCF, 0x13, 0x22)   # ToolSub::colors[0]

EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


def lparam(x, y):
    return (y << 16) | (x & 0xFFFF)


def windows_of(pid):
    found = []

    def cb(hwnd, _):
        wpid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(wpid))
        if wpid.value == pid:
            cls = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, cls, 256)
            r = wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(r))
            found.append({'hwnd': hwnd, 'cls': cls.value,
                          'visible': bool(user32.IsWindowVisible(hwnd)),
                          'rect': (r.left, r.top, r.right - r.left, r.bottom - r.top)})
        return True

    user32.EnumWindows(EnumWindowsProc(cb), 0)
    return found


def find_msg_window(pid):
    prev = None
    while True:
        hwnd = user32.FindWindowExW(wintypes.HWND(HWND_MESSAGE), prev, 'STATIC', None)
        if not hwnd:
            return None
        prev = hwnd
        wpid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(wpid))
        if wpid.value == pid:
            return hwnd


def click(hwnd, x, y):
    user32.PostMessageW(hwnd, WM_LBUTTONDOWN, MK_LBUTTON, lparam(x, y))
    time.sleep(0.12)
    user32.PostMessageW(hwnd, WM_LBUTTONUP, 0, lparam(x, y))


def drag(hwnd, x1, y1, x2, y2):
    user32.PostMessageW(hwnd, WM_MOUSEMOVE, MK_LBUTTON, lparam(x1, y1))
    time.sleep(0.1)
    user32.PostMessageW(hwnd, WM_LBUTTONDOWN, MK_LBUTTON, lparam(x1, y1))
    for i in range(1, 5):
        user32.PostMessageW(hwnd, WM_MOUSEMOVE, MK_LBUTTON,
                            lparam(x1 + (x2 - x1) * i // 4, y1 + (y2 - y1) * i // 4))
        time.sleep(0.08)
    user32.PostMessageW(hwnd, WM_LBUTTONUP, 0, lparam(x2, y2))
    time.sleep(0.5)


def main():
    if not os.path.exists(EXE):
        print('!! 找不到 exe')
        return 1
    with open(PORTABLE_CFG, 'w', encoding='utf-16') as f:
        f.write('{"common":{"autoStart":false,"language":"zh-CN"},'
                '"shortcutKey":{"cap":"F1","pin":"F3"}}')

    proc = subprocess.Popen([EXE])
    pid = proc.pid
    try:
        time.sleep(3.0)
        msgwnd = find_msg_window(pid)
        if not msgwnd:
            print('!! 没找到消息窗口（可能有别的实例在跑）')
            return 1
        user32.PostMessageW(msgwnd, WM_HOTKEY, WM_APP + 100, 0)
        time.sleep(2.0)
        vis = [w for w in windows_of(pid) if w['visible'] and w['cls'] == 'Ling']
        cap = [w for w in vis if w['rect'][2] > 1000 or w['rect'][3] > 800]
        if not cap:
            print('!! 覆盖层没出现')
            return 1
        capwnd = cap[0]['hwnd']
        origin = (cap[0]['rect'][0], cap[0]['rect'][1])
        drag(capwnd, *SEL)

        vis = [w for w in windows_of(pid) if w['visible'] and w['cls'] == 'Ling']
        bars_all = [w for w in vis if w['hwnd'] != capwnd]
        if not bars_all:
            print('!! 工具条没出来')
            return 1
        bar = min(bars_all, key=lambda w: w['rect'][1])   # 主工具条（在 ToolSub 上方）
        barw, barh = bar['rect'][2], bar['rect'][3]
        sep = 1.5
        btn_w = (barw - 2 * sep) / 17

        def btn_x(idx):
            seps = 1 if idx >= 8 else 0
            seps = 2 if idx >= 10 else seps
            return int(idx * btn_w + seps * sep + btn_w / 2)

        print('== 点矩形工具（按钮 0，x=%d，条宽 %d）==' % (btn_x(0), barw))
        click(bar['hwnd'], btn_x(0), int(barh / 2))
        time.sleep(0.8)
        n_after = len([w for w in windows_of(pid) if w['visible'] and w['cls'] == 'Ling'])
        print('   点完工具后可见 Ling 窗口 = %d（应比之前多一个 ToolSub）' % n_after)

        print('== 画矩形 %s ==' % (RECT,))
        drag(capwnd, *RECT)
    finally:
        from PIL import ImageGrab
        shot = ImageGrab.grab()
        try:
            proc.kill()
            proc.wait(timeout=5)
        except Exception:
            pass

    print('   抓屏尺寸 = %s' % (shot.size,))
    shot = shot.convert('RGB')

    def at(sx, sy):
        return shot.getpixel((sx + origin[0], sy + origin[1]))

    ref = at(SEL[0] + 30, SEL[1] + 30)                       # 选区里、矩形外
    inner = at((RECT[0] + RECT[2]) // 2, (RECT[1] + RECT[3]) // 2)
    onborder = at(RECT[0] + 1, RECT[1] + 1)
    print('   选区底图取样 %s   矩形内部 %s   矩形边框 %s' % (ref, inner, onborder))

    def dist(a, b):
        return sum((x - y) ** 2 for x, y in zip(a, b)) ** 0.5

    d_shape = dist(inner, SHAPE_COLOR)
    print('   内部到形状色 %s 的距离 = %.1f；内部到底图 %s 的距离 = %.1f'
          % (SHAPE_COLOR, d_shape, ref, dist(inner, ref)))
    if d_shape < 40:
        print('  => **矩形是填充的**（内部就是形状色）')
        return 1
    print('  => 通过：矩形是空心的（内部是底图内容，不是形状色）')
    return 0


if __name__ == '__main__':
    rc = main()
    print('\n===== 退出码 %d =====' % rc)
    sys.exit(rc)
