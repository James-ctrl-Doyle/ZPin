r"""测试用的配置护栏。

这些脚本为了隔离配置，会把 `<exe 同目录>\\config.json` 当成"便携配置"反复覆盖 ——
但数据目录从 2026-09-19 起就在 exe 同目录，那份文件**就是用户真实的配置**。
不护栏的话，跑一次测试就把用户的热键、画笔粗细、边框粗细全冲掉。

用法（脚本里紧跟 PORTABLE_CFG 定义之后两行）：

    import _cfg_guard
    _cfg_guard.install(PORTABLE_CFG)

三个要点（都是踩出来的）：

1. **`已有旧备份就不覆盖`才是真正的保险**：Windows 上没有 POSIX 信号 —— `timeout` 和
   `Popen.terminate()` 落到进程上的都是 TerminateProcess（硬杀），`finally` 和 atexit
   一律不会执行（拿这个结论反推过一次事故：那次 `timeout 400` 打断的历史测试把用户配置
   留在了"测试配置"状态，下一次运行又把这份测试配置当成"用户原配置"备份下来，等于把
   设置永久弄丢）。所以规则是：`.testbak` 只要还在，它就是干净的那一份，新一次运行
   沿用它、只在**正常退出**时还原。代价是要多跑一次才能救回来，但不会再丢。
   （下面仍挂了 SIGTERM/SIGINT 处理，在 POSIX 上有效，在 Windows 上是死代码。）
2. 还原后删掉 `.testbak`，下次正常跑可以重新备份。
3. 用户**本来没有**这份配置时，退出时把自己写出来的删掉，别给人留下测试配置。
"""
import atexit
import os
import shutil
import signal
import sys
import time

_installed = set()


def kill_running_instances():
    r"""结束正在运行的 ZPin 实例（测试开始时的对称兜底）。

    程序有单实例检测：老实例还活着时，测试新起的实例会直接退场，
    于是测试要么整片失败（"F1 后可见窗口=0"），要么在驱动**老代码**的窗口 ——
    后者更阴：结果全"通过"，验的却是旧版本。rebuild_all.sh 在构建前做同样的事，
    但构建完到测试之间用户随时可能又把 release 里的 exe 点起来，所以测试侧
    开头也要杀一遍。

    用进程快照枚举（Toolhelp32），不用 tasklist/taskkill：
    tasklist 输出是 GBK、本机 taskkill 不可用。杀完等 1 秒再返回，
    让 exe 的文件锁释放（后面可能要覆盖或重新启动它）。
    """
    import ctypes
    from ctypes import wintypes

    # ⚠ 匹配必须用前缀而不是精确名：release 目录的发布件叫 ZPin_<版本>.exe，
    # 进程名是 "ZPin_2.6.0" 这种 —— 按精确名单杀 ZPin/ZPin.build 会漏掉它，
    # 老 release 实例就这么活下来的（2026-09-26 用户实际踩到）。
    def _is_ours(name):
        n = name.lower()
        return n.endswith('.exe') and (n.startswith('zpin') or n.startswith('screencapture'))

    k32 = ctypes.WinDLL('kernel32', use_last_error=True)
    TH32CS_SNAPPROCESS = 0x00000002
    INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
    PROCESS_TERMINATE = 0x0001

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ('dwSize', wintypes.DWORD),
            ('cntUsage', wintypes.DWORD),
            ('th32ProcessID', wintypes.DWORD),
            ('th32DefaultHeapID', ctypes.c_size_t),
            ('th32ModuleID', wintypes.DWORD),
            ('cntThreads', wintypes.DWORD),
            ('th32ParentProcessID', wintypes.DWORD),
            ('pcPriClassBase', wintypes.LONG),
            ('dwFlags', wintypes.DWORD),
            ('szExeFile', ctypes.c_wchar * 260),
        ]

    # 句柄类返回值/参数必须显式声明，否则 64 位句柄被截断（踩过两次，见 ZPin-notes 第 6 节）
    k32.CreateToolhelp32Snapshot.restype = ctypes.c_void_p
    k32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    k32.Process32FirstW.argtypes = [ctypes.c_void_p, ctypes.POINTER(PROCESSENTRY32W)]
    k32.Process32NextW.argtypes = [ctypes.c_void_p, ctypes.POINTER(PROCESSENTRY32W)]
    k32.OpenProcess.restype = ctypes.c_void_p
    k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k32.TerminateProcess.argtypes = [ctypes.c_void_p, wintypes.UINT]
    k32.CloseHandle.argtypes = [ctypes.c_void_p]

    snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snap in (None, INVALID_HANDLE_VALUE):
        print('[cfg-guard] !! 进程快照创建失败，跳过杀旧实例（err=%d）' % k32.GetLastError())
        return []
    killed = []
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        ok = k32.Process32FirstW(snap, ctypes.byref(entry))
        while ok:
            if entry.th32ProcessID != os.getpid() and _is_ours(entry.szExeFile):
                h = k32.OpenProcess(PROCESS_TERMINATE, False, entry.th32ProcessID)
                if h:
                    k32.TerminateProcess(h, 1)
                    k32.CloseHandle(h)
                    killed.append((entry.szExeFile, entry.th32ProcessID))
            ok = k32.Process32NextW(snap, ctypes.byref(entry))
    finally:
        k32.CloseHandle(snap)
    if killed:
        print('[cfg-guard] 已结束正在运行的旧实例：%s' %
              ', '.join('%s(pid %d)' % (n, p) for n, p in killed))
        time.sleep(1)   # 等文件锁释放，测试随后可能要覆盖/启动这个 exe
    return killed


def install(cfg_path, label=''):
    if cfg_path in _installed:
        return
    _installed.add(cfg_path)
    bak = cfg_path + '.testbak'
    tag = label or os.path.basename(cfg_path)

    # 先杀旧实例再备份配置：实例活着时既可能占着 config.json，也可能在测试
    # 起新实例前抢走单实例名额（症状见 kill_running_instances 的 docstring）
    kill_running_instances()

    if os.path.exists(bak):
        # 上一次没收拾干净：那份备份比磁盘现在的配置更可信，别动它
        print('[cfg-guard] 发现上次留下的备份 %s，沿用它（不覆盖）' % os.path.basename(bak))
        had = True
    else:
        had = os.path.exists(cfg_path)
        if had:
            shutil.copy2(cfg_path, bak)

    def restore(*_):
        try:
            if had:
                shutil.copy2(bak, cfg_path)
                if os.path.exists(bak):
                    os.remove(bak)
                print('[cfg-guard] 已还原 %s' % tag)
            elif os.path.exists(cfg_path):
                # 用户本来没有这份配置：把自己写出来的删掉，别给人家留下测试配置
                os.remove(cfg_path)
                print('[cfg-guard] 已清掉测试写出的 %s' % tag)
        except Exception as e:
            print('[cfg-guard] !! 还原 %s 失败：%s' % (tag, e))

    atexit.register(restore)

    def on_signal(signum, _frame):
        restore()
        signal.signal(signum, signal.SIG_DFL)
        os.kill(os.getpid(), signum)

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(sig, on_signal)
        except Exception:
            pass
