"""一个可滚动的测试窗口（独立进程跑）。

用途：给"截长图"当目标窗口。虚拟内容高 CONTENT_H，窗口只有客户区那么高；
每 16px 一块的颜色由 (行号, 块号) 决定 —— 这样每一行的灰度图样都不同，
既能让拼接算法精确匹配，也方便事后逐行核对有没有漏行。
滚轮按"一格 = 100px"处理（浏览器量级），滚动量打印出来供测试脚本核对。

启动后往 stdout 打印一行 "RECT left top width height"，然后进入消息循环。
"""
import ctypes
import sys
from ctypes import wintypes

user32 = ctypes.WinDLL('user32', use_last_error=True)
gdi32 = ctypes.WinDLL('gdi32', use_last_error=True)
kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    pass

CONTENT_H = 4000
BLOCK = 16
WHEEL_PX = 100          # 一格滚轮滚多少像素
WIN_W, WIN_H = 700, 760
WIN_X, WIN_Y = 300, 150

WS_OVERLAPPEDWINDOW = 0x00CF0000
WS_VISIBLE = 0x10000000
WM_PAINT = 0x000F
WM_MOUSEWHEEL = 0x020A
WM_DESTROY = 0x0002
WM_ERASEBKGND = 0x0014

WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_longlong, wintypes.HWND, wintypes.UINT,
                             wintypes.WPARAM, wintypes.LPARAM)


class WNDCLASSEXW(ctypes.Structure):
    _fields_ = [
        ('cbSize', wintypes.UINT),
        ('style', wintypes.UINT),
        ('lpfnWndProc', WNDPROC),
        ('cbClsExtra', ctypes.c_int),
        ('cbWndExtra', ctypes.c_int),
        ('hInstance', wintypes.HINSTANCE),
        ('hIcon', wintypes.HANDLE),
        ('hCursor', wintypes.HANDLE),
        ('hbrBackground', wintypes.HANDLE),
        ('lpszMenuName', wintypes.LPCWSTR),
        ('lpszClassName', wintypes.LPCWSTR),
        ('hIconSm', wintypes.HANDLE),
    ]

class PAINTSTRUCT(ctypes.Structure):
    _fields_ = [
        ('hdc', wintypes.HDC),
        ('fErase', wintypes.BOOL),
        ('rcPaint', wintypes.RECT),
        ('fRestore', wintypes.BOOL),
        ('fIncUpdate', wintypes.BOOL),
        ('rgbReserved', ctypes.c_byte * 32),
    ]


scroll_y = 0
client_w, client_h = WIN_W, WIN_H


def block_gray(y, bx):
    """内容第 y 行、第 bx 块的颜色（灰度）。
    用哈希而不是线性式子 —— 线性式子的灰度序列会周期重复（比如 y*7 每 256 行一轮），
    那样"按行号核对拼接结果"就会失去判别力：偏移恰好是周期整数倍时看起来也对得上"""
    h = (y * 2654435761) ^ (bx * 40503) ^ (y << 13)
    return ((h >> 11) ^ (h >> 3)) & 0xFF


def on_paint(hwnd):
    ps = PAINTSTRUCT()
    hdc = user32.BeginPaint(hwnd, ctypes.byref(ps))
    for row in range(client_h):
        y = scroll_y + row
        if y >= CONTENT_H:
            break
        for bx in range(client_w // BLOCK + 1):
            g = block_gray(y, bx)
            hb = gdi32.CreateSolidBrush(g * 0x010101)   # 灰度 → 0xRRGGBB
            r = wintypes.RECT(bx * BLOCK, row, min((bx + 1) * BLOCK, client_w), row + 1)
            user32.FillRect(hdc, ctypes.byref(r), hb)
            gdi32.DeleteObject(wintypes.HANDLE(hb))
    user32.EndPaint(hwnd, ctypes.byref(ps))


@WNDPROC
def wndproc(hwnd, msg, wparam, lparam):
    global scroll_y, client_w, client_h
    if msg == WM_ERASEBKGND:
        return 1
    if msg == WM_PAINT:
        on_paint(hwnd)
        return 0
    if msg == WM_MOUSEWHEEL:
        delta = ctypes.c_short((wparam >> 16) & 0xFFFF).value
        notches = delta / 120.0
        max_scroll = max(0, CONTENT_H - client_h)
        before = scroll_y
        scroll_y = int(max(0, min(max_scroll, scroll_y - notches * WHEEL_PX)))
        print('SCROLL %d -> %d (delta=%d)' % (before, scroll_y, delta), flush=True)
        user32.InvalidateRect(hwnd, None, True)
        return 0
    if msg == WM_DESTROY:
        user32.PostQuitMessage(0)
        return 0
    return user32.DefWindowProcW(hwnd, msg, wparam, lparam)


def main():
    global client_w, client_h
    # 不声明 argtypes 的话 ctypes 会按 32 位传参，句柄/消息参数一大就 OverflowError
    user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.DefWindowProcW.restype = wintypes.LPARAM
    user32.BeginPaint.argtypes = [wintypes.HWND, ctypes.POINTER(PAINTSTRUCT)]
    user32.BeginPaint.restype = wintypes.HDC
    user32.EndPaint.argtypes = [wintypes.HWND, ctypes.POINTER(PAINTSTRUCT)]
    user32.FillRect.argtypes = [wintypes.HDC, ctypes.POINTER(wintypes.RECT), wintypes.HANDLE]
    gdi32.CreateSolidBrush.argtypes = [wintypes.COLORREF]
    gdi32.CreateSolidBrush.restype = wintypes.HANDLE
    gdi32.DeleteObject.argtypes = [wintypes.HANDLE]
    gdi32.DeleteObject.restype = wintypes.BOOL
    kernel32.GetModuleHandleW.restype = wintypes.HINSTANCE
    user32.CreateWindowExW.argtypes = [
        wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
        ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
    user32.CreateWindowExW.restype = wintypes.HWND
    user32.RegisterClassExW.argtypes = [ctypes.POINTER(WNDCLASSEXW)]
    user32.InvalidateRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT), wintypes.BOOL]
    hinst = kernel32.GetModuleHandleW(None)
    cls = WNDCLASSEXW()
    cls.cbSize = ctypes.sizeof(cls)
    cls.style = 0
    cls.lpfnWndProc = wndproc
    cls.hInstance = hinst
    cls.lpszClassName = 'LongCapTarget'
    cls.hbrBackground = None
    if not user32.RegisterClassExW(ctypes.byref(cls)):
        print('ERR 注册窗口类失败 %d' % ctypes.get_last_error(), flush=True)
        return 1
    hwnd = user32.CreateWindowExW(
        0, 'LongCapTarget', 'LongCapture Target',
        WS_OVERLAPPEDWINDOW | WS_VISIBLE,
        WIN_X, WIN_Y, WIN_W, WIN_H, None, None, hinst, None)
    if not hwnd:
        print('ERR 建窗口失败 %d' % ctypes.get_last_error(), flush=True)
        return 1
    r = wintypes.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(r))
    client_w, client_h = r.right - r.left, r.bottom - r.top
    pt = wintypes.POINT(0, 0)
    user32.ClientToScreen(hwnd, ctypes.byref(pt))
    print('RECT %d %d %d %d' % (pt.x, pt.y, client_w, client_h), flush=True)

    msg = wintypes.MSG()
    while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
        user32.TranslateMessage(ctypes.byref(msg))
        user32.DispatchMessageW(ctypes.byref(msg))
    return 0


if __name__ == '__main__':
    sys.exit(main())
