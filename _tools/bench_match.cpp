// 长图滚动匹配算法：验证"提前退出"版与"完整遍历"版结果完全一致，并测加速比。
// 用真实规模的数据：2560 宽的窗口、800 行的搜索区、100 行的比较条带。
#include <cstdio>
#include <cstdlib>
#include <cfloat>
#include <cstring>
#include <cmath>
#include <chrono>
#include <vector>

// ———— 原版：完整遍历，无提前退出 ————
int findMostSimilarY_old(const unsigned char* gray1, int gray1H, const unsigned char* gray2, int gray2H, int width)
{
    int searchH = gray1H - gray2H + 1;
    if (searchH <= 0) return 0;
    double minAvgError = DBL_MAX;
    int bestY = 0;
    for (int y = 0; y < searchH; y++) {
        double error = 0.0;
        for (int row = 0; row < gray2H; row++) {
            const unsigned char* row1 = gray1 + (y + row) * width;
            const unsigned char* row2 = gray2 + row * width;
            for (int x = 0; x < width; x++) {
                int diff = (int)row1[x] - (int)row2[x];
                error += diff * diff;
            }
        }
        double avgError = error / gray2H;
        if (avgError < minAvgError) { minAvgError = avgError; bestY = y; }
    }
    return bestY;
}

// ———— 新版：用上一次滚动量当种子 + 逐行剪枝 ————
int findMostSimilarY_new(const unsigned char* g1, int g1H, const unsigned char* g2, int g2H, int width, int hint)
{
    int searchH = g1H - g2H + 1;
    if (searchH <= 0) return 0;
    auto evalAt = [&](int y, double pruneLimit) -> double {
        double error = 0.0;
        const unsigned char* row1 = g1 + (size_t)y * width;
        for (int row = 0; row < g2H; row++, row1 += width) {
            const unsigned char* row2 = g2 + (size_t)row * width;
            for (int x = 0; x < width; x++) {
                int diff = (int)row1[x] - (int)row2[x];
                error += diff * diff;
            }
            if (pruneLimit > 0 && error > pruneLimit) return DBL_MAX;
        }
        return error / g2H;
    };
    double seed = DBL_MAX;
    const int guesses[] = { 0, hint, hint > 0 ? hint * 2 : -1 };
    for (int g : guesses) {
        if (g < 0 || g >= searchH) continue;
        double e = evalAt(g, 0.0);
        if (e < seed) seed = e;
    }
    double minAvgError = DBL_MAX;
    int bestY = 0;
    for (int y = 0; y < searchH; y++) {
        const double ref = minAvgError < seed ? minAvgError : seed;
        double avgError = evalAt(y, ref * g2H);
        if (avgError < minAvgError) { minAvgError = avgError; bestY = y; }
    }
    return bestY;
}

static unsigned rngState = 12345u;
static unsigned rnd() { rngState = rngState * 1664525u + 1013904223u; return rngState >> 8; }

int main()
{
    const int width = 2560, gray1H = 800, gray2H = 100;
    std::vector<unsigned char> g1((size_t)width * gray1H);

    int fail = 0;
    double totalOld = 0, totalNew = 0;
    int cases[] = { 0, 1, 3, 17, 40, 137, 400, 690 };

    for (int ci = 0; ci < (int)(sizeof(cases) / sizeof(cases[0])); ci++) {
        const int s = cases[ci];
        // 造"页面"内容：带纵向渐变背景 + 随机纹理（模拟真实网页/文档）
        for (int y = 0; y < gray1H; y++) {
            for (int x = 0; x < width; x++) {
                int v = (y * 255 / gray1H) / 3 + (int)(rnd() % 48);
                g1[(size_t)y * width + x] = (unsigned char)(v > 255 ? 255 : v);
            }
        }
        // 新一帧 = 页面整体上移 s 行后落在窗口里的那 100 行（即 gray1 的 [s, s+gray2H)）
        std::vector<unsigned char> g2((size_t)width * gray2H);
        for (int row = 0; row < gray2H; row++)
            memcpy(&g2[(size_t)row * width], &g1[(size_t)(s + row) * width], width);
        // 加一点点噪声，模拟闪烁/抗锯齿差
        for (size_t i = 0; i < g2.size(); i += 7) {
            int v = g2[i] + (int)(rnd() % 5) - 2;
            g2[i] = (unsigned char)(v < 0 ? 0 : (v > 255 ? 255 : v));
        }

        auto t0 = std::chrono::steady_clock::now();
        int yo = findMostSimilarY_old(g1.data(), gray1H, g2.data(), gray2H, width);
        auto t1 = std::chrono::steady_clock::now();
        int yn = findMostSimilarY_new(g1.data(), gray1H, g2.data(), gray2H, width, s > 0 ? s : -1);
        auto t2 = std::chrono::steady_clock::now();
        double msOld = std::chrono::duration<double, std::milli>(t1 - t0).count();
        double msNew = std::chrono::duration<double, std::milli>(t2 - t1).count();
        totalOld += msOld; totalNew += msNew;
        bool same = (yo == yn);
        if (!same) fail++;
        printf("真实滚动 s=%-4d  旧=%-4d 新=%-4d  结果%s   旧 %7.2f ms  新 %6.2f ms  加速 %5.1fx\n",
            s, yo, yn, same ? "一致" : "**不一致**", msOld, msNew, msNew > 0 ? msOld / msNew : 0.0);
    }
    printf("\n合计：旧 %.2f ms  新 %.2f ms  总加速 %.1fx；结果不一致的用例 %d 个\n",
        totalOld, totalNew, totalNew > 0 ? totalOld / totalNew : 0.0, fail);
    return fail ? 1 : 0;
}
