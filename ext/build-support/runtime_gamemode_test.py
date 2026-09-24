r"""验证"游戏模式"（设置 → 通用里的开关，存 common.gameMode）。

它做的事：开着的时候，检测到全屏（含无边框全屏）游戏就自动暂停所有全局热键，
退出游戏自动恢复。暂停走 Setting::suspendShortcuts —— **只注销热键、不写配置**，
所以和用户显式设置的"关闭所有快捷键"互不覆盖（用户手动关的，游戏结束也不会被
它悄悄打开）。

判据用**持有探测**（别的进程 RegisterHotKey 同一组合失败 = 程序持有着它），
理由见 runtime_hotkey_disable_test.py 开头那段：注入按键触发热键会受桌面会话
状态影响，实测出现过环境漂移。

两段：
  A. 开关与热键注册（默认跑）：gameMode=true 启动时，F1/F3 仍应被程序持有
     （开关开着不等于禁用 —— 只有真检测到全屏游戏才暂停）
  B. 全屏检测（要加 --fullscreen 才跑）：
     gameMode=true  + 造一个铺满屏幕的无边框窗口并置前 → F1/F3 应变成**空闲**
     撤掉那个窗口                                        → F1/F3 应重新**被持有**
     gameMode=false + 同样造窗口                          → F1/F3 应始终**被持有**

⚠ 关于 --fullscreen：这一步必须有一个真的铺满屏幕、无边框且在前台的窗口才能
  触发 —— 那是检测逻辑本身的性质（判据就是"前台窗口铺满显示器且没有标题栏"）。
  但它会短暂盖住整个屏幕（约 3 秒），所以**默认不跑**。
  （教训：早先跑回归时铺过全屏黑窗口，用户以为死机了 —— 占屏这事要主动交代。）

用法：
  python runtime_gamemode_test.py               # 只跑 A
  python runtime_gamemode_test.py --fullscreen  # A + B
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

u = ctypes.windll.user32
k32 = ctypes.windll.kernel32

_HERE = os.path.dirname(os.path.abspath(__file__))
_BUILD = os.path.normpath(os.path.join(_HERE, '..', 'build'))
EXE = os.environ.get('SC_EXE') or os.path.join(_BUILD, 'bin', 'x64', 'Release', 'ZPin.build.exe')
PORTABLE_CFG = os.path.join(os.path.dirname(EXE), 'config.json')
import _cfg_guard          # exe 同目录的 config.json = 用户真实配置，得护栏
_cfg_guard.install(PORTABLE_CFG)

VK_F1, VK_F3 = 0x70, 0x72


def held(vk):
    """某个键当前是否被别的进程注册成了全局热键。RegisterHotKey 成功 = 空闲。
    探测完立刻释放，免得自己把它占住影响下一次判断。"""
    ok = u.RegisterHotKey(None, 0xC0F0, 0, vk)
    if ok:
        u.UnregisterHotKey(None, 0xC0F0)
    return not ok


def write_cfg(game_mode):
    if os.path.exists(PORTABLE_CFG):
        os.remove(PORTABLE_CFG)
    with open(PORTABLE_CFG, 'w', encoding='utf-16') as f:
        f.write('{"common":{"autoStart":false,"language":"zh-CN","gameMode":%s},'
                '"shortcutKey":{"cap":"F1","pin":"F3"}}'
                % ('true' if game_mode else 'false'))


# ———— 造一个"铺满屏幕的无边框窗口"，模拟全屏游戏 ————
WNDCLASSEXW_FIELDS = [
    ('cbSize', wintypes.UINT), ('style', wintypes.UINT), ('lpfnWndProc', ctypes.c_void_p),
    ('cbClsExtra', ctypes.c_int), ('cbWndExtra', ctypes.c_int), ('hInstance', wintypes.HINSTANCE),
    ('hIcon', wintypes.HICON), ('hCursor', wintypes.HANDLE), ('hbrBackground', wintypes.HBRUSH),
    ('lpszMenuName', wintypes.LPCWSTR), ('lpszClassName', wintypes.LPCWSTR),
    ('hIconSm', wintypes.HICON),
]


class WNDCLASSEXW(ctypes.Structure):
    _fields_ = WNDCLASSEXW_FIELDS


WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_longlong, wintypes.HWND, wintypes.UINT,
                             wintypes.WPARAM, wintypes.LPARAM)

WS_POPUP, WS_VISIBLE = 0x80000000, 0x10000000
WS_EX_TOPMOST = 0x00000008
_proc_ref = None       # 保住回调，别被 GC 掉


def make_fullscreen_window(title):
    """铺满主显示器、无边框、置顶 + 抢到前台。返回 hwnd。"""
    global _proc_ref
    _proc_ref = WNDPROC(lambda h, m, w, l: u.DefWindowProcW(h, m, w, l))

    cls_name = 'ZPinGameModeTestWnd'
    wc = WNDCLASSEXW()
    wc.cbSize = ctypes.sizeof(WNDCLASSEXW)
    wc.lpfnWndProc = ctypes.cast(_proc_ref, ctypes.c_void_p)
    wc.hInstance = k32.GetModuleHandleW(None)
    wc.lpszClassName = cls_name
    if not u.RegisterClassExW(ctypes.byref(wc)):
        raise OSError('RegisterClassExW 失败: %d' % ctypes.get_last_error())

    sw, sh = u.GetSystemMetrics(0), u.GetSystemMetrics(1)      # 主显示器像素尺寸
    hwnd = u.CreateWindowExW(WS_EX_TOPMOST, cls_name, title,
                             WS_POPUP | WS_VISIBLE, 0, 0, sw, sh,
                             None, None, wc.hInstance, None)
    if not hwnd:
        raise OSError('CreateWindowExW 失败: %d' % ctypes.get_last_error())
    # 抢前台：SetForegroundWindow 对"刚创建且当前没人操作"的进程通常直接成功
    u.SetWindowPos(hwnd, -1, 0, 0, sw, sh, 0x0040)             # HWND_TOPMOST + SHOWWINDOW
    u.SetForegroundWindow(hwnd)
    u.BringWindowToTop(hwnd)
    return hwnd


def kill_window(hwnd):
    u.DestroyWindow(hwnd)


def start_exe(game_mode):
    write_cfg(game_mode)
    return subprocess.Popen([EXE])


def main():
    full = '--fullscreen' in sys.argv

    print('--- A. 开关开着，没有全屏窗口 → 热键应仍被程序持有 ---')
    proc = start_exe(True)
    try:
        time.sleep(4.0)
        f1, f3 = held(VK_F1), held(VK_F3)
        print('   gameMode=true, 无全屏窗口: F1 %s / F3 %s'
              % ('被持有' if f1 else '空闲', '被持有' if f3 else '空闲'))
        if not (f1 and f3):
            print('   !! 期望两个都被持有 —— 开关本身不该禁用热键')
            return 1
        print('   ✔ 符合预期')

        if not full:
            print()
            print('=> 通过（只跑了 A）。想验证"检测到全屏游戏自动暂停"请加 --fullscreen')
            print('   ⚠ 那一步会短暂占满屏幕约 3 秒')
            return 0

        print()
        print('--- B1. 造一个铺满屏幕的无边框窗口并置前（约 3 秒）---')
        hwnd = make_fullscreen_window('ZPin 游戏模式自检窗口')
        try:
            time.sleep(3.0)          # 检测周期 1.5 秒，留两轮
            f1, f3 = held(VK_F1), held(VK_F3)
            print('   全屏窗口在前台: F1 %s / F3 %s'
                  % ('被持有' if f1 else '空闲', '被持有' if f3 else '空闲'))
            if f1 or f3:
                print('   !! 期望两个都变空闲（热键被自动暂停）')
                return 1
            print('   ✔ 热键已被自动暂停')
        finally:
            kill_window(hwnd)

        print()
        print('--- B2. 撤掉窗口 → 应自动恢复注册 ---')
        time.sleep(3.0)
        f1, f3 = held(VK_F1), held(VK_F3)
        print('   窗口已撤: F1 %s / F3 %s'
              % ('被持有' if f1 else '空闲', '被持有' if f3 else '空闲'))
        if not (f1 and f3):
            print('   !! 期望两个都恢复成被持有')
            return 1
        print('   ✔ 已自动恢复')
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            u.PostMessageW(0xFFFF, 0x0010, 0, 0)

    print()
    print('--- C. 开关关掉 + 同样造窗口 → 不该介入 ---')
    proc = start_exe(False)
    try:
        time.sleep(4.0)
        hwnd = make_fullscreen_window('ZPin 游戏模式自检窗口(开关关)')
        try:
            time.sleep(3.0)
            f1, f3 = held(VK_F1), held(VK_F3)
            print('   gameMode=false, 全屏窗口在前台: F1 %s / F3 %s'
                  % ('被持有' if f1 else '空闲', '被持有' if f3 else '空闲'))
            if not (f1 and f3):
                print('   !! 开关关着时不该碰热键')
                return 1
            print('   ✔ 符合预期（开关关闭时不介入）')
        finally:
            kill_window(hwnd)
    finally:
        proc.terminate()

    print()
    print('=> 通过：开关、自动暂停、自动恢复、关闭时不介入，四项都符合预期')
    return 0


if __name__ == '__main__':
    sys.exit(main())
