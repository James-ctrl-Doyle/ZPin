r"""验证这一轮的四项改动：

1) 数据目录搬到了 exe 同目录（config.json 与 temp\ 都在 exe 旁边，不再碰 %appdata%）
2) 每次截图留一条历史（temp\shots\<时间戳>.bin），翻页键能翻看上一条 / 下一条，
   翻出来的那张可以重新裁（用复制出来的图尺寸来核对框是不是回到了当时那个）。
   翻页键默认 , 和 .（设置-快捷键里可改），这一组里既验默认值、也验改过之后生效、
   顺带确认方向键没被弄坏
3) 快速保存：勾上之后点保存直接落到默认目录（用配置里的 saveDir 指到临时目录来验）
4) 录屏收尾只剩 丢弃 + 保存，保存按钮是对勾（工具条宽度按 2 个按钮算）
"""
import _pylibs  # noqa: F401  —— 把 build/.pylibs（Pillow）挂进 sys.path
import ctypes
import os
import re
import shutil
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
kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
user32.GetClipboardData.restype = wintypes.HANDLE
user32.GetClipboardData.argtypes = [wintypes.UINT]
kernel32.GlobalLock.restype = ctypes.c_void_p
kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
kernel32.GlobalSize.restype = ctypes.c_size_t
kernel32.GlobalSize.argtypes = [wintypes.HGLOBAL]

WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
MK_LBUTTON = 0x0001
HWND_MESSAGE = -3
VK_RETURN = 0x0D
VK_COMMA = 0xBC      # ,  翻页键默认的"上一条"
VK_PERIOD = 0xBE     # .  翻页键默认的"下一条"
VK_LEFT = 0x25
VK_RIGHT = 0x27
VK_OEM_4 = 0xDB      # [  用来验"改过绑定之后按新键生效"
VK_OEM_6 = 0xDD      # ]

_HERE = os.path.dirname(os.path.abspath(__file__))
_BUILD = os.path.normpath(os.path.join(_HERE, '..', 'build'))
# 产物路径从脚本自身位置推导（脚本在 <仓库根>/build-support/），换机器/挪目录都不用改。
# 需要指到别的 exe 时用环境变量 SC_EXE
EXE = os.environ.get('SC_EXE') or os.path.join(_BUILD, 'bin', 'x64', 'Release', 'ZPin.build.exe')
KEEP_DIR = os.path.join(_BUILD, 'logs', 'quicksave')
EXE_DIR = os.path.dirname(EXE)
CFG = os.path.join(EXE_DIR, 'config.json')
import _cfg_guard          # 这份文件就是用户真实配置，来回覆盖它，必须护栏
_cfg_guard.install(CFG, 'exe 同目录的 config.json')
SHOTS = os.path.join(EXE_DIR, 'temp', 'shots')
SEL_A = (400, 300, 1100, 900)     # 700x600
SEL_B = (500, 400, 1000, 800)     # 500x400
SEL_C = (600, 450, 900, 750)      # 300x300
# 验"工具条跟不跟过去"专用的：右边缘 860 和别的选区都不一样，
# 否则新旧右边缘撞在一起，"位置变了"和"位置本来就对"就分不出来（踩过）
SEL_D = (500, 400, 860, 700)      # 360x300，右边缘 860

EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


def lparam(x, y):
    return (y << 16) | (x & 0xFFFF)


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
            out.append({'hwnd': hwnd, 'cls': cls.value,
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


def key(vk):
    user32.keybd_event(vk, 0, 0, 0)
    time.sleep(0.06)
    user32.keybd_event(vk, 0, 2, 0)
    time.sleep(0.5)


def drag(hwnd, x1, y1, x2, y2, steps=8):
    user32.PostMessageW(hwnd, WM_MOUSEMOVE, 0, lparam(x1, y1))
    time.sleep(0.15)
    user32.PostMessageW(hwnd, WM_LBUTTONDOWN, MK_LBUTTON, lparam(x1, y1))
    time.sleep(0.15)
    for i in range(1, steps + 1):
        user32.PostMessageW(hwnd, WM_MOUSEMOVE, MK_LBUTTON,
                            lparam(x1 + (x2 - x1) * i // steps, y1 + (y2 - y1) * i // steps))
        time.sleep(0.12)
    user32.PostMessageW(hwnd, WM_LBUTTONUP, 0, lparam(x2, y2))
    time.sleep(0.8)


def clipboard_png_size():
    """从剪贴板读 PNG 的尺寸。读不到返回 None"""
    from PIL import Image
    import io as _io
    user32.OpenClipboard(None)
    try:
        fmt, target = 0, 0
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
        p = kernel32.GlobalLock(ctypes.c_void_p(h))
        if not p:
            return None
        size = kernel32.GlobalSize(ctypes.c_void_p(h))
        data = ctypes.string_at(p, size)
        kernel32.GlobalUnlock(ctypes.c_void_p(h))
        return Image.open(_io.BytesIO(data)).size
    finally:
        user32.CloseClipboard()


def read_shot_rects():
    """按时间倒序（最新在前）返回每条历史的截图框尺寸。

    直接从 .bin 的自定义头里读，不猜 —— 翻页的期望值如果靠人肉数"现在是第几条"，
    每加一段用例就会错一次（这个坑踩过）。头布局：
      'SCHT'(4) + version(4) + 整屏 x,y,w,h(16) + 框 l,t,r,b(16) + pngOffset(4)
      所以框的四个值在 offset 24 起，不是 28（第一版按"magic 当 8 字节"数错了，
      读出来的宽高是 (400, -956) 这种鬼数字）
    """
    out = []
    for name in sorted(shot_files(), reverse=True):     # 文件名是时间戳，倒序 = 最新在前
        with open(os.path.join(SHOTS, name), 'rb') as f:
            head = f.read(44)
        if len(head) < 44 or head[:4] != b'SCHT':
            continue
        l, t, r, b = struct.unpack_from('<4i', head, 24)   # maskL/maskT/maskR/maskB
        out.append((name, (r - l, b - t)))
    return out


def read_shot_masks():
    """按时间倒序返回 (文件名, (l,t,r,b)) —— 框是**屏幕坐标**（工具条右边缘就对齐到 r）"""
    out = []
    for name in sorted(shot_files(), reverse=True):
        with open(os.path.join(SHOTS, name), 'rb') as f:
            head = f.read(44)
        if len(head) < 44 or head[:4] != b'SCHT':
            continue
        out.append((name, struct.unpack_from('<4i', head, 24)))
    return out


def shot_files():
    if not os.path.isdir(SHOTS):
        return []
    return sorted(f for f in os.listdir(SHOTS) if f.endswith('.bin'))


def write_cfg(quick_save=False, save_dir='', days=3, prev_shot=None, next_shot=None):
    keys = '"cap":"F1","pin":"F3"'
    if prev_shot is not None:
        keys += ',"prevShot":"%s"' % prev_shot
    if next_shot is not None:
        keys += ',"nextShot":"%s"' % next_shot
    with open(CFG, 'w', encoding='utf-16') as f:
        f.write('{"common":{"autoStart":false,"language":"zh-CN","borderWidth":0,'
                '"quickSave":%s,"saveDir":"%s","historyDays":%d},'
                '"shortcutKey":{%s}}'
                % ('true' if quick_save else 'false', save_dir.replace('\\', '\\\\'), days, keys))


def main():
    # 干净的起点：清掉历史与上次遗留的便携配置（脚本会自己重建）。
    # config.json 的备份/还原交给 _cfg_guard，它连 SIGTERM 都兜住了
    shutil.rmtree(SHOTS, ignore_errors=True)
    shutil.rmtree(KEEP_DIR, ignore_errors=True)
    os.makedirs(KEEP_DIR, exist_ok=True)
    write_cfg()

    proc = subprocess.Popen([EXE])
    pid = proc.pid
    ok = True
    try:
        time.sleep(3.0)
        msgwnd = find_msg_window(pid)

        print('== 第 1 张：框 700x600，回车复制 ==')
        key(0x70)
        time.sleep(2.0)
        cap = [w for w in windows_of(pid) if w['rect'][2] > 1000 or w['rect'][3] > 800][0]
        drag(cap['hwnd'], *SEL_A)
        key(VK_RETURN)
        time.sleep(1.5)
        print('   剪贴板里的图 = %s' % (clipboard_png_size(),))
        files = shot_files()
        print('   历史文件 %d 个：%s' % (len(files), files))
        if len(files) != 1:
            print('  => **问题：截图后应该留下 1 条历史**')
            ok = False

        print('== 第 2 张：框 500x400，按 , 翻到上一条，再复制 ==')
        key(0x70)
        time.sleep(2.0)
        cap = [w for w in windows_of(pid) if w['rect'][2] > 1000 or w['rect'][3] > 800][0]
        drag(cap['hwnd'], *SEL_B)
        key(VK_COMMA)      # , = 上一条（默认绑定）
        time.sleep(1.0)
        key(VK_RETURN)
        time.sleep(1.5)
        size = clipboard_png_size()
        print('   翻到上一条后复制的图 = %s（应为 %s）'
              % (size, (SEL_A[2] - SEL_A[0], SEL_A[3] - SEL_A[1])))
        if size != (SEL_A[2] - SEL_A[0], SEL_A[3] - SEL_A[1]):
            print('  => **问题：, 没有回到上一条的框**')
            ok = False
        files = shot_files()
        print('   历史文件 %d 个' % len(files))
        if len(files) != 2:
            print('  => **问题：按 , 时应该把当前这张也记进历史，共 2 条**')
            ok = False

        print('== 按 . 回到更新的一张（默认绑定）==')
        # ⚠ 回车是"复制并关窗"，所以一个窗口里只能按一次回车 —— 想再看一次结果就得重开 F1
        # 这一把：F1 → 框 500x400 → , (退到上一条) → . (再翻回来) → 回车。
        # 只看 , 的话会落在上一条（700x600）；加上 . 才会回到本轮的 500x400
        key(0x70)
        time.sleep(2.0)
        cap = [w for w in windows_of(pid) if w['rect'][2] > 1000 or w['rect'][3] > 800][0]
        drag(cap['hwnd'], *SEL_B)
        key(VK_COMMA)      # , 上一条
        time.sleep(0.9)
        key(VK_PERIOD)     # . 下一条 → 回到本轮的 500x400
        time.sleep(0.9)
        key(VK_RETURN)
        time.sleep(1.5)
        size = clipboard_png_size()
        want_b = (SEL_B[2] - SEL_B[0], SEL_B[3] - SEL_B[1])
        print('   , 再 . 之后复制的图 = %s（应为 %s；若 . 没生效会是 700x600）' % (size, want_b))
        if size != want_b:
            print('  => **问题：. 没有翻回更新的那张**')
            ok = False

        print('== 方向键 ← 仍然可用（不和新的 , 冲突）==')
        # 退 4 步：先按一次 , 再连按三次 ←。方向键和 , 是同一个动作，所以两个都该算数。
        # 之所以退这么多步：要落到一条尺寸明显不同的历史（最开始那张 700x600）上，
        # 否则"翻了"和"没翻"看起来一样，这检查就是白做的
        before = read_shot_rects()
        want_sel = (SEL_B[2] - SEL_B[0], SEL_B[3] - SEL_B[1])
        # 步数按实际条数算：一路退到最旧那条。翻不动时按键是空操作，所以不用怕多按
        steps = len(before)
        if steps == 0 or before[-1][1] == want_sel:
            # 最旧那条和本轮选区一样大 ⇒ "翻了"和"没翻"看不出区别，这检查没有意义
            print('  => 跳过：最旧那条(%s)和本轮选区(%s)一样大，这一步区分不出来'
                  % (before[-1][1] if before else None, want_sel))
        else:
            key(0x70)
            time.sleep(2.0)
            cap = [w for w in windows_of(pid) if w['rect'][2] > 1000 or w['rect'][3] > 800][0]
            drag(cap['hwnd'], *SEL_B)
            key(VK_COMMA)                  # 第一次用 ,
            time.sleep(0.7)
            for _ in range(steps - 1):     # 剩下的都用 ← （两者是同一个动作）
                key(VK_LEFT)
                time.sleep(0.7)
            key(VK_RETURN)
            time.sleep(1.5)
            size = clipboard_png_size()
            want = before[-1][1]
            print('   , + ←×%d 之后复制的图 = %s（应为最旧那条 %s）'
                  % (steps - 1, size, want))
            if size != want:
                print('  => **问题：方向键翻页被弄坏了**')
                ok = False

        print('== 翻到最旧那一条，把框改小，翻走再翻回来，看框有没有记住 ==')
        # 一路按到底（翻不动时按键是空操作，所以多按几次没有副作用），
        # 落在最旧那条 = 最开始那张 700x600（位于 400,300-1100,900）。
        # 不数"该按几下"：前面每加一段用例，条数就变一次，数出来的必错（踩过两次）
        key(0x70)
        time.sleep(2.0)
        cap = [w for w in windows_of(pid) if w['rect'][2] > 1000 or w['rect'][3] > 800][0]
        drag(cap['hwnd'], *SEL_A)
        for _ in range(12):
            key(VK_COMMA)
            time.sleep(0.35)
        time.sleep(0.6)
        cap = [w for w in windows_of(pid) if w['rect'][2] > 1000 or w['rect'][3] > 800]
        if cap:
            # 在选区左边框外侧按下去 = 调左边那条边（见 WinCap::onDown 的 startAdjust 分支），
            # 往右拖到 x=700，框就变成 700,300-1100,900 = 400x600
            drag(cap[0]['hwnd'], SEL_A[0] - 8, 600, 700, 600)
            time.sleep(0.4)
            key(VK_PERIOD)             # . 翻走（离开时会把这个新框记回最旧那条）
            time.sleep(0.8)
            key(VK_COMMA)              # , 再翻回最旧那条
            time.sleep(1.0)
            key(VK_RETURN)
            time.sleep(1.5)
            size = clipboard_png_size()
            want = (SEL_A[2] - 700, SEL_A[3] - SEL_A[1])   # 400 x 600
            print('   改框 → 翻走 → 翻回来，复制的图 = %s（应约 %s）' % (size, want))
            if not size or abs(size[0] - want[0]) > 4 or abs(size[1] - want[1]) > 4:
                print('  => **问题：翻走时没把改过的框记回历史**')
                ok = False
        else:
            print('  => **覆盖层没了**')
            ok = False

        print('== 刚按 F1、还没拖框，就该能翻历史 ==')
        # 这一节的由来：stage 在"刚进来还没框"时是 Select 而不是 Adjust，
        # 原来 canGoPrevShot 只认 Adjust，于是必须先框一下才能翻页 —— 用户报的就是这个
        before = read_shot_rects()
        if not before:
            print('  => **前置条件不足：没有历史**')
            ok = False
        else:
            key(0x70)
            time.sleep(2.0)
            cap_now = [w for w in windows_of(pid) if w['rect'][2] > 1000 or w['rect'][3] > 800]
            if not cap_now:
                print('  => **覆盖层没起来**')
                ok = False
            else:
                bars0 = [w for w in windows_of(pid)
                         if w['cls'] == 'Ling' and w['hwnd'] != cap_now[0]['hwnd']]
                print('   按 F1 后（还没框）：工具条 %d 个' % len(bars0))
                key(VK_COMMA)          # 关键：不拖框，直接按 , 
                time.sleep(1.2)
                bars1 = [w for w in windows_of(pid)
                         if w['cls'] == 'Ling' and w['hwnd'] != cap_now[0]['hwnd']]
                key(VK_RETURN)
                time.sleep(1.5)
                size = clipboard_png_size()
                want = before[0][1]
                print('   直接按 , 再复制 = %s（应为最新那条 %s）' % (size, want))
                if size != want:
                    print('  => **问题：没框框之前翻不动历史**')
                    ok = False
                # 翻进来是 Adjust 阶段，工具条是那时候才建的 —— 漏了这一步会"有框、没工具条"
                if not bars1:
                    print('  => **问题：翻进去之后没有工具条**')
                    ok = False
                else:
                    print('   翻进去之后工具条 %d 个，宽度 %s（截图条 16 个按钮约 637）'
                          % (len(bars1), [w['rect'][2] for w in bars1]))
                    if not any(600 < w['rect'][2] < 700 for w in bars1):
                        print('  => **问题：工具条宽度不对（可能只建了一部分）**')
                        ok = False

            # 反向对照：Select 阶段方向键仍然只挪光标、不翻页（那个阶段要用它对准起点）
            if len(before) >= 2 and before[0][1] != before[1][1]:
                key(0x70)
                time.sleep(2.0)
                key(VK_LEFT)           # Select 阶段：只是把光标挪 1 像素
                time.sleep(0.8)
                key(VK_COMMA)          # 这一下才该翻页
                time.sleep(1.0)
                key(VK_RETURN)
                time.sleep(1.5)
                size = clipboard_png_size()
                print('   Select 阶段先按方向键再按 ,  = %s（应仍是最新那条 %s；'
                      '若方向键也翻页则会变成 %s）' % (size, before[0][1], before[1][1]))
                if size != before[0][1]:
                    print('  => **问题：Select 阶段方向键被抢去翻页了**')
                    ok = False
            else:
                print('   （跳过方向键对照：最新两条尺寸相同，区分不出来）')

        print('== 按 , 翻出去之后按 . 要能回到截图状态（还没框那个状态）==')
        # 之前的毛病：. 只认 shotIndex > 0，而"这次截图"是 shotIndex = -1，
        # 于是从 Select 按 , 翻出去以后就再也翻不回来了
        key(0x70)
        time.sleep(2.0)
        cap_now = [w for w in windows_of(pid) if w['rect'][2] > 1000 or w['rect'][3] > 800]
        if not cap_now:
            print('  => **覆盖层没起来**')
            ok = False
        else:
            capwnd2 = cap_now[0]['hwnd']
            key(VK_COMMA)              # , 翻到上一条
            time.sleep(1.2)
            key(VK_PERIOD)             # . 回到"这次截图"本身
            time.sleep(1.2)
            left = [w for w in windows_of(pid)
                    if w['cls'] == 'Ling' and w['hwnd'] != capwnd2]
            print('   . 之后还露着的工具条 %d 个（回到"还没框"就该是 0 个）' % len(left))
            if left:
                print('  => **问题：回到截图状态后工具条没收起来**')
                ok = False
            # 没选区时回车什么也不该发生（有选区的话它会复制并关窗）——
            # 拿这个当"确实回到了还没框的状态"的判据
            key(VK_RETURN)
            time.sleep(1.5)
            alive = [w for w in windows_of(pid) if w['hwnd'] == capwnd2]
            print('   此时按回车：覆盖层还在 = %s（在 = 没选区，正确）' % bool(alive))
            if not alive:
                print('  => **问题：回到的状态里还有选区（回车把它复制走了）**')
                ok = False
                # 窗口已经关了，后面没法接着验，直接跳过
            else:
                key(VK_COMMA)          # 再翻回去，应当又能翻：证明真的回到了 shotIndex = -1
                time.sleep(1.0)
                key(VK_RETURN)
                time.sleep(1.5)
                size = clipboard_png_size()
                want = read_shot_rects()[0][1]
                print('   再按 , 再回车 = %s（应为最新那条 %s）' % (size, want))
                if size != want:
                    print('  => **问题：翻回来之后就翻不动了**')
                    ok = False

        print('== 按 , 之后工具条要立刻跟到新选区（不用点一下）==')
        # 之前的毛病：applyShot 只调 raiseToolbars，而 layoutTools 只在 makeTools
        # 真的新建窗口时才走 —— 翻页时工具条是复用的，于是位置留在上一条选区那儿，
        # 要等下一次鼠标移动（onMove 里也调 layoutTools）才跟过去
        masks = read_shot_masks()
        if not masks:
            print('  => **前置条件不足：没有历史**')
            ok = False
        else:
            key(0x70)
            time.sleep(2.0)
            cap_now = [w for w in windows_of(pid) if w['rect'][2] > 1000 or w['rect'][3] > 800]
            drag(cap_now[0]['hwnd'], *SEL_D)
            bars = [w for w in windows_of(pid)
                    if w['cls'] == 'Ling' and w['hwnd'] != cap_now[0]['hwnd']]
            if not bars:
                print('  => **问题：框完之后没有工具条**')
                ok = False
            else:
                before_rect = bars[0]['rect']
                key(VK_COMMA)          # 翻到上一条：选区换成 masks[0]，工具条该立刻跟过去
                time.sleep(1.2)
                bars2 = [w for w in windows_of(pid)
                         if w['cls'] == 'Ling' and w['hwnd'] != cap_now[0]['hwnd']]
                if not bars2:
                    print('  => **问题：翻页之后工具条不见了**')
                    ok = False
                else:
                    after_rect = bars2[0]['rect']
                    want_right = masks[0][1][2]          # 选区的屏幕右边缘
                    got_right = after_rect[0] + after_rect[2]
                    print('   翻页前工具条 x=%d，翻页后 x=%d（没动过鼠标）'
                          % (before_rect[0], after_rect[0]))
                    print('   翻页后工具条右边缘 = %d（应为新选区右边缘 %d）'
                          % (got_right, want_right))
                    if want_right == SEL_D[2]:
                        # 新旧右边缘一样时这一步没有判别力（位置本来就在那儿），跳过
                        print('   （跳过"位置变没变"：新选区右边缘和本轮选区相同）')
                    elif after_rect[0] == before_rect[0]:
                        print('  => **问题：工具条没跟过去（还停在上一条的位置）**')
                        ok = False
                    if abs(got_right - want_right) > 8:
                        print('  => **问题：工具条没对齐到新选区**')
                        ok = False

        print('== 数据目录检查 ==')
        cfg_ok = os.path.exists(CFG)
        temp_ok = os.path.isdir(os.path.join(EXE_DIR, 'temp'))
        print('   exe 同目录 config.json = %s，temp\\ = %s' % (cfg_ok, temp_ok))
        if not (cfg_ok and temp_ok):
            print('  => **问题：数据目录没落在 exe 同目录**')
            ok = False

        print('== 快速保存：开开关 + 指到临时目录，截一张按保存，应直接落盘不弹框 ==')
        proc.kill()
        proc.wait(timeout=5)
        write_cfg(quick_save=True, save_dir=KEEP_DIR)
        proc = subprocess.Popen([EXE])
        pid = proc.pid
        time.sleep(3.0)
        key(0x70)
        time.sleep(2.0)
        cap = [w for w in windows_of(pid) if w['rect'][2] > 1000 or w['rect'][3] > 800][0]
        drag(cap['hwnd'], *SEL_B)
        user32.keybd_event(0x11, 0, 0, 0)   # Ctrl 按住
        time.sleep(0.1)
        user32.keybd_event(0x53, 0, 0, 0)   # S
        time.sleep(0.15)
        user32.keybd_event(0x53, 0, 2, 0)
        user32.keybd_event(0x11, 0, 2, 0)
        time.sleep(2.0)
        saved = [f for f in os.listdir(KEEP_DIR) if f.lower().endswith('.png')]
        print('   快速保存目录里的文件：%s' % saved)
        if not saved:
            print('  => **问题：快速保存没直接落盘**')
            ok = False
        else:
            from PIL import Image
            im = Image.open(os.path.join(KEEP_DIR, saved[0]))
            print('   落盘图片尺寸 = %s（应为 %s）'
                  % (im.size, (SEL_B[2] - SEL_B[0], SEL_B[3] - SEL_B[1])))
            if im.size != (SEL_B[2] - SEL_B[0], SEL_B[3] - SEL_B[1]):
                print('  => **问题：快速保存存的图不对**')
                ok = False
        print('== 改过绑定之后：新键生效、旧键失效 ==')
        proc.kill()
        proc.wait(timeout=5)
        # 把翻页键改成 [ 和 ]（走的就是设置页会写的那两个键），重启后应当立刻生效
        write_cfg(prev_shot='[', next_shot=']')
        proc = subprocess.Popen([EXE])
        pid = proc.pid
        time.sleep(3.0)

        # 先做反向对照：默认的 , 已经不该再翻页了，回车复制的应当还是当前这个选区。
        # 想区分"没翻"和"翻了"：翻了的话会落到历史里某一条，尺寸是 700x600 或 500x400，
        # 和这里的 300x300 不会撞
        key(0x70)
        time.sleep(2.0)
        cap = [w for w in windows_of(pid) if w['rect'][2] > 1000 or w['rect'][3] > 800][0]
        drag(cap['hwnd'], *SEL_C)
        key(VK_COMMA)      # 改绑之后这个键已经不管翻页了
        time.sleep(1.0)
        key(VK_RETURN)
        time.sleep(1.5)
        size = clipboard_png_size()
        want_c = (SEL_C[2] - SEL_C[0], SEL_C[3] - SEL_C[1])
        print('   改绑后按 , 再复制 = %s（应为当前选区 %s，说明 , 已失效）' % (size, want_c))
        if size != want_c:
            print('  => **问题：改绑之后旧的 , 居然还在翻页**')
            ok = False

        # 再验新键：连续按两次 [ 往前翻两条，落到哪一条直接问历史文件（下标 1）
        before = read_shot_rects()
        want = before[1][1]
        key(0x70)
        time.sleep(2.0)
        cap = [w for w in windows_of(pid) if w['rect'][2] > 1000 or w['rect'][3] > 800][0]
        drag(cap['hwnd'], *SEL_C)
        key(VK_OEM_4)      # [ = 上一条
        time.sleep(1.0)
        key(VK_OEM_4)      # [ 再往前一条
        time.sleep(1.0)
        key(VK_RETURN)
        time.sleep(1.5)
        size = clipboard_png_size()
        print('   改绑后连按两次 [ 再复制 = %s（应为往下数第 3 条 %s）' % (size, want))
        if size != want:
            print('  => **问题：配置里改的翻页键没生效**')
            ok = False
    finally:
        try:
            proc.kill()
            proc.wait(timeout=5)
        except Exception:
            pass

    print('\n===== %s =====' % ('全部通过' if ok else '有问题'))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
