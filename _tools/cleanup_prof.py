# 清理排查录屏问题时埋的临时日志/计时（TEMP-PROF、vtrace 那一套）。
# 用文件的形式跑，避免在 shell 里跟引号搏斗。
import io
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(_HERE, '..'))   # 脚本在 <仓库根>/_tools/ 下
SRC = os.path.join(ROOT, 'Src')


def edit(rel, pairs, must=True):
    p = os.path.join(SRC, rel)
    s = io.open(p, encoding='utf-8').read()
    for old, new in pairs:
        if old not in s:
            if must:
                raise SystemExit('!! 没找到片段（%s）：\n%s' % (rel, old[:120]))
            continue
        s = s.replace(old, new)
    io.open(p, 'w', encoding='utf-8').write(s)
    print('已清理', rel)


# ---------- CapVideo.cpp ----------
edit('Win/CapVideo.cpp', [
    ('''#include <fstream>   // TEMP-PROF
#include <cstdio>    // TEMP-PROF
namespace vtrace {''', '''namespace UNUSED_VTRACE_REMOVED {'''),
])
# 上面那步只是把开头替换掉，剩下整个 vtrace 块要按范围删
p = os.path.join(SRC, 'Win/CapVideo.cpp')
s = io.open(p, encoding='utf-8').read()
start = s.index('namespace UNUSED_VTRACE_REMOVED {')
end = s.index('#include "VideoMp4.hpp"')
s = s[:start] + s[end:]
io.open(p, 'w', encoding='utf-8').write(s)

edit('Win/CapVideo.cpp', [
    ('''    {   // TEMP-PROF 每轮清空
        std::ofstream f("C:\\\\Users\\\\zqw35\\\\WorkBuddy\\\\ScreenCapture-src\\\\ext\\\\build\\\\logs\\\\video_trace.log", std::ios::trunc);
        f << "=== 录屏跟踪（speaker=" << (useSpeaker ? 1 : 0) << " mic=" << (useMic ? 1 : 0) << "）===\\n";
    }
''', ''),
    ('        vtrace::vtRaw(">>> 采集线程启动"); // TEMP-PROF\n', ''),
    ('        vtrace::vtRaw(">>> MFStartup 完成"); // TEMP-PROF\n', ''),
    ('        vtrace::vtRaw(">>> CoInitializeEx 完成，开始收集桌面复制目标"); // TEMP-PROF\n', ''),
    ('        vtrace::vtRaw(">>> DesktopCapture 全部尝试结束，准备 CoUninitialize"); // TEMP-PROF\n', ''),
    ('        vtrace::vtRaw(">>> CoUninitialize 完成"); // TEMP-PROF\n', ''),
    ('        vtrace::vtRaw(">>> MFShutdown 完成，采集线程即将退出"); // TEMP-PROF\n', ''),
    ('    vtrace::vtRaw(">>> dispose() 进入"); // TEMP-PROF\n', ''),
    ('    vtrace::vtRaw(">>> dispose(): stop() 已返回，准备关录屏工具条"); // TEMP-PROF\n', ''),
    ('    vtrace::vtRaw(">>> dispose(): 工具条已关，dispose 完成"); // TEMP-PROF\n', ''),
    ('    long long vt0 = vtrace::vtNow(); // TEMP-PROF\n', ''),
    ('    vtrace::vtMark("stop() 进入", vt0); // TEMP-PROF\n', ''),
    ('    if (!mp4Param) { vtrace::vtMark("stop() 无事可做（没有 mp4Param）", vt0); return L""; }',
     '    if (!mp4Param) return L"";'),
    ('    vtrace::vtMark("win->hide() 完成", vt0); // TEMP-PROF\n', ''),
    ('    vtrace::vtMark("MustEnd 已置位，准备 join", vt0); // TEMP-PROF\n', ''),
    ('    vtrace::vtMark("join 返回", vt0); // TEMP-PROF\n', ''),
])

# ---------- VideoMp4.hpp ----------
edit('Win/VideoMp4.hpp', [
    ('        { static int vtN = 0; vtrace::vtLoop(++vtN, dp.MustEnd); } // TEMP-PROF\n', ''),
    ('    vtrace::vtRaw(">>> 录屏循环已退出，开始收尾"); // TEMP-PROF\n', ''),
    ('    vtrace::vtRaw("    音频已 Stop，进 Finalize"); // TEMP-PROF\n\n', '\n'),
    ('    vtrace::vtRaw("    Finalize 返回"); // TEMP-PROF\n', ''),
    ('    vtrace::vtRaw(">>> DesktopCapture 返回 0"); // TEMP-PROF\n', ''),
])
# 那块“桌面复制格式”日志是带大括号的一段，按范围删
s = io.open(os.path.join(SRC, 'Win/VideoMp4.hpp'), encoding='utf-8').read()
key = '        {   // TEMP-PROF\n'
if key in s:
    start = s.index(key)
    end = s.index('        if (desc.Format == DXGI_FORMAT_R16G16B16A16_FLOAT)')
    s = s[:start] + s[end:]
    io.open(os.path.join(SRC, 'Win/VideoMp4.hpp'), 'w', encoding='utf-8').write(s)
    print('已清理 VideoMp4.hpp 的格式日志段')

# ---------- WinCap.cpp ----------
edit('Win/WinCap.cpp', [
    ('namespace vtrace { void vtRaw(const char* s); } // TEMP-PROF 定义在 CapVideo.cpp\n', ''),
    ('    vtrace::vtRaw("onClosed: 进入");\n', ''),
    ('    if (capVideo) { capVideo->dispose(); vtrace::vtRaw("onClosed: capVideo->dispose() 完成"); }',
     '    if (capVideo) capVideo->dispose();'),
    ('    if (capLong) { capLong->dispose(); vtrace::vtRaw("onClosed: capLong->dispose() 完成"); }',
     '    if (capLong) capLong->dispose();'),
    ('    if (toolSub) { toolSub->close(); vtrace::vtRaw("onClosed: toolSub->close() 完成"); }',
     '    if (toolSub) toolSub->close();'),
    ('    if (toolMain) { toolMain->close(); vtrace::vtRaw("onClosed: toolMain->close() 完成"); }',
     '    if (toolMain) toolMain->close();'),
    ('    vtrace::vtRaw("onClosed: 准备 TryEnqueue");\n', ''),
    ('        vtrace::vtRaw("dq 回调: 进入");\n', ''),
    ('        vtrace::vtRaw("dq 回调: winCap.reset() 完成");\n', ''),
    ('            vtrace::vtRaw("dq 回调: 没有贴图窗口");\n', ''),
    ('                vtrace::vtRaw("dq 回调: 走 quit");\n', ''),
    ('                vtrace::vtRaw("dq 回调: quit 返回");\n', ''),
    ('                vtrace::vtRaw("dq 回调: 准备 checkLater");\n', ''),
    ('                vtrace::vtRaw("dq 回调: checkLater 完成");\n', ''),
    ('        vtrace::vtRaw("dq 回调: 结束（下面就是 dq 泵里的事）");\n', ''),
])
print('全部清理完成')
