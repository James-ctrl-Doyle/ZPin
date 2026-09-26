r"""设置页"退出管理员模式"依赖的关键机制验证。

提权进程**造不出普通权限的子进程** —— CreateProcess 出来的子进程一律继承提权令牌。
所以程序里的做法是借已登录的 shell（explorer，跑在用户会话、中等完整性）的令牌来起新实例：
    GetShellWindow → OpenProcessToken → DuplicateTokenEx → CreateProcessWithTokenW

这个假设是整个"退出管理员模式"能不能成立的关键，本脚本把它复刻一遍来验证：
  1. 脚本先把自己用 runas 拉成一个**管理员**副本（--child）
  2. 那个管理员副本用 explorer 的令牌启动 ZPin.exe
  3. 检查新实例的令牌 —— 必须是**普通权限**才算通过

反向那条（普通 → 管理员，走 runas）由 runtime_autostart_test.py 覆盖。
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

k32 = ctypes.windll.kernel32
user32 = ctypes.WinDLL('user32', use_last_error=True)
adv = ctypes.windll.advapi32
shell = ctypes.windll.shell32
shell.ShellExecuteW.restype = ctypes.c_void_p
shell.ShellExecuteW.argtypes = [wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR,
                               wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.c_int]

PROC_NAME = 'ZPin.build.exe'
_HERE = os.path.dirname(os.path.abspath(__file__))
_BUILD = os.path.normpath(os.path.join(_HERE, '..', 'build'))
EXE = os.environ.get('SC_EXE') or os.path.join(_BUILD, 'bin', 'x64', 'Release', PROC_NAME)
EXE_DIR = os.path.dirname(EXE)
PORTABLE_CFG = os.path.join(EXE_DIR, 'config.json')
import _cfg_guard
_cfg_guard.install(PORTABLE_CFG)

RESULT = os.path.join(_BUILD, 'logs', 'admin_toggle_result.txt')

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
    if adv.OpenProcessToken(h, TOKEN_QUERY, ctypes.byref(tok)):
        class TE(ctypes.Structure):
            _fields_ = [('v', ctypes.c_ulong)]
        te = TE()
        sz = ctypes.c_ulong()
        adv.GetTokenInformation(tok, 20, ctypes.byref(te), ctypes.sizeof(te), ctypes.byref(sz))
        res = bool(te.v)
    k32.CloseHandle(h)
    return res


def kill_all():
    for p in pids_of(PROC_NAME):
        h = k32.OpenProcess(1, False, p)
        if h:
            k32.TerminateProcess(h, 0)
    time.sleep(0.8)


def is_admin():
    return bool(shell.IsUserAnAdmin())


# ———— 管理员副本：复刻 relaunchSelf(false) ————
def child_main():
    lines = []
    lines.append('child: IsUserAnAdmin=%s' % is_admin())
    if not is_admin():
        lines.append('child: 不是管理员，没法验证降权')
        open(RESULT, 'w', encoding='utf-8').write('\n'.join(lines))
        return

    kill_all()
    shell_wnd = user32.GetShellWindow()
    lines.append('GetShellWindow=0x%X' % (shell_wnd or 0))
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(shell_wnd, ctypes.byref(pid))
    lines.append('explorer pid=%d' % pid.value)
    proc = k32.OpenProcess(0x1000, False, pid.value)
    lines.append('OpenProcess(explorer)=0x%X' % (proc or 0))
    tok = wintypes.HANDLE()
    lines.append('OpenProcessToken=%s' % bool(adv.OpenProcessToken(
        proc, TOKEN_DUPLICATE | TOKEN_QUERY, ctypes.byref(tok))))
    dup = wintypes.HANDLE()
    lines.append('DuplicateTokenEx=%s' % bool(adv.DuplicateTokenEx(
        tok, MAXIMUM_ALLOWED, None, SecurityImpersonation, TokenPrimary, ctypes.byref(dup))))
    si = STARTUPINFOW()
    si.cb = ctypes.sizeof(si)
    pi = PROCESS_INFORMATION()
    cmd = '"%s"' % EXE
    ok = adv.CreateProcessWithTokenW(dup, LOGON_WITH_PROFILE, None, cmd, 0, None, None,
                                     ctypes.byref(si), ctypes.byref(pi))
    lines.append('CreateProcessWithTokenW=%s (err=%d)' % (bool(ok), ctypes.get_last_error()))
    if ok:
        k32.CloseHandle(pi.hThread)
        k32.CloseHandle(pi.hProcess)
    k32.CloseHandle(dup)
    if tok:
        k32.CloseHandle(tok)
    if proc:
        k32.CloseHandle(proc)

    time.sleep(4)
    procs = pids_of(PROC_NAME)
    elev = [(p, is_elevated(p)) for p in procs]
    lines.append('新实例: %s' % (elev,))
    lines.append('RESULT=%s' % ('PASS' if procs and not any(e for _, e in elev) else 'FAIL'))
    open(RESULT, 'w', encoding='utf-8').write('\n'.join(lines))


def main():
    if '--child' in sys.argv:
        child_main()
        return 0
    if os.path.exists(RESULT):
        os.remove(RESULT)
    kill_all()
    print('把自己用 runas 拉成管理员副本...')
    args = '"%s" --child' % os.path.abspath(__file__)
    r = shell.ShellExecuteW(None, 'runas', sys.executable, args, None, 1)
    print('runas 返回:', r)
    for _ in range(30):
        time.sleep(1)
        if os.path.exists(RESULT):
            break
    if not os.path.exists(RESULT):
        print('!! 子副本没写出结果（UAC 被拒？）')
        return 1
    print(open(RESULT, encoding='utf-8').read())
    kill_all()
    ok = 'RESULT=PASS' in open(RESULT, encoding='utf-8').read()
    print('=>', '通过：提权进程能借 explorer 令牌起出普通权限实例（退出管理员模式可行）'
          if ok else '**未通过**')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
