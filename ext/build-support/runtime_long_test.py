r"""截长图端到端验证（第 4 项：每步滚更多 + 拼接正确性）。

流程：
  1. 起一个可滚动的目标窗口（scroll_target.py，独立进程；一格滚轮 = 100px，内容高 4000）
  2. F1 → 框选目标窗口客户区 → 点"截长图" → 在选区里点一下开始滚动
  3. 等它自己滚到底（工具条出现）
  4. 点长图工具条上的"复制" → 结果图会写进 %appdata%\\ScreenCapture\\temp\\last.bin
  5. 读 last.bin：核对高度，并逐行比对内容行号 —— 拼接正确的话第 i 行就该是内容第 i 行，
     漏行/重复行都会立刻暴露
"""
import ctypes
import os
import struct
import subprocess
import sys
import time
from ctypes import wintypes

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    pass

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
TARGET = os.path.join(_HERE, 'scroll_target.py')
EXE_DIR = os.path.dirname(EXE)
PORTABLE_CFG = os.path.join(EXE_DIR, 'config.json')
import _cfg_guard          # 这行文件就是 <exe 同目录>\config.json = 用户真实配置，得护栏
_cfg_guard.install(PORTABLE_CFG)
PY = sys.executable
LAST_BIN = os.path.join(os.path.dirname(EXE), 'temp', 'last.bin')

BLOCK = 16
CONTENT_H = 4000

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
            found.append({'hwnd': hwnd, 'cls': cls.value,
                          'visible': bool(user32.IsWindowVisible(hwnd)),
                          'rect': (r.left, r.top, r.right - r.left, r.bottom - r.top)})
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


def click(hwnd, x, y):
    user32.PostMessageW(hwnd, WM_LBUTTONDOWN, MK_LBUTTON, lparam(x, y))
    time.sleep(0.12)
    user32.PostMessageW(hwnd, WM_LBUTTONUP, 0, lparam(x, y))
    time.sleep(0.25)


def drag(hwnd, x1, y1, x2, y2):
    user32.PostMessageW(hwnd, WM_MOUSEMOVE, MK_LBUTTON, lparam(x1, y1))
    time.sleep(0.1)
    user32.PostMessageW(hwnd, WM_LBUTTONDOWN, MK_LBUTTON, lparam(x1, y1))
    for i in range(1, 5):
        user32.PostMessageW(hwnd, WM_MOUSEMOVE, MK_LBUTTON,
                            lparam(x1 + (x2 - x1) * i // 4, y1 + (y2 - y1) * i // 4))
        time.sleep(0.08)
    user32.PostMessageW(hwnd, WM_LBUTTONUP, 0, lparam(x2, y2))
    time.sleep(0.6)


def btn_x(barw, idx, total):
    sep = 1.5
    w = (barw - 2 * sep) / total
    seps = 1 if idx >= 8 else 0
    seps = 2 if idx >= 10 else seps
    return int(idx * w + seps * sep + w / 2)


def read_clipboard_png():
    """从剪贴板里取 "PNG" 格式（saveToClipboard 一定会写这一种）。返回 bytes 或 None"""
    # 句柄类返回值一定要声明 restype：默认按 c_int 返回会把 64 位句柄截断，
    # 后面 GlobalLock 拿到的就是无效句柄（这一步曾经让我误判成"复制没生效"）
    user32.GetClipboardData.restype = wintypes.HANDLE
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel32.GlobalLock.argtypes = [wintypes.HANDLE]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalSize.argtypes = [wintypes.HANDLE]
    kernel32.GlobalSize.restype = ctypes.c_size_t
    kernel32.GlobalUnlock.argtypes = [wintypes.HANDLE]

    user32.OpenClipboard(None)
    try:
        fmt = 0
        target = 0
        name = ctypes.create_unicode_buffer(256)
        while True:
            fmt = user32.EnumClipboardFormats(fmt)
            if not fmt:
                break
            if user32.GetClipboardFormatNameW(fmt, name, 256) and name.value == 'PNG':
                target = fmt
                break
        if not target:
            return None
        h = user32.GetClipboardData(target)
        if not h:
            return None
        p = kernel32.GlobalLock(h)
        if not p:
            return None
        size = kernel32.GlobalSize(h)
        data = ctypes.string_at(p, size)
        kernel32.GlobalUnlock(h)
        return data
    finally:
        user32.CloseClipboard()


def main():
    # 起目标窗口，并用一个线程持续收集它打印的滚动日志 —— 既能看进度，
    # 也能量出"一步实际滚了多少像素"（这是第 4 项的直接指标）
    target = subprocess.Popen([PY, TARGET], stdout=subprocess.PIPE, text=True, bufsize=1)
    out_lines = []
    import threading

    def reader():
        for ln in target.stdout:
            out_lines.append(ln.strip())
    threading.Thread(target=reader, daemon=True).start()

    line = ''
    t0 = time.time()
    while time.time() - t0 < 8:
        if out_lines:
            line = out_lines[0]
            break
        time.sleep(0.2)
    if not line.startswith('RECT'):
        print('!! 目标窗口没起来: %r' % line)
        target.kill()
        return 1
    tx, ty, tw, th = [int(v) for v in line.split()[1:]]
    print('目标窗口客户区 = (%d,%d) %dx%d，内容高 %d' % (tx, ty, tw, th, CONTENT_H))

    with open(PORTABLE_CFG, 'w', encoding='utf-16') as f:
        f.write('{"common":{"autoStart":false,"language":"zh-CN"},'
                '"shortcutKey":{"cap":"F1","pin":"F3"}}')

    if os.path.exists(LAST_BIN):
        os.remove(LAST_BIN)

    proc = subprocess.Popen([EXE])
    pid = proc.pid
    try:
        time.sleep(3.0)
        msgwnd = find_msg_window(pid)
        if not msgwnd:
            print('!! 没找到消息窗口（可能有别的实例在跑）')
            return 1
        user32.PostMessageW(msgwnd, WM_HOTKEY, WM_APP + 100, 0)
        time.sleep(2.0)
        vis = [w for w in windows_of(pid) if w['visible'] and w['cls'] == 'Ling']
        cap = [w for w in vis if w['rect'][2] > 1000 or w['rect'][3] > 800]
        if not cap:
            print('!! 覆盖层没出现')
            return 1
        capwnd = cap[0]['hwnd']
        origin = (cap[0]['rect'][0], cap[0]['rect'][1])

        # 框选目标窗口客户区（转成覆盖层的客户坐标）
        x1, y1 = tx - origin[0], ty - origin[1]
        x2, y2 = x1 + tw, y1 + th
        drag(capwnd, x1, y1, x2, y2)

        vis = [w for w in windows_of(pid) if w['visible'] and w['cls'] == 'Ling']
        bars = [w for w in vis if w['hwnd'] != capwnd]
        if not bars:
            print('!! 工具条没出来')
            return 1
        bar = min(bars, key=lambda w: w['rect'][1])
        barw, barh = bar['rect'][2], bar['rect'][3]
        print('截图工具条 %dx%d，共 16 个按钮' % (barw, barh))

        print('== 点"截长图"（按钮 10）==')
        click(bar['hwnd'], btn_x(barw, 10, 16), int(barh / 2))
        time.sleep(1.2)
        # 长图会把鼠标移到选区内开始滚，先把光标放到目标窗口正中
        user32.SetCursorPos(tx + tw // 2, ty + th // 2)
        time.sleep(0.3)
        print('== 在选区里点一下开始滚动 ==')
        click(capwnd, (x1 + x2) // 2, (y1 + y2) // 2)

        # 等滚到底：长图工具条出现（4 个按钮，宽度 = 4*32*dpi）
        longbar = None
        t0 = time.time()
        while time.time() - t0 < 60:
            time.sleep(1.0)
            ws = [w for w in windows_of(pid) if w['visible'] and w['cls'] == 'Ling']
            cand = [w for w in ws if w['hwnd'] != capwnd and w['hwnd'] != bar['hwnd']
                    and w['rect'][2] < barw * 0.6]
            if cand:
                longbar = cand[0]
                break
        if not longbar:
            print('!! 等不到长图工具条（滚动可能没跑起来）')
            return 1
        print('   长图工具条 %s，用时 %.1fs' % (longbar['rect'], time.time() - t0))

        # 长图工具条在"开始滚动"那一刻就建好了，所以不能拿它当"滚完了"的信号。
        # 改用目标窗口的滚动日志：等到有滚动、且连续一段时间没有新滚动 = 滚到底了
        print('== 等滚动结束 ==')
        t0 = time.time()
        last_count, last_change = 0, time.time()
        while time.time() - t0 < 90:
            time.sleep(1.0)
            n = len([l for l in out_lines if l.startswith('SCROLL')])
            if n != last_count:
                last_count, last_change = n, time.time()
            if last_count > 0 and time.time() - last_change > 6:
                break
        steps = [l for l in out_lines if l.startswith('SCROLL')]
        print('   目标窗口收到 %d 次滚动，用时 %.1fs' % (len(steps), time.time() - t0))
        for s in steps:
            print('     ' + s)

        print('== 点长图工具条的"复制"（第 4 个按钮）==')
        print('   当前可见 Ling 窗口：')
        for w in windows_of(pid):
            if w['visible'] and w['cls'] == 'Ling':
                print('     hwnd=0x%X rect=%s' % (w['hwnd'], w['rect']))
        lw, lh = longbar['rect'][2], longbar['rect'][3]
        b = lw / 4
        print('   点 (%d,%d)  窗口 0x%X 宽 %d' % (int(3 * b + b / 2), int(lh / 2), longbar['hwnd'], lw))
        click(longbar['hwnd'], int(3 * b + b / 2), int(lh / 2))
        time.sleep(2.0)
        # 点中任何一个按钮都会走 ToolLong::onClick 然后 close()，所以进程退出 = 点击确实生效了
        rc = proc.poll()
        print('   点击后进程状态 = %s' % ('已退出' if rc is not None else '还活着'))
        if rc is None:
            print('   仍然可见的 Ling 窗口：')
            for w in windows_of(pid):
                if w['visible'] and w['cls'] == 'Ling':
                    print('     hwnd=0x%X rect=%s' % (w['hwnd'], w['rect']))
        png_now = read_clipboard_png()
        print('   剪贴板 PNG：%s' % ('有，%d 字节' % len(png_now) if png_now else '无'))
        # 列一下剪贴板里到底有什么格式，便于判断是"没写"还是"写了但读法不对"
        user32.OpenClipboard(None)
        try:
            fmt, names = 0, []
            buf = ctypes.create_unicode_buffer(256)
            while True:
                fmt = user32.EnumClipboardFormats(fmt)
                if not fmt:
                    break
                n = user32.GetClipboardFormatNameW(fmt, buf, 256)
                names.append('%d:%s' % (fmt, buf.value if n else '(标准格式)'))
            print('   剪贴板格式：%s' % (names or '空'))
        finally:
            user32.CloseClipboard()
        # 有产物就够了，别因为一个推断性子句把结果误报成失败
        if rc is None and not png_now:
            print('   !! 点击没生效：进程没退、剪贴板也没东西')
    finally:
        target.kill()
        try:
            proc.kill()
            proc.wait(timeout=5)
        except Exception:
            pass

    png = read_clipboard_png()
    if not png:
        print('!! 剪贴板里没有 PNG（长图的复制没生效？）')
        return 1
    from PIL import Image
    import io as _io
    img = Image.open(_io.BytesIO(png)).convert('L')
    w, h = img.size
    print('   拼接结果 %dx%d' % (w, h))

    def gray_at(row, bx):
        return img.getpixel((bx * BLOCK + BLOCK // 2, row))

    bad = []
    for row in range(0, min(h, CONTENT_H), 37):
        for bx in (0, 10, 30):
            got = gray_at(row, bx)
            hh = (row * 2654435761) ^ (bx * 40503) ^ (row << 13)
            exp = ((hh >> 11) ^ (hh >> 3)) & 0xFF
            if abs(got - exp) > 12:
                bad.append((row, bx, exp, got))
                break
    print('   逐行核对：抽查 %d 行，不符 %d 行' % (len(range(0, min(h, CONTENT_H), 37)), len(bad)))
    for row, bx, exp, got in bad[:6]:
        print('     行%d 块%d 期望%d 实得%d' % (row, bx, exp, got))

    # 每步滚多少：从目标窗口日志里数"真正发生了位移"的次数
    moved = [ln for ln in out_lines if ln.startswith('SCROLL') and '-> ' in ln]
    eff = []
    prev = None
    for ln in moved:
        a, b = ln.split()[1], ln.split()[3]
        if a != b:
            eff.append(int(b) - int(a))
    if eff:
        print('   目标窗口实际位移 %d 次，每次 %d px（合计 %d px）'
              % (len(eff), eff[0], sum(eff)))
    ok = True
    # 内容总高 4000、窗口高 th，所以拼出来应该是 4000 上下（末尾几行是空白也正常）
    if h < CONTENT_H - 5:
        print('  => **图太短**：%d < %d，说明有内容没接上' % (h, CONTENT_H))
        ok = False
    else:
        print('  => 通过：高度 %d ≥ 内容高 %d' % (h, CONTENT_H))
    if bad:
        print('  => **拼接有错**：抽查行与内容行号对不上（漏行或重复）')
        ok = False
    else:
        print('  => 通过：抽查的每一行都与内容行号一致（没有漏行/重复）')
    return 0 if ok else 1


if __name__ == '__main__':
    rc = main()
    print('\n===== 退出码 %d =====' % rc)
    sys.exit(rc)
