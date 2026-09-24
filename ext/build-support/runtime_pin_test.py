"""端到端运行时验证（不碰键盘，全部用 PostMessage 模拟热键）。

验四件事：
  1. 不带参数启动 exe 之后**没有**任何可见窗口（第 6 条：不再自动进截图模式）
  2. 贴图热键能读到数据目录里的临时文件（第 1 条：图来自临时文件而不是剪贴板）
  3. 贴出来的窗口落在当初记录的那块屏幕上（第 3 条：贴至原位）
  4. 整条链路不崩（窗口真的建出来了，尺寸与图一致）

用的是独立进程 + 便携配置，跑完把临时文件和便携配置都删掉，
不碰用户 %appdata% 里那份 config.json。
"""
import _pylibs  # noqa: F401  —— 把 ext/build/.pylibs（Pillow）挂进 sys.path
import ctypes
import os
import struct
import subprocess
import sys
import time
from ctypes import wintypes

user32 = ctypes.WinDLL('user32', use_last_error=True)
kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)

WM_HOTKEY = 0x0312
WM_APP = 0x8000
HWND_MESSAGE = -3
_HERE = os.path.dirname(os.path.abspath(__file__))
_BUILD = os.path.normpath(os.path.join(_HERE, '..', 'build'))
# 产物路径从脚本自身位置推导（脚本在 <仓库根>/ext/build-support/），换机器/挪目录都不用改。
# 需要指到别的 exe 时用环境变量 SC_EXE
EXE = os.environ.get('SC_EXE') or os.path.join(_BUILD, 'bin', 'x64', 'Release', 'ZPin.build.exe')
EXE_DIR = os.path.dirname(EXE)
# 数据目录已经搬到 exe 同目录了（不再建 %appdata%\ZPin），
# last.bin 现在落在 <exe 目录>\temp\last.bin
APPDATA = EXE_DIR
TEMP_DIR = os.path.join(APPDATA, 'temp')
TEMP_FILE = os.path.join(TEMP_DIR, 'last.bin')
PORTABLE_CFG = os.path.join(EXE_DIR, 'config.json')
import _cfg_guard          # 这行文件就是 <exe 同目录>\config.json = 用户真实配置，得护栏
_cfg_guard.install(PORTABLE_CFG)

# 造一张带字的图（顺便把识别那条路也跑起来）。位置故意挑个不居中的地方，
# 这样"原位贴出"和"居中贴出"能一眼区分开
IMG_X, IMG_Y, IMG_W, IMG_H = 300, 220, 420, 160

EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


def make_capture_bin(path):
    """按 Util::saveLastCapture 的格式写：'SCAP' + version + x,y,w,h + BGRA 像素"""
    from PIL import Image, ImageDraw
    img = Image.new('RGB', (IMG_W, IMG_H), (255, 255, 255))
    d = ImageDraw.Draw(img)
    d.text((16, 16), "hello pin 1234", fill=(0, 0, 0))
    d.text((16, 60), "文字识别测试", fill=(0, 0, 0))
    # 左下角一块纯色，方便肉眼认出这是测试图
    d.rectangle([0, IMG_H - 24, IMG_W, IMG_H], fill=(0, 120, 215))
    # PIL 是 RGB，转成 BGRA
    bgra = bytearray()
    px = img.load()
    for y in range(IMG_H):
        for x in range(IMG_W):
            r, g, b = px[x, y]
            bgra += bytes((b, g, r, 255))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'wb') as f:
        f.write(struct.pack('<4sIiiii', b'SCAP', 1, IMG_X, IMG_Y, IMG_W, IMG_H))
        f.write(bytes(bgra))
    print('  写好临时截图 %s（%dx%d @ %d,%d）' % (path, IMG_W, IMG_H, IMG_X, IMG_Y))


def windows_of(pid):
    """列出该进程的所有顶层可见/不可见窗口"""
    found = []

    def cb(hwnd, _):
        wpid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(wpid))
        if wpid.value == pid:
            cls = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, cls, 256)
            title = ctypes.create_unicode_buffer(512)
            user32.GetWindowTextW(hwnd, title, 512)
            r = wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(r))
            found.append({
                'hwnd': hwnd, 'cls': cls.value, 'title': title.value,
                'visible': bool(user32.IsWindowVisible(hwnd)),
                'rect': (r.left, r.top, r.right - r.left, r.bottom - r.top),
            })
        return True

    user32.EnumWindows(EnumWindowsProc(cb), 0)
    return found


def find_msg_window(pid):
    """消息窗口是 message-only 类型，EnumWindows 看不到，得从 HWND_MESSAGE 顺着找"""
    prev = None
    while True:
        hwnd = user32.FindWindowExW(wintypes.HWND(HWND_MESSAGE), prev, 'STATIC', None)
        if not hwnd:
            return None
        prev = hwnd
        wpid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(wpid))
        if wpid.value == pid:
            title = ctypes.create_unicode_buffer(512)
            user32.GetWindowTextW(hwnd, title, 512)
            print('  找到消息窗口 class=STATIC title=%s' % title.value)
            return hwnd


def main():
    if not os.path.exists(EXE):
        print('!! 找不到 exe：' + EXE)
        return 1

    print('== 0) 准备：便携配置 + 一份"最近一次截图" ==')
    with open(PORTABLE_CFG, 'w', encoding='utf-16') as f:
        f.write('{"common":{"autoStart":false,"language":"zh-CN"},'
                '"shortcutKey":{"cap":"F1","pin":"F3"}}')
    make_capture_bin(TEMP_FILE)

    print('\n== 1) 不带参数启动，看它是不是自动进了截图模式 ==')
    proc = subprocess.Popen([EXE])
    pid = proc.pid
    time.sleep(2.5)
    ws = windows_of(pid)
    vis = [w for w in ws if w['visible']]
    print('  进程 pid=%d，顶层窗口 %d 个，其中可见 %d 个' % (pid, len(ws), len(vis)))
    for w in ws:
        print('     %-24s visible=%-5s rect=%s title=%r'
              % (w['cls'], w['visible'], w['rect'], w['title']))
    ok_tray = (len(vis) == 0)
    print('  => %s' % ('通过：启动后没有可见窗口（只在托盘待命）' if ok_tray
                       else '**失败：启动就弹了窗口**'))

    print('\n== 2) PostMessage 模拟贴图热键（WM_APP+101）==')
    hwnd = find_msg_window(pid)
    if not hwnd:
        print('  !! 没找到消息窗口，后面的测试没法做')
        proc.kill()
        return 1
    user32.PostMessageW(hwnd, WM_HOTKEY, WM_APP + 101, 0)
    time.sleep(3.0)   # 建窗口 + 后台识别

    ws = windows_of(pid)
    vis = [w for w in ws if w['visible']]
    print('  现在可见窗口 %d 个：' % len(vis))
    for w in vis:
        print('     %-24s rect=%s title=%r' % (w['cls'], w['rect'], w['title']))

    # 贴图窗口应当落在当初记录的位置上，尺寸与图一致
    hit = None
    for w in vis:
        x, y, cw, ch = w['rect']
        if x == IMG_X and y == IMG_Y:
            hit = w
            break
    ok_pos = hit is not None
    print('  => %s' % ('通过：贴到了原位 (%d,%d)' % (IMG_X, IMG_Y) if ok_pos
                       else '**失败：没有窗口落在 (%d,%d)**' % (IMG_X, IMG_Y)))
    if hit:
        x, y, cw, ch = hit['rect']
        ok_size = (cw == IMG_W and ch == IMG_H)
        print('  => 尺寸 %dx%d，%s' % (cw, ch, '与原图一致' if ok_size else
                                      '**与原图 %dx%d 不一致（可能被缩放）**' % (IMG_W, IMG_H)))

    print('\n== 3) 收尾 ==')
    proc.kill()
    proc.wait(timeout=5)
    time.sleep(0.5)
    print('  已结束进程 %d' % pid)

    return 0 if (ok_tray and ok_pos) else 1


if __name__ == '__main__':
    rc = 1
    try:
        rc = main()
    finally:
        # 清理：便携配置与临时截图都不留下，用户 appdata 里的 config.json 不动
        for p in (PORTABLE_CFG, TEMP_FILE):
            try:
                os.remove(p)
                print('  已删除 ' + p)
            except OSError:
                pass
        try:
            os.rmdir(TEMP_DIR)
            print('  已删除空目录 ' + TEMP_DIR)
        except OSError:
            pass
    print('\n===== 退出码 %d =====' % rc)
    sys.exit(rc)
