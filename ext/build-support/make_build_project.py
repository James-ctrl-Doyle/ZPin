r"""生成一份 ZPin 的工程副本，用于本机编译验证。

为什么要副本：原 `Src/ZPin.vcxproj` 里的 IntDir / OutDir 会落到仓库里，
而我们要把中间产物和 exe 都放到工作区的 `ext/build/` 下，不污染仓库。所以不改原文件，
只生成一份同目录的副本（`ZPin.build.vcxproj`），把产物目录指过去。

Ling 的路径**不用替换**：原工程写的是 `$(SolutionDir)ext\Ling`，而 Ling 已经内置在仓库的
`ext/Ling`，用 `ZPin.slnx` 打开就能直接编（见 Doc/Build.md）。
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
#    FileNotFoundError 找不到 Src/ZPin.vcxproj。数层数要照着实际目录数。
ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                     '..', '..'))
EXT = os.path.join(ROOT, 'ext')
SRC = os.path.join(ROOT, 'Src')

src_path = os.path.join(SRC, 'ZPin.vcxproj')
dst_path = os.path.join(SRC, 'ZPin.build.vcxproj')

raw = open(src_path, 'rb').read()
bom = raw[:3] == b'\xef\xbb\xbf'
text = (raw[3:] if bom else raw).decode('utf-8')

pairs = [
    # 0) Ling 发布包路径（2026-09-26 起，配合 ext/build-support/ling_pkg.sh）。
    #    装了包（ext/ling-pkg/current 存在）就优先用它；没装时这两个目录不存在，
    #    MSBuild 对不存在的搜索路径只是跳过，回落到下面的源码路径。
    #    ⚠ 必须排在下面两条之前 —— 组合串里含有旧串，被旧串先替换就匹配不到了。
    (r'$(SolutionDir)ext\ling-pkg\current\x64\$(Configuration);$(SolutionDir)ext\Ling\x64\$(Configuration)',
     EXT + r'\ling-pkg\current\x64\$(Configuration);' + EXT + r'\Ling\x64\$(Configuration)'),
    (r'$(SolutionDir)ext\ling-pkg\current;$(SolutionDir)ext\Ling;$(ProjectDir)',
     EXT + r'\ling-pkg\current;' + EXT + r'\Ling;$(ProjectDir)'),
    # 1) 兼容：工程还没接 ling-pkg 时（或将来回退）只剩这两条旧串
    # 库搜索路径
    (r'$(SolutionDir)ext\Ling\x64\$(Configuration)',
     EXT + r'\Ling\x64\$(Configuration)'),
    # 头文件搜索路径：Ling 仓库根（源码里是 #include <include/Ling.h>）
    (r'$(SolutionDir)ext\Ling;$(ProjectDir)',
     EXT + r'\Ling;$(ProjectDir)'),
    # 2) 中间产物全部放到 build 目录，别落到仓库里
    (r'<IntDir>$(SolutionDir)$(Platform)\$(Configuration)Temp\</IntDir>',
     '<IntDir>' + EXT + r'\build\obj\$(Platform)\$(Configuration)\</IntDir>'),
]

for old, new in pairs:
    n = text.count(old)
    if n == 0:
        # 兼容对允许没有（新工程里已被组合对吃掉）；IntDir 那条永远必须在
        if 'IntDir' not in old:
            print('skip (0 hits)  %s' % old[:60])
            continue
        raise SystemExit('未匹配到: ' + old)
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
