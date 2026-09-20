#!/usr/bin/env bash
# 编滚动匹配算法的基准程序（bench_match.cpp）。
# 用途：把「逐行剪枝 + 用上一次滚动量当剪枝种子」这一版和原来的完整遍历版放一起跑，
# 验证结果严格一致、并量出加速比。属于开发工具，不进产品构建流程。
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$SCRIPT_DIR/_msvc_env.sh"

OUT_DIR="$SCRIPT_DIR/bench"
mkdir -p "$OUT_DIR"
OUT="$(winpath "$OUT_DIR")"
SRC="$(winpath "$SCRIPT_DIR/bench_match.cpp")"

"$CL" -nologo -std:c++20 -EHsc -O2 -utf-8 "$SRC" -Fe:"$OUT\\bench_match.exe"
