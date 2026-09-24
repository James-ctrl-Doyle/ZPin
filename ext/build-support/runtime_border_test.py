"""验证"选区边框粗细"设置（第 1 项）：0 应为完全隐藏，默认 2 应能看到蓝框。

做法：分别用 borderWidth=0 / 不写（默认 2）跑两轮，F1 → 框选 → 抓屏，
数一数选区边框那一圈有多少蓝色（#1677ff）像素。
"""
import _pylibs  # noqa: F401  —— 把 ext/build/.pylibs（Pillow）挂进 sys.path
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
# 产物路径从脚本自身位置推导（脚本在 <仓库根>/ext/build-support/），换机器/挪目录都不用改。
# 需要指到别的 exe 时用环境变量 SC_EXE
EXE = os.environ.get('SC_EXE') or os.path.join(_BUILD, 'bin', 'x64', 'Release', 'ZPin.build.exe')
EXE_DIR = os.path.dirname(EXE)
PORTABLE_CFG = os.path.join(EXE_DIR, 'config.json')
import _cfg_guard          # 这行文件就是 <exe 同目录>\config.json = 用户真实配置，得护栏
_cfg_guard.install(PORTABLE_CFG)
SEL = (400, 300, 900, 700)
BORDER_BLUE = (0x16, 0x77, 0xFF)

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


def drag(hwnd, x1, y1, x2, y2):
    user32.PostMessageW(hwnd, WM_MOUSEMOVE, MK_LBUTTON, lparam(x1, y1))
    time.sleep(0.1)
    user32.PostMessageW(hwnd, WM_LBUTTONDOWN, MK_LBUTTON, lparam(x1, y1))
    for i in range(1, 5):
        user32.PostMessageW(hwnd, WM_MOUSEMOVE, MK_LBUTTON,
                            lparam(x1 + (x2 - x1) * i // 4, y1 + (y2 - y1) * i // 4))
        time.sleep(0.08)
    user32.PostMessageW(hwnd, WM_LBUTTONUP, 0, lparam(x2, y2))
    time.sleep(0.7)


def run_case(cfg_common):
    with open(PORTABLE_CFG, 'w', encoding='utf-16') as f:
        f.write('{"common":{%s"autoStart":false,"language":"zh-CN"},'
                '"shortcutKey":{"cap":"F1","pin":"F3"}}' % cfg_common)
    proc = subprocess.Popen([EXE])
    pid = proc.pid
    origin = (0, 0)
    try:
        time.sleep(3.0)
        msgwnd = find_msg_window(pid)
        if not msgwnd:
            return None, '没找到消息窗口'
        user32.PostMessageW(msgwnd, WM_HOTKEY, WM_APP + 100, 0)
        time.sleep(2.0)
        vis = [w for w in windows_of(pid) if w['visible'] and w['cls'] == 'Ling']
        cap = [w for w in vis if w['rect'][2] > 1000 or w['rect'][3] > 800]
        if not cap:
            return None, '覆盖层没出现'
        origin = (cap[0]['rect'][0], cap[0]['rect'][1])
        drag(cap[0]['hwnd'], *SEL)
    finally:
        from PIL import ImageGrab
        shot = ImageGrab.grab().convert('RGB')
        try:
            proc.kill()
            proc.wait(timeout=5)
        except Exception:
            pass

    def blue_near(sx, sy):
        """在 (sx,sy) 附近 5x5 里找最接近边框蓝的像素，返回距离"""
        best = 1e9
        for dy in range(-2, 3):
            for dx in range(-2, 3):
                px = shot.getpixel((sx + origin[0] + dx, sy + origin[1] + dy))
                d = sum((a - b) ** 2 for a, b in zip(px, BORDER_BLUE)) ** 0.5
                best = min(best, d)
        return best

    # 取选区左边框的中点附近
    y_mid = (SEL[1] + SEL[3]) // 2
    return blue_near(SEL[0], y_mid), None


def main():
    print('== A) borderWidth = 0（应完全看不到边框）==')
    da, err = run_case('"borderWidth":0,')
    if err:
        print('  !! ' + err)
        return 1
    print('   选区左边框中点处，到边框蓝的最近距离 = %.1f' % da)

    print('== B) 不写 borderWidth（默认 2，应能看到蓝框）==')
    db, err = run_case('')
    if err:
        print('  !! ' + err)
        return 1
    print('   选区左边框中点处，到边框蓝的最近距离 = %.1f' % db)

    ok = True
    if da < 60:
        print('  => **borderWidth=0 时仍能看到边框**')
        ok = False
    else:
        print('  => 通过：borderWidth=0 时边框不见了')
    if db > 60:
        print('  => **默认值下看不到边框**')
        ok = False
    else:
        print('  => 通过：默认值下边框在')
    return 0 if ok else 1


if __name__ == '__main__':
    rc = main()
    print('\n===== 退出码 %d =====' % rc)
    sys.exit(rc)
