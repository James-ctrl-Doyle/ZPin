#pragma once
#include <include/Ling.h>
class ToolHost;
class Tip;
class ToolMain : public Ling::WinBase
{
public:
	// capTools 为真 = 挂在截图覆盖层上，除绘图按钮外还带"截长图 / 录屏 / 文字识别 / 二维码识别"；
	// 为假 = 挂在贴图窗口上，那几个功能没有意义（图已经贴出来了），不出现
	ToolMain(ToolHost* win, bool capTools = false);
	~ToolMain();
	static void init();
	float getBtnCenterX();
	// 取消当前选中：清空 curId、把所有按钮恢复常态配色，并重排工具组（curId 空了 ToolSub 会隐藏）。
	void cancelSelect();
public:
	std::wstring curId;
private:
	void onCreated() override;
	void onClick(Ling::Button* btn);
	void onMinMaxInfo(MINMAXINFO* mmi);
	// 未选中态配色，选中态在 onClick 里就地设置
	void applyNormalStyle(Ling::Button* btn);
	// 按当前 dpi 把窗口尺寸算出来并应用。构造时算一次，DPI 变了再算一次
	void refreshSize();
	// 按钮的悬停提示取哪条翻译。绘图按钮在 tool.*，截图专属的那几个在 cap.*
	std::wstring tipKey(const std::wstring& id) const;
private:
	ToolHost* win;
	// 见构造函数的注释：为真是挂在截图覆盖层上的那一根
	bool capTools{ false };
	// onDpiChanged 与 onSizeChanged 之间的接力标记，见构造函数里的注释
	bool dpiChanged{ false };
	// 逻辑像素，交给 Ling 的 setter 时由其内部乘 dpi
	static constexpr float btnSize{ 32.f };
	static constexpr float spliterW{ 1.f };
	// 只有截图覆盖层才有的那几个按钮，它们的翻译在 cap.* 而不是 tool.*
	static const std::vector<std::wstring> capOnlyIds;
	// 上面这几个按钮插在第 2 个分隔符之后（绘图 | 撤销重做 | 功能 | 关闭保存复制）
	static constexpr size_t capInsertPos{ 12 };
	// 按钮表在构造函数里按 capTools 拼出来。三张表一一对应，"|" 是分隔符
	std::vector<std::wstring> btnIds;
	std::vector<std::wstring> btnCodes;
	std::vector<Ling::Button*> btns;
	// 悬停提示。要 hwnd，所以在 onCreated 里才建得起来
	std::unique_ptr<Tip> tip;
};

