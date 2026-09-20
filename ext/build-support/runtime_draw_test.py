"""验证截图阶段的绘图链路真的能用（ToolHost::history 不是空的）。

背景：把绘图工具从贴图窗口搬到截图阶段时，WinCap 忘了创建 history（WinPin 是在自己
构造体里建的）。后果有两条，都是"点了画笔却画不出东西"：
  1. ToolHost::beginShape() 里 `if (!hasTool() || !history) return false;` —— 静默失败
  2. 更糟：撤销按钮 / Ctrl+Z 走的是 `history->undo()`，history 为空就是直接崩

这个脚本在截图阶段点工具条上的"撤销"按钮。它不需要 Ctrl（直接调 history->undo()），
所以不用碰键盘 —— 全程 PostMessage。
撤销按钮是第 9 个按钮（前面有 8 个绘图按钮 + 1 个分隔符）。
"""
import ctypes
import os
import subprocess
import sys
import time
from ctypes import wintypes

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
EXE = os.environ.get('SC_EXE') or os.path.join(_BUILD, 'bin', 'x64', 'Release', 'ScreenCapture.build.exe')
EXE_DIR = os.path.dirname(EXE)
PORTABLE_CFG = os.path.join(EXE_DIR, 'config.json')
import _cfg_guard          # 这行文件就是 <exe 同目录>\config.json = 用户真实配置，得护栏
_cfg_guard.install(PORTABLE_CFG)
DRAG = (400, 300, 900, 700)

# 工具条上的按钮序号（只数按钮，不含分隔符）：0..7 绘图，8 撤销，9 重做，10..12 关闭/保存/复制，
# 中间还有截长图/录屏/文字识别/二维码。撤销前面有 1 个分隔符
UNDO_BTN_INDEX = 8
SEPARATORS_BEFORE_UNDO = 1
TOTAL_BUTTONS = 17        # 截图那根合并后的条
TOTAL_SEPARATORS = 2

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
            found.append({
                'hwnd': hwnd, 'cls': cls.value,
                'visible': bool(user32.IsWindowVisible(hwnd)),
                'rect': (r.left, r.top, r.right - r.left, r.bottom - r.top),
            })
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


def main():
    if not os.path.exists(EXE):
        print('!! 找不到 exe')
        return 1
    with open(PORTABLE_CFG, 'w', encoding='utf-16') as f:
        f.write('{"common":{"autoStart":false,"language":"zh-CN"},'
                '"shortcutKey":{"cap":"F1","pin":"F3"}}')

    proc = subprocess.Popen([EXE])
    pid = proc.pid
    ok = False
    try:
        time.sleep(2.5)
        msgwnd = find_msg_window(pid)
        if not msgwnd:
            print('!! 没找到消息窗口')
            return 1

        print('== 1) F1 开截图覆盖层，拖一个框 ==')
        user32.PostMessageW(msgwnd, WM_HOTKEY, WM_APP + 100, 0)
        time.sleep(2.0)
        ws = windows_of(pid)
        cap = [w for w in ws if w['visible'] and w['rect'][2] > 1000]
        if not cap:
            print('  !! 截图窗口没出现')
            return 1
        capwnd = cap[0]['hwnd']
        x1, y1, x2, y2 = DRAG
        user32.PostMessageW(capwnd, WM_MOUSEMOVE, 0, lparam(x1, y1))
        time.sleep(0.2)
        user32.PostMessageW(capwnd, WM_LBUTTONDOWN, MK_LBUTTON, lparam(x1, y1))
        for i in range(1, 6):
            mx = x1 + (x2 - x1) * i // 5
            my = y1 + (y2 - y1) * i // 5
            user32.PostMessageW(capwnd, WM_MOUSEMOVE, MK_LBUTTON, lparam(mx, my))
            time.sleep(0.1)
        user32.PostMessageW(capwnd, WM_LBUTTONUP, 0, lparam(x2, y2))
        time.sleep(1.5)
        print('  拖框完成')

        ws = windows_of(pid)
        bars = [w for w in ws if w['visible'] and w['cls'] == 'Ling'
                and not (w['rect'][2] > 1000 and w['rect'][3] > 800)]
        if not bars:
            print('  !! 没找到工具条')
            return 1
        bar = bars[0]
        barw, barh = bar['rect'][2], bar['rect'][3]
        # 17 个按钮 + 2 个分隔符 = 整条宽度。分隔符很窄，按 1.5px 估，误差远小于按钮宽度
        sep = 1.5
        btn_w = (barw - TOTAL_SEPARATORS * sep) / TOTAL_BUTTONS
        cx = int(UNDO_BTN_INDEX * btn_w + SEPARATORS_BEFORE_UNDO * sep + btn_w / 2)
        cy = int(barh / 2)
        print('== 2) 点工具条上的"撤销"（工具条 %dx%d，点 (%d,%d)，按钮宽约 %.1f）'
              % (barw, barh, cx, cy, btn_w))
        user32.PostMessageW(bar['hwnd'], WM_LBUTTONDOWN, MK_LBUTTON, lparam(cx, cy))
        time.sleep(0.15)
        user32.PostMessageW(bar['hwnd'], WM_LBUTTONUP, 0, lparam(cx, cy))
        time.sleep(1.5)

        rc = proc.poll()
        if rc is None:
            print('  => 通过：点撤销之后进程还活着（history 不是空的）')
            ok = True
        else:
            print('  => **进程已经死了（退出码 %s）—— history 是空的，撤销踩了空指针**' % rc)
            ok = False
    finally:
        try:
            proc.kill()
            proc.wait(timeout=5)
        except Exception:
            pass
        try:
            os.remove(PORTABLE_CFG)
        except OSError:
            pass

    print('\n===== 退出码 %d =====' % (0 if ok else 1))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
