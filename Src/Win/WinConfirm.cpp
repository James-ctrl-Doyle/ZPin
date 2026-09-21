#include "pch.h"
#include "WinConfirm.h"
#include "../Lang.h"

WinConfirm* WinConfirm::cur{ nullptr };

namespace
{
	// 版面（逻辑像素）。跟设置页保持同一套观感：白卡片、10 圆角、蓝色强调
	constexpr float padX{ 22.f }, padY{ 20.f };
	constexpr float titleFont{ 15.f }, textFont{ 13.f };
	constexpr float gapTitle{ 12.f }, gapBtn{ 18.f };
	constexpr float btnW{ 88.f }, btnH{ 32.f }, btnGap{ 10.f };
	// ⚠ 名字别叫 minW / maxW：WinBase 有同名成员（`float w, h, minW{800}, minH{600}`），
	// 在本类的成员函数里裸写 minW 会解析成**基类那个成员**而不是这里的常量。
	// 踩过：clamp(contentW, minW*dpi, maxW*dpi) 实际变成 clamp(x, 800*dpi, 520*dpi)，
	// 下界比上界还大 → 宽度被钉死在 991.7，弹框一直宽得离谱
	constexpr float cardMinW{ 340.f }, cardMaxW{ 520.f };
}

WinConfirm::WinConfirm(Ling::WinBase* owner, const std::wstring& title, const std::wstring& text,
	const std::wstring& okText, std::function<void()> onOk)
	: Ling::WinBase(), ownerHwnd(owner ? owner->hwnd : nullptr),
	title(title), text(text), okText(okText), onOk(std::move(onOk))
{
	cur = this;
	if (owner) this->dpi = owner->dpi;
	// 窗口标题给它自己（窗口本身是无边框的，标题看不见）—— 自动化测试靠它把这个框
	// 从一堆 Ling 窗口里认出来
	setTitle(title);

	// 尺寸必须赶在 createNativeWindow 之前定下来 —— 先按字号把两段文字量一遍。
	// 正文里的换行是在语言文件里手工排好的（Label 没有"给个宽度自动折行"的能力），
	// 所以这里量出来的最宽行宽就直接是卡片内容宽度
	auto measure = [&](const std::wstring& s, float fontSize) {
		D2D1_SIZE_F size{ 0.f, 0.f };
		auto layout = Ling::D2D::get()->makeTextLayout(s, fontSize * dpi);
		DWRITE_TEXT_METRICS tm{};
		if (layout && SUCCEEDED(layout->GetMetrics(&tm))) {
			size.width = tm.width;
			size.height = tm.height;
		}
		return size;
	};
	const auto titleSize = measure(title, titleFont);
	const auto textSize = measure(text, textFont);

	float contentW = (std::max)({ titleSize.width, textSize.width, (btnW * 2.f + btnGap) * dpi });
	contentW = std::clamp(contentW, cardMinW * dpi, cardMaxW * dpi);
	const float contentH = titleSize.height + gapTitle * dpi + textSize.height
		+ gapBtn * dpi + btnH * dpi;
	const float w = contentW + padX * 2.f * dpi;
	const float h = contentH + padY * 2.f * dpi;
	setSize(w / dpi, h / dpi);       // setSize 收逻辑像素，内部乘 dpi

	if (owner) {
		x = owner->x + static_cast<int>((owner->w - w) / 2.f);
		y = owner->y + static_cast<int>((owner->h - h) / 2.f);
	}
	else {
		x = static_cast<int>((GetSystemMetrics(SM_CXSCREEN) - w) / 2.f);
		y = static_cast<int>((GetSystemMetrics(SM_CYSCREEN) - h) / 2.f);
	}
	createNativeWindow(WS_EX_TOPMOST | WS_EX_TOOLWINDOW, WS_POPUP);
	// 模态：把 owner 的输入关掉（见头文件里的说明）
	if (ownerHwnd && IsWindow(ownerHwnd)) EnableWindow(ownerHwnd, FALSE);
	// 拿到活动窗口，这样 ESC 能收到。这里用 SetActiveWindow 而不是 SetForegroundWindow ——
	// 同一个进程内的活动窗口切换不需要前台权限，而 SetForegroundWindow 会被系统的
	// "前台锁"（foreground lock timeout）挡掉，那就白叫了
	SetActiveWindow(hwnd);

	onKeyDown.add([this](UINT key) {
		if (key == VK_ESCAPE) close();
	});
	onDestroy.add([this]() {
		if (isClosed) return;
		isClosed = true;
		if (cur == this) cur = nullptr;
		// 输入与活动窗口都还给设置页（都是被我们拿走的）；它可能已经不在了，所以要判 IsWindow。
		// ⚠ 活动窗口必须显式还回去：不给的话下一次点设置页上的开关会被系统当成
		// "点击以激活窗口"吃掉，用户得点两次才生效（实测就是这个症状）
		if (ownerHwnd && IsWindow(ownerHwnd)) {
			EnableWindow(ownerHwnd, TRUE);
			SetActiveWindow(ownerHwnd);
		}
		// 与 WinCap::onClosed / Toast 同一个道理：DestroyWindow 之后是同步走到这里的，
		// 在这里立刻 delete 就是 use-after-free，推迟到下一轮消息循环
		if (auto app = Ling::App::get()) {
			app->dq.TryEnqueue([this]() { delete this; });
		}
	});
}

WinConfirm::~WinConfirm()
{
}

void WinConfirm::onCreated()
{
	body->setBg(0xFFFFFFFF);
	body->setBorderRadius(10.f);
	body->setBorder(1.f, 0xE6E6E6FF);
	body->setPadding(padX, padY, padX, padY);
	body->setFlexDirection(Ling::FlexDirection::Column);

	auto titleLabel = body->makeChild<Ling::Label>();
	titleLabel->setText(title);
	titleLabel->setFontSize(titleFont);
	titleLabel->setColor(0x1A1A1AFF);

	auto textLabel = body->makeChild<Ling::Label>();
	textLabel->setText(text);
	textLabel->setFontSize(textFont);
	textLabel->setColor(0x555555FF);
	textLabel->setMarginTop(gapTitle);

	// 按钮行：整行占满、内容右对齐
	auto row = body->makeChild<Ling::Node>();
	row->setWidthPercent(100.f);
	row->setFlexDirection(Ling::FlexDirection::Row);
	row->setJustifyContent(Ling::Justify::End);
	row->setMarginTop(gapBtn);

	auto cancel = row->makeChild<Ling::Button>();
	cancel->setText(Lang::get(L"setting.cancel"));
	cancel->setSize(btnW, btnH);
	cancel->setFontSize(13.f);
	cancel->setBorderRadius(6.f);
	cancel->setBg(0xF2F2F2FF);
	cancel->setColor(0x333333FF);
	cancel->setHoverBg(0xE8E8E8FF);
	cancel->onClick.add([this](Ling::Button*) { close(); });

	auto okBtn = row->makeChild<Ling::Button>();
	okBtn->setText(okText);
	okBtn->setSize(btnW, btnH);
	okBtn->setFontSize(13.f);
	okBtn->setMarginLeft(btnGap);
	okBtn->setBorderRadius(6.f);
	okBtn->setBg(0x597ef7FF);
	okBtn->setColor(0xFFFFFFFF);
	okBtn->setHoverBg(0x3D6BE8FF);
	okBtn->onClick.add([this](Ling::Button*) {
		// 先把回调拷出来、再收掉自己：回调做的往往是"重启 / 退出程序"，
		// 而且 close() 之后本对象就交给 onDestroy 去销毁了，回调里不能再碰 this
		auto cb = onOk;
		close();
		if (cb) cb();
	});

	show();
}

void WinConfirm::showAt(Ling::WinBase* owner, const std::wstring& title, const std::wstring& text,
	const std::wstring& okText, std::function<void()> onOk)
{
	// 上一个还在就直接收掉：close() 会同步进它的 onDestroy（把 cur 置空并延迟销毁）
	if (cur) cur->close();
	new WinConfirm(owner, title, text, okText, std::move(onOk));
}

void WinConfirm::dispose()
{
	if (cur) cur->close();
}

bool WinConfirm::isOpen()
{
	return cur != nullptr;
}
