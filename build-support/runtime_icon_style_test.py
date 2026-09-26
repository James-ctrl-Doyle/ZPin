r"""设置-通用"图标"行（彩色版/简洁版）的行为验证 —— 按精确坐标点，不扫描。

坐标推导与 runtime_setting_toggles_test.py 同一套：窗口 680x560、内容区 y=40 起、
每行 39+1 分隔线。"图标"是最后一行，行中心（逻辑 y）= 439.5，按钮列中心 x = 570。

判据：点一下 → 配置里 common.iconStyle 变 simple；再点一下 → 变回 color。
托盘图标本身（NIM_MODIFY 换图）没法稳定断言，由人工验收；这里保证的是
"点击→写配置→重读"整条链路 + 切换过程不崩。
"""
import _pylibs  # noqa: F401  —— 把 build/.pylibs（Pillow）挂进 sys.path
import ctypes
import json
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
user32.GetDpiForWindow.argtypes = [ctypes.c_void_p]
user32.GetDpiForWindow.restype = ctypes.c_uint

_HERE = os.path.dirname(os.path.abspath(__file__))
_BUILD = os.path.normpath(os.path.join(_HERE, '..', 'build'))
EXE = os.environ.get('SC_EXE') or os.path.join(_BUILD, 'bin', 'x64', 'Release', 'ZPin.build.exe')
EXE_DIR = os.path.dirname(EXE)
PORTABLE_CFG = os.path.join(EXE_DIR, 'config.json')
import _cfg_guard
_cfg_guard.install(PORTABLE_CFG)

ICON_ROW_Y = 439.5     # "图标"行的逻辑 y 中心（最后一行，见 WinSettingCommon 构造函数）
BTN_X = 570.0          # 按钮列中心 x（推导见 toggles 测试头部注释）
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
                        'rect': (r.left, r.top, r.right, r.bottom)})
        return 1   # ⚠ BOOL 回调必须返回整数，返回 None 报 TypeError（ZPin-notes 坑）

    user32.EnumWindows(EnumProc(cb), 0)
    return out


def real_click(x, y, settle=0.6):
    user32.SetCursorPos(int(x), int(y))
    time.sleep(0.2)
    user32.mouse_event(0x0002, 0, 0, 0, 0)   # left down
    time.sleep(0.08)
    user32.mouse_event(0x0004, 0, 0, 0, 0)   # left up
    time.sleep(settle)


def read_icon_style():
    try:
        d = json.loads(open(PORTABLE_CFG, encoding='utf-16').read())
        return d.get('common', {}).get('iconStyle', 'color')
    except Exception:
        return None


def wait_style(expect, timeout=4.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if read_icon_style() == expect:
            return True
        time.sleep(0.25)
    return False


def main():
    # 便携配置里不写 iconStyle —— 走默认彩色版，正好覆盖"默认值"这条路径
    with open(PORTABLE_CFG, 'w', encoding='utf-16') as f:
        f.write('{"common":{"autoStart":false,"language":"zh-CN","borderWidth":0},'
                '"shortcutKey":{"cap":"F1","pin":"F3"}}')

    proc = subprocess.Popen([EXE, '--open-setting=true'])
    try:
        win = None
        deadline = time.time() + 10
        while time.time() < deadline and not win:
            for w in windows_of(proc.pid):
                W = w['rect'][2] - w['rect'][0]
                H = w['rect'][3] - w['rect'][1]
                # ⚠ 按"宽"过滤而不是 right 坐标 —— 窗口位置居中时 right 能到 1700
                if w['cls'] == 'Ling' and 400 < W < 1200 and H > 300:
                    win = w
                    break
            time.sleep(0.4)
        if not win:
            print('!! 设置窗口没出现')
            return 1
        time.sleep(0.8)

        dpi = user32.GetDpiForWindow(win['hwnd']) / 96.0
        L, T = win['rect'][0], win['rect'][1]
        bx = L + BTN_X * dpi
        by = T + ICON_ROW_Y * dpi

        print('设置窗口 %s dpi=%.2f 按钮落点 (%.0f, %.0f)' % (win['rect'], dpi, bx, by))
        real_click(bx, by, settle=0.8)
        ok1 = wait_style('simple')
        print('第 1 次点击 → iconStyle = %s' % read_icon_style())

        real_click(bx, by, settle=0.8)
        ok2 = wait_style('color')
        print('第 2 次点击 → iconStyle = %s' % read_icon_style())

        ok = ok1 and ok2
        if not ok1:
            print('   !! 点了"图标"按钮，配置没变成 simple')
        if not ok2:
            print('   !! 再点一次，配置没变回 color')
        print()
        print('=>', '通过：图标样式两档循环切换且落盘' if ok else '**未通过**')
        return 0 if ok else 1
    finally:
        try:
            proc.kill()
            proc.wait(timeout=5)
        except Exception:
            pass


if __name__ == '__main__':
    sys.exit(main())
