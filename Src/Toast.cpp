#include "pch.h"
#include "Toast.h"

Toast* Toast::cur{ nullptr };

// 窗口尺寸要在 createNativeWindow 之前定下来，所以先把文字量一遍
Toast::Toast(const std::wstring& text, int cx, int cy, float dpi, UINT showMs)
	: Ling::WinBase(), text(text)
{
	cur = this;
	this->dpi = dpi;

	float textW{ 0.f }, textH{ 0.f };
	auto layout = Ling::D2D::get()->makeTextLayout(text, 13.f * dpi);
	DWRITE_TEXT_METRICS tm{};
	if (layout && SUCCEEDED(layout->GetMetrics(&tm))) {
		textW = tm.width;
		textH = tm.height;
	}
	auto pad = 8.f * dpi;
	auto boxW = textW + pad * 2;
	auto boxH = textH + pad * 2;
	// setSize 收的是逻辑像素，内部会乘 dpi
	setSize(boxW / dpi, boxH / dpi);
	x = static_cast<int>(cx - boxW / 2.f);
	y = static_cast<int>(cy - boxH / 2.f);

	// 置顶、不在任务栏露面、不抢焦点、鼠标穿透（2 秒里用户可能已经在干别的，别挡着他）
	createNativeWindow(WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE | WS_EX_TRANSPARENT,
		WS_POPUP);

	onDestroy.add([this]() {
		if (cur == this) cur = nullptr;
		// 与 WinCap::onClosed 同一个道理：DestroyWindow 之后是同步走到这里的，
		// 在这里立刻 delete 就是 use-after-free，推迟到下一轮消息循环
		if (auto app = Ling::App::get()) {
			app->dq.TryEnqueue([this]() { delete this; });
		}
	});

	setTimer(showMs, 1);
	onTimer.add([this](UINT id) {
		if (id != 1) return;
		killTimer(1);
		close();     // 走进 onDestroy，由它负责销毁自己
	});
}

Toast::~Toast()
{
}

void Toast::onCreated()
{
	body->setBg(0x1A1A1AF2);
	body->setBorderRadius(4.f);
	body->setAlignItems(Ling::Align::Center);
	body->setJustifyContent(Ling::Justify::Center);
	auto label = body->makeChild<Ling::Label>();
	label->setText(text);
	label->setFontSize(13.f);
	label->setColor(0xFFFFFFFF);
	show();
}

void Toast::showAt(const std::wstring& text, int cx, int cy, float dpi, UINT showMs)
{
	// 上一条立刻收掉：close() 会同步进它的 onDestroy（那里把 cur 置空并延迟销毁）
	if (cur) cur->close();
	new Toast(text, cx, cy, dpi, showMs);   // 构造函数里把 cur 指向自己，之后自己管自己
}
