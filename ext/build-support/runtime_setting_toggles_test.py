r"""设置页开关与"自绘确认框"的行为验证 —— 按精确坐标点，不扫描。

坐标不靠试：设置页的布局是固定的（窗口 680x560、菜单宽 160、内容区 padding 20/40、
每行 39 + 1 分隔线），按下表的逻辑坐标 × dpi 就能点到目标那一行的按钮列：

    行序（WinSettingCommon 构造函数里的顺序）      行中心（逻辑 y）
    开机自启                                       59.5
    语言                                            99.5
    选区边框                                       139.5
    默认保存位置                                   179.5
    快速保存                                       219.5
    截图历史                                       279.5
    管理员模式（最后一行）                         319.5
    按钮列中心 x = 160(菜单宽) + 520(内容宽) - 20(右内边距) - 90(半按钮宽) = 570

验证四件事：
  1. 点"管理员模式"开关 → 弹出自绘确认框（独立 Ling 窗口，标题就是那句标题）
  2. 点确认框的「取消」→ 框消失、程序**没有**重启（PID 不变、权限不变）
  3. 再点一次 → 点「确定」→ 程序重启，且新实例是管理员
  4. 管理员实例上点同一个开关 → 标题变成"退出管理员模式"，点确定又回到普通权限
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
k32 = ctypes.windll.kernel32
adv = ctypes.windll.advapi32
user32.FindWindowExW.restype = wintypes.HWND
user32.GetDpiForWindow.argtypes = [ctypes.c_void_p]
user32.GetDpiForWindow.restype = ctypes.c_uint

PROC_NAME = 'ScreenCapture.build.exe'
_HERE = os.path.dirname(os.path.abspath(__file__))
_BUILD = os.path.normpath(os.path.join(_HERE, '..', 'build'))
EXE = os.environ.get('SC_EXE') or os.path.join(_BUILD, 'bin', 'x64', 'Release', PROC_NAME)
EXE_DIR = os.path.dirname(EXE)
PORTABLE_CFG = os.path.join(EXE_DIR, 'config.json')
import _cfg_guard
_cfg_guard.install(PORTABLE_CFG)

WM_APP = 0x8000
TRAY_MSG = WM_APP + 100
WM_RBUTTONDOWN = 0x0204
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
HWND_MESSAGE = -3

ROW_Y = {'autoStart': 59.5, 'quickSave': 219.5, 'admin': 319.5}
BTN_X = 570.0

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


def real_click(x, y, settle=0.6):
    user32.SetCursorPos(int(x), int(y))
    time.sleep(0.2)
    user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    time.sleep(0.08)
    user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
    time.sleep(settle)


def write_cfg():
    with open(PORTABLE_CFG, 'w', encoding='utf-16') as f:
        f.write('{"common":{"autoStart":false,"language":"zh-CN","borderWidth":0},'
                '"shortcutKey":{"cap":"F1","pin":"F3"}}')


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
    for _ in range(10):
        s = [w for w in windows_of(pid) if 400 < w['rect'][2] < 1200 and w['rect'][3] > 300]
        if s:
            return s[0]
        time.sleep(0.4)
    return None


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


def is_elevated(pid):
    h = k32.OpenProcess(0x1000, False, pid)
    if not h:
        return None
    tok = wintypes.HANDLE()
    res = None
    if adv.OpenProcessToken(h, 0x0008, ctypes.byref(tok)):
        class TE(ctypes.Structure):
            _fields_ = [('v', ctypes.c_ulong)]
        te = TE()
        sz = ctypes.c_ulong()
        adv.GetTokenInformation(tok, 20, ctypes.byref(te), ctypes.sizeof(te), ctypes.byref(sz))
        res = bool(te.v)
    k32.CloseHandle(h)
    return res


def find_confirm(pid, title_kw, timeout=4.0):
    """确认框是个独立的 Ling 窗口，标题就是那句标题 —— 直接按标题认，不用猜坐标"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        for w in windows_of(pid):
            if w['cls'] == 'Ling' and title_kw in w['title']:
                return w
        time.sleep(0.25)
    return None


def click_confirm_button(pid, title_kw, which):
    """点确认框上的按钮。卡片就是窗口本身，布局由 WinConfirm 定死：
    右下角内边距 22/20、按钮 88x32、两个按钮右对齐（确定在最右）"""
    w = find_confirm(pid, title_kw)
    if not w:
        return False
    dpi = user32.GetDpiForWindow(w['hwnd']) / 96.0
    L, T, W, H = w['rect']
    y = T + H - (20 + 16) * dpi
    if which == 'ok':
        x = L + W - (22 + 44) * dpi
    else:
        x = L + W - (22 + 88 + 10 + 44) * dpi
    real_click(x, y, settle=0.9)
    return True


def open_setting(proc, tries=3):
    for _ in range(tries):
        msgwnd = find_msg_window(proc.pid)
        if msgwnd:
            win = open_setting_via_tray(proc.pid, msgwnd)
            if win:
                return win
        time.sleep(1.0)
    return None


def click_admin_switch(win):
    L, T, W, H = win['rect']
    dpi = user32.GetDpiForWindow(win['hwnd']) / 96.0
    x = L + BTN_X * dpi
    y = T + ROW_Y['admin'] * dpi
    print('   点管理员开关 (%d,%d)' % (x, y))
    real_click(x, y, settle=1.2)


def wait_new_pid(old_pid, timeout=20):
    for _ in range(timeout):
        time.sleep(1)
        cands = [p for p in pids_of(PROC_NAME) if p != old_pid]
        if cands:
            return cands[0]
    return None


def main():
    write_cfg()
    ok = True
    proc = subprocess.Popen([EXE])
    try:
        time.sleep(3.5)
        win = open_setting(proc)
        if not win:
            print('!! 没能打开设置窗口')
            return 1
        print('设置窗口 rect=%s' % (win['rect'],))
        first_pid = proc.pid

        print('--- 1/2. 点管理员开关 → 自绘确认框 → 点「取消」不该重启 ---')
        click_admin_switch(win)
        dlg = find_confirm(first_pid, '以管理员模式重启')
        if dlg:
            print('   ✔ 弹出确认框：title=%r rect=%s' % (dlg['title'], dlg['rect']))
            # 留一张图：这个框是自绘的，观感本身就是需求的一部分（原来用系统 MessageBox 太丑）
            try:
                from PIL import ImageGrab
                L0, T0, W0, H0 = dlg['rect']
                m = 30
                im = ImageGrab.grab(bbox=(L0 - m, T0 - m, L0 + W0 + m, T0 + H0 + m))
                im.save(os.path.join(_BUILD, 'logs', 'confirm_dialog.png'))
                print('   （确认框截图已存 ext/build/logs/confirm_dialog.png）')
            except Exception as e:
                print('   （截图失败：%s）' % e)
        else:
            print('   !! 没等到确认框')
            ok = False
        if click_confirm_button(first_pid, '以管理员模式重启', 'cancel'):
            time.sleep(1.5)
            if proc.poll() is None and not is_elevated(first_pid):
                print('   ✔ 点「取消」：程序没重启，仍是普通权限（pid=%d）' % first_pid)
            else:
                print('   !! 点取消后进程状态不对')
                ok = False
        else:
            print('   !! 没能点到取消按钮')
            ok = False

        print('--- 3. 再点一次 → 点「确定」→ 应重启成管理员 ---')
        # 上一步的"取消"刚把设置窗口的输入还回来（EnableWindow + SetForegroundWindow），
        # 立刻再点会偶发点不动 —— 等它两秒，并且同一个目标最多重试三次
        time.sleep(2.0)
        wins = [w for w in windows_of(first_pid)
                if 400 < w['rect'][2] < 1200 and w['rect'][3] > 300]
        if not wins:
            print('   !! 设置窗口不见了')
            return 1
        for attempt in range(3):
            click_admin_switch(wins[0])
            if find_confirm(first_pid, '以管理员模式重启', timeout=2.0):
                break
            print('   （第 %d 次点击没弹出，重试）' % (attempt + 1))
            time.sleep(1.0)
        if click_confirm_button(first_pid, '以管理员模式重启', 'ok'):
            new_pid = wait_new_pid(first_pid)
            if new_pid and is_elevated(new_pid):
                print('   ✔ 重启成功：新实例 pid=%d elevated=True' % new_pid)
            else:
                print('   !! 没换成管理员实例（pid=%s）' % new_pid)
                ok = False
        else:
            print('   !! 没能点到确定按钮')
            ok = False

        print('--- 4. 管理员实例上的"退出管理员模式"见 runtime_admin_exit_test.py ---')
        print('   （那一步得用管理员权限的脚本去驱动管理员实例：普通权限的进程给不了')
        print('     更高完整性的窗口发消息，UIPI 会拦）')
    finally:
        for p in pids_of(PROC_NAME):
            h = k32.OpenProcess(1, False, p)
            if h:
                k32.TerminateProcess(h, 0)
        time.sleep(0.5)
    print()
    print('=>', '通过：确认框与开关行为都符合预期' if ok else '**未通过**')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
