#!/usr/bin/env bash
# 完整重编（Rebuild）：yoga.lib / Ling.lib 从源码编一遍，ZPin 全部文件重编。
# 日志落在 ext/build/logs/，摘要写到 ext/build/summary.txt。
# 必须在沙箱外执行（要真实调用编译器）。
#
# 路径全部从本脚本自身位置推导（脚本位于 <仓库根>/ext/build-support/），换机器不用改。
# 可覆盖的环境变量：
#   SC_ROOT  项目根目录（默认 = 本脚本的上上级）
#   MSBUILD  MSBuild.exe 路径（默认自动找 VS）
export PATH="/usr/bin:/bin:/c/Windows/System32:$PATH"

# 本机环境里 HTTP_PROXY 和 http_proxy 同时存在（大小写两份）。MSBuild 用 .NET 的
# ProcessStartInfo.EnvironmentVariables（大小写不敏感）构造子进程环境，撞键就抛
# MSB6001 "CL.exe 的命令行开关无效"。编译不需要代理，把变量清掉即可。
unset http_proxy https_proxy all_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="${SC_ROOT:-$(cd "$SCRIPT_DIR/../.." && pwd)}"
EXT="$ROOT/ext"
LOGS="$EXT/build/logs"
SUMMARY="$EXT/build/summary.txt"

# Ling 是** submodule **（2026-09-25 起不再内置源码）。刚 clone 完 ZPin 时 ext/Ling 是空目录，
# 直接编 yoga/Ling 会以"找不到 vcxproj"失败。这里自动补上 —— 已经初始化过时这条是空操作。
if [ ! -f "$EXT/Ling/Ling.vcxproj" ]; then
    echo "Ling 源码不在（submodule 未初始化）→ git submodule update --init"
    (cd "$ROOT" && git submodule update --init --recursive) || {
        echo "!! submodule 初始化失败，构建中止（检查网络与 .gitmodules）"
        exit 1
    }
fi

mkdir -p "$LOGS"
: > "$SUMMARY"

# POSIX 路径 -> Windows 路径（MSBuild 只认后者）。没 cygpath 就手工转换兜底
winpath() {
    if command -v cygpath >/dev/null 2>&1; then
        cygpath -w "$1"
    else
        printf '%s' "$1" | sed -e 's|^/\([a-zA-Z]\)/|\1:\\|' -e 's|/|\\|g'
    fi
}

# MSBuild：优先用 $MSBUILD，否则用 vswhere 找最新 VS，最后退回常见安装路径
find_msbuild() {
    if [ -n "${MSBUILD:-}" ]; then printf '%s' "$MSBUILD"; return; fi
    local vswhere='/c/Program Files (x86)/Microsoft Visual Studio/Installer/vswhere.exe'
    if [ -x "$vswhere" ]; then
        local p
        p="$("$vswhere" -latest -requires Microsoft.Component.MSBuild \
             -find 'MSBuild/**/Bin/MSBuild.exe' 2>/dev/null | head -1)"
        if [ -n "$p" ]; then printf '%s' "$(winpath "$p")"; return; fi
    fi
    printf '%s' 'C:\Program Files\Microsoft Visual Studio\18\Community\MSBuild\Current\Bin\MSBuild.exe'
}
MSB="$(find_msbuild)"

LING_DIR="$(winpath "$EXT/Ling")\\"
LING_PROJ="${LING_DIR}Ling.vcxproj"
YOGA_PROJ="${LING_DIR}yoga\\yoga.vcxproj"
SC_PROJ="$(winpath "$ROOT/Src/ZPin.build.vcxproj")"

log() { echo "$@" | tee -a "$SUMMARY"; }
log "MSBuild : $MSB"
log "项目根  : $ROOT"
log ""

# 0) 生成构建用的工程副本（Src/ZPin.build.vcxproj）。
#    为什么需要副本：MSBuild 直接编 .vcxproj（不经过 .slnx）时 $(SolutionDir) 是空的，
#    `$(SolutionDir)ext\Ling` 解析不出来就找不到 include/Ling.h；副本里把它换成绝对路径，
#    顺便把 IntDir/OutDir 引到 ext/build/ 下，不污染仓库。
#    ⚠ 副本**不在仓库里**（已被 .gitignore）——刚 clone 下来肯定没有它，
#      所以这里必须每次重新生成；否则新建的仓库第一次就编不过（C1083）。
#      重新生成也顺带解决"挪过目录 / 改过路径之后副本里还是旧路径"的问题。
log "########## 0/3  生成构建工程副本 ##########"
PY=""
for c in python python3 py; do
    if command -v "$c" >/dev/null 2>&1; then PY="$c"; break; fi
done
if [ -z "$PY" ]; then
    log "!! 找不到 python（生成构建工程副本需要它）"
    log "   替代做法：用 Visual Studio 打开 $ROOT/ZPin.slnx 直接编译"
    exit 1
fi
# 生成脚本与本脚本同目录（ext/build-support/）——2026-09-22 从 _tools/ 搬过来的
if ! "$PY" "$(winpath "$SCRIPT_DIR/make_build_project.py")" > "$LOGS/make_project.log" 2>&1; then
    log "!! 生成 $ROOT/Src/ZPin.build.vcxproj 失败，日志见 $LOGS/make_project.log"
    cat "$LOGS/make_project.log" >> "$SUMMARY"
    exit 1
fi
log "ok  (python: $PY)"
log ""

# 产物 exe 正在运行会挡住链接（LNK1104 无法打开文件）；另外用户自己很可能还开着一份
# 从 ext/build/release/ 起的那份 —— 两份实例抢 F1 热键，回归测试会整片失败
# （表现为"一半用例过、一半挂"）。所以两种名字都先结束掉。这是开发用的构建脚本，反复手杀太烦。
# taskkill 本机不可用，用 PowerShell 的 Stop-Process。
if ps -W 2>/dev/null | grep -qi "ZPin"; then
    log "--- 检测到正在运行的 ZPin 实例，先结束它 ---"
    powershell -NoProfile -Command \
        "Get-Process -Name 'ZPin.build','ZPin' -ErrorAction SilentlyContinue | Stop-Process -Force -Confirm:\$false" \
        >/dev/null 2>&1
    sleep 1
fi

# Ling 发布包优先（ext/build-support/ling_pkg.sh 装/卸，版本记录在 ling.lock）。
# 装了包就跳过 yoga/Ling 的源码编译 —— lib 直接连 ext/ling-pkg/current 里的；
# vcxproj 的搜索路径也是包优先（ext\ling-pkg\current 在 ext\Ling 前面），两边一致。
# 强制从源码编：LING_FROM_SOURCE=1 bash rebuild_all.sh，或 bash ling_pkg.sh source
if [ -z "${LING_FROM_SOURCE:-}" ] && [ -f "$EXT/ling-pkg/current/x64/Release/Ling.lib" ]; then
    log "########## Ling 走发布包（ext/ling-pkg/current），跳过 yoga/Ling 编译 ##########"
    log "（强制源码编译：LING_FROM_SOURCE=1，或 bash ext/build-support/ling_pkg.sh source）"
    log ""
else

log "########## 1/3  yoga.lib (Rebuild, Release x64) ##########"
"$MSB" "$YOGA_PROJ" -p:Configuration=Release -p:Platform=x64 -p:SolutionDir="$LING_DIR" \
    -restore:false -t:Rebuild -m -v:m > "$LOGS/yoga.log" 2>&1
log "yoga exit=$?"
grep -E "error [A-Z]+[0-9]+|warning [A-Z]+[0-9]+" "$LOGS/yoga.log" | head -5 | tee -a "$SUMMARY"

log ""
log "########## 2/3  Ling.lib (Rebuild, Release x64) ##########"
"$MSB" "$LING_PROJ" -p:Configuration=Release -p:Platform=x64 -p:SolutionDir="$LING_DIR" \
    -restore:false -t:Rebuild -m -v:m > "$LOGS/ling.log" 2>&1
log "Ling exit=$?"
grep -cE "error [A-Z]+[0-9]+" "$LOGS/ling.log" | tee -a "$SUMMARY"
ls -l "$EXT/Ling/x64/Release/" 2>/dev/null | tee -a "$SUMMARY"

fi

log ""
log "########## 3/3  ZPin (Rebuild, Release x64) ##########"
"$MSB" "$SC_PROJ" -p:Configuration=Release -p:Platform=x64 -t:Rebuild -m -v:m \
    > "$LOGS/screencapture.log" 2>&1
log "ZPin exit=$?"

log ""
log "--- 错误/警告统计 ---"
grep -oE "(error|warning) [A-Z]+[0-9]+" "$LOGS/screencapture.log" | sort | uniq -c | sort -rn | tee -a "$SUMMARY"

log ""
log "--- 全部错误 ---"
grep -E "error [A-Z]+[0-9]+" "$LOGS/screencapture.log" | tee -a "$SUMMARY"

log ""
log "--- 编译过的文件数 ---"
grep -cE "\.cpp$|\.c$" "$LOGS/screencapture.log" | tee -a "$SUMMARY"

log ""
log "--- 产物 ---"
ls -l "$EXT/build/bin/x64/Release/" 2>/dev/null | tee -a "$SUMMARY"

# ---- 顺手备一份带版本号的发布件 ----
# 内部产物名保持 ZPin.build.exe 不变：三十来个测试脚本都按这个名字找它，
# config.json / temp 也在那个目录里，改名会把整套回归打挂。
# 对外发布用的是另一份 ZPin_<版本>.exe，版本号从 exe 自己的 VERSIONINFO 读
# （唯一真源是 Src/Res/Resource.rc，不另外维护一处版本号）。
# 真要发到 GitHub Releases 走 release.sh，它直接拿这个文件。
REL_EXE="$EXT/build/bin/x64/Release/ZPin.build.exe"
if [ -f "$REL_EXE" ]; then
    VER_FULL="$(powershell -NoProfile -Command \
        "(Get-Item '$(winpath "$REL_EXE")').VersionInfo.FileVersion" 2>/dev/null | tr -d '\r\n')"
    VER="$(printf '%s' "$VER_FULL" | cut -d. -f1-3)"
    if [ -n "$VER" ]; then
        REL_DIR="$EXT/build/release"
        mkdir -p "$REL_DIR"
        cp -f "$REL_EXE" "$REL_DIR/ZPin_$VER.exe"
        log ""
        log "--- 发布件（v$VER）---"
        ls -l "$REL_DIR/ZPin_$VER.exe" | tee -a "$SUMMARY"
        log "发到 GitHub Releases：bash ext/build-support/release.sh"
    else
        log "!! 读不到 exe 的版本资源，跳过发布件"
    fi
fi
