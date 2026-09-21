"""验证二维码识别"成功"那条路的新行为：

    识别到 -> 内容写进剪切板 -> **立刻退出截图状态** -> 那句"已复制"由独立小窗（Toast）继续飘 2 秒

屏幕上的二维码从 git 历史里取回（当初删掉的那批赞助码之一），用 ctypes 手画一个窗口显示它，
再走真实流程：F1 -> 框选二维码 -> 点工具条上的二维码按钮。

四条断言（都有判别力）：
  1. 0.7 秒时截图窗口**必须已经没了**（"立马退出"）；
  2. 但 0.7 秒时选区正中**必须还看得见提示** —— 证明提示不依赖截图窗口；
  3. 2.8 秒时提示自己收掉（画面回到原样），且进程一个可见窗口都不剩；
  4. 剪切板里确实拿到了内容。

屏幕上没有二维码时（"未识别到"那条路）由 runtime_qr_test.py 负责：那条路应该留在原地。
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
gdi32 = ctypes.WinDLL('gdi32', use_last_error=True)
# ⚠ ctypes 调 Win32 的句柄类参数/返回值**必须**声明 argtypes / restype（见文件末尾那一段说明），
# 声明集中放在两个窗口类定义之后——那里才有 WNDCLASSEXW / PAINTSTRUCT
WM_HOTKEY = 0x0312
WM_APP = 0x8000
WM_DESTROY = 0x0002
WM_PAINT = 0x000F
WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
MK_LBUTTON = 0x0001
HWND_MESSAGE = -3
IMAGE_BITMAP = 0
LR_LOADFROMFILE = 0x00000010
LR_CREATEDIBSECTION = 0x00002000
SRCCOPY = 0x00CC0020
WHITE_BRUSH = 0

_HERE = os.path.dirname(os.path.abspath(__file__))
_BUILD = os.path.normpath(os.path.join(_HERE, '..', 'build'))
EXE = os.environ.get('SC_EXE') or os.path.join(_BUILD, 'bin', 'x64', 'Release', 'ScreenCapture.build.exe')
EXE_DIR = os.path.dirname(EXE)
PORTABLE_CFG = os.path.join(EXE_DIR, 'config.json')
import _cfg_guard          # 这行文件就是 <exe 同目录>\config.json = 用户真实配置，得护栏
_cfg_guard.install(PORTABLE_CFG)
ROOT = os.path.normpath(os.path.join(_HERE, '..', '..'))
LOG_DIR = os.path.join(_BUILD, 'logs')

# 二维码窗口：620x620 白底 + 居中 540x540 的二维码（留出 40px 静默区，quirc 靠它定位）
WIN_X, WIN_Y, WIN_W, WIN_H = 380, 260, 620, 620
QR_OFF, QR_SIZE = 40, 540
SEL = (WIN_X, WIN_Y, WIN_X + WIN_W, WIN_Y + WIN_H)

EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_longlong, wintypes.HWND, wintypes.UINT,
                             wintypes.WPARAM, wintypes.LPARAM)


class WNDCLASSEXW(ctypes.Structure):
    _fields_ = [('cbSize', wintypes.UINT), ('style', wintypes.UINT),
                ('lpfnWndProc', WNDPROC), ('cbClsExtra', ctypes.c_int),
                ('cbWndExtra', ctypes.c_int), ('hInstance', wintypes.HINSTANCE),
                ('hIcon', wintypes.HICON), ('hCursor', wintypes.HANDLE),
                ('hbrBackground', wintypes.HBRUSH), ('lpszMenuName', wintypes.LPCWSTR),
                ('lpszClassName', wintypes.LPCWSTR), ('hIconSm', wintypes.HICON)]


class PAINTSTRUCT(ctypes.Structure):
    _fields_ = [('hdc', wintypes.HDC), ('fErase', wintypes.BOOL),
                ('rcPaint', wintypes.RECT), ('fRestore', wintypes.BOOL),
                ('fIncUpdate', wintypes.BOOL),                 ('rgbReserved', ctypes.c_byte * 32)]

# ⚠ ctypes 调 Win32：句柄相关的参数和返回值**必须**声明 argtypes / restype。
# 不声明的话 ctypes 会按 c_int（32 位）打包，64 位句柄一传就 "int too long to convert"，
# 症状是"窗口建出来了却是白板、Bitmap 没贴上去"——看起来像画错了，其实是参数被截掉了。
user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR,
                                   wintypes.DWORD, ctypes.c_int, ctypes.c_int,
                                   ctypes.c_int, ctypes.c_int, wintypes.HWND,
                                   wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
user32.CreateWindowExW.restype = wintypes.HWND
user32.RegisterClassExW.argtypes = [ctypes.POINTER(WNDCLASSEXW)]
user32.LoadImageW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT,
                              ctypes.c_int, ctypes.c_int, wintypes.UINT]
user32.LoadImageW.restype = wintypes.HANDLE
user32.BeginPaint.argtypes = [wintypes.HWND, ctypes.POINTER(PAINTSTRUCT)]
user32.BeginPaint.restype = wintypes.HDC
user32.EndPaint.argtypes = [wintypes.HWND, ctypes.POINTER(PAINTSTRUCT)]
user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.DefWindowProcW.restype = ctypes.c_longlong
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
gdi32.CreateCompatibleDC.restype = wintypes.HDC
gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
gdi32.SelectObject.restype = wintypes.HGDIOBJ
gdi32.BitBlt.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                         wintypes.HDC, ctypes.c_int, ctypes.c_int, wintypes.DWORD]
gdi32.DeleteDC.argtypes = [wintypes.HDC]


def lparam(x, y):
    return (y << 16) | (x & 0xFFFF)


def ensure_fixture():
    """把二维码取到 ext/build/logs/ 下（git 历史里还有，当初从 Doc/ 删掉的）。
    顺便存一份 24 位 BMP —— LoadImage 只认 .bmp 文件"""
    from PIL import Image
    jpg = os.path.join(LOG_DIR, 'qr_fixture.jpg')
    bmp = os.path.join(LOG_DIR, 'qr_fixture.bmp')
    if not os.path.exists(jpg):
        os.makedirs(LOG_DIR, exist_ok=True)
        h = subprocess.run(['git', 'log', '--diff-filter=D', '--format=%H', '-1', '--', 'Doc/alipay.jpg'],
                           cwd=ROOT, capture_output=True, text=True).stdout.strip()
        if not h:
            print('!! 没能从 git 历史里找到二维码素材')
            return None
        blob = subprocess.run(['git', 'show', h + '^:Doc/alipay.jpg'], cwd=ROOT,
                              capture_output=True).stdout
        if not blob:
            print('!! git show 取不出二维码素材')
            return None
        open(jpg, 'wb').write(blob)
    im = Image.open(jpg).convert('RGB').resize((QR_SIZE, QR_SIZE), Image.NEAREST)
    canvas = Image.new('RGB', (WIN_W, WIN_H), (255, 255, 255))
    canvas.paste(im, (QR_OFF, QR_OFF))
    canvas.save(bmp)
    return bmp


def make_qr_window(bmp_path):
    """白底窗口 + BitBlt 把二维码贴上去。句柄类返回值必须声明 restype，否则 64 位会被截成 32 位"""
    state = {'hbm': user32.LoadImageW(None, bmp_path, IMAGE_BITMAP, 0, 0,
                                      LR_LOADFROMFILE | LR_CREATEDIBSECTION),
             'hwnd': None}

    def on_paint(hwnd):
        ps = PAINTSTRUCT()
        hdc = user32.BeginPaint(hwnd, ctypes.byref(ps))
        memdc = gdi32.CreateCompatibleDC(hdc)
        old = gdi32.SelectObject(memdc, state['hbm'])
        gdi32.BitBlt(hdc, 0, 0, WIN_W, WIN_H, memdc, 0, 0, SRCCOPY)
        gdi32.SelectObject(memdc, old)
        gdi32.DeleteDC(memdc)
        user32.EndPaint(hwnd, ctypes.byref(ps))

    def proc(hwnd, msg, wp, lp):
        if msg == WM_PAINT:
            on_paint(hwnd)
            return 0
        if msg == WM_DESTROY:
            user32.PostQuitMessage(0)
            return 0
        return user32.DefWindowProcW(hwnd, msg, wp, lp)

    cls = WNDCLASSEXW()
    cls.cbSize = ctypes.sizeof(WNDCLASSEXW)
    cls.style = 0
    cls.lpfnWndProc = WNDPROC(proc)
    cls.hInstance = ctypes.windll.kernel32.GetModuleHandleW(None)
    cls.hCursor = user32.LoadCursorW(None, ctypes.c_wchar_p(32512))
    cls.hbrBackground = gdi32.GetStockObject(WHITE_BRUSH)
    cls.lpszClassName = 'ScQrFixture'
    if not user32.RegisterClassExW(ctypes.byref(cls)):
        err = ctypes.get_last_error()
        if err != 1410:          # 1410 = 类已注册（上一次跑留下的）
            print('!! RegisterClassExW 失败 err=%d' % err)
            return None
    hwnd = user32.CreateWindowExW(0x00000008, 'ScQrFixture', 'qr', 0x80000000,
                                  WIN_X, WIN_Y, WIN_W, WIN_H, None, None, cls.hInstance, None)
    if not hwnd:
        print('!! CreateWindowExW 失败')
        return None
    state['hwnd'] = hwnd
    user32.ShowWindow(hwnd, 5)          # SW_SHOW
    user32.UpdateWindow(hwnd)
    time.sleep(0.5)
    return hwnd


def windows_of(pid):
    found = []

    def cb(hwnd, _):
        wpid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(wpid))
        if wpid.value == pid:
            r = wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(r))
            found.append({'hwnd': hwnd, 'visible': bool(user32.IsWindowVisible(hwnd)),
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


def center_gray(cx, cy):
    """取选区正中一块的灰度，用来判断提示有没有出现"""
    from PIL import ImageGrab
    shot = ImageGrab.grab().convert('L')
    return [shot.getpixel((x, y)) for y in range(cy - 30, cy + 30)
            for x in range(cx - 90, cx + 90)]


def clipboard_text():
    CF_UNICODETEXT = 13
    kernel32 = ctypes.windll.kernel32
    # 同样是句柄类返回值/参数，必须声明（见前面的说明）
    user32.OpenClipboard.argtypes = [wintypes.HWND]
    user32.OpenClipboard.restype = wintypes.BOOL
    user32.GetClipboardData.argtypes = [wintypes.UINT]
    user32.GetClipboardData.restype = wintypes.HANDLE
    kernel32.GlobalLock.argtypes = [wintypes.HANDLE]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [wintypes.HANDLE]
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


def changed(a, b, thr=15):
    return sum(1 for x, y in zip(a, b) if abs(x - y) > thr)


def main():
    if not os.path.exists(EXE):
        print('!! 找不到 exe: %s' % EXE)
        return 1
    bmp = ensure_fixture()
    if not bmp:
        return 1

    with open(PORTABLE_CFG, 'w', encoding='utf-16') as f:
        f.write('{"common":{"autoStart":false,"language":"zh-CN"},'
                '"shortcutKey":{"cap":"F1","pin":"F3"}}')

    # 先把剪切板弄脏，这样"识别成功"之后读到的内容只可能来自这次识别
    user32.OpenClipboard(None)
    user32.EmptyClipboard()
    user32.CloseClipboard()

    fx = make_qr_window(bmp)
    if not fx:
        return 1
    print('== 二维码已显示在 (%d,%d) %dx%d ==' % (WIN_X, WIN_Y, WIN_W, WIN_H))

    proc = subprocess.Popen([EXE])
    pid = proc.pid
    try:
        time.sleep(3.0)
        msgwnd = find_msg_window(pid)
        if not msgwnd:
            print('!! 没找到消息窗口（可能有别的实例在跑）')
            return 1
        user32.PostMessageW(msgwnd, WM_HOTKEY, WM_APP + 100, 0)   # 等价按 F1
        time.sleep(2.0)
        vis = [w for w in windows_of(pid) if w['visible']]
        cap = [w for w in vis if w['rect'][2] > 1000 or w['rect'][3] > 800]
        if not cap:
            print('!! 覆盖层没出现')
            return 1
        capwnd = cap[0]['hwnd']
        drag(capwnd, *SEL)

        bars = [w for w in windows_of(pid) if w['visible'] and w['hwnd'] != capwnd]
        bar = min(bars, key=lambda w: w['rect'][1])
        barw, barh = bar['rect'][2], bar['rect'][3]
        sep = 1.5
        w1 = (barw - 2 * sep) / 16               # 共 16 个按钮
        bx = int(12 * w1 + 2 * sep + w1 / 2)     # 第 13 个 = 二维码

        cx = (SEL[0] + SEL[2]) // 2
        cy = (SEL[1] + SEL[3]) // 2
        before = center_gray(cx, cy)
        avg_before = sum(before) / len(before)
        # 判别力：全白说明二维码根本没画到窗口上，那样后面走的是"未识别"那条路，
        # 会得出"窗口留在原地"的假结果 —— 先在这里拦掉
        if avg_before > 250:
            print('!! 选区里几乎纯白（平均亮度 %.1f）：二维码没画上，先修这个再跑' % avg_before)
            return 1

        print('== 点二维码识别（按钮 13，x=%d）== 点之前平均亮度 %.1f'
              % (bx, avg_before))
        click(bar['hwnd'], bx, int(barh / 2))

        # 0.7 秒：截图窗口应该**已经没了**（立刻退出），而独立提示还在屏幕上
        time.sleep(0.7)
        during = center_gray(cx, cy)
        vis_07 = [w for w in windows_of(pid) if w['visible']]
        alive_07 = any(w['hwnd'] == capwnd for w in vis_07)
        print('   0.7 秒：平均亮度 %.1f；截图窗口还在 = %s；本进程可见窗口 %d 个'
              % (sum(during) / len(during), alive_07, len(vis_07)))

        # 再等到约 2.8 秒：提示应该自己收掉了，一个窗口都不剩
        time.sleep(2.1)
        after = center_gray(cx, cy)
        vis_28 = [w for w in windows_of(pid) if w['visible']]
        print('   2.8 秒：平均亮度 %.1f；本进程可见窗口 %d 个'
              % (sum(after) / len(after), len(vis_28)))

        text = clipboard_text()
        print('   剪切板内容：%r' % (text[:60] if text else None))
    finally:
        try:
            proc.kill()
            proc.wait(timeout=5)
        except Exception:
            pass
        user32.PostMessageW(fx, WM_DESTROY, 0, 0)
        time.sleep(0.3)

    d_tip = changed(before, during)
    d_gone = changed(before, after)
    print('   相对"点之前"：0.7 秒变化 %d 个像素，2.8 秒变化 %d 个' % (d_tip, d_gone))

    ok = True
    if alive_07:
        print('  => **问题：0.7 秒时截图窗口还在，没有"立马退出"**')
        ok = False
    else:
        print('  => 通过：0.7 秒时截图窗口已经关掉（识别完立刻退出）')
    if d_tip < 500:
        print('  => **问题：0.7 秒时选区正中没看见提示（变化像素太少）**')
        ok = False
    else:
        print('  => 通过：提示独立于窗口还在显示（%d 个像素被改动）' % d_tip)
    if d_gone > 500:
        print('  => **问题：2.8 秒后提示还在，没自己收掉**')
        ok = False
    else:
        print('  => 通过：2.8 秒后提示自己消失了（残留变化 %d）' % d_gone)
    if len(vis_28) != 0:
        print('  => **问题：2.8 秒后进程还剩 %d 个可见窗口（提示没销毁）**' % len(vis_28))
        ok = False
    else:
        print('  => 通过：2.8 秒后本进程没有可见窗口了')
    if not text:
        print('  => **问题：剪切板里没有内容，二维码没识别出来**')
        ok = False
    else:
        print('  => 通过：剪切板拿到了二维码内容')
    return 0 if ok else 1


if __name__ == '__main__':
    rc = main()
    print('\n===== 退出码 %d =====' % rc)
    sys.exit(rc)
