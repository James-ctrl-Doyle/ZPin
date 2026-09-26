#include "pch.h"
#include "Tray.h"
#include "App.h"
#include "Lang.h"
#include "WinCap.h"
#include "WinPin.h"
#include "WinSetting.h"
#include "Setting.h"

namespace {
	static std::unique_ptr<Tray> trayIns;
	static constexpr UINT settingMsg = 163;
	static constexpr UINT exitMsg = 164;
	static constexpr UINT disableHotkeysMsg = 165;
	static constexpr UINT gameModeMsg = 166;
	// 贴图已按用户要求从托盘菜单去掉（F3 热键和 WinPin::doPin 都还在，只是菜单里不再列）
}

Tray::Tray()
{
	auto lingApp = Ling::App::get();
	lingApp->initTray(100, L"Screen Capture");
	applyIconStyle();
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

// 托盘图标按配置换图。资源 ID 与 Resource.rc 对齐：1 = 彩色版、2 = 简洁版（白 Z 透明底）。
// exe 文件本身的图标永远是彩色版（嵌在 PE 里，运行期改不了），这里管的是托盘那一颗。
void Tray::applyIconStyle()
{
	applyIconStyle(Setting::get()->getIconStyle() == L"simple");
}

void Tray::applyIconStyle(bool simple)
{
	Ling::App::get()->setTrayIcon(simple ? 2 : 1);
}

Tray* Tray::get()
{
	return trayIns.get();
}

void Tray::onTrayRightClick()
{
	auto menu = CreatePopupMenu();
	AppendMenu(menu, MF_STRING, settingMsg, Lang::get(L"tray.setting").data());
	// 关闭快捷键：一键注销所有全局热键（F1/F3 等），打游戏不误触；再点一次恢复。
	// **手动**开关 —— 状态用勾选标记 + 存进配置，重启后保持
	const bool disabled = Setting::get()->getDisableHotkeys();
	AppendMenu(menu, MF_STRING | (disabled ? MF_CHECKED : MF_UNCHECKED),
		disableHotkeysMsg, Lang::get(L"tray.disableHotkeys").data());
	// 游戏模式：**自动**版 —— 开着时检测到全屏游戏就自己暂停热键、退出自动恢复。
	// 和上面那条并存：一个是用户手动按住的持久开关，一个是按场景自动进出的，
	// 两者互不覆盖（游戏结束只恢复它自己暂停的那份）。详细判据见 App.cpp 的 GameWatcher
	const bool gameModeOn = Setting::get()->getGameMode();
	AppendMenu(menu, MF_STRING | (gameModeOn ? MF_CHECKED : MF_UNCHECKED),
		gameModeMsg, Lang::get(L"tray.gameMode").data());
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
	else if (menuId == gameModeMsg)
	{
		Setting::get()->setGameMode(!gameModeOn);
	}
	else if (menuId == exitMsg)
	{
		Ling::App::get()->quit(0);
	}
}
