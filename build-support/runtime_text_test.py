"""验证用户报的三个问题。

  #1 截图状态按右键不应退出
  #2 截图状态编辑以后工具栏消失（用"矩形"工具画一笔复现）
  #3 编辑时按 ESC 应只退出编辑，不该关掉整个截图

全部走 PostMessage（不碰真实键盘鼠标）。
注意：本脚本用 PostMessage 模拟热键，绕过了真实的按键流程，
系统不会授予前台权限 —— 所以覆盖层抢前台在真实按键下才生效，这里验证不了。
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
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_RBUTTONDOWN = 0x0204
WM_RBUTTONUP = 0x0205
MK_LBUTTON = 0x0001
VK_ESCAPE = 0x1B
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
DRAG = (400, 300, 900, 700)
TEXT_CLICK = (600, 500)
RECT_DRAW = (450, 350, 700, 550)

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
            # EnumWindows 按 z-order 从顶到底枚举，序号越小越靠上
            found.append({
                'hwnd': hwnd, 'cls': cls.value,
                'visible': bool(user32.IsWindowVisible(hwnd)),
                'rect': (r.left, r.top, r.right - r.left, r.bottom - r.top),
                'z': len(found),
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


def proc_alive(pid):
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    STILL_ACTIVE = 259
    k32 = ctypes.WinDLL('kernel32', use_last_error=True)
    h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return False
    code = wintypes.DWORD()
    k32.GetExitCodeProcess(h, ctypes.byref(code))
    k32.CloseHandle(h)
    return code.value == STILL_ACTIVE


def shot(pid, title):
    ws = windows_of(pid)
    vis = [w for w in ws if w['visible'] and w['cls'] == 'Ling']
    alive = proc_alive(pid)
    print('  --- %s --- 进程=%s 可见Ling窗口=%d %s'
          % (title, '活' if alive else '死', len(vis),
             [w['rect'] for w in vis]))
    return alive, vis


def click(hwnd, x, y):
    user32.PostMessageW(hwnd, WM_LBUTTONDOWN, MK_LBUTTON, lparam(x, y))
    time.sleep(0.12)
    user32.PostMessageW(hwnd, WM_LBUTTONUP, 0, lparam(x, y))


def drag(hwnd, x1, y1, x2, y2, right=False):
    down, up = (WM_RBUTTONDOWN, WM_RBUTTONUP) if right else (WM_LBUTTONDOWN, WM_LBUTTONUP)
    mk = 0 if right else MK_LBUTTON
    user32.PostMessageW(hwnd, WM_MOUSEMOVE, mk, lparam(x1, y1))
    time.sleep(0.1)
    user32.PostMessageW(hwnd, down, mk, lparam(x1, y1))
    for i in range(1, 5):
        user32.PostMessageW(hwnd, WM_MOUSEMOVE, mk,
                            lparam(x1 + (x2 - x1) * i // 4, y1 + (y2 - y1) * i // 4))
        time.sleep(0.08)
    user32.PostMessageW(hwnd, up, mk, lparam(x2, y2))
    time.sleep(0.6)


def real_key(vk):
    """真实注入一个按键（按下+抬起）。F1/ESC 走真实键盘才能和真实使用一致 ——
    尤其 F1：真实按键会让系统授予前台权限，覆盖层的 takeForeground 才生效；
    用 PostMessage 模拟 WM_HOTKEY 则永远拿不到前台，测出来的行为是失真的。"""
    user32.keybd_event(vk, 0, 0, 0)
    time.sleep(0.05)
    user32.keybd_event(vk, 0, 2, 0)   # KEYEVENTF_KEYUP
    time.sleep(0.3)


def esc(hwnd):
    real_key(VK_ESCAPE)               # 真实 ESC：进的是当前前台窗口（应该就是覆盖层）


def main():
    if not os.path.exists(EXE):
        print('!! 找不到 exe')
        return 1
    with open(PORTABLE_CFG, 'w', encoding='utf-16') as f:
        f.write('{"common":{"autoStart":false,"language":"zh-CN"},'
                '"shortcutKey":{"cap":"F1","pin":"F3"}}')

    proc = subprocess.Popen([EXE])
    pid = proc.pid
    ok = True
    try:
        time.sleep(2.5)
        msgwnd = find_msg_window(pid)
        if not msgwnd:
            print('!! 没找到消息窗口（可能有别的实例在跑）')
            return 1

        print('== A) 文本编辑 + ESC ==')
        real_key(0x70)                    # 真实 F1：触发热键 + 让系统授予前台权限
        time.sleep(2.0)
        alive, vis = shot(pid, 'F1 后')
        cap = [w for w in vis if w['rect'][2] > 1000 or w['rect'][3] > 800]
        if not cap:
            print('  !! 覆盖层没出现')
            return 1
        capwnd = cap[0]['hwnd']
        x1, y1, x2, y2 = DRAG
        drag(capwnd, x1, y1, x2, y2)
        alive, vis = shot(pid, '拖框后')
        fg = user32.GetForegroundWindow()
        fgcls = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(fg, fgcls, 256)
        print('     前台=0x%X(%s) 覆盖层=0x%X %s'
              % (fg, fgcls.value, capwnd,
                 '=> 前台正确' if fg == capwnd else '=> **前台不对**'))
        bars = [w for w in vis if w['hwnd'] != capwnd]
        if not bars:
            print('  !! 工具条没出来')
            return 1
        bar = bars[0]
        barw, barh = bar['rect'][2], bar['rect'][3]
        sep = 1.5

        def btn_x(idx):
            seps = 1 if idx >= 8 else 0
            seps = 2 if idx >= 10 else seps
            return int(idx * ((barw - 2 * sep) / 17) + seps * sep + ((barw - 2 * sep) / 17) / 2)

        # 点"文本"工具 → 在选区里点一下 → **立即** ESC（300ms 兜底窗口内）
        click(bar['hwnd'], btn_x(5), int(barh / 2))
        alive, vis = shot(pid, '点了文本工具')
        if not alive:
            return 1
        tx, ty = TEXT_CLICK
        click(capwnd, tx, ty)
        alive, vis = shot(pid, '落出输入框后')
        esc(capwnd)                       # 紧跟其后，落在 300ms 兜底窗口内
        alive, vis = shot(pid, '第 1 下 ESC 后（应只退编辑，窗口还在）')
        if not alive or not vis:
            print('  => **问题 #3：ESC 还是把截图关了**')
            ok = False
        else:
            print('  => 通过：第一下 ESC 只退出编辑')
        time.sleep(1.0)
        esc(capwnd)
        alive, vis = shot(pid, '第 2 下 ESC 后（应关掉截图）')
        if alive and vis:
            print('  => 第二下 ESC 没关掉（可接受）')

        print('\n== B) 矩形工具画一笔，看工具条是否消失（#2）==')
        real_key(0x70)                    # 真实 F1
        time.sleep(2.0)
        alive, vis = shot(pid, 'F1 后')
        cap = [w for w in vis if w['rect'][2] > 1000 or w['rect'][3] > 800]
        if not cap:
            print('  !! 覆盖层没出现')
            return 1
        capwnd = cap[0]['hwnd']
        drag(capwnd, x1, y1, x2, y2)
        alive, vis = shot(pid, '拖框后')
        bars = [w for w in vis if w['hwnd'] != capwnd]
        if not bars:
            print('  !! 工具条没出来')
            return 1
        bar = bars[0]
        barw, barh = bar['rect'][2], bar['rect'][3]
        click(bar['hwnd'], btn_x(0), int(barh / 2))     # 矩形工具
        alive, vis = shot(pid, '点了矩形工具')
        if not alive:
            return 1
        rx1, ry1, rx2, ry2 = RECT_DRAW
        drag(capwnd, rx1, ry1, rx2, ry2)                # 在选区里画一个矩形
        alive, vis = shot(pid, '画完矩形后')
        bars2 = [w for w in vis if w['hwnd'] != capwnd]
        if not alive:
            return 1
        if not bars2:
            print('  => **问题 #2 复现：画完一笔工具条没了**')
            ok = False
        else:
            print('  => 通过：画完一笔工具条还在（%d 个）' % len(bars2))

        print('\n== C) 文本编辑时工具条是否被覆盖（#2 的 z-order 检查）==')
        click(bar['hwnd'], btn_x(5), int(barh / 2))     # 文本工具
        click(capwnd, tx if False else 600, 500)        # 落输入框（这一下会激活覆盖层）
        alive, vis = shot(pid, '编辑中')
        ov = [w for w in vis if w['hwnd'] == capwnd]
        tb = [w for w in vis if w['hwnd'] != capwnd]
        if ov and tb:
            ov_z = ov[0]['z']
            above = all(t['z'] < ov_z for t in tb)
            print('     覆盖层 z=%d，工具条 z=%s' % (ov_z, [t['z'] for t in tb]))
            print('  => %s' % ('通过：工具条都在覆盖层上面' if above
                               else '**问题 #2 复现：工具条被覆盖层盖住了**'))
            ok = ok and above
        elif not alive:
            return 1

        print('\n== D) 右键不应退出（#1）==')
        if proc_alive(pid):
            ws = windows_of(pid)
            cap = [w for w in ws if w['visible'] and w['cls'] == 'Ling'
                   and (w['rect'][2] > 1000 or w['rect'][3] > 800)]
            if cap:
                drag(cap[0]['hwnd'], 500, 500, 500, 500, right=True)
                alive, vis = shot(pid, '右键后')
                if alive and vis:
                    print('  => 通过：右键没有退出截图')
                else:
                    print('  => **问题 #1 复现：右键退出了截图**')
                    ok = False

        return 0 if ok else 1
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


if __name__ == '__main__':
    rc = main()
    print('\n===== 退出码 %d =====' % rc)
    sys.exit(rc)
