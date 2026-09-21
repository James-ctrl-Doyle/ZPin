r"""设置页"退出管理员模式"的验证 —— 必须用管理员权限跑。

为什么单独一个脚本：
  普通权限的进程给不了更高完整性的窗口发消息（UIPI 拦 PostMessage），所以想驱动
  **管理员实例**的设置页、点它的开关，测试脚本自己也得是管理员。
  （反方向那条"普通 → 管理员"在 runtime_setting_toggles_test.py 里验证。）

脚本自己 runas 提权（--child），子副本是管理员：
  启动 exe（继承管理员令牌）→ 托盘右键开设置页 → 点"管理员模式"开关
  → 确认框标题应是「退出管理员模式」→ 点「确定」
  → 程序应以**普通权限**重新启动（提权进程造不出普通权限的子进程，程序借 explorer
     的令牌起新实例，机制本身由 runtime_admin_toggle_test.py 单独验证过）
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
k32 = ctypes.windll.kernel32
adv = ctypes.windll.advapi32
shell = ctypes.windll.shell32
shell.ShellExecuteW.restype = ctypes.c_void_p
shell.ShellExecuteW.argtypes = [wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR,
                               wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.c_int]
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

RESULT = os.path.join(_BUILD, 'logs', 'admin_exit_result.txt')

WM_APP = 0x8000
TRAY_MSG = WM_APP + 100
WM_RBUTTONDOWN = 0x0204
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
HWND_MESSAGE = -3

BTN_X = 570.0
# 2026-09-22：管理员模式从最后一行挪到"开机自启"下面（第 2 项），行中心 99.5
# （内容区从 y=40 起：开机自启 39+1=40，接着管理员行 39 → 中心 80+19.5）
ADMIN_ROW_Y = 99.5

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


def child_main():
    lines = []

    def log(s):
        lines.append(s)

    log('child 是管理员: %s' % bool(shell.IsUserAnAdmin()))
    if not shell.IsUserAnAdmin():
        open(RESULT, 'w', encoding='utf-8').write('\n'.join(lines) + '\nRESULT=FAIL')
        return

    with open(PORTABLE_CFG, 'w', encoding='utf-16') as f:
        f.write('{"common":{"autoStart":false,"language":"zh-CN","borderWidth":0},'
                '"shortcutKey":{"cap":"F1","pin":"F3"}}')

    for p in pids_of(PROC_NAME):
        h = k32.OpenProcess(1, False, p)
        if h:
            k32.TerminateProcess(h, 0)
    time.sleep(0.8)

    proc = subprocess.Popen([EXE])       # 脚本是管理员 → 这个实例也是管理员
    ok = True
    try:
        time.sleep(4.0)
        log('启动的实例 pid=%d elevated=%s' % (proc.pid, is_elevated(proc.pid)))
        if not is_elevated(proc.pid):
            log('!! 起出来的不是管理员实例，测不了"退出"')
            ok = False
        msgwnd = find_msg_window(proc.pid)
        win = open_setting_via_tray(proc.pid, msgwnd) if msgwnd else None
        if not win:
            log('!! 没能打开设置窗口')
            ok = False

        if ok:
            L, T, W, H = win['rect']
            dpi = user32.GetDpiForWindow(win['hwnd']) / 96.0
            x, y = L + BTN_X * dpi, T + ADMIN_ROW_Y * dpi
            log('点管理员开关 (%d,%d)' % (x, y))
            real_click(x, y, settle=1.2)

            # 确认框是个独立 Ling 窗口，标题就是那句标题
            dlg = None
            for _ in range(16):
                for w in windows_of(proc.pid):
                    if w['cls'] == 'Ling' and '退出管理员模式' in w['title']:
                        dlg = w
                        break
                if dlg:
                    break
                time.sleep(0.25)
            if dlg:
                log('✔ 确认框 title=%r rect=%s' % (dlg['title'], dlg['rect']))
                cdpi = user32.GetDpiForWindow(dlg['hwnd']) / 96.0
                cl, ct, cw, ch = dlg['rect']
                # 确定按钮：右下角 padding 22/20，按钮 88x32，确定在最右
                real_click(cl + cw - (22 + 44) * cdpi, ct + ch - (20 + 16) * cdpi, settle=0.9)
                back = None
                for _ in range(20):
                    time.sleep(1)
                    cands = [p for p in pids_of(PROC_NAME) if p != proc.pid]
                    if cands:
                        back = cands[0]
                        break
                if back and not is_elevated(back):
                    log('✔ 退出管理员模式成功：新实例 pid=%d elevated=False' % back)
                else:
                    log('!! 没能降回普通权限（pid=%s）' % back)
                    ok = False
            else:
                log('!! 没等到"退出管理员模式"确认框 —— 管理员模式下点开关应弹这个框')
                ok = False
    finally:
        for p in pids_of(PROC_NAME):
            h = k32.OpenProcess(1, False, p)
            if h:
                k32.TerminateProcess(h, 0)
        time.sleep(0.5)
    open(RESULT, 'w', encoding='utf-8').write('\n'.join(lines) +
                                             '\nRESULT=%s' % ('PASS' if ok else 'FAIL'))


def main():
    if '--child' in sys.argv:
        child_main()
        return 0
    if os.path.exists(RESULT):
        os.remove(RESULT)
    print('用 runas 拉起管理员副本...')
    args = '"%s" --child' % os.path.abspath(__file__)
    r = shell.ShellExecuteW(None, 'runas', sys.executable, args, None, 1)
    print('runas 返回:', r)
    for _ in range(90):
        time.sleep(1)
        if os.path.exists(RESULT):
            break
    if not os.path.exists(RESULT):
        print('!! 子副本没写出结果（UAC 被拒？）')
        return 1
    content = open(RESULT, encoding='utf-8').read()
    print(content)
    print()
    print('=>', '通过：管理员模式下能退出、且带着二次确认'
          if 'RESULT=PASS' in content else '**未通过**')
    return 0 if 'RESULT=PASS' in content else 1


if __name__ == '__main__':
    sys.exit(main())
