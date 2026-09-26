#include "pch.h"
#include "ToolMain.h"
#include "ToolSub.h"
#include "ShapeBase.h"
#include "ShapeText.h"
#include "WinPin.h"
#include "WinCap.h"
#include "History.h"
#include "App.h"
#include "Lang.h"
#include "Util.h"
#include "Update.h"

using namespace Microsoft::WRL;
namespace {
	std::vector<std::unique_ptr<WinPin>> winPins;

	int clampPos(float val, float size, int min, int max)
	{
		auto upper = max - static_cast<int>(size);
		if (upper < min) upper = min;
		auto result = static_cast<int>(val);
		if (result < min) result = min;
		if (result > upper) result = upper;
		return result;
	}
}

WinPin::WinPin(int x, int y, int w, int h, const std::vector<BYTE>* data, float initScale)
	: ToolHost()
{
	// history 由基类 ToolHost 的构造函数建（两个宿主共用一处），这里不用再管
	this->x = x;
	this->y = y;
	if (data) {
		// 外部像素建底图。ShapeMosaic / ShapeEraser 会把它当画刷源，属性与 getCutImg() 出来的保持一致
		D2D1_BITMAP_PROPERTIES1 props{};
		props.pixelFormat = D2D1::PixelFormat(DXGI_FORMAT_B8G8R8A8_UNORM, D2D1_ALPHA_MODE_PREMULTIPLIED);
		props.bitmapOptions = D2D1_BITMAP_OPTIONS_NONE;
		props.dpiX = 96.0f;
		props.dpiY = 96.0f;
		Ling::D2D::get()->deviceContext->CreateBitmap(D2D1::SizeU(w, h), data->data(), w * 4, &props, screenImg.GetAddressOf());
	}
	// 窗口尺寸 = 底图像素 × 倍数，不照抄入参的 w / h —— 入参给的是底图尺寸，
	// initScale < 1 时两者不是一回事。底图仍旧是原始分辨率，所以倍数只影响窗口大小、
	// 不影响导出：贴一张比屏幕还大的图时靠它把整张图放进工作区
	if (initScale > 0.f && initScale < 1.f) scale = (std::max)(0.1f, initScale);
	auto imgSize = getImgSize();
	if (imgSize.width && imgSize.height) {
		this->w = (float)std::max(1, static_cast<int>(std::lround(imgSize.width * scale)));
		this->h = (float)std::max(1, static_cast<int>(std::lround(imgSize.height * scale)));
	}
	else {
		this->w = (float)w;
		this->h = (float)h;
	}
	// 绘图工具条也建出来，但默认是收起的（见 onCreated 里的 hideTools）：
	// 贴图窗口的常态是"只有一张图"，右键才把工具条唤回来接着改
	toolMain = std::make_unique<ToolMain>(this);
	toolSub = std::make_unique<ToolSub>(this);
	onMoved.add([this]() { layoutTools(); });
	// DPI 变了（用户改了缩放比例，或者窗口被拖到缩放比例不同的显示器上）：系统会按新旧缩放比
	// 把窗口整体放大一圈，但贴图窗口的尺寸是钉死在底图像素上的 —— 底图按原始像素画，
	// shape 的坐标也都是相对底图的物理像素，跟着缩放只会让窗口比图大一圈：
	// 右边、下边多出一条空白，边框看着比左上两边粗（描边居中，左上那半截被窗口边裁掉了），
	// 工具条也会按虚高的宽高往右下偏。所以等系统把建议矩形应用完（紧随而来的 WM_SIZE）
	// 再把尺寸掰回底图大小，并重排工具条。位置不能在 onDpiChanged 里改 ——
	// 那个事件在系统建议矩形生效之前触发，改了马上被覆盖
	onDpiChanged.add([this]() { dpiChanged = true; });
	onSizeChanged.add([this]() {
		if (!dpiChanged) return;
		dpiChanged = false;
		applyWinSize();
		layoutTools();
	});
	onMouseDown.add([this](POINT pos, BOOL isRight) {this->onDown(pos, isRight);});
	onMouseMove.add([this](POINT pos) {this->onMove(pos);});
	onMouseUp.add([this](POINT pos, BOOL isRight) {this->onUp(pos, isRight);});
	// 滚轮就是缩放：鼠标停在贴图上滚一下就能放大缩小，不需要按 Ctrl。
	// Ling 传进来的是已经换算成滚动距离的 space（一格 = 60 逻辑像素 × dpi），这里只看方向。
	// 一格 10%，按当前倍数等比走，放大和缩小的手感才对称
	onMouseWheel.add([this](POINT pos, float space) {
		applyScale(scale * (space > 0 ? 1.1f : 1.f / 1.1f), pos);
	});
	onTimer.add([this](UINT id) {this->onTimerCB(id);});
	onKeyDown.add([this](UINT key) {this->onKey(key);});
	onDestroy.add([this]() { this->onClosed(); });
}

// WinBase::close() 里 DestroyWindow 之后同步触发 onDestroy，所以这个函数很可能是从
// ToolMain 的按钮回调里一路调进来的（点了 close 按钮）。此时 ToolMain::onClick 还在栈上，
// 而 toolMain 是 WinPin 的成员 —— 在这里直接把自己从 winPins 里擦掉就是 use-after-free。
// 因此：窗口句柄立即销毁（用户马上看到界面消失），C++ 对象的释放推迟到下一轮消息循环。
void WinPin::onClosed()
{
	// 防止 close() 被走两遍（比如按钮和快捷键先后触发）时排两次销毁
	if (isClosed) return;
	isClosed = true;
	if (editingText) editingText->finishEdit();
	// 先收起附属窗口，再让出 hover 指针 —— shapeHover 指向 history 里的元素，
	// history 随 WinPin 一起析构，留着悬空指针没意义
	if (toolSub) toolSub->close();
	if (toolMain) toolMain->close();
	shapeHover = nullptr;
	editingText = nullptr;
	// screenImg / canvas / history 都是成员（canvas 挂在 body 的子节点上），随下面这次 erase 一并释放
	Ling::App::get()->dq.TryEnqueue([this]() {
		std::erase_if(winPins, [this](const std::unique_ptr<WinPin>& p) { return p.get() == this; });
		// 用完即走模式下，最后一个贴图窗口关掉就退出进程，不驻留在系统里。
		// 贴图可以同时开好几个，所以得等它们都没了才退
		if (winPins.empty()) {
			if (Ling::App::get()->args[L"--auto-quit"] == L"true") {
				Ling::App::get()->quit(0);
			}
			else {
				Update::checkLater(); //只剩托盘图标了，顺便查一下更新
			}
		}
	});
}

bool WinPin::hasWindow()
{
	return !winPins.empty();
}

void WinPin::dispose()
{
	winPins.clear();
}

void WinPin::applyWinSize()
{
	auto sz = getImgSize();
	if (!hwnd || sz.width == 0 || sz.height == 0) return;
	auto newW = std::max(1, static_cast<int>(std::lround(sz.width * scale)));
	auto newH = std::max(1, static_cast<int>(std::lround(sz.height * scale)));
	w = static_cast<float>(newW);
	h = static_cast<float>(newH);
	// 不走 setSize：它收的是逻辑像素、内部还要乘一遍 dpi，而这里的宽高本来就是物理像素
	SetWindowPos(hwnd, nullptr, 0, 0, newW, newH, SWP_NOMOVE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_NOREDRAW);
}

void WinPin::applyScale(float newScale, POINT anchor)
{
	auto sz = getImgSize();
	if (sz.width == 0 || sz.height == 0) return;
	// 上限跟着底图大小走：窗口边长再大，swap chain 那块显存也吃不消，人也看不过来；
	// 但至少要能回到 1 倍，所以下面用 max 兜一下
	auto maxScale = std::max(1.f, std::min(8.f, 16000.f / std::max(sz.width, sz.height)));
	newScale = std::clamp(newScale, 0.1f, maxScale);
	if (std::abs(newScale - scale) < 0.0001f) return;
	// 编辑中的文字是 TextBox（真控件）画的，缩放期间它的位置、字号都得跟着重算，
	// 与其在缩放过程里一路同步，不如先收尾把文字交回 ShapeText 自己画 —— 之后它就跟着一起缩了
	if (editingText) editingText->finishEdit();
	// anchor 底下那个底图上的点，缩放前后都要停在光标下：屏幕坐标 = 窗口原点 + 底图点 × 倍数
	auto imgX = anchor.x / scale;
	auto imgY = anchor.y / scale;
	scale = newScale;
	applyWinSize();
	// setPosition 内部会 SetWindowPos，随后的 WM_MOVE 会带出 onMoved -> layoutTools
	setPosition(x + anchor.x - static_cast<int>(std::lround(imgX * scale)),
		y + anchor.y - static_cast<int>(std::lround(imgY * scale)));
	showTip(std::format(L"{}%", static_cast<int>(std::lround(scale * 100.f))));
	layoutTools();
	refresh();
}

// 右上角浮一条提示，停手 800ms 后由定时器收掉。同一个 id 再调一次 setTimer 就是重新计时，
// 所以连续操作期间它一直不会触发
void WinPin::showTip(const std::wstring& text)
{
	tipLayout = Ling::D2D::get()->makeTextLayout(text, 11.f * dpi);
	setTimer(800, 101);
}

// 画在窗口右上角，半透明底 + 白字，与 CutMask 上那个坐标标签一个路子。
// 调用方要先把缩放变换收回去：这是窗口装饰，不跟着图一起放大
void WinPin::paintTip(ID2D1DeviceContext* ctx)
{
	if (!tipLayout || !brushTipBg) return;
	DWRITE_TEXT_METRICS tm{};
	if (FAILED(tipLayout->GetMetrics(&tm))) return;
	auto pad = 3.f * dpi;
	auto margin = 5.f * dpi;
	D2D1_RECT_F bgRect{ w - margin - tm.width - pad * 2, margin, w - margin, margin + tm.height + pad * 2 };
	// 图小到装不下提示时，贴着左边画，别画到窗口外面去
	if (bgRect.left < margin) bgRect.left = margin;
	ctx->FillRectangle(bgRect, brushTipBg.Get());
	ctx->DrawTextLayout({ bgRect.left + pad, bgRect.top + pad }, tipLayout.Get(), brushTipText.Get(), D2D1_DRAW_TEXT_OPTIONS_NONE);
}

// 把 ToolMain / ToolSub 摆到贴图周围，始终靠贴图右对齐，并尽量留在屏幕可视区内。
// 三种模式，按 ToolMain+ToolSub 的总高度决定（与 curId 是否为空无关，避免选中按钮时整组跳动）：
//   bottom : 贴图下方，自上而下 ToolMain -> ToolSub
//   top    : 下方空间不足时改到贴图上方，自上而下 ToolMain -> ToolSub -> 贴图
//   overlay: 上下都不足时覆盖在贴图右下角，整组贴贴图底边
// ToolSub 只在 curId 非空时显示，此时 ToolMain 上移为它腾出空间；ToolSub 永远紧贴 ToolMain 下方，
// 所以它那个朝上的小箭头在三种模式下都不需要翻转。
void WinPin::layoutTools()
{
	if (!toolMain || !toolSub) return;
	// 本函数会在构造期被调用（那会儿还没 hwnd），也可能在工具条收起时被调用 ——
	// 后者不能提前返回：右键唤回工具条时正是"先摆位置再 show"，
	// 一跳过就摆在旧坐标上了（窗口当时还没显示）
	if (!hwnd) return;
	// WinPin 的 hwnd 此时可能还没创建（本函数会在构造期调用），所以用矩形而不是窗口句柄找显示器。
	RECT winRect{ x, y, x + static_cast<int>(w), y + static_cast<int>(h) };
	MONITORINFO mi{ .cbSize = sizeof(MONITORINFO) };
	auto monitor = MonitorFromRect(&winRect, MONITOR_DEFAULTTONEAREST);
	if (!monitor || !GetMonitorInfo(monitor, &mi)) {
		auto [sx, sy, sw, sh] = App::get()->getScreenArea();
		mi.rcWork = RECT{ sx, sy, sx + sw, sy + sh };
	}
	auto& wa = mi.rcWork;

	const auto gap = 5.f * dpi;              // 工具栏与贴图之间的间距
	const auto subGap = ToolSub::mainGap;    // ToolMain 与 ToolSub 之间的间距
	const auto mainH = toolMain->h;
	const auto subH = toolSub->getDesiredHeight();
	const auto groupH = mainH + subGap + subH;
	const bool showSub = !toolMain->curId.empty() && toolSub->hasContent();
	// ToolSub 实际显示时 ToolMain 才上移让出它的位置（有些绘图按钮暂时还没有子工具栏）
	const auto usedH = showSub ? groupH : mainH;

	float mainY;
	if (winRect.bottom + gap + groupH <= wa.bottom) {         // bottom
		mainY = winRect.bottom + gap;
	}
	else if (winRect.top - gap - groupH >= wa.top) {          // top
		mainY = winRect.top - gap - usedH;
	}
	else {                                                    // overlay
		mainY = winRect.bottom - gap - usedH;
	}
	auto mainX = static_cast<float>(winRect.right) - toolMain->w;
	// 垂直方向按整组当前高度裁剪，避免贴图超出工作区时把 ToolSub 挤到屏幕外
	toolMain->setPosition(clampPos(mainX, toolMain->w, wa.left, wa.right), clampPos(mainY, usedH, wa.top, wa.bottom));
	if (showSub) {
		toolSub->updatePosition(wa);
	}
	else {
		toolSub->hideTools();
	}
}

// 把工具条收起来。收起时一定要把画笔选中态也清掉：留着 curId 的话鼠标还归绘图管，
// 而用户已经看不见工具条了，点哪儿都画不出一条线、也没法拖动贴图
void WinPin::hideTools()
{
	if (toolMain) {
		toolMain->cancelSelect();
		toolMain->hide();
	}
	if (toolSub) toolSub->hideTools();
}

// 右键的开关：贴图窗口的常态是没有工具条的，这一下是它唯一的唤出入口
void WinPin::toggleTools()
{
	if (!toolMain) return;
	if (IsWindowVisible(toolMain->hwnd)) {
		hideTools();
	}
	else {
		// 先摆位置再显示：layoutTools 按当前窗口位置算落点，
		// 反过来（先 show 再摆）会先在旧坐标上闪一下
		layoutTools();
		toolMain->show();
	}
}

WinPin::~WinPin()
{
}

void WinPin::initFromData(int x, int y, int w, int h, std::vector<BYTE>& data, float initScale, bool ocr)
{
	auto ptr = new WinPin(x, y, w, h, &data, initScale);
	std::unique_ptr<WinPin> winPin{ ptr };
	ptr->createNativeWindow(WS_EX_TOPMOST | WS_EX_TOOLWINDOW, WS_MAXIMIZEBOX | WS_MINIMIZEBOX | WS_POPUP);
	winPins.push_back(std::move(winPin));
	// 识别放在窗口建完之后：它要读回底图像素，得等图形设备就绪
	if (ocr) ptr->startOcr(false);
}

// 贴"最近一次截图"。图从数据目录的临时文件里读，与剪贴板无关 ——
// 这样复制过文字（剪贴板被占）之后照样能贴图
bool WinPin::initFromLastCapture(bool ocr)
{
	// 截图窗口正开着时不做：它是铺满桌面的一张静态底图，此刻贴上去的东西不会出现在这次
	// 截图的画面里（底图是拖框那一刻拍的），贴出来只会让人以为程序出了问题。
	// 那种情况该走 WinCap::finishToPin()（把当前选区收尾并贴出来）
	if (WinCap::get()) return false;

	std::vector<BYTE> pixels;
	int w{ 0 }, h{ 0 }, sx{ 0 }, sy{ 0 };
	if (!Util::loadLastCapture(pixels, w, h, sx, sy)) {
		// 热键按下去毫无反应，用户只会以为程序卡了，明确说一句。
		// 弹框得跟上 topmost —— 贴图窗口和截图窗口都是 topmost 的，普通弹框会被压在它后面
		MessageBoxW(nullptr, Lang::get(L"pin.empty").data(), Lang::get(L"about.sysTip").data(),
			MB_OK | MB_ICONINFORMATION | MB_TOPMOST | MB_SETFOREGROUND);
		return false;
	}

	// 贴回原处：当初框的是屏幕哪一块，就贴回哪一块。越出工作区时往回夹一下
	MONITORINFO mi{ sizeof(MONITORINFO) };
	auto monitor = MonitorFromPoint(POINT{ sx, sy }, MONITOR_DEFAULTTOPRIMARY);
	if (!monitor || !GetMonitorInfo(monitor, &mi)) {
		auto [ax, ay, aw, ah] = App::get()->getScreenArea();
		mi.rcWork = RECT{ ax, ay, ax + aw, ay + ah };
	}
	const auto& wa = mi.rcWork;
	const int workW = (int)(wa.right - wa.left);
	const int workH = (int)(wa.bottom - wa.top);
	// 比工作区还大就先缩一点，否则一大半在屏幕外。缩的是窗口倍数而不是像素：
	// 底图仍是原始分辨率，之后滚轮放大回去、或者直接复制 / 存盘，拿到的都还是原图
	float initScale{ 1.f };
	if (w > workW || h > workH) {
		initScale = (std::min)((float)workW / (float)w, (float)workH / (float)h) * 0.9f;
	}
	const int drawW = (std::max)(1, static_cast<int>(std::lround(w * initScale)));
	const int drawH = (std::max)(1, static_cast<int>(std::lround(h * initScale)));
	const int px = (std::max)((int)wa.left, (std::min)(sx, (int)wa.right - drawW));
	const int py = (std::max)((int)wa.top, (std::min)(sy, (int)wa.bottom - drawH));
	initFromData(px, py, w, h, pixels, initScale, ocr);
	return true;
}

void WinPin::doPin()
{
	// 截图窗口开着：用户是在 F1 的框选过程中按的贴图键，
	// 这一下要"立刻完成 截图 → 存剪贴板 → 贴图"这一串
	if (auto cap = WinCap::get()) {
		// 还没框出选区时 finishToPin 返回 false（多半是手快按早了），此时什么都不做 ——
		// 那个截图窗口还留着，用户接着框就是
		cap->finishToPin();
		return;
	}
	initFromLastCapture(true);
}

void WinPin::onCreated()
{
    disableBorderRadius();
    auto d2d = Ling::D2D::get();
    // 画布铺满窗口，走 swap chain（双缓冲）后端，避免拖动时整帧闪烁
    canvas = body->makeChild<Ling::Canvas>();
    canvas->enableSwapChain();
    canvas->setSizePercent(100.f, 100.f);
    d2d->deviceContext->CreateSolidColorBrush(D2D1::ColorF(0x1677ff), borderBrush.GetAddressOf());
    d2d->deviceContext->CreateSolidColorBrush(D2D1::ColorF(0x000000, 0.46f), brushTipBg.GetAddressOf());
    d2d->deviceContext->CreateSolidColorBrush(D2D1::ColorF(D2D1::ColorF::White), brushTipText.GetAddressOf());
    // 文字层只有一种高亮：真正被选中的那一段。识别到的词**不铺底** ——
    // 整片淡蓝会把图盖住，用户要看的是图不是识别范围
    d2d->deviceContext->CreateSolidColorBrush(D2D1::ColorF(0x1677ff, 0.34f), brushOcrSel.GetAddressOf());
    // 贴图窗口的常态就是"一张图"：工具条建好了但先收起来，右键才唤回
    hideTools();
    show();
    // 同 WinCap：贴图窗口也要前台。F3 热键唤出时没人激活它，不抢前台的话
    // 文字编辑的 SetFocus 会被系统立刻收回，编辑立不住、ESC 也会落进关窗分支
    takeForeground();
}

void WinPin::layout()
{
    Ling::WinBase::layout();
    if (!screenImg || !canvas) return;
    auto ctx = canvas->startPaint();
    if (!ctx) return;
    ctx->Clear(0);
    auto sz = screenImg->GetSize();
    D2D1_RECT_F destRect = D2D1::RectF(0, 0, sz.width, sz.height);
    // 底图和 shape 都是按底图像素画的，放大缩小整个交给这个变换，
    // 笔宽、夹点跟着一起缩 —— 鼠标坐标进来时也除掉了倍数，所以命中判定天然对得上
    ctx->SetTransform(D2D1::Matrix3x2F::Scale(scale, scale));
    ctx->DrawBitmap(screenImg.Get(), destRect);
	// 标注（工具条是右键唤回来的，平时这里是空的）。文字层盖在它上面：
	// 它是"读图"的辅助，不该被标注挡住
	paintShapes(ctx);
	paintOcrLayer(ctx);
	// 蓝边框和提示属于窗口装饰，不跟着图缩放：变换收回来，按窗口坐标画。
	// 边框也因此从"底图矩形"改成"窗口矩形"，任何倍数下都是 2*dpi 粗
	ctx->SetTransform(D2D1::Matrix3x2F::Identity());
	ctx->DrawRectangle(D2D1::RectF(0.f, 0.f, w, h), borderBrush.Get(), 2*dpi);
	paintTip(ctx);
    canvas->finishPaint();
}

void WinPin::onMinMaxInfo(MINMAXINFO* mmi)
{
	auto [x, y, w, h] = App::get()->getScreenArea();
	mmi->ptMaxPosition.x = x;
	mmi->ptMaxPosition.y = y;
	mmi->ptMaxSize.x = w;
	mmi->ptMaxSize.y = h;
	mmi->ptMinTrackSize.x = 1;
	mmi->ptMinTrackSize.y = 1;
	// 放大后窗口可以比屏幕大（超出的部分自然被裁掉）。默认的最大跟踪尺寸只有
	// 主显示器那么大，不放开的话 SetWindowPos 会被系统按住，放大就到此为止了
	mmi->ptMaxTrackSize.x = 20000;
	mmi->ptMaxTrackSize.y = 20000;
}

void WinPin::onDown(POINT pos, BOOL isRight)
{
	// 编辑文本时，落在文本框里的点击整个交给 TextBox（它自己订阅了窗口的鼠标事件）。
	// 这里不能抢先 SetCapture / 置 isMouseDown，否则拖选文本会被当成拖 shape
	if (editingText && textBox && textBox->isPosIn(pos)) return;

	if (isRight) {
		// 右键是工具条的开关。贴图窗口默认没有工具条，这是唤回它的唯一入口
		toggleTools();
		return;
	}

	// 选中了画笔：这一下归绘图（工具条是右键唤回来的，那时用户就是想画东西）
	if (hasTool()) {
		isMouseDown = true;
		SetCapture(hwnd);
		if (!beginShape(pos)) {
			isMouseDown = false;
			ReleaseCapture();
		}
		return;
	}

	// 没拿画笔：光标落在识别到的文字上就开始选字，落在空白处就拖窗口。
	// 这个分叉正是"文字上能选字、其他地方能自由拖动贴图"
	auto imgPos = toImgPos(pos);
	const int idx = textPickMode() ? wordIndexAt((float)imgPos.x, (float)imgPos.y) : -1;
	isMouseDown = true;
	hasDragged = false;
	SetCapture(hwnd);
	if (idx >= 0) {
		// 起一个选字区间。按下不拖 = 区间只有一个词，也就等于选中了光标下这个词
		selAnchor = idx;
		selCur = idx;
		movingWindow = false;
		refresh();
		return;
	}
	// 空白处：清掉选中，准备拖窗口（pressPos 记的是窗口内的偏移，拖动时把抓住的那点保持在光标下）
	clearSelection();
	pressPos = pos;
	movingWindow = true;
	refresh();
}

void WinPin::onMove(POINT pos)
{
	// 同 onDown：文本框里的移动归 TextBox（拖选、滚动条 hover）
	if (editingText && textBox && textBox->isPosIn(pos)) return;

	if (isMouseDown) {
		if (hasTool()) {
			dragShape(pos);
			return;
		}
		if (movingWindow) {
			setPosition(x + pos.x - pressPos.x, y + pos.y - pressPos.y);
			return;
		}
		if (hasSelection()) {
			// 选字中：光标扫到哪个词就把区间的另一头拉到哪儿。词与词之间那点缝不算数，
			// 所以稍微离开文字也不会把区间打回原点
			auto imgPos = toImgPos(pos);
			const int idx = wordIndexAt((float)imgPos.x, (float)imgPos.y);
			if (idx >= 0 && idx != selCur) {
				selCur = idx;
				refresh();
			}
			return;
		}
		return;
	}

	// 没按下：只有把工具条唤回来之后才有 hover 反馈（画夹点、换光标）
	if (hasTool()) {
		hoverShapeAt(pos);
	}
}

void WinPin::onUp(POINT pos, BOOL isRight)
{
	// 右键按下时什么都没抓（既没置 isMouseDown 也没 SetCapture，见 onDown），抬手也就没什么要收的。
	// 更要紧的是不能往下走：下面会把工具条显示出来，而右键刚刚才把它收起来 —— 一按一放就等于什么都没做
	if (isRight) return;
	if (!isMouseDown) return;
	isMouseDown = false;
	ReleaseCapture();

	if (hasTool()) {
		endShape(pos);
		return;
	}
	if (movingWindow) {
		movingWindow = false;
		// 拖完窗口，工具条跟着走位
		layoutTools();
		return;
	}
	// 选字结束：区间留着，等用户按 Ctrl+C
	if (hasSelection()) refresh();
}

void WinPin::onTimerCB(UINT id)
{
	if (id == 101) { //停手了，收掉右上角那条提示（缩放倍数 / 复制文字反馈）
		killTimer(101);
		tipLayout = nullptr;
		refresh();
		return;
	}
	if (id != 100) return;
	if (!shapeHover) {
		refresh();
		killTimer(100);
	}
}

void WinPin::onKey(UINT key)
{
	// 编辑文本时所有按键都归 TextBox：否则 Ctrl+C 复制的是文字层、Delete 删掉的是整个 shape、
	// ESC 直接把窗口关了。ESC 结束编辑由 TextBox 自己处理
	if (editingText) return;

	if (key == VK_ESCAPE) {
		// 同 WinCap：编辑中由宿主明确收尾（宿主先执行），别依赖 TextBox 的失焦收尾
		if (editingText) {
			editingText->finishEdit();
			// 同 WinCap：ESC 退出编辑时把画笔也取消选中
			if (toolMain) toolMain->cancelSelect();
			return;
		}
		// TextBox 先收过尾的时间窗内不关窗（保底）
		if (GetTickCount64() - textEditEndedAt < 300) return;
		close();
		return;
	}
	bool ctrl = (GetKeyState(VK_CONTROL) & 0x8000) != 0;
	if (ctrl && key == 'C') {
		// 复制的是**选中的文字**，而且不关窗 —— 用户多半还要接着选。
		// 一个词都没选中时给个提示就停下，别把整张图复制走再关窗（刚选好的一半就白选了）
		auto text = selectedOcrText();
		if (text.empty()) {
			showTip(Lang::get(L"pin.ocrNoSel"));
		}
		else {
			Ling::Util::setTextToClipboard(text);
			showTip(Lang::get(L"pin.ocrCopied"));
		}
		refresh();
		return;
	}
	// 下面这些只在把工具条唤回来、正在画东西时才有意义
	if (ctrl && key == 'Z') {
		history->undo();
	}
	else if (ctrl && key == 'Y') {
		history->redo();
	}
	else if (key == VK_DELETE && hasTool()) {
		history->removeHoverShape();
	}
}

void WinPin::copyToClipboard()
{
	std::vector<BYTE> pixels;
	D2D1_SIZE_U size{};
	if (!getImagePixels(pixels, size)) return;
	Util::saveToClipboard((int)size.width, (int)size.height, pixels.data());
	close();
}

void WinPin::saveToFile()
{
	auto foregroundBeforeDialog = GetForegroundWindow();
	auto path = Util::getSaveFilePath(hwnd);
	if (path.empty()) {   // 用户取消
		restoreWindowState(foregroundBeforeDialog);
		return;
	}
	std::vector<BYTE> pixels;
	D2D1_SIZE_U size{};
	if (!getImagePixels(pixels, size)) {
		restoreWindowState(foregroundBeforeDialog);
		return;
	}
	if (Util::saveToFile(path, (int)size.width, (int)size.height, pixels.data())) {
		close();
	}
	else {
		restoreWindowState(foregroundBeforeDialog);
	}
}

// 另存为对话框关掉后会把 owner(hwnd) 变成活动窗口，WinPin 一被激活就会盖住 ToolMain。
// 这里把三个窗口重新压到 topmost，并把前台还给开对话框之前的那个窗口。
void WinPin::restoreWindowState(HWND foregroundBeforeDialog)
{
	SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE);
	if (toolMain && toolMain->hwnd && IsWindowVisible(toolMain->hwnd)) {
		SetWindowPos(toolMain->hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE);
	}
	if (toolSub && toolSub->hwnd && IsWindowVisible(toolSub->hwnd)) {
		SetWindowPos(toolSub->hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE);
	}
	if (foregroundBeforeDialog && foregroundBeforeDialog != hwnd && IsWindowVisible(foregroundBeforeDialog)) {
		SetForegroundWindow(foregroundBeforeDialog);
	}
}

// 离屏把底图和 shape 合成到一张新位图上再读回像素。
// 不直接画到 screenImg 上：它是 ShapeEraser 的"原样"来源，也是 ShapeMosaic 的取样来源，
// 一旦被 shape 覆写，之后再擦除/打码就会拿到已经画过的画面。
// 用 d2d->deviceContext 做离屏是安全的，SetTarget → BeginDraw → EndDraw → SetTarget(nullptr) 在本函数内闭环。
bool WinPin::getImagePixels(std::vector<BYTE>& pixels, D2D1_SIZE_U& size)
{
	// 尺寸一律取底图的像素尺寸，不用窗口的 w/h —— 缩放改的是窗口，
	// 导出的图该始终是原始大小。调用方也得按这个尺寸解释 pixels，所以用出参交出去
	auto imgSize = getImgSize();
	if (imgSize.width == 0 || imgSize.height == 0) return false;
	// 编辑中的文字是 TextBox 自己那层画的，进不了下面这个离屏 target。
	// 先收尾，把文字交回 ShapeText 自己画，保存/复制出去的图才有它。
	if (editingText) editingText->finishEdit();
	size = imgSize;
	auto d2d = Ling::D2D::get();
	auto ctx = d2d->deviceContext.Get();

	D2D1_BITMAP_PROPERTIES1 targetProps{
		.pixelFormat{ D2D1::PixelFormat(DXGI_FORMAT_B8G8R8A8_UNORM, D2D1_ALPHA_MODE_PREMULTIPLIED) },
		.dpiX{ 96.0f }, .dpiY{ 96.0f },
		.bitmapOptions{ D2D1_BITMAP_OPTIONS_TARGET }
	};
	ComPtr<ID2D1Bitmap1> targetBmp;
	auto hr = ctx->CreateBitmap(size, nullptr, 0, &targetProps, targetBmp.GetAddressOf());
	if (FAILED(hr)) return false;

	ctx->SetTarget(targetBmp.Get());
	ctx->SetTransform(D2D1::Matrix3x2F::Identity());
	ctx->BeginDraw();
	ctx->Clear(D2D1::ColorF(0, 0.0f));
	ctx->DrawBitmap(screenImg.Get(), D2D1::RectF(0.f, 0.f, (float)imgSize.width, (float)imgSize.height));
	for (auto& shape : history->shapes)
	{
		if (!shape->isUndo) {
			shape->paint(ctx);
		}
	}
	hr = ctx->EndDraw();
	// 解绑，下面 CopyFromBitmap 才能把它当 source 读
	ctx->SetTarget(nullptr);
	if (FAILED(hr)) return false;

	// GPU 上的 target 位图不能直接 Map，得先拷到一块带 CPU_READ 的位图上
	D2D1_BITMAP_PROPERTIES1 cpuProps{
		.pixelFormat{ targetBmp->GetPixelFormat() },
		.dpiX{ 96.0f }, .dpiY{ 96.0f },
		.bitmapOptions{ D2D1_BITMAP_OPTIONS_CPU_READ | D2D1_BITMAP_OPTIONS_CANNOT_DRAW }
	};
	ComPtr<ID2D1Bitmap1> cpuBmp;
	hr = ctx->CreateBitmap(size, nullptr, 0, &cpuProps, cpuBmp.GetAddressOf());
	if (FAILED(hr)) return false;
	hr = cpuBmp->CopyFromBitmap(nullptr, targetBmp.Get(), nullptr);
	if (FAILED(hr)) return false;
	D2D1_MAPPED_RECT mapped{};
	hr = cpuBmp->Map(D2D1_MAP_OPTIONS_READ, &mapped);
	if (FAILED(hr)) return false;
	// mapped.pitch 按 GPU 行对齐，可能大于 w*4；剪切板和 WIC 都要求紧凑步长，逐行紧缩
	const UINT32 rowBytes = size.width * 4;
	pixels.resize((size_t)rowBytes * size.height);
	for (UINT32 row = 0; row < size.height; ++row)
	{
		CopyMemory(pixels.data() + (size_t)row * rowBytes,
			mapped.bits + (size_t)row * mapped.pitch,
			rowBytes);
	}
	cpuBmp->Unmap();
	return true;
}

BOOL WinPin::setCursor()
{
	// 编辑文本时光标形状交给 TextBox 决定（文本区 I 形、滚动条箭头）。
	// 本函数覆写了基类且不调用它，TextBox 挂在 onCursor 上的那个订阅不会自己被触发，得手动发一次。
	if (editingText) {
		bool handled{ false };
		onCursor(&handled);
		if (handled) return TRUE;
	}
	// 把工具条唤回来之后，光标归绘图（悬停在元素上由元素决定，否则十字 / 文字的 I 形）
	if (setToolCursor()) return TRUE;
	// 落在识别到的字符上才是 I 形（提示这里能选字）。其余地方维持系统默认的箭头 ——
	// 之前是四向箭头，但那会让人误以为"这里只能拖窗口"，而实际上拖哪儿都能拖
	POINT pos{};
	GetCursorPos(&pos);
	ScreenToClient(hwnd, &pos);
	auto imgPos = toImgPos(pos);
	if (textPickMode() && wordIndexAt((float)imgPos.x, (float)imgPos.y) >= 0) {
		SetCursor(LoadCursor(nullptr, IDC_IBEAM));
		return TRUE;
	}
	SetCursor(LoadCursor(nullptr, IDC_ARROW));
	return TRUE;
}

// ————————————————— 文字识别（Windows.Media.Ocr）—————————————————

void WinPin::startOcr(bool notify)
{
	// 已经起过（在跑或跑完了）就不再重复
	if (ocrStarted) return;

	// 先看系统有没有可用的识别引擎。没装 OCR 语言包时整个功能是死的，
	// 必须让用户知道原因 —— 否则按了 F3 只会以为程序坏了。
	// 用 static 保证一个进程只提示一次，别每贴一张图就弹一个框
	static bool warnedNoEngine{ false };
	if (!Ocr::available()) {
		if (!warnedNoEngine) {
			warnedNoEngine = true;
			MessageBoxW(nullptr, Lang::get(L"pin.ocrNoLang").data(), Lang::get(L"about.sysTip").data(),
				MB_OK | MB_ICONINFORMATION | MB_TOPMOST | MB_SETFOREGROUND);
		}
		return;
	}

	ocrStarted = true;
	std::vector<BYTE> pixels;
	D2D1_SIZE_U size{};
	if (!getBaseImagePixels(pixels, size)) {
		// 读像素失败不该把这张图记成"识别过了"，否则之后就没反应了
		ocrStarted = false;
		return;
	}
	// 回调可能在本窗口析构之后才回来，只拿 weak_ptr 认路
	std::weak_ptr<OcrGuard> weak{ ocrGuard };
	Ocr::recognize((int)size.width, (int)size.height, std::move(pixels),
		Ling::App::get()->dq,
		[this, weak, notify](std::shared_ptr<OcrPage> page) {
			if (weak.expired() || isClosed) return;
			onOcrDone(std::move(page));
			// 是用户主动要识别的：没结果也得说一声
			if (notify && !hasOcrText()) {
				showTip(Lang::get(L"pin.ocrEmpty"));
				refresh();
			}
		});
}

void WinPin::onOcrDone(std::shared_ptr<OcrPage> page)
{
	if (!page || page->empty()) return;
	ocrPage = std::move(page);
	// 不需要把文字层"打开"—— 没有选中画笔时它本来就在工作（见 textPickMode）。
	// 只要刷一遍，把那层淡蓝铺上去就行
	refresh();
}

// 只读底图（不带任何 shape）。OCR 要的是"原图"，图上已经画了标注也不该拿合成结果去识别。
// 做法与 getImagePixels 的取像素段一样：先拷到一块 CPU 可读的位图上再 Map。
// 直接从底图拷（不经渲染目标）还有一个好处：GDI 抓屏写出来的图 alpha 常常是 0，
// 原样拷贝拿到的是真实 RGB，不会被预乘合成弄成黑的
bool WinPin::getBaseImagePixels(std::vector<BYTE>& pixels, D2D1_SIZE_U& size)
{
	if (!screenImg) return false;
	auto imgSize = getImgSize();
	if (imgSize.width == 0 || imgSize.height == 0) return false;
	size = imgSize;
	auto ctx = Ling::D2D::get()->deviceContext.Get();

	D2D1_BITMAP_PROPERTIES1 cpuProps{
		.pixelFormat{ D2D1::PixelFormat(DXGI_FORMAT_B8G8R8A8_UNORM, D2D1_ALPHA_MODE_PREMULTIPLIED) },
		.dpiX{ 96.0f }, .dpiY{ 96.0f },
		.bitmapOptions{ D2D1_BITMAP_OPTIONS_CPU_READ | D2D1_BITMAP_OPTIONS_CANNOT_DRAW }
	};
	ComPtr<ID2D1Bitmap1> cpuBmp;
	if (FAILED(ctx->CreateBitmap(imgSize, nullptr, 0, &cpuProps, cpuBmp.GetAddressOf()))) return false;
	if (FAILED(cpuBmp->CopyFromBitmap(nullptr, screenImg.Get(), nullptr))) return false;
	D2D1_MAPPED_RECT mapped{};
	if (FAILED(cpuBmp->Map(D2D1_MAP_OPTIONS_READ, &mapped))) return false;
	// mapped.pitch 按 GPU 行对齐，可能大于 w*4，而 Ocr 要求行紧凑，逐行收紧
	const UINT32 rowBytes = imgSize.width * 4;
	pixels.resize((size_t)rowBytes * imgSize.height);
	for (UINT32 row = 0; row < imgSize.height; ++row) {
		CopyMemory(pixels.data() + (size_t)row * rowBytes,
			mapped.bits + (size_t)row * mapped.pitch, rowBytes);
	}
	cpuBmp->Unmap();
	return true;
}

// 文字层。调用的地方还在缩放变换里，所以这里一律用底图像素坐标
void WinPin::paintOcrLayer(ID2D1DeviceContext* ctx)
{
	// 没选中任何东西就什么都不画：识别到的词不铺底，图保持原样
	if (!textPickMode() || !brushOcrSel || !hasSelection()) return;
	// 这些都是又扁又长的小方块，开抗锯齿反而把边糊掉
	ctx->SetAntialiasMode(D2D1_ANTIALIAS_MODE_ALIASED);
	const int from = selFrom(), to = selTo();
	for (size_t i = 0; i < ocrPage->words.size(); i++)
	{
		if ((int)i < from) continue;
		if ((int)i > to) break;
		auto& wd = ocrPage->words[i];
		ctx->FillRectangle(D2D1::RectF(wd.left, wd.top, wd.right, wd.bottom), brushOcrSel.Get());
	}
	ctx->SetAntialiasMode(D2D1_ANTIALIAS_MODE_PER_PRIMITIVE);
}

// 只在真正落在某个词上时才认（空白处要留给"拖窗口"）。
// 拖选过程中词与词之间那点缝自然就跳过去了，不必再兜底找最近的词 ——
// 那样反而会在光标划过空白时把区间甩到很远的一行去
int WinPin::wordIndexAt(float x, float y) const
{
	if (!ocrPage) return -1;
	for (size_t i = 0; i < ocrPage->words.size(); i++) {
		if (ocrPage->words[i].contains(x, y)) return (int)i;
	}
	return -1;
}

int WinPin::selFrom() const
{
	if (!hasSelection()) return -1;
	return (std::min)(selAnchor, selCur);
}

int WinPin::selTo() const
{
	if (!hasSelection()) return -1;
	return (std::max)(selAnchor, selCur);
}

void WinPin::clearSelection()
{
	selAnchor = -1;
	selCur = -1;
}

std::wstring WinPin::selectedOcrText() const
{
	if (!ocrPage || !hasSelection()) return L"";
	// textOf 认的是升序下标表；区间本身就是连续的，直接铺出来
	std::vector<int> picked;
	picked.reserve((size_t)(selTo() - selFrom() + 1));
	for (int i = selFrom(); i <= selTo(); i++) picked.push_back(i);
	return ocrPage->textOf(picked);
}
