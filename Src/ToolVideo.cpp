#include "pch.h"
#include "WinCap.h"
#include "Util.h"
#include "Lang.h"
#include "Tip.h"
#include "ToolVideo.h"
#include "ToolHost.h"

void ToolVideo::raiseSelf()
{
	ToolHost::raiseTopmost(hwnd);
	if (tip) ToolHost::raiseTopmost(tip->hwnd());
}

ToolVideo::ToolVideo(WinCap* win) : Ling::WinBase(), win(win)
{
	// 跟着宿主窗口的缩放走：WinBase 构造里取的是系统 dpi，宿主可能在另一块缩放比例不同的屏上
	dpi = win->dpi;
	// 位置由 CapVideo::makeTool() 在 createNativeWindow 之前设好，这里只算尺寸
	refreshSize();
	// 点按钮会把 ToolVideo 激活，键盘消息进的是它，转发给 WinCap 让 ESC 一致生效
	onKeyDown.add([this](UINT key) { this->win->onKeyDown(key); });
	onTimer.add([this](UINT id) { this->onTimerCB(id); });
	// DPI 变了（工具条被挪到缩放比例不同的显示器上，或者用户改了系统缩放）：
	// Ling 只会把窗口按系统给的建议矩形整体缩放一遍，我们自己定的那套摆放规则不会重跑，
	// 工具条就歪在别处了。位置也不能在 onDpiChanged 里直接改 —— 那个事件在 Ling 应用建议矩形
	// 之前触发，改了马上被覆盖，所以这里只记个标记，等建议矩形应用后紧随而来的 WM_SIZE 再动手
	onDpiChanged.add([this]() { dpiChanged = true; });
	onSizeChanged.add([this]() {
		if (!dpiChanged) return;
		dpiChanged = false;
		refreshSize();                    //宿主的摆放规则要用宽高，先按新 dpi 把尺寸定下来
		this->win->layoutTool(this);
	});
}

void ToolVideo::refreshSize()
{
	setSize(isRecording ? recordingWidth() : settingWidth(), btnSize);
}

ToolVideo::~ToolVideo()
{
}

void ToolVideo::onCreated()
{
	tip = std::make_unique<Tip>(this);
	// 提示气泡是独立顶层窗口，本窗口被摘出屏幕捕获它不跟着走，得单独说一声
	tip->excludeFromCapture();
	body->setBg(0xFFFFFFFF);
	body->setBorder(1.f, 0xA8A8A8ff);
	body->setAlignItems(Ling::Align::Center);
	body->setFlexDirection(Ling::FlexDirection::Row);
	showSetting();
	show();
}

void ToolVideo::onMinMaxInfo(MINMAXINFO* mmi)
{
	mmi->ptMinTrackSize.x = 1;
	mmi->ptMinTrackSize.y = 1;
}

float ToolVideo::settingWidth() const
{
	// 系统声/麦克风 + 分隔符 + 开始/退出
	return spliterW + btnSize * 4;
}

float ToolVideo::recordingWidth() const
{
	// 左右内边距 + 计时 + 分隔符 + 丢弃/保存
	return timerW + spliterW + btnSize * 2;
}

Ling::Node* ToolVideo::makeSpliter()
{
	auto spliter = body->makeChild<Ling::Node>();
	spliter->setSize(spliterW, 18.f);
	spliter->setBg(0xDDDDDDff);
	return spliter;
}

Ling::Button* ToolVideo::makeIconBtn(const std::wstring& code)
{
	auto btn = body->makeChild<Ling::Button>();
	btn->setText(code);
	btn->setWidth(btnSize);
	btn->setHeightPercent(100.f);
	btn->setHoverBg(0xF2F2F2ff);
	btn->setFontFamily(L"icon");
	btn->setFontSize(13.f);
	return btn;
}

void ToolVideo::applyToggleStyle(Ling::Button* btn, bool selected)
{
	if (selected) {
		btn->setBg(0xe6f4ffff);
		btn->setHoverBg(0xe6f4ffff);
		btn->setColor(0x1677ffff);
		btn->setHoverColor(0x1677ffff);
	}
	else {
		btn->setBg(0);
		btn->setHoverBg(0xF2F2F2ff);
		btn->setColor(0x333333ff);
		btn->setHoverColor(0x333333ff);
	}
}

void ToolVideo::showSetting()
{
	// 重建前先把旧指针作废：removeAllChildren 会连带销毁所有子节点
	btnSpeaker = nullptr;
	btnMic = nullptr;
	timerLabel = nullptr;
	// 按钮被销毁时 onLeave 不会触发，提示得手动收掉，否则它会一直挂在屏幕上
	tip->hide();
	body->removeAllChildren();
	setSize(settingWidth(), btnSize);

	btnSpeaker = makeIconBtn(L"\ue654");
	btnSpeaker->onClick.add([this](Ling::Button* btn) {
		selectSpeaker = !selectSpeaker;
		applyToggleStyle(btn, selectSpeaker);
	});
	tip->bind(btnSpeaker, Lang::get(L"video.recordSystem"));
	btnMic = makeIconBtn(L"\ue73b");
	btnMic->onClick.add([this](Ling::Button* btn) {
		selectMic = !selectMic;
		applyToggleStyle(btn, selectMic);
	});
	tip->bind(btnMic, Lang::get(L"video.recordMic"));

	makeSpliter();

	auto btnStart = makeIconBtn(L"\ue660");
	btnStart->onClick.add([this](Ling::Button*) { startRecord(); });
	tip->bind(btnStart, Lang::get(L"video.startRecord"));
	auto btnClose = makeIconBtn(L"\ue62d");
	btnClose->onClick.add([this](Ling::Button*) { this->win->close(); });
	tip->bind(btnClose, Lang::get(L"video.exit"));

	applyToggleStyle(btnSpeaker, selectSpeaker);
	applyToggleStyle(btnMic, selectMic);
	// 尺寸刚变过，位置必须重算：摆放规则是"右边缘对齐选区右边缘"，按旧宽度算出来的
	// X 会让变宽后的工具条向右溢出（见 showRecording 里那条同类注释）
	this->win->layoutTool(this);
	raiseSelf();
}

void ToolVideo::showRecording()
{
	btnSpeaker = nullptr;
	btnMic = nullptr;
	timerLabel = nullptr;
	tip->hide();
	body->removeAllChildren();
	setSize(recordingWidth(), btnSize);

	timerLabel = body->makeChild<Ling::Label>();
	timerLabel->setWidth(timerW);
	timerLabel->setHeightPercent(100.f);
	timerLabel->setAlignItems(Ling::Align::Center);
	timerLabel->setJustifyContent(Ling::Justify::Center);
	updateTimerText();

	makeSpliter();

	// 收尾只有两条路：丢弃 / 保存（用户要求去掉"存剪切板"）。
	// 保存的图标用对勾（U+E6AD）而不是软盘：软盘跟工具条上"保存截图"那个撞脸，
	// 而这里按下去是"就这样，收工"，勾更贴切
	auto btnDiscard = makeIconBtn(L"\ue62d");
	btnDiscard->onClick.add([this](Ling::Button*) { discardRecord(); });
	tip->bind(btnDiscard, Lang::get(L"video.stopExit"));
	auto btnSave = makeIconBtn(L"\ue6ad");
	btnSave->onClick.add([this](Ling::Button*) { saveFile(); });
	tip->bind(btnSave, Lang::get(L"video.stopFile"));
	// ⚠ 从设置态切到录制态宽度会变（计时器比两个音源按钮宽），位置**必须**重算。
	// 摆放规则是"右边缘对齐选区右边缘"（见 WinCap::layoutTool），X 是按当时的宽度算的；
	// 只改尺寸不重摆，工具条就会以左上角为锚点向右长出那么一截。
	// 选区贴着屏幕右边 / 全屏录制时，多出来的那截正好把最右边的"保存"顶到屏幕外 ——
	// 用户看到的就是"一开始还能看见的工具条，点了开始录制之后就没了、也退不出来"。
	this->win->layoutTool(this);
	raiseSelf();
}

void ToolVideo::startRecord()
{
	isRecording = true;
	totalSeconds = 0;
	showRecording();
	setTimer(1000, tickTimerId);
	win->startMp4(selectSpeaker, selectMic);
}

void ToolVideo::updateTimerText()
{
	if (!timerLabel) return;
	// 上限 120 分钟
	constexpr int maxMinutes = 120;
	timerLabel->setText(std::format(L"{:02d}:{:02d} / {:02d}:00", totalSeconds / 60, totalSeconds % 60, maxMinutes));
}

void ToolVideo::onTimerCB(UINT id)
{
	if (id != tickTimerId) return;
	totalSeconds += 1;
	updateTimerText();
	// 每秒顺手把自己顶回最上面：录制途中只要有谁（覆盖层被激活、别的程序弹窗）
	// 把工具条压下去，最多 1 秒就自己回来 —— 不然用户就是"按钮没了、退不出来"
	raiseSelf();
	constexpr int maxSeconds = 120 * 60;
	if (totalSeconds >= maxSeconds) {
		// 到上限就自动存盘收工
		saveFile();
	}
}

void ToolVideo::saveFile()
{
	hide();
	killTimer(tickTimerId);
	auto srcPath = win->stopRecord();
	// 空路径 = 一帧都没录到（刚开录就停了），没什么可存的，别弹保存框去打扰用户
	if (srcPath.empty()) {
		win->close();
		return;
	}
	// 保存位置 / 快速保存统一走 Util：勾了快速保存就直接进默认目录（默认是"下载"），不弹框
	auto tarPath = Util::resolveSavePath(L"mp4");
	bool copied = false;
	if (!tarPath.empty()) {
		copied = CopyFile(srcPath.data(), tarPath.data(), false) != 0;
	}
	// 只有确实写出去了才删临时文件 —— 拷贝失败（没权限、盘满）时留着，
	// 用户还能去数据目录的 temp 下把这段录像捞出来，删了就真没了
	if (copied || tarPath.empty()) {
		DeleteFile(srcPath.data());
	}
	win->close();
}

bool ToolVideo::onSaveKey(bool toClipboard)
{
	if (!isRecording) return false;
	// 录制收尾只剩"保存"一条路（"存剪切板"已按用户要求去掉），所以 Ctrl+C 也当成保存
	(void)toClipboard;
	saveFile();
	return true;
}

void ToolVideo::discardRecord()
{
	hide();
	killTimer(tickTimerId);
	auto srcPath = win->stopRecord();
	// 丢掉这段录制：临时文件也删掉。空路径 = 一帧都没录到，程序已经删过了
	if (!srcPath.empty()) DeleteFile(srcPath.data());
	win->close();
}
