r"""放大镜（取景框）的几何自检 —— 准星到底框住几个源像素、格子多大。

背景（2026-09-21 用户反馈）：
  进截图模式后那个取景框，中心准星看着像框住了 2x2 四个像素，分不清当前取到的
  到底是哪一个；而且每格放大得不够，小字看不清。

判据全部落在**蓝色十字**上（便携配置里 borderWidth=0、背景铺纯黑，
屏幕上唯一的蓝色来源就是它），无需给屏幕铺图案：

  十字的四个臂是从取景框边缘画到中心留白外侧的，所以
  * 横向总跨度 == pixW   = srcW * scaleNum
  * 纵向总跨度 == pixImgH = srcH * scaleNum
  这两个量能反推出"每个源像素放大后占多少物理像素"。
  再扫中心那一行/列，量出两条臂之间**没有蓝色**的那段缺口宽度 —— 那就是准星
  留白，也就能算出它框住了几个源像素（目标：正好 1 个）。

黑底上十字的实际颜色是半透明蓝叠黑 ≈ #0D407F，所以蓝色阈值取"b-r>=50 且 b>=100"。
"""
import ctypes
import os
import subprocess
import sys
import time
from ctypes import wintypes

_HERE0 = os.path.dirname(os.path.abspath(__file__))
_PYLIBS = os.path.normpath(os.path.join(_HERE0, '..', '..', '_tools', '.pylibs'))
if os.path.isdir(_PYLIBS) and _PYLIBS not in sys.path:
    sys.path.insert(0, _PYLIBS)

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    pass

user32 = ctypes.WinDLL('user32', use_last_error=True)
gdi32 = ctypes.WinDLL('gdi32', use_last_error=True)
kernel32 = ctypes.windll.kernel32
kernel32.GetModuleHandleW.restype = ctypes.c_void_p

_HERE = os.path.dirname(os.path.abspath(__file__))
_BUILD = os.path.normpath(os.path.join(_HERE, '..', 'build'))
EXE = os.environ.get('SC_EXE') or os.path.join(_BUILD, 'bin', 'x64', 'Release', 'ScreenCapture.build.exe')
EXE_DIR = os.path.dirname(EXE)
PORTABLE_CFG = os.path.join(EXE_DIR, 'config.json')
import _cfg_guard
_cfg_guard.install(PORTABLE_CFG)

LOG_DIR = os.path.join(_BUILD, 'logs')
SHOT = os.path.join(LOG_DIR, 'mag_geometry.png')

# 期望值：改 src/scaleNum 时要同步这里
EXPECT_SCALE = 8.0      # 每个源像素放大后的物理像素数
EXPECT_SRC_W, EXPECT_SRC_H = 50, 30

# 光标停在这里：取景框默认摆在光标右下，放左上角附近给框留足空间
CURSOR = (260, 200)

WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_longlong, wintypes.HWND, ctypes.c_uint,
                             ctypes.c_ulonglong, ctypes.c_longlong)


def _wnd_proc(hwnd, msg, wp, lp):
    return user32.DefWindowProcW(hwnd, msg, wp, lp)


_proc = WNDPROC(_wnd_proc)
user32.RegisterClassExW.restype = ctypes.c_ushort
user32.RegisterClassExW.argtypes = [ctypes.c_void_p]
user32.CreateWindowExW.restype = wintypes.HWND
user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR,
                                   wintypes.DWORD, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                   ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p,
                                   ctypes.c_void_p, ctypes.c_void_p]
user32.DefWindowProcW.restype = ctypes.c_longlong
user32.DefWindowProcW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_ulonglong,
                                  ctypes.c_longlong]
user32.ShowWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]
user32.UpdateWindow.argtypes = [ctypes.c_void_p]
user32.DestroyWindow.argtypes = [ctypes.c_void_p]
user32.IsWindowVisible.argtypes = [ctypes.c_void_p]
user32.IsWindowVisible.restype = wintypes.BOOL
user32.GetWindowRect.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.RECT)]
user32.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD)]
user32.EnumWindows.argtypes = [ctypes.c_void_p, wintypes.LPARAM]
user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
user32.keybd_event.argtypes = [ctypes.c_ubyte, ctypes.c_ubyte, wintypes.DWORD, ctypes.c_void_p]


class WNDCLASSEXW(ctypes.Structure):
    _fields_ = [('cbSize', ctypes.c_uint), ('style', ctypes.c_uint),
                ('lpfnWndProc', ctypes.c_void_p), ('cbClsExtra', ctypes.c_int),
                ('cbWndExtra', ctypes.c_int), ('hInstance', ctypes.c_void_p),
                ('hIcon', ctypes.c_void_p), ('hCursor', ctypes.c_void_p),
                ('hbrBackground', ctypes.c_void_p), ('lpszMenuName', ctypes.c_wchar_p),
                ('lpszClassName', ctypes.c_wchar_p), ('hIconSm', ctypes.c_void_p)]


def make_black_window():
    cls = 'MagGeomBlackWnd'
    hinst = kernel32.GetModuleHandleW(None)
    wc = WNDCLASSEXW()
    wc.cbSize = ctypes.sizeof(wc)
    wc.lpfnWndProc = ctypes.cast(_proc, ctypes.c_void_p)
    wc.hInstance = hinst
    wc.hbrBackground = gdi32.CreateSolidBrush(0x000000)
    wc.lpszClassName = cls
    user32.RegisterClassExW(ctypes.byref(wc))
    vx, vy = user32.GetSystemMetrics(76), user32.GetSystemMetrics(77)
    vw, vh = user32.GetSystemMetrics(78), user32.GetSystemMetrics(79)
    hwnd = user32.CreateWindowExW(0x8 | 0x80, cls, 'mag-geom-test',
                                  0x80000000, vx, vy, vw, vh, None, None, hinst, None)
    user32.ShowWindow(hwnd, 5)
    user32.UpdateWindow(hwnd)
    return hwnd


def click_shot_hotkey():
    user32.keybd_event(0x70, 0, 0, 0)
    time.sleep(0.06)
    user32.keybd_event(0x70, 0, 2, 0)


def overlay_hwnd(pid, timeout=8.0):
    CB = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    deadline = time.time() + timeout
    while time.time() < deadline:
        found = []

        def cb(h, _):
            p = ctypes.c_uint()
            user32.GetWindowThreadProcessId(h, ctypes.byref(p))
            if p.value == pid and user32.IsWindowVisible(h):
                r = wintypes.RECT()
                user32.GetWindowRect(h, ctypes.byref(r))
                if r.right - r.left > 1000 and r.bottom - r.top > 600:
                    found.append(h)
            return True

        user32.EnumWindows(CB(cb), 0)
        if found:
            return found[0]
        time.sleep(0.3)
    return None


def blue_mask(im):
    from PIL import ImageChops
    r, g, b = im.split()[:3]
    m1 = ImageChops.subtract(b, r).point(lambda v: 255 if v >= 50 else 0)
    m2 = b.point(lambda v: 255 if v >= 100 else 0)
    return ImageChops.multiply(m1, m2)


def run_gap(mask, y, x0, x1):
    """在 y 这一行、x0..x1 之间找**最长的连续非蓝色段**，返回 (起点, 终点, 长度)。
    准星留白就是中心那条最长的缺口。"""
    px = mask.load()
    best = (0, 0, 0)
    cur_s = None
    for x in range(x0, x1):
        if px[x, y] == 0:
            if cur_s is None:
                cur_s = x
        else:
            if cur_s is not None:
                if x - cur_s > best[2]:
                    best = (cur_s, x - 1, x - cur_s)
                cur_s = None
    if cur_s is not None and x1 - cur_s > best[2]:
        best = (cur_s, x1 - 1, x1 - cur_s)
    return best


def run_gap_col(mask, x, y0, y1):
    px = mask.load()
    best = (0, 0, 0)
    cur_s = None
    for y in range(y0, y1):
        if px[x, y] == 0:
            if cur_s is None:
                cur_s = y
        else:
            if cur_s is not None:
                if y - cur_s > best[2]:
                    best = (cur_s, y - 1, y - cur_s)
                cur_s = None
    if cur_s is not None and y1 - cur_s > best[2]:
        best = (cur_s, y1 - 1, y1 - cur_s)
    return best


def main():
    with open(PORTABLE_CFG, 'w', encoding='utf-16') as f:
        f.write('{"common":{"autoStart":false,"language":"zh-CN","borderWidth":0},'
                '"shortcutKey":{"cap":"F1","pin":"F3"}}')

    from PIL import ImageGrab
    os.makedirs(LOG_DIR, exist_ok=True)
    scr = (user32.GetSystemMetrics(0), user32.GetSystemMetrics(1))
    print('屏幕: %dx%d' % scr)

    black = make_black_window()
    time.sleep(0.6)
    ok = True
    proc = subprocess.Popen([EXE])
    try:
        time.sleep(4.0)
        click_shot_hotkey()
        if not overlay_hwnd(proc.pid):
            print('!! 覆盖层没出现（F1 没生效？）')
            return 1
        time.sleep(1.0)
        user32.SetCursorPos(*CURSOR)
        time.sleep(0.8)

        im = ImageGrab.grab().convert('RGB')
        im.save(SHOT)
        print('（已存图 ext/build/logs/mag_geometry.png）')

        mask = blue_mask(im)
        cnt = mask.histogram()[255]
        bbox = mask.getbbox()
        if not bbox:
            print('!! 画面上没有蓝色 → 十字没画出来')
            return 1
        bx0, by0, bx1, by1 = bbox
        cross_w = bx1 - bx0
        cross_h = by1 - by0
        print('蓝色(十字)包围盒 x %d..%d y %d..%d  像素数 %d' % (bx0, bx1 - 1, by0, by1 - 1, cnt))
        print('十字横向跨度 %d  纵向跨度 %d' % (cross_w, cross_h))

        # 十字总跨 == 取景框内尺寸（臂从框边画到中心留白外侧）
        exp_w = EXPECT_SRC_W * EXPECT_SCALE
        exp_h = EXPECT_SRC_H * EXPECT_SCALE
        if abs(cross_w - exp_w) > 3:
            print('!! 横向跨度 %d，期望 %d（srcW %d × scale %.0f）' % (cross_w, exp_w, EXPECT_SRC_W, EXPECT_SCALE))
            ok = False
        else:
            print('✔ 横向跨度 %d == %d 个源像素 × %.0f' % (cross_w, EXPECT_SRC_W, EXPECT_SCALE))
        if abs(cross_h - exp_h) > 3:
            print('!! 纵向跨度 %d，期望 %d' % (cross_h, exp_h))
            ok = False
        else:
            print('✔ 纵向跨度 %d == %d 个源像素 × %.0f' % (cross_h, EXPECT_SRC_H, EXPECT_SCALE))

        # 中心留白：扫包围盒正中那一行 / 那一列，找最长缺口
        cy = (by0 + by1) // 2
        cx = (bx0 + bx1) // 2
        gx0, gx1, gw = run_gap(mask, cy, bx0, bx1 + 1)
        gy0, gy1, gh = run_gap_col(mask, cx, by0, by1 + 1)
        print('中心留白：横向 x %d..%d（宽 %d）  纵向 y %d..%d（高 %d）'
              % (gx0, gx1, gw, gy0, gy1, gh))

        # 留白宽 / 每格大小 就是"准星框住了几个源像素"
        px_per_cell = cross_w / EXPECT_SRC_W
        n_x = gw / px_per_cell
        n_y = gh / px_per_cell
        print('每个源像素占 %.2f 物理像素；准星留白覆盖 %.2f × %.2f 个源像素'
              % (px_per_cell, n_x, n_y))

        if abs(n_x - 1.0) > 0.25 or abs(n_y - 1.0) > 0.25:
            print('!! 准星留白不是 1 个源像素（期望约 1×1）')
            ok = False
        else:
            print('✔ 准星留白的正好是 1 个源像素')

        # 留白中心应该落在取景框正中（也就是光标那个像素上）
        if abs((gx0 + gx1) / 2 - (bx0 + bx1) / 2) > 2 or abs((gy0 + gy1) / 2 - (by0 + by1) / 2) > 2:
            print('   !! 留白没对准取景框中心')
            ok = False
        else:
            print('✔ 留白正好落在取景框中心')
    finally:
        try:
            proc.kill()
            proc.wait(timeout=5)
        except Exception:
            pass
        if black:
            user32.DestroyWindow(black)
    print()
    print('=>', '通过：准星正好框住 1 个源像素，放大倍率 %.0f' % EXPECT_SCALE
          if ok else '**未通过**')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
