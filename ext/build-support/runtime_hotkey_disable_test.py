"""验证"关闭所有快捷键"开关（托盘菜单项 / common.disableHotkeys）。

⚠ 不要用"注入按键看热键响不响应"来测 —— 注入键（keybd_event/SendInput）对
RegisterHotKey 热键的触发依赖桌面会话状态（实测出现过同一脚本先几百次成功、
之后全程失效的环境漂移，与程序行为无关）。改用**持有探测**：程序注册了某个
全局热键，别的进程 RegisterHotKey 同一组合就会失败 —— 用这个判断程序"持有"
哪些热键，稳定且不依赖注入：

  模式 on  ：config 里 common.disableHotkeys=true 启动
             → F1 / F3 都应**空闲**（程序不持有任何全局热键）
  模式 off ：正常配置启动
             → F1 / F3 都应**被程序持有**（RegisterHotKey 失败）

托盘菜单切换（setDisableHotkeys 的 unReg/reg 循环）与启动注册（initShortcutKeys）
由同一张 shortcutTable 驱动；配置持久化由 save() 保证，重启后状态保持。

用法：python runtime_hotkey_disable_test.py on|off
"""
import ctypes
import os
import subprocess
import sys
import time

u = ctypes.windll.user32
try:
    u.SetProcessDPIAware()
except Exception:
    pass

_HERE = os.path.dirname(os.path.abspath(__file__))
_BUILD = os.path.normpath(os.path.join(_HERE, '..', 'build'))
EXE = os.environ.get('SC_EXE') or os.path.join(_BUILD, 'bin', 'x64', 'Release', 'ScreenCapture.build.exe')
PORTABLE_CFG = os.path.join(os.path.dirname(EXE), 'config.json')
import _cfg_guard          # exe 同目录的 config.json = 用户真实配置，得护栏
_cfg_guard.install(PORTABLE_CFG)


def held(vk):
    """探测某个键当前是否被别的进程注册为全局热键（无修饰符）。
    RegisterHotKey 成功 = 空闲；失败 = 已被持有。探测后立刻释放。"""
    ok = u.RegisterHotKey(None, 0xC0F0, 0, vk)
    if ok:
        u.UnregisterHotKey(None, 0xC0F0)
    return not ok


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else 'off'
    disable = mode == 'on'
    if os.path.exists(PORTABLE_CFG):
        os.remove(PORTABLE_CFG)
    with open(PORTABLE_CFG, 'w', encoding='utf-16') as f:
        f.write('{"common":{"autoStart":false,"language":"zh-CN","disableHotkeys":%s},'
                '"shortcutKey":{"cap":"F1","pin":"F3"}}' % ('true' if disable else 'false'))

    proc = subprocess.Popen([EXE])
    try:
        time.sleep(4.0)
        f1, f3 = held(0x70), held(0x72)
        print('模式=%s（disableHotkeys=%s）：F1 被持有=%s，F3 被持有=%s'
              % (mode, disable, f1, f3))
        if disable:
            if f1 or f3:
                print('  => **问题：禁用状态下程序仍持有全局热键**')
                return 1
            print('  => 通过：禁用状态下程序没有持有任何全局热键')
        else:
            if f1 and f3:
                print('  => 通过：正常配置下 F1/F3 都被程序持有（热键已注册）')
            else:
                print('  => **问题：正常配置下热键没有注册上（F1=%s F3=%s）**' % (f1, f3))
                return 1
        return 0
    finally:
        try:
            proc.kill()
            proc.wait(timeout=5)
        except Exception:
            pass


if __name__ == '__main__':
    sys.exit(main())
