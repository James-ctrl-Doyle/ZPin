#include "pch.h"
#include <wincodec.h>
#include <shobjidl.h>
#include <format>
#include <fstream>
#include "Util.h"
#include "Lang.h"
#include "Setting.h"
#include "quirc/quirc.h"

using Microsoft::WRL::ComPtr;

namespace {
	// 把 BGRA top-down 像素编码成 PNG 写进 stream。saveToClipboard 和 saveToFile 共用这段。
	bool encodePng(IStream* stream, const int w, const int h, BYTE* data)
	{
		UINT rowBytes = (UINT)w * 4;
		UINT imgBytes = rowBytes * (UINT)h;
		ComPtr<IWICImagingFactory> factory;
		auto hr = CoCreateInstance(CLSID_WICImagingFactory, nullptr, CLSCTX_INPROC_SERVER, IID_PPV_ARGS(factory.GetAddressOf()));
		if (FAILED(hr)) return false;
		ComPtr<IWICBitmapEncoder> encoder;
		hr = factory->CreateEncoder(GUID_ContainerFormatPng, nullptr, encoder.GetAddressOf());
		if (FAILED(hr)) return false;
		hr = encoder->Initialize(stream, WICBitmapEncoderNoCache);
		if (FAILED(hr)) return false;
		ComPtr<IWICBitmapFrameEncode> frame;
		hr = encoder->CreateNewFrame(frame.GetAddressOf(), nullptr);
		if (FAILED(hr)) return false;
		hr = frame->Initialize(nullptr);
		if (FAILED(hr)) return false;
		hr = frame->SetSize((UINT)w, (UINT)h);
		if (FAILED(hr)) return false;
		WICPixelFormatGUID fmt = GUID_WICPixelFormat32bppBGRA;
		hr = frame->SetPixelFormat(&fmt);
		if (FAILED(hr) || !IsEqualGUID(fmt, GUID_WICPixelFormat32bppBGRA)) return false;
		hr = frame->WritePixels((UINT)h, rowBytes, imgBytes, data);
		if (FAILED(hr)) return false;
		hr = frame->Commit();
		if (FAILED(hr)) return false;
		return SUCCEEDED(encoder->Commit());
	}

	// quirc 交出来的是裸字节流：BYTE 类型的二维码现实中基本都是 UTF-8（微信、支付宝
	// 生成的都是），Kanji 类型按 ISO 18004 规定是 Shift-JIS。所以先按 UTF-8 严格解，
	// 解不通再退回对应的本地代码页，避免把中文变成一堆问号
	std::wstring qrPayloadToWStr(const uint8_t* payload, const int len, const int dataType)
	{
		if (len <= 0) return L"";
		auto convert = [payload, len](UINT codePage, DWORD flags) {
			auto str = (const char*)payload;
			auto count = MultiByteToWideChar(codePage, flags, str, len, nullptr, 0);
			if (count <= 0) return std::wstring();
			std::wstring result(count, 0);
			MultiByteToWideChar(codePage, flags, str, len, result.data(), count);
			return result;
		};
		auto result = convert(CP_UTF8, MB_ERR_INVALID_CHARS);
		if (!result.empty()) return result;
		return convert(dataType == QUIRC_DATA_TYPE_KANJI ? 932 : CP_ACP, 0);
	}

	// "最近一次截图"的临时文件格式。
	// 头是定长的：magic + 版本 + 那张图当初在屏幕上的位置与尺寸；后面紧跟 w*h*4 字节 BGRA。
	// 自描述是为了把"图"和"它原来在屏幕哪儿"放在同一个文件里 —— 贴图要按原位贴出，
	// 两个文件分开写就有对不上的可能
	struct CaptureHead
	{
		char magic[4];
		unsigned version;
		int x, y, w, h;
	};
	constexpr unsigned captureVersion{ 1 };

	std::filesystem::path lastCapturePath()
	{
		auto dir = Setting::get()->getDataPath().append(L"temp");
		std::error_code ec;
		std::filesystem::create_directories(dir, ec);
		return dir.append(L"last.bin");
	}
}

bool Util::saveLastCapture(const int w, const int h, const int x, const int y, BYTE* data)
{
	if (w <= 0 || h <= 0 || !data) return false;
	auto path = lastCapturePath();
	std::ofstream out{ path, std::ios::binary | std::ios::trunc };
	if (!out) return false;
	CaptureHead head{ { 'S','C','A','P' }, captureVersion, x, y, w, h };
	out.write(reinterpret_cast<const char*>(&head), sizeof(head));
	out.write(reinterpret_cast<const char*>(data), (std::streamsize)w * h * 4);
	return out.good();
}

bool Util::loadLastCapture(std::vector<BYTE>& pixels, int& w, int& h, int& x, int& y)
{
	std::ifstream in{ lastCapturePath(), std::ios::binary };
	if (!in) return false;
	CaptureHead head{};
	in.read(reinterpret_cast<char*>(&head), sizeof(head));
	if (!in) return false;
	if (memcmp(head.magic, "SCAP", 4) != 0 || head.version != captureVersion) return false;
	// 尺寸上限与抓屏、剪贴板那几处的取值同量级，防的是文件被改坏之后按离谱的宽高分配
	if (head.w <= 0 || head.h <= 0 || head.w > 32768 || head.h > 32768) return false;
	pixels.resize((size_t)head.w * head.h * 4);
	in.read(reinterpret_cast<char*>(pixels.data()), (std::streamsize)pixels.size());
	if (!in) {
		pixels.clear();
		return false;
	}
	w = head.w;
	h = head.h;
	x = head.x;
	y = head.y;
	return true;
}

// ———————————————————— 截图历史 ————————————————————
// 每次截图留一份"整屏画面 + 当时的截图框"，按时间戳命名摆在 temp\shots 下。
// 这样截图模式里按 ← 就能把上一条翻出来重看：底图、框都回到当时的样子，
// 想重新裁一块或者补两笔都行。默认只留 3 天，天数在设置里可调。
namespace {
	struct ShotHead
	{
		char magic[4];        // 'S','C','H','T'
		uint32_t version;
		int32_t screenX, screenY, screenW, screenH;   // 整屏图在虚拟桌面里的位置与尺寸
		int32_t maskL, maskT, maskR, maskB;           // 当时的截图框（屏幕坐标）
		uint32_t pngOffset;                           // PNG 数据从头开始的偏移
	};
	constexpr uint32_t shotVersion{ 1 };
	// 时间戳文件名：20260919_010203_456.bin
	std::wstring shotName()
	{
		SYSTEMTIME st;
		GetLocalTime(&st);
		return std::format(L"{:04d}{:02d}{:02d}_{:02d}{:02d}{:02d}_{:03d}.bin",
			st.wYear, st.wMonth, st.wDay, st.wHour, st.wMinute, st.wSecond, st.wMilliseconds);
	}
}

std::filesystem::path Util::shotDir()
{
	auto dir = Setting::get()->getTempPath(); // <exe 同目录>\temp
	return dir.append(L"shots");
}

std::wstring Util::makeShotPath()
{
	auto dir = shotDir();
	std::error_code ec;
	std::filesystem::create_directories(dir, ec);
	// 时间戳精确到毫秒，同一毫秒内再来一次就往后顺延（同一次截图里连点复制也只会写一条，
	// 这里只是别让两个后台写入撞到同一个名字上）
	for (int i = 0; i < 1000; i++) {
		auto name = shotName();
		if (i > 0) {
			auto dot = name.rfind(L'.');
			name.insert(dot, std::format(L"_{:03d}", i));
		}
		auto path = dir / name;
		if (!std::filesystem::exists(path, ec)) return path.wstring();
	}
	return (dir / shotName()).wstring();
}

bool Util::writeShot(const std::wstring& path, const int screenX, const int screenY,
	const int screenW, const int screenH, std::vector<BYTE> pixels, const RECT& mask)
{
	if (path.empty() || screenW <= 0 || screenH <= 0) return false;
	if (pixels.size() < (size_t)screenW * screenH * 4) return false;

	// 先编码 PNG：头里的 pngOffset 要用到编码后的字节数
	ComPtr<IStream> stream;
	if (FAILED(CreateStreamOnHGlobal(nullptr, TRUE, stream.GetAddressOf()))) return false;
	if (!encodePng(stream.Get(), screenW, screenH, pixels.data())) return false;
	STATSTG stat{};
	if (FAILED(stream->Stat(&stat, STATFLAG_NONAME))) return false;
	HGLOBAL hGlobal{ nullptr };
	if (FAILED(GetHGlobalFromStream(stream.Get(), &hGlobal)) || !hGlobal) return false;
	auto src = static_cast<const BYTE*>(GlobalLock(hGlobal));
	if (!src) return L"";

	// 写 .tmp 再改名：中途被打断也不会留下半个 .bin 让下次读到坏数据
	std::filesystem::path target{ path };
	std::filesystem::path tmp{ path + L".tmp" };
	bool ok{ false };
	{
		std::ofstream out{ tmp, std::ios::binary | std::ios::trunc };
		if (out) {
			ShotHead head{};
			memcpy(head.magic, "SCHT", 4);
			head.version = shotVersion;
			head.screenX = screenX;
			head.screenY = screenY;
			head.screenW = screenW;
			head.screenH = screenH;
			head.maskL = mask.left;
			head.maskT = mask.top;
			head.maskR = mask.right;
			head.maskB = mask.bottom;
			head.pngOffset = sizeof(ShotHead);
			out.write(reinterpret_cast<const char*>(&head), sizeof(head));
			out.write(reinterpret_cast<const char*>(src), (std::streamsize)stat.cbSize.QuadPart);
			ok = out.good();
		}
	}
	GlobalUnlock(hGlobal);
	std::error_code ec;
	if (!ok) {
		std::filesystem::remove(tmp, ec);
		return false;
	}
	std::filesystem::rename(tmp, target, ec);
	if (ec) {
		std::filesystem::remove(tmp, ec);
		return false;
	}
	return true;
}

std::wstring Util::saveShot(const int screenX, const int screenY, const int screenW,
	const int screenH, BYTE* data, const RECT& mask)
{
	if (!data) return L"";
	auto path = makeShotPath();
	std::vector<BYTE> copy(data, data + (size_t)screenW * screenH * 4);
	if (!writeShot(path, screenX, screenY, screenW, screenH, std::move(copy), mask)) return L"";
	return path;
}

bool Util::patchShotRect(const std::wstring& path, const RECT& mask)
{
	// 只改头里的框：头是定长的、在文件最前面，不用重新编码 PNG。
	// 翻看历史时"改完框再翻走"就靠它把新框记回去
	std::fstream file{ path, std::ios::binary | std::ios::in | std::ios::out };
	if (!file) return false;
	ShotHead head{};
	file.read(reinterpret_cast<char*>(&head), sizeof(head));
	if (!file || memcmp(head.magic, "SCHT", 4) != 0 || head.version != shotVersion) return false;
	head.maskL = mask.left;
	head.maskT = mask.top;
	head.maskR = mask.right;
	head.maskB = mask.bottom;
	file.seekp(0);
	file.write(reinterpret_cast<const char*>(&head), sizeof(head));
	return file.good();
}

bool Util::loadShot(const std::wstring& path, std::vector<BYTE>& pixels, int& w, int& h,
	int& screenX, int& screenY, RECT& mask)
{
	std::ifstream in{ path, std::ios::binary };
	if (!in) return false;
	ShotHead head{};
	in.read(reinterpret_cast<char*>(&head), sizeof(head));
	if (!in) return false;
	if (memcmp(head.magic, "SCHT", 4) != 0 || head.version != shotVersion) return false;
	if (head.screenW <= 0 || head.screenH <= 0 ||
		head.screenW > 32768 || head.screenH > 32768) return false;
	in.seekg(head.pngOffset);
	std::vector<BYTE> png{ std::istreambuf_iterator<char>{in}, std::istreambuf_iterator<char>{} };
	if (png.empty()) return false;

	// 和读剪贴板那边同一套路：解码后统一转成 32 位 BGRA
	ComPtr<IStream> stream;
	if (FAILED(CreateStreamOnHGlobal(nullptr, TRUE, stream.GetAddressOf()))) return false;
	ULONG written{ 0 };
	if (FAILED(stream->Write(png.data(), (ULONG)png.size(), &written))) return false;
	LARGE_INTEGER zero{};
	stream->Seek(zero, STREAM_SEEK_SET, nullptr);

	ComPtr<IWICImagingFactory> factory;
	if (FAILED(CoCreateInstance(CLSID_WICImagingFactory, nullptr, CLSCTX_INPROC_SERVER,
		IID_PPV_ARGS(factory.GetAddressOf())))) return false;
	ComPtr<IWICBitmapDecoder> decoder;
	if (FAILED(factory->CreateDecoderFromStream(stream.Get(), nullptr,
		WICDecodeMetadataCacheOnDemand, decoder.GetAddressOf()))) return false;
	ComPtr<IWICBitmapFrameDecode> frame;
	if (FAILED(decoder->GetFrame(0, frame.GetAddressOf()))) return false;
	ComPtr<IWICFormatConverter> converter;
	if (FAILED(factory->CreateFormatConverter(converter.GetAddressOf()))) return false;
	if (FAILED(converter->Initialize(frame.Get(), GUID_WICPixelFormat32bppBGRA,
		WICBitmapDitherTypeNone, nullptr, 0.0f, WICBitmapPaletteTypeCustom))) return false;
	UINT cw{ 0 }, ch{ 0 };
	if (FAILED(converter->GetSize(&cw, &ch)) || cw == 0 || ch == 0 || cw > 32768 || ch > 32768) return false;
	const UINT rowBytes = cw * 4;
	pixels.resize((size_t)rowBytes * ch);
	if (FAILED(converter->CopyPixels(nullptr, rowBytes, (UINT)pixels.size(), pixels.data()))) {
		pixels.clear();
		return false;
	}
	w = (int)cw;
	h = (int)ch;
	screenX = head.screenX;
	screenY = head.screenY;
	mask = { head.maskL, head.maskT, head.maskR, head.maskB };
	return true;
}

std::vector<Util::ShotInfo> Util::listShots()
{
	std::vector<ShotInfo> list;
	auto dir = shotDir();
	std::error_code ec;
	if (!std::filesystem::exists(dir, ec)) return list;
	for (auto& entry : std::filesystem::directory_iterator(dir, ec)) {
		if (ec) break;
		if (!entry.is_regular_file(ec)) continue;
		if (entry.path().extension() != L".bin") continue;
		ShotInfo info{};
		info.path = entry.path().wstring();
		// 时间戳就在名字里（20260919_010203_456.bin），按名字排就等于按时间排，
		// 比读文件的修改时间稳 —— 复制/搬家之后 mtime 会变，名字不会
		info.name = entry.path().filename().wstring();
		list.push_back(info);
	}
	// 新的排前面：名字是定长时间戳，字典序倒排即可
	std::sort(list.begin(), list.end(),
		[](const ShotInfo& a, const ShotInfo& b) { return a.name > b.name; });
	return list;
}

void Util::pruneShots(int days)
{
	std::error_code ec;
	// "现在"和"截图时间"都走 FILETIME（1601 起、单位 100ns），不混用 std::filesystem 的时钟基准 ——
	// 那个基准是实现定义的，和 FILETIME 对不上就会把新文件当过期删掉
	SYSTEMTIME nowSt{};
	GetLocalTime(&nowSt);
	FILETIME nowFt{};
	if (!SystemTimeToFileTime(&nowSt, &nowFt)) return;
	ULARGE_INTEGER now{ { nowFt.dwLowDateTime, nowFt.dwHighDateTime } };
	constexpr long long day100ns{ 24LL * 3600 * 10000000 };
	for (auto& shot : listShots()) {
		// 时间从文件名里的时间戳解析，不依赖文件时间：复制/搬家之后 mtime 会变，名字不会
		int y{}, mo{}, d{}, hh{}, mi{}, ss{}, ms{};
		if (swscanf_s(std::filesystem::path{ shot.name }.stem().c_str(),
			L"%4d%2d%2d_%2d%2d%2d_%3d", &y, &mo, &d, &hh, &mi, &ss, &ms) != 7) continue;
		SYSTEMTIME st{};
		st.wYear = (WORD)y; st.wMonth = (WORD)mo; st.wDay = (WORD)d;
		st.wHour = (WORD)hh; st.wMinute = (WORD)mi; st.wSecond = (WORD)ss;
		FILETIME ft{};
		if (!SystemTimeToFileTime(&st, &ft)) continue;
		ULARGE_INTEGER t{ { ft.dwLowDateTime, ft.dwHighDateTime } };
		if (t.QuadPart >= now.QuadPart) continue;  // 时间戳比现在晚（改过系统时间），留着
		auto ageDays = (long long)((now.QuadPart - t.QuadPart) / day100ns);
		// days <= 0 = 不保留历史，全清
		if (days <= 0 || ageDays >= days) {
			std::filesystem::remove(shot.path, ec);
		}
	}
}

void Util::saveToClipboard(const int w, const int h, BYTE* data)
{
	if (w <= 0 || h <= 0 || !data) return;
	DWORD rowBytes = (DWORD)w * 4;
	DWORD imgBytes = rowBytes * (DWORD)h;

	// ---------- 1) PNG 编码到内存流 ----------
	ComPtr<IStream> pngStream;
	if (FAILED(CreateStreamOnHGlobal(nullptr, TRUE, pngStream.GetAddressOf()))) return;
	if (!encodePng(pngStream.Get(), w, h, data)) return;
	// 流内部的 HGLOBAL 尺寸可能大于实际字节数，拷一份精确大小的出来给剪切板
	STATSTG stat{};
	if (FAILED(pngStream->Stat(&stat, STATFLAG_NONAME))) return;
	SIZE_T pngSize = (SIZE_T)stat.cbSize.QuadPart;
	if (pngSize == 0) return;
	HGLOBAL hPngSrc{ nullptr };
	if (FAILED(GetHGlobalFromStream(pngStream.Get(), &hPngSrc)) || !hPngSrc) return;
	auto srcPtr = GlobalLock(hPngSrc);
	if (!srcPtr) return;
	HGLOBAL hPng = GlobalAlloc(GMEM_MOVEABLE, pngSize);
	if (!hPng) { GlobalUnlock(hPngSrc); return; }
	auto dstPtr = GlobalLock(hPng);
	if (!dstPtr) { GlobalUnlock(hPngSrc); GlobalFree(hPng); return; }
	CopyMemory(dstPtr, srcPtr, pngSize);
	GlobalUnlock(hPng);
	GlobalUnlock(hPngSrc);

	// ---------- 2) 构造 CF_DIBV5（带 alpha） ----------
	HGLOBAL hDibV5 = GlobalAlloc(GMEM_MOVEABLE, sizeof(BITMAPV5HEADER) + imgBytes);
	if (!hDibV5) { GlobalFree(hPng); return; }
	auto pv5 = static_cast<BYTE*>(GlobalLock(hDibV5));
	if (!pv5) { GlobalFree(hDibV5); GlobalFree(hPng); return; }
	auto bv5 = reinterpret_cast<BITMAPV5HEADER*>(pv5);
	*bv5 = {};
	bv5->bV5Size = sizeof(BITMAPV5HEADER);
	bv5->bV5Width = w;
	bv5->bV5Height = -h;                  // 负 = top-down
	bv5->bV5Planes = 1;
	bv5->bV5BitCount = 32;
	bv5->bV5Compression = BI_BITFIELDS;   // 让接收端识别 alpha
	bv5->bV5SizeImage = imgBytes;
	bv5->bV5RedMask = 0x00FF0000;
	bv5->bV5GreenMask = 0x0000FF00;
	bv5->bV5BlueMask = 0x000000FF;
	bv5->bV5AlphaMask = 0xFF000000;
	bv5->bV5CSType = LCS_sRGB;
	bv5->bV5Intent = LCS_GM_GRAPHICS;
	CopyMemory(pv5 + sizeof(BITMAPV5HEADER), data, imgBytes);
	GlobalUnlock(hDibV5);

	// ---------- 3) 构造 CF_DIB（24bpp、BI_RGB、自下而上） ----------
	// 老软件（比如 Illustrator 2020）只认最传统的这一种 DIB：注册格式 PNG 它不查，
	// CF_DIBV5 它不认，32bpp + BI_BITFIELDS 和 top-down 也读不了。系统虽然能从 CF_DIBV5
	// 合成出 CF_DIB，合成出来的仍是那份带 alpha 的 32 位数据，一样不合它的口味。
	// 所以显式再放一份最保守的：丢掉 alpha 写成 24 位，行按 4 字节对齐，自下而上排列
	DWORD dibRowBytes = ((DWORD)w * 3 + 3) & ~3u;
	DWORD dibImgBytes = dibRowBytes * (DWORD)h;
	HGLOBAL hDib = GlobalAlloc(GMEM_MOVEABLE, sizeof(BITMAPINFOHEADER) + dibImgBytes);
	if (!hDib) { GlobalFree(hDibV5); GlobalFree(hPng); return; }
	auto pDib = static_cast<BYTE*>(GlobalLock(hDib));
	if (!pDib) { GlobalFree(hDib); GlobalFree(hDibV5); GlobalFree(hPng); return; }
	auto bi = reinterpret_cast<BITMAPINFOHEADER*>(pDib);
	*bi = {};
	bi->biSize = sizeof(BITMAPINFOHEADER);
	bi->biWidth = w;
	bi->biHeight = h;                     // 正 = 自下而上
	bi->biPlanes = 1;
	bi->biBitCount = 24;
	bi->biCompression = BI_RGB;
	bi->biSizeImage = dibImgBytes;
	auto dibPixels = pDib + sizeof(BITMAPINFOHEADER);
	for (int row = 0; row < h; row++) {
		auto src = data + (size_t)row * rowBytes;                 //入参是 top-down
		auto dst = dibPixels + (size_t)(h - 1 - row) * dibRowBytes;
		for (int col = 0; col < w; col++) {
			dst[0] = src[0]; dst[1] = src[1]; dst[2] = src[2];     //BGRA -> BGR
			src += 4;
			dst += 3;
		}
	}
	GlobalUnlock(hDib);

	// ---------- 4) 写入剪切板 ----------
	if (!OpenClipboard(nullptr)) {
		GlobalFree(hDib);
		GlobalFree(hDibV5);
		GlobalFree(hPng);
		return;
	}
	EmptyClipboard();
	// SetClipboardData 成功后 HGLOBAL 归剪切板所有，不能再 GlobalFree；失败了才要自己释放
	if (!SetClipboardData(CF_DIBV5, hDibV5)) {
		GlobalFree(hDibV5);
	}
	if (!SetClipboardData(CF_DIB, hDib)) {
		GlobalFree(hDib);
	}
	UINT cfPng = RegisterClipboardFormatW(L"PNG");
	if (cfPng == 0 || !SetClipboardData(cfPng, hPng)) {
		GlobalFree(hPng);
	}
	CloseClipboard();
}

bool Util::saveToFile(const std::wstring& path, const int w, const int h, BYTE* data)
{
	if (path.empty() || w <= 0 || h <= 0 || !data) return false;
	ComPtr<IWICImagingFactory> factory;
	auto hr = CoCreateInstance(CLSID_WICImagingFactory, nullptr, CLSCTX_INPROC_SERVER, IID_PPV_ARGS(factory.GetAddressOf()));
	if (FAILED(hr)) return false;
	ComPtr<IWICStream> stream;
	hr = factory->CreateStream(stream.GetAddressOf());
	if (FAILED(hr)) return false;
	hr = stream->InitializeFromFilename(path.c_str(), GENERIC_WRITE);
	if (FAILED(hr)) return false;
	return encodePng(stream.Get(), w, h, data);
}

std::wstring Util::getSaveFilePath(HWND hwnd, const std::wstring& ext, const std::filesystem::path& dir)
{
	std::wstring result;
	ComPtr<IFileSaveDialog> saveDialog;
	auto hr = CoCreateInstance(CLSID_FileSaveDialog, nullptr, CLSCTX_INPROC_SERVER, IID_PPV_ARGS(saveDialog.GetAddressOf()));
	if (FAILED(hr)) return result;
	DWORD dwFlags{ 0 };
	saveDialog->GetOptions(&dwFlags);
	saveDialog->SetOptions(dwFlags | FOS_OVERWRITEPROMPT | FOS_STRICTFILETYPES);
	auto pattern = L"*." + ext;
	auto typeName = Lang::get(L"util.file");
	COMDLG_FILTERSPEC filterSpec[]{ { typeName.c_str(), pattern.c_str() } };
	saveDialog->SetFileTypes(_countof(filterSpec), filterSpec);
	saveDialog->SetFileTypeIndex(1);
	saveDialog->SetDefaultExtension(ext.c_str());
	// "默认保存位置"：设了就用它。SetDefaultFolder 只管"头一次打开"，
	// 系统还会记住本进程上次选的目录 —— 所以再设一遍 SetFolder 强制换过去，
	// 否则用户换了默认位置却发现对话框还停在上次那个文件夹
	if (!dir.empty() && std::filesystem::exists(dir)) {
		ComPtr<IShellItem> folder;
		if (SUCCEEDED(SHCreateItemFromParsingName(dir.c_str(), nullptr, IID_PPV_ARGS(folder.GetAddressOf())))) {
			saveDialog->SetDefaultFolder(folder.Get());
			saveDialog->SetFolder(folder.Get());
		}
	}
	auto fileName = createFileName(ext);
	saveDialog->SetFileName(fileName.c_str());
	// 用户取消时 Show 返回 HRESULT_FROM_WIN32(ERROR_CANCELLED)，一样走 FAILED 分支
	hr = saveDialog->Show(hwnd);
	if (FAILED(hr)) return result;
	ComPtr<IShellItem> item;
	hr = saveDialog->GetResult(item.GetAddressOf());
	if (FAILED(hr)) return result;
	PWSTR filePath{ nullptr };
	hr = item->GetDisplayName(SIGDN_FILESYSPATH, &filePath);
	if (FAILED(hr)) return result;
	result = filePath;
	CoTaskMemFree(filePath);
	return result;
}

std::wstring Util::pickFolder(HWND owner, const std::filesystem::path& initial)
{
	std::wstring result;
	ComPtr<IFileOpenDialog> dlg;
	auto hr = CoCreateInstance(CLSID_FileOpenDialog, nullptr, CLSCTX_INPROC_SERVER, IID_PPV_ARGS(dlg.GetAddressOf()));
	if (FAILED(hr)) return result;
	DWORD flags{ 0 };
	dlg->GetOptions(&flags);
	// FOS_PICKFOLDERS 把它变成"选目录"；PATHMUSTEXIST 免得用户选到一个不存在的路径
	dlg->SetOptions(flags | FOS_PICKFOLDERS | FOS_FORCEFILESYSTEM | FOS_PATHMUSTEXIST);
	dlg->SetTitle(Lang::get(L"setting.saveDir").c_str());
	if (!initial.empty() && std::filesystem::exists(initial)) {
		ComPtr<IShellItem> folder;
		if (SUCCEEDED(SHCreateItemFromParsingName(initial.c_str(), nullptr, IID_PPV_ARGS(folder.GetAddressOf())))) {
			dlg->SetFolder(folder.Get());
		}
	}
	hr = dlg->Show(owner);
	if (FAILED(hr)) return result; //用户取消（HRESULT_FROM_WIN32(ERROR_CANCELLED)）走这里
	ComPtr<IShellItem> item;
	if (FAILED(dlg->GetResult(item.GetAddressOf()))) return result;
	PWSTR path{ nullptr };
	if (FAILED(item->GetDisplayName(SIGDN_FILESYSPATH, &path))) return result;
	result = path;
	CoTaskMemFree(path);
	return result;
}

std::wstring Util::resolveSavePath(const std::wstring& ext, HWND owner)
{
	auto setting = Setting::get();
	if (!setting) return getSaveFilePath(owner, ext);
	if (!setting->getQuickSave()) {
		// 没勾快速保存：还是每次弹另存为，只是初始目录用"默认保存位置"
		return getSaveFilePath(owner, ext, setting->getSaveDir());
	}
	auto dir = setting->getSaveDir();
	// 用户选的目录后来被删了/挪走了：现建一个，别让"快速保存"静默失败
	std::error_code ec;
	if (!std::filesystem::exists(dir, ec)) {
		std::filesystem::create_directories(dir, ec);
	}
	return (dir / createFileName(ext)).wstring();
}

std::wstring Util::createFileName(const std::wstring& ext)
{
	SYSTEMTIME st;
	GetLocalTime(&st);
	return std::format(L"{:04d}{:02d}{:02d}{:02d}{:02d}{:02d}{:03d}.{}",
		st.wYear, st.wMonth, st.wDay, st.wHour, st.wMinute, st.wSecond, st.wMilliseconds, ext);
}

std::vector<BYTE> Util::captureScreen(const int x, const int y, const int w, const int h)
{
	std::vector<BYTE> data;
	if (w <= 0 || h <= 0) return data;
	HDC hScreen = GetDC(nullptr);
	// 用 DIBSection 直接拿像素内存：BitBlt 写进去就是我们要的格式，
	// 省掉 CreateCompatibleBitmap + GetDIBits 那一趟整屏回读。
	// 长图每滚一步都要调这个函数，这笔开销是按步计的
	BITMAPINFO bmi{};
	bmi.bmiHeader.biSize = sizeof(BITMAPINFOHEADER);
	bmi.bmiHeader.biWidth = w;
	// 负高度 = top-down，第一行就是屏幕最上面那行，省掉后续所有翻转
	bmi.bmiHeader.biHeight = -h;
	bmi.bmiHeader.biPlanes = 1;
	bmi.bmiHeader.biBitCount = 32;
	bmi.bmiHeader.biCompression = BI_RGB;
	void* bits{ nullptr };
	HBITMAP hBitmap = CreateDIBSection(hScreen, &bmi, DIB_RGB_COLORS, &bits, nullptr, 0);
	if (!hBitmap || !bits) {
		ReleaseDC(nullptr, hScreen);
		return data;
	}
	HDC hDC = CreateCompatibleDC(hScreen);
	auto oldObj = SelectObject(hDC, hBitmap);
	BitBlt(hDC, 0, 0, w, h, hScreen, x, y, SRCCOPY);
	// GDI 的绘制是批处理的，读 bits 之前必须让它落盘
	GdiFlush();
	SelectObject(hDC, oldObj);
	DeleteDC(hDC);
	ReleaseDC(nullptr, hScreen);
	const size_t bytes = (size_t)w * 4 * h;
	data.resize(bytes);
	CopyMemory(data.data(), bits, bytes);
	DeleteObject(hBitmap);
	return data;
}

void Util::addFileToClipboard(const std::wstring& filePath)
{
	if (!OpenClipboard(nullptr)) return;
	EmptyClipboard();
	// DROPFILES 之后紧跟双 \0 结尾的路径列表，这里只放一条
	auto totalSize = sizeof(DROPFILES) + (filePath.length() + 2) * sizeof(wchar_t);
	auto hGlobal = GlobalAlloc(GMEM_MOVEABLE, totalSize);
	if (!hGlobal) {
		CloseClipboard();
		return;
	}
	auto pDropFiles = static_cast<DROPFILES*>(GlobalLock(hGlobal));
	if (!pDropFiles) {
		GlobalFree(hGlobal);
		CloseClipboard();
		return;
	}
	pDropFiles->pFiles = sizeof(DROPFILES);
	pDropFiles->fWide = TRUE;
	auto dest = reinterpret_cast<wchar_t*>(pDropFiles + 1);
	wcscpy_s(dest, filePath.length() + 1, filePath.c_str());
	dest[filePath.length() + 1] = L'\0';
	GlobalUnlock(hGlobal);
	// 成功后 HGLOBAL 归剪切板所有，只在失败时自己释放
	if (!SetClipboardData(CF_HDROP, hGlobal)) {
		GlobalFree(hGlobal);
	}
	CloseClipboard();
}

bool Util::getClipboardImage(std::vector<BYTE>& pixels, int& w, int& h)
{
	pixels.clear();
	w = 0;
	h = 0;

	const UINT cfPng = RegisterClipboardFormatW(L"PNG");
	// 三种格式一个都不在，就不必去开剪贴板了
	if (!cfPng ||
		(!IsClipboardFormatAvailable(cfPng) &&
		 !IsClipboardFormatAvailable(CF_DIBV5) &&
		 !IsClipboardFormatAvailable(CF_DIB))) return false;

	if (!OpenClipboard(nullptr)) return false;

	// 出口统一收尾。中间分支多，散着写迟早漏一个 —— 漏了 CloseClipboard 会让剪贴板一直锁着，
	// 用户在别的程序里全都粘贴不了。声明在 OpenClipboard 之后，析构顺序上它又是最后一个，
	// 所以 WIC 那些对象已经用完这张位图了才轮到这里删它
	struct Guard
	{
		HBITMAP bmp{ nullptr };
		~Guard()
		{
			if (bmp) DeleteObject(bmp);
			CloseClipboard();
		}
	} guard;

	ComPtr<IWICImagingFactory> factory;
	auto hr = CoCreateInstance(CLSID_WICImagingFactory, nullptr, CLSCTX_INPROC_SERVER, IID_PPV_ARGS(factory.GetAddressOf()));
	if (FAILED(hr)) return false;

	ComPtr<IWICBitmapSource> source;
	// 来源到底有没有可信的 alpha。PNG 和"V5 头里带了非零 alpha 掩码"的 DIB 才算有，
	// 其余的（尤其 32 位 CF_DIB）一律当不透明，见下面补 alpha 那一段
	bool hasAlpha{ false };

	// ---------- 路线一：注册格式 "PNG" ----------
	// 本程序自己、浏览器 / Electron 一类程序放的就是这一份：alpha 完整，而且不用去猜
	// DIB 的朝向、位深和位域，所以有它就优先走它
	if (IsClipboardFormatAvailable(cfPng)) {
		if (HANDLE hMem = GetClipboardData(cfPng)) {
			// fDeleteOnRelease = FALSE：这块 HGLOBAL 归剪贴板所有，包成流只是为了读，
			// 顺手释放掉就是动别人的内存。包好之后不用 GlobalLock，流自己会去访问
			ComPtr<IStream> stream;
			if (SUCCEEDED(CreateStreamOnHGlobal(hMem, FALSE, stream.GetAddressOf()))) {
				ComPtr<IWICBitmapDecoder> decoder;
				if (SUCCEEDED(factory->CreateDecoderFromStream(stream.Get(), nullptr, WICDecodeMetadataCacheOnDemand, decoder.GetAddressOf()))) {
					ComPtr<IWICBitmapFrameDecode> frame;
					if (SUCCEEDED(decoder->GetFrame(0, frame.GetAddressOf()))) {
						source = frame;
						hasAlpha = true;
					}
				}
			}
		}
	}

	// ---------- 路线二：CF_DIBV5 / CF_DIB ----------
	// 系统能从 CF_DIBV5 合成出 CF_DIB，反过来不行，所以先问 V5。
	// 这条路要把来源的朝向、位深、位域全抹平，办法是借 GDI 建一张 DIBSection 中转：
	// 朝向交给 GDI，像素格式交给 WIC，比自己解析三种位域省事也更不容易错
	if (!source) {
		const UINT cf = IsClipboardFormatAvailable(CF_DIBV5) ? CF_DIBV5 : CF_DIB;
		if (HANDLE hMem = GetClipboardData(cf)) {
			auto src = (const BYTE*)GlobalLock(hMem);
			if (src) {
				auto bi = (const BITMAPINFOHEADER*)src;
				if (bi->biSize >= sizeof(BITMAPINFOHEADER) && bi->biWidth > 0 &&
					bi->biHeight != 0 && bi->biBitCount >= 1) {
					// 剪贴板里放的是 BITMAPINFO 后紧跟像素。头后面可能还跟着颜色表或三个
					// 位域掩码，长度现算：位域掩码只在 40 字节的小头后面才跟在外面
					//（V4 / V5 的掩码在头内部）
					UINT extra{ 0 };
					if (bi->biCompression == BI_BITFIELDS && bi->biSize == sizeof(BITMAPINFOHEADER)) extra = 12;
					UINT clrEntries = bi->biClrUsed;
					if (clrEntries == 0 && bi->biBitCount <= 8) clrEntries = 1u << bi->biBitCount;
					const UINT infoBytes = bi->biSize + extra + clrEntries * 4;

					// 剪贴板里那份头是只读的，而 CreateDIBSection 要能改它（下面要把高度掰正），
					// 所以整块拷一份出来
					std::vector<BYTE> info(infoBytes);
					CopyMemory(info.data(), src, infoBytes);
					auto pbi = (BITMAPINFO*)info.data();
					const int imgW = (int)pbi->bmiHeader.biWidth;
					const int imgH = std::abs((int)pbi->bmiHeader.biHeight);
					const bool srcTopDown = bi->biHeight < 0;
					// 统一按 top-down 建，朝向的差异在下面拷行时一次抹平
					pbi->bmiHeader.biHeight = -imgH;

					HDC hScreen = GetDC(nullptr);
					void* bits{ nullptr };
					guard.bmp = CreateDIBSection(hScreen, pbi, DIB_RGB_COLORS, &bits, nullptr, 0);
					ReleaseDC(nullptr, hScreen);
					if (guard.bmp && bits) {
						// DIB 的扫描行一律按 4 字节对齐（不管多少位），来源和 DIBSection 用
						// 的是同一个公式，所以可以整行 memcpy
						const UINT rowBytes = (UINT)(((size_t)imgW * pbi->bmiHeader.biBitCount + 31) / 32 * 4);
						for (int row = 0; row < imgH; row++) {
							auto line = src + infoBytes + (size_t)(srcTopDown ? row : imgH - 1 - row) * rowBytes;
							CopyMemory((BYTE*)bits + (size_t)row * rowBytes, line, rowBytes);
						}
						// alpha 只信 V5 里真的带了非零掩码的那些。CF_DIB 一律当不透明 ——
						// 32 位但 alpha 全 0 的图很常见，当真了贴出来就是一张全透明的图
						hasAlpha = cf == CF_DIBV5 && bi->biSize >= sizeof(BITMAPV5HEADER) &&
							((const BITMAPV5HEADER*)src)->bV5AlphaMask != 0;
						ComPtr<IWICBitmap> bmp;
						// WICBitmapUseAlpha / IgnoreAlpha 正好对应上面两种情况：前者保住 V5 的
						// alpha，后者显式忽略 32 位 DIB 里那个没意义的 alpha 通道
						if (SUCCEEDED(factory->CreateBitmapFromHBITMAP(guard.bmp, nullptr,
							hasAlpha ? WICBitmapUseAlpha : WICBitmapIgnoreAlpha, bmp.GetAddressOf()))) {
							source = bmp;
						}
					}
				}
				GlobalUnlock(hMem);
			}
		}
	}

	if (!source) return false;

	// ---------- 统一转成 32 位 BGRA（直通 alpha） ----------
	ComPtr<IWICFormatConverter> converter;
	hr = factory->CreateFormatConverter(converter.GetAddressOf());
	if (FAILED(hr)) return false;
	hr = converter->Initialize(source.Get(), GUID_WICPixelFormat32bppBGRA,
		WICBitmapDitherTypeNone, nullptr, 0.0f, WICBitmapPaletteTypeCustom);
	if (FAILED(hr)) return false;

	UINT cw{ 0 }, ch{ 0 };
	if (FAILED(converter->GetSize(&cw, &ch))) return false;
	// 16384 是防剪贴板里被塞了畸形尺寸的图：再大下去 cw * 4 * ch 会溢出下面那个
	// UINT 长度参数，真到那个量级也已经不是"贴一张图"该有的用法了
	if (cw == 0 || ch == 0 || cw > 16384 || ch > 16384) return false;

	const UINT rowBytes = cw * 4;
	pixels.resize((size_t)rowBytes * ch);
	hr = converter->CopyPixels(nullptr, rowBytes, (UINT)pixels.size(), pixels.data());
	if (FAILED(hr)) {
		pixels.clear();
		return false;
	}

	// 声明带 alpha、但整张 alpha 全是 0 的图也真实存在（放的时候就压根没填过 alpha 通道）。
	// 那种贴出来是全透明的，用户只会以为程序坏了 —— 真·全透明图片极少见，统一当不透明
	if (hasAlpha) {
		hasAlpha = false;
		for (size_t i = 3; i < pixels.size(); i += 4) {
			if (pixels[i] != 0) { hasAlpha = true; break; }
		}
	}
	if (!hasAlpha) {
		for (size_t i = 3; i < pixels.size(); i += 4) pixels[i] = 255;
	}

	// 贴图窗口的底图是按"预乘 alpha"建的（见 WinPin 里的 CreateBitmap 用的是
	// ALPHA_MODE_PREMULTIPLIED），WIC 交出来的是直通 alpha，这里补一次预乘 ——
	// 拿直通值当预乘值用，D2D 会按 alpha 又乘一遍，半透明像素会偏亮
	for (size_t i = 0; i + 3 < pixels.size(); i += 4) {
		const BYTE a = pixels[i + 3];
		if (a == 255) continue;
		// a == 0 的像素不能只是跳过：预乘要求 RGB 不大于 alpha，留着直通值
		// 会让 D2D 按预乘规则混合时算出负数
		if (a == 0) {
			pixels[i] = pixels[i + 1] = pixels[i + 2] = 0;
			continue;
		}
		pixels[i + 0] = (BYTE)((pixels[i + 0] * a + 127) / 255);
		pixels[i + 1] = (BYTE)((pixels[i + 1] * a + 127) / 255);
		pixels[i + 2] = (BYTE)((pixels[i + 2] * a + 127) / 255);
	}

	w = (int)cw;
	h = (int)ch;
	return true;
}

std::wstring Util::decodeQrCode(const int w, const int h, BYTE* data)
{
	std::wstring result;
	if (w <= 0 || h <= 0 || !data) return result;
	// quirc_new 和 quirc_resize 是这个库里唯一会申请内存的两个函数，选区大的时候
	// 那块灰度缓冲不小，所以下面每条返回路径都得走到 quirc_destroy
	auto qr = quirc_new();
	if (!qr) return result;
	if (quirc_resize(qr, w, h) < 0) {
		quirc_destroy(qr);
		return result;
	}
	// quirc_begin 给的就是它内部那块缓冲，一个像素一字节，直接把灰度写进去
	int bufW{ 0 }, bufH{ 0 };
	auto buffer = quirc_begin(qr, &bufW, &bufH);
	const size_t count = (size_t)w * h;
	for (size_t i = 0; i < count; i++) {
		auto px = data + i * 4; //入参是 BGRA
		buffer[i] = (uint8_t)((px[2] * 77 + px[1] * 150 + px[0] * 29) >> 8);
	}
	quirc_end(qr);
	auto codeCount = quirc_count(qr);
	for (int i = 0; i < codeCount; i++) {
		quirc_code code{};
		quirc_data qrData{};
		quirc_extract(qr, i, &code);
		auto err = quirc_decode(&code, &qrData);
		if (err == QUIRC_ERROR_DATA_ECC) {
			// 可能是镜像的码（ISO 18004:2015 允许），翻过来再试一次
			quirc_flip(&code);
			err = quirc_decode(&code, &qrData);
		}
		if (err != QUIRC_SUCCESS) continue;
		auto text = qrPayloadToWStr(qrData.payload, qrData.payload_len, qrData.data_type);
		if (text.empty()) continue;
		if (!result.empty()) result += L"\n";
		result += text;
	}
	quirc_destroy(qr);
	return result;
}

