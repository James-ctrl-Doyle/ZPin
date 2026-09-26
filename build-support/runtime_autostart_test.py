r"""开机自启：注册表行为 + 管理员模式的提权启动。

背景：注册表的 Run 项**没有提权能力** —— 写在里面的程序开机一律以普通权限启动。
所以"管理员模式 + 开机自启"只能自己补一步：自启命令行里带 `--elevate=true`，
进程起来发现自己是普通权限时用 runas 再拉一个管理员实例，然后把让位。

三项验证：
  A. 自启项带 --elevate 时：从普通权限启动 → 自动换成管理员实例（普通那个退出，不套娃）
  B. 自启项不带 --elevate 时：启动后仍是普通权限，不会被莫名提权
  C. 以管理员身份跑一次 → 把"普通版"自启项升级成带提权标记的版本（Setting::syncAutoStartElevation）

⚠ 只碰 HKCU\...\Run\ZPin 这一个值，跑完删掉（并确认恢复原状）。
"""
import ctypes
import os
import subprocess
import sys
import time
import winreg
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

RUN_KEY = r'Software\Microsoft\Windows\CurrentVersion\Run'
VALUE = 'ZPin'
PROC_NAME = 'ZPin.build.exe'

_HERE = os.path.dirname(os.path.abspath(__file__))
_BUILD = os.path.normpath(os.path.join(_HERE, '..', 'build'))
EXE = os.environ.get('SC_EXE') or os.path.join(_BUILD, 'bin', 'x64', 'Release', PROC_NAME)
EXE_DIR = os.path.dirname(EXE)
PORTABLE_CFG = os.path.join(EXE_DIR, 'config.json')
import _cfg_guard          # 那是用户真实配置，装个护栏
_cfg_guard.install(PORTABLE_CFG)


# ———— 注册表 ————
def read_value():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            return winreg.QueryValueEx(k, VALUE)[0]
    except FileNotFoundError:
        return None


def write_value(v):
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
        winreg.SetValueEx(k, VALUE, 0, winreg.REG_SZ, v)


def delete_value():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
            winreg.DeleteValue(k, VALUE)
    except FileNotFoundError:
        pass


# ———— 进程 ————
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
    h = k32.OpenProcess(0x1000, False, pid)      # PROCESS_QUERY_LIMITED_INFORMATION
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


def kill_all():
    for p in pids_of(PROC_NAME):
        h = k32.OpenProcess(1, False, p)
        if h:
            k32.TerminateProcess(h, 0)
    time.sleep(0.8)


def snapshot(label):
    procs = pids_of(PROC_NAME)
    info = [(p, is_elevated(p)) for p in procs]
    print('   %s: %s' % (label, info or '（无实例）'))
    return info


def main():
    original = read_value()
    print('跑之前注册表里那个值:', repr(original))
    ok = True
    try:
        # ———— A：带 --elevate 的自启项，普通权限启动 → 应换成管理员 ————
        print('--- A 自启项带 --elevate：启动后应变成管理员实例 ---')
        kill_all()
        write_value('"%s" --auto-start=true --elevate=true' % EXE)
        # 模拟开机：系统是按注册表里的**完整命令行**拉起它的，参数要一起带上 ——
        # 只 Popen([EXE]) 等于测了个没带 --elevate 的普通启动，验证不到提权那条路
        subprocess.Popen([EXE, '--auto-start=true', '--elevate=true'])
        time.sleep(9)
        info = snapshot('9 秒后')
        if not info:
            print('   !! 一个实例都没有 —— 提权后没起来？')
            ok = False
        elif all(e for _, e in info):
            print('   ✔ 现在跑着的都是管理员实例（普通那个已经让位）')
        else:
            print('   !! 还有非管理员实例，或者没换过来：', info)
            ok = False

        # ———— B：不带 --elevate → 不该被提权 ————
        print('--- B 自启项不带 --elevate：应保持普通权限 ---')
        kill_all()
        write_value('"%s" --auto-start=true' % EXE)
        subprocess.Popen([EXE])
        time.sleep(6)
        info = snapshot('6 秒后')
        if not info:
            print('   !! 进程没起来')
            ok = False
        elif any(e for _, e in info):
            print('   !! 被莫名提权了')
            ok = False
        else:
            print('   ✔ 仍是普通权限（没有多此一举去提权）')

        # ———— C：管理员跑一次 → 把普通版自启项升级 ————
        print('--- C 以管理员跑一次：普通版自启项应被补上提权标记 ---')
        kill_all()
        write_value('"%s" --auto-start=true' % EXE)
        print('   升级前:', repr(read_value()))
        r = shell.ShellExecuteW(None, 'runas', EXE, None, None, 1)
        print('   runas 返回:', r)
        upgraded = None
        for _ in range(12):             # 最多等 12 秒
            time.sleep(1)
            upgraded = read_value()
            if upgraded and '--elevate' in upgraded:
                break
        print('   升级后:', repr(upgraded))
        if upgraded and '--elevate' in upgraded:
            print('   ✔ 管理员实例启动时把自启项升级成了提权版')
        else:
            print('   !! 没有被升级')
            ok = False
        info = snapshot('（管理员实例）')
        if info and not any(e for _, e in info):
            print('   !! runas 起来的这个不是管理员？')
            ok = False
    finally:
        kill_all()
        # 还原：跑之前有就写回去，没有就删掉
        if original is None:
            delete_value()
        else:
            write_value(original)
        print('注册表已还原:', repr(read_value()))
    print()
    print('=>', '通过：自启的注册表行为与管理员模式适配都正确' if ok else '**未通过**')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
