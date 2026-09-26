r"""W/A/S/D 微调光标 1 像素（方向键的别名）。

用户需求：靠人手拖鼠标很难精确到那 1 个像素，希望能用键盘微调。方向键本来就能做
（WinCap::onKey 里已在挪 SetCursorPos），再加一套 W/A/S/D —— 左手不用离开键盘，
W 与 ↑ 完全等价。

三项验证：
  1. 框选前（Select）：8 个键各按一次，光标都正好挪 1 像素
  2. 框好之后（Adjust）：W/A/S/D 同样挪 1 像素
  3. 长图阶段（Long，用 --enter=long 直达）：按 W 光标**不动** —— 录制/滚动时
     W/A/S/D 必须留给被录的那个程序（游戏里就是方向，被吃掉等于"一录屏角色就不会动"）

按键用 PostMessage(WM_KEYDOWN) 直接发给覆盖层窗口：不需要前台权限，也不受
"注入按键能否触发热键依赖桌面会话状态"那件事影响（见 MEMORY 里那条踩坑）。
"""
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

user32.PostMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_ulonglong,
                                ctypes.c_longlong]
user32.PostMessageW.restype = wintypes.BOOL
user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
user32.GetCursorPos.restype = wintypes.BOOL
user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
user32.SetCursorPos.restype = wintypes.BOOL
user32.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
user32.GetWindowRect.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.RECT)]
user32.GetWindowRect.restype = wintypes.BOOL
user32.IsWindowVisible.argtypes = [ctypes.c_void_p]
user32.IsWindowVisible.restype = wintypes.BOOL
user32.EnumWindows.argtypes = [ctypes.c_void_p, wintypes.LPARAM]
user32.EnumWindows.restype = wintypes.BOOL
user32.mouse_event.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
                              wintypes.DWORD, ctypes.c_void_p]
user32.keybd_event.argtypes = [ctypes.c_ubyte, ctypes.c_ubyte, wintypes.DWORD, ctypes.c_void_p]

WM_KEYDOWN, WM_KEYUP = 0x0100, 0x0101
VK_UP, VK_DOWN, VK_LEFT, VK_RIGHT = 0x26, 0x28, 0x25, 0x27

_HERE = os.path.dirname(os.path.abspath(__file__))
_BUILD = os.path.normpath(os.path.join(_HERE, '..', 'build'))
EXE = os.environ.get('SC_EXE') or os.path.join(_BUILD, 'bin', 'x64', 'Release', 'ZPin.build.exe')
EXE_DIR = os.path.dirname(EXE)
PORTABLE_CFG = os.path.join(EXE_DIR, 'config.json')
import _cfg_guard          # 这行文件就是 <exe 同目录>\config.json = 用户真实配置，得护栏
_cfg_guard.install(PORTABLE_CFG)

BASE = (400, 400)          # 每个键都从这个点起测，位移一目了然
RECT_FROM, RECT_TO = (300, 300), (900, 700)

# (显示名, 虚拟键码, 期望位移)
KEYS_ALL = [('W', 0x57, (0, -1)), ('S', 0x53, (0, 1)), ('A', 0x41, (-1, 0)), ('D', 0x44, (1, 0)),
            ('Up', VK_UP, (0, -1)), ('Down', VK_DOWN, (0, 1)),
            ('Left', VK_LEFT, (-1, 0)), ('Right', VK_RIGHT, (1, 0))]
KEYS_WASD = [k for k in KEYS_ALL if len(k[0]) == 1]


def cursor():
    p = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(p))
    return (p.x, p.y)


def move(x, y):
    user32.SetCursorPos(x, y)


def send_key(hwnd, vk, hold_ms=60):
    """PostMessage 一个 WM_KEYDOWN/UP 组合。lParam 按常规填（扫描码没给，Ling 只看 wParam）"""
    user32.PostMessageW(hwnd, WM_KEYDOWN, vk, 0x00110001)
    time.sleep(hold_ms / 1000.0)
    user32.PostMessageW(hwnd, WM_KEYUP, vk, 0xC0110001)
    time.sleep(0.25)


def overlay_hwnd(pid, timeout=8.0):
    CB = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    deadline = time.time() + timeout
    while time.time() < deadline:
        found = []

        def cb(h, _):
            p = ctypes.c_uint()
            user32.GetWindowThreadProcessId(h, ctypes.byref(p))
            if p.value == pid and user32.IsWindowVisible(h):
                r = wintypes.RECT()
                user32.GetWindowRect(h, ctypes.byref(r))
                if r.right - r.left > 1000 and r.bottom - r.top > 600:
                    found.append(h)
            return True

        user32.EnumWindows(CB(cb), 0)
        if found:
            return found[0]
        time.sleep(0.3)
    return None


def shot_hotkey():
    user32.keybd_event(0x70, 0, 0, 0)
    time.sleep(0.06)
    user32.keybd_event(0x70, 0, 2, 0)


def nudge(hwnd, name, vk, want):
    """挪回基准点 → 读一次"按键前"的实际位置 → 按一下 → 再读。
    位移一律以**按键前读到的那个位置**为准：SetCursorPos 之后偶尔会有一次
    与按键无关的漂移（覆盖层刚显示时遇到过），拿固定坐标当基准会误判成按键的锅"""
    move(*BASE)
    time.sleep(0.3)
    before = cursor()
    send_key(hwnd, vk)
    after = cursor()
    got = (after[0] - before[0], after[1] - before[1])
    ok = got == want
    extra = '' if before == BASE else '  (基准点漂到 %s)' % (before,)
    print('   %-5s -> 位移 %-10s %s%s' % (name, got, '✔' if ok else '✘ 期望 %s' % (want,), extra))
    return ok


def drag_rect():
    """真实鼠标按下拖框，松开后进 Adjust 阶段"""
    user32.SetCursorPos(*RECT_FROM)
    time.sleep(0.25)
    user32.mouse_event(0x0002, 0, 0, 0, 0)
    time.sleep(0.12)
    for i in range(1, 9):
        user32.SetCursorPos(RECT_FROM[0] + (RECT_TO[0] - RECT_FROM[0]) * i // 8,
                            RECT_FROM[1] + (RECT_TO[1] - RECT_FROM[1]) * i // 8)
        time.sleep(0.05)
    time.sleep(0.3)
    user32.mouse_event(0x0004, 0, 0, 0, 0)
    time.sleep(0.8)


def main():
    with open(PORTABLE_CFG, 'w', encoding='utf-16') as f:
        f.write('{"common":{"autoStart":false,"language":"zh-CN","borderWidth":0},'
                '"shortcutKey":{"cap":"F1","pin":"F3"}}')

    ok = True

    # ---- 1 & 2：Select 阶段 8 个键、Adjust 阶段 4 个键 ----
    proc = subprocess.Popen([EXE])
    try:
        time.sleep(4.0)
        shot_hotkey()
        hwnd = overlay_hwnd(proc.pid)
        if not hwnd:
            print('!! 覆盖层没出现（F1 没生效？）')
            return 1
        time.sleep(0.8)

        print('--- 框选前（Select 阶段）：8 个键各按一次 ---')
        for name, vk, want in KEYS_ALL:
            ok &= nudge(hwnd, name, vk, want)

        print('--- 框好之后（Adjust 阶段）：W/A/S/D ---')
        drag_rect()
        time.sleep(0.4)
        for name, vk, want in KEYS_WASD:
            ok &= nudge(hwnd, name, vk, want)

        sys.stdout.flush()
    finally:
        try:
            proc.kill()
            proc.wait(timeout=5)
        except Exception:
            pass

    # ---- 3：长图阶段不该吃 W/A/S/D ----
    print('--- 长图阶段：按 W 光标应当不动 ---')
    proc = subprocess.Popen([EXE, '--enter=long'])
    try:
        time.sleep(4.0)
        shot_hotkey()
        hwnd = overlay_hwnd(proc.pid)
        if not hwnd:
            print('!! 覆盖层没出现（--enter=long + F1）')
            return 1
        time.sleep(0.8)
        drag_rect()          # 框完直接进长图阶段（不出工具条）
        time.sleep(0.6)
        move(*BASE)
        time.sleep(0.3)
        before = cursor()
        send_key(hwnd, 0x57)          # W
        after = cursor()
        got = (after[0] - before[0], after[1] - before[1])
        if got == (0, 0):
            print('   ✔ 长图阶段 W 没有动光标（键留给被滚/被录的那个窗口）')
        else:
            print('   !! 长图阶段 W 把光标挪了 %s —— 录制时会抢走游戏的方向键' % (got,))
            ok = False
    finally:
        try:
            proc.kill()
            proc.wait(timeout=5)
        except Exception:
            pass

    print()
    print('=>', '通过：W/A/S/D 与方向键等价（截图阶段挪 1 像素，长图/录屏阶段让开）'
          if ok else '**未通过**')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
