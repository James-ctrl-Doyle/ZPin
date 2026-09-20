#pragma once
#include <include/Ling.h>
#include <string>

// 独立的一行提示（"已复制二维码内容"之类）：自己就是一个置顶、不吃鼠标的小窗，
// 显示若干毫秒后自己关掉。
//
// 和画在窗口上的 WinCap::showTip 的区别就在这里：**它不依赖任何别的窗口**。
// 截图窗口可以立刻关掉，提示照样在屏幕上飘满 2 秒 —— "扫完码马上退出截图状态、
// 但那句'已复制'还得让人看见"就是这么来的。
class Toast : public Ling::WinBase
{
public:
	// 在屏幕 (cx, cy)（物理像素）处居中显示 text，showMs 毫秒后自己消失。
	// 连着调用只会留下最新一条（上一条立刻关掉）。
	// ⚠ 名字不叫 show：基类 WinBase 已经有个 show()，同名会把它**静默遮蔽**
	// （本项目踩过这个坑：派生类声明与基类同名的成员，编译器不报错、行为却变了）。
	static void showAt(const std::wstring& text, int cx, int cy, float dpi, UINT showMs = 2000);
private:
	Toast(const std::wstring& text, int cx, int cy, float dpi, UINT showMs);
	~Toast();
	void onCreated() override;
private:
	std::wstring text;
	// 当前还在显示的那一条。只为"来新的时候把旧的收掉"服务
	static Toast* cur;
};
