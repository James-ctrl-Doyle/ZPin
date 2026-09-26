"""录屏过程中"用户看到的是什么" —— 抓屏时带上分层窗口（Pillow 的 include_layered_windows
走 CAPTUREBLT），否则遮罩/工具条这些 WS_EX_LAYERED 的窗口根本抓不到，会误判成"屏幕正常"。

在三个时刻各抓一张：
  1) F1 刚进截图、拖完框         —— 应有暗色遮罩 + 选区里是静态底图
  2) 点了"录屏"之后（未开始录制） —— enterLiveStage 应该把静态底图撤掉、选区透出活桌面
  3) 录制进行中                  —— 选区里应该是活的桌面
"""
import _pylibs  # noqa: F401  —— 把 build/.pylibs（Pillow）挂进 sys.path
import ctypes
import os
import subprocess
import sys
import time
from ctypes import wintypes

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    pass

from PIL import ImageGrab

user32 = ctypes.WinDLL('user32', use_last_error=True)
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
LOG_DIR = os.path.join(_BUILD, 'logs')
EXE_DIR = os.path.dirname(EXE)
PORTABLE_CFG = os.path.join(EXE_DIR, 'config.json')
import _cfg_guard          # 这行文件就是 <exe 同目录>\config.json = 用户真实配置，得护栏
_cfg_guard.install(PORTABLE_CFG)
SEL = (400, 300, 1100, 900)

EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


def lparam(x, y):
    return (y << 16) | (x & 0xFFFF)


def windows_of(pid, visible=True):
    out = []

    def cb(hwnd, _):
        p = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
        if p.value == pid and (not visible or user32.IsWindowVisible(hwnd)):
            cls = ctypes.create_unicode_buffer(128)
            user32.GetClassNameW(hwnd, cls, 128)
            r = wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(r))
            out.append({'hwnd': hwnd, 'cls': cls.value,
                        'rect': (r.left, r.top, r.right - r.left, r.bottom - r.top)})
        return True

    user32.EnumWindows(EnumWindowsProc(cb), 0)
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


def grab(name):
    im = ImageGrab.grab(include_layered_windows=True).convert('RGB')
    p = os.path.join(LOG_DIR, name)
    im.save(p)
    return im, p


def drag(hwnd, x1, y1, x2, y2):
    user32.PostMessageW(hwnd, WM_MOUSEMOVE, 0, lparam(x1, y1))
    time.sleep(0.1)
    user32.PostMessageW(hwnd, WM_LBUTTONDOWN, MK_LBUTTON, lparam(x1, y1))
    for i in range(1, 5):
        user32.PostMessageW(hwnd, WM_MOUSEMOVE, MK_LBUTTON,
                            lparam(x1 + (x2 - x1) * i // 4, y1 + (y2 - y1) * i // 4))
        time.sleep(0.08)
    user32.PostMessageW(hwnd, WM_LBUTTONUP, 0, lparam(x2, y2))
    time.sleep(0.6)


def real_click(hwnd, x, y, hover=0.7):
    r = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    user32.SetCursorPos(r.left + x, r.top + y)
    time.sleep(hover)
    user32.mouse_event(0x0002, 0, 0, 0, 0)
    time.sleep(0.1)
    user32.mouse_event(0x0004, 0, 0, 0, 0)
    time.sleep(0.5)


def key(vk):
    user32.keybd_event(vk, 0, 0, 0)
    time.sleep(0.06)
    user32.keybd_event(vk, 0, 2, 0)
    time.sleep(0.3)


def diff(a, b, box):
    """两图在 box 区域里有多少像素不同"""
    x1, y1, x2, y2 = box
    pa, pb = a.load(), b.load()
    n = 0
    for y in range(y1, y2, 6):
        for x in range(x1, x2, 6):
            if sum(abs(c1 - c2) for c1, c2 in zip(pa[x, y], pb[x, y])) > 30:
                n += 1
    return n


def main():
    if os.path.exists(PORTABLE_CFG):
        os.remove(PORTABLE_CFG)
    with open(PORTABLE_CFG, 'w', encoding='utf-16') as f:
        f.write('{"common":{"autoStart":false,"language":"zh-CN"},'
                '"shortcutKey":{"cap":"F1","pin":"F3"}}')

    proc = subprocess.Popen([EXE])
    pid = proc.pid
    try:
        time.sleep(3.0)
        msgwnd = find_msg_window(pid)
        key(0x70)
        time.sleep(2.0)
        capwnd = [w for w in windows_of(pid)
                  if w['rect'][2] > 1000 or w['rect'][3] > 800][0]['hwnd']
        drag(capwnd, *SEL)
        a, pa = grab('look_1_selected.png')
        # 选区正中一小块，用来比"选区里显示的是静态图还是活桌面"
        box = ((SEL[0] + SEL[2]) // 2 - 150, (SEL[1] + SEL[3]) // 2 - 60,
               (SEL[0] + SEL[2]) // 2 + 150, (SEL[1] + SEL[3]) // 2 + 60)
        print('选区中央对比区域 =', box)

        bar = min([w for w in windows_of(pid) if w['hwnd'] != capwnd],
                  key=lambda w: w['rect'][1])
        barw, barh = bar['rect'][2], bar['rect'][3]
        w1 = (barw - 3.0) / 16
        real_click(bar['hwnd'], int(11 * w1 + 2 * 1.5 + w1 / 2), int(barh / 2))

        tb = [w for w in windows_of(pid) if w['cls'] == 'Ling' and w['hwnd'] != capwnd][0]
        unit = tb['rect'][2] / 129.0
        # 录屏工具条会挡住选区右下角一小块，抓屏时把这一块排除掉：只比选区左上部分
        box2 = (SEL[0] + 40, SEL[1] + 40, SEL[0] + 40 + 300, SEL[1] + 40 + 200)

        b, pb = grab('look_2_recordmode.png')
        print('进了录屏模式，截图窗口还在 = %s'
              % bool([w for w in windows_of(pid) if w['hwnd'] == capwnd]))

        real_click(tb['hwnd'], int((1 + 32 + 32 + 16) * unit), int(tb['rect'][3] / 2))
        time.sleep(2.0)
        c, pc = grab('look_3_recording_a.png')
        time.sleep(1.5)
        d, pd = grab('look_4_recording_b.png')

        print('抓屏结果：')
        print('  %s' % pa)
        print('  %s' % pb)
        print('  %s' % pc)
        print('  %s' % pd)
        print('选区左上区域（排除工具条）：')
        print('  1 拖完框 vs 2 录屏模式(未录制) ：%d 个采样点不同' % diff(a, b, box2))
        print('  3 录制中 vs 4 再等 1.5 秒      ：%d 个采样点不同  <<< 若为 0 说明画面是死的' % diff(c, d, box2))
        print('  1 拖完框 vs 3 录制中           ：%d 个采样点不同' % diff(a, c, box2))
    finally:
        try:
            proc.kill()
            proc.wait(timeout=5)
        except Exception:
            pass
    return 0


if __name__ == '__main__':
    sys.exit(main())
