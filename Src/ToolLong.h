#pragma once
#include <include/Ling.h>

class WinCap;
class Tip;
class ToolLong : public Ling::WinBase
{
public:
	ToolLong(WinCap* win);
	~ToolLong();
private:
	void onCreated() override;
	void onClick(Ling::Button* btn);
	void onMinMaxInfo(MINMAXINFO* mmi) override;
	// 按当前 dpi 把窗口尺寸算出来并应用。构造时算一次，DPI 变了再算一次
	void refreshSize();
private:
	WinCap* win;
	// onDpiChanged 与 onSizeChanged 之间的接力标记，见构造函数里的注释
	bool dpiChanged{ false };
	// 逻辑像素，交给 Ling 的 setter 时由其内部乘 dpi
	static constexpr float btnSize{ 32.f };
	// 收尾与录屏同一套（用户要求去掉"存剪贴板"）：贴图 / 丢弃(✕) / 保存(✓，对勾 U+E6AD
	// 而不是软盘——软盘跟截图工具条上"保存"那个撞脸，按下去是"就这样，收工"）
	std::vector<std::wstring> btnIds = { L"pin",L"close",L"save" };
	std::vector<std::wstring> btnCodes = { L"\ue6a2",L"\ue62d",L"\ue6ad" };
	// 悬停提示。要 hwnd，所以在 onCreated 里才建得起来
	std::unique_ptr<Tip> tip;
};
