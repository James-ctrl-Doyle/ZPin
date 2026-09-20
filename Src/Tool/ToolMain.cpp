#include "pch.h"
#include "ToolHost.h"
#include "../History.h"
#include "../Lang.h"
#include "../Tip.h"
#include "ToolMain.h"
#include "ToolSub.h"

// 只有截图覆盖层才有的功能按钮。它们的翻译在 cap.* 而不是 tool.*
// （"文字识别"按钮已按用户要求去掉：贴图窗口 F3 后仍会自动识别，功能没丢，只是截图工具条上不再露出来）
const std::vector<std::wstring> ToolMain::capOnlyIds = { L"long", L"video", L"qrcode" };

// 挂在各宿主上的公共那一列。"关闭 / 保存 / 复制"走的是 ToolHost 上共有的
// close() / saveToFile() / copyToClipboard()，所以两个宿主都能用
static const std::vector<std::wstring> baseIds = {
	L"rect",L"ellipse",L"arrow",L"number",L"line",L"text",L"mosaic",L"eraser",
	L"|",L"undo",L"redo",L"|",L"close",L"save",L"clipboard"
};
static const std::vector<std::wstring> baseCodes = {
	L"\ue8e8",L"\ue6bc",L"\ue603",L"\ue776",L"\ue601",L"\ue6ec",L"\ue82e",L"\ue6be",
	L"|",L"\ued85",L"\ued8a",L"|",L"\ue62d",L"\ue608",L"\ue6ad"
};
// 截长图 / 录屏 / 二维码识别。码点在 iconfont 里都确认过存在（与 capOnlyIds 一一对应）
static const std::vector<std::wstring> capCodes = { L"\ue73e",L"\ue660",L"\ue71e" };

ToolMain::ToolMain(ToolHost* win, bool capTools) : Ling::WinBase(), win(win), capTools(capTools)
{
	btnIds = baseIds;
	btnCodes = baseCodes;
	if (capTools) {
		// 插在第 2 个分隔符之后，得到：绘图 | 撤销重做 | 功能 | 关闭保存复制。
		// 原先"截长图 / 录屏 / 文字识别 / 二维码"是单独一根 ToolCap，两根条摞在选区旁边；
		// 现在并成一根，重复的"关闭 / 保存 / 复制"也只留一份
		btnIds.insert(btnIds.begin() + capInsertPos, capOnlyIds.begin(), capOnlyIds.end());
		btnCodes.insert(btnCodes.begin() + capInsertPos, capCodes.begin(), capCodes.end());
	}
	// 跟着宿主窗口的缩放走：WinBase 构造里取的是系统 dpi，宿主可能在另一块缩放比例不同的屏上
	dpi = win->dpi;
	// 初始位置由 WinPin::layoutTools() 统一决定，这里只算尺寸
	x = win->x;
	y = win->y + win->h + 5.f * win->dpi;
	refreshSize();
	// 点按钮会把 ToolMain 激活，此后键盘消息进的是它而不是 WinPin。
	// 直接把按键转触给 WinPin 的同名事件，快捷键在两个窗口上表现一致。
	onKeyDown.add([this](UINT key) { this->win->onKeyDown(key); });
	// DPI 变了（工具条被挪到缩放比例不同的显示器上，或者用户改了系统缩放）：
	// Ling 只会把窗口按系统给的建议矩形整体缩放一遍，我们自己定的那套摆放规则不会重跑，
	// 工具条就歪在别处了。位置也不能在 onDpiChanged 里直接改 —— 那个事件在 Ling 应用建议矩形
	// 之前触发，改了马上被覆盖，所以这里只记个标记，等建议矩形应用后紧随而来的 WM_SIZE 再动手
	onDpiChanged.add([this]() { dpiChanged = true; });
	onSizeChanged.add([this]() {
		if (!dpiChanged) return;
		dpiChanged = false;
		refreshSize();                    //宿主的摆放规则要用宽高，先按新 dpi 把尺寸定下来
		this->win->layoutTools();
	});
	// 挂在截图覆盖层上时要带 WS_EX_NOACTIVATE：点工具条不该把焦点从宿主那里抢走，
	// 否则键盘消息进了工具条，宿主那套快捷键就得全靠转发。贴图窗口那条不需要 ——
	// 它唤回工具条时本来就是要接收键盘（文本框编辑）
	auto exStyle = capTools ? (WS_EX_TOPMOST | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW)
		: (WS_EX_TOPMOST | WS_EX_TOOLWINDOW);
	createNativeWindow(exStyle, WS_POPUP);
}

// 悬停提示取哪条翻译：截图专属的那几个在 cap.*，其余在 tool.*
std::wstring ToolMain::tipKey(const std::wstring& id) const
{
	for (auto& capId : capOnlyIds) {
		if (id == capId) return std::format(L"cap.{}", id);
	}
	return std::format(L"tool.{}", id);
}

// 宽度 = 各按钮宽度之和（btnIds 里的 "|" 是分隔符，只占 spliterW），高度 = 按钮高
void ToolMain::refreshSize()
{
	float logicW{ 0.f };
	for (auto& id : btnIds) {
		logicW += (id == L"|") ? spliterW : btnSize;
	}
	setSize(logicW, btnSize);
}

ToolMain::~ToolMain()
{
}

void ToolMain::init()
{
}

// 返回 curId 对应按钮的中心相对 ToolMain 左边的偏移（物理像素）。
// btnIds 含分隔符而 btns 不含，所以要单独维护 btns 的下标，不能拿 i 去索引 btns。
float ToolMain::getBtnCenterX()
{
	float result{ 0.f };
	size_t btnIndex{ 0 };
	for (size_t i = 0; i < btnIds.size(); i++)
	{
		if (btnIds[i] == L"|") {
			// 分隔符不在 btns 里，宽度与 onCreated 里 spliter 的 setSize(dpi, ...) 一致
			result += dpi;
			continue;
		}
		if (curId == btnIds[i]) {
			result += btns[btnIndex]->w / 2.f;
			return result;
		}
		result += btns[btnIndex]->w;
		btnIndex++;
	}
	return result;
}

void ToolMain::onCreated()
{
	tip = std::make_unique<Tip>(this);
	body->setBg(0xFFFFFFFF);
	body->setBorder(1.f, 0xA8A8A8ff);
	body->setAlignItems(Ling::Align::Center);
	body->setFlexDirection(Ling::FlexDirection::Row);
	for (size_t i = 0; i < btnIds.size(); i++)
	{
		auto& id = btnIds[i];
		if (id == L"|") {
			auto spliter = body->makeChild<Ling::Node>();
			spliter->setSize(dpi, 18.f);
			spliter->setBg(0xDDDDDDff);
		}
		else {
			auto btn = body->makeChild<Ling::Button>();
			btn->setId(id);
			btn->setText(btnCodes[i]);
			btn->setHeightPercent(100.f);
			btn->setFlexGrow(1.f);
			btn->setHoverBg(0xF2F2F2ff);
			btn->setFontFamily(L"icon");
			btn->setFontSize(13.f);
			btn->onClick.add([this](Ling::Button* btn) {onClick(btn);});
			tip->bind(btn, Lang::get(tipKey(id)));
			btns.push_back(btn);
		}
	}
	show();
}

void ToolMain::applyNormalStyle(Ling::Button* btn)
{
	btn->setBg(0);
	btn->setHoverBg(0xF2F2F2ff);
}

// 取消选中：与 onClick 选中某个按钮是对称操作，只是没有新的选中项。
// ToolSub 由 curId 是否为空驱动，所以清空 curId 后 layoutTools() 会自动把它收起来。
void ToolMain::cancelSelect()
{
	if (curId.empty()) return;
	for (auto b : btns)
	{
		if (b->id == curId) {
			applyNormalStyle(b);
		}
	}
	curId.clear();
	win->toolSub->hideTools();
	// curId 空了 ToolMain 要下移收回 ToolSub 让出的空间，交给 WinPin 重排整组
	win->layoutTools();
}

void ToolMain::onClick(Ling::Button* btn)
{
	// 关闭整个宿主窗口。宿主的 onDestroy 里会连带关掉 ToolMain / ToolSub，
	// 但 C++ 对象的释放被推迟到下一轮消息循环，所以这里 return 之后栈上访问 this 仍是安全的。
	if (btn->id == L"close") {
		win->close();
		return;
	}
	// 下面这几个都是"执行一次动作"而不是"切换绘图工具"，做完就返回，不动 curId 和选中态。
	// undo/redo 由 History 内部负责 refresh；save/clipboard 成功后会关窗，同样不能往下走。
	else if (btn->id == L"undo") {
		win->history->undo();
		return;
	}
	else if (btn->id == L"redo") {
		win->history->redo();
		return;
	}
	else if (btn->id == L"save") {
		win->saveToFile();
		return;
	}
	else if (btn->id == L"clipboard") {
		win->copyToClipboard();
		return;
	}
	// 截图专属的功能按钮（截长图 / 录屏 / 文字识别 / 二维码）：只有截图覆盖层那根条上有，
	// 转给宿主去做。它们不是"画笔"，不进下面的选中流程 —— 否则会把自己当成当前工具
	for (auto& capId : capOnlyIds) {
		if (btn->id == capId) {
			win->onCapAction(capId);
			return;
		}
	}
	// 再次点击已选中的按钮 = 取消选中（开关式）。cancelSelect 里已经做了配色复位、
	// 隐藏 ToolSub 和重排，这里直接返回，不要再往下走选中流程。
	if (btn->id == curId) {
		cancelSelect();
		return;
	}
	for (auto b:btns)
	{
		if (b->id == curId)
		{
			applyNormalStyle(b);
		}
		if (b->id == btn->id)
		{
			b->setBg(0xe6f4ffff);
			b->setHoverBg(0xe6f4ffff);
		}
	}
	curId = btn->id;
	if (curId == L"rect") {
		win->toolSub->showRectTools();
	}
	else if (curId == L"ellipse") {
		win->toolSub->showEllipseTools();
	}
	else if (curId == L"arrow") {
		win->toolSub->showArrowTools();
	}
	else if (curId == L"number") {
		win->toolSub->showNumberTools();
	}
	else if (curId == L"line") {
		win->toolSub->showLineTools();
	}
	else if (curId == L"text") {
		win->toolSub->showTextTools();
	}
	else if (curId == L"mosaic") {
		win->toolSub->showMosaicTools();
	}
	else if (curId == L"eraser") {
		win->toolSub->showEraserTools();
	}
	else {
		win->toolSub->hideTools();
	}
	// curId 变化后 ToolMain 可能要上移给 ToolSub 腾位置，交给 WinPin 重新排布整组
	win->layoutTools();
}

void ToolMain::onMinMaxInfo(MINMAXINFO* mmi)
{
	mmi->ptMinTrackSize.x = 1;
	mmi->ptMinTrackSize.y = 1;
}