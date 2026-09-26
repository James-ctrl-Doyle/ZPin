"""模拟 F1 → 拖框 → F3，验证第 2、4 条。

全部走 PostMessage（不改系统排序、不抢键盘），只在屏幕上短暂出现几秒窗口。
验两件事：
  1. 第 4 条：框完选区之后，**截图阶段**就出现绘图工具条（WinCap 之外还多出 ToolMain）
  2. 第 2 条：接着按贴图热键 → 截图覆盖层关掉，并贴出一个贴图窗口

注意：finishToPin 会把结果写进剪贴板，所以这个脚本会**覆盖当前剪贴板**。
脚本会先尽力备份纯文本（CF_UNICODETEXT）并在结束时还原；其它格式无法还原。
"""
import ctypes
import os
import subprocess
import sys
import time
from ctypes import wintypes

user32 = ctypes.WinDLL('user32', use_last_error=True)
kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)

WM_HOTKEY = 0x0312
WM_APP = 0x8000
WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
MK_LBUTTON = 0x0001
HWND_MESSAGE = -3
CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002

_HERE = os.path.dirname(os.path.abspath(__file__))
_BUILD = os.path.normpath(os.path.join(_HERE, '..', 'build'))
# 产物路径从脚本自身位置推导（脚本在 <仓库根>/build-support/），换机器/挪目录都不用改。
# 需要指到别的 exe 时用环境变量 SC_EXE
EXE = os.environ.get('SC_EXE') or os.path.join(_BUILD, 'bin', 'x64', 'Release', 'ZPin.build.exe')
EXE_DIR = os.path.dirname(EXE)
PORTABLE_CFG = os.path.join(EXE_DIR, 'config.json')
import _cfg_guard          # 这行文件就是 <exe 同目录>\config.json = 用户真实配置，得护栏
_cfg_guard.install(PORTABLE_CFG)

# 模拟拖框的客户区坐标（相对截图覆盖层左上角 = 虚拟桌面原点）
DRAG = (400, 300, 900, 700)

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


def dump(title, ws):
    print('  %s：共 %d 个窗口' % (title, len(ws)))
    for w in sorted(ws, key=lambda v: v['cls']):
        print('     %-10s visible=%-5s rect=%s' % (w['cls'], w['visible'], w['rect']))


# ———— 剪贴板纯文本的备份 / 还原（尽力而为，只覆盖文本这一种格式）————
def clipboard_get_text():
    if not user32.IsClipboardFormatAvailable(CF_UNICODETEXT):
        return None
    if not user32.OpenClipboard(None):
        return None
    try:
        h = user32.GetClipboardData(CF_UNICODETEXT)
        if not h:
            return None
        p = kernel32.GlobalLock(h)
        if not p:
            return None
        try:
            return ctypes.c_wchar_p(p).value
        finally:
            kernel32.GlobalUnlock(h)
    finally:
        user32.CloseClipboard()


def clipboard_set_text(text):
    if text is None:
        return
    data = ctypes.create_unicode_buffer(text)
    size = ctypes.sizeof(data)
    if not user32.OpenClipboard(None):
        return
    try:
        user32.EmptyClipboard()
        h = kernel32.GlobalAlloc(GMEM_MOVEABLE, size)
        p = kernel32.GlobalLock(h)
        ctypes.memmove(p, data, size)
        kernel32.GlobalUnlock(h)
        user32.SetClipboardData(CF_UNICODETEXT, h)
    finally:
        user32.CloseClipboard()


def main():
    global SAVED_TEXT
    if not os.path.exists(EXE):
        print('!! 找不到 exe')
        return 1
    SAVED_TEXT = clipboard_get_text()
    print('== 0) 已备份剪贴板纯文本：%s' % ('(空)' if not SAVED_TEXT else repr(SAVED_TEXT[:40])))
    with open(PORTABLE_CFG, 'w', encoding='utf-16') as f:
        f.write('{"common":{"autoStart":false,"language":"zh-CN"},'
                '"shortcutKey":{"cap":"F1","pin":"F3"}}')

    proc = subprocess.Popen([EXE])
    pid = proc.pid
    time.sleep(2.5)
    msgwnd = find_msg_window(pid)
    if not msgwnd:
        print('!! 没找到消息窗口')
        proc.kill()
        return 1

    print('\n== 1) 模拟 F1：开截图覆盖层 ==')
    user32.PostMessageW(msgwnd, WM_HOTKEY, WM_APP + 100, 0)
    time.sleep(2.0)
    ws = windows_of(pid)
    dump('按 F1 之后', ws)
    cap = [w for w in ws if w['visible']]
    if not cap:
        print('  !! 截图窗口没出现，后面的测试没法做')
        proc.kill()
        return 1
    capwnd = cap[0]['hwnd']
    origin = (cap[0]['rect'][0], cap[0]['rect'][1])
    print('  => 截图覆盖层 rect=%s（= 虚拟桌面）' % (cap[0]['rect'],))

    print('\n== 2) 模拟在覆盖层上拖框 %s ==' % (DRAG,))
    x1, y1, x2, y2 = DRAG
    user32.PostMessageW(capwnd, WM_MOUSEMOVE, 0, lparam(x1, y1))
    time.sleep(0.2)
    user32.PostMessageW(capwnd, WM_LBUTTONDOWN, MK_LBUTTON, lparam(x1, y1))
    time.sleep(0.2)
    # 分几步移动，让它走真实的 makeRect 路径
    for i in range(1, 6):
        mx = x1 + (x2 - x1) * i // 5
        my = y1 + (y2 - y1) * i // 5
        user32.PostMessageW(capwnd, WM_MOUSEMOVE, MK_LBUTTON, lparam(mx, my))
        time.sleep(0.1)
    user32.PostMessageW(capwnd, WM_LBUTTONUP, 0, lparam(x2, y2))
    time.sleep(1.5)

    ws = windows_of(pid)
    dump('拖框结束之后', ws)
    vis = [w for w in ws if w['visible']]
    n_ling = len([w for w in vis if w['cls'] == 'Ling'])
    # 合并之后截图阶段只有一根工具条：覆盖层 + 工具条 = 2 个可见 Ling 窗口
    # （合并前是覆盖层 + 绘图条 + 功能条 = 3 个）
    print('  => 可见 Ling 窗口 %d 个（应为 2：覆盖层 + 合并后的那根工具条）' % n_ling)
    ok_tools = (n_ling == 2)
    print('  => %s' % ('通过：截图阶段只有一根合并后的工具条' if ok_tools
                       else '**窗口数不对，工具条没合并或没出现**'))
    # 宽度会随系统 dpi 缩放，所以不写死数值，只记下来留到第 3 步跟"贴图那根"比
    bars = [w for w in vis if w['cls'] == 'Ling'
            and not (w['rect'][2] > 1000 and w['rect'][3] > 800)]
    cap_bar_w = 0
    cap_bar_h = 0
    for w in bars:
        cap_bar_w = w['rect'][2]
        cap_bar_h = w['rect'][3]
        print('     截图工具条 rect=%s（16 个按钮：绘图 8 + 撤销重做 2 + 功能 3 + 关闭保存复制 3）'
              % (w['rect'],))
    ok_merge = cap_bar_w > 0
    print('  => %s' % ('截图工具条已出现，宽度待与贴图工具条对比' if ok_merge
                       else '**没看到工具条**'))

    print('\n== 3) 模拟贴图热键 F3（截图过程中按）==')
    user32.PostMessageW(msgwnd, WM_HOTKEY, WM_APP + 101, 0)
    time.sleep(3.5)
    ws = windows_of(pid)
    dump('按 F3 之后', ws)
    vis = [w for w in ws if w['visible']]
    full = [w for w in vis if w['rect'][2] > 1000 and w['rect'][3] > 800]
    small = [w for w in vis if not (w['rect'][2] > 1000 and w['rect'][3] > 800)]
    ok_finish = (len(full) == 0 and len(small) >= 1)
    print('  => 全屏覆盖层还剩 %d 个，小窗口 %d 个' % (len(full), len(small)))
    for w in small:
        print('     贴图候选 rect=%s（拖框起点换算到屏幕应当是 %s）'
              % (w['rect'], (origin[0] + x1, origin[1] + y1)))

    # 贴图窗口自己的工具条是 13 个按钮（绘图 8 + 撤销重做 2 + 关闭保存复制 3），
    # 比截图那根少"截长图 / 录屏 / 文字识别 / 二维码"这 4 个。宽度差正好是 4 个按钮 ——
    # 这一条同时验证了：合并确实把功能按钮并进来了，且它们不会漏到贴图窗口上
    # 高度要与截图那根一致，否则会把贴图窗口本身也算进来（它也是 Ling 窗口、也可能更窄）
    pin_bars = [w for w in ws if w['cls'] == 'Ling'
                and w['rect'][3] == cap_bar_h and 0 < w['rect'][2] < cap_bar_w]
    for w in pin_bars:
        print('     贴图窗口的工具条 rect=%s（应比截图那根 %d 窄 3 个按钮）'
              % (w['rect'], cap_bar_w))
    ok_split = bool(pin_bars) and (cap_bar_w - pin_bars[0]['rect'][2]) > 100
    print('  => %s' % ('通过：截图条(%d) 比贴图条(%d) 多出 3 个功能按钮（截长图/录屏/二维码），合并生效'
                       % (cap_bar_w, pin_bars[0]['rect'][2]) if ok_split
                       else '**两根条的按钮数没体现出差异**'))
    print('  => %s' % ('通过：覆盖层已收工，贴图窗口出现' if ok_finish
                       else '**覆盖层没收工或没贴出图**'))

    print('\n== 4) 往贴图窗口滚一格滚轮，看它是不是直接缩放（第 5 条：不需要按 Ctrl）==')
    ok_zoom = False
    if small:
        pin = small[0]['hwnd']
        before = small[0]['rect']
        WM_MOUSEWHEEL = 0x020A
        # 高字是滚轮增量，低字是按键状态；lParam 是光标的**屏幕**坐标
        for _ in range(3):
            user32.PostMessageW(pin, WM_MOUSEWHEEL,
                                (120 << 16) | 0,
                                lparam(before[0] + before[2] // 2,
                                       before[1] + before[3] // 2))
            time.sleep(0.35)
        time.sleep(0.5)
        ws = windows_of(pid)
        after = [w['rect'] for w in ws if w['hwnd'] == pin]
        after = after[0] if after else None
        print('  滚轮前 rect=%s' % (before,))
        print('  滚轮后 rect=%s' % (after,))
        ok_zoom = bool(after) and after[2] > before[2] and after[3] > before[3]
        if ok_zoom:
            print('  => 通过：滚轮直接放大了（%dx%d -> %dx%d）'
                  % (before[2], before[3], after[2], after[3]))
        else:
            print('  => **失败：滚轮没有放大**')
    else:
        print('  !! 没有贴图窗口，跳过')

    print('\n== 5) 收尾 ==')
    proc.kill()
    proc.wait(timeout=5)
    return 0 if (ok_tools and ok_merge and ok_split and ok_finish and ok_zoom) else 1


if __name__ == '__main__':
    rc = 1
    SAVED_TEXT = None
    try:
        rc = main()
    finally:
        try:
            os.remove(PORTABLE_CFG)
            print('  已删除便携配置')
        except OSError:
            pass
        # finishToPin 会把图写进剪贴板，这里把之前备份的纯文本放回去（只覆盖文本这一种格式）
        current = clipboard_get_text()
        print('  （测试后剪贴板文本：%s）' % ('(空)' if not current else repr(current[:40])))
        if SAVED_TEXT:
            clipboard_set_text(SAVED_TEXT)
            print('  已还原剪贴板文本')
    print('\n===== 退出码 %d =====' % rc)
    sys.exit(rc)
