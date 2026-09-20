#!/usr/bin/env bash
# 完整重编（Rebuild）：yoga.lib / Ling.lib 从源码编一遍，ScreenCapture 全部文件重编。
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
SC_PROJ="$(winpath "$ROOT/Src/ScreenCapture.build.vcxproj")"

log() { echo "$@" | tee -a "$SUMMARY"; }
log "MSBuild : $MSB"
log "项目根  : $ROOT"
log ""

# 0) 生成构建用的工程副本（Src/ScreenCapture.build.vcxproj）。
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
    log "   替代做法：用 Visual Studio 打开 $ROOT/ScreenCapture.slnx 直接编译"
    exit 1
fi
if ! "$PY" "$(winpath "$ROOT/_tools/make_build_project.py")" > "$LOGS/make_project.log" 2>&1; then
    log "!! 生成 $ROOT/Src/ScreenCapture.build.vcxproj 失败，日志见 $LOGS/make_project.log"
    cat "$LOGS/make_project.log" >> "$SUMMARY"
    exit 1
fi
log "ok  (python: $PY)"
log ""

# 产物 exe 正在运行会挡住链接（LNK1104 无法打开文件）。先结束掉 —— 这是开发用的构建脚本，
# 反复手杀太烦。taskkill 本机不可用，用 PowerShell 的 Stop-Process（要 WINPID，ps -W 第 4 列）。
if ps -W 2>/dev/null | grep -qi "ScreenCapture.build.exe"; then
    log "--- 检测到正在运行的 ScreenCapture.build.exe，先结束它 ---"
    powershell -NoProfile -Command \
        "Get-Process -Name 'ScreenCapture.build' -ErrorAction SilentlyContinue | Stop-Process -Force -Confirm:\$false" \
        >/dev/null 2>&1
    sleep 1
fi

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

log ""
log "########## 3/3  ScreenCapture (Rebuild, Release x64) ##########"
"$MSB" "$SC_PROJ" -p:Configuration=Release -p:Platform=x64 -t:Rebuild -m -v:m \
    > "$LOGS/screencapture.log" 2>&1
log "ScreenCapture exit=$?"

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
