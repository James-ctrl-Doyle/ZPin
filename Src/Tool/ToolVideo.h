#pragma once
#include <include/Ling.h>

class WinCap;
class Tip;
// 录屏工具条。两种形态，切换时把 body 的子节点整批重建（同 ToolSub 的做法）：
//   未录制：系统声 / 麦克风开关 + 开始录制 + 退出
//   录制中：计时文字 + 丢弃 / 存文件 / 存剪切板
// 只输出 MP4，所以没有格式选择那一组 —— 原先的 MP4 / GIF 二选一随 GIF 一起去掉了
class ToolVideo : public Ling::WinBase
{
public:
	ToolVideo(WinCap* win);
	~ToolVideo();
	// Ctrl+S / Ctrl+C 从 WinCap 转进来，等价于录制中那两个按钮。
	// 没在录制（还停在设置形态）时没东西可存，返回 false
	bool onSaveKey(bool toClipboard);
private:
	void onCreated() override;
	void onMinMaxInfo(MINMAXINFO* mmi) override;
	void showSetting();
	void showRecording();
	void onTimerCB(UINT id);
	void startRecord();
	// 停止录制并保存到"保存位置"（勾了快速保存就直接落盘，否则弹另存为）；计时到上限时也走这里
	void saveFile();
	// 丢掉这段录制：停录、删临时文件、关掉整个流程
	void discardRecord();
	// 把自己（连同悬停提示）顶到 topmost 带最上面。全屏覆盖层一被激活就会被系统提到
	// 这一带最上面，把这根同样是 topmost 的工具条整个盖住 —— 用户看到的就是
	// "点完录屏按钮全没了、也退不出来"。形态切换和每秒计时都顺手顶一遍
	void raiseSelf();
	void updateTimerText();
	// 选中/未选中两套配色，与 ToolSub、ToolMain 的选中效果保持一致
	void applyToggleStyle(Ling::Button* btn, bool selected);
	Ling::Button* makeIconBtn(const std::wstring& code);
	Ling::Node* makeSpliter();
	float settingWidth() const;
	float recordingWidth() const;
	// 按当前 dpi 与当前形态（未录制 / 录制中）把窗口尺寸算出来并应用
	void refreshSize();
private:
	WinCap* win;
	// onDpiChanged 与 onSizeChanged 之间的接力标记，见构造函数里的注释
	bool dpiChanged{ false };

	std::unique_ptr<Tip> tip;
	Ling::Button* btnSpeaker{ nullptr };
	Ling::Button* btnMic{ nullptr };
	Ling::Label* timerLabel{ nullptr };
	int totalSeconds{ 0 };
	bool selectSpeaker{ true }, selectMic{ false }, isRecording{ false };
	// 以下都是逻辑像素，交给 Ling 的 setter 时由其内部乘 dpi
	static constexpr float btnSize{ 32.f };
	static constexpr float timerW{ 112.f };
	static constexpr float spliterW{ 1.f };
	static constexpr UINT tickTimerId{ 100 };
};
