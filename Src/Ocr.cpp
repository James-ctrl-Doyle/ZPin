#include "pch.h"
#include "Ocr.h"

#include <winrt/Windows.Foundation.h>
#include <winrt/Windows.Foundation.Collections.h>
#include <winrt/Windows.Globalization.h>
#include <winrt/Windows.Graphics.Imaging.h>
#include <winrt/Windows.Media.Ocr.h>
#include <winrt/Windows.Security.Cryptography.h>
#include <winrt/Windows.Storage.Streams.h>
#include <winrt/Windows.System.h>

#include <algorithm>
#include <cmath>
#include <thread>

// 这里**不能**用 using namespace winrt::Windows::Media::Ocr：
// WinRT 投影里本来就有一个 OcrWord 类型，导进来会和本文件对外暴露的 OcrWord 撞名
//（error C2872 不明确的符号），所以用命名空间别名逐个限定
namespace wocr = winrt::Windows::Media::Ocr;

using namespace winrt::Windows::Graphics::Imaging;
using namespace winrt::Windows::Security::Cryptography;

namespace {
	// 放大后允许的最大像素数（约 80MB 的 BGRA 缓冲）。
	// 4K 全屏截图再放大两倍就是 3300 万像素，那已经不值得为识别质量付这份内存了
	constexpr UINT64 maxOcrPixels{ 24000000 };

	// 拿一个可用引擎。优先用户语言；用户语言里没有 OCR 能力时退到系统装着的第一种 ——
	// 这样"英文系统 + 只装了中文识别包"也能用起来，而不是直接没反应
	wocr::OcrEngine makeEngine()
	{
		auto engine = wocr::OcrEngine::TryCreateFromUserProfileLanguages();
		if (engine) return engine;
		auto langs = wocr::OcrEngine::AvailableRecognizerLanguages();
		for (uint32_t i = 0; i < langs.Size(); i++) {
			engine = wocr::OcrEngine::TryCreateFromLanguage(langs.GetAt(i));
			if (engine) return engine;
		}
		return nullptr;
	}

	// 按目标尺寸重采样一块 BGRA（top-down、行紧凑）像素。
	// 用 GDI 的 StretchBlt + HALFTONE：这是实测下来对小字提升最大的做法
	//（14px 正文直接识别会错成"户协议与《政策"，放大两倍后完全正确），
	// 而且项目本来就在用 GDI 抓屏，不引入新依赖
	std::vector<BYTE> rescale(const std::vector<BYTE>& src, int sw, int sh, int dw, int dh)
	{
		if (sw <= 0 || sh <= 0 || dw <= 0 || dh <= 0) return {};
		if (sw == dw && sh == dh) return src;
		if (src.size() < (size_t)sw * sh * 4) return {};

		BITMAPINFO bi{};
		bi.bmiHeader.biSize = sizeof(BITMAPINFOHEADER);
		bi.bmiHeader.biWidth = sw;
		// 负高度 = top-down。输入输出必须是同一个方向，否则行序会上下颠倒
		bi.bmiHeader.biHeight = -sh;
		bi.bmiHeader.biPlanes = 1;
		bi.bmiHeader.biBitCount = 32;
		bi.bmiHeader.biCompression = BI_RGB;

		std::vector<BYTE> out((size_t)dw * dh * 4);
		HDC screen = GetDC(nullptr);
		HDC sdc = CreateCompatibleDC(screen);
		HDC ddc = CreateCompatibleDC(screen);
		void* srcBits{ nullptr };
		void* dstBits{ nullptr };
		HBITMAP sbmp = CreateDIBSection(sdc, &bi, DIB_RGB_COLORS, &srcBits, nullptr, 0);
		BITMAPINFO bd = bi;
		bd.bmiHeader.biWidth = dw;
		bd.bmiHeader.biHeight = -dh;
		HBITMAP dbmp = CreateDIBSection(ddc, &bd, DIB_RGB_COLORS, &dstBits, nullptr, 0);

		if (sbmp && dbmp && srcBits && dstBits) {
			CopyMemory(srcBits, src.data(), (size_t)sw * sh * 4);
			HGDIOBJ sold = SelectObject(sdc, sbmp);
			HGDIOBJ dold = SelectObject(ddc, dbmp);
			// HALFTONE 必须配 SetBrushOrgEx，否则半色调图案的基准点没定义，结果可能错乱
			SetStretchBltMode(ddc, HALFTONE);
			SetBrushOrgEx(ddc, 0, 0, nullptr);
			if (StretchBlt(ddc, 0, 0, dw, dh, sdc, 0, 0, sw, sh, SRCCOPY)) {
				GdiFlush();
				CopyMemory(out.data(), dstBits, out.size());
			}
			else {
				out.clear();
			}
			SelectObject(ddc, dold);
			SelectObject(sdc, sold);
		}
		else {
			out.clear();
		}
		if (dbmp) DeleteObject(dbmp);
		if (sbmp) DeleteObject(sbmp);
		DeleteDC(ddc);
		DeleteDC(sdc);
		ReleaseDC(nullptr, screen);
		return out;
	}

	// 中英文之间该不该补空格：两边都是拉丁字母/数字才补。
	// 引擎给的 OcrLine.Text 是在每个"词"之间都插空格，中文会变成"文 字 识 别"，
	// 所以不能用它，必须自己拼
	bool needSpace(wchar_t prev, wchar_t next)
	{
		auto latin = [](wchar_t c) {
			return (c >= L'0' && c <= L'9') || (c >= L'a' && c <= L'z') || (c >= L'A' && c <= L'Z');
		};
		return latin(prev) && latin(next);
	}

	// 真正干活的部分，跑在后台线程上。
	// 整个流程都用这一条 MTA 线程自己的 WinRT 对象，不跨套间传对象 ——
	// 只有最后那份纯 C++ 结构会回到 UI 线程
	std::shared_ptr<OcrPage> doRecognize(int w, int h, const std::vector<BYTE>& pixels)
	{
		if (w <= 0 || h <= 0) return nullptr;
		if (pixels.size() < (size_t)w * h * 4) return nullptr;
		auto engine = makeEngine();
		if (!engine) return nullptr;

		// 先定放大倍数。小字放大两倍是实测最优（三倍反而糊），
		// 但放大后不能越过引擎上限，也不该为了识别把内存顶爆
		const UINT64 maxDim = engine.MaxImageDimension();
		int factor = 2;
		while (factor > 1 && ((UINT64)w * factor > maxDim || (UINT64)h * factor > maxDim
			|| (UINT64)w * h * factor * factor > maxOcrPixels)) {
			factor--;
		}
		// 退到 1 倍还是超上限（滚动截图拼出来的长图可能超过 10000px）：只能等比缩小，
		// 否则 RecognizeAsync 会直接失败
		double shrink = 1.0;
		if ((UINT64)w * factor > maxDim || (UINT64)h * factor > maxDim) {
			shrink = (double)maxDim / (double)((std::max)((UINT64)w * factor, (UINT64)h * factor));
		}
		const double total = factor * shrink;

		const int ow = (std::max)(1, (int)std::llround(w * total));
		const int oh = (std::max)(1, (int)std::llround(h * total));
		std::vector<BYTE> scaled = rescale(pixels, w, h, ow, oh);
		if (scaled.empty()) return nullptr;

		auto buffer = CryptographicBuffer::CreateFromByteArray(
			winrt::array_view<const uint8_t>(scaled.data(), scaled.data() + scaled.size()));
		// Alpha 用 Ignore：抓屏和大多数剪贴板图源的 alpha 通道都不可信（GDI 常常留 0），
		// 而识别只看 RGB
		auto bitmap = SoftwareBitmap::CreateCopyFromBuffer(buffer, BitmapPixelFormat::Bgra8, ow, oh,
			BitmapAlphaMode::Ignore);
		auto result = engine.RecognizeAsync(bitmap).get();

		auto page = std::make_shared<OcrPage>();
		const double inv = 1.0 / total;
		for (auto const& line : result.Lines()) {
			page->lineStarts.push_back((int)page->words.size());
			for (auto const& word : line.Words()) {
				std::wstring text{ word.Text() };
				if (text.empty()) continue;
				auto r = word.BoundingRect();
				OcrWord wd;
				wd.text = std::move(text);
				// 引擎给的是像素矩形（本机实测：720x300 的图上最大 X 是 378），
				// 不是文档里容易误读的归一化值；换算回底图原始像素只要乘 inv
				wd.left = (float)(r.X * inv);
				wd.top = (float)(r.Y * inv);
				wd.right = (float)((r.X + r.Width) * inv);
				wd.bottom = (float)((r.Y + r.Height) * inv);
				page->words.push_back(std::move(wd));
			}
		}
		// 末位哨兵：拼接时用它当每行的终点，不必再判"是不是最后一行"
		page->lineStarts.push_back((int)page->words.size());
		return page;
	}
}

std::wstring OcrPage::textOf(const std::vector<int>& picked) const
{
	std::wstring out;
	// picked 是升序的，用游标一路推进即可，不必每个下标都去二分查找
	size_t k{ 0 };
	for (size_t li = 0; li + 1 < lineStarts.size(); li++)
	{
		std::wstring line;
		for (int i = lineStarts[li]; i < lineStarts[li + 1]; i++)
		{
			while (k < picked.size() && picked[k] < i) k++;
			if (k >= picked.size() || picked[k] != i) continue;
			if (i < 0 || i >= (int)words.size()) continue;
			auto& wd = words[i];
			if (wd.text.empty()) continue;
			if (!line.empty() && needSpace(line.back(), wd.text.front())) line += L' ';
			line += wd.text;
		}
		// 一行都没选中的行不占位置（否则复制出来会多出空行）
		if (line.empty()) continue;
		if (!out.empty()) out += L'\n';
		out += line;
	}
	return out;
}

bool Ocr::available(std::wstring* lang)
{
	if (lang) lang->clear();
	try {
		auto engine = makeEngine();
		if (!engine) return false;
		if (lang) *lang = std::wstring{ engine.RecognizerLanguage().DisplayName() };
		return true;
	}
	catch (...) {
		return false;
	}
}

void Ocr::recognize(int w, int h, std::vector<BYTE> pixels,
	winrt::Windows::System::DispatcherQueue const& dq,
	std::function<void(std::shared_ptr<OcrPage>)> done)
{
	// 拿到结果要往回投，没有 dq 这条链就断了，不如不做
	if (!dq) return;

	// resources 全部按值捕获。像素缓冲可能有好几十 MB，用 move 递进去，别多拷一份
	std::thread([w, h, px = std::move(pixels), dq, done = std::move(done)]() mutable {
		std::shared_ptr<OcrPage> page;
		try {
			// 这条线程自己起一个 MTA 套间：识别全程只碰自己创建的对象，
			// 不把任何 WinRT 对象跨套间传出去
			winrt::init_apartment(winrt::apartment_type::multi_threaded);
			page = doRecognize(w, h, px);
		}
		catch (...) {
			// 引擎内部出什么错都不该把进程带走，当作"没识别到"处理
			page = nullptr;
		}
		// 回到窗口线程再交给调用方 —— 调用方要拿结果去改窗口、请求重绘。
		// TryEnqueue 在 dq 已经停掉时返回 false，那种情况（程序正在退出）丢掉结果即可
		dq.TryEnqueue([done = std::move(done), page]() {
			if (done) done(page);
		});
		try { winrt::uninit_apartment(); }
		catch (...) {}
	}).detach();
}
