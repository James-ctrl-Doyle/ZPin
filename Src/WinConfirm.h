#pragma once
#include <include/Ling.h>
#include <functional>
#include <string>

// 自绘的确认框。**不用系统 MessageBox** —— 它的浅色方框、系统字体和那套按钮跟这个程序
// （自绘的圆角卡片、蓝色强调色）完全不搭，而且另有一套 DPI/主题逻辑。这里做成自己的小窗：
// 白底圆角卡片 + 标题 + 正文 + 「取消 / 确定」，配色与字号跟设置页一模一样。
//
// 模态性靠 EnableWindow(owner, FALSE)：确认框开着时底下的窗口不再接收任何输入 ——
// 一是防止用户在确认框还开着的时候又去点别的开关，二是免得点击被底下窗口收走。
class WinConfirm : public Ling::WinBase
{
public:
	// 盖在 owner 窗口正中弹一个确认框：点「确定」执行 onOk，点「取消」或按 ESC 直接收掉。
	// 同一时间只会有一个（再调就把上一个收掉）。
	// ⚠ 名字不叫 show：基类 WinBase 已经有 show()，派生类同名会把它**静默遮蔽**
	// （本项目踩过这个坑）
	static void showAt(Ling::WinBase* owner, const std::wstring& title, const std::wstring& text,
		const std::wstring& okText, std::function<void()> onOk);
	// 退出流程里调：确认框可能正开着等着用户点
	static void dispose();
	static bool isOpen();
private:
	WinConfirm(Ling::WinBase* owner, const std::wstring& title, const std::wstring& text,
		const std::wstring& okText, std::function<void()> onOk);
	~WinConfirm();
	void onCreated() override;
private:
	// ⚠ 只留句柄不留指针：确认框开着的这段时间里，owner（设置窗口）完全可能先被销毁，
	// 指针会悬空；句柄配 IsWindow 判断才是安全的
	HWND ownerHwnd{ nullptr };
	std::wstring title, text, okText;
	std::function<void()> onOk;
	// close() 可能被走到两次（showAt 收掉上一个时，它可能自己也在关），
	// 靠它保证收尾动作（把输入和活动窗口还给设置页）只执行一次
	bool isClosed{ false };
	// 当前开着的那一个（只为"来新的先把旧的收掉"和退出时收尾服务）
	static WinConfirm* cur;
};
