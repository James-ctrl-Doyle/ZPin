"""点"录屏"之后那根工具条还能不能被点到 —— 用 WindowFromPoint 直接问系统：
"这个坐标上的点击会落到哪个窗口？"

之前的回归测试用的是 PostMessage 点击，绕过了系统命中测试，所以"工具条被全屏覆盖层
盖住"这种问题测不出来。这里改成**真鼠标**：真拖框、真悬停、真点按钮，然后逐个按钮
中心问 WindowFromPoint，并打印窗口的 z 序（EnumWindows 是从上往下枚举的）。
"""
import _pylibs  # noqa: F401  —— 把 build/.pylibs（Pillow）挂进 sys.path
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
user32.WindowFromPoint.restype = wintypes.HWND
user32.WindowFromPoint.argtypes = [wintypes.POINT]
user32.RealChildWindowFromPoint.restype = wintypes.HWND

WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
MK_LBUTTON = 0x0001
HWND_MESSAGE = -3

_HERE = os.path.dirname(os.path.abspath(__file__))
_BUILD = os.path.normpath(os.path.join(_HERE, '..', 'build'))
# 产物路径从脚本自身位置推导（脚本在 <仓库根>/build-support/），换机器/挪目录都不用改。
# 需要指到别的 exe 时用环境变量 SC_EXE
EXE = os.environ.get('SC_EXE') or os.path.join(_BUILD, 'bin', 'x64', 'Release', 'ZPin.build.exe')
LOG_DIR = os.path.join(_BUILD, 'logs')
EXE_DIR = os.path.dirname(EXE)
PORTABLE_CFG = os.path.join(EXE_DIR, 'config.json')
import _cfg_guard          # 这行文件就是 <exe 同目录>\config.json = 用户真实配置，得护栏
_cfg_guard.install(PORTABLE_CFG)
# 默认选区是"屏幕中间一块"，工具条摆在它右下方，四周都很宽裕 —— 这种位置测不出
# "工具条被挤出屏幕"的问题。要复现就得让选区贴着屏幕边，所以支持从命令行传：
#   python runtime_video_probe.py <left> <top> <right> <bottom>
# 例：右边缘贴屏幕右边 (700 350 1910 950)、近全屏 (10 10 1910 1190)
SEL = (500, 350, 1200, 950)
if len(sys.argv) >= 5:
    SEL = tuple(int(v) for v in sys.argv[1:5])

EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

SPI_GETWORKAREA = 0x0030


def work_area():
    """主显示器工作区 (left, top, right, bottom)，物理像素 —— 和程序里
    GetMonitorInfo 的 rcWork 是同一个概念（都不含任务栏）。

    拿它来判断"工具条有没有被挤出屏幕"：窗口的 rect 可以落在屏幕外（Windows 不管），
    但用户看不见也点不到，所以必须自己断言。
    """
    r = wintypes.RECT()
    user32.SystemParametersInfoW.argtypes = [wintypes.UINT, wintypes.UINT,
                                             ctypes.POINTER(wintypes.RECT), wintypes.UINT]
    user32.SystemParametersInfoW(SPI_GETWORKAREA, 0, ctypes.byref(r), 0)
    return (r.left, r.top, r.right, r.bottom)


def windows_of(pid, visible=True):
    out = []

    def cb(hwnd, _):
        p = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
        if p.value == pid and (not visible or user32.IsWindowVisible(hwnd)):
            cls = ctypes.create_unicode_buffer(128)
            user32.GetClassNameW(hwnd, cls, 128)
            r = wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(r))
            out.append({'hwnd': hwnd, 'cls': cls.value, 'visible': bool(user32.IsWindowVisible(hwnd)),
                        'rect': (r.left, r.top, r.right - r.left, r.bottom - r.top)})
        return True

    user32.EnumWindows(EnumWindowsProc(cb), 0)
    return out


def find_msg_window(pid):
    prev = None
    while True:
        h = user32.FindWindowExW(wintypes.HWND(HWND_MESSAGE), prev, 'STATIC', None)
        if not h:
            return None
        prev = h
        p = wintypes.DWORD()
        user32.GetWindowThreadProcessId(h, ctypes.byref(p))
        if p.value == pid:
            return h


def zorder(pid):
    """返回 pid 的可见窗口，按 z 序从上到下"""
    return windows_of(pid)


def fg_label():
    h = user32.GetForegroundWindow()
    if not h:
        return '(无)'
    cls = ctypes.create_unicode_buffer(128)
    user32.GetClassNameW(h, cls, 128)
    return '0x%X %s' % (h, cls.value)


def hit_label(pid, x, y):
    pt = wintypes.POINT(x, y)
    h = user32.WindowFromPoint(pt)
    if not h:
        return '(无窗口)'
    p = wintypes.DWORD()
    user32.GetWindowThreadProcessId(h, ctypes.byref(p))
    cls = ctypes.create_unicode_buffer(128)
    user32.GetClassNameW(h, cls, 128)
    own = '' if p.value == pid else '  <<< 不是本程序的窗口！'
    return '0x%X %s%s' % (h, cls.value, own)


def key(vk):
    user32.keybd_event(vk, 0, 0, 0)
    time.sleep(0.06)
    user32.keybd_event(vk, 0, 2, 0)
    time.sleep(0.3)


def real_drag(x1, y1, x2, y2):
    """真鼠标拖框：和用户一样按住左键拖（会触发 SetCapture 那一套）"""
    user32.SetCursorPos(x1, y1)
    time.sleep(0.3)
    user32.mouse_event(0x0002, 0, 0, 0, 0)
    time.sleep(0.15)
    steps = 8
    for i in range(1, steps + 1):
        user32.SetCursorPos(x1 + (x2 - x1) * i // steps, y1 + (y2 - y1) * i // steps)
        time.sleep(0.05)
    user32.mouse_event(0x0004, 0, 0, 0, 0)
    time.sleep(0.6)


def real_click(x, y, hover=0.9):
    user32.SetCursorPos(x, y)
    time.sleep(hover)
    user32.mouse_event(0x0002, 0, 0, 0, 0)
    time.sleep(0.1)
    user32.mouse_event(0x0004, 0, 0, 0, 0)
    time.sleep(0.5)


def dump_state(pid, tag, barhint=None):
    print('--- %s ---' % tag)
    ws = windows_of(pid)
    for i, w in enumerate(ws):
        print('   z序%2d  hwnd=0x%-7X %-18s rect=%s' % (i, w['hwnd'], w['cls'], w['rect']))
    if barhint:
        bx, by, bw, bh = barhint
        print('   工具条上各点的命中：')
        for name, fx in (('系统声', 16), ('麦克风', 48), ('开始/计时', 81), ('退出/丢弃', 113)):
            pass
        for i in range(5):
            x = bx + int((i + 0.5) * bw / 5)
            y = by + bh // 2
            print('     逻辑第 %d 按钮 (屏 %d,%d) -> %s' % (i, x, y, hit_label(pid, x, y)))


def main():
    if os.path.exists(PORTABLE_CFG):
        os.remove(PORTABLE_CFG)
    with open(PORTABLE_CFG, 'w', encoding='utf-16') as f:
        f.write('{"common":{"autoStart":false,"language":"zh-CN"},'
                '"shortcutKey":{"cap":"F1","pin":"F3"}}')

    proc = subprocess.Popen([EXE])
    pid = proc.pid
    try:
        time.sleep(3.0)
        find_msg_window(pid)
        key(0x70)
        time.sleep(2.0)
        cap = [w for w in windows_of(pid) if w['rect'][2] > 1000 or w['rect'][3] > 800][0]
        capwnd = cap['hwnd']
        print('=== 真鼠标拖框 %s ===' % (SEL,))
        real_drag(*SEL)
        dump_state(pid, '拖完框')
        print('   拖完框后前台 = %s' % fg_label())

        bar = [w for w in windows_of(pid) if w['hwnd'] != capwnd][0]
        barw, barh = bar['rect'][2], bar['rect'][3]
        w1 = (barw - 3.0) / 16
        vid_x = bar['rect'][0] + int(11 * w1 + 2 * 1.5 + w1 / 2)
        vid_y = bar['rect'][1] + barh // 2
        # 用户的真实情况：光标停在工具条上、**工具条就是当前活动窗口**，
        # 这时点"录屏"，enterLiveStage 会把活动的工具条隐藏掉 —— 隐藏活动窗口会让系统
        # 把激活权交给同线程的下一个窗口（= 全屏覆盖层），而"激活"会把 topmost 窗口
        # 提到 topmost 带的最上面。先显式激活主工具条，模拟这个前提
        print('   点录屏前：前台 = %s' % fg_label())
        user32.SetForegroundWindow(wintypes.HWND(bar['hwnd']))
        time.sleep(0.4)
        print('   显式激活主工具条后：前台 = %s' % fg_label())
        print('=== 真鼠标点"录屏"（屏 %d,%d）===' % (vid_x, vid_y))
        real_click(vid_x, vid_y)
        time.sleep(2.0)
        print('   进录屏模式后：前台 = %s' % fg_label())

        ws = windows_of(pid)
        tb = [w for w in ws if w['hwnd'] != capwnd and w['cls'] == 'Ling']
        dump_state(pid, '进入录屏模式后', tb[0]['rect'] if tb else None)

        # TEMP-DEBUG 抓屏：临时停用了 excludeFromCapture，工具条这次能看到
        try:
            from PIL import ImageGrab
            im = ImageGrab.grab(include_layered_windows=True).convert('RGB')
            p1 = os.path.join(LOG_DIR, 'probe_recordmode.png')
            im.save(p1)
            print('   截图 %s' % p1)
            if tb:
                r = tb[0]['rect']
                box = (max(0, r[0] - 20), max(0, r[1] - 30),
                       min(im.width, r[0] + r[2] + 20), min(im.height, r[1] + r[3] + 15))
                crop = im.crop(box)
                crop = crop.resize((crop.width * 3, crop.height * 3), 0)
                p2 = os.path.join(LOG_DIR, 'probe_recordbar_zoom.png')
                crop.save(p2)
                print('   工具条放大图 %s  （裁剪 %s）' % (p2, box))
        except Exception as e:
            print('   抓屏失败: %s' % e)

        # 让覆盖层成为活动窗口（激活会把 topmost 窗口提到这一带最上面）
        print('=== 强制激活全屏覆盖层，看工具条会不会被盖住 ===')
        user32.SetForegroundWindow(wintypes.HWND(capwnd))
        time.sleep(0.6)
        print('   前台 = %s' % fg_label())
        dump_state(pid, '激活覆盖层之后', tb[0]['rect'] if tb else None)
        try:
            from PIL import ImageGrab
            im2 = ImageGrab.grab(include_layered_windows=True).convert('RGB')
            p3 = os.path.join(LOG_DIR, 'probe_after_activate.png')
            im2.save(p3)
            if tb:
                r = tb[0]['rect']
                box = (max(0, r[0] - 30), max(0, r[1] - 40),
                       min(im2.width, r[0] + r[2] + 30), min(im2.height, r[1] + r[3] + 20))
                c = im2.crop(box)
                c = c.resize((c.width * 3, c.height * 3), 0)
                c.save(os.path.join(LOG_DIR, 'probe_after_activate_zoom.png'))
                print('   激活后工具条区域图 %s' % os.path.join(LOG_DIR, 'probe_after_activate_zoom.png'))
        except Exception as e:
            print('   抓屏失败 %s' % e)

        if tb:
            t = tb[0]
            bx, by, bw, bh = t['rect']
            print('   录屏工具条 0x%X rect=%s  z序位置=%d（越小越靠上）'
                  % (t['hwnd'], t['rect'], ws.index(t)))
            print('   覆盖层     0x%X          z序位置=%d'
                  % (capwnd, [i for i, w in enumerate(ws) if w['hwnd'] == capwnd][0]))
            # 真点一个按钮，看状态有没有变（工具条会从 129 宽变成 209 宽）
            print('=== 真鼠标点"开始录制"（工具条 1/4 处）===')
            real_click(bx + int(bw * (81 / 129.0)), by + bh // 2)
            time.sleep(2.0)
            ws2 = windows_of(pid)
            t2 = [w for w in ws2 if w['hwnd'] != capwnd and w['cls'] == 'Ling']
            print('   点击后工具条宽度：%s -> %s（录屏形态应为 209 逻辑宽的 1.24 倍）'
                  % (bw, t2[0]['rect'][2] if t2 else '窗口没了'))
            tmp = os.path.join(os.path.dirname(EXE), 'temp.mp4')
            print('   temp.mp4: %s' % (os.path.getsize(tmp) if os.path.exists(tmp) else '不存在'))
            dump_state(pid, '点开始录制之后', t2[0]['rect'] if t2 else None)

            # 录制中再强制激活一次覆盖层：这是用户最可能碰到的时刻（点选区里的窗口
            # 会让覆盖层被激活）。工具条必须还在最上面，否则就是"按钮全没了、退不出来"
            print('=== 录制中强制激活覆盖层 ===')
            user32.SetForegroundWindow(wintypes.HWND(capwnd))
            time.sleep(0.6)
            ws3 = windows_of(pid)
            t3 = [w for w in ws3 if w['hwnd'] != capwnd and w['cls'] == 'Ling']
            if not t3:
                print('  => **录屏工具条不见了**')
                return 1
            above = ws3.index(t3[0]) < [i for i, w in enumerate(ws3) if w['hwnd'] == capwnd][0]
            print('   工具条 z序=%d  覆盖层 z序=%d  => %s'
                  % (ws3.index(t3[0]),
                     [i for i, w in enumerate(ws3) if w['hwnd'] == capwnd][0],
                     '通过：工具条在覆盖层之上' if above else '**问题：工具条被覆盖层盖住了**'))
            print('   各按钮命中：')
            ok_hit = True
            for i in range(5):
                x = t3[0]['rect'][0] + int((i + 0.5) * t3[0]['rect'][2] / 5)
                y = t3[0]['rect'][1] + t3[0]['rect'][3] // 2
                h = hit_label(pid, x, y)
                good = h.startswith('0x%X' % t3[0]['hwnd'])
                if not good:
                    ok_hit = False
                print('     第 %d 点 (屏 %d,%d) -> %s%s'
                      % (i, x, y, h, '' if good else '   <<< 点不到按钮'))

            # 越界检查：光"z 序在覆盖层之上"不够 —— 工具条还可能整个（或部分）被挤出
            # 屏幕外，那时 WindowFromPoint 照样能命中它（命中测试用的是虚拟桌面坐标），
            # 但用户看不见也点不着。录制开始后工具条会变宽，位置没重算就会往右溢出。
            wa = work_area()
            L, T, W, H = t3[0]['rect']
            over = []
            if L < wa[0]:
                over.append('左')
            if T < wa[1]:
                over.append('上')
            if L + W > wa[2]:
                over.append('右(右边缘 %d > 工作区 %d)' % (L + W, wa[2]))
            if T + H > wa[3]:
                over.append('下(底边缘 %d > 工作区 %d)' % (T + H, wa[3]))
            if over:
                print('   => **问题：工具条越出屏幕工作区【%s】**' % '，'.join(over))
                print('      越界的那截在屏幕外，看不见也点不到')
                return 1
            print('   => 通过：工具条完整落在屏幕工作区内（rect=%s，工作区=%s）'
                  % (t3[0]['rect'], wa))
            return 0 if (above and ok_hit) else 1
    finally:
        try:
            proc.kill()
            proc.wait(timeout=5)
        except Exception:
            pass
    return 0


if __name__ == '__main__':
    sys.exit(main())
