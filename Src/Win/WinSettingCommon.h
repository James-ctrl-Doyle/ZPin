#pragma once
#include <include/Ling.h>
class WinSettingCommon:public Ling::Node
{
public:
	WinSettingCommon(Ling::WinBase* parent);
	~WinSettingCommon();
	// 收掉语言下拉框。它挂在 win->body 上而不是挂在本节点里，所以本节点被换掉 / 销毁时
	// 它不会跟着走，得由外面在合适的时机显式收掉
	void hideSelectBox();
private:
	void initAutoStartCtrls();
	void initLangCtrls();
	// 默认保存位置（选文件夹）+ 快速保存开关
	void initSaveCtrls();
	// 截图历史保留天数
	void initHistoryCtrl();
	void updateSaveDirLabel();
	void updateHistoryLabel();
	void setQuickSaveBtn(Ling::Button* btn);
	// 截图选区边框的粗细（0 = 不画边框）
	void initBorderCtrl();
	void updateBorderLabel();
	void setAutoStartBtn(Ling::Button* btn);
	void showSelectBox(Ling::Button* btn);
private:
	Ling::Button* selectBtn{ nullptr };
	// 显示当前保存目录的按钮（点它选新目录）
	Ling::Button* saveDirBtn{ nullptr };
	// "截图历史保留 N 天"那行的标签
	Ling::Label* historyLabel{ nullptr };
	Ling::ScrollerBox* selectBox{ nullptr };
	Ling::Label* borderLabel{ nullptr };
	winrt::event_token onMouseDownToken;
};

