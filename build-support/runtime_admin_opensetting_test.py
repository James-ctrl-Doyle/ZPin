r"""「切换管理员模式后自动打开设置界面」的验证。

需求：在设置页点"管理员模式"开关 → 二次确认 → 程序重启（托盘图标先消失再回来）
      → **重启后的实例应当自己把设置窗口摆回来**，用户不用再去托盘点一次。

实现是两段拼起来的，这里两段都验：
  * 设置页 relaunchSelf() 给新实例的命令行加 --open-setting
  * App 构造里看到 --open-setting 就走 WinSetting::init()

脚本自己 runas 提权（--child），原因和 runtime_admin_exit_test.py 一样：
要驱动管理员实例的窗口，脚本本身也得是管理员（UIPI）。

两条断言：
  1. 普通 → 管理员：确认框点确定后，新实例的**命令行里有 --open-setting**，
     并且**新实例有可见的设置窗口**（标题=通用设置）
  2. 反向再走一遍（管理员 → 普通），同样要自动开设置页

结果写 build/logs/admin_opensetting_result.txt
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

PROC_NAME = 'ZPin.build.exe'
_HERE = os.path.dirname(os.path.abspath(__file__))
_BUILD = os.path.normpath(os.path.join(_HERE, '..', 'build'))
EXE = os.environ.get('SC_EXE') or os.path.join(_BUILD, 'bin', 'x64', 'Release', PROC_NAME)
EXE_DIR = os.path.dirname(EXE)
PORTABLE_CFG = os.path.join(EXE_DIR, 'config.json')
import _cfg_guard
_cfg_guard.install(PORTABLE_CFG)

RESULT = os.path.join(_BUILD, 'logs', 'admin_opensetting_result.txt')

WM_APP = 0x8000
TRAY_MSG = WM_APP + 100
WM_RBUTTONDOWN = 0x0204
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
HWND_MESSAGE = -3

BTN_X = 570.0        # 按钮列中心（逻辑 x）：160 菜单 + 520 内容 - 20 右内边距 - 90 半按钮宽
# 2026-09-22：管理员模式从最后一行挪到"开机自启"下面（第 2 项），行中心 99.5
ADMIN_ROW_Y = 99.5   # "管理员模式"那一行的中心（逻辑 y）

EnumProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

TOKEN_DUPLICATE = 0x0002
TOKEN_QUERY = 0x0008
MAXIMUM_ALLOWED = 0x02000000
SecurityImpersonation = 2
TokenPrimary = 1
LOGON_WITH_PROFILE = 0x00000001


class STARTUPINFOW(ctypes.Structure):
    _fields_ = [('cb', wintypes.DWORD), ('lpReserved', wintypes.LPWSTR),
                ('lpDesktop', wintypes.LPWSTR), ('lpTitle', wintypes.LPWSTR),
                ('dwX', wintypes.DWORD), ('dwY', wintypes.DWORD),
                ('dwXSize', wintypes.DWORD), ('dwYSize', wintypes.DWORD),
                ('dwXCountChars', wintypes.DWORD), ('dwYCountChars', wintypes.DWORD),
                ('dwFillAttribute', wintypes.DWORD), ('dwFlags', wintypes.DWORD),
                ('wShowWindow', wintypes.WORD), ('cbReserved2', wintypes.WORD),
                ('lpReserved2', ctypes.c_void_p), ('hStdInput', wintypes.HANDLE),
                ('hStdOutput', wintypes.HANDLE), ('hStdError', wintypes.HANDLE)]


class PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [('hProcess', wintypes.HANDLE), ('hThread', wintypes.HANDLE),
                ('dwProcessId', wintypes.DWORD), ('dwThreadId', wintypes.DWORD)]


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


def cmdline_of(pid):
    """读指定进程的命令行。

    走 WMI（Win32_Process.CommandLine）—— 提权进程的命令行普通权限读不到，
    但 WMI 请求是由自己的 WMI 服务代答的，前提是脚本本身是管理员（本脚本正是）。
    """
    try:
        out = subprocess.run(
            ['powershell', '-NoProfile', '-NonInteractive', '-Command',
             '(Get-CimInstance Win32_Process -Filter "ProcessId=%d").CommandLine' % pid],
            capture_output=True, text=True, timeout=20)
        return (out.stdout or '').strip()
    except Exception as e:
        return ''


def start_normal_instance():
    """用 explorer 的令牌起一个**普通权限**实例，返回 pid。

    脚本自己是管理员，直接 Popen 出来的实例也是管理员，测不了"普通 → 管理员"
    那一半。程序里的 relaunchSelf(false) 就是这么降权的，这里复刻一遍。
    （用 PROCESS_INFORMATION 取 pid，别手算结构体偏移 —— 那样很容易读到 0。）
    """
    shell_wnd = user32.GetShellWindow()
    if not shell_wnd:
        return None
    shell_pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(shell_wnd, ctypes.byref(shell_pid))
    hproc = k32.OpenProcess(0x1000, False, shell_pid.value)   # QUERY_LIMITED_INFORMATION
    if not hproc:
        return None
    tok = wintypes.HANDLE()
    dup = wintypes.HANDLE()
    ok = (adv.OpenProcessToken(hproc, TOKEN_DUPLICATE | TOKEN_QUERY, ctypes.byref(tok))
          and adv.DuplicateTokenEx(tok, MAXIMUM_ALLOWED, None, SecurityImpersonation,
                                   TokenPrimary, ctypes.byref(dup)))
    k32.CloseHandle(hproc)
    if not ok:
        return None
    si = STARTUPINFOW()
    si.cb = ctypes.sizeof(si)
    pi = PROCESS_INFORMATION()
    created = adv.CreateProcessWithTokenW(dup, LOGON_WITH_PROFILE, None, '"%s"' % EXE,
                                          0, None, None, ctypes.byref(si), ctypes.byref(pi))
    k32.CloseHandle(tok)
    k32.CloseHandle(dup)
    if not created:
        return None
    k32.CloseHandle(pi.hThread)
    k32.CloseHandle(pi.hProcess)
    return pi.dwProcessId


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


def open_setting_window(pid):
    """设置窗口：可见的 Ling 窗口，宽 400~1200、高 >300，标题是"通用设置"那一类。"""
    for w in windows_of(pid):
        if w['cls'] != 'Ling':
            continue
        L, T, W, H = w['rect']
        if 400 < W < 1200 and H > 300 and w['title']:
            return w
    return None


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
    for _ in range(12):
        s = open_setting_window(pid)
        if s:
            return s
        time.sleep(0.4)
    return None


def close_setting(win):
    """关掉设置窗口：点右上角那个 42x32 的关闭按钮。

    为什么要关：验证的是"重启后**自动**开设置页"，所以重启前必须把设置页关掉，
    否则重启后看到的那扇窗是新实例自己开的、还是别的东西，说不清。
    """
    L, T, W, H = win['rect']
    dpi = user32.GetDpiForWindow(win['hwnd']) / 96.0
    real_click(L + W - 21 * dpi, T + 16 * dpi, settle=1.0)


def click_admin_switch(win):
    L, T, W, H = win['rect']
    dpi = user32.GetDpiForWindow(win['hwnd']) / 96.0
    real_click(L + BTN_X * dpi, T + ADMIN_ROW_Y * dpi, settle=1.2)


def find_confirm(pid, kw, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        for w in windows_of(pid):
            if w['cls'] == 'Ling' and kw in w['title']:
                return w
        time.sleep(0.25)
    return None


def click_confirm_ok(dlg):
    """确认框：右下角内边距 22/20，按钮 88x32，确定在最右。"""
    cdpi = user32.GetDpiForWindow(dlg['hwnd']) / 96.0
    cl, ct, cw, ch = dlg['rect']
    real_click(cl + cw - (22 + 44) * cdpi, ct + ch - (20 + 16) * cdpi, settle=1.0)


def wait_new_pid(old_pid, timeout=25):
    for _ in range(timeout):
        time.sleep(1)
        cands = [p for p in pids_of(PROC_NAME) if p != old_pid]
        if cands:
            return cands[0]
    return None


def wait_open_setting(pid, timeout=12):
    """等新实例自己把设置窗口开出来。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        w = open_setting_window(pid)
        if w:
            return w
        time.sleep(0.5)
    return None


def switch_admin(proc_pid, log, expect_elevated):
    """点开关 → 确认 → 等新实例 → 断言新实例自动开了设置页。返回 (ok, new_pid)。"""
    msgwnd = find_msg_window(proc_pid)
    win = open_setting_via_tray(proc_pid, msgwnd) if msgwnd else None
    if not win:
        log('!! 没能打开设置窗口')
        return False, None
    # 记下窗口里的文案，确认这确实是设置页（不是确认框之类的）
    log('   设置窗口 rect=%s title=%r' % (win['rect'], win['title']))

    # 关掉它，这样重启后能不能再看到就成了"自动打开"的证据
    close_setting(win)
    time.sleep(1.0)
    if open_setting_window(proc_pid):
        log('!! 设置窗口没关掉，后面的判断不可信')
        return False, None
    log('   已关闭设置窗口（重启前应当是关着的）')

    # 再开一次，点开关
    msgwnd = find_msg_window(proc_pid)
    win = open_setting_via_tray(proc_pid, msgwnd) if msgwnd else None
    if not win:
        log('!! 第二次也没能打开设置窗口')
        return False, None
    click_admin_switch(win)

    kw = '以管理员模式重启' if expect_elevated else '退出管理员模式'
    dlg = find_confirm(proc_pid, kw)
    if not dlg:
        log('!! 没等到确认框 %r' % kw)
        return False, None
    log('   ✔ 确认框 title=%r rect=%s' % (dlg['title'], dlg['rect']))
    click_confirm_ok(dlg)

    new_pid = wait_new_pid(proc_pid)
    if not new_pid:
        log('!! 没等到新实例')
        return False, None
    elevated = is_elevated(new_pid)
    log('   ✔ 新实例 pid=%d elevated=%s（期望 %s）' % (new_pid, elevated, expect_elevated))
    if elevated is not expect_elevated:
        log('   !! 权限没切过来')
        return False, new_pid

    # 关键断言 1：命令行里带着 --open-setting
    cl = cmdline_of(new_pid) or ''
    log('   新实例命令行: %s' % cl)
    if '--open-setting' not in cl:
        log('   !! 命令行里没有 --open-setting，新实例不可能知道要开设置页')
        return False, new_pid
    log('   ✔ 命令行带着 --open-setting')

    # 关键断言 2：新实例自己把设置窗口开出来了
    w = wait_open_setting(new_pid)
    if w:
        log('   ✔ 重启后自动打开设置界面：rect=%s title=%r' % (w['rect'], w['title']))
        return True, new_pid
    log('   !! 重启后没看到设置窗口（--open-setting 没被消费？）')
    return False, new_pid


def child_main():
    lines = []

    def log(s):
        print(s, flush=True)
        lines.append(s)

    log('child 是管理员: %s' % bool(shell.IsUserAnAdmin()))
    if not shell.IsUserAnAdmin():
        open(RESULT, 'w', encoding='utf-8').write('RESULT=FAIL')
        return

    with open(PORTABLE_CFG, 'w', encoding='utf-16') as f:
        f.write('{"common":{"autoStart":false,"language":"zh-CN","borderWidth":0},'
                '"shortcutKey":{"cap":"F1","pin":"F3"}}')

    for p in pids_of(PROC_NAME):
        h = k32.OpenProcess(1, False, p)
        if h:
            k32.TerminateProcess(h, 0)
    time.sleep(0.8)

    # ⚠ 脚本是管理员 → 这个实例也是管理员。要测"普通 → 管理员"那一半，
    #    得先用 explorer 的令牌起一个普通权限实例（程序自己也是这么降权的）。
    proc = None
    ok = True
    try:
        log('--- 0. 先起一个普通权限实例 ---')
        pid0 = start_normal_instance()
        if not pid0:
            log('!! 起普通权限实例失败（CreateProcessWithTokenW）')
            ok = False
        else:
            time.sleep(4.0)

            class _P(object):
                pid = pid0
            proc = _P()
            log('启动的实例 pid=%d elevated=%s' % (pid0, is_elevated(pid0)))
            if is_elevated(pid0):
                log('!! 起出来的还是管理员，测不了"普通 → 管理员"')
                ok = False

        if ok:
            log('--- 1. 普通 → 管理员：切换后应自动打开设置界面 ---')
            good, pid2 = switch_admin(proc.pid, log, expect_elevated=True)
            ok = ok and good
            if pid2:
                log('--- 2. 管理员 → 普通：反向再走一遍 ---')
                good2, _ = switch_admin(pid2, log, expect_elevated=False)
                ok = ok and good2
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
    for _ in range(180):
        time.sleep(1)
        if os.path.exists(RESULT):
            break
    if not os.path.exists(RESULT):
        print('!! 子副本没写出结果（UAC 被拒？）')
        return 1
    content = open(RESULT, encoding='utf-8').read()
    print(content)
    print()
    print('=>', '通过：切换管理员模式后设置界面会自动打开'
          if 'RESULT=PASS' in content else '**未通过**')
    return 0 if 'RESULT=PASS' in content else 1


if __name__ == '__main__':
    sys.exit(main())
