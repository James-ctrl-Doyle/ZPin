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
  	// 管理员模式：显示当前状态，非管理员时可一键以管理员身份重启
  	// （任务管理器这类管理员窗口，普通权限的进程截不了）
  	void initAdminCtrls();
	void updateSaveDirLabel();
	void updateHistoryLabel();
	void setQuickSaveBtn(Ling::Button* btn);
	// 截图选区边框的粗细（0 = 不画边框）
	void initBorderCtrl();
	void updateBorderLabel();
	void setAutoStartBtn(Ling::Button* btn);
	// ———— 三个开关（管理员模式 / 开机自启 / 快速保存）共用的一小套东西 ————
	// 行里那个开关样式的按钮。原来它们是只有图标的小按钮，状态全靠图标形状猜，
	// 用户根本看不出是什么；统一成"文字显示当前状态、点一下切换"
	Ling::Button* makeOnOffBtn(Ling::Node* row);
	// 按开/关上色与文案（关的文案统一是 setting.toggleOff，开的那句各行的说法不同）
	void styleToggle(Ling::Button* btn, bool on, const std::wstring& onText);
	// 把自己重新拉起来：elevate = true 走 runas（管理员），false 用 explorer 的令牌起
	// 一个普通权限实例（提权进程造不出普通权限的子进程，见实现里的注释）。
	// 静态：它不依赖本节点状态，而"用户在确认框里点确定之后才执行"是异步的 ——
	// 那一刻本节点可能已经不在了（设置页切了标签、或者程序正在退出）
	static bool relaunchSelf(bool elevate);
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

