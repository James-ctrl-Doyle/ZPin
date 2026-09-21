r"""生成一份 ScreenCapture 的工程副本，用于本机编译验证。

为什么要副本：原 `Src/ScreenCapture.vcxproj` 里的 IntDir / OutDir 会落到仓库里，
而我们要把中间产物和 exe 都放到工作区的 `ext/build/` 下，不污染仓库。所以不改原文件，
只生成一份同目录的副本（`ScreenCapture.build.vcxproj`），把产物目录指过去。

Ling 的路径**不用替换**：原工程写的是 `$(SolutionDir)ext\Ling`，而 Ling 已经内置在仓库的
`ext/Ling`，用 `ScreenCapture.slnx` 打开就能直接编（见 Doc/Build.md）。
副本里之所以还是要换成绝对路径，是因为 MSBuild 直接编 .vcxproj（不经过 .slnx）时
`$(SolutionDir)` 是空的。

（GIF 录屏已于 2026-09-13 删除，所以不再需要 gifski 的桩 —— 见 _removed_gif/）
"""
import os

# 路径全部从本文件位置推导，不写死任何机器上的绝对路径。
# 本文件在 <仓库根>/ext/build-support/ 下，所以**往上两级**才是仓库根
# （ext/build-support → ext → <仓库根>）。
# ⚠ 它原来放在 <仓库根>/_tools/，那时是一级。2026-09-22 收拢到 ext/build-support/
#    时改过这里 —— 当时先写成三级，把 ROOT 推到了仓库的父目录，构建直接
#    FileNotFoundError 找不到 Src/ScreenCapture.vcxproj。数层数要照着实际目录数。
ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                     '..', '..'))
EXT = os.path.join(ROOT, 'ext')
SRC = os.path.join(ROOT, 'Src')

src_path = os.path.join(SRC, 'ScreenCapture.vcxproj')
dst_path = os.path.join(SRC, 'ScreenCapture.build.vcxproj')

raw = open(src_path, 'rb').read()
bom = raw[:3] == b'\xef\xbb\xbf'
text = (raw[3:] if bom else raw).decode('utf-8')

pairs = [
    # 库搜索路径（先换长的，否则会被短的那条先吃掉）
    (r'$(SolutionDir)ext\Ling\x64\$(Configuration)',
     EXT + r'\Ling\x64\$(Configuration)'),
    # 头文件搜索路径：Ling 仓库根（源码里是 #include <include/Ling.h>）
    (r'$(SolutionDir)ext\Ling;$(ProjectDir)',
     EXT + r'\Ling;$(ProjectDir)'),
    # 中间产物全部放到 build 目录，别落到仓库里
    (r'<IntDir>$(SolutionDir)$(Platform)\$(Configuration)Temp\</IntDir>',
     '<IntDir>' + EXT + r'\build\obj\$(Platform)\$(Configuration)\</IntDir>'),
]

for old, new in pairs:
    n = text.count(old)
    assert n > 0, '未匹配到: ' + old
    text = text.replace(old, new)
    print('replaced x%d  %s' % (n, old[:60]))

# 输出目录（默认会落到副本所在目录）
anchor = '  <PropertyGroup Label="UserMacros" />'
assert text.count(anchor) == 1
text = text.replace(anchor, anchor + '\n  <PropertyGroup>\n    <OutDir>'
                    + EXT + r'\build\bin\$(Platform)\$(Configuration)\</OutDir>'
                    + '\n  </PropertyGroup>')

out = (b'\xef\xbb\xbf' if bom else b'') + text.encode('utf-8')
open(dst_path, 'wb').write(out)
print('written:', dst_path, len(out), 'bytes')
