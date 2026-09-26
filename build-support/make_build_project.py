r"""生成一份 ZPin 的工程副本，用于本机编译验证。

为什么要副本：原 `Src/ZPin.vcxproj` 里的 IntDir / OutDir 会落到仓库里，
而我们要把中间产物和 exe 都放到工作区的 `build/` 下，不污染仓库。所以不改原文件，
只生成一份同目录的副本（`ZPin.build.vcxproj`），把产物目录指过去。

Ling 的引用与 ZDock 同一套（build-support/build.sh 的优先级）：
  1) 环境变量 LING_ROOT
  2) ../Ling/dist/ling-v1.3.1-x64     —— Ling 仓库打出来的发布包（含 include/ + x64/Release）
  3) ../Ling                           —— Ling 源码树（布局与发布包一致）
`Src/ZPin.vcxproj` 里写的是 `__LING_ROOT__` 占位符，这里解析成绝对路径烘进副本
（MSBuild 直接编 .vcxproj 时不经过 .slnx，`$(SolutionDir)` 是空的，所以必须绝对路径）。
"""
import os

# 路径全部从本文件位置推导，不写死任何机器上的绝对路径。
# 本文件在 <仓库根>/build-support/ 下，往上一级就是仓库根。
# ⚠ 它原来在 <仓库根>/_tools/（一级）、后来 build-support/（两级），
#    2026-09-26 目录重组回到顶层 build-support/（一级）。数层数要照着实际目录数。
ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                     '..'))
SRC = os.path.join(ROOT, 'Src')
BUILD = os.path.join(ROOT, 'build')


def resolve_ling_root():
    """与 ZDock 的 build.sh 同一套优先级：env → 发布包 → 源码树。"""
    env = os.environ.get('LING_ROOT')
    if env:
        return env
    dist = os.path.normpath(os.path.join(ROOT, '..', 'Ling',
                                         'dist', 'ling-v1.3.1-x64'))
    if os.path.isdir(os.path.join(dist, 'include')):
        return dist
    return os.path.normpath(os.path.join(ROOT, '..', 'Ling'))


LING = resolve_ling_root()

src_path = os.path.join(SRC, 'ZPin.vcxproj')
dst_path = os.path.join(SRC, 'ZPin.build.vcxproj')

raw = open(src_path, 'rb').read()
bom = raw[:3] == b'\xef\xbb\xbf'
text = (raw[3:] if bom else raw).decode('utf-8')

pairs = [
    # Ling 引用：vcxproj 里只写 __LING_ROOT__ 占位符，这里烘成解析出的绝对路径。
    # 头文件搜索路径 = Ling 仓库根（源码里是 #include <include/Ling.h>）；
    # 库搜索路径 = 其 x64/$(Configuration)（发布包与源码树的布局一致）。
    (r'__LING_ROOT__;$(ProjectDir)',
     LING + ';$(ProjectDir)'),
    (r'__LING_ROOT__\x64\$(Configuration)',
     LING + r'\x64\$(Configuration)'),
    # 中间产物全部放到 build 目录，别落到仓库里
    (r'<IntDir>$(SolutionDir)$(Platform)\$(Configuration)Temp\</IntDir>',
     '<IntDir>' + BUILD + r'\obj\$(Platform)\$(Configuration)\</IntDir>'),
]

for old, new in pairs:
    n = text.count(old)
    if n == 0:
        # 兼容对允许没有；IntDir 那条永远必须在
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
                    + BUILD + r'\bin\$(Platform)\$(Configuration)\</OutDir>'
                    + '\n  </PropertyGroup>')

out = (b'\xef\xbb\xbf' if bom else b'') + text.encode('utf-8')
open(dst_path, 'wb').write(out)
print('written:', dst_path, len(out), 'bytes')
print('LING   :', LING)
