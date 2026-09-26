"""验证二维码识别"没扫到"那条路的行为：不弹框、不关窗，原地显示一行提示、2 秒后消失。

屏幕上没有二维码时走的是"未识别到二维码"那条路（同样的 showTip / paintTip / 定时器），
足够验证提示机制与"不该关窗"这一点：
  点二维码按钮 -> 截图窗口还在、选区正中出现深色提示框 + 白字 -> 2.4 秒后提示消失

⚠ 2.4 这个等待值是有判别力的：提示时长是 2 秒，所以 2.4 秒时它必须已经没了；
  万一有人把时长改回 3 秒，这条用例会失败。
⚠ "识别成功"那条路（提示 2 秒后**自动退出截图状态**）由 runtime_qr_close_test.py 负责。
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

EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


def lparam(x, y):
    return (y << 16) | (x & 0xFFFF)


def windows_of(pid):
    found = []

    def cb(hwnd, _):
        wpid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(wpid))
        if wpid.value == pid:
            r = wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(r))
            found.append({'hwnd': hwnd, 'visible': bool(user32.IsWindowVisible(hwnd)),
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
    time.sleep(0.25)


def drag(hwnd, x1, y1, x2, y2):
    user32.PostMessageW(hwnd, WM_MOUSEMOVE, MK_LBUTTON, lparam(x1, y1))
    time.sleep(0.1)
    user32.PostMessageW(hwnd, WM_LBUTTONDOWN, MK_LBUTTON, lparam(x1, y1))
    for i in range(1, 5):
        user32.PostMessageW(hwnd, WM_MOUSEMOVE, MK_LBUTTON,
                            lparam(x1 + (x2 - x1) * i // 4, y1 + (y2 - y1) * i // 4))
        time.sleep(0.08)
    user32.PostMessageW(hwnd, WM_LBUTTONUP, 0, lparam(x2, y2))
    time.sleep(0.6)


def center_stats(cx, cy):
    """取选区正中的一块，返回 (平均亮度, 亮点数, 灰度列表)。
    灰度列表用来和另一时刻逐像素比变化 —— 背景明暗不定，"变亮/变暗"这种单一指标不可靠，
    但"有多少像素被改动过"是稳的"""
    from PIL import ImageGrab
    shot = ImageGrab.grab().convert('L')
    vals = []
    tot, bright = 0, 0
    for y in range(cy - 30, cy + 30):
        for x in range(cx - 90, cx + 90):
            v = shot.getpixel((x, y))
            vals.append(v)
            tot += v
            if v > 200:
                bright += 1
    return tot / len(vals), bright, vals


def changed(a, b, thr=25):
    return sum(1 for x, y in zip(a, b) if abs(x - y) > thr)


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
        vis = [w for w in windows_of(pid) if w['visible']]
        cap = [w for w in vis if w['rect'][2] > 1000 or w['rect'][3] > 800]
        if not cap:
            print('!! 覆盖层没出现')
            return 1
        capwnd = cap[0]['hwnd']
        drag(capwnd, *SEL)

        bars_all = [w for w in windows_of(pid) if w['visible'] and w['hwnd'] != capwnd]
        bar = min(bars_all, key=lambda w: w['rect'][1])
        barw, barh = bar['rect'][2], bar['rect'][3]
        sep = 1.5
        w1 = (barw - 2 * sep) / 16               # 现在共 16 个按钮
        bx = int(12 * w1 + 2 * sep + w1 / 2)     # 第 13 个 = 二维码（10 长图 11 录屏 12 二维码）

        cx = (SEL[0] + SEL[2]) // 2
        cy = (SEL[1] + SEL[3]) // 2

        before = center_stats(cx, cy)
        print('== 点二维码识别（按钮 12，x=%d）== 点之前：平均亮度 %.1f' % (bx, before[0]))
        click(bar['hwnd'], bx, int(barh / 2))
        # 采样点要离"提示消失"远一点：提示只停 2 秒，而采样本身（截屏 + 逐像素比）也要花时间。
        # 原来这里等 1.2 秒，机器一卡就整个错过提示，报出"没出现提示"的假失败。
        time.sleep(0.6)
        during = center_stats(cx, cy)
        win_alive = [w for w in windows_of(pid) if w['visible'] and w['hwnd'] == capwnd]
        print('   点之后：平均亮度 %.1f 亮点 %d；截图窗口还在 = %s'
              % (during[0], during[1], bool(win_alive)))
        time.sleep(2.4)     # 提示时长 2 秒，2.4 秒时它必须已经消失了
        after = center_stats(cx, cy)
        win_alive2 = [w for w in windows_of(pid) if w['visible'] and w['hwnd'] == capwnd]
        print('   2.4 秒后：平均亮度 %.1f 亮点 %d；截图窗口还在 = %s'
              % (after[0], after[1], bool(win_alive2)))
    finally:
        try:
            proc.kill()
            proc.wait(timeout=5)
        except Exception:
            pass

    # 阈值取 15：提示框是 72% 黑压在半透明底上，实测每像素只暗 20~30，
    # 用 25 会漏掉一大半；用 15 能完整框住"被盖住的那一块 + 白字"
    d_tip = changed(before[2], during[2], 15)
    d_gone = changed(before[2], after[2], 15)
    print('   与"点之前"相比：点击后变化像素 %d，2.4 秒后变化像素 %d（共 %d）'
          % (d_tip, d_gone, len(before[2])))
    ok = True
    if not win_alive:
        print('  => **问题：点二维码之后截图窗口被关掉了（应该留在原地）**')
        ok = False
    else:
        print('  => 通过：不再弹框、截图窗口留在原地')
    if d_tip < 500:   # 提示里的白字会带来上千个被改动的像素；底噪实测为 0
        print('  => **问题：选区正中没出现提示（变化像素太少）**')
        ok = False
    else:
        print('  => 通过：选区正中出现了提示（%d 个像素被改动）' % d_tip)
    if d_gone > d_tip * 0.35:
        print('  => **问题：2 秒后提示没消失**')
        ok = False
    else:
        print('  => 通过：2 秒后提示自己消失了（残留变化只有 %d）' % d_gone)
    return 0 if ok else 1


if __name__ == '__main__':
    rc = main()
    print('\n===== 退出码 %d =====' % rc)
    sys.exit(rc)
