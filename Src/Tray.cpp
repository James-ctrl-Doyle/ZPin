#include "pch.h"
#include "Tray.h"
#include "App.h"
#include "Lang.h"
#include "Win/WinCap.h"
#include "Win/WinPin.h"
#include "Win/WinSetting.h"
#include "Setting.h"

namespace {
	static std::unique_ptr<Tray> trayIns;
	static constexpr UINT settingMsg = 163;
	static constexpr UINT exitMsg = 164;
	static constexpr UINT disableHotkeysMsg = 165;
	// 贴图已按用户要求从托盘菜单去掉（F3 热键和 WinPin::doPin 都还在，只是菜单里不再列）
}

Tray::Tray()
{
	auto lingApp = Ling::App::get();
	lingApp->initTray(100, L"Screen Capture");
	Setting::get()->initShortcutKeys();
	// 左键单击 / 双击 都进入截图
	lingApp->onTrayMouseEvent.add([this](bool isDown, bool isRight) {
		if (isDown && !isRight) {
			WinCap::init();
		}
		else if (isDown && isRight) {
			this->onTrayRightClick();
		}
	});
}

Tray::~Tray()
{
}

void Tray::init()
{
	auto ptr = new Tray();
	trayIns.reset(ptr);
}

Tray* Tray::get()
{
	return trayIns.get();
}

void Tray::onTrayRightClick()
{
	auto menu = CreatePopupMenu();
	AppendMenu(menu, MF_STRING, settingMsg, Lang::get(L"tray.setting").data());
	// 游戏模式：一键注销所有全局热键（F1/F3 等），打游戏不误触；再点一次恢复。
	// 状态用勾选标记 + 存进配置，重启后保持
	const bool disabled = Setting::get()->getDisableHotkeys();
	AppendMenu(menu, MF_STRING | (disabled ? MF_CHECKED : MF_UNCHECKED),
		disableHotkeysMsg, Lang::get(L"tray.disableHotkeys").data());
	AppendMenu(menu, MF_SEPARATOR, 0, nullptr);
	AppendMenu(menu, MF_STRING, exitMsg, Lang::get(L"tray.exit").data());
	auto menuId = Ling::App::get()->popupMenu(menu);
	if (menuId == settingMsg)
	{
		WinSetting::init();
	}
	else if (menuId == disableHotkeysMsg)
	{
		Setting::get()->setDisableHotkeys(!disabled);
	}
	else if (menuId == exitMsg)
	{
		Ling::App::get()->quit(0);
	}
}
