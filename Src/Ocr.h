#pragma once
#include <include/Ling.h>
// DispatcherQueue 是异步结果回投的落点（见 recognize），这里显式带上免得依赖 Ling 的间接包含
#include <winrt/Windows.System.h>
#include <functional>
#include <memory>
#include <string>
#include <vector>

// 识别出来的一个词。注意 Windows.Media.Ocr 对中文是按**单字**切词的
//（"文字识别" 会返回 文 / 字 / 识 / 别 四个"词"），正好对上"选中字符"这个用法。
// rect 是相对**底图原始像素**的坐标 —— 不是归一化值，也不是窗口坐标。
// 引擎返回的是相对"它收到的那张位图"的像素矩形，中间做过缩放的话在 Ocr.cpp 里已经换算回来
struct OcrWord
{
	std::wstring text;
	float left{}, top{}, right{}, bottom{};

	float centerX() const { return (left + right) * 0.5f; }
	float centerY() const { return (top + bottom) * 0.5f; }
	bool contains(float x, float y) const
	{
		return x >= left && x <= right && y >= top && y <= bottom;
	}
	// 与给定矩形有没有交叠。拖框选字用的是交叠而不是"中心点落在框内"：
	// 用户拖框时习惯把整段文字圈住，交叠更符合直觉
	bool overlaps(float l, float t, float r, float b) const
	{
		return !(right < l || left > r || bottom < t || top > b);
	}
};

// 识别结果。所有词按**阅读顺序**展平成一张表（就是引擎给的 行→词 两层的顺序），
// 选中态记的就是这张表上的下标；每行在表里的起点存在 lineStarts 里，
// 末尾多一个哨兵，这样拼接文本时不必再去翻两层的结构
struct OcrPage
{
	std::vector<OcrWord> words;
	std::vector<int> lineStarts;

	bool empty() const { return words.empty(); }
	int count() const { return (int)words.size(); }
	// picked 是升序的下标表，按行拼成文本（行间换行），行内按中英文规则补空格
	std::wstring textOf(const std::vector<int>& picked) const;
};

// Windows.Media.Ocr 的封装。识别能力来自系统自带的 OCR 引擎 ——
// 在「设置 → 时间和语言 → 语言和区域」里给某个语言装上"光学字符识别"即可，
// 本机实测装的是 zh-Hans-CN。不依赖任何第三方库，所以主程序体积不变
class Ocr
{
public:
	// 系统里有没有可用引擎。lang 收引擎实际使用的语言名（没有引擎时置空）
	static bool available(std::wstring* lang = nullptr);
	// 异步识别，立刻返回。pixels 要求 BGRA、top-down、行紧凑（步长 = w*4），
	// 与 Util::captureScreen / WinPin::getImagePixels 的输出格式一致。
	// done 会被调度回 dq 所属的线程（也就是 UI 线程）；没有可用引擎、图像异常或
	// 识别抛异常时 page 为空 —— 调用方必须处理空结果，别假设一定有文字
	static void recognize(int w, int h, std::vector<BYTE> pixels,
		winrt::Windows::System::DispatcherQueue const& dq,
		std::function<void(std::shared_ptr<OcrPage>)> done);
};
