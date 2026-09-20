#pragma once
#include <include/Ling.h>

// 自动升级 —— 已停用（见 Update.cpp 顶部说明）。
// 保留这个类只为让调用点（App.cpp / WinCap.cpp / WinPin.cpp）不必改动：
// 每次回到"只剩托盘图标待命"的状态时会调一次 checkLater()，现在它什么也不做。
// 配置里的 common.updateCheckDay 键现已无人读写，属于历史残留，不影响使用。
class Update
{
public:
	// 每次回到空闲状态都会调。当前是空实现，多调无害
	static void checkLater();
};
