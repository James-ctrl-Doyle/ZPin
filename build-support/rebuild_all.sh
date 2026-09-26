#!/usr/bin/env bash
# 完整重编（Rebuild）：ZPin 全部文件重编；Ling 优先走发布包，没有包才从源码编。
# 日志落在 build/logs/，摘要写到 build/summary.txt。
# 必须在沙箱外执行（要真实调用编译器）。
#
# 路径全部从本脚本自身位置推导（脚本位于 <仓库根>/build-support/），换机器不用改。
# 可覆盖的环境变量：
#   SC_ROOT    项目根目录（默认 = 本脚本的上一级）
#   MSBUILD    MSBuild.exe 路径（默认自动找 VS）
#   LING_ROOT  Ling 库位置（默认按 ZDock 同款优先级解析，见下）
#   LING_FROM_SOURCE=1  强制从 ../Ling 源码树编译（忽略发布包）
export PATH="/usr/bin:/bin:/c/Windows/System32:$PATH"

# 本机环境里 HTTP_PROXY 和 http_proxy 同时存在（大小写两份）。MSBuild 用 .NET 的
# ProcessStartInfo.EnvironmentVariables（大小写不敏感）构造子进程环境，撞键就抛
# MSB6001 "CL.exe 的命令行开关无效"。编译不需要代理，把变量清掉即可。
unset http_proxy https_proxy all_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="${SC_ROOT:-$(cd "$SCRIPT_DIR/.." && pwd)}"
BUILD="$ROOT/build"
LOGS="$BUILD/logs"
SUMMARY="$BUILD/summary.txt"

mkdir -p "$LOGS"
: > "$SUMMARY"

# ---- Ling 引用（与 ZDock 的 build.sh 同一套优先级）----
#   1) $LING_ROOT 环境变量
#   2) ../Ling/dist/ling-v1.3.1-x64  —— Ling 仓库的发布包（include/ + x64/Release）
#   3) ../Ling                        —— Ling 源码树（布局与发布包一致）
# 解析到发布包 → 直接连它的 lib，跳过 yoga/Ling 编译；解析到源码树 → 现场编一遍。
# LING_FROM_SOURCE=1 可强制走源码树。判断依据：包里有没有 x64/Release/Ling.lib。
resolve_ling_root() {
    if [ -n "${LING_ROOT:-}" ]; then printf '%s' "$LING_ROOT"; return; fi
    local dist="$ROOT/../Ling/dist/ling-v1.3.1-x64"
    if [ -f "$dist/x64/Release/Ling.lib" ]; then printf '%s' "$dist"; return; fi
    printf '%s' "$ROOT/../Ling"
}
LING_ROOT="$(resolve_ling_root)"
LING_HAS_PKG=0
if [ -z "${LING_FROM_SOURCE:-}" ] && [ -f "$LING_ROOT/x64/Release/Ling.lib" ]; then
    LING_HAS_PKG=1
fi

# 本脚本要用 python 的地方有两处：杀旧实例、生成构建工程副本。
PY=""
for c in python python3 py; do
    if command -v "$c" >/dev/null 2>&1; then PY="$c"; break; fi
done

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

SC_PROJ="$(winpath "$ROOT/Src/ZPin.build.vcxproj")"

log() { echo "$@" | tee -a "$SUMMARY"; }
log "MSBuild : $MSB"
log "项目根  : $ROOT"
log "Ling    : $LING_ROOT$([ "$LING_HAS_PKG" = 1 ] && echo '（发布包）' || echo '（源码树）')"
log ""

# 0) 生成构建用的工程副本（Src/ZPin.build.vcxproj）。
#    为什么需要副本：MSBuild 直接编 .vcxproj（不经过 .slnx）时 $(SolutionDir) 是空的，
#    Ling 的引用（__LING_ROOT__ 占位符）解析不出来；副本里把它烘成绝对路径，
#    顺便把 IntDir/OutDir 引到 build/ 下，不污染仓库。
#    ⚠ 副本**不在仓库里**（已被 .gitignore）——刚 clone 下来肯定没有它，
#      所以这里必须每次重新生成；否则新建的仓库第一次就编不过（C1083）。
#      重新生成也顺带解决"挪过目录 / 改过路径之后副本里还是旧路径"的问题。
log "########## 0/3  生成构建工程副本 ##########"
if [ -z "$PY" ]; then
    log "!! 找不到 python（生成构建工程副本需要它）"
    log "   替代做法：用 Visual Studio 打开 $ROOT/ZPin.slnx 直接编译"
    exit 1
fi
# 生成脚本与本脚本同目录（build-support/）
if ! "$PY" "$(winpath "$SCRIPT_DIR/make_build_project.py")" > "$LOGS/make_project.log" 2>&1; then
    log "!! 生成 $ROOT/Src/ZPin.build.vcxproj 失败，日志见 $LOGS/make_project.log"
    cat "$LOGS/make_project.log" >> "$SUMMARY"
    exit 1
fi
log "ok  (python: $PY)"
log ""

# 产物 exe 正在运行会挡住链接（LNK1104 无法打开文件）；另外用户自己很可能还开着一份
# 从 build/release/ 起的那份 —— 两份实例抢 F1 热键，回归测试会整片失败。
# ⚠ 匹配必须用前缀：release 发布件叫 ZPin_<版本>.exe，进程名 "ZPin_2.6.0" 按精确名
#   'ZPin' 是杀不到的（2026-09-26 实际踩到）。
# ⚠ 杀进程走 python（_cfg_guard.kill_running_instances，Toolhelp 快照）而不是
#   PowerShell：沙箱里 bash 调 powershell 会被安全策略整个拦掉，脚本直接中断 ——
#   2026-09-26 实测过；测试脚本启动时也走同一个函数杀，两边行为一致。
if [ -n "$PY" ]; then
    log "检查并结束正在运行的 ZPin 实例（含 release 版 ZPin_*.exe）"
    "$PY" -c "import sys; sys.path.insert(0, r'$(winpath "$SCRIPT_DIR")'); import _cfg_guard; _cfg_guard.kill_running_instances()" | tee -a "$SUMMARY"
else
    log "!! 找不到 python，跳过杀旧实例（有实例在跑时构建/测试会互相干扰）"
fi

if [ "$LING_HAS_PKG" = 1 ]; then
    log "########## Ling 走发布包，跳过 yoga/Ling 编译 ##########"
    log "（强制源码编译：LING_FROM_SOURCE=1 bash rebuild_all.sh）"
    log ""
else
    LING_DIR="$(winpath "$LING_ROOT")\\"
    log "########## 1/3  yoga.lib (Rebuild, Release x64) ##########"
    "$MSB" "${LING_DIR}yoga\\yoga.vcxproj" -p:Configuration=Release -p:Platform=x64 \
        -p:SolutionDir="$LING_DIR" -restore:false -t:Rebuild -m -v:m > "$LOGS/yoga.log" 2>&1
    log "yoga exit=$?"
    grep -E "error [A-Z]+[0-9]+|warning [A-Z]+[0-9]+" "$LOGS/yoga.log" | head -5 | tee -a "$SUMMARY"

    log ""
    log "########## 2/3  Ling.lib (Rebuild, Release x64) ##########"
    "$MSB" "${LING_DIR}Ling.vcxproj" -p:Configuration=Release -p:Platform=x64 \
        -p:SolutionDir="$LING_DIR" -restore:false -t:Rebuild -m -v:m > "$LOGS/ling.log" 2>&1
    log "Ling exit=$?"
    grep -cE "error [A-Z]+[0-9]+" "$LOGS/ling.log" | tee -a "$SUMMARY"
    ls -l "$LING_ROOT/x64/Release/" 2>/dev/null | tee -a "$SUMMARY"
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
ls -l "$BUILD/bin/x64/Release/" 2>/dev/null | tee -a "$SUMMARY"

# ---- 顺手备一份带版本号的发布件 ----
# 内部产物名保持 ZPin.build.exe 不变：三十来个测试脚本都按这个名字找它，
# config.json / temp 也在那个目录里，改名会把整套回归打挂。
# 对外发布用的是另一份 ZPin_<版本>.exe，版本号从 exe 自己的 VERSIONINFO 读
# （唯一真源是 Src/Res/Resource.rc，不另外维护一处版本号）。
# 真要发到 GitHub Releases 走 release.sh，它直接拿这个文件。
REL_EXE="$BUILD/bin/x64/Release/ZPin.build.exe"
if [ -f "$REL_EXE" ]; then
    VER_FULL="$(powershell -NoProfile -Command \
        "(Get-Item '$(winpath "$REL_EXE")').VersionInfo.FileVersion" 2>/dev/null | tr -d '\r\n')"
    VER="$(printf '%s' "$VER_FULL" | cut -d. -f1-3)"
    if [ -n "$VER" ]; then
        REL_DIR="$BUILD/release"
        mkdir -p "$REL_DIR"
        cp -f "$REL_EXE" "$REL_DIR/ZPin_$VER.exe"
        log ""
        log "--- 发布件（v$VER）---"
        ls -l "$REL_DIR/ZPin_$VER.exe" | tee -a "$SUMMARY"
        log "发到 GitHub Releases：bash build-support/release.sh"
    else
        log "!! 读不到 exe 的版本资源，跳过发布件"
    fi
fi
