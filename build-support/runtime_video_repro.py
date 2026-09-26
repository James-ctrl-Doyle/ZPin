"""复现"进入截图模式后点录屏按钮，工具条消失"——用**用户真实环境**：

- exe 用 _review/ZPin_<版本>.exe（交付目录里那份，旁边就是
  用户的真实 config.json），**不覆盖那份 config.json**（cfg_guard 会备份/还原）。
  对比：runtime_video_probe.py 每次都自己写一份接近默认的测试配置 —— 这正是
  它一直复现不出来、而用户天天能撞见的原因之一。
  （2026-09-22 之前这里是 _review/ZPin.exe；_review 已撤销，配置与运行
   数据都收进了 _review/。）
- 窗口枚举**包含隐藏窗口**：如果 ToolVideo 建出来了但 IsWindowVisible=false，
  或者建在了屏幕外，probe 那种"只看可见窗口"的列表根本暴露不了。
- 全屏截图留档，肉眼确认工具条在不在画面里。

用法：python runtime_video_repro.py [left top right bottom]（默认贴右边选区）
"""
import _pylibs  # noqa: F401  —— 把 build/.pylibs（Pillow）挂进 sys.path
import glob
import importlib.util
import os
import subprocess
import sys
import time

try:
    import ctypes
    ctypes.windll.shcore.SetProcessDPIAwareness(2)
except Exception:
    pass

_HERE = os.path.dirname(os.path.abspath(__file__))
# 本文件在 <仓库根>/build-support/ 下，仓库根要往上两级
_REPO = os.path.normpath(os.path.join(_HERE, '..', '..'))
# 默认用交付目录里那份 exe + 它旁边的真实 config（cwd 会是 exe 目录）。
# 文件名带版本号（ZPin_2.6.0.exe），所以按通配取最新的那个。
_REL_DIR = os.path.join(_REPO, 'ext', 'build', 'release')
_CANDS = sorted(glob.glob(os.path.join(_REL_DIR, 'ZPin_*.exe')))
if not _CANDS:
    print("!! 交付目录里没有 ZPin_*.exe：%s" % _REL_DIR)
    print("   先跑 bash build-support/rebuild_all.sh，或用 SC_EXE 环境变量指定 exe")
os.environ.setdefault('SC_EXE', _CANDS[-1] if _CANDS else '')

spec = importlib.util.spec_from_file_location(
    'vp', os.path.join(_HERE, 'runtime_video_probe.py'))
vp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vp)     # 模块级会装 cfg_guard（备份/还原 exe 目录的 config.json）

from ctypes import wintypes
import ctypes
from PIL import ImageGrab

SEL = (700, 350, 1910, 950)
if len(sys.argv) >= 5:
    SEL = tuple(int(v) for v in sys.argv[1:5])


def dump_all(pid, tag):
    """全部窗口（含隐藏）都列出来，可见 / 隐藏分开。"""
    allw = vp.windows_of(pid, visible=False)
    print('--- %s：进程共 %d 个窗口 ---' % (tag, len(allw)))
    for w in allw:
        r = w['rect']
        wa = vp.work_area()
        out = ''
        if r[0] + r[2] > wa[2] or r[1] + r[3] > wa[3] or r[0] < wa[0] or r[1] < wa[1]:
            out = '   <<< 越出工作区 %s' % (wa,)
        print('   %-8s %s visible=%-5s rect=%s%s'
              % (w['hwnd'], w['cls'], w['visible'], r, out))
    return allw


def shot(tag):
    p = os.path.join(vp.LOG_DIR, 'repro_%s.png' % tag)
    ImageGrab.grab(all_screens=True).save(p)
    print('   截图 %s' % p)


def main():
    wa = vp.work_area()
    print('工作区 = %s   选区 = %s' % (wa, SEL))
    proc = subprocess.Popen([vp.EXE])
    pid = proc.pid
    try:
        time.sleep(3.0)
        vp.find_msg_window(pid)
        vp.key(0x70)                 # F1
        time.sleep(2.0)
        cap = [w for w in vp.windows_of(pid) if w['rect'][2] > 1000 or w['rect'][3] > 800][0]
        capwnd = cap['hwnd']
        print('=== 真鼠标拖框 %s ===' % (SEL,))
        vp.real_drag(*SEL)
        time.sleep(0.5)

        bars = [w for w in vp.windows_of(pid) if w['hwnd'] != capwnd and w['cls'] == 'Ling']
        if not bars:
            print('=> **拖完框主工具条就没出现**')
            return 1
        bar = bars[0]
        barw, barh = bar['rect'][2], bar['rect'][3]
        w1 = (barw - 3.0) / 16
        vid_x = bar['rect'][0] + int(11 * w1 + 2 * 1.5 + w1 / 2)
        vid_y = bar['rect'][1] + barh // 2
        # 与 probe 相同的前提：光标停在工具条上、工具条是活动窗口
        vp.user32.SetForegroundWindow(wintypes.HWND(bar['hwnd']))
        time.sleep(0.4)
        print('=== 真鼠标点"录屏"（屏 %d,%d）===' % (vid_x, vid_y))
        vp.real_click(vid_x, vid_y)
        time.sleep(2.0)

        allw = dump_all(pid, '点录屏按钮之后')
        shot('after_click')

        vis_ling = [w for w in allw if w['visible'] and w['cls'] == 'Ling'
                    and w['hwnd'] != capwnd]
        if not vis_ling:
            print('=> **问题：点录屏按钮后，除覆盖层外没有任何可见的工具条窗口**')
            return 1
        tb = vis_ling[0]
        print('=> 录屏工具条 hwnd=%s rect=%s visible=True' % (tb['hwnd'], tb['rect']))
        r = tb['rect']
        if r[0] + r[2] > wa[2] or r[1] + r[3] > wa[3] or r[0] < wa[0] or r[1] < wa[1]:
            print('=> **问题：工具条越出屏幕工作区（工作区=%s）**' % (wa,))
            return 1
        # 再逐点问命中：真按上去能不能点到
        print('   命中测试：')
        for i in range(4):
            x = r[0] + int((i + 0.5) * r[2] / 4)
            y = r[1] + r[3] // 2
            print('     第 %d 点 (屏 %d,%d) -> %s' % (i, x, y, vp.hit_label(pid, x, y)))
        print('=> 通过：录屏工具条可见、在屏幕内')
        return 0
    finally:
        try:
            proc.kill()
            proc.wait(timeout=5)
        except Exception:
            pass


if __name__ == '__main__':
    sys.exit(main())
