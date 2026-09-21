r"""放大镜在拖框过程中是否跟随光标。

2026-09-21 用户反馈：进截图模式后，鼠标还没点下去时有放大镜（取景框 + 十字 +
HEX/RGB/CMYK/POS 四行信息），一按下开始拖框它就没了 —— 于是"起点能对准、
终点只能靠感觉"。

三个状态各截一张全屏图（A 未按下 / B 拖动中 / C 松开后）：
  A. 光标停在起点        → 应有放大镜
  B. 按下不放、移到终点  → **应有放大镜，且跟着光标移到终点那侧**（本次修复点）
  C. 松开（进调选区阶段）→ 放大镜收起（原有行为，作为对照）

判据用**蓝色十字**：crossBrush 是半透明蓝，而在便携配置里把 borderWidth 设成 0
（选区边框不画）、又铺一个纯黑的测试窗口当背景，画面上唯一的蓝色来源就是它。
比起"找白字"，它不会被工具条图标、任务栏时钟之类的白点干扰。

放大镜显示的是"F1 那一刻的屏幕画面"（screenImg 在覆盖层 show 之前抓的），
所以黑色测试窗口要在启动程序**之前**铺好 —— 这样取景框里也是黑的，蓝色十字更干净。
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
gdi32 = ctypes.WinDLL('gdi32', use_last_error=True)
kernel32 = ctypes.windll.kernel32
kernel32.GetModuleHandleW.restype = ctypes.c_void_p

_HERE = os.path.dirname(os.path.abspath(__file__))
_BUILD = os.path.normpath(os.path.join(_HERE, '..', 'build'))
EXE = os.environ.get('SC_EXE') or os.path.join(_BUILD, 'bin', 'x64', 'Release', 'ScreenCapture.build.exe')
EXE_DIR = os.path.dirname(EXE)
PORTABLE_CFG = os.path.join(EXE_DIR, 'config.json')
import _cfg_guard          # 这行文件就是 <exe 同目录>\config.json = 用户真实配置，得护栏
_cfg_guard.install(PORTABLE_CFG)

LOG_DIR = os.path.join(_BUILD, 'logs')

# 拖框的起点与终点（屏幕坐标）。取屏幕靠上的位置，保证放大镜（约 250x245）不会溢出屏幕
P1 = (300, 300)
P2 = (900, 700)

WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_longlong, wintypes.HWND, ctypes.c_uint,
                             ctypes.c_ulonglong, ctypes.c_longlong)


def _wnd_proc(hwnd, msg, wp, lp):
    return user32.DefWindowProcW(hwnd, msg, wp, lp)


_proc = WNDPROC(_wnd_proc)

# ctypes 对没声明过的函数按 int 推断参数 —— 64 位句柄（hInstance/HWND）和
# 0x80000000 这种超 int 范围的样式常量会被当成溢出报 ArgumentError，必须显式声明
user32.CreateWindowExW.restype = wintypes.HWND
user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR,
                                   wintypes.DWORD, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                   ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p,
                                   ctypes.c_void_p, ctypes.c_void_p]
user32.DefWindowProcW.restype = ctypes.c_longlong
user32.DefWindowProcW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_ulonglong,
                                  ctypes.c_longlong]
user32.RegisterClassExW.restype = ctypes.c_ushort
user32.RegisterClassExW.argtypes = [ctypes.c_void_p]
user32.ShowWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]
user32.UpdateWindow.argtypes = [ctypes.c_void_p]
user32.DestroyWindow.argtypes = [ctypes.c_void_p]
user32.IsWindowVisible.argtypes = [ctypes.c_void_p]
user32.IsWindowVisible.restype = wintypes.BOOL
user32.GetWindowRect.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.RECT)]
user32.GetWindowRect.restype = wintypes.BOOL
user32.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
user32.EnumWindows.argtypes = [ctypes.c_void_p, wintypes.LPARAM]
user32.EnumWindows.restype = wintypes.BOOL
user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
user32.keybd_event.argtypes = [ctypes.c_ubyte, ctypes.c_ubyte, wintypes.DWORD, ctypes.c_void_p]
user32.mouse_event.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
                               wintypes.DWORD, ctypes.c_void_p]
user32.GetSystemMetrics.restype = ctypes.c_int


class WNDCLASSEXW(ctypes.Structure):
    _fields_ = [('cbSize', ctypes.c_uint), ('style', ctypes.c_uint),
                ('lpfnWndProc', ctypes.c_void_p), ('cbClsExtra', ctypes.c_int),
                ('cbWndExtra', ctypes.c_int), ('hInstance', ctypes.c_void_p),
                ('hIcon', ctypes.c_void_p), ('hCursor', ctypes.c_void_p),
                ('hbrBackground', ctypes.c_void_p), ('lpszMenuName', ctypes.c_wchar_p),
                ('lpszClassName', ctypes.c_wchar_p), ('hIconSm', ctypes.c_void_p)]


def make_black_window():
    """铺一块纯黑的 topmost 窗口：既压住任务栏（省得它的白字干扰判读），
    又让放大镜取景框里是黑的"""
    cls = 'MagTestBlackWnd'
    hinst = kernel32.GetModuleHandleW(None)
    wc = WNDCLASSEXW()
    wc.cbSize = ctypes.sizeof(wc)
    wc.lpfnWndProc = ctypes.cast(_proc, ctypes.c_void_p)
    wc.hInstance = hinst
    wc.hbrBackground = gdi32.CreateSolidBrush(0x000000)
    wc.lpszClassName = cls
    if not user32.RegisterClassExW(ctypes.byref(wc)):
        print('!! RegisterClassExW 失败，err=%d' % ctypes.get_last_error())
    vx, vy = user32.GetSystemMetrics(76), user32.GetSystemMetrics(77)
    vw, vh = user32.GetSystemMetrics(78), user32.GetSystemMetrics(79)
    WS_EX_TOPMOST, WS_EX_TOOLWINDOW = 0x8, 0x80
    WS_POPUP = 0x80000000
    hwnd = user32.CreateWindowExW(WS_EX_TOPMOST | WS_EX_TOOLWINDOW, cls, 'mag-test',
                                  WS_POPUP, vx, vy, vw, vh, None, None, hinst, None)
    if not hwnd:
        print('!! CreateWindowExW 失败，err=%d' % ctypes.get_last_error())
    user32.ShowWindow(hwnd, 5)
    user32.UpdateWindow(hwnd)
    return hwnd


def click_shot_hotkey():
    """按真 F1 唤出截图覆盖层（探针同款做法）"""
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


def grab(name):
    from PIL import ImageGrab
    os.makedirs(LOG_DIR, exist_ok=True)
    im = ImageGrab.grab()
    im.save(os.path.join(LOG_DIR, 'mag_%s.png' % name))
    return im


def blue_stats(im):
    """蓝色像素数 + 包围盒。
    十字是半透明蓝（ColorF(0.1,0.5,1,0.5)）叠在黑底上 → 实测 #0D407F（b=127），
    所以 b 的阈值不能按"接近纯蓝"来卡，50 / 100 这种松弛值就够 —— 屏幕上
    没有别的蓝色来源（选区边框已在便携配置里关掉）"""
    from PIL import ImageChops
    r, g, b = im.split()[:3]
    m1 = ImageChops.subtract(b, r).point(lambda v: 255 if v >= 50 else 0)
    m2 = b.point(lambda v: 255 if v >= 100 else 0)
    m = ImageChops.multiply(m1, m2)      # 两张 0/255 蒙版相乘 = 取交集
    return m.histogram()[255], m.getbbox()


def center(bbox):
    return ((bbox[0] + bbox[2]) // 2, (bbox[1] + bbox[3]) // 2)


def move(x, y):
    user32.SetCursorPos(x, y)


def button(down):
    user32.mouse_event(0x0002 if down else 0x0004, 0, 0, 0, 0)


def run_round(start, end, tag):
    """一轮完整验证：A 未按下 / B 拖动中 / C 松开后，各截一张图。
    每轮都重新起一个进程 —— 第一次松开后会进"调整选区"阶段，那个窗口不关掉，
    再按 F1 只会更新目标功能、不会新建窗口"""
    proc = subprocess.Popen([EXE])
    pid = proc.pid
    try:
        time.sleep(4.0)
        click_shot_hotkey()
        hwnd = overlay_hwnd(pid)
        if not hwnd:
            print('!! 覆盖层没出现（F1 没生效？）')
            return None
        time.sleep(1.0)

        move(*start)
        time.sleep(0.6)
        a_cnt, a_box = blue_stats(grab('%s_A_before_press' % tag))

        button(True)
        time.sleep(0.2)
        for i in range(1, 9):        # 分几步移动，像真人拖拽
            move(start[0] + (end[0] - start[0]) * i // 8,
                 start[1] + (end[1] - start[1]) * i // 8)
            time.sleep(0.06)
        time.sleep(0.6)
        b_cnt, b_box = blue_stats(grab('%s_B_dragging' % tag))
        button(False)

        time.sleep(0.8)
        c_cnt, c_box = blue_stats(grab('%s_C_after_release' % tag))
        return hwnd, a_cnt, a_box, b_cnt, b_box, c_cnt, c_box
    finally:
        try:
            proc.kill()
            proc.wait(timeout=5)
        except Exception:
            pass


def check(start, end, tag, res):
    print('--- 第 %s 轮：%s -> %s ---' % (tag, start, end))
    if res is None:
        return False
    _, a_cnt, a_box, b_cnt, b_box, c_cnt, c_box = res
    print('A 未按下   : 蓝像素=%-6d 包围盒=%s' % (a_cnt, a_box))
    print('B 拖动中   : 蓝像素=%-6d 包围盒=%s' % (b_cnt, b_box))
    print('C 松开后   : 蓝像素=%-6d 包围盒=%s' % (c_cnt, c_box))
    ok = True

    # A：起点处有放大镜（还没按下时就该有，原本就有这个行为）
    if a_cnt < 200:
        print('   !! A 未按下时就没看到放大镜（判据本身有问题？）')
        ok = False
    else:
        print('   ✔ A 未按下：放大镜在光标附近，中心 %s' % (center(a_box),))

    # B：拖动中仍有放大镜，且跟着光标搬家 —— 这是本次要修的
    if b_cnt < 200:
        print('   !! B 拖动中放大镜不见了 —— 就是用户报的那个问题')
        ok = False
    else:
        cx, cy = center(b_box)
        # 只断言"取景框就在终点旁边"：不能用 A→B 的位移来断言 ——
        # 往左上拖时取景框会翻到光标左上侧，位移里天然多出一个翻转量（约 275px）
        if abs(cx - end[0]) > 400 or abs(cy - end[1]) > 400:
            print('   !! B 的取景框没跟到终点附近：中心 (%d,%d)，终点 %s' % (cx, cy, end))
            ok = False
        else:
            print('   ✔ B 拖动中：取景框跟到了终点旁，中心 (%d,%d)' % (cx, cy))
        # 避让：取景框应落在"背离拖动方向"那一侧（向右下拖 → 在光标右下；
        # 向左上拖 → 在光标左上），这样它不会压住正在调的选区
        want_left = end[0] < start[0]
        want_top = end[1] < start[1]
        if (cx < end[0]) != want_left or (cy < end[1]) != want_top:
            print('   !! B 的取景框避让方向不对：中心 (%d,%d)，光标 %s' % (cx, cy, end))
            ok = False
        else:
            print('   ✔ B 取景框落在选区外侧（光标%s）' % ('左上' if want_left else '右下'))

    # C：松开后收起（原有行为，仅作对照）
    if c_cnt >= 200:
        print('   !! C 松开后放大镜没收起来（与原有行为不符）')
        ok = False
    else:
        print('   ✔ C 松开后：放大镜已收起')
    return ok


def main():
    # 便携配置：borderWidth=0 → 选区不画蓝边框，屏幕上唯一的蓝色就是放大镜的十字
    with open(PORTABLE_CFG, 'w', encoding='utf-16') as f:
        f.write('{"common":{"autoStart":false,"language":"zh-CN","borderWidth":0},'
                '"shortcutKey":{"cap":"F1","pin":"F3"}}')

    scr_w, scr_h = user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
    print('屏幕: %dx%d' % (scr_w, scr_h))

    black = make_black_window()
    time.sleep(0.6)
    try:
        ok = True
        # 正向：从左上往右下拖（常见用法）
        ok &= check(P1, P2, 'fwd', run_round(P1, P2, 'fwd'))
        # 反向：从右下往左上拖 —— 取景框要翻到光标左上方去，别盖住选区
        ok &= check(P2, P1, 'rev', run_round(P2, P1, 'rev'))
        print()
        print('=>', '通过：拖框过程中放大镜一直跟着鼠标，且不会压住选区'
              if ok else '**未通过**')
        return 0 if ok else 1
    finally:
        if black:
            user32.DestroyWindow(black)


if __name__ == '__main__':
    sys.exit(main())
