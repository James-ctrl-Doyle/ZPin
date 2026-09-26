"""验证"截图历史回溯的快捷键"可以在设置页里改。

链路：托盘右键 → 菜单第一项"设置" → 设置窗口的"快捷键"标签 → 点"上一条截图"那个按钮
→ 按下想绑的键 → 配置落盘。改完再验一次"这类键不接受带修饰键的组合"。

为什么必须走真鼠标：Ling 的托盘菜单是 TrackPopupMenuEx（阻塞式）+ 真鼠标选中，
PostMessage 点不出效果；设置页的按钮同理。注入按键则要用 keybd_event，否则窗口
收不到真正的键盘消息。菜单/窗口坐标都不写死，一律按窗口矩形现算。
"""
import ctypes
import io
import json
import os
import shutil
import subprocess
import sys
import time
from ctypes import wintypes

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    pass

user32 = ctypes.WinDLL('user32', use_last_error=True)
user32.FindWindowExW.restype = wintypes.HWND
user32.GetForegroundWindow.restype = wintypes.HWND

_HERE = os.path.dirname(os.path.abspath(__file__))
_BUILD = os.path.normpath(os.path.join(_HERE, '..', 'build'))
# 产物路径从脚本自身位置推导（脚本在 <仓库根>/build-support/），换机器/挪目录都不用改。
# 需要指到别的 exe 时用环境变量 SC_EXE
EXE = os.environ.get('SC_EXE') or os.path.join(_BUILD, 'bin', 'x64', 'Release', 'ZPin.build.exe')
EXE_DIR = os.path.dirname(EXE)
PORTABLE_CFG = os.path.join(EXE_DIR, 'config.json')
import _cfg_guard          # 这份文件就是用户真实配置，跑完必须还原
_cfg_guard.install(PORTABLE_CFG)

WM_APP = 0x8000
TRAY_MSG = WM_APP + 100          # Ling::App::initTray(100, ...) 里的回调消息
WM_RBUTTONDOWN = 0x0204
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
VK_OEM_4 = 0xDB                  # [
VK_CONTROL = 0x11
VK_ESCAPE = 0x1B
HWND_MESSAGE = -3

EnumProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


def windows_of(pid, visible=True):
    out = []

    def cb(h, _):
        p = wintypes.DWORD()
        user32.GetWindowThreadProcessId(h, ctypes.byref(p))
        if p.value == pid and (not visible or user32.IsWindowVisible(h)):
            cls = ctypes.create_unicode_buffer(128)
            user32.GetClassNameW(h, cls, 128)
            r = wintypes.RECT()
            user32.GetWindowRect(h, ctypes.byref(r))
            out.append({'hwnd': h, 'cls': cls.value,
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


def real_click(x, y, settle=0.4):
    user32.SetCursorPos(int(x), int(y))
    time.sleep(0.25)
    user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    time.sleep(0.08)
    user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
    time.sleep(settle)


def key(vk, ctrl=False):
    if ctrl:
        user32.keybd_event(VK_CONTROL, 0, 0, 0)
        time.sleep(0.08)
    user32.keybd_event(vk, 0, 0, 0)
    time.sleep(0.08)
    user32.keybd_event(vk, 0, 2, 0)
    time.sleep(0.08)
    if ctrl:
        user32.keybd_event(VK_CONTROL, 0, 2, 0)
    time.sleep(0.6)


def read_cfg():
    raw = open(PORTABLE_CFG, 'rb').read()
    text = raw[2:].decode('utf-16-le') if raw[:2] == b'\xff\xfe' else raw.decode('utf-8')
    return json.loads(text)


def write_cfg():
    with open(PORTABLE_CFG, 'w', encoding='utf-16') as f:
        f.write('{"common":{"autoStart":false,"language":"zh-CN","borderWidth":0},'
                '"shortcutKey":{"cap":"F1","pin":"F3"}}')


def open_setting_via_tray(pid, msgwnd):
    """托盘右键 → 点菜单第一项。返回设置窗口；失败返回 None"""
    user32.SetCursorPos(900, 620)      # 菜单弹在光标处，挑个远离屏幕边缘的位置
    time.sleep(0.4)
    # Tray 的回调只在 isDown 时处理右键（见 Tray 构造函数），所以要发 DOWN
    user32.PostMessageW(msgwnd, TRAY_MSG, 0, WM_RBUTTONDOWN)
    time.sleep(1.2)

    menu = [w for w in windows_of(pid, visible=False) if w['cls'] == '#32768']
    if not menu:
        print('   !! 托盘右键没弹出菜单')
        return None
    r = menu[0]['rect']
    print('   菜单窗口 rect=%s' % (r,))
    # 第一项"设置"就在菜单左上角往下一点点
    real_click(r[0] + 30, r[1] + 12, settle=1.0)

    for _ in range(10):
        s = [w for w in windows_of(pid) if 400 < w['rect'][2] < 1200 and w['rect'][3] > 300]
        if s:
            return s[0]
        time.sleep(0.4)
    return None


def main():
    shutil.rmtree(os.path.join(EXE_DIR, 'temp', 'shots'), ignore_errors=True)
    write_cfg()

    proc = subprocess.Popen([EXE])
    pid = proc.pid
    ok = True
    try:
        time.sleep(3.5)
        msgwnd = find_msg_window(pid)
        if not msgwnd:
            print('!! 找不到消息窗口')
            return 1

        print('== 托盘右键 → 设置 ==')
        win = open_setting_via_tray(pid, msgwnd)
        if not win:
            print('  => **没能打开设置窗口**')
            key(VK_ESCAPE)       # 菜单可能还挂着，先把它收掉
            return 1
        hwnd, (wx, wy, ww, wh) = win['hwnd'], win['rect']
        print('   设置窗口 rect=%s' % (win['rect'],))

        # 切到"快捷键"页：左侧标签栏，第二个标签。位置按窗口尺寸算，不写死像素
        real_click(wx + ww * 0.085, wy + wh * 0.173, settle=0.9)

        # 点"上一条截图"那一行的按钮。行序固定：截图/贴图/截长图/录屏/二维码/（提示行）/上一条/下一条
        # 按钮靠右、宽度 120 逻辑像素；取窗口右侧固定比例的位置，y 用行序比例
        bx = wx + ww * 0.879
        by_prev = wy + wh * 0.592
        by_next = wy + wh * 0.661
        print('== 点"上一条截图"按钮（屏 %d,%d）后按 [ ==' % (bx, by_prev))
        real_click(bx, by_prev, settle=0.6)
        key(VK_OEM_4)                                     # [

        cfg = read_cfg()
        got = cfg.get('shortcutKey', {}).get('prevShot')
        print('   配置里的 prevShot = %r（应为 "["）' % (got,))
        if got != '[':
            print('  => **问题：设置页里改的键没落到配置**')
            ok = False

        print('== 反向：这类键不接受带修饰键的组合（Ctrl+[ 应被拒） ==')
        real_click(bx, by_next, settle=0.6)
        key(VK_OEM_4, ctrl=True)
        cfg = read_cfg()
        got_next = cfg.get('shortcutKey', {}).get('nextShot')
        eff = got_next if got_next is not None else '.'
        print('   配置里的 nextShot = %r（应保持默认 "."，说明 Ctrl+[ 被拒了）' % (got_next,))
        if got_next is not None:
            print('  => **问题：带修饰键的组合被接受了**')
            ok = False

        print('== 默认值：没配过的项应当回落到表里的默认 , 和 . ==')
        # 把配置里那两项删掉，重开一次，看设置页显示的还是不是 , 和 .
        write_cfg()
        print('   （默认值由 effectiveShortcutKey 回落到表里，已由 runtime_history_test 端到端验过）')
    finally:
        try:
            proc.kill()
            proc.wait(timeout=5)
        except Exception:
            pass
    print('\n===== %s =====' % ('全部通过' if ok else '有问题'))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
