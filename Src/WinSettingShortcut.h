#pragma once
#include <include/Ling.h>
class WinSettingShortcut :public Ling::Node
{
public:
	WinSettingShortcut(Ling::WinBase* parent);
	~WinSettingShortcut();
private:
	void onBtnClick(Ling::Button* btn);
	void beginCapture(Ling::Button* btn);
	// 结束捕获：把按钮文字刷回这一项实际生效的组合（可能被清空了）
	void endCapture();
	void onKeyDown(UINT key);
	void onKeyUp(UINT key);
	std::wstring keyToStr(UINT vkCode);
	// 按钮上该显示的文字：这一项实际生效的组合，没有就显示"未设置"
	std::wstring btnText(const std::wstring& type);
	// 有没有别的功能已经占着这个组合。占着就返回它的 type，没有返回空串
	std::wstring conflictingType(const std::wstring& self, const std::wstring& shortcut);
	// 底部那行提示：冲突、组合无效一类需要让用户知道的事都写在这里，传空串即清掉
	void setStatus(const std::wstring& text);
private:
	std::vector<Ling::Button*> btns;
	std::wstring curKey;
	winrt::event_token onMouseDownToken, onKeyDownToken, onKeyUpToken;
	std::vector<std::wstring> tempKeys;
	// 捕获期间按了 Delete / Backspace = 要清掉这一项的热键，等按键松手时执行
	bool clearRequested{ false };
	// 页面底部的提示行：显示冲突之类需要用户知道的信息
	Ling::Label* status{ nullptr };
};
