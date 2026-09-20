#include "pch.h"

#include "App.h"
#include "Setting.h"
#include "Tray.h"
#include "Lang.h"
#include "Update.h"
#include "./Win/WinCap.h"
#include "./Win/WinPin.h"
#include "./Win/WinSetting.h"

std::unique_ptr<App> app;

namespace
{
    // 让图形设备常驻。
    // D2D 是在"最后一个 Ling 窗口关掉"时被释放的（Ling 的 ~WinBase 按 windows 是否为空判断），
    // 而本程序常态就是零窗口（只挂个托盘），于是**每按一次 F1 都要重建一次 D3D11 + D2D 工厂**
    // —— 实测 ~250ms，这才是"按 F1 卡一下"的真正来源（不是只有第一次，是每一次）。
    // 留一个隐藏窗口占着那个列表，设备就一直活着。
    // 它从不显示：CutMask 枚举窗口时只看可见窗口，会跳过它；
    // 而那个列表本身也只被这一处判断用到，所以不影响任何其它流程。
    class DeviceKeepAlive : public Ling::WinBase
    {
    public:
        void onCreated() override {}
    };

    // 进程存活期间一直留着，退出时不必回收（那时 COM/D2D 都已经拆了）
    DeviceKeepAlive* g_deviceKeepAlive{ nullptr };
}


App::~App()
{
}

void App::init()
{
    auto ptr = new App();
    app.reset(ptr);
}

void App::dispose()
{
    // 窗口对象是文件级静态变量，交给静态析构就晚了（那时 CoUninitialize 已经跑完），
    // 所以趁这里把还开着的窗口先放掉
    WinPin::dispose();
    WinCap::dispose();
    WinSetting::dispose();
    // 占位窗口也放掉：它一析构、列表就空了，D2D 随之释放（此时已没有别的窗口）
    delete g_deviceKeepAlive;
    g_deviceKeepAlive = nullptr;
    Lang::dispose();
    Setting::dispose();
    app.reset();
}

App* App::get()
{
    return app.get();
}

void App::takeScreenShot(int x, int y, int w, int h, ID2D1Bitmap1** img, std::vector<BYTE>* rawOut)
{
    HDC hScreen = GetDC(NULL);
    // 直接用 DIBSection：BitBlt 会把像素写进我们拿到的内存，省掉原来 CreateCompatibleBitmap
    // + GetDIBits 那一趟整屏回读（还要先分配并清零一个 w*h*4 的 vector，都是白花的）
    BITMAPINFO bmi{};
    bmi.bmiHeader.biSize = sizeof(BITMAPINFOHEADER);
    bmi.bmiHeader.biWidth = w;
    bmi.bmiHeader.biHeight = -h;   // 负数 = 自上而下，与 D2D 的行序一致
    bmi.bmiHeader.biPlanes = 1;
    bmi.bmiHeader.biBitCount = 32;
    bmi.bmiHeader.biCompression = BI_RGB;
    void* bits{ nullptr };
    HBITMAP hBitmap = CreateDIBSection(hScreen, &bmi, DIB_RGB_COLORS, &bits, nullptr, 0);
    if (!hBitmap || !bits) {
        ReleaseDC(NULL, hScreen);
        return;
    }
    HDC hDC = CreateCompatibleDC(hScreen);
    auto oldObj = SelectObject(hDC, hBitmap);
    BitBlt(hDC, 0, 0, w, h, hScreen, x, y, SRCCOPY);
    // GDI 的绘制是批处理的，读 bits 之前必须让它落盘
    GdiFlush();
    SelectObject(hDC, oldObj);
    DeleteDC(hDC);
    ReleaseDC(NULL, hScreen);
    D2D1_BITMAP_PROPERTIES1 props = {
       .pixelFormat{D2D1::PixelFormat(DXGI_FORMAT_B8G8R8A8_UNORM, D2D1_ALPHA_MODE_IGNORE)},
       .dpiX{96.0f}, .dpiY{96.0f}, .bitmapOptions{D2D1_BITMAP_OPTIONS_NONE}
    };
    // 截图历史要的那份"整屏原图"：bits 就是干净的屏幕像素（还没被任何遮罩/标注污染），
    // 直接拷一份，省得以后再从 D2D 位图上回读
    if (rawOut) {
        rawOut->resize((size_t)w * h * 4);
        CopyMemory(rawOut->data(), bits, rawOut->size());
    }
    auto d2d = Ling::D2D::get();
    d2d->deviceContext->CreateBitmap(D2D1::SizeU(w, h), bits, w * 4, props, img);
    DeleteObject(hBitmap);
}

std::tuple<int, int, int, int> App::getScreenArea()
{
	return std::make_tuple(GetSystemMetrics(SM_XVIRTUALSCREEN), 
        GetSystemMetrics(SM_YVIRTUALSCREEN), 
        GetSystemMetrics(SM_CXVIRTUALSCREEN), 
        GetSystemMetrics(SM_CYVIRTUALSCREEN));
}

void App::excludeFromCapture(HWND hwnd)
{
    if (!hwnd) return;
    // 老系统上这个调用不但不失败，还会把窗口变成捕获画面里的一整块黑（实测 build 18363：
    // 返回 TRUE，读回来的 affinity 就是 0x11 —— 内核照存，可那会儿的 DWM 只认"非零即
    // 受保护内容"，一律涂黑）。所以必须自己拦住，让老系统退回"照旧被录进去"。
    // GetVersionEx 会被兼容性清单骗，只有 RtlGetVersion 给的是真版本号
    static const bool supported = []() {
        OSVERSIONINFOW vi{ sizeof(vi) };
        auto rtlGetVersion = (LONG(WINAPI*)(OSVERSIONINFOW*))GetProcAddress(
            GetModuleHandleW(L"ntdll.dll"), "RtlGetVersion");
        return rtlGetVersion && rtlGetVersion(&vi) == 0 && vi.dwBuildNumber >= 19041;
    }();
    if (!supported) return;
    SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE);
}

App::App()
{
    // Ling 的 init 不接受参数：appID 由 App 自己在构造里生成（Ling_XXXXXX，见 Ling 的
    // COMPILE_TIME_RAND_STR），并顺手调 SetCurrentProcessExplicitAppUserModelID。
    // 原来这里传的 L"ScreenCapture" 是更早那版 Ling 的写法，公开 master 上已经没有这个参数了
    Ling::init();
    auto app = Ling::App::get();
    app->initArgs();
    Ling::D2D::addFonts({ L"icon.ttf" });
    // 录制中直接退出会让编码线程和 D3D 设备一起卡住，退出前先把录制停掉
    app->onBeforeQuit.add([]() { WinCap::stopIfRecording(); });
    Setting::init();
    Lang::init();
    if (app->args[L"--auto-quit"] == L"true") {
        WinCap::init();
    }
    else {
        bool flag = app->refuseSecondInstance();
        if (flag) return;
        Tray::init();
		// 启动后只挂个托盘图标待命，**不自动进截图模式** —— 用户按 F1 才截。
		// 开机自启、--enter=tray（升级完重启新版本走的就是它）也走同一条路：
		// 这条路上一个窗口都不建，图形设备也就根本不会创建
		//
		// 先占住一个隐藏窗口，让图形设备不被回收（见 DeviceKeepAlive 的注释），
		// 再在消息循环起来之后补一次预热：托盘图标先出来，设备紧接着在空闲时建好，
		// 之后每次 F1 就只剩抓屏那几十毫秒了。
		// 预热必须走 dq（= UI 线程）—— D2D 工厂是 SINGLE_THREADED 的，换线程建出来也不能用
		g_deviceKeepAlive = new DeviceKeepAlive();
		g_deviceKeepAlive->createNativeWindow(WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE, WS_POPUP);
		app->dq.TryEnqueue([]() { Ling::D2D::get(); });
        Update::checkLater();
    }
}
