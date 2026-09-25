#pragma once
#include <include/Ling.h>

class Tray
{
public:
	~Tray();
	static void init();
	static Tray* get();
	// 按 common.iconStyle 给托盘换图（启动 / 托盘创建时用）
	static void applyIconStyle();
	// 显式指定风格：true = 简洁版（白 Z 透明底）。设置页切换时用
	static void applyIconStyle(bool simple);
private:
	Tray();
	void onTrayRightClick();
};
