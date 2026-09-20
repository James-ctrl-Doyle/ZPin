#!/usr/bin/env bash
# 编 probe_play.exe（Media Foundation 探针）。
# 用途：把录屏产出的 mp4 逐帧解出来存成 raw，排查「文件到底能不能解、画面对不对」。
# 属于开发工具，不进产品构建流程。
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$SCRIPT_DIR/_msvc_env.sh"

OUT_DIR="$SCRIPT_DIR/bench"
mkdir -p "$OUT_DIR"
OUT="$(winpath "$OUT_DIR")"
SRC="$(winpath "$SCRIPT_DIR/probe_play.cpp")"

"$CL" -nologo -std:c++20 -EHsc -O2 -utf-8 "$SRC" -Fe:"$OUT\\probe_play.exe" \
      -link mfplat.lib mfreadwrite.lib mfuuid.lib ole32.lib
