#pragma once
#include <thread>
#include <include/Ling.h>

// 录制参数只在 CapVideo.cpp 里构造，头文件用前向声明就够 ——
// VideoMp4.hpp 会拉进整套 MediaFoundation 头，不该让 ToolVideo / WinCap 这些
// 只是引用 CapVideo 的编译单元都跟着吃一遍。
namespace VideoMp4 { struct DESKTOPCAPTUREPARAMS; }

class WinCap;
class ToolVideo;
// 屏幕录制。区域已经由 WinCap 定好了，所以它不是窗口，只管工具条和编码线程。
class CapVideo
{
public:
	CapVideo(WinCap* win);
	~CapVideo();
	// 工具条原地换成 ToolVideo
	void makeTool();
	// 工具条的窗口句柄（还没建时为空）。宿主要靠它把工具条顶回 topmost 带最上面 ——
	// 见 WinCap::raiseToolbars 的注释。ToolVideo 只前向声明，实现放 .cpp 里
	HWND toolHwnd() const;
	// ToolVideo 的摆放规则（就是 WinCap 那套通用规则）。建窗口时走一遍，
	// 工具条或宿主的 DPI 变了之后回头再走一遍
	void layoutTool();
	// 宿主窗口要销毁了：停掉录制、收掉工具条
	void dispose();
	bool isRecording() const;
	void startMp4(bool useSpeaker, bool useMic);
	// 停止录制并返回录好的临时文件路径；没在录制时返回空串
	std::wstring stop();
	// Ctrl+S / Ctrl+C 转给工具条上的"存文件" / "存剪切板"；没在录制时返回 false
	bool onSaveKey(bool toClipboard);
private:
	WinCap* win;
	std::unique_ptr<ToolVideo> tool;
	std::unique_ptr<VideoMp4::DESKTOPCAPTUREPARAMS> mp4Param;
	std::jthread captureThread;
};
