"""录屏链路的卡死侦察：分阶段跑，每阶段都持续探测"窗口还响不响应消息"。

用户报"一打开就卡住"，但单纯走完【F1 → 拖框 → 录屏按钮 → 开始录制】是正常的，
所以要逐个试其它出口：录完按 ESC 退出、点"存剪切板"收工，看哪一步把 UI 线程卡住。

用法：python runtime_video_test.py [stop_mode]
  stop_mode = esc   录制几秒后按 ESC（用户最可能的退出方式）
            = clip  录制几秒后点"存剪切板"
            = none  只录，不停（基线）
"""
import _pylibs  # noqa: F401  —— 把 ext/build/.pylibs（Pillow）挂进 sys.path
import ctypes
import os
import shutil
import subprocess
import sys
import time
from ctypes import wintypes

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    pass

user32 = ctypes.WinDLL('user32', use_last_error=True)
user32.SendMessageTimeoutW.restype = ctypes.c_longlong
user32.SendMessageTimeoutW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM,
                                       wintypes.LPARAM, wintypes.UINT, wintypes.UINT,
                                       ctypes.POINTER(ctypes.c_ulonglong)]

WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_NULL = 0x0000
MK_LBUTTON = 0x0001
HWND_MESSAGE = -3
SMTO_ABORTIFHUNG = 0x0002

_HERE = os.path.dirname(os.path.abspath(__file__))
_BUILD = os.path.normpath(os.path.join(_HERE, '..', 'build'))
# 产物路径从脚本自身位置推导（脚本在 <仓库根>/ext/build-support/），换机器/挪目录都不用改。
# 需要指到别的 exe 时用环境变量 SC_EXE
EXE = os.environ.get('SC_EXE') or os.path.join(_BUILD, 'bin', 'x64', 'Release', 'ScreenCapture.build.exe')
LOG_DIR = os.path.join(_BUILD, 'logs')
QUICK_DIR = os.path.join(_BUILD, 'logs', 'quicksave_video')
EXE_DIR = os.path.dirname(EXE)
PORTABLE_CFG = os.path.join(EXE_DIR, 'config.json')
import _cfg_guard          # 这行文件就是 <exe 同目录>\config.json = 用户真实配置，得护栏
_cfg_guard.install(PORTABLE_CFG)
SEL = (400, 300, 1100, 900)

EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


def lparam(x, y):
    return (y << 16) | (x & 0xFFFF)


def windows_of(pid, visible_only=True):
    found = []

    def cb(hwnd, _):
        wpid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(wpid))
        if wpid.value == pid:
            if visible_only and not user32.IsWindowVisible(hwnd):
                return True
            cls = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, cls, 256)
            r = wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(r))
            found.append({'hwnd': hwnd, 'cls': cls.value,
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


def responsive(hwnd, timeout=1200):
    out = ctypes.c_ulonglong(0)
    return bool(user32.SendMessageTimeoutW(wintypes.HWND(hwnd), WM_NULL, 0, 0,
                                           SMTO_ABORTIFHUNG, timeout, ctypes.byref(out)))


def watch(pid, hwnd, seconds, tag):
    # 注意 hwnd 必须是"活着"的窗口：覆盖层被 ESC 关掉之后，往那个死句柄
    # SendMessageTimeoutW 会直接失败，看起来就像卡死。消息窗口最合适
    """持续探测 seconds 秒，返回最长的一次"不响应"持续了多久"""
    worst, cur, t0 = 0.0, 0.0, time.time()
    while time.time() - t0 < seconds:
        if responsive(hwnd):
            worst = max(worst, cur)
            cur = 0.0
        else:
            cur += 0.2
        time.sleep(0.2)
    worst = max(worst, cur)
    print('   [%s] 观察 %.0f 秒：最长无响应 %.1f 秒%s'
          % (tag, seconds, worst, '  <<< 卡住了' if worst >= 1.0 else ''))
    return worst


def real_click(hwnd, x, y, hover=0.8):
    r = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    user32.SetCursorPos(r.left + x, r.top + y)
    time.sleep(hover)
    user32.mouse_event(0x0002, 0, 0, 0, 0)
    time.sleep(0.1)
    user32.mouse_event(0x0004, 0, 0, 0, 0)
    time.sleep(0.4)


def drag(hwnd, x1, y1, x2, y2):
    user32.PostMessageW(hwnd, WM_MOUSEMOVE, 0, lparam(x1, y1))
    time.sleep(0.1)
    user32.PostMessageW(hwnd, WM_LBUTTONDOWN, MK_LBUTTON, lparam(x1, y1))
    for i in range(1, 5):
        user32.PostMessageW(hwnd, WM_MOUSEMOVE, MK_LBUTTON,
                            lparam(x1 + (x2 - x1) * i // 4, y1 + (y2 - y1) * i // 4))
        time.sleep(0.08)
    user32.PostMessageW(hwnd, WM_LBUTTONUP, 0, lparam(x2, y2))
    time.sleep(0.6)


def key(vk):
    user32.keybd_event(vk, 0, 0, 0)
    time.sleep(0.06)
    user32.keybd_event(vk, 0, 2, 0)
    time.sleep(0.3)


def shot(name):
    os.makedirs(LOG_DIR, exist_ok=True)
    p = os.path.join(LOG_DIR, name)
    try:
        from PIL import ImageGrab
        ImageGrab.grab().save(p)
        return p
    except Exception as e:
        return '(截图失败 %s)' % e


def main():
    global SEL
    mode = sys.argv[1] if len(sys.argv) > 1 else 'none'
    global SEL
    if len(sys.argv) >= 6:
        SEL = tuple(int(v) for v in sys.argv[2:6])
        print('选区 =', SEL)
    if os.path.exists(PORTABLE_CFG):
        os.remove(PORTABLE_CFG)
    quick = mode in ('quicksave',)
    shutil.rmtree(QUICK_DIR, ignore_errors=True)
    os.makedirs(QUICK_DIR, exist_ok=True)
    with open(PORTABLE_CFG, 'w', encoding='utf-16') as f:
        f.write('{"common":{"autoStart":false,"language":"zh-CN","borderWidth":0,'
                '"quickSave":%s,"saveDir":"%s","historyDays":3},'
                '"shortcutKey":{"cap":"F1","pin":"F3"}}'
                % ('true' if quick else 'false', QUICK_DIR.replace('\\', '\\\\')))

    proc = subprocess.Popen([EXE])
    pid = proc.pid
    tmp = os.path.join(os.path.dirname(EXE), 'temp.mp4')
    try:
        time.sleep(3.0)
        if not find_msg_window(pid):
            print('!! 没找到消息窗口（可能有别的实例在跑）')
            return 1

        msgwnd2 = find_msg_window(pid)   # 探活用它：它和窗口同一个消息循环，且始终活着
        key(0x70)
        time.sleep(2.0)
        capwnd = [w for w in windows_of(pid)
                  if w['rect'][2] > 1000 or w['rect'][3] > 800][0]['hwnd']
        drag(capwnd, *SEL)

        bar = min([w for w in windows_of(pid) if w['hwnd'] != capwnd],
                  key=lambda w: w['rect'][1])
        barw, barh = bar['rect'][2], bar['rect'][3]
        w1 = (barw - 3.0) / 16
        vid_x = int(11 * w1 + 2 * 1.5 + w1 / 2)
        real_click(bar['hwnd'], vid_x, int(barh / 2))
        time.sleep(2.0)

        vb = [w for w in windows_of(pid) if w['hwnd'] not in (capwnd,)]
        vb = [w for w in vb if w['cls'] == 'Ling'][0]
        vw, vh = vb['rect'][2], vb['rect'][3]
        unit = vw / 129.0
        if mode == 'noaudio':
            # 设置形态：系统声(0) / 麦克风(1) / 分隔符 / 开始 / 退出
            print('== 关掉系统声 ==')
            real_click(vb['hwnd'], int(16 * unit), int(vh / 2))
            time.sleep(0.8)
        def bx(logical):   # 逻辑像素 -> 该工具条上的物理像素
            return int(logical * unit)
        # 设置形态的按钮中心（逻辑像素）：系统声 16 / 麦 48 / 分隔 1 / 开始 81 / 退出 113
        # 录制形态：计时 112 / 分隔 1 / 丢弃 129 / 存文件 161 / 存剪切板 193
        if mode in ('exit', 'esc_pre', 'esc_noaudio'):
            if mode == 'exit':
                print('== 点录屏工具条的"退出"（x=%d）==' % bx(113))
                real_click(vb['hwnd'], bx(113), int(vh / 2))
            else:
                print('== 还没开始录制就按 ESC ==')
                key(0x1B)
            watch(pid, msgnd2 if False else msgwnd2, 5.0, mode)
            print('   探活=%s' % responsive(msgwnd2))
            for w in windows_of(pid, visible_only=False):
                print('   0x%-7X %-20s rect=%s' % (w['hwnd'], w['cls'], w['rect']))
            key(0x70)
            time.sleep(2.0)
            again = [w for w in windows_of(pid) if w['rect'][2] > 1000 or w['rect'][3] > 800]
            print('   再按 F1 覆盖层出现 = %s' % bool(again))
            if again:
                key(0x1B)
                time.sleep(1.0)
                print('   关掉后探活=%s' % responsive(msgwnd2))
            return 0
        start_x = int((1 + 32 + 32 + 16) * unit)
        print('== 开始录制（工具条 %dx%d，按钮 x=%d）==' % (vw, vh, start_x))
        real_click(vb['hwnd'], start_x, int(vh / 2))
        watch(pid, msgwnd2, 4.0, '录制中')
        print('   temp.mp4 大小 %s' % (os.path.getsize(tmp) if os.path.exists(tmp) else '无'))

        if mode == 'esc' or mode == 'noaudio_esc':
            print('== 录制中按 ESC ==')
            key(0x1B)
            watch(pid, msgwnd2, 6.0, 'ESC 之后')
        elif mode == 'quicksave':
            print('== 录制中点"保存"（对勾，x=%d）==' % int(161 * unit))
            real_click(vb['hwnd'], int(161 * unit), int(vh / 2), hover=0.8)
            time.sleep(2.5)
            got = [f for f in os.listdir(QUICK_DIR)] if os.path.isdir(QUICK_DIR) else []
            print('   快速保存目录里的文件：%s' % got)
            print('   => %s' % ('通过：点保存直接落盘（没弹另存为）' if got else '**问题：没有落盘**'))
            now = [w for w in windows_of(pid) if w['cls'] == 'Ling'
                   and w['hwnd'] != capwnd]
            if now:
                print('   录制形态工具条宽度 = %d px（2 个按钮算下来约 %d）'
                      % (now[0]['rect'][2], int(177 * unit)))
        elif mode == 'save':
            print('== 录制中点"存文件"（x=%d）==' % int(161 * unit))
            real_click(vb['hwnd'], int(161 * unit), int(vh / 2), hover=0.8)
            time.sleep(1.5)
            # 应该弹出系统保存对话框：看看有没有新窗口、能不能响应
            dlgs = [w for w in windows_of(pid, visible_only=False) if w['cls'] != 'Ling']
            print('   弹窗情况：')
            for w in dlgs:
                print('     0x%-7X %-24s rect=%s 响应=%s'
                      % (w['hwnd'], w['cls'], w['rect'], responsive(w['hwnd'])))
            watch(pid, msgwnd2, 4.0, '保存对话框期间')
            key(0x1B)   # 取消对话框
            time.sleep(1.5)
            watch(pid, msgwnd2, 4.0, '取消之后')
        elif mode == 'discard':
            print('== 录制中点"丢弃"（✕，x=%d）==' % int(129 * unit))
            real_click(vb['hwnd'], int(129 * unit), int(vh / 2), hover=0.8)
            watch(pid, msgwnd2, 5.0, '丢弃之后')
        elif mode in ('clip', 'noaudio'):
            # 录制形态：计时 112 + 分隔 1 + 丢弃/存文件/存剪切板 三个 32
            clip_x = int((112 + 1 + 32 + 32 + 16) * unit)
            print('== 录制中点"存剪切板"（x=%d）==' % clip_x)
            real_click(vb['hwnd'], clip_x, int(vh / 2))
            watch(pid, msgwnd2, 6.0, '存剪切板之后')
        time.sleep(1.0)
        print('   探活（消息窗口 0x%X）：响应=%s' % (msgwnd2, responsive(msgwnd2)))
        for w in windows_of(pid, visible_only=False):
            print('   0x%-7X %-20s rect=%s 响应=%s'
                  % (w['hwnd'], w['cls'], w['rect'], responsive(w['hwnd'])))
        print('== 收工后再按一次 F1，看还能不能正常截图 ==')
        key(0x70)
        time.sleep(2.0)
        again = [w for w in windows_of(pid) if w['rect'][2] > 1000 or w['rect'][3] > 800]
        print('   覆盖层又出现 = %s；探活=%s'
              % (bool(again), responsive(msgwnd2)))
        if again:
            key(0x1B)
            time.sleep(1.0)
            print('   ESC 关掉后探活=%s' % responsive(msgwnd2))
        print('   截图: %s' % shot('video_stop_%s.png' % mode))
        print('   temp.mp4 %s' % ('还在，%d 字节' % os.path.getsize(tmp)
                                  if os.path.exists(tmp) else '已删除'))
    finally:
        try:
            proc.kill()
            proc.wait(timeout=5)
        except Exception:
            pass
    return 0


if __name__ == '__main__':
    rc = main()
    print('===== 退出码 %d =====' % rc)
    sys.exit(rc)
