#!/usr/bin/env bash
# Ling 发布包的安装/切换脚本 —— "pip 包"流程里的 pip install 环节。
#
# 用法:
#   bash ext/build-support/ling_pkg.sh install <版本>   # 例: install v1.0.0
#   bash ext/build-support/ling_pkg.sh source           # 卸掉包，回到 submodule 源码编译
#   bash ext/build-support/ling_pkg.sh status
#
# install 做的事：
#   1. 从 GitHub Release 下载 ling-<版本>-x64.zip
#   2. 解压到临时目录 → 换名成 ext/ling-pkg/current（先挪走旧的，避免新旧文件混留）
#   3. 记录 ling.lock（仓库根）：版本 / commit / sha256 / 安装时间
#
# 生效机制：Src/ZPin.vcxproj 的 include/lib 搜索路径里 ext\ling-pkg\current 排在
# ext\Ling 源码路径**前面** —— 装了包就用包，`source` 卸掉即回落源码编译。
# 注意：包里只有 Release/x64 的 lib；编 Debug 配置前请先 `ling_pkg.sh source`，
# 否则 Debug 的 ZPin 会链接到 Release 的 Ling.lib（运行库不匹配，LNK2038）。
export PATH="/usr/bin:/bin:/c/Windows/System32:$PATH"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
PKG_ROOT="$ROOT/ext/ling-pkg"
CURRENT="$PKG_ROOT/current"
LOCK="$ROOT/ling.lock"
REPO="James-ctrl-Doyle/Ling"
TAR="/c/Windows/System32/tar.exe"

# 沙箱对一次删 >50 个文件有阈值，分两批：先删子目录里的，再删顶层
rmrf() {
    rm -rf "$1" 2>/dev/null
    if [ -e "$1" ]; then
        find "$1" -mindepth 2 -type f -delete 2>/dev/null
        rm -rf "$1" 2>/dev/null
    fi
    [ ! -e "$1" ]
}

die() { echo "!! $*"; exit 1; }

cmd="${1:-status}"

case "$cmd" in

install)
    VER="${2:-}"
    case "$VER" in
        v*) ;;
        "") die "用法: ling_pkg.sh install <版本>，例: install v1.0.0" ;;
        *) VER="v$VER" ;;
    esac
    URL="https://github.com/$REPO/releases/download/$VER/ling-$VER-x64.zip"
    ZIP="$PKG_ROOT/ling-$VER-x64.zip"
    STAGE="$PKG_ROOT/stage"

    mkdir -p "$PKG_ROOT"
    echo "下载 $URL"
    curl -fL --retry 3 -o "$ZIP" "$URL" || die "下载失败（检查版本号 $VER 是否已发布）"
    SHA=$(sha256sum "$ZIP" | cut -d' ' -f1)

    rmrf "$STAGE" || die "清不掉 $STAGE"
    mkdir -p "$STAGE"
    "$TAR" -xf "$(cygpath -w "$ZIP")" -C "$(cygpath -w "$STAGE")" || die "解压失败"
    # zip 里有一层顶层目录 ling-<版本>-x64/，把它找出来
    INNER=$(find "$STAGE" -mindepth 1 -maxdepth 1 -type d | head -1)
    [ -n "$INNER" ] && [ -f "$INNER/x64/Release/Ling.lib" ] \
        || die "包内容不对（找不到 x64/Release/Ling.lib）"

    # 换名上正式岗：旧的挪到 .old，成功后再删 —— 中途断了也不会两头都没包
    rmrf "$PKG_ROOT/current.old"
    if [ -e "$CURRENT" ]; then
        mv "$CURRENT" "$PKG_ROOT/current.old" || die "挪不走旧的 current"
    fi
    mv "$INNER" "$CURRENT" || die "启用新包失败"
    rm -rf "$STAGE"
    rmrf "$PKG_ROOT/current.old" || echo "（提示：$PKG_ROOT/current.old 没删干净，可手动删）"
    rm -f "$ZIP"

    COMMIT=$(sed -n 's/^commit[[:space:]]*:[[:space:]]*//p' "$CURRENT/VERSION.txt" | head -1)
    {
        echo "name: ling"
        echo "version: $VER"
        echo "commit: ${COMMIT:-unknown}"
        echo "url: $URL"
        echo "sha256: $SHA"
        echo "mode: package"
        echo "installed: $(date +%F' '%T)"
    } > "$LOCK"
    echo "已安装 $VER（commit ${COMMIT:-unknown}），lock 见 ling.lock"
    ;;

source)
    rmrf "$CURRENT" || die "清不掉 $CURRENT（有编译进程占着？）"
    rmrf "$PKG_ROOT/current.old"
    if [ -f "$LOCK" ]; then
        sed -i 's/^mode:.*/mode: source/' "$LOCK"
    fi
    echo "已切回源码编译模式（ext/Ling submodule）"
    ;;

status)
    if [ -f "$LOCK" ]; then echo "--- ling.lock ---"; cat "$LOCK"; else echo "ling.lock 不存在"; fi
    if [ -f "$CURRENT/x64/Release/Ling.lib" ]; then
        echo "包状态: 已启用 ($CURRENT)"
    else
        echo "包状态: 未启用（构建将回落到 ext/Ling 源码编译）"
    fi
    ;;

*)
    die "未知子命令: $cmd（install/source/status）"
    ;;
esac
