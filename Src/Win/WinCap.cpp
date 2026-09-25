#include "pch.h"
#include <include/Ling.h>
#include "WinCap.h"
#include "WinPin.h"
#include "CutMask.h"
#include "../App.h"
#include "../Util.h"
#include "../Lang.h"
#include "../Setting.h"
#include "../Toast.h"
#include <thread>
#include "../Update.h"
#include "CapLong.h"
#include "CapVideo.h"
#include "../Tool/ToolMain.h"
#include "../Tool/ToolSub.h"
#include "../Shape/ShapeBase.h"
#include "../Shape/ShapeText.h"
using namespace Microsoft::WRL;

namespace
{
    // 放大镜（取景框）：取光标周围 srcW×srcH 个屏幕像素，每个放大 scaleNum 倍画出来。
    // scaleNum 是**物理像素**倍率（不乘 dpi）—— 源像素本来就是物理像素，倍率再跟 dpi
    // 挂钩反而会让不同缩放的屏幕上"一格"大小不一。
    constexpr float scaleNum{ 8.f }, srcW{ 50.f }, srcH{ 30.f };
    constexpr float pixImgH{ scaleNum * srcH };
    constexpr float pixW{ srcW * scaleNum };
    // 原地提示的定时器 id 与显示时长（2 秒）。18 / 19 是 CapLong 的滚动定时器、100 是绘图夹点，
    // 这里避开它们（宿主窗口上共用一套 id）
    constexpr UINT tipMsgId = 21;
    constexpr UINT tipShowMs = 2000;
}

std::unique_ptr<WinCap> winCap;

WinCap::WinCap() : ToolHost()
{
	setTitle(L"Screen Capture");
    auto [x1, y1, w1, h1] = App::get()->getScreenArea();
	this->x = x1;this->y = y1;this->w = w1;this->h = h1;
    onMouseDown.add([this](POINT pos, bool isRight) { this->onDown(pos, isRight); });
    onMouseMove.add([this](POINT pos) { this->onMove(pos); });
    onMouseUp.add([this](POINT pos, bool isRight) { this->onUp(pos, isRight); });
    onKeyDown.add([this](UINT key) { this->onKey(key); });
    // 滚动截图的定时器借的是本窗口的，转给 CapLong。
    // id 100 是绘图夹点的自动收起（ToolHost::hoverShapeAt 里起的，与贴图窗口同一套约定）
    onTimer.add([this](UINT id) {
        if (id == 100) {
            if (!shapeHover) {
                refresh();
                killTimer(100);
            }
            return;
        }
          // 原地提示到点了：收掉它并重画
          if (id == tipMsgId) {
              tipLayout.Reset();
              killTimer(tipMsgId);
              refresh();
              return;
          }
        if (capLong) capLong->onTimerCB(id);
    });
    onDestroy.add([this]() { this->onClosed(); });
    // DPI 变了（用户改了缩放比例）：系统会按新旧缩放比把窗口整体缩放一圈，但本窗口是铺满整个
    // 虚拟桌面的，缩放之后就盖不住桌面了，而且底图、选区（cutMask->maskRect）用的都是物理像素，
    // 窗口一变形它们全部错位，挂在选区上的工具条自然也跟着偏。改缩放不会改分辨率，
    // 桌面还是那么多像素，所以等系统把建议矩形应用完（紧随而来的 WM_SIZE）再把窗口掰回桌面大小。
    // 位置不能在 onDpiChanged 里改 —— 那个事件在建议矩形生效之前触发，改了马上被覆盖
    onDpiChanged.add([this]() { dpiChanged = true; });
    onSizeChanged.add([this]() {
        if (!dpiChanged) return;
        dpiChanged = false;
        auto [x1, y1, w1, h1] = App::get()->getScreenArea();
        this->x = x1; this->y = y1; this->w = w1; this->h = h1;
        SetWindowPos(hwnd, nullptr, x1, y1, (int)w1, (int)h1, SWP_NOZORDER | SWP_NOACTIVATE);
        relayoutTool();
    });
}

WinCap::~WinCap()
{
}

void WinCap::init(const std::wstring& enter)
{
    // 双击托盘图标会连着来两下，功能热键也能在截图窗口开着的时候再按一次。
    // 已经开着就只更新"框完之后去哪"，不再建第二个窗口 —— 用户还没开始拖框时这一下
    // 相当于改了目标功能（先按 F1 再按其它功能键），已经开始拖了就什么都不会发生
    if (winCap) {
        winCap->enterArg = enter;
        return;
    }
    // 每次开截图顺手清一次过期历史（保留天数在设置里，0 = 不留历史）
    Util::pruneShots(Setting::get()->getHistoryDays());
    auto ptr = new WinCap();
    winCap.reset(ptr);
    // 翻历史的按键（默认 , 和 .）在这里取一次，之后按键分发直接比虚拟键码
    ptr->historyPrevVk = Setting::get()->effectiveShortcutVk(L"prevShot");
    ptr->historyNextVk = Setting::get()->effectiveShortcutVk(L"nextShot");
    ptr->enterArg = enter;
    ptr->cutMask = std::make_unique<CutMask>(ptr);
    ptr->createNativeWindow(WS_EX_TOOLWINDOW | WS_EX_TOPMOST, WS_POPUP);//WS_EX_TOPMOST
    // 热键唤出的覆盖层必须抢前台：不抢的话键盘消息（ESC/Ctrl+C）到不了这里，
    // 文字编辑也会因为 SetFocus 被系统立刻收回（WM_KILLFOCUS）而立不住
    ptr->takeForeground();
}

WinCap* WinCap::get()
{
    return winCap.get();
}

void WinCap::dispose()
{
    winCap.reset();
}

void WinCap::onCreated()
{
    // 顺手把整屏原图也拷一份：截图历史要留"当时整个屏幕的画面"
    App::get()->takeScreenShot(x, y, w, h, &screenImg, &screenRaw);
	auto d2d = Ling::D2D::get();
    // 画布铺满窗口，走 swap chain（双缓冲）后端，避免调整选区时整帧闪烁
    canvas = body->makeChild<Ling::Canvas>();
    canvas->enableSwapChain();
    canvas->setSizePercent(100.f, 100.f);
    d2d->deviceContext->CreateSolidColorBrush(D2D1::ColorF(D2D1::ColorF::White), brushText.GetAddressOf());
    d2d->deviceContext->CreateSolidColorBrush(D2D1::ColorF(0x000000, 0.56f), brushBg.GetAddressOf());
    d2d->deviceContext->CreateSolidColorBrush(D2D1::ColorF(0.1f, 0.5f, 1.f, 0.5f), crossBrush.GetAddressOf());
    // 原地提示的底与字：半透明黑底 + 白字，和选区里那个坐标标签一个路子
    d2d->deviceContext->CreateSolidColorBrush(D2D1::ColorF(0x000000, 0.72f), brushTipBg.GetAddressOf());
    d2d->deviceContext->CreateSolidColorBrush(D2D1::ColorF(D2D1::ColorF::White), brushTipText.GetAddressOf());
    POINT pos;
    GetCursorPos(&pos);
    ScreenToClient(hwnd, &pos);
    getPixImg(pos);
    setPixPos(pos);
    show();
}

void WinCap::layout()
{
    Ling::WinBase::layout();
    if (!canvas) return;
    auto ctx = canvas->startPaint();
    if (!ctx) return;
    ctx->Clear(0);
    D2D1_RECT_F destRect = D2D1::RectF(0, 0, (float)w, (float)h);
    if (!hideScreenImg) {
        ctx->DrawBitmap(screenImg.Get(), destRect);
        // 标注画在底图之上、蒙版之下：蒙版只压暗选区外面，所以选区里的标注照常看得见。
        // 裁到选区上 —— 拖动时手指会跑到选区外，裁掉之后所见即所得，
        // 与导出（导出也只取选区那一块）一致。
        // 这里的坐标系是桌面物理像素（本窗口铺满桌面且不做缩放），shape 存的就是这个坐标
        if (history && cutMask->hasRect()) {
            auto& mr = cutMask->maskRect;
            ctx->PushAxisAlignedClip(D2D1::RectF(mr.left, mr.top, mr.right, mr.bottom), D2D1_ANTIALIAS_MODE_ALIASED);
            paintShapes(ctx);
            ctx->PopAxisAlignedClip();
        }
    }
    cutMask->paint(ctx);
    if (capLong) capLong->paint(ctx);
    paintPix(ctx);
    paintTip(ctx);
    canvas->finishPaint();
}

// 在选区正中画一行提示。这不是标注，不进 history、也不进导出图 —— 它只是给用户看一眼
void WinCap::paintTip(ID2D1DeviceContext* ctx)
{
    if (!tipLayout || !brushTipBg || !cutMask->hasRect()) return;
    DWRITE_TEXT_METRICS tm{};
    if (FAILED(tipLayout->GetMetrics(&tm))) return;
    auto pad = 8.f * dpi;
    auto boxW = tm.width + pad * 2;
    auto boxH = tm.height + pad * 2;
    auto& mr = cutMask->maskRect;
    auto cx = (mr.left + mr.right) / 2.f;
    auto cy = (mr.top + mr.bottom) / 2.f;
    D2D1_RECT_F bgRect{ cx - boxW / 2, cy - boxH / 2, cx + boxW / 2, cy + boxH / 2 };
    // 选区太小时（比提示框还窄）也别画到选区外面去
    if (bgRect.left < 0) { bgRect.right -= bgRect.left; bgRect.left = 0; }
    ctx->FillRectangle(bgRect, brushTipBg.Get());
    ctx->DrawTextLayout({ bgRect.left + pad, bgRect.top + pad }, tipLayout.Get(), brushTipText.Get(), D2D1_DRAW_TEXT_OPTIONS_NONE);
}

void WinCap::showTip(const std::wstring& text)
{
    tipLayout = Ling::D2D::get()->makeTextLayout(text, 13.f * dpi);
    // 先撤掉上一次的定时器再重新计时：连着点两次二维码，第二次应该重新显示满 2 秒
    killTimer(tipMsgId);
    setTimer(tipShowMs, tipMsgId);
    refresh();
}

BOOL WinCap::setCursor()
{
    if (stage == CapStage::Select) {
        SetCursor(LoadCursor(nullptr, IDC_CROSS));
        return TRUE;
    }
    if (stage == CapStage::Long && capLong) {
        capLong->setCursor();
        return TRUE;
    }
    if (stage == CapStage::Adjust) {
        // 选了画笔：光标归绘图，不能再给"调整选区"那套箭头 ——
        // 否则选了"线条"却满屏四向箭头，看着就像只能拖选区、画不了东西
        if (setToolCursor()) return TRUE;
        POINT pos{};
        GetCursorPos(&pos);
        ScreenToClient(hwnd, &pos);
        switch (cutMask->hitTest(pos))
        {
        case MaskHit::TopLeft:
        case MaskHit::BottomRight:
            SetCursor(LoadCursor(nullptr, IDC_SIZENWSE));
            return TRUE;
        case MaskHit::TopRight:
        case MaskHit::BottomLeft:
            SetCursor(LoadCursor(nullptr, IDC_SIZENESW));
            return TRUE;
        case MaskHit::Top:
        case MaskHit::Bottom:
            SetCursor(LoadCursor(nullptr, IDC_SIZENS));
            return TRUE;
        case MaskHit::Left:
        case MaskHit::Right:
            SetCursor(LoadCursor(nullptr, IDC_SIZEWE));
            return TRUE;
        case MaskHit::Inside:
            SetCursor(LoadCursor(nullptr, IDC_SIZEALL));
            return TRUE;
        default:
            break;
        }
    }
    SetCursor(LoadCursor(nullptr, IDC_ARROW));
    return TRUE;
}

// preferLeft / preferTop：优先把取景框放在光标的左侧 / 上方。
// 拖框过程中用得上 —— 默认"右下"在往左上拖时会正好压住正在调的选区，
// 传进拖动方向反侧的偏好，取景框就落在选区外面了。
// 偏好位置放不下（顶到窗口边）仍然会翻回另一侧，保证它总在屏幕内。
void WinCap::setPixPos(POINT pos, bool preferLeft, bool preferTop)
{
    pixPreferL = preferLeft;   // 记下最近的避让偏好，调整阶段悬停沿用
    pixPreferT = preferTop;
    auto span{ 10 * dpi };
    auto pixH{ pixImgH + 76.f * dpi };
    if (preferLeft) {
        pixPos.x = int(pos.x - span - pixW + dpi);
        if (pixPos.x < 0) pixPos.x = int(pos.x + span + dpi);
    }
    else {
        pixPos.x = int(pos.x + span + dpi);
        if (pixPos.x + pixW > w) {
            pixPos.x = int(pos.x - span - pixW + dpi);
        }
    }
    if (preferTop) {
        pixPos.y = int(pos.y - span - pixH + dpi);
        if (pixPos.y < 0) pixPos.y = int(pos.y + span + dpi);
    }
    else {
        pixPos.y = int(pos.y + span + dpi);
        if (pixPos.y + pixH > h) {
            pixPos.y = int(pos.y - span - pixH + dpi);
        }
    }
}

void WinCap::getPixImg(POINT pos)
{
    // 拖动中（isPress）也要取像：终点和起点一样要能对准（见 onMove）。
    // 调整阶段（Adjust）同样要放大镜 —— 挪框/拉角也要对准到像素
    if (stage != CapStage::Select && stage != CapStage::Adjust) return;
    const long sw = static_cast<long>(srcW), sh = static_cast<long>(srcH);
    const long iw = static_cast<long>(w), ih = static_cast<long>(h);
    // 期望的源矩形：以光标为正中心，可以越出屏幕。
    const long wantL = pos.x - sw / 2, wantT = pos.y - sh / 2;
    long vl = std::max(wantL, 0L), vt = std::max(wantT, 0L);
    long vr = std::min(wantL + sw, iw), vb = std::min(wantT + sh, ih);
    // 交集在 pixImg 内的落点：期望矩形左上角为原点，所以减 wantL/wantT（越界时为正偏移）
    const long dl = vl - wantL, dt = vt - wantT;
    if (!pixImg) {
        auto d2d = Ling::D2D::get();
        D2D1_BITMAP_PROPERTIES1 prop{};
        prop.pixelFormat = screenImg->GetPixelFormat();
        prop.bitmapOptions = D2D1_BITMAP_OPTIONS_NONE;
        screenImg->GetDpi(&prop.dpiX, &prop.dpiY);
        auto hr = d2d->deviceContext->CreateBitmap(D2D1::SizeU(sw, sh), nullptr, 0, &prop, &pixImg);
    }
    auto srcRect = D2D1::RectU(vl, vt, vr, vb);
    auto destPoint = D2D1::Point2U(static_cast<UINT32>(dl), static_cast<UINT32>(dt));
    auto hr = pixImg->CopyFromBitmap(&destPoint, screenImg.Get(), &srcRect);
    // pixImg 里这一帧真正有内容的区域。越界部分留着上一帧的残留，
    // 绘制时靠 DrawBitmap 的 srcRect 把它排除掉，露出取景框自己的底色。
    pixSrcRect = D2D1::RectF((float)dl, (float)dt, float(dl + (vr - vl)), float(dt + (vb - vt)));
}

void WinCap::paintPix(ID2D1DeviceContext* ctx)
{
	// 拖动中也照画（原来按下就收起来，于是"起点能对准、终点看不见"）。
	// 调整阶段同样照画 —— 挪框 / 拉角也要对准（2026-09-26 起）
	if (stage != CapStage::Select && stage != CapStage::Adjust) return;
    D2D1_RECT_F pixRect{ (float)pixPos.x, (float)pixPos.y, pixPos.x + pixW, pixPos.y + pixImgH + 76.f * dpi };
    ctx->FillRectangle(pixRect, brushBg.Get());
    if (pixSrcRect.right > pixSrcRect.left && pixSrcRect.bottom > pixSrcRect.top) {
        D2D1_RECT_F imgRect{
            pixPos.x + pixSrcRect.left * scaleNum,
            pixPos.y + pixSrcRect.top * scaleNum,
            pixPos.x + pixSrcRect.right * scaleNum,
            pixPos.y + pixSrcRect.bottom * scaleNum
        };
        ctx->DrawBitmap(pixImg.Get(), imgRect, 1.0f, D2D1_BITMAP_INTERPOLATION_MODE_NEAREST_NEIGHBOR, &pixSrcRect);
    }
    ctx->DrawRectangle(pixRect, brushBg.Get(),dpi);

    // 十字的臂半宽。臂厚 = 2×crossWHalf，跟 scaleNum 走、不能乘 dpi（历史教训：
    //   最早写 4*dpi 而 scaleNum=5，臂缝里能塞下两个源像素，准星分不清取的是哪一个）。
    // ⚠ 中心"洞"的位置必须对齐到**光标下那个源像素**的格子上，不是简单居中：
    //   采样窗固定取 wantL = pos.x - srcW/2，所以光标永远落在采样窗第 srcW/2 个
    //   源像素的**左边缘**上 —— 画出来就是 [pixW/2, pixW/2+scaleNum) 这一个格子。
    //   若把洞居中在 pixW/2（[pixW/2-scaleNum/2, pixW/2+scaleNum/2)），洞会骑在
    //   两个源像素的交界上，各露一半 —— 看着就是 2×2 四个像素（2026-09-26 用户实测）。
    const float crossWHalf{ scaleNum * 0.5f };
    const float px{ scaleNum };
    auto crossRect0 = D2D1::RectF(pixPos.x, pixPos.y+pixImgH / 2 - crossWHalf, pixPos.x+pixW / 2, pixPos.y + pixImgH / 2 + crossWHalf);
    auto crossRect1 = D2D1::RectF(pixPos.x + pixW / 2 + px, pixPos.y+pixImgH / 2 - crossWHalf, pixPos.x + pixW, pixPos.y + pixImgH / 2 + crossWHalf);
    auto crossRect2 = D2D1::RectF(pixPos.x + pixW / 2 - crossWHalf, pixPos.y, pixPos.x + pixW / 2 + crossWHalf, pixPos.y + pixImgH / 2);
    auto crossRect3 = D2D1::RectF(pixPos.x + pixW / 2 - crossWHalf, pixPos.y+pixImgH / 2 + px, pixPos.x + pixW / 2 + crossWHalf, pixPos.y + pixImgH);

    ctx->FillRectangle(crossRect0, crossBrush.Get());
    ctx->FillRectangle(crossRect1, crossBrush.Get());
    ctx->FillRectangle(crossRect2, crossBrush.Get());
    ctx->FillRectangle(crossRect3, crossBrush.Get());

    POINT pos;
	GetCursorPos(&pos);
    HDC hScreen = GetDC(NULL);
    COLORREF cr = GetPixel(hScreen, pos.x, pos.y);
    ReleaseDC(NULL, hScreen);
    auto d2d = Ling::D2D::get();
    float padding{ 7.f * dpi },fontSize{ 10.f*dpi };
    Microsoft::WRL::ComPtr<IDWriteTextLayout> textLayout;
    for (size_t i = 0; i < 4; i++)
    {
        std::wstring str;
        if (i == 0) {
            str = std::format(L"HEX (Ctrl+H) : #{:02X}{:02X}{:02X}", GetRValue(cr), GetGValue(cr), GetBValue(cr));
		}
		else if (i == 1) {
			str = std::format(L"RGB (Ctrl+R) : {},{},{}", GetRValue(cr), GetGValue(cr), GetBValue(cr));
		}
        else if (i == 2) {
            auto [c, m, y1, k] = getCMYK(GetRValue(cr), GetGValue(cr), GetBValue(cr));
            str = std::format(L"CMYK (Ctrl+K) : {},{},{},{}", c, m, y1,k);
        }
        else if (i == 3) {
            str = std::format(L"POS (Ctrl+P) : X:{} Y:{}", pos.x, pos.y);
        }
        d2d->dwriteFactory->CreateTextLayout(str.data(), (UINT32)str.length(), d2d->baseTextFormat.Get(), FLT_MAX, FLT_MAX, &textLayout);
        textLayout->SetFontSize(fontSize, { 0,INT_MAX });
        ctx->DrawTextLayout({ pixPos.x + padding, pixPos.y + pixImgH + padding*(i+1) + fontSize*i }, textLayout.Get(), brushText.Get(), D2D1_DRAW_TEXT_OPTIONS_NONE);
    }
}

void WinCap::onKey(UINT key)
{
    // 编辑文本时所有按键都归 TextBox：否则 ESC 会把整个截图窗口连图带标注关掉、
    // Ctrl+Z 会去撤销上一个图形
    if (editingText) return;

    auto func = []() {
        POINT pos;
        GetCursorPos(&pos);
        HDC hScreen = GetDC(NULL);
        COLORREF cr = GetPixel(hScreen, pos.x, pos.y);
        ReleaseDC(NULL, hScreen);
        return cr;
    };
    if (key == VK_ESCAPE) {
        // 宿主在这个事件里先执行（先注册先调用），所以编辑中由这里**明确**收尾 ——
        // 不能指望 TextBox 自己的 ESC 分支：它失焦收尾会把 editingText 清掉，
        // 一旦焦点状态有变，轮到宿主时编辑已经没了，ESC 就会落进下面的关窗分支
        if (editingText) {
            editingText->finishEdit();
            // 顺手取消画笔选中：ESC 是"退出编辑"，该回到普通截图状态，
            // 而不是让下一次点击又落出一个新输入框
            if (toolMain) toolMain->cancelSelect();
            return;
        }
        // TextBox 已在这一次按键里先收过尾的时间窗内不关窗（保底）
        if (GetTickCount64() - textEditEndedAt < 300) return;
        close();
    }
    // 绘图：撤销 / 重做。只在"调整选区"这个阶段有意义（那会儿绘图工具条在）。
    // 键盘消息常常是落在工具条上的，ToolMain 会把 onKeyDown 转回这里
    else if ((key == 'Z' || key == 'Y') && stage == CapStage::Adjust && (GetKeyState(VK_CONTROL) & 0x8000)) {
        if (key == 'Z') history->undo();
        else history->redo();
    }
    else if (key == 'H' && (GetKeyState(VK_CONTROL) & 0x8000)) {
		auto cr = func();
        BYTE r = GetRValue(cr), g = GetGValue(cr), b = GetBValue(cr);
        wchar_t hex[8];
        swprintf_s(hex, L"#%02X%02X%02X", r, g, b);
        Ling::Util::setTextToClipboard(hex);
        close();
    }
    else if (key == 'R' && (GetKeyState(VK_CONTROL) & 0x8000)) {
        auto cr = func();
        BYTE r = GetRValue(cr), g = GetGValue(cr), b = GetBValue(cr);
        Ling::Util::setTextToClipboard(std::format(L"rgb({},{},{})", r, g, b));
        close();
    }
    else if (key == 'K' && (GetKeyState(VK_CONTROL) & 0x8000)) {
        auto cr = func();
        BYTE r = GetRValue(cr), g = GetGValue(cr), b = GetBValue(cr);
        auto [c, m, y1, k] = getCMYK(r, g, b);
        Ling::Util::setTextToClipboard(std::format(L"cmyk({},{},{},{})", c, m, y1, k));
        close();
    }
    else if (key == 'P' && (GetKeyState(VK_CONTROL) & 0x8000)) {
        POINT pos;
        GetCursorPos(&pos);
        Ling::Util::setTextToClipboard(std::format(L"{},{}", pos.x, pos.y));
        close();
    }
    // 长图与录屏阶段：Ctrl+S 存文件，Ctrl+C 存剪切板，等价于各自工具条上的那两个按钮。
    // 这两个阶段里键盘消息进的往往是工具条，ToolLong / ToolVideo 会把 onKeyDown 转回这里
    else if ((key == 'S' || key == 'C') && (GetKeyState(VK_CONTROL) & 0x8000)) {
        const bool toClipboard{ key == 'C' };
        if (stage == CapStage::Adjust) {
            // 截图阶段也认 Ctrl+S / Ctrl+C，和工具条上那两个按钮一个意思。
            // 在此之前只有回车能复制、没有键盘存盘，长图/录屏那两阶段反而都有
            if (toClipboard) copyToClipboard();
            else saveToFile();
        }
          else if (stage == CapStage::Long && capLong && capLong->hasImage()) {
              // 收尾只剩"保存"一条路（与录屏一致）：Ctrl+C 也当成保存，别再往剪贴板走。
              // 与 ToolLong::onClick 同一套规则：存盘被取消了就留在原地，图还没丢
              if (!longSaveToFile()) return;
              close();
          }
        else if (stage == CapStage::Video && capVideo) {
            // 停录、存盘、关窗都在 ToolVideo 那边一条龙做完
            capVideo->onSaveKey(toClipboard);
        }
    }
    // 历史翻页的专用按键（设置-快捷键里可改，默认 , 和 .）。
    // 只在没按住任何修饰键时才认 —— 否则用户把 , 绑成翻页之后，Ctrl+, 之类也会被吃掉；
    // 而且 Ctrl+S / Ctrl+Z 这些现成组合必须原样保留。翻不动时什么都不做（这类键是
    // 专门为翻页绑的，不该像方向键那样再退回去干别的）
    else if (key != 0 && (key == historyPrevVk || key == historyNextVk)
        && !(GetKeyState(VK_CONTROL) & 0x8000) && !(GetKeyState(VK_MENU) & 0x8000)
        && !(GetKeyState(VK_SHIFT) & 0x8000) && !(GetKeyState(VK_LWIN) & 0x8000)
        && !(GetKeyState(VK_RWIN) & 0x8000)) {
        if (key == historyPrevVk && canGoPrevShot()) goPrevShot();
        else if (key == historyNextVk && canGoNextShot()) goNextShot();
        return;
    }
    else if (key == VK_UP || key == VK_DOWN || key == VK_LEFT || key == VK_RIGHT
        || ((key == 'W' || key == 'A' || key == 'S' || key == 'D')
            && !(GetKeyState(VK_CONTROL) & 0x8000) && !(GetKeyState(VK_MENU) & 0x8000)
            && !(GetKeyState(VK_SHIFT) & 0x8000)
            && !(GetKeyState(VK_LWIN) & 0x8000) && !(GetKeyState(VK_RWIN) & 0x8000)
            // ⚠ W/A/S/D 只在截图这两个阶段生效。长图 / 录屏阶段必须让开 ——
            // 录制时用户要拿 WASD 操作被录的那个程序（游戏里就是方向），
            // 被这里吃掉就等于"一录屏角色就不会动了"
            && (stage == CapStage::Select || stage == CapStage::Adjust))) {
        // ← / → 优先用来翻看上一条 / 下一条截图（连标注一起回到当时的样子做不到，
        // 见 applyShot 的注释）。历史里翻不动时，才退回原来的"1 像素挪光标一格"，
        // 这样第一次截图时方向键还是老行为。
        // ⚠ 只在"调整选区"阶段兼作翻页：Select 阶段（刚按 F1 还没框）方向键是
        // "1 像素 1 像素挪光标、对准起点"用的，那个阶段不抢它 —— 想看上一张请用
        // 设置里配的翻页键（默认 , 和 .），那两个键两个阶段都生效
        // ⚠ W/A/S/D 是方向键的别名（左手不用离开键盘就能把落点挪准 1 个像素，
        // 鼠标手抖很难做到），但它不参与翻页：翻历史有方向键和 , . 就够了
        const bool arrow = (key == VK_UP || key == VK_DOWN || key == VK_LEFT || key == VK_RIGHT);
        const bool arrowCanNav = (stage == CapStage::Adjust);
        if (arrow && arrowCanNav && key == VK_LEFT && canGoPrevShot()) { goPrevShot(); return; }
        if (arrow && arrowCanNav && key == VK_RIGHT && canGoNextShot()) { goNextShot(); return; }
        POINT pos;
        GetCursorPos(&pos);
        if (key == VK_UP || key == 'W') pos.y -= 1;
        else if (key == VK_DOWN || key == 'S') pos.y += 1;
        else if (key == VK_LEFT || key == 'A') pos.x -= 1;
        else pos.x += 1;
        SetCursorPos(pos.x, pos.y); // 后面的 WM_MOUSEMOVE 会让 onMove 跟着刷新
    }
    // Enter 与 Ctrl+C 一个意思：把图存进剪切板。比 Ctrl+C 多管一个阶段 ——
    // 选区刚框好（Adjust）时也认，那会儿等于点了工具条上的复制按钮
    else if (key == VK_RETURN) {
        copyCurrentStage();
    }
}

void WinCap::copyCurrentStage()
{
    if (stage == CapStage::Adjust) {
        // 选区里的像素，与在窗口里双击同一条路（见 onDown）。它自己会关窗
        copyToClipboard();
    }
    else if (stage == CapStage::Long && capLong && capLong->hasImage()) {
        // 还没点"开始"滚动时一张图都没有（hasImage），此时不该收工
        longCopyToClipboard();
        close();
    }
    else if (stage == CapStage::Video && capVideo) {
        // 停录、存盘、关窗都在 ToolVideo 那边一条龙做完
        capVideo->onSaveKey(true);
    }
}

std::tuple<int, int, int, int> WinCap::getCMYK(const BYTE& r, const BYTE& g, const BYTE& b)
{
    double R = r / 255.0, G = g / 255.0, B = b / 255.0;
    double K = 1.0 - (std::max)(R, (std::max)(G, B));
    double C = (K == 1.0) ? 0.0 : (1.0 - R - K) / (1.0 - K);
    double M = (K == 1.0) ? 0.0 : (1.0 - G - K) / (1.0 - K);
    double Y = (K == 1.0) ? 0.0 : (1.0 - B - K) / (1.0 - K);
    return std::make_tuple(static_cast<int>(std::round(C * 100)),
        static_cast<int>(std::round(M * 100)),
        static_cast<int>(std::round(Y * 100)),
        static_cast<int>(std::round(K * 100))
    );
}
LRESULT WinCap::onHitTest(const POINT pos)
{
    // 录屏阶段整窗让出鼠标：用户要能直接操作被录的那个应用
    if (isMouseTransparent || stage == CapStage::Video) return HTTRANSPARENT;
    return HTCLIENT;
}

void WinCap::onDown(POINT pos, bool isRight)
{
    // 编辑文本时，落在文本框里的点击整个交给 TextBox（它自己订阅了窗口的鼠标事件）。
    // 这里不能抢先 SetCapture / 置 isMouseDown，否则拖选文本会被当成拖 shape 或调选区
    if (editingText && textBox && textBox->isPosIn(pos)) return;

    // 右键不再退出截图（原来这里直接 close()）。什么都不做：取消用 ESC 或工具条上的关闭
    if (isRight) {
        return;
    }
    // 选区框好之后，窗口里任意位置双击都等于点了工具条上的"复制到剪切板"。
    // 双击判定得自己做：Ling 的窗口类没带 CS_DBLCLKS，WM_LBUTTONDBLCLK 根本不会来，
    // 所以拿系统的双击间隔（用户在控制面板里调的那个）和双击判定框来认
    auto now = GetTickCount64();
    bool isDblClick = (now - lastDownTime <= GetDoubleClickTime())
        && std::abs(pos.x - lastDownPos.x) <= GetSystemMetrics(SM_CXDOUBLECLK)
        && std::abs(pos.y - lastDownPos.y) <= GetSystemMetrics(SM_CYDOUBLECLK);
    lastDownTime = now;
    lastDownPos = pos;
    if (isDblClick && stage == CapStage::Adjust && !hasTool()) {
        copyToClipboard();
        return;
    }
    if (stage == CapStage::Select) {
        isPress = true;
        dragStartPos = pos;
        cutMask->startMakeRect(pos);
        // 拖框期间抓住鼠标：快速拖到屏幕边缘会触发 WM_MOUSELEAVE，Ling 的
        // mouseLeave 会拿 {INT_MAX,INT_MAX} 来调 onMove，框选和调整都会被
        // clamp 到右下角（2026-09-26 用户实测"框闪到屏幕最右下角"）。
        // 抓住之后 leave 不来、move 也不会断，是根治；哨兵防护是兜底。
        SetCapture(hwnd);
        // 放大镜在拖动过程中一直留着（原来按下就收起来了），按下这一下先刷一次，
        // 免得要等鼠标动了它才重新出现
        refresh();
    }
    else if (stage == CapStage::Adjust) {
        // 选了画笔、而且按在选区里：这一下归绘图，不是调整选区
        if (hasTool() && isPosInMask(pos)) {
            isMouseDown = true;
            SetCapture(hwnd);
            if (!beginShape(pos)) {
                isMouseDown = false;
                ReleaseCapture();
            }
            return;
        }
        // 选区外面按下不是重新框选，而是按落点所在的那一块调对应的边或角
        isPress = true;
        dragStartPos = pos;   // 放大镜摆向靠它判断拖动方向（与 Select 同款）
        cutMask->startAdjust(pos);
        SetCapture(hwnd);
        layoutTools();
        refresh();   // 调整阶段放大镜也常驻，按下先刷出来
    }
}

void WinCap::onMove(POINT pos)
{
    // Ling 的 mouseLeave 用 {INT_MAX,INT_MAX} 当哨兵。调整选区时收到它等于
    // "把选区夹到右下角"，直接忽略（拖框期间已 SetCapture，正常不会收到；
    // 这是给没抓住时的兜底）
    if (pos.x == INT_MAX || pos.y == INT_MAX) return;

    // 编辑文本时鼠标交给 TextBox，别让 hoverShapeAt 去画夹点、换光标
    if (editingText && textBox && textBox->isPosIn(pos)) return;

    if (stage == CapStage::Select) {
        if (isPress) {
            // 拖动过程中放大镜也跟着鼠标走：只对准起点、看不见终点的话，
            // 相当于每次都得靠感觉收尾。取景框摆在拖动方向的反侧
            //（光标在起点的右上就摆右上），这样它落在选区外面，不会压住正在调的内容
            getPixImg(pos);
            setPixPos(pos, pos.x < dragStartPos.x, pos.y < dragStartPos.y);
            cutMask->makeRect(pos);   // 内部 refresh，连放大镜一起重画
        }
        else {
            cutMask->highlight(pos);
            getPixImg(pos);
            setPixPos(pos);
            refresh();
        }
    }
    else if (stage == CapStage::Adjust) {
        // 画笔按着：拖的是图形
        if (hasTool() && isMouseDown) {
            dragShape(pos);
            return;
        }
        if (!isPress) {
            // 没按下时给画笔一点悬停反馈（夹点、光标）；
            // 放大镜调整阶段常驻，跟着光标走，避让方向沿用拖角时那一侧
            if (hasTool()) hoverShapeAt(pos);
            getPixImg(pos);
            setPixPos(pos, pixPreferL, pixPreferT);
            refresh();
            return;
        }
        getPixImg(pos);
        // 放大镜摆到拖动方向的反侧，别压住正在调的选区
        setPixPos(pos, pos.x < dragStartPos.x, pos.y < dragStartPos.y);
        cutMask->adjust(pos);
        // 选区变了，整组工具条跟着走位
        layoutTools();
    }
    else if (stage == CapStage::Long && capLong) {
        capLong->onMove(pos);
    }
}

void WinCap::onUp(POINT pos, bool isRight)
{
    auto releaseIfCaptured = [this]() {
        if (GetCapture() == hwnd) ReleaseCapture();
    };
    if (stage == CapStage::Select) {
        isPress = false;
        releaseIfCaptured();
        // 只是点了一下，又没吸附到任何窗口，那就接着让用户框
        if (!cutMask->hasRect()) return;
        // 命令行指定了直奔某个阶段：它比下面 Ctrl 那条钉图的快捷路径更优先 ——
        // 参数是用户明确要求的，Ctrl 只是顺手按上的
        if (enterByArg()) return;
        // 按住 Ctrl 框选：跳过调整和工具条，直接钉到桌面上
        if (GetKeyState(VK_CONTROL) & 0x8000) {
            startPin();
            return;
        }
        stage = CapStage::Adjust;
        refresh();  // 进调整阶段：放大镜继续留在这个阶段常驻
        makeTools();
    }
    else if (stage == CapStage::Adjust) {
        if (hasTool() && isMouseDown) {
            isMouseDown = false;
            ReleaseCapture();
            endShape(pos);
            return;
        }
        isPress = false;
        releaseIfCaptured();
    }
    else if (stage == CapStage::Long && capLong) {
        capLong->onUp(pos);
    }
}

// close() 里 DestroyWindow 之后同步触发 onDestroy，而这条路径通常是从某个工具条的按钮
// 回调里一路进来的（工具条是 WinCap / CapLong / CapVideo 的成员）。在这里直接
// winCap.reset() 就是 use-after-free，所以窗口句柄立即销毁，C++ 对象的释放推迟到下一轮消息循环。
void WinCap::onClosed()
{
    if (isClosed) return;
    isClosed = true;
    if (capVideo) capVideo->dispose();
    if (capLong) capLong->dispose();
    if (toolSub) toolSub->close();
    if (toolMain) toolMain->close();
    Ling::App::get()->dq.TryEnqueue([]() {
        winCap.reset();
        // 用完即走模式下截图结束就退出进程，与 App 构造里的判断对称。
        // 但标注、长截图这两条路是先把图钉到桌面上再关自己的，那种情况下活还没干完，
        // 退出的活交给最后一个关掉的贴图窗口
        if (!WinPin::hasWindow()) {
            if (Ling::App::get()->args[L"--auto-quit"] == L"true") {
                Ling::App::get()->quit(0);
            }
            else {
                Update::checkLater(); //只剩托盘图标了，顺便查一下更新
            }
        }
    });
}

void WinCap::stopIfRecording()
{
    if (!winCap || !winCap->capVideo) return;
    // 正在录制：先停止编码线程，避免退出时线程与设备卡死
    winCap->capVideo->stop();
}

void WinCap::makeTools()
{
    if (!toolMain) {
        // 工具条自己会在构造里建窗口。绘图子系统（Shape* / History）认的是 ToolHost，
        // WinCap 正是它的一个宿主，所以这里建出来的跟贴图窗口用的是同一套代码。
        // 传 capTools=true：这一根上除了绘图按钮还带截长图 / 录屏 / 文字识别 / 二维码 ——
        // 原先那根独立的 ToolCap 并进来了，两根条合成一根
        toolMain = std::make_unique<ToolMain>(this, true);
        toolSub = std::make_unique<ToolSub>(this);
    }
    // 无论这次是新建还是复用，都要露出来 + 按当前选区重摆一次。
    // "复用"这条路上必须显式 show：翻历史回到"还没框"那一步时工具条是被 hide 掉的
    toolMain->show();
    layoutTools();
}

// 一整组工具条：主条（+ 画笔选项）右对齐摞在选区外侧。
// 单根条的规则见 layoutTool()，这里在它之上把整组当成一块来摆 ——
// 因为选区靠近屏幕边缘时得整体翻到上方，不能每根条各判各的。
void WinCap::layoutTools()
{
    // 只有"调整选区"这个阶段归这里管：长图 / 录屏阶段各自的工具条由它们自己摆
    if (stage != CapStage::Adjust) return;

    struct Bar { Ling::WinBase* win; int h; };
    std::vector<Bar> bars;
    if (toolMain) bars.push_back({ toolMain.get(), (int)(toolMain->h + 0.5f) });
    const bool showSub = toolMain && toolSub && !toolMain->curId.empty() && toolSub->hasContent();
    if (showSub) bars.push_back({ toolSub.get(), (int)(toolSub->getDesiredHeight() + 0.5f) });

    // 选区换算到屏幕坐标
    const int ml = x + (int)cutMask->maskRect.left;
    const int mt = y + (int)cutMask->maskRect.top;
    const int mr = x + (int)cutMask->maskRect.right;
    const int mb = y + (int)cutMask->maskRect.bottom;
    RECT maskScrRect{ ml, mt, mr, mb };
    HMONITOR hMon = MonitorFromRect(&maskScrRect, MONITOR_DEFAULTTONEAREST);
    MONITORINFO mi{ sizeof(MONITORINFO) };
    if (!hMon || !GetMonitorInfo(hMon, &mi)) {
        auto [ax, ay, aw, ah] = App::get()->getScreenArea();
        mi.rcWork = RECT{ ax, ay, ax + aw, ay + ah };
    }
    const auto& wa = mi.rcWork;

    const int gap = (int)(cutMask->strokeWidth + 2.f * dpi + 0.5f);  // 与框选边框的间距，同 layoutTool
    const int barGap = (int)(2.f * dpi + 0.5f);                     // 条与条之间的缝
    int totalH{ 0 };
    for (auto& b : bars) totalH += b.h;
    totalH += barGap * (int)(bars.size() - 1);

    const bool fitBelow = (mb + gap + totalH) <= wa.bottom;
    const bool fitAbove = (mt - gap - totalH) >= wa.top;
    int y0{ 0 };
    int rightEdge = mr;
    if (fitBelow) {
        y0 = mb + gap;                       // 选区下方
    }
    else if (fitAbove) {
        y0 = mt - gap - totalH;              // 上方
    }
    else {
        // 上下都不够：盖在选区右下角内部，与右 / 底各留 3*dpi（与 layoutTool 一致）
        const int pad = (int)(3.f * dpi + 0.5f);
        y0 = mb - pad - totalH;
        rightEdge = mr - pad;
    }
    // 兜底：整组不越出所在显示器工作区
    if (y0 + totalH > wa.bottom) y0 = wa.bottom - totalH;
    if (y0 < wa.top) y0 = wa.top;

    int yy = y0;
    for (auto& b : bars) {
        const int bw = (int)(b.win->w + 0.5f);
        int bx = rightEdge - bw;
        if (bx < wa.left) bx = wa.left;
        if (bx + bw > wa.right) bx = wa.right - bw;
        b.win->setPosition(bx, yy);
        yy += b.h + barGap;
    }
    // ToolSub 的位置由它自己按 ToolMain 算 —— 它带一个朝上的小箭头，得贴着主条
    if (showSub) {
        toolSub->updatePosition(wa);
    }
    else if (toolSub) {
        toolSub->hideTools();
    }
}

bool WinCap::isPosInMask(POINT pos) const
{
    if (!cutMask->hasRect()) return false;
    auto& r = cutMask->maskRect;
    return pos.x >= r.left && pos.x < r.right && pos.y >= r.top && pos.y < r.bottom;
}

bool WinCap::enterByArg()
{
    // 目标功能有两个来源：这次截图自己带的（设置页里配的功能热键），以及进程启动时的
    // 命令行 --enter=xxx。前者优先 —— 它是用户刚刚按下的动作，后者只是启动这个进程时的
    // 约定（比如 --enter=tray 起的进程一直待命，之后用户按哪个功能键就该走哪个功能）
    auto val{ enterArg };
    if (val.empty()) {
        auto& args = Ling::App::get()->args;
        auto it = args.find(L"--enter");
        if (it == args.end()) return false;
        val = it->second;
    }
    // 下面这几条路本来都是从工具条上的按钮进的，start* 会检查选区是不是已经定下来了
    stage = CapStage::Adjust;
    refresh();      //收掉放大镜：这几条路都是马上要换阶段或者弹窗，屏幕上不能留着它
    if (val == L"long") startLong();
    else if (val == L"video") startVideo();
    else if (val == L"ocr") startOcr();
    else if (val == L"qr" || val == L"qrcode") startQrcode();
    else if (val == L"pin") startPin();   //等于替用户按住了 Ctrl 框选
    // 值不认识（用户拼错了）：当没给这个参数，照常出工具条。上面那两句白做了，
    // 但调用方接着也是这两句，重复一遍没有副作用
    else return false;
    return true;
}

void WinCap::raiseToolbars()
{
	ToolHost::raiseToolbars();
	// 长图 / 录屏阶段的工具条不在 ToolHost 的成员里（ToolLong / ToolVideo 各自有窗口），
	// 基类那遍顶不到它们，这里补上。见头文件注释：漏了这一步的表现就是
	// "点了录屏，工具条上的按钮全没了，也退不出来"
	raiseTopmost(capLong ? capLong->toolHwnd() : nullptr);
	raiseTopmost(capVideo ? capVideo->toolHwnd() : nullptr);
}

void WinCap::relayoutTool()
{
    if (capLong) capLong->layoutTool();
    else if (capVideo) capVideo->layoutTool();
    else layoutTools();
}

void WinCap::layoutTool(Ling::WinBase* tool)
{
    if (!tool) return;
    const int toolW = (int)(tool->w + 0.5f);
    const int toolH = (int)(tool->h + 0.5f);
    // maskRect 是本窗口的客户区坐标，换算到屏幕坐标
    const int maskLeftScr = x + (int)cutMask->maskRect.left;
    const int maskTopScr = y + (int)cutMask->maskRect.top;
    const int maskRightScr = x + (int)cutMask->maskRect.right;
    const int maskBottomScr = y + (int)cutMask->maskRect.bottom;

      // 用框选区域所在显示器的工作区判断上/下方是否有足够空间
      RECT maskScrRect{ maskLeftScr, maskTopScr, maskRightScr, maskBottomScr };
      HMONITOR hMon = MonitorFromRect(&maskScrRect, MONITOR_DEFAULTTONEAREST);
      MONITORINFO mi{ sizeof(MONITORINFO) };
      // 拿不到显示器信息就退回整个虚拟桌面（与 layoutTools 那边的兜底一致）。
      // 少了这一步，mi.rcWork 会是全 0，下面那几句兜底会把工具条夹到屏幕左上角去
      if (!hMon || !GetMonitorInfo(hMon, &mi)) {
          auto [ax, ay, aw, ah] = App::get()->getScreenArea();
          mi.rcWork = RECT{ ax, ay, ax + aw, ay + ah };
      }

    // 间距按工具条自己所在显示器的缩放算：本窗口铺满整个虚拟桌面，dpi 是系统缩放，
    // 混合缩放的多屏下和选区所在的那块屏不一定是一回事
    const int gap = (int)(cutMask->strokeWidth + 2.f * tool->dpi + 0.5f); // 与框选边框的间距
    const bool fitBelow = (maskBottomScr + gap + toolH) <= mi.rcWork.bottom;
    const bool fitAbove = (maskTopScr - gap - toolH) >= mi.rcWork.top;

    // 工具条右侧与框选区域右侧对齐
    int toolX = maskRightScr - toolW;
    int toolY = 0;
    if (fitBelow) {
        // 右下方
        toolY = maskBottomScr + gap;
    }
    else if (fitAbove) {
        // 右上方
        toolY = maskTopScr - gap - toolH;
    }
    else {
        // 叠加在框选区域右下方内部，与右/底各留 3*dpi
        const int overlapPad = (int)(3.f * tool->dpi + 0.5f);
        toolX = maskRightScr - toolW - overlapPad;
        toolY = maskBottomScr - toolH - overlapPad;
    }

      // 兜底：不越出所在显示器工作区。X 和 Y 都要夹 ——
      // 只夹 X 的话，"叠加在选区内部"那条路算出来的 toolY 一旦越界（选区底边贴近/超出
      // 工作区底边，混合缩放多屏下尤其容易），整根工具条就跑到屏幕外去了，
      // 用户看到的就是"工具条不见了"。
      if (toolX < mi.rcWork.left) toolX = mi.rcWork.left;
      if (toolX + toolW > mi.rcWork.right) toolX = mi.rcWork.right - toolW;
      if (toolY < mi.rcWork.top) toolY = mi.rcWork.top;
      if (toolY + toolH > mi.rcWork.bottom) toolY = mi.rcWork.bottom - toolH;
      tool->setPosition(toolX, toolY);
}

void WinCap::enterLiveStage()
{
    // 底图是拖框那一刻的静态截图，从这里开始不能再画它 ——
    // 否则录屏和滚动截图从屏幕上拿到的都是这张死图。只留遮罩，选区内是透明的洞。
    hideScreenImg = true;
    // 尺寸标签放不下时会折回选区内部（全屏必然如此），那就会被录进去 / 滚进长图。
    // 选区这时已经定死了，标签也没什么可看的，直接不画 —— 这样选区内就真的什么都不画了，
    // 不必再拿 WDA_EXCLUDEFROMCAPTURE 去摘整块屏幕大小的宿主窗口
    cutMask->hideLabel = true;
    // 工具条收掉：从这里开始鼠标要留给被录 / 被滚的那个窗口，
    // 屏幕上能看见的东西也都会被录进去或滚进长图
    if (toolMain) {
        toolMain->cancelSelect();
        toolMain->hide();
    }
    if (toolSub) toolSub->hideTools();
    // 原来的 WinLong / WinVideo 建窗口时就是 topmost，这里补上
    SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE);
    refresh();
}

// 工具条上"只有截图那一根才有"的功能按钮落到这里。start* 自己会检查选区定下来没有，
// 所以这里不做额外判断 —— 没框好时它们本来就是什么都不做
void WinCap::onCapAction(const std::wstring& id)
{
    if (id == L"long") startLong();
    else if (id == L"video") startVideo();
    else if (id == L"ocr") startOcr();
    else if (id == L"qrcode") startQrcode();
}

void WinCap::startPin()
{
    // 把选区（含标注）合成出来，再原位贴成一个贴图窗口。
    // 以前是让 WinPin 回头来取 getCutImg()，现在走像素 —— 因为出去的那张图要带上标注
    std::vector<BYTE> pixels;
    int cw{ 0 }, ch{ 0 };
    if (!getCutPixels(pixels, cw, ch)) return;
    auto& maskRect = cutMask->maskRect;
    WinPin::initFromData(int(maskRect.left) + x, int(maskRect.top) + y, cw, ch, pixels, 1.f, false);
    close();
}

void WinCap::startLong()
{
    if (stage != CapStage::Adjust || !cutMask->hasRect()) return;
    stage = CapStage::Long;
    enterLiveStage();
    // 选区已经定了，接下来光标移进选区会出现"开始"按钮，点一下才真的开始滚
    capLong = std::make_unique<CapLong>(this);
}

void WinCap::startVideo()
{
    if (stage != CapStage::Adjust || !cutMask->hasRect()) return;
    stage = CapStage::Video;
    enterLiveStage();
    capVideo = std::make_unique<CapVideo>(this);
    // 工具条原地换成 ToolVideo
    capVideo->makeTool();
}

void WinCap::startMp4(bool useSpeaker, bool useMic)
{
    if (capVideo) capVideo->startMp4(useSpeaker, useMic);
}

std::wstring WinCap::stopRecord()
{
    return capVideo ? capVideo->stop() : L"";
}

void WinCap::layoutLongTool()
{
    if (capLong) capLong->layoutTool();
}

void WinCap::longPin()
{
    if (capLong) capLong->pin();
}

bool WinCap::longSaveToFile()
{
    return capLong ? capLong->saveToFile() : false;
}

void WinCap::longCopyToClipboard()
{
    if (capLong) capLong->copyToClipboard();
}

void WinCap::hollowWin()
{
    HRGN rgn1 = CreateRectRgn(0, 0, (int)w, (int)h);
    auto& r = cutMask->maskRect;
    HRGN rgn2 = CreateRectRgn((int)r.left, (int)r.top, (int)r.right, (int)r.bottom);
    CombineRgn(rgn1, rgn1, rgn2, RGN_DIFF);
    DeleteObject(rgn2);
    if (SetWindowRgn(hwnd, rgn1, TRUE) == 0) {
        DeleteObject(rgn1);
    }
}

void WinCap::restoreWin()
{
    SetWindowRgn(hwnd, NULL, TRUE);
}

void WinCap::setMouseTransparent(bool transparent)
{
    isMouseTransparent = transparent;
    if (!hwnd) return;
    LONG_PTR exStyle = GetWindowLongPtr(hwnd, GWL_EXSTYLE);
    if (transparent) {
        exStyle |= WS_EX_LAYERED;
        exStyle |= WS_EX_TRANSPARENT;
        if (GetCapture() == hwnd) {
            ReleaseCapture();
        }
        isPress = false;
        SetLayeredWindowAttributes(hwnd, 0, 255, LWA_ALPHA);
    }
    else {
        exStyle &= ~WS_EX_TRANSPARENT;
        exStyle &= ~WS_EX_LAYERED;
    }
    SetWindowLongPtr(hwnd, GWL_EXSTYLE, exStyle);
    SetWindowPos(hwnd, nullptr, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED);
}

// 文字识别改成程序内自己做（Windows.Media.Ocr）：
// 把选区（含标注）贴成一个贴图窗口，并让它建好就自动识别一遍，
// 用户在那个窗口里像在编辑器里那样拖选文字、Ctrl+C 复制。
// 与 startPin 一样要先建 WinPin 再关自己
void WinCap::startOcr()
{
    std::vector<BYTE> pixels;
    int cw{ 0 }, ch{ 0 };
    if (!getCutPixels(pixels, cw, ch)) return;
    auto& maskRect = cutMask->maskRect;
    WinPin::initFromData(int(maskRect.left) + x, int(maskRect.top) + y, cw, ch, pixels, 1.f, true);
    close();
}

// 截图过程中按贴图热键（F3）：立刻收尾 —— 截图 → 存进剪贴板 → 贴到桌面上。
// 与"框完点钉住"的差别只是顺手复制了一份，方便马上粘到别处。
// 还没框出选区时返回 false，让调用方（热键那一侧）去决定要不要提示
bool WinCap::finishToPin()
{
    if (!cutMask->hasRect()) return false;
    std::vector<BYTE> pixels;
    int cw{ 0 }, ch{ 0 };
    if (!getCutPixels(pixels, cw, ch)) return false;   // 顺带记下"最近一次截图"
    Util::saveToClipboard(cw, ch, pixels.data());
    auto& maskRect = cutMask->maskRect;
    // ocr = true：这条路的下一步多半就是取字，贴出来就直接能选
    WinPin::initFromData(int(maskRect.left) + x, int(maskRect.top) + y, cw, ch, pixels, 1.f, true);
    close();
    return true;
}

void WinCap::startQrcode()
{
    std::vector<BYTE> pixels;
    int cw{ 0 }, ch{ 0 };
    if (!getCutPixels(pixels, cw, ch)) return;
    auto text = Util::decodeQrCode(cw, ch, pixels.data());
    // 不弹框。认出来就：内容静默写进剪切板 -> **立刻退出截图状态** -> 让那句"已复制"以
    // 独立小窗（Toast）的形式在原地再飘 2 秒。扫个码而已，不用自己按 ESC 或点关闭。
    // 没认出来就留在原地，方便调整选区重扫 —— 那种情况下自动退出反而碍事
    if (text.empty()) {
        showTip(Lang::get(L"cap.qrcodeEmpty"));
    }
    else {
        Ling::Util::setTextToClipboard(text);
        auto& mr = cutMask->maskRect;
        // 用完即走模式不弹提示：那种用法下 WinCap::onClosed 会立刻 quit(0)，
        // 提示窗刚建出来就被进程带走，只会闪一下 —— 脚本要的是剪切板里的结果，不是看提示
        if (Ling::App::get()->args[L"--auto-quit"] != L"true") {
            Toast::showAt(Lang::get(L"cap.qrcodeCopied"),
                (mr.left + mr.right) / 2, (mr.top + mr.bottom) / 2, dpi);
        }
        close();
    }
}

void WinCap::saveToFile()
{
    std::vector<BYTE> pixels;
    int cw{ 0 }, ch{ 0 };
    if (!getCutPixels(pixels, cw, ch)) return;
    // 另存为对话框是 WinCap 的附属窗口，而 WinCap 自己不是 topmost，对话框也就待在普通层；
    // 工具条却是 topmost 的，topmost 那一层永远盖在普通层之上，于是工具条浮在对话框上面。
    // 所以开对话框前先把工具条降回普通层，关掉之后再压回去
    auto setToolTopmost = [this](bool topmost) {
        // 写死成 WinBase* 的数组：两个都是派生类指针，直接放 initializer_list 推不出公共类型
        Ling::WinBase* tools[] = { toolMain.get(), toolSub.get() };
        for (auto t : tools) {
            if (!t || !t->hwnd) continue;
            SetWindowPos(t->hwnd, topmost ? HWND_TOPMOST : HWND_NOTOPMOST,
                0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE);
        }
    };
    // 快速保存不弹框，也就不用降层 —— 降层只为绕开"对话框在普通层、工具条在 topmost"这件事
    const bool quick = Setting::get()->getQuickSave();
    setToolTopmost(quick);
    auto path = Util::resolveSavePath(L"png", hwnd);
    // 对话框关掉后本窗口会被激活（会盖住降下来的工具条），所以只要还留在截图里，
    // 工具条就得重新压回最上层
    if (path.empty()) { //用户取消了
        setToolTopmost(true);
        return;
    }
    if (Util::saveToFile(path, cw, ch, pixels.data())) {
        close();
    }
    else {
        setToolTopmost(true);
    }
}

void WinCap::copyToClipboard()
{
    std::vector<BYTE> pixels;
    int cw{ 0 }, ch{ 0 };
    if (!getCutPixels(pixels, cw, ch)) return;
    Util::saveToClipboard(cw, ch, pixels.data());
    close();
}

// 把选区那块**合成**出像素：底图之上盖一层未撤销的标注。
// 不用直接 CopyFromBitmap 裁底图 —— 那样标注就丢了；标注是画在底图上的，
// 出去的那张图（复制 / 存盘 / 钉住 / 识别）必须是它俩合起来的样子。
// 合成用离屏 target，之后拷到 CPU_READ 位图再读回来（GPU 位图不能直接 Map）。
bool WinCap::getCutPixels(std::vector<BYTE>& pixels, int& cw, int& ch, bool remember)
{
    if (!screenImg || !cutMask->hasRect()) return false;
    auto& maskRect = cutMask->maskRect;
    const UINT32 cutW = (UINT32)(maskRect.right - maskRect.left);
    const UINT32 cutH = (UINT32)(maskRect.bottom - maskRect.top);
    if (cutW == 0 || cutH == 0) return false;
    // 编辑中的文字是 TextBox 自己那层画的，进不了下面这个离屏 target。先收尾，
    // 把它交回 ShapeText 自己画，出去的那张图才有这行字
    if (editingText) editingText->finishEdit();

    auto ctx = Ling::D2D::get()->deviceContext.Get();
    D2D1_BITMAP_PROPERTIES1 targetProps{
        .pixelFormat{ screenImg->GetPixelFormat() },
        .dpiX{ 96.0f }, .dpiY{ 96.0f },
        .bitmapOptions{ D2D1_BITMAP_OPTIONS_TARGET }
    };
    ComPtr<ID2D1Bitmap1> targetBmp;
    if (FAILED(ctx->CreateBitmap(D2D1::SizeU(cutW, cutH), nullptr, 0, &targetProps, targetBmp.GetAddressOf()))) return false;

    ctx->SetTarget(targetBmp.Get());
    ctx->SetTransform(D2D1::Matrix3x2F::Identity());
    ctx->BeginDraw();
    ctx->Clear(D2D1::ColorF(0, 0.0f));
    // 底图上选区那一块搬到 (0,0)
    ctx->DrawBitmap(screenImg.Get(),
        D2D1::RectF(0.f, 0.f, (float)cutW, (float)cutH),
        1.f, D2D1_BITMAP_INTERPOLATION_MODE_LINEAR,
        D2D1::RectF(maskRect.left, maskRect.top, maskRect.right, maskRect.bottom));
    // 标注是按桌面物理像素存的，平移到选区原点再画
    ctx->SetTransform(D2D1::Matrix3x2F::Translation(-maskRect.left, -maskRect.top));
    if (history) {
        for (auto& shape : history->shapes) {
            if (!shape->isUndo) shape->paint(ctx);
        }
    }
    ctx->SetTransform(D2D1::Matrix3x2F::Identity());
    auto hr = ctx->EndDraw();
    // 解绑，下面 CopyFromBitmap 才能把它当 source 读
    ctx->SetTarget(nullptr);
    if (FAILED(hr)) return false;

    D2D1_BITMAP_PROPERTIES1 prop{
        .pixelFormat{ targetBmp->GetPixelFormat() },
        .dpiX{ 96.0f }, .dpiY{ 96.0f },
        .bitmapOptions{ D2D1_BITMAP_OPTIONS_CPU_READ | D2D1_BITMAP_OPTIONS_CANNOT_DRAW }
    };
    ComPtr<ID2D1Bitmap1> cpuBmp;
    hr = ctx->CreateBitmap(D2D1::SizeU(cutW, cutH), nullptr, 0, &prop, cpuBmp.GetAddressOf());
    if (FAILED(hr)) return false;
    if (FAILED(cpuBmp->CopyFromBitmap(nullptr, targetBmp.Get(), nullptr))) return false;
    D2D1_MAPPED_RECT mapped{};
    if (FAILED(cpuBmp->Map(D2D1_MAP_OPTIONS_READ, &mapped))) return false;
    // mapped.pitch 按 GPU 行对齐，可能大于 cutW*4；剪切板和 WIC 都要求紧凑步长，逐行紧缩
    const UINT32 rowBytes = cutW * 4;
    pixels.resize((size_t)rowBytes * cutH);
    for (UINT32 row = 0; row < cutH; row++)
    {
        auto dst = pixels.data() + (size_t)row * rowBytes;
        CopyMemory(dst, mapped.bits + (size_t)row * mapped.pitch, rowBytes);
        // 底图是 GDI 抓来的，alpha 全 0（它自己是 ALPHA_MODE_IGNORE 所以无所谓），
        // 但 PNG 和剪切板会当真，这里统一按不透明补上
        for (UINT32 i = 3; i < rowBytes; i += 4) dst[i] = 255;
    }
    cpuBmp->Unmap();
    cw = (int)cutW;
    ch = (int)cutH;
    // 顺手把这次的结果记成"最近一次截图"：贴图（F3）取的就是它，与剪贴板无关。
    // 记的是选区在**屏幕**上的位置，贴图据此回到原位
    if (remember) {
        Util::saveLastCapture(cw, ch, (int)maskRect.left + x, (int)maskRect.top + y, pixels.data());
        // 除了"最近一次"，再往截图历史里记一条（整屏画面 + 这个框），
        // 之后按 ← 能把这张翻出来重看、重裁
        saveShotToHistory();
    }
    return true;
}

// ———————————————————— 截图历史 ————————————————————

void WinCap::saveShotToHistory()
{
    // 关掉历史（保留天数 0）或这轮没抓到整屏图时，什么都不做
    if (Setting::get()->getHistoryDays() <= 0) return;
    if (screenRaw.empty() || !cutMask->hasRect()) return;
    if (stage != CapStage::Adjust) return;   // 长图/录屏阶段没有"截图框"这回事

    // 框存屏幕坐标（贴图那份 last.bin 也是这么记的）
    RECT maskScr{
        x + (LONG)cutMask->maskRect.left,  y + (LONG)cutMask->maskRect.top,
        x + (LONG)cutMask->maskRect.right, y + (LONG)cutMask->maskRect.bottom
    };
    if (!shotFilesLoaded) {
        shotFilesLoaded = true;
        for (auto& shot : Util::listShots()) shotFiles.push_back(shot.path);
    }
    if (!curShotPath.empty()) {
        // 这一张已经记过了（改完框又复制了一次之类）：只把框更新回去，别多记一条
        Util::patchShotRect(curShotPath, maskScr);
        return;
    }
    auto path = Util::makeShotPath();
    if (path.empty()) return;
    curShotPath = path;
    shotFiles.insert(shotFiles.begin(), path);
    shotIndex = 0;   // 当前这张就是最新那一条
    // 落盘丢到后台线程：整屏 PNG 编码一百多毫秒，而这里是"复制 / 保存 / 贴图"的必经之路，
    // 让用户等它不合适。线程只碰自己那份像素副本和路径，不碰窗口状态
    std::vector<BYTE> pixels = screenRaw;   // 拷一份给它（14MB 级，约 5ms）
    auto maskCopy = maskScr;
    const int shotX{ x }, shotY{ y }, shotW{ (int)w }, shotH{ (int)h };
    std::thread([path, shotX, shotY, shotW, shotH, pixels = std::move(pixels), maskCopy]() {
        Util::writeShot(path, shotX, shotY, shotW, shotH, pixels, maskCopy);
    }).detach();
    // 顺手清掉过期的
    Util::pruneShots(Setting::get()->getHistoryDays());
}

bool WinCap::canGoPrevShot()
{
    // 刚按 F1、还没框的时候也要能翻（用户在截图态一进来就想看上一张），所以不要求 Adjust
    if (!historyNavStage()) return false;
    if (!shotFilesLoaded) {
        shotFilesLoaded = true;
        for (auto& shot : Util::listShots()) shotFiles.push_back(shot.path);
    }
    return (size_t)(shotIndex + 1) < shotFiles.size();
}

bool WinCap::canGoNextShot()
{
    // 只有"正在看某条历史"时才谈得上往后翻。
    // shotIndex 0 = 最新那条历史，再往后一步就回到"这次截图"本身（shotIndex = -1），
    // 所以这里是 >= 0 而不是 > 0 —— 少这一格就会出现"按了 , 之后按 . 回不到截图状态"
    return historyNavStage() && shotIndex >= 0;
}

bool WinCap::applyShot(const std::wstring& path)
{
    std::vector<BYTE> pixels;
    int iw{ 0 }, ih{ 0 }, sx{ 0 }, sy{ 0 };
    RECT maskScr{};
    if (!Util::loadShot(path, pixels, iw, ih, sx, sy, maskScr)) return false;
    auto ctx = Ling::D2D::get()->deviceContext.Get();
    D2D1_BITMAP_PROPERTIES1 props{
        .pixelFormat{ D2D1::PixelFormat(DXGI_FORMAT_B8G8R8A8_UNORM, D2D1_ALPHA_MODE_IGNORE) },
        .dpiX{ 96.0f }, .dpiY{ 96.0f }, .bitmapOptions{ D2D1_BITMAP_OPTIONS_NONE }
    };
    ComPtr<ID2D1Bitmap1> bmp;
    if (FAILED(ctx->CreateBitmap(D2D1::SizeU((UINT)iw, (UINT)ih), pixels.data(), iw * 4,
        props, bmp.GetAddressOf()))) return false;

    // 换底图。hideScreenImg 要显式复位：万一之前进过长图/录屏阶段，它是 true
    screenImg = bmp;
    hideScreenImg = false;

    // 框存的是屏幕坐标，换成客户区坐标。换过分辨率/显示器时老历史的整屏尺寸可能和当前
    // 窗口对不上，那就把它夹进窗口 —— 图照样铺（左上角对齐），别让一条老历史卡住流程
    auto clamp = [](float v, float lo, float hi) { return v < lo ? lo : (v > hi ? hi : v); };
    const float maxX{ (float)w }, maxY{ (float)h };
    D2D1_RECT_F r{
        clamp((float)(maskScr.left - x), 0.f, maxX),
        clamp((float)(maskScr.top - y), 0.f, maxY),
        clamp((float)(maskScr.right - x), 0.f, maxX),
        clamp((float)(maskScr.bottom - y), 0.f, maxY)
    };
    // 夹完之后可能退化成一条线甚至反向，保证还是个能用的矩形（CutMask 的最小边长是 4）
    if (r.right - r.left < 4.f) r.right = std::min(maxX, r.left + 4.f);
    if (r.bottom - r.top < 4.f) r.bottom = std::min(maxY, r.top + 4.f);
    cutMask->maskRect = r;
    cutMask->hideLabel = false;

    // 画布上原来的标注属于上一张，不跟着过来（历史文件里也没有存标注）。
    // 悬停/拖动指针必须先摘掉，否则指着刚被销毁的图形
    if (history) history->shapes.clear();
    shapeHover = nullptr;
    newShape = nullptr;   // "正在画的那一笔"也指着 shapes 里的对象，一起摘掉

    // 关键：记下"现在这张画布对应哪条历史"。漏掉它的话，之后改完框再翻走时
    // patch 会打在上一条（curShotPath 还指着旧值）上，这一条的框就白改了
    curShotPath = path;

    // 回到"框选好了、等下一步"的状态：工具条露出来，光标进选区就能继续调。
    // ⚠ 从 Select 阶段（刚按 F1、还没框）翻进来时工具条**还没建过** —— 它是切到 Adjust
    // 时才由 onUp 建的。所以这里必须走一次 makeTools（它认得"已经建了就复用"）
    stage = CapStage::Adjust;
    makeTools();
    // ⚠ 位置必须在这里再摆一次：翻页时工具条是**复用**的，而 layoutTools 只在
    // makeTools 真的新建窗口那条路上被调用过 —— 不补这一句，工具条会留在上一条选区的
    // 位置，要等下一次鼠标移动（onMove 里也调 layoutTools）才跟过去。
    // 用户看到的"按了 , 工具条不跟过去、点一下才过去"就是这个
    layoutTools();
    if (toolMain) toolMain->show();
    raiseToolbars();
    refresh();
    return true;
}

void WinCap::goPrevShot()
{
    // 第一次从"这次截图"翻出去之前，先把它的状态记下来，这样 . 能翻回来。
    // 必须记在 saveShotToHistory 之前：那个函数在 Select 阶段是空操作（没有选区），
    // 光靠历史文件还原不了"还没框"这个状态
    if (shotIndex < 0) {
        liveStage = stage;
        liveMaskRect = cutMask->maskRect;
    }
    // 先把当前这张的状态记进历史（头一次按 ← 时它还没被记过），
    // 这样往回翻回来，框还是刚改过的样子
    saveShotToHistory();
    const int next = shotIndex + 1;
    if (next < 0 || (size_t)next >= shotFiles.size()) return;
    if (!applyShot(shotFiles[next])) return;
    shotIndex = next;
}

void WinCap::goNextShot()
{
    if (shotIndex < 0) return;   // 已经在"这次截图"上了，没有更前的可翻
    saveShotToHistory();
    const int next = shotIndex - 1;
    if (next < 0) {
        // 最新那条再往前一步 = 回到这次截图本身（含"还没框"那个状态）
        restoreLiveShot();
        return;
    }
    if ((size_t)next >= shotFiles.size()) return;
    if (!applyShot(shotFiles[next])) return;
    shotIndex = next;
}

bool WinCap::restoreLiveShot()
{
    if (screenRaw.empty() || w <= 0 || h <= 0) return false;
    auto ctx = Ling::D2D::get()->deviceContext.Get();
    D2D1_BITMAP_PROPERTIES1 props{
        .pixelFormat{ D2D1::PixelFormat(DXGI_FORMAT_B8G8R8A8_UNORM, D2D1_ALPHA_MODE_IGNORE) },
        .dpiX{ 96.0f }, .dpiY{ 96.0f }, .bitmapOptions{ D2D1_BITMAP_OPTIONS_NONE }
    };
    ComPtr<ID2D1Bitmap1> bmp;
    // 直接从 F1 留下的整屏原始像素重建，不用再抓一次屏（那样画面早变了）
    if (FAILED(ctx->CreateBitmap(D2D1::SizeU((UINT)w, (UINT)h),
        screenRaw.data(), (UINT)w * 4, props, bmp.GetAddressOf()))) return false;

    screenImg = bmp;
    hideScreenImg = false;

    // 翻出去看那张上的标注不跟着回来（历史文件里也没存标注）
    if (history) history->shapes.clear();
    shapeHover = nullptr;
    newShape = nullptr;
    // "这次截图"在历史里的代表就是最新那条（goPrevShot 离开时记下的）。接着用它，
    // 来回翻几次也不会多出重复条目。Select 阶段存不了这条（没选区），所以是空
    curShotPath = (liveStage == CapStage::Adjust && !shotFiles.empty())
        ? shotFiles[0] : std::wstring{};

    stage = liveStage;
    cutMask->hideLabel = false;
    if (liveStage == CapStage::Select) {
        // 还原成"还没框"的样子：没有选区、没有工具条，光标回十字。
        // 工具条藏起来而不是销毁 —— 下一次框完（onUp）会再 makeTools，那个函数
        // 现在无论是否新建都会 show()，所以藏过也能回来
        cutMask->maskRect = D2D1::RectF();
        if (toolSub) toolSub->hideTools();
        if (toolMain) toolMain->hide();
    }
    else {
        cutMask->maskRect = liveMaskRect;
        makeTools();       // 里面会 show + 摆位置
        raiseToolbars();
    }
    shotIndex = -1;
    setCursor();
    refresh();
    return true;
}
