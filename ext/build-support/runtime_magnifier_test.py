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

import _pylibs  # noqa: F401  —— 把 ext/build/.pylibs（Pillow）挂进 sys.path

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
EXE = os.environ.get('SC_EXE') or os.path.join(_BUILD, 'bin', 'x64', 'Release', 'ZPin.build.exe')
EXE_DIR = os.path.dirname(EXE)
PORTABLE_CFG = os.path.join(EXE_DIR, 'config.json')
import _cfg_guard          # 这行文件就是 <exe 同目录>\config.json = 用户真实配置，得护栏
_cfg_guard.install(PORTABLE_CFG)

LOG_DIR = os.path.join(_BUILD, 'logs')

# 拖框的起点与终点（屏幕坐标）。要点：**两侧都要留得下取景框**。
# 取景框尺寸 = srcW×srcH × scaleNum（WinCap.cpp 顶部那组常量），scaleNum 一改
# 就得重新核这两个点 —— 否则光标贴边时 setPixPos 会按既有逻辑把框翻到另一侧，
# "避让方向"那条断言就会误报（放大镜从 250 宽变 400 宽后就撞过一次：
# 终点 (300,300) 左侧只剩 300px，装不下 400 的框，框翻到了右边）。
# 另外这两点还决定了下面要铺多大一块黑底（见 main 里的 patch 计算），
# 拖得越远黑块越大 —— 够验证"跟随 + 避让"就行，不必拉很长。
P1 = (700, 500)
P2 = (950, 650)

# 放大镜参数，镜像 WinCap.cpp 顶部那组 constexpr —— 那边改了这里要同步
SCALE = 8.0
SRC_W, SRC_H = 50, 30

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


def make_black_patch(x, y, w, h):
    """在指定矩形铺一块**小**黑窗，只盖住放大镜会从屏幕采样的那一片。

    ⚠ 这里以前铺的是**全屏**黑 topmost 窗，跑十几秒还压着任务栏 ——
    用户看到就是"测试把屏幕搞黑了"（2026-09-21 连夜改掉）。
    完全没必要：取景框里的图像来自 **F1 抓屏那一刻**（screenImg 在覆盖层 show
    之前抓的），而它取的只是**光标周围 srcW×srcH 那一小块**。所以只要把
    光标会经过的那片区域铺黑，取景框里就是黑的、十字叠上去颜色就确定，
    屏幕其余部分保持原样。
    尺寸按"拖框起终点围出来的矩形 + 取样半径 + 余量"算，见 main()。
    """
    cls = 'MagTestBlackPatch'
    hinst = kernel32.GetModuleHandleW(None)
    wc = WNDCLASSEXW()
    wc.cbSize = ctypes.sizeof(wc)
    wc.lpfnWndProc = ctypes.cast(_proc, ctypes.c_void_p)
    wc.hInstance = hinst
    wc.hbrBackground = gdi32.CreateSolidBrush(0x000000)
    wc.lpszClassName = cls
    if not user32.RegisterClassExW(ctypes.byref(wc)):
        print('!! RegisterClassExW 失败，err=%d' % ctypes.get_last_error())
    WS_EX_TOPMOST, WS_EX_TOOLWINDOW = 0x8, 0x80
    WS_POPUP = 0x80000000
    hwnd = user32.CreateWindowExW(WS_EX_TOPMOST | WS_EX_TOOLWINDOW, cls, 'mag-test',
                                  WS_POPUP, x, y, w, h, None, None, hinst, None)
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


def grab(name, box=None):
    """截图。传 box 就只存那一块（顺便省得日志目录堆全屏大图）"""
    from PIL import ImageGrab
    os.makedirs(LOG_DIR, exist_ok=True)
    im = ImageGrab.grab()
    if box:
        im = im.crop(box)
    im.save(os.path.join(LOG_DIR, 'mag_%s.png' % name))
    return im


def magnifier_rect(cursor, prefer_left, prefer_top):
    """算出取景框会画在哪 —— 复刻 WinCap::setPixPos 的算法。

    ⚠ 为什么要自己算：不铺全屏黑底之后，桌面本来就有大片蓝色（实测两万多个像素、
    包围盒几乎铺满屏幕），全屏统计蓝像素会被污染。只统计取景框自己那块矩形就干净了。
    ⚠ 这段和 setPixPos 是**耦合**的：那边改了摆位规则（span / 翻转条件 / 信息行高度），
    这里要跟着改。几何测试 runtime_magnifier_geometry_test.py 里也有一份同样的算法，
    并且它的预期位置与实际渲染结果是逐像素对得上的，可以拿来交叉验证。
    """
    hdc = user32.GetDC(0)
    dpi = gdi32.GetDeviceCaps(hdc, 88) / 96.0
    user32.ReleaseDC(0, hdc)
    scr_w, scr_h = user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
    span = 10 * dpi
    pix_w = SRC_W * SCALE
    pix_h = SRC_H * SCALE
    info_h = 76 * dpi                      # 下面那四行 HEX/RGB/CMYK/POS
    d = int(dpi)
    if prefer_left:
        x = int(cursor[0] - span - pix_w + d)
        if x < 0:
            x = int(cursor[0] + span + d)
    else:
        x = int(cursor[0] + span + d)
        if x + pix_w > scr_w:
            x = int(cursor[0] - span - pix_w + d)
    if prefer_top:
        y = int(cursor[1] - span - pix_h - info_h + d)
        if y < 0:
            y = int(cursor[1] + span + d)
    else:
        y = int(cursor[1] + span + d)
        if y + pix_h + info_h > scr_h:
            y = int(cursor[1] - span - pix_h - info_h + d)
    return (x, y, x + pix_w, y + pix_h)


def blue_mask(im, box=None):
    """蓝色像素的 0/255 掩码（可只取 box 那块）。

    十字是半透明蓝（ColorF(0.1,0.5,1,0.5)）叠在取景框的黑底上 → 实测 #0D407F
    （b=127），所以阈值不能按"接近纯蓝"卡，50 / 100 这种松弛值就够。
    """
    from PIL import ImageChops
    if box:
        im = im.crop(box)
    r, g, b = im.split()[:3]
    m1 = ImageChops.subtract(b, r).point(lambda v: 255 if v >= 50 else 0)
    m2 = b.point(lambda v: 255 if v >= 100 else 0)
    return ImageChops.multiply(m1, m2)      # 两张 0/255 蒙版相乘 = 取交集


def bbox_screen(mask, box):
    """掩码的包围盒，换算成屏幕坐标（box 是 crop 的偏移）"""
    bb = mask.getbbox()
    if not bb:
        return None
    if box:
        bb = (bb[0] + box[0], bb[1] + box[1], bb[2] + box[0], bb[3] + box[1])
    return bb


def cross_runs(mask):
    """量出这块区域里"最长的连续蓝色横段"和"最长连续蓝色竖段"（像素）。

    ⚠ 为什么不用"蓝色像素数 >= N"当判据：桌面本来就有大片蓝色，连**终端的蓝色
    路径文字**都能凑出几百个蓝像素、把判据骗过去（实测松手后那轮就是这么误报的：
    残留的"蓝色"其实是我自己终端窗口里的一行字）。

    ⚠ 阈值为什么是 150 / 90 而不是 400 / 240：**十字是挖空的** —— 中心留白把每条臂
    都从中间截断了，所以"最长连续段"只有半个臂：
      横臂半段 = pixW/2 - crossWHalf = 400/2 - 4 = 196
      竖臂半段 = pixImgH/2 - crossWHalf = 240/2 - 4 = 116
    （一开始按整臂 400/240 卡阈值，结果十字明明在图上、判据却全 False。）

    双条件（横 >= 150 且竖 >= 90）已经足够特异：文字笔画是断的，而一个 150px 宽的
    蓝色按钮不会有 90px 高的连续竖段 —— 不再依赖"屏幕上没有别的蓝色"这个假设。
    """
    w, h = mask.size
    px = mask.load()
    best_row = 0
    for y in range(h):
        run = 0
        for x in range(w):
            run = run + 1 if px[x, y] else 0
            if run > best_row:
                best_row = run
    best_col = 0
    for x in range(w):
        run = 0
        for y in range(h):
            run = run + 1 if px[x, y] else 0
            if run > best_col:
                best_col = run
    return best_row, best_col


def has_cross(mask):
    """区域内是否画着放大镜的十字（横臂半段 + 竖臂半段都够长）。"""
    row_run, col_run = cross_runs(mask)
    return row_run >= 150 and col_run >= 90, row_run, col_run


def probe(im, box):
    """对取景框那一块做一次判读，返回 dict"""
    m = blue_mask(im, box)
    found, row_run, col_run = has_cross(m)
    return {'cross': found, 'runs': (row_run, col_run), 'bbox': bbox_screen(m, box)}


def center(bbox):
    return ((bbox[0] + bbox[2]) // 2, (bbox[1] + bbox[3]) // 2)


def move(x, y):
    user32.SetCursorPos(x, y)


def button(down):
    user32.mouse_event(0x0002 if down else 0x0004, 0, 0, 0, 0)


def run_round(start, end, tag):
    """一轮完整验证：A 未按下 / B 拖动中 / C 松开后，各截一张图 —— 而且每次只判读
    **取景框自己那块矩形**（屏幕别处的蓝色不算，见 magnifier_rect 的说明）。
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

        # ⚠ 先挪到别处再回来：上一轮结束时鼠标可能就停在 start 上，SetCursorPos 到
        #    同一个坐标**不会产生移动消息**，onMove 不跑 → 取景框不画、而且按下会被
        #    当成"在旧选区上做调整"（不进框选）。实测 rev 轮就是这么整轮失效的
        move(start[0] - 180, start[1] - 150)
        time.sleep(0.25)
        move(*start)
        time.sleep(0.6)
        box_a = magnifier_rect(start, False, False)
        a = probe(grab('%s_A_before_press' % tag), box_a)

        button(True)
        time.sleep(0.2)
        for i in range(1, 9):        # 分几步移动，像真人拖拽
            move(start[0] + (end[0] - start[0]) * i // 8,
                 start[1] + (end[1] - start[1]) * i // 8)
            time.sleep(0.06)
        time.sleep(0.6)
        # B：拖动中取景框摆在背离拖动方向那一侧（onMove 里的 preferLeft/preferTop）
        box_b = magnifier_rect(end, end[0] < start[0], end[1] < start[1])
        b = probe(grab('%s_B_dragging' % tag), box_b)
        button(False)

        time.sleep(0.8)
        # C：松手后取景框该收起 —— 还按 B 那块位置判读，十字应当没了
        c = probe(grab('%s_C_after_release' % tag), box_b)
        return a['cross'], a['bbox'], b['cross'], b['bbox'], c['cross'], c['bbox']
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
    a_has, a_box, b_has, b_box, c_has, c_box = res
    print('A 未按下   : 十字=%-5s 包围盒=%s' % (a_has, a_box))
    print('B 拖动中   : 十字=%-5s 包围盒=%s' % (b_has, b_box))
    print('C 松开后   : 十字=%-5s 包围盒=%s' % (c_has, c_box))
    ok = True

    # A：起点处有放大镜（还没按下时就该有，原本就有这个行为）
    if not a_has:
        print('   !! A 未按下时就没看到放大镜')
        ok = False
    else:
        print('   ✔ A 未按下：放大镜在光标附近，中心 %s' % (center(a_box),))

    # B：拖动中仍有放大镜，且跟着光标搬家 —— 这是本次要修的
    if not b_has:
        print('   !! B 拖动中放大镜不见了 —— 就是用户报的那个问题')
        ok = False
    else:
        cx, cy = center(b_box)
        # 只断言"取景框就在终点旁边"：不能用 A→B 的位移来断言 ——
        # 往左上拖时取景框会翻到光标左上侧，位移里天然多出一个翻转量
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
    if c_has:
        print('   !! C 松开后放大镜没收起来（与原有行为不符）')
        ok = False
    else:
        print('   ✔ C 松开后：放大镜已收起')
    return ok


def main():
    # 便携配置：borderWidth=0 → 选区不画蓝边框，屏幕上的蓝色来源就只剩放大镜的十字
    with open(PORTABLE_CFG, 'w', encoding='utf-16') as f:
        f.write('{"common":{"autoStart":false,"language":"zh-CN","borderWidth":0},'
                '"shortcutKey":{"cap":"F1","pin":"F3"}}')

    scr_w, scr_h = user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
    print('屏幕: %dx%d' % (scr_w, scr_h))

    # 黑块只盖住"拖框起终点围出的矩形 + 取样半径 + 余量"：
    # 取景框要从这里取像，黑底才能让十字颜色确定（不再铺全屏）
    SRC_HALF_W, SRC_HALF_H = 25, 15     # srcW/2, srcH/2（WinCap.cpp 那组常量）
    pad = 20
    px0 = min(P1[0], P2[0]) - SRC_HALF_W - pad
    py0 = min(P1[1], P2[1]) - SRC_HALF_H - pad
    px1 = max(P1[0], P2[0]) + SRC_HALF_W + pad
    py1 = max(P1[1], P2[1]) + SRC_HALF_H + pad
    patch = (px0, py0, px1 - px0, py1 - py0)
    print('黑块 %s（%.0f×%.0f，只盖住采样区）'
          % (str(patch), patch[2], patch[3]))

    black = make_black_patch(*patch)
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
