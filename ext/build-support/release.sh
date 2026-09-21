#!/usr/bin/env bash
# 把编好的 exe 发到 GitHub Releases。
#
#   bash ext/build-support/release.sh            # 正式发布
#   bash ext/build-support/release.sh --dry-run  # 只做本地准备，不碰 GitHub
#
# 做的事：
#   1. 要求工作区干净（发布件必须能对应到某个提交）
#   2. 从 exe 的**版本资源**里读版本号（不猜、不解析源码）→ 2.6.0
#   3. 把 exe 复制成  ext/build/release/ScreenCapture_2.6.0.exe
#   4. 从 CHANGELOG.md 抽出该版本的段落当 release 说明
#   5. 打 tag v2.6.0 并推送
#   6. 建 release + 上传那个 exe
#
# 关于 token：走 git 的凭据管理器（git credential fill），不落地任何文件。
# 仓库地址从 git remote 里取，不写死 owner/repo。
export PATH="/usr/bin:/bin:/c/Windows/System32:$PATH"
unset http_proxy https_proxy all_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY

DRY_RUN=0
[ "$1" = "--dry-run" ] && DRY_RUN=1

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
EXE="$ROOT/ext/build/bin/x64/Release/ScreenCapture.build.exe"
REL_DIR="$ROOT/ext/build/release"
CHANGELOG="$ROOT/CHANGELOG.md"

winpath() {
    if command -v cygpath >/dev/null 2>&1; then cygpath -w "$1"
    else printf '%s' "$1" | sed -e 's|^/\([a-zA-Z]\)/|\1:\\|' -e 's|/|\\|g'; fi
}

die() { echo "!! $*" >&2; exit 1; }

# ———— 1. 工作区要干净 ————
if [ -n "$(git -C "$ROOT" status --porcelain)" ]; then
    echo "!! 工作区有未提交的改动，先提交再发（发布件必须对应到一个确定的提交）"
    git -C "$ROOT" status --short
    exit 1
fi

# ———— 2. exe 与版本号 ————
[ -f "$EXE" ] || die "没有找到 $EXE —— 先跑 bash ext/build-support/rebuild_all.sh"
# 版本号取自 exe 的 VERSIONINFO（唯一真源是 Src/Res/Resource.rc），取前三段
VER_FULL="$(powershell -NoProfile -Command \
    "(Get-Item '$(winpath "$EXE")').VersionInfo.FileVersion" 2>/dev/null | tr -d '\r\n')"
[ -n "$VER_FULL" ] || die "读不到 exe 的版本资源"
VER="$(printf '%s' "$VER_FULL" | cut -d. -f1-3)"
TAG="v$VER"
ASSET_NAME="ScreenCapture_${VER}.exe"
echo "版本   : $VER_FULL  →  发布用 $VER"
echo "tag    : $TAG"
echo "发布件 : $ASSET_NAME"

# ———— 3. 复制成带版本号的名字 ————
mkdir -p "$REL_DIR"
ASSET="$REL_DIR/$ASSET_NAME"
cp -f "$EXE" "$ASSET"
echo "已生成 : ${ASSET#$ROOT/}  ($(wc -c < "$ASSET") 字节)"

# ———— 4. release 说明：CHANGELOG 里该版本那一段 ————
NOTES="$(awk -v ver="$VER" '
    $0 ~ "^##[[:space:]]+" ver { on=1; next }
    on && /^##[[:space:]]/ { exit }
    on { print }
' "$CHANGELOG")"
if [ -z "$NOTES" ]; then
    echo "（CHANGELOG.md 里没找到 $VER 那一段，说明留空）"
else
    echo "说明   : 从 CHANGELOG.md 抽到 $(printf '%s' "$NOTES" | wc -l) 行"
fi

if [ "$DRY_RUN" = "1" ]; then
    echo
    echo "---- dry-run：以上都已就绪，没有碰 GitHub ----"
    echo "发布件路径：$ASSET"
    echo "release 说明预览："
    printf '%s\n' "$NOTES" | head -10
    exit 0
fi

# ———— 5. tag ————
if git -C "$ROOT" rev-parse -q --verify "refs/tags/$TAG" >/dev/null; then
    die "tag $TAG 已存在（要重发就先删：git tag -d $TAG && git push origin :refs/tags/$TAG）"
fi
git -C "$ROOT" tag -a "$TAG" -m "$TAG"
# ⚠ git push 的输出走 stderr，不重定向到文件的话会被管道吞掉、看起来像"没生效"
git -C "$ROOT" push origin "refs/tags/$TAG" > "$ROOT/ext/build/logs/push_tag.log" 2>&1
echo "tag 已推送：$(tail -1 "$ROOT/ext/build/logs/push_tag.log")"

# ———— 6. token + owner/repo ————
TOK="$(printf 'protocol=https\nhost=github.com\n\n' | git credential fill 2>/dev/null \
       | sed -n 's/^password=//p')"
[ -n "$TOK" ] || die "从 git 凭据管理器取不到 token"
REMOTE="$(git -C "$ROOT" remote get-url origin)"
SLUG="$(printf '%s' "$REMOTE" | sed -e 's|^git@[^:]*:||' -e 's|^https\?://[^/]*/||' -e 's|\.git$||')"
[ -n "$SLUG" ] || die "解析不出 owner/repo（remote: $REMOTE）"
echo "仓库   : $SLUG"

# ———— 7. 建 release ————
BODY_JSON="$(printf '%s' "$NOTES" | python -c 'import json,sys; print(json.dumps(sys.stdin.read()))')"
RESP="$(curl -sS -X POST \
    -H "Authorization: token $TOK" \
    -H "Accept: application/vnd.github+json" \
    "https://api.github.com/repos/$SLUG/releases" \
    -d "{\"tag_name\":\"$TAG\",\"name\":\"$TAG\",\"body\":$BODY_JSON,\"draft\":false,\"prerelease\":false}")"
REL_ID="$(printf '%s' "$RESP" | sed -n 's/.*"id":[[:space:]]*\([0-9]\{1,\}\).*/\1/p' | head -1)"
[ -n "$REL_ID" ] || die "建 release 失败：$RESP"
echo "release: #$REL_ID 已创建（$TAG）"

# ———— 8. 传 exe ————
# ⚠ 资产上传端点是 uploads.github.com —— 用 api.github.com 会 404
UP="$(curl -sS -X POST \
    -H "Authorization: token $TOK" \
    -H "Content-Type: application/octet-stream" \
    --data-binary @"$ASSET" \
    "https://uploads.github.com/repos/$SLUG/releases/$REL_ID/assets?name=$ASSET_NAME")"
if printf '%s' "$UP" | grep -q '"browser_download_url"'; then
    DL="$(printf '%s' "$UP" | sed -n 's/.*"browser_download_url":[[:space:]]*"\([^"]*\)".*/\1/p' | head -1)"
    echo
    echo "✔ 发布完成"
    echo "  release 页面：https://github.com/$SLUG/releases/tag/$TAG"
    echo "  下载直链    ：$DL"
else
    die "上传资产失败：$UP"
fi
